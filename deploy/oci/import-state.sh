#!/usr/bin/env bash
set -euo pipefail

bundle=${1:?Usage: import-state.sh BUNDLE_DIR ENV_FILE}
env_file=${2:?Usage: import-state.sh BUNDLE_DIR ENV_FILE}
root=$(cd "$(dirname "$0")/../.." && pwd)
state=${MAUSAM_STATE_DIR:-/srv/mausamsetu/state}
project=${MAUSAM_COMPOSE_PROJECT:-mausamsetu-oci}

[[ -f "$bundle/manifest.json" && -f "$bundle/mausam.dump" ]] || {
  echo "Migration bundle is incomplete" >&2; exit 1;
}
[[ -f "$env_file" ]] || { echo "Environment file missing" >&2; exit 1; }

python3 - "$bundle" <<'PY'
import hashlib,json,sys
from pathlib import Path
folder=Path(sys.argv[1]); manifest=json.loads((folder/"manifest.json").read_text())
for name,meta in manifest["files"].items():
    path=folder/name
    if not path.is_file(): raise SystemExit(f"Missing {name}")
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    if h.hexdigest()!=meta["sha256"]: raise SystemExit(f"Checksum failed: {name}")
print("Migration checksums verified.")
PY

extract() {
  local archive=$1 destination=$2 owner=$3 mode=$4
  [[ -f "$bundle/$archive" ]] || return 0
  sudo install -d -o "$owner" -g "$owner" -m "$mode" "$destination"
  if [[ -n "$(sudo find "$destination" -mindepth 1 -maxdepth 1 -print -quit)" && "${FORCE_IMPORT:-0}" != "1" ]]; then
    echo "$destination is not empty; set FORCE_IMPORT=1 only for intentional replacement" >&2
    exit 1
  fi
  sudo tar --numeric-owner -xzf "$bundle/$archive" -C "$destination"
}

extract forecast-data.tgz "$state/forecast" 10001 0700
extract public-products.tgz "$state/public" 10001 0755
extract run-backups.tgz "$state/backups" 10001 0700
extract provider-cache.tgz "$state/cache" 10001 0700
sudo install -d -o 999 -g 999 -m 0700 "$state/postgres"

compose=(docker compose --env-file "$env_file" -p "$project"
  -f "$root/docker-compose.yml"
  -f "$root/docker-compose.runtime.yml"
  -f "$root/docker-compose.oci.yml")

"${compose[@]}" up -d --build postgres
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T postgres pg_isready -U mausam -d mausam >/dev/null 2>&1; then break; fi
  sleep 2
done
"${compose[@]}" exec -T postgres pg_isready -U mausam -d mausam >/dev/null
"${compose[@]}" exec -T postgres \
  pg_restore -U mausam -d mausam --no-owner --no-privileges < "$bundle/mausam.dump"

"${compose[@]}" up -d --build
echo "Waiting for API and web health..."
for _ in $(seq 1 90); do
  api=0; web=0
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && api=1 || true
  curl -fsS http://127.0.0.1:4173/api/runtime >/dev/null 2>&1 && web=1 || true
  [[ "$api" == 1 && "$web" == 1 ]] && break
  sleep 2
done

curl -fsS http://127.0.0.1:8000/public/status
echo
"${compose[@]}" ps
echo "OCI research deployment restored. Do not stop the Mac collectors yet."

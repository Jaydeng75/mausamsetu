#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out=${1:-"${MAUSAM_MIGRATION_OUT:-$HOME/mausamsetu-migration}/$stamp"}
mkdir -p "$out"
out=$(cd "$out" && pwd)

project=${MAUSAM_COMPOSE_PROJECT:-mausamsetu-audit}
for c in api postgres ingest-worker rain-worker imd-gauge-worker; do
  docker inspect "$project-$c-1" >/dev/null
done

git -C "$root" diff --quiet
git -C "$root" diff --cached --quiet

writers=("$project-ingest-worker-1" "$project-rain-worker-1" "$project-imd-gauge-worker-1" "$project-replay-worker-1" "$project-db-backup-1")
paused=0
resume_writers() {
  if [[ "$paused" == "1" ]]; then
    docker start "${writers[@]}" >/dev/null
  fi
}
trap resume_writers EXIT
if [[ "${SNAPSHOT_PAUSE_WRITERS:-1}" == "1" ]]; then
  docker stop -t 30 "${writers[@]}" >/dev/null
  paused=1
fi

commit=$(git -C "$root" rev-parse HEAD)
printf '%s\n' "$commit" > "$out/git-commit.txt"
git -C "$root" archive --format=tar.gz -o "$out/mausamsetu-source.tgz" HEAD

docker exec "$project-postgres-1" \
  pg_dump -U mausam -d mausam -Fc > "$out/mausam.dump"

pack_volume() {
  local volume=$1 output=$2
  docker run --rm -v "$volume:/src:ro" -v "$out:/out" alpine:3.20 \
    tar -czf "/out/$output" -C /src .
}

pack_volume "${project}_forecast-data" forecast-data.tgz
pack_volume "${project}_public-products" public-products.tgz
pack_volume "${project}_run-backups" run-backups.tgz

if [[ "${INCLUDE_PROVIDER_CACHE:-0}" == "1" ]]; then
  pack_volume "${project}_provider-cache" provider-cache.tgz
fi

if [[ "$paused" == "1" ]]; then
  docker start "${writers[@]}" >/dev/null
  paused=0
  trap - EXIT
fi

python3 - "$out" "$commit" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
folder=Path(sys.argv[1])
files={}
for path in sorted(folder.iterdir()):
    if path.is_file() and path.name!="manifest.json":
        h=hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
        files[path.name]={"bytes":path.stat().st_size,"sha256":h.hexdigest()}
manifest={"schema_version":1,"created_at":datetime.now(timezone.utc).isoformat(),
          "git_commit":sys.argv[2],"contains_secrets":False,"files":files}
(folder/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
PY

echo "Migration bundle: $out"
du -sh "$out"

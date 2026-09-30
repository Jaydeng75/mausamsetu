#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Expected OCI Ampere aarch64 host" >&2
  exit 1
fi
command -v docker >/dev/null
docker compose version >/dev/null

mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
cpus=$(nproc)
free_kb=$(df -Pk / | awk 'NR==2 {print $4}')
(( mem_kb >= 8*1024*1024 )) || { echo "Need at least 8 GiB RAM" >&2; exit 1; }
(( cpus >= 2 )) || { echo "Need at least 2 CPUs" >&2; exit 1; }
(( free_kb >= 20*1024*1024 )) || { echo "Need at least 20 GiB free disk" >&2; exit 1; }

root=/srv/mausamsetu
host_uid=${SUDO_UID:-$(id -u)}
host_gid=${SUDO_GID:-$(id -g)}
sudo install -d -m 0755 /opt/mausamsetu "$root" "$root/state"
sudo install -d -o "$host_uid" -g "$host_gid" -m 0700 "$root/secrets" "$root/migration"
sudo install -d -o 10001 -g 10001 -m 0700 \
  "$root/state/forecast" "$root/state/cache" "$root/state/backups"
sudo install -d -o 10001 -g 10001 -m 0755 "$root/state/public"
sudo install -d -o 999 -g 999 -m 0700 "$root/state/postgres"

echo "OCI host directories prepared."
echo "Keep ports 4173 and 8000 private; use an SSH tunnel during validation."

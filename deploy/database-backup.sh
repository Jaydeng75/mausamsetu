#!/bin/bash
set -eu
umask 077
mkdir -p /backups/db
while true; do
  day=$(date -u +%Y%m%d)
  target="/backups/db/$day.dump"
  checksum="$target.sha256"
  valid=false
  if [ -s "$target" ] && [ -s "$checksum" ]; then
    expected=$(cat "$checksum")
    if printf '%s  %s\n' "$expected" "$target" | sha256sum --check --status; then valid=true; fi
  fi
  if [ "$valid" = false ]; then
    temporary=$(mktemp /backups/db/.dump-XXXXXX)
    if timeout 120 pg_dump --host="${PGHOST:-postgres}" --username="${PGUSER:-mausam}" --dbname="${PGDATABASE:-mausam}" --lock-wait-timeout=30s --format=custom --file="$temporary"; then
      hash=$(sha256sum "$temporary" | cut -d' ' -f1)
      mv "$temporary" "$target"
      printf '%s\n' "$hash" > "$checksum.part"
      mv "$checksum.part" "$checksum"
      printf 'Database backup completed: %s\n' "$day"
    else
      rm -f "$temporary"
      printf 'Database backup failed: %s\n' "$day" >&2
    fi
  fi
  find /backups/db -maxdepth 1 -type f -name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].dump' | sort -r | tail -n +8 | while IFS= read -r old; do
    rm -f -- "$old" "$old.sha256"
  done
  sleep 3600
done

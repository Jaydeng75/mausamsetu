# MausamSetu deployment and recovery runbook

## Primary deployment: Docker

The active deployment uses Docker rather than macOS launch agents. The attempted launch agents did not become reachable and were disabled; their files were archived under the private runtime's `disabled-launchd` directory. The optional installer remains in the repository but is not the primary deployment path.

```sh
# Run from the repository root with your private environment file.
MAUSAM_SEED_CACHE=/path/to/existing/public-provider-cache \
EARTHDATA_NETRC_PATH=/path/to/private/earthdata.netrc \
 docker compose --env-file /path/to/private.env -p mausamsetu-audit \
 -f docker-compose.yml -f docker-compose.runtime.yml up --build -d
```

`POSTGRES_PASSWORD` must match the existing database. Keep the environment file private. The optional seed cache is read-only and only allowlisted provider GRIB filenames are copied. Earthdata credentials are mounted as a Compose secret and must be owner-only; never put them in the repository or public volume. Without a seed cache, the worker retrieves current eligible source data itself.

The workbench is at `http://127.0.0.1:4173`; release evidence and operations are at `/sih`. The API is bound to localhost port 8000. No public cloud endpoint has been provisioned.

The deployment contains the web app, API, Postgres, replay/observation worker, one sequential forecast-maintenance worker, the CMORPH/IMERG rainfall-verification + shadow worker, a separate IMD exact-window gauge-grid verification worker, and the database-backup worker. The forecast worker checks India first and then global using one shared provider cache, so the two domains do not race the same ECMWF files. A one-shot initializer sets ownership of new application volumes. Workers do not receive the Docker socket.

```sh
docker compose -p mausamsetu-audit -f docker-compose.yml -f docker-compose.runtime.yml ps
curl --fail http://127.0.0.1:4173/api/operations
curl --fail http://127.0.0.1:8000/health/ready
```

Docker restart policies restart services when Docker is running. A powered-off or sleeping laptop is still not an always-on institutional host. Use an approved server/cloud account for that requirement.

## Scheduled work

The forecast-maintenance worker checks hourly, selects a configured 00/12 UTC cycle with an eight-hour availability allowance, verifies the India product, and then checks the matching global product. ECMWF retrieval is serialized with shared provider/file locks and bounded backoff. It skips already complete cycles, quarantines malformed cached GRIB files, preserves native files, and publishes immutable numerical snapshots before replacing the India or global latest pointers.

The database-backup worker makes one custom-format dump per UTC day and retains seven days. The ingestion/maintenance worker separately snapshots published scientific artifacts and the current public forecast, checks recorded hashes, and publishes operational status. Backups are private Docker volumes, not public downloads or off-site disaster recovery.

The replay worker also watches `/data/observation-inbox`. An authorized provider can place a normalized `.npy` file and a JSON sidecar containing `ready: true`, its basename in `file`, `run_id`, and the complete metadata defined in `VERIFICATION.md`. Released batches are verified once; incomplete or future-release batches wait, and invalid batches receive quarantine receipts. This generic inbox is separate from the public IMD gauge-grid worker.

## Recovery and failure behavior

A failed refresh leaves the previous publication intact. Old backfills cannot replace a newer cycle. The browser distinguishes a retained stale run from a fresh forecast. Unsupported missing-source combinations are withheld; explicitly approved combinations give the missing source zero contribution.

The maintenance worker enforces a 5 GB free-space floor, including the read-only host budget mount where available. Raw provider archives are not silently deleted to reclaim space. Provision approved external storage before growing a substantial historical archive.

Restore scientific archives to a new empty directory using `python -m mausam.backup --restore ARCHIVE --into EMPTY_DIRECTORY`. Restore database dumps to a separate test database with the matching Postgres client, verify migration state and records, and check artifact hashes before switching a live deployment. The release audit includes successful isolated restores.

External paging/email, off-site backups, immutable external audit retention and an on-call process are not configured. The current alerts are visible in the operations page and local event records. A healthy service report is not scientific acceptance.

## Institutional deployment gates

Apply `docker-compose.production.yml` only with real HTTPS OIDC issuer/JWKS/audience settings, explicit allowed origins and non-development database credentials. Production startup rejects anonymous institutional access. Signed-token tests exercise viewer, reviewer and approver boundaries; no institution's identity provider has been impersonated or configured.

Keep only approved public-source derivatives in the public projection. NCUM, NEPS research samples, station observations, model artifacts and backup dumps remain outside it. Configure an approved HTTPS ingress, resource budgets, rate limits and organization-specific access policies before exposing institutional endpoints.

To stop services without deleting data, use the same Compose files with `stop`. Never use `down -v` on data that must be preserved. Source code can be rebuilt independently of the named forecast, provider-cache and backup volumes.

Known compatibility notes: the regression environment emits a Starlette/httpx deprecation warning and a NumPy/netCDF4 binary-size warning. The tests pass; the publication API uses the explicitly selected SciPy NetCDF reader. Review these dependencies and raw-provider I/O compatibility before institutional acceptance rather than treating a passing test count as blanket certification.


## Rainfall shadow bootstrap and prospective operation

The hourly rainfall worker refreshes the live-roster shadow evidence automatically after satellite verification. Its persistent prospective start is stored in the private scientific volume and is not reset by retrospective backfill.

A bounded recent-history bootstrap can be run manually when enough public provider history remains available:

```sh
EARTHDATA_NETRC_PATH=/path/to/private/earthdata.netrc \
docker compose --env-file /path/to/private.env -p mausamsetu-audit \
  -f docker-compose.yml -f docker-compose.runtime.yml \
  run --rm --no-deps rain-worker \
  python -m mausam.shadow_backfill \
  --runtime /data --cache /cache --public /public \
  --netrc /run/secrets/earthdata_netrc \
  --start 2026-09-20T00:00:00Z --count 6
```

The CLI uses only 00 UTC +24 h cycles, writes a private compact rainfall archive, and does **not** update India/global public forecast pointers. GEFS falls back from NOMADS to NOAA's public cloud archive when older filtered files have rotated out. Backfilled cases can bootstrap model fitting but never increment the prospective counter.

Provider cache growth is bounded operationally by the host disk guard; inspect disk usage before larger backfills.


## Multi-variable shadow bootstrap

The multi-variable archive uses one 00 UTC initialization per day and stores +24/+48/+72 h rainfall, 2 m temperature and 10 m U/V for all four live experts. Historical GFS/GEFS fields come from NOAA public cloud GRIB indexes. IFS/AIFS use direct ECMWF Open Data where possible and may fall back to explicitly pinned Open-Meteo Single Runs; Open-Meteo never substitutes GFS/GEFS.

A bounded backfill can be run with:

```sh
python -m mausam.multi_backfill \
  --runtime /data --cache /cache --public /public \
  --netrc /run/secrets/earthdata_netrc \
  --start 2026-09-13T00:00:00Z --count 6
```

This populates the research archive and references only. It does not replace the public forecast pointer and historical initializations never count as prospective evidence.

The regular rainfall worker subsequently refreshes `multi-shadow-status.json` and current research-only inference when the latest public run is a supported 00 UTC cycle.

## IMD exact-window worker

`imd-gauge-worker` checks due 00 UTC forecast initializations at +24/+48/+72 h. IMD's daily 0.25° gauge-gridded analysis ends at 03:00 UTC, so model precipitation is reconstructed for exactly 03:00→03:00 UTC rather than using the normal 00:00→00:00 shadow total.

The worker validates IMD content type, filename, binary length, dtype, grid geometry, missing-value convention and physical range. It publishes source/equal-baseline scorecards separately from the 00→00 adaptive gate.

## Institution-facing production preflight

Do not put production secrets in the repository. Create an owner-only file from `deploy/production.env.example`, then run:

```sh
chmod 600 /secure/mausamsetu-production.env
python deploy/production-preflight.py --env-file /secure/mausamsetu-production.env

EARTHDATA_NETRC_PATH=/secure/earthdata.netrc \
docker compose --env-file /secure/mausamsetu-production.env \
  -f docker-compose.yml -f docker-compose.runtime.yml -f docker-compose.production.yml config
```

The preflight rejects placeholder/weak secrets, HTTP/localhost origins, wildcard CORS/email domains and group/world-readable credential files. The production overlay adds Caddy HTTPS and oauth2-proxy OIDC SSO, while the backend independently verifies issuer, audience, JWKS signature, token age and application roles.

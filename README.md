# MausamSetu

India-first forecast blending and verification workbench for SIH26081.

## SIH 2026 submission

**Team:** HEXATECH · **Problem statement:** SIH26081

- [Live prototype](https://mausamsetu-mauve.vercel.app/)
- [Research, validation and source readiness](https://mausamsetu-mauve.vercel.app/sih)
- [Preparedness companion](https://mausamsetu-mauve.vercel.app/preparedness)
- [Six-slide submission PDF](submission/MausamSetu-SIH2026.pdf)

This repository is a clean source snapshot for review, including the September 30 operational fixes and MOSDAC integration. Credentials, private archives, database state and provider caches are excluded. Packaged forecast snapshots are dated examples; the deployed service publishes newer runs. Configure your own credentials and provider permissions before running scheduled ingestion.

## Current release

The application uses real GFS/GEFS/IFS/AIFS numerical forecasts, near-real-time CMORPH/IMERG rainfall verification, an independently deployable Python API, a reviewed-model publication pipeline, and separate scientific benchmarks. It is an **experimental research deployment, not an institutionally approved forecasting or warning service**.

- **Forecasts:** India and global live GFS/GEFS/IFS/AIFS maps, lead-time navigation, point inspection, source provenance, GEFS ensemble statistics, quality flags and an explicitly uncalibrated availability-aware equal baseline.
- **Backend:** FastAPI, Postgres, immutable scientific products, distribution mixtures, learned grid-wise weights, protected reviews, activation/rollback and observation verification.
- **Science:** historical IFS/Pangu and IFS/GraphCast benchmarks plus live-roster research shadow candidates for GFS/GEFS/IFS/AIFS at +24/+48/+72 h. Rainfall uses CMORPH for fitting/selection and IMERG as an independent cross-reference; temperature and paired U/V wind use delayed ERA5-family reanalysis. All candidates remain non-production until prospective, outage, extreme-event and institutional gates pass.
- **India evidence:** IMD's public real-time 0.25° daily gauge-gridded rainfall binary is decoded and verified on its exact 03→03 UTC accumulation window, with the older 2020 IMD NetCDF retained privately for research. Delayed NEPS research access is exercised; NCUM latest-cycle access remains institutional.
- **Operations:** sequential India→global refresh, source freshness, ECMWF mirror fallback, CMORPH/IMERG and IMD gauge-grid verification workers, multi-variable shadow refresh, local alert events, daily database/product backups and integrity-checked restoration.
- **SIH:** `/sih` shows measured tests, India source readiness, historical benchmarks, live CMORPH/IMERG scorecards, bootstrap-versus-prospective shadow evidence and unresolved acceptance gates. Synthetic demonstration screens remain clearly labeled.

See [release evidence](docs/RELEASE-2026-09-26.md), [operations runbook](docs/RUNBOOK.md), [training](docs/TRAINING.md), [verification](docs/VERIFICATION.md), [live rainfall shadow contract](docs/LIVE-SHADOW-RAIN-2026-09-27.md), [Open-Meteo backfill policy](docs/OPEN-METEO-BACKFILL.md), [production security](docs/PRODUCTION-SECURITY.md), and [data sources](docs/DATA-SOURCES.md).

## Frontend

```sh
npm ci
npm run build
MAUSAM_PUBLIC_BACKEND_URL=http://127.0.0.1:8000 npm run start -- --hostname 127.0.0.1 --port 4173
```

Open `http://127.0.0.1:4173`. Without the backend environment setting, the site uses packaged snapshots. With it, the browser checks for newly published backend products every minute. A backend failure is not replaced with synthetic data.

The active frontend is **standard Next.js**. Development uses `.next-dev`; production builds use `.next`. The older Vinext scripts are retained for historical context and are not the production entry point.

## Primary deployment: Docker

```sh
# Use a private environment file with the existing database password.
MAUSAM_SEED_CACHE=/path/to/optional/provider-cache docker compose \
  --env-file /path/to/private.env -p mausamsetu-audit \
  -f docker-compose.yml -f docker-compose.runtime.yml up --build -d
```

This starts the frontend on localhost port 4173, API on 8000, Postgres, replay/observation worker, one hourly forecast-maintenance worker, one rainfall-verification worker and the daily database-backup worker. Persistent volumes keep public products, native cache, scientific data and backups separate. See the runbook for source seeding and recovery.

For an Oracle Cloud Ampere A1 ARM64 migration, use `docker-compose.oci.yml` and the checked export/import procedure in [deploy/oci/README.md](deploy/oci/README.md). The deployed frontend runs on Vercel; OCI hosts the API, database and workers. The read-only HTTPS gateway is described in `deploy/oci/compose.gateway.yml`; internal application ports remain private.

The public gateway exposes selected read-only forecast and status routes. Administrative writes require signed role-bearing tokens and remain outside the public gateway. Institutional operation still requires identity integration, distribution permissions and scientific review. OCI collects prospective evidence independently of the Mac.

The optional macOS service installer is retained, but the attempted launch agents were disabled because they did not become reachable. Docker is the active scheduler. Do not start a second frontend on port 4173.

## Validation

```sh
npm run typecheck
npm run test:science
npm run test:data
PYTHONPATH=backend python -m pytest backend/tests -q
npm run build
MAUSAM_E2E_RUNNING=true MAUSAM_E2E_CONNECTED=true npm run test:e2e
```

The command above tests the already-running Docker frontend. Omit MAUSAM_E2E_RUNNING to let Playwright start its own test server on a free port 4173. The connected tests require the API/public projection on port 8000. Without `MAUSAM_E2E_CONNECTED=true`, they test packaged snapshots. Scientific tests and interface fixtures do not constitute forecast-skill validation; inspect the separate held-out experiment and its limitations.

Remaining external gates are a verified NCUM/latest-cycle NEPS feed, multi-season/prospective acceptance for the deployed source roster, independent observational review for temperature/wind, institutional identity values and distribution approvals, off-site recovery, and operational ownership. IMD public gauge-grid exact-window rainfall verification, +24/+48/+72 multi-variable shadow candidates, extreme-event support gates and the 10-pattern missing-source matrix are implemented; they have not yet accumulated enough prospective evidence for production acceptance.

## Preparedness companion

Open `/preparedness` for the source-linked safety handbook, private preparedness checklist, printable/script-free offline HTML export, and USGS earthquake catalogue with actual-coordinate MapLibre inspection. The main point panel also includes seven-day cards using the selected published forecast source and display units.

These are supplementary interfaces, not additions to the weather blending algorithm or an official warning system. No mock weather, fabricated alerts, made-up nearby facilities, browser AI keys, or extra map SDK were imported from the reference ZIP. See [the integration record](docs/WEATHER-ZIP-INTEGRATION.md) and [attribution](docs/ATTRIBUTION.md).

Run `npm run test:preparedness` for the new contract/export checks. Browser tests include offline guidance, storage failures, real-coordinate rendering, stale/error states and mobile layouts.

## Continuous integration

The GitHub Actions configuration is provided in `docs/ci/github-actions.yml.example`. To enable it, copy it to `.github/workflows/ci.yml` using an account or token with workflow permission. The submission publishing token did not have that scope. The validation commands above can also be run locally.

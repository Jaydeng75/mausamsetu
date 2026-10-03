# MOSDAC satellite rainfall context

## Scientific scope

INSAT-3DS `3SIMG_L2G_IMR` rain rates (mm/hr) are independent satellite context.
They are not accumulated rainfall, official warnings, ground truth, or inputs to
operational forecast weights. The worker samples the three latest catalogue
entries every 30 minutes; outages can leave gaps, so this is not a complete
verification archive. A validated scan-to-accumulation method and complete
matched intervals are required before forecast scoring.

The decoder validates product identity, units, dimensions, monotonic coordinates,
acquisition interval against catalogue interval, fill values and scale/offset.
Latitude-weighted means and wet-area fractions are calculated for seven named
bounding boxes; these include ocean and neighbouring countries. Coverage and
unweighted grid-cell percentiles are shown. No pixel quality flags are present
in the inspected IMR product. File coordinates take precedence over nominal
resolution statements. File SHA-256 and retrieval time are preserved.

## Provider and policy

- Interface: https://www.mosdac.gov.in/downloadapi-manual
- Policy: https://www.mosdac.gov.in/data-access-policy
- Guidelines: https://www.mosdac.gov.in/look/DOCS/mosdac-data-guidelines_english.pdf
- Product manual: https://www.mosdac.gov.in/docs/INSAT-3DS_Operational_Products_V1.pdf

Source attribution: MOSDAC/SAC/ISRO. Raw products stay private; only derived
regional summaries are public. A product-specific INSAT-3DS DOI has not been
confirmed; do not reuse the INSAT-3D DOI. Account access to current scans was
verified locally on 2026-09-28; availability can change with provider permissions.

## Installation on existing OCI host

Keep existing forecast workers running. Provision
`/srv/mausamsetu/state/mosdac` owned by 10001:10001 with mode 700.
Transfer the account JSON privately to
`/srv/mausamsetu/secrets/mosdac.json`, owner 10001:10001, mode 600.
The JSON has username/password keys. Never commit it or send it to Vercel.

From `/opt/mausamsetu`:

```sh
docker compose -p mausamsetu-mosdac -f deploy/oci/compose.mosdac.yml up -d --build
docker compose -p mausamsetu-mosdac -f deploy/oci/compose.mosdac.yml logs --tail 5
```

Validate the updated Caddy configuration, then recreate the existing gateway
with `deploy/oci/compose.gateway.yml` to mount public summaries read-only.
The exact `/public/mosdac` route serves only `mosdac-status.json`.
Other raw archive and administrative paths must remain inaccessible.
The Vercel `/api/mosdac` route proxies that summary; `/sih#mosdac` renders it.

## Operations

- Every 30 minutes, maximum three scans per cycle, 8 MB per-file bound.
- Private scan retention: 14 days by local file mtime.
- Status report retains last successful observation on failure with explicit
  unavailable/authentication state; UI marks status over 90 minutes overdue.
- Authentication rejection suspends retries until credential file mtime changes.
  Rotate/update credentials privately, then restart the worker.
- Worker logs contain status/error class only, never provider bodies or secrets.
- Authenticated cycles call the official logout endpoint in cleanup, including download failures.
- The API health projection includes MOSDAC failure, stale-status and logout-failure alerts.
- A rejected login remains paused to prevent account lockout. After a single operator login succeeds, archive the rejection marker and restart only the MOSDAC worker. Do not repeatedly retry invalid credentials.
- Container runs as non-root, read-only root filesystem, no added capabilities,
  512 MB memory and 0.5 CPU limit; no published ports.
- Stop only the `mausamsetu-mosdac` compose project to roll back this collector.
  Existing forecast collection and prospective evidence are independent.

## Verification completed locally

Real authenticated downloads decoded successfully (three scans). Six tests cover
packed-value masks, rate semantics, units, timestamps, coordinate integrity, and
authentication retry suspension. TypeScript typecheck passed. OCI ARM64 activation passed on 2026-09-28 at 10:47 UTC, with three real scans.
The public endpoint and Vercel proxy returned available. Raw-file paths and
administrative paths returned 404. The live SIH panel rendered seven regional
summaries with no browser console errors. Production Vercel deployment:
`dpl_GYjzFYkFhPcjUXKXB6PxK1cchJtt`.

# Implementation boundary — current release

This document supersedes the earlier prototype checklist. See `RELEASE-2026-09-26.md` for measured results and `RUNBOOK.md` for deployment instructions.

## Running and tested

The Docker-native deployment serves real GFS, GEFS ensemble statistics, IFS and AIFS numerical products through the Python backend to the standalone Next.js map, with separate India and live-global publications. Ingestion and maintenance are designed for hourly execution; database and scientific-product backups are versioned with checksums. Source freshness, explicit failures and backup state appear on the SIH evidence page.

The backend includes source contracts, interval/unit/grid checks, immutable publication, distribution mixtures, grid-wise learned weights, signed-token roles, review records, active-model resolution, rollback, observation verification and a normalized-observation inbox. Optional context fields are checksum-pinned, grid-checked and rejected when they were not available by the forecast decision time.

The current regression suite has 117 backend tests, 280 synthetic forecast-combination checks, 2,880 synthetic verification records, public-data integrity checks, preparedness checks, production type/build checks and 19 browser tests. Connected-archive testing is run separately after the Docker API/public projection is started.

## Real research evidence

The temperature benchmark uses WeatherBench IFS-HRES, Pangu and ERA5 with separated calibration, training, model-selection and held-out periods. The public aggregate is `public/data/learned-benchmark.json`.

A second bounded rainfall benchmark uses IFS-HRES + GraphCast 24-hour precipitation against ERA5 over the India-region box. The adaptive mixture has lower held-out CRPS than the static mixture in this experiment; the initialization-block 95% interval is below zero. The experiment is retrospective, uses reanalysis rather than independent gauges, samples three initialization dates per month and contains only one held-out case above 115.6 mm/24h. It is not an extreme-weather acceptance result.

A real 2020 IMD 0.25-degree daily gridded-rainfall NetCDF is staged privately with checksum and metadata. It is not silently collocated with the WeatherBench score because the file does not encode accumulation bounds and the exact reporting window must match the forecast accumulation.

## Indian provider readiness

- GFS/GEFS/IFS/AIFS: live public-source numerical ingestion is implemented. GEFS is an ensemble-mean expert with provider spread retained; IFS/AIFS use mirror-aware locked retrieval.
- NEPS: a delayed TIGGE/ECDS research sample is present; the route is 48-hour delayed and is not a latest-cycle operational feed.
- NCUM: authorized-file import is implemented, but no verified authorized numerical file/latest-cycle endpoint is configured.
- IMD rainfall: the public real-time 0.25° daily gauge-gridded binary endpoint is integrated and exact-window scorecards are implemented. The separate credentialed/API ecosystem may still require institutional access for other products.
- MOSDAC: public catalogue discovery is working for current INSAT rainfall products; HDF5 download needs an authorized account.
- INCOIS ERDDAP: active historical ASCAT/TMI/value-added datasets were verified through the server catalogue. Python TLS trust remains unresolved on this Mac, so no verification bypass is used.

## Deliberate boundaries

The live four-source map still uses an explicitly uncalibrated equal-contribution baseline over available central fields. GEFS contributes one ensemble-mean expert, not 31 pseudo-models. Research weights from IFS/Pangu or IFS/GraphCast are never transferred to this different live roster.

The synthetic workbench retains advanced interaction demonstrations—weights, probabilities, uncertainty and replay—with clear labels. Those screens are not evidence of operational source skill.

The live-roster acceptance framework now covers rainfall, temperature and paired U/V wind at +24/+48/+72 h, all 10 single-/two-source outage combinations per candidate, and rainfall extreme thresholds at 64.5/115.6/204.5 mm/24 h. The gates are implemented and measured, but the current bootstrap does not yet contain enough independent held-out/prospective events to pass them. Unsupported or unvalidated configurations remain withheld rather than silently authorized.

## External acceptance requirements

Latest-cycle NCUM/NEPS access, source-version-specific calibration, multi-season/prospective acceptance, independent observational review for temperature/wind, institutional scientific approval and approved always-on hosting remain necessary. IMD public gauge-grid rainfall, CMORPH, IMERG and ERA5 analysis reference paths are implemented; having a reference path does not itself satisfy the minimum event-count or prospective-skill gates.

The institution must also supply real identity-provider settings, HTTPS/public deployment approval, distribution policies, reviewer authority, off-site recovery and external paging. The current application is a research deployment, not an officially approved forecast/warning service.


## Live operational extensions added 27 September 2026

The public-source forecast roster now includes **GFS, GEFS ensemble statistics, IFS and AIFS**. India is published at six-hour leads on the bounded 1° browser grid; a separate 2° global live preview is published at daily leads. Both products are checksum-pinned and independently addressed.

GEFS central fields are explicitly labelled as the provider ensemble mean. GRIB-reported ensemble count and provider spread are retained for temperature, pressure and wind components. The system does not synthesize a 24-hour precipitation spread from six-hour spread fields.

CMORPH2 NRT and IMERG Early V07 are now scheduled, reference-preserving rainfall verification sources. Their scorecards remain separate because both are satellite precipitation estimates. They are not treated as IMD/gauge truth and are only ingested after the forecast valid window has elapsed.

The India and global workers share ECMWF Open Data locks, use file-level integrity checks, retry provider throttling with backoff, and publish degraded source status instead of silently filling an unavailable IFS/AIFS field.


### Final live scheduler policy

Only one forecast-maintenance worker runs provider ingestion. It publishes India first and then invokes the global refresh sequentially, so the two domains never compete for provider bandwidth or peak process memory. The former standalone global worker has been removed from the deployment definition.

India publishes GFS, GEFS and AIFS at six-hour steps. IFS is published at +24, +48, +72, +96, +120, +144 and +168 hours; unavailable intermediate IFS leads are represented as unavailable and are never interpolated. The equal baseline re-normalizes across the central fields actually present at each lead. Global live mode is daily for all four sources.

ECMWF files use per-file locks plus a shared Open Data retrieval lock. The direct ECMWF endpoint is primary and the Google Cloud mirror is a fallback after bounded retries. Successful retrieval route, checksum and field metadata are retained. Corrupt cached GRIBs are discarded and fetched again.


## Production-readiness expansion — 27 September 2026

The repository now includes a multi-variable live-roster shadow framework for the exact GFS / GEFS ensemble mean / IFS / AIFS roster at +24, +48 and +72 hours:

- rainfall: scalar point-mixture CRPS, CMORPH primary reference, independent IMERG cross-reference;
- 2 m temperature: scalar point-mixture CRPS against delayed ERA5 analysis;
- 10 m wind: one shared source-weight gate for paired U/V vectors, evaluated with the multivariate energy score against delayed ERA5 analysis.

A bounded six-day real-data bootstrap produced all nine candidate slots. These are research candidates only: the bootstrap contains 6 initialization blocks with 3 train / 1 selection / 2 held-out, and zero prospective blocks. No candidate is production-accepted.

Every candidate evaluates 10 degraded-source states (four single-source outages plus six two-source outages). Acceptance requires the adaptive degraded forecast to beat the equal fallback with its event-block interval and stay within a configured degradation bound relative to the full-source adaptive candidate.

Rainfall additionally tracks heavy / very-heavy / extremely-heavy support at 64.5, 115.6 and 204.5 mm/24 h. The current bootstrap does not meet the declared independent-event support requirement, so the extreme gate remains blocked.

IMD's public 0.25° daily gauge-gridded binary is decoded as little-endian float32 and matched only to an exact 03:00→03:00 UTC model accumulation window. A real 26 September 00 UTC +24 verification completed over 316 finite collocated cells. The 00→00 adaptive gate is deliberately not transferred to this different observation window.

Historical bootstrap uses direct NOAA cloud archives for GFS/GEFS and direct ECMWF Open Data where available. Open-Meteo Single Runs is an optional IFS/AIFS fallback only, with explicit run/model pinning, no elevation downscaling, response checksums and research-only provenance.

The institution-facing deployment overlay now contains Caddy HTTPS ingress, oauth2-proxy OIDC SSO, backend JWT issuer/audience/JWKS/role checks, explicit CORS, strong-secret/file-permission preflight, read-only containers and reduced Linux capabilities. Real institutional DNS/OIDC credentials and approver identities remain external configuration and are intentionally not fabricated in the repository.

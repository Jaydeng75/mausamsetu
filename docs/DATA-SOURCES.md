# Real data integration — 27 September 2026

## What is actually loaded

| Source | Product and coverage in this delivery | Status |
| --- | --- | --- |
| NOAA GFS | Live 00/12 UTC cycles; +24 to +168 hours with six-hour India steps and daily global preview; rainfall, 2 m temperature, 10 m wind, mean sea level pressure | Downloaded, GRIB decoded, connected to hosted map |
| NOAA GEFS | Provider ensemble mean plus GRIB-reported ensemble count and provider spread for temperature, pressure and wind components | Live ensemble-derived source; 24-hour rainfall spread is deliberately not synthesized |
| ECMWF IFS | Physical-model Open Data; six-hour India timeline and daily global preview through +168 h | Live source with shared provider/file locks, corruption quarantine and bounded retry/backoff |
| ECMWF AIFS Single | AI forecast Open Data, same core fields and forecast windows | Live source with shared provider/file locks and bounded retry/backoff |
| WeatherBench 2 HRES / ERA5 | 31 daily 00 UTC initializations during January 2020; +24 through +168 hours daily; same four variables | Downloaded remotely from Zarr and evaluated; 28 score rows and first-initialization maps published |
| NCMRWF NEPS via TIGGE | 1 January 2020 00 UTC, +24h; 11 perturbed members, five GRIB fields per member | Retrieved through the user's authenticated ECDS account; 55 records decoded, member identities preserved in local NetCDF groups |
| NCUM | Official MoES catalogue points to IITM ARDC | No authorized numerical file is staged. The importer is ready, but latest-cycle access and use permissions remain external dependencies. |
| IMD 0.25° daily rainfall — public real-time binary | Gauge-gridded daily analysis, 129 × 135, little-endian float32, 24 h ending 03:00 UTC | Public numerical endpoint integrated; exact 03→03 UTC four-source scorecards are generated without substituting the 00→00 shadow target. |
| IMD 0.25° daily rainfall — historical NetCDF | Real 2020 NetCDF, 366 × 129 × 135, millimetres | Retained in private research storage with SHA-256 inventory; interval semantics are not guessed when metadata is absent. |
| MOSDAC INSAT rainfall | Public catalogue product `3SIMG_L2G_IMR` | Current catalogue discovery works; numerical HDF5 download requires an authorized MOSDAC account. |
| NOAA CMORPH2 NRT | 0.25° half-hourly satellite precipitation, exact 24-hour aggregation | Automatic no-login post-event rainfall verification; kept separate from gauge truth |
| NASA GPM IMERG Early V07 GIS | 0.1° provider one-day satellite precipitation | Authenticated automatic post-event rainfall verification; credential is mounted privately, not stored in Git |
| ERA5 analysis | Delayed 2 m temperature and 10 m U/V analysis on exact valid times | Normalized from direct Google ARCO ERA5T or explicitly recorded Open-Meteo ERA5 Archive transport; reanalysis, not an independent station network |
| Open-Meteo Single Runs | Explicit archived IFS/AIFS runs | Optional historical fallback only; run/model pinned, elevation=nan requested, response SHA-256 retained; never counts as prospective evidence |
| INCOIS ERDDAP | Active ASCAT, TMI and value-added ocean/context archives | Server catalogue verified with system TLS; Python worker trust-chain configuration is unresolved. Selected archives are historical, not live 2026 gate features. |

The default app uses real versioned GFS/GEFS/IFS/AIFS grid assets for India plus a separate live-global product. The older synthetic features remain explicitly accessible under **Synthetic demo**. One maintenance worker refreshes India and then global sequentially each hour. Valid degraded runs may publish with unavailable sources explicitly recorded; no missing source is silently substituted. This local loop is not an institutional operational feed.

## Forecast products

India uses exact native points sampled to a 1° browser grid over 5–38°N / 65–100°E. The live-global preview uses 2° display points. Native inputs differ by source: GFS 0.25° in India / 1° global, GEFS provider statistics 0.25° in India / 0.5° global, and IFS/AIFS 0.25°. GFS, GEFS, IFS and AIFS are published every six hours in the India timeline; the global browser preview is intentionally daily to bound payload and provider load. These are display point samples, not conservative area averages or downscaling. Native files remain in the private provider cache.

GFS precipitation uses the GRIB accumulation origin and end time. For each six-hour increment, the importer uses either an explicit six-hour total or a difference between cumulative fields with the same origin, then sums four increments. AIFS uses the difference between end-of-window and preceding-24-hour cumulative totals, accepting the explicitly encoded metres or kg/m² units. Temperature is converted K→°C, pressure Pa→hPa, and wind speed is computed from paired u/v components. No source is inferred from its display name.

Negative rainfall differences are represented as null, with per-lead counts and minima retained in each run’s provenance. The app withholds the equal blend at affected cells rather than treating them as zero rainfall. Counts are run-specific; inspect the corresponding manifest rather than reusing counts from an older cycle.

The displayed equal blend is an uncalibrated central-field baseline over currently available experts. GEFS contributes one provider ensemble-mean expert, not its members as separate votes. Wind blends paired u/v before magnitude. Source disagreement and GEFS spread are not relabelled as calibrated predictive intervals, skill weights or event probabilities.

## WeatherBench outside India

- Published upstream grids: HRES `2016-2022-0012-64x32_equiangular_conservative.zarr`; ERA5 `1959-2023_01_10-6h-64x32_equiangular_conservative.zarr`.
- The evaluation selects exact initialization times and exact prediction durations; ERA5 is selected at initialization plus lead. No nearest-time substitution.
- Both products share the same conservative 64×32 grid; grid equality is checked.
- A Natural Earth cell-centre mask excludes nine Indian grid cells. 2,039 global cells remain, including oceans. Coarse cells can straddle boundaries.
- RMSE, MAE and bias use cosine-latitude area weights. Each score uses 31 initializations × 2,039 cells = 63,209 paired values.
- Rain uses each dataset's explicitly derived `total_precipitation_24hr` field, converted metres→mm.
- ERA5 is a reanalysis reference, not independent station observations. This January sample is not a full WeatherBench benchmark, seasonal validation, adaptive-gate training, or an official leaderboard result.

## India rainfall research and observations

The bounded rainfall experiment uses IFS-HRES and ERA5-initialized GraphCast `total_precipitation_24hr` over 36 selected 2020 initialization dates and three lead times. January–February calibrate source residuals, March–June train the gate, July–August select regularization, and September–December remain held out. The adaptive mixture has lower held-out CRPS than the static mixture in this experiment; `public/data/rainfall-benchmark.json` records the full metrics, fixed thresholds and limitations. ERA5 is still the reference, not independent Indian gauges. Only one held-out case exceeds 115.6 mm/24h, so no severe-tail skill claim is made.

A real IMD 2020 0.25° daily gridded-rainfall NetCDF is stored outside the public application at `work/research-data/imd`. Its checksum, dimensions, units and coordinate coverage are inventoried. IMD's operational daily rainfall pages describe 08:30 IST-to-08:30 IST accumulation, while the archive NetCDF has no time bounds. Exact model/observation interval mapping is therefore kept as a scientific acceptance gate rather than guessed.

MOSDAC public search currently identifies INSAT rainfall catalogue products without requiring download credentials. The numerical HDF5 download workflow remains credentialed. INCOIS ERDDAP currently exposes 17 active datasets; the selected ASCAT/TMI/value-added products are historical context archives, so they are not injected into a 2026 live gate.

## Reproduce

From the `backend` directory, install `pip install -e '.[public-data,test]'` into your environment, then:

```sh
python -m mausam.public_data --date 20260926 --cycle 0 --domain india --cache /path/to/private/cache --output ../public/data/products
python -m mausam.public_data --date 20260926 --cycle 0 --domain global --step 24 --cache /path/to/private/cache --output ../public/data/products
python -m mausam.weatherbench --start 2020-01-01 --days 31 --countries ../public/data/countries.geojson --output ../public/data/products
python -m mausam.imd_gridded --year 2020 --output /path/to/private/research/imd
python -m mausam.india_sources --neps-dir /path/to/private/research/neps --imd-grid-dir /path/to/private/research/imd --output ../public/data/india-source-status.json
python -m mausam.rainfall_benchmark --archive /path/to/private/research/ifs-graphcast-rainfall-2020 --output ../public/data/rainfall-benchmark.json --replays ../public/data/rainfall-replays.json
```

The first command requires the explicitly chosen run to still be present in the providers' rolling archives. Choose a common available initialization when refreshing. The cache allows exact regeneration after the provider window expires. Each product has a content-derived filename; the browser checks the SHA-256 in the corresponding latest pointer. Publish the updated site after generating new assets. Do not overwrite the packaged files independently of the source version.

TIGGE access now uses CDS-API at ECDS, not the retired public Web API. After configuring `ECDS_API_KEY` locally, the retrieval adapter is:

```sh
python -m mausam.research_access --date 2020-01-01 --cycle 0 --members 1,2,3,4,5,6,7,8,9,10,11 --output /path/to/private/research/neps
```

This retrieves control and explicitly listed perturbed members, retaining GRIB inventory, member IDs, generating process identifiers, table versions, accumulation intervals and checksums. Verify the historical member roster for each requested period. The browser-downloaded sample in this delivery contains only the 11 perturbed members, not a complete control-plus-perturbed ensemble. A browser login does not automatically configure an API token for Python.

NCUM import accepts an authorized file plus a metadata JSON carrying `product` (NCUM-G or NCUM-R), `model_version`, `initialization`, `licence`, `authorization_reference`, `expected_sha256` and `provider_interface`:

```sh
python -m mausam.ncum_import /path/to/ncum.grib2 --metadata /path/to/product.json --output /path/to/private/staging
```

It validates checksum and numerical format and records inventory. Provider-specific normalization still requires an actual authorized product to verify. It does not manufacture a download endpoint or redistribution rights.

## Indian observations and context checked on 26 September 2026

- **IMD 0.25° daily gridded rainfall:** the real 2020 NetCDF (`ind2020_rfp25.nc`) is staged outside the public application. The decoded field is `RAINFALL`, units are mm, with 366 daily time points on a 129 × 135 grid covering 6.5–38.5°N and 66.5–100°E. SHA-256 is recorded in its private manifest. The NetCDF has no interval bounds, so exact forecast-window collocation remains a scientific gate; the file is not forced into the WeatherBench score.
- **IMD API:** the official API-management portal is reachable. The tested district/AWS-style numerical endpoint returned HTTP 401 from this machine; this is recorded as access/IP-whitelist required, not as a live observation feed.
- **MOSDAC:** public catalogue search is working for INSAT-3DS rainfall dataset `3SIMG_L2G_IMR`. At the recorded probe, the catalogue exposed a current half-hourly item. Numerical HDF5 download requires authorized MOSDAC credentials; catalogue metadata alone is not treated as an observation.
- **INCOIS ERDDAP:** the server's active dataset table was retrieved with normal TLS verification via the system client. Relevant active IDs include `ascat_daily_datasets`, `incois_tmi_3day_datasets`, and `incois_valueadded_products_datasets`. Their published time coverage is historical, so they are context/research sources rather than live 2026 gate inputs. Python/httpx on this Mac does not currently trust the server certificate chain; verification is not disabled.

The release-time machine-readable readiness record is `public/data/india-source-status.json`. Reachability is not scientific acceptance and does not alter dataset licences.

## Real rainfall research experiment

`mausam.rainfall_benchmark` builds a matched IFS-HRES + GraphCast + ERA5 24-hour precipitation archive for selected 2020 initialization dates on a shared 1.5° grid. It trains an adaptive mixture only on the explicitly separated training period and publishes aggregate metrics, fixed-threshold diagnostics, algorithmically selected held-out replay examples and failure cases. The report is `public/data/rainfall-benchmark.json`.

This experiment is retrospective and ERA5-verified. It does not replace IMD verification. Only one held-out case exceeds 115.6 mm/24h, so it cannot support a severe-tail skill claim.

## Licences and references

- [NOAA GFS public data](https://registry.opendata.aws/noaa-gfs-bdp-pds/) and [NOMADS GEFS](https://nomads.ncep.noaa.gov/): public NOAA forecast data; credit NOAA, identify modifications, do not imply endorsement.
- [NOAA CPC CMORPH](https://www.cpc.ncep.noaa.gov/products/janowiak/cmorph.html): satellite precipitation estimate used as a separate verification reference.
- [NASA GPM IMERG Early](https://gpm.nasa.gov/data/directory/imerg-early-run-pps-near-real-time-gis): near-real-time satellite precipitation product; access credentials remain private.
- [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data): CC BY 4.0 and ECMWF terms. This service is based on ECMWF data and products; spatial sampling and unit conversions are modifications. ECMWF accepts no liability for errors, omissions, availability or losses arising from use.
- [WeatherBench HRES licence](https://storage.googleapis.com/weatherbench2/datasets/hres/LICENSE): ECMWF CC BY 4.0 and terms.
- [WeatherBench ERA5 licence](https://storage.googleapis.com/weatherbench2/datasets/era5/LICENSE): Copernicus terms. Contains modified Copernicus Climate Change Service information (2020). Neither the European Commission nor ECMWF is responsible for use.
- [WeatherBench 2 data guide](https://weatherbench2.readthedocs.io/en/latest/data-guide.html). Rasp et al., *WeatherBench 2*, 2024, DOI 10.1029/2023MS004019.
- [Current TIGGE licence, revision 2](https://ecds.ecmwf.int/licences/tigge-licence): NCMRWF data are listed under CC BY-NC 4.0, which permits noncommercial sharing and adaptation subject to attribution and the licence conditions. Access is delayed 48 hours. The previous blanket prohibition against redistribution was incorrect. The existing research sample is nevertheless kept private, outside the Site repository and deployment archive, as requested by the user. This does not authorize a commercial or latest-cycle institutional feed.
- [NCUM catalogue](https://incois.gov.in/essdp/ViewMetadata?fileid=f348c74a-fe80-46a8-b9c7-6e84aaac15f6).

These integrations do not complete the separate institutional authorization, automated operations, calibration/gate training, validation, backup and scientific monitoring work listed in IMPLEMENTATION.md.


## Live four-source forecast and satellite verification extension — 27 September 2026

The live public forecast roster is now **GFS + GEFS + IFS + AIFS**. India uses a 1° browser preview at six-hour forecast leads; the global browser preview uses 2° sampling at +24 to +168 hours. Native provider GRIB files are retained in the private cache and each published asset records source checksums and provider metadata.

GEFS is not treated as a deterministic ensemble member. The displayed GEFS central field is NOAA's provider **ensemble mean**. The GRIB-reported ensemble forecast count is retained, together with NOAA's provider spread for temperature, pressure and wind components. A 24-hour rainfall spread is deliberately not manufactured by summing six-hour spread fields.

ECMWF IFS and AIFS use a shared provider lock across India/global workers, per-file locks, corruption quarantine, and extended retry/backoff. This prevents the two ingestion workers from racing the same Open Data files and reduces 429 throttling. A source that still fails is marked unavailable and the run is published as degraded; it is never silently substituted.

Near-real-time rainfall verification now has two independent satellite references:

- **NOAA CPC CMORPH2 NRT 0.25° / 30 minute**: 48 half-hourly rates are integrated over the exact forecast 24-hour interval, then area-averaged onto the India display grid with a minimum coverage rule.
- **NASA GPM IMERG Early V07 GIS**: authenticated one-day accumulations are decoded using the provider's scale/missing-value metadata and area-averaged onto the same grid.

CMORPH and IMERG scorecards remain separate and are labelled **satellite precipitation estimates**, not gauge truth. The scheduled rainfall worker never uses future observations in a forecast; it only verifies a forecast after the exact accumulation interval and provider latency have elapsed. Credentials are mounted from a permission-restricted file outside the repository and are not copied into published products or Git.


## Public IMD exact-window verification

The public IMD real-time rainfall page provides a 0.25° daily gauge-gridded binary. MausamSetu validates the response content type, expected filename, exact byte length, little-endian float32 layout, physical value range and missing-value convention before sampling exact grid coordinates.

IMD daily rainfall represents the 24 hours ending **03:00 UTC (08:30 IST)**. Therefore the verifier does not compare it with a 00→00 model total. For a 00 UTC forecast initialization it reconstructs a model window from lead `L-21` through `L+3`, using provider accumulation metadata and only contiguous increments. ECMWF cumulative fields are differenced at the exact boundaries; NOAA accumulation origins are explicitly decoded.

A real +24 h check for the 26 September 2026 00 UTC initialization completed over **316 finite collocated India-grid cells**:

| Forecast | RMSE (mm) | MAE (mm) |
| --- | ---: | ---: |
| GFS | 10.200 | 3.970 |
| GEFS ensemble mean | 9.017 | 3.606 |
| IFS | 10.812 | 4.036 |
| AIFS | 8.349 | 3.233 |
| Equal central-field baseline | **8.098** | 3.260 |

This is a one-window verification result, not a skill ranking or production acceptance result. The existing adaptive 00→00 rainfall gate is deliberately **not** transferred to the 03→03 IMD accumulation window.

## Live-roster multi-variable shadow bootstrap

The live-roster research archive evaluates the exact GFS / GEFS ensemble mean / IFS / AIFS source set at +24, +48 and +72 hours. A six-initialization real-data bootstrap produced all nine candidate slots:

- rainfall: CMORPH primary reference plus separate IMERG cross-reference;
- temperature: delayed ERA5 analysis reference;
- wind: paired U/V gate with multivariate energy score against delayed ERA5 analysis.

Each candidate also evaluates four single-source and six two-source outages. Rainfall adds event-support/skill gates at 64.5, 115.6 and 204.5 mm/24 h. The current bootstrap has only two held-out initialization blocks and zero prospective blocks, so no candidate is production-accepted.

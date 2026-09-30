# Open-Meteo historical backfill role

MausamSetu keeps direct NOAA and ECMWF provider files as the canonical live forecast inputs. Open-Meteo is used only as a supplemental historical backfill route when a direct archived ECMWF run is unavailable or inconvenient to retrieve.

## Accepted use

The connector uses the Open-Meteo **Single Runs API** and always pins:

- the initialization timestamp with `run=`;
- a specific model identifier;
- explicit hourly variables;
- GMT/UTC timestamps;
- elevation=nan is requested so the API does not apply a user-elevation correction;
- cached response bytes plus SHA-256 provenance.

Current approved Open-Meteo fallback models:

| MausamSetu source | Open-Meteo model | Role |
| --- | --- | --- |
| IFS | `ecmwf_ifs025` | optional historical fallback |
| AIFS | `ecmwf_aifs025_single` | optional historical fallback |

GFS and GEFS are deliberately **not** substituted through Open-Meteo in the live-roster experiment. NOAA's public cloud archives are the backfill source for those models. In testing, archived GFS Single Runs returned null fields for the selected run, and Open-Meteo HGEFS is not treated as an identity-equivalent replacement for NOAA GEFS.

## Derived fields

Open-Meteo returns hourly precipitation, 2 m temperature, 10 m wind speed and wind direction. MausamSetu:

1. sums exactly 24 hourly precipitation values for each +24/+48/+72 accumulation window;
2. takes instantaneous temperature at the requested valid time;
3. converts wind speed from km/h to m/s;
4. converts meteorological wind direction to paired U/V components;
5. rejects incomplete/null/negative rainfall windows.

The normalized fallback is tagged as Open-Meteo-derived and never replaces the direct-provider provenance record silently.

## Scientific boundary

Open-Meteo data accelerate retrospective bootstrap only. They **never increment the prospective validation counter**. Direct-provider live ingestion remains the production-facing path.

Open-Meteo's free public API is suitable here only for non-commercial research use and has published request limits. An institutional/commercial deployment must either retain direct-provider feeds, use an appropriate paid Open-Meteo service, or self-host under the applicable licence and infrastructure policy.

References:

- https://open-meteo.com/en/docs/single-runs-api
- https://open-meteo.com/en/docs/previous-runs-api
- https://open-meteo.com/en/terms

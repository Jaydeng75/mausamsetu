# Live global and near-real-time rainfall release — 27 September 2026

MausamSetu now has three distinct data modes: India live, Global live, and a separate WeatherBench 2 historical benchmark. India live uses GFS, GEFS provider ensemble statistics and AIFS at six-hour leads, with IFS available at daily leads from +24 to +168 h on the 1° browser grid. Global live uses all four source products on a 2° browser grid at daily leads.

The live equal blend is an uncalibrated equal-source central-field baseline. GEFS contributes one provider ensemble-mean field, not one vote per ensemble member. Provider spread is retained separately and is not treated as calibrated predictive uncertainty.

## Source integrity

GFS and GEFS come from NOAA NOMADS; IFS and AIFS come from ECMWF Open Data. Provider files are checked for initialization, lead, units and grid geometry before publication. Published browser products have checksummed provenance and do not substitute synthetic values when a source fails.

GEFS ensemble size is read from the GRIB numberOfForecastsInEnsemble metadata rather than hard-coded. The current provider statistic reports 30 forecasts in that field, and that provenance is stored with the product.

## Rainfall verification

NOAA CMORPH2 NRT 0.25° half-hourly rainfall rates are integrated over the exact 24-hour forecast window and area-averaged to the India grid. NASA GPM IMERG Early V07 one-day GIS accumulation is independently decoded and area-averaged to the same grid. Both remain labelled satellite precipitation references, never gauge truth, and their scorecards are never pooled.

The first end-to-end reference cycle completed with both CMORPH and IMERG and no deferred reference. It verified the 25 September 00 UTC +24 h India forecast after the rainfall references became available.

## Secret handling and services

IMERG authentication is supplied through a permission-restricted local credential file mounted read-only into the rainfall worker. The repository contains only an empty placeholder. No secret is exposed to frontend code or public products.

Docker runs one forecast-maintenance worker plus a rainfall-verification worker. The forecast worker refreshes India first and global second, eliminating provider races between domains. Immutable product files, atomic latest pointers, disk-space guards, source-health checks and checksum-backed backups protect the last intact publication while degraded source availability remains explicit.

## Scientific boundary

The expanded live roster does not make historical learned weights production-valid. Existing IFS/Pangu temperature and IFS/GraphCast rainfall experiments remain retrospective research evidence. A learned live blend still requires a matched multi-season archive for the exact GFS/GEFS/IFS/AIFS roster, source calibration, held-out region/season/extreme evaluation, missing-source acceptance and prospective shadow evaluation. NCUM/NEPS and IMD can be added when authorized access becomes available.

No official warning, institutional approval or India-wide forecast advantage is claimed by this release.

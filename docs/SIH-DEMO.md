# SIH26081 demonstration guide

## Opening

“MausamSetu is an India-first forecast-fusion workbench. We separate live numerical forecasts, reproducible research experiments, observation/context access, and clearly labeled simulations.”

## Five-minute demonstration

| Time | Show | Defensible statement |
| --- | --- | --- |
| 0:00–0:40 | India map, GFS/GEFS/IFS/AIFS, selected location and time | These are decoded numerical forecasts with initialization, valid interval, checksum and source provenance. GEFS is explicitly an ensemble mean. |
| 0:40–1:10 | Source comparison and forecast age | The live public view is an equal-weight deterministic baseline, not a calibrated AI forecast. |
| 1:10–1:45 | India observations | Show the real IMD 0.25° gauge-grid +24 scorecard and its exact 03→03 UTC window, then separate CMORPH/IMERG satellite verification. No source is labelled raw station truth. |
| 1:45–2:25 | Multi-variable live-roster matrix | Show GFS/GEFS/IFS/AIFS candidates for rain, temperature and paired U/V wind at +24/+48/+72 h. Emphasize chronological train/selection/test separation and zero prospective blocks. |
| 2:25–3:20 | Extremes, outages and shadow mode | Show 64.5/115.6/204.5 mm event-support gates and the 10 missing-source scenarios per candidate. Inspect a +24/+48/+72 research shadow point only on a trained 00 UTC cycle; otherwise show deliberate withholding. |
| 3:20–4:00 | Release evidence / operations | Show checksums, tests, source freshness, backup/recovery evidence and explicit outage behavior. |
| 4:00–4:30 | Labeled synthetic workbench | Demonstrate interaction patterns that require richer calibrated live distributions; state clearly that the inputs are synthetic. |
| 4:30–5:00 | Acceptance gates | Latest-cycle NCMRWF feeds, prospective/multi-season skill, independent temperature/wind observations, real institutional identity values, approved hosting and shadow acceptance remain external gates. IMD exact-window rainfall collocation, outage matrices and extreme-event gates are already implemented. |

## Technical answers

**Did you prove better forecasts everywhere?** No. The temperature and rainfall improvements are bounded retrospective experiments with stated references, dates, grids and limitations. They do not establish India-wide operational superiority.

**What does the rainfall experiment establish?** In its 2020 held-out regional experiment, adaptive CRPS is lower than the static mixture and its initialization-block interval is below zero. It uses ERA5 rather than independent gauges and only one held-out case exceeds 115.6 mm/24h, so it does not establish severe-tail operational skill.

**Do you have IMD data?** Yes for the public daily gauge-grid product. MausamSetu validates IMD's public 0.25° real-time binary and reconstructs the four model rainfall totals on the same 03:00→03:00 UTC window before scoring. A real 26 September 00 UTC +24 case produced 316 finite collocated cells. The separate 2020 NetCDF remains staged for historical research, and this gauge-grid product is not raw station truth.

**Are NCUM and NEPS live?** No. A real delayed NEPS research sample exists through TIGGE/ECDS. No verified latest-cycle NCUM or NEPS feed is configured, and NCUM remains an institutional access dependency.

**What is MOSDAC doing?** Public catalogue discovery identifies current INSAT rainfall products, but numerical HDF5 download requires an authorized MOSDAC account. Catalogue visibility is not mislabeled as downloaded observations.

**Why not put research weights in today's map?** The research source rosters differ from the live GFS/GEFS/IFS/AIFS roster. Transferring weights would be scientifically unjustified.

**What is ready today?** A running research deployment with genuine GFS/GEFS/IFS/AIFS India and global ingestion, CMORPH/IMERG post-event rainfall verification, delayed NEPS research compatibility, staged IMD rainfall, adaptive research experiments, evidence/replay tooling, and operational recovery controls. It is not an authorized warning service.


**What does the live-roster shadow result establish?** The current GFS/GEFS/IFS/AIFS bootstrap has 7 non-overlapping 00 UTC +24 h blocks, split 4 train / 1 selection / 2 held-out. Adaptive CRPS is lower than static on both CMORPH and IMERG, but the CMORPH 95% initialization-block interval still crosses zero and there are 0 prospective blocks. It is therefore provisional bootstrap evidence, not an operational accuracy claim.

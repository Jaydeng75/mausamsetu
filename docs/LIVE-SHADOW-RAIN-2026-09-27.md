# Live-roster rainfall shadow experiment — 27 September 2026

MausamSetu now runs a separate rainfall shadow-learning path for the exact live India source roster:

- GFS deterministic forecast
- GEFS provider ensemble mean
- IFS deterministic forecast
- AIFS deterministic forecast

The public forecast is unchanged. Shadow artifacts are research-only and carry `production_active: false`.

## Scientific contract

The first operational shadow experiment is deliberately limited to **00 UTC +24 h rainfall**. This gives adjacent, non-overlapping 24-hour target windows. Six-hour and 12 UTC operational cycles remain archived but do not enter this train/selection/test experiment.

CMORPH2 NRT is used as the primary satellite reference for fitting/selection. IMERG Early V07 is evaluated independently on the same held-out initialization blocks. The references are never pooled and neither is called gauge truth.

Features are available at initialization time only: latitude, longitude, lead, seasonal sine/cosine, four source rainfall forecasts, source mean, source standard deviation and source range. Observation values are targets only and never gate features.

The source forecasts are treated as an **empirical point-mixture**, not calibrated predictive distributions. Consequently, source weights and threshold exceedance mass are not advertised as calibrated probabilities.

## Chronological split and gates

Initialization blocks remain intact and are ordered chronologically. The oldest ~60% train the gate, the next ~20% choose regularization, and the newest remainder are held out. No grid-cell random split is used.

A provisional research candidate requires at least **6** eligible daily initialization blocks.

Production acceptance is deliberately much stricter and cannot be satisfied by retrospective backfill alone. It requires all of:

- at least **30** total daily initialization blocks;
- at least **10 prospective blocks** initialized after the shadow-deployment timestamp stored in `/data/shadow-rain/config.json`;
- at least **6 held-out blocks**;
- adaptive CRPS below the static blend on CMORPH with a block-bootstrap 95% interval below zero;
- the same held-out improvement condition independently on IMERG;
- separate institutional/scientific review.

Even satisfying these automatic gates does not itself authorize operational warnings.

## Private bootstrap

`mausam.shadow_backfill` can retrieve recent historical 00 UTC +24 h four-source cycles into the private shadow archive without changing public forecast pointers. NOAA GEFS uses the NOMADS filter when available and falls back to NOAA's public cloud archive for older cycles. The backfill also obtains exact-window CMORPH and IMERG references.

Backfilled initializations are bootstrap evidence only. The prospective counter starts from the immutable runtime deployment timestamp.

## Artifacts

Private runtime artifacts:

- `/data/shadow-rain/forecasts/` — compact rainfall-only forecast archive;
- `/data/shadow-rain/model/candidate.json` — current shadow gate;
- `/data/shadow-rain/model/status.json` — evaluation report;
- `/data/shadow-rain/latest-shadow.json` — current shadow inference;
- `/data/shadow-rain/config.json` — prospective start/policy.

Public evidence projection:

- `/public/shadow-rain-status.json`
- backend: `GET /public/shadow-rain`
- frontend: `/sih`

The public evidence projection contains status and scores, not Earthdata credentials or raw restricted observations.

## Current bootstrap status

As of 27 September 2026, the running shadow archive contains **7 non-overlapping daily 00 UTC +24 h initialization blocks** matched to both CMORPH and IMERG. All 7 are bootstrap blocks; **0 prospective blocks** are counted because the prospective clock starts from the recorded shadow-deployment timestamp.

The current chronological split is 4 train / 1 selection / 2 held-out daily blocks. This is much too small for an acceptance claim.

Held-out bootstrap scores:

| Reference | Equal CRPS | Static CRPS | Adaptive CRPS | Adaptive − static 95% block interval |
| --- | ---: | ---: | ---: | ---: |
| CMORPH | 3.6216 | 3.6029 | **3.5514** | **[-0.1174, 0.0012]** |
| IMERG | 3.0990 | 3.0671 | **2.9885** | **[-0.0933, -0.0747]** |

The adaptive point estimate is lower on both references, but the CMORPH interval still crosses zero and only two held-out daily blocks exist. Therefore the result is reported as **provisional bootstrap evidence only**. `acceptance_passed` remains false and the public equal baseline remains active.

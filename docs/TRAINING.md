# Training and scientific acceptance

The implemented production-engine candidate is a small **linear softmax gate**, trained with empirical distribution-mixture CRPS and regularization. It is not a new global weather model. The optional PyTorch code remains a separate experiment.

`mausam.adaptive` fits context-dependent source weights. Its features are latitude, longitude, lead time, seasonal sine/cosine, and each calibrated source's mean and spread. Named weather-regime classifications are not yet validated or implemented in this gate.

## Training contract

The NPZ archive must contain `features` (case × feature), `samples` (case × source × member), `observations` (case), and the following case-length arrays:

- `decision_time`, `valid_end`, `observation_available_at`, `feature_available_at`: Unix seconds, explicitly derived from UTC metadata.
- `event_id`: event/time-block identifiers. An event must not cross training and test partitions.
- Optional `case_weight`: nonnegative geographical/sample weights.

`metadata` is a scalar JSON string with `source_ids`, `feature_names`, `variable`, `units`, `data_kind`, `reference`, `calibration_available_at`, and `upstream_training_audited`.

Source distributions must already have been calibrated on an earlier, separate period. Do not supply raw deterministic forecasts and relabel their spread as calibrated uncertainty. Audit upstream AI-model training periods and retrospective initialization separately.

```sh
PYTHONPATH=backend python -m mausam.train matched.npz \
  --output data/models/candidate-v1 \
  --train-end 2021-12-31T00:00:00Z \
  --test-start 2022-02-01T00:00:00Z
```

The dates above are examples, not a claim that the required archive exists. The CLI rejects hindsight features, overlapping events, invalid timestamps, and mismatched arrays. It reports every individual source, the equal distribution mixture, and the learned blend on the held-out partition.

Candidate artifacts are JSON with SHA-256 manifests; no executable pickle is loaded. A candidate is not automatically promoted. `eligible_for_production` remains false until an independent, documented acceptance review covers actual operational sources, seasons, regions, extremes, calibration and degraded-source configurations.

`mausam.registry.activate` records the reviewer, reason, source/evaluation hashes and previous version. Production activation is protected by the API's approver role. The published run pins the exact approved artifact. Filesystem permissions and operator controls remain essential: a normal local audit directory is not a tamper-proof external ledger.

The current tests prove algorithm and publication mechanics using synthetic fixtures. They do **not** establish India-wide forecast improvement. The public map deliberately remains an uncalibrated GFS/AIFS baseline until a scientifically accepted real-source model is available.


## Live-roster rainfall shadow path

The deployed rainfall shadow path is intentionally separate from production model promotion. It uses the exact live source roster **GFS / GEFS ensemble mean / IFS / AIFS** and currently trains only on **00 UTC +24 h rainfall**, which gives non-overlapping daily target windows.

The gate input kind is `source_point_mixture`. Each source contributes one rainfall point forecast; GEFS contributes the provider ensemble mean as one source. This is different from `calibrated_samples`: shadow weights and source-mixture exceedance mass must not be described as calibrated probabilities.

CMORPH is the primary fitting/selection reference. IMERG is evaluated independently on the same held-out blocks. Grid cells are not randomly split across train/test. Entire daily initialization blocks are ordered chronologically.

Automatic gates:

- 6 daily blocks: minimum for a provisional research candidate;
- 30 daily blocks: minimum total acceptance evidence;
- 10 blocks initialized after the recorded shadow-deployment timestamp: minimum prospective evidence;
- 6 held-out blocks;
- adaptive-minus-static CRPS 95% block-bootstrap interval below zero on CMORPH;
- independently, the same condition on IMERG.

All automatic conditions can pass while `eligible_for_production` remains false. Institutional scientific review is still required.


## Multi-variable live-roster acceptance matrix

The newer `mausam.multi_shadow` path extends the exact live GFS / GEFS ensemble mean / IFS / AIFS roster to separate +24, +48 and +72 h candidates.

### Rainfall

- empirical point-mixture CRPS;
- CMORPH primary fitting/selection reference;
- IMERG independent held-out cross-reference;
- thresholds 64.5 / 115.6 / 204.5 mm per 24 h;
- declared minimum independent held-out event blocks at each threshold;
- no transfer of the 00→00 gate to the IMD 03→03 accumulation window.

### Temperature

- scalar point-mixture CRPS;
- delayed ERA5 exact-valid-time analysis reference;
- numerical evidence can progress, but ERA5 is reanalysis, so automatic production acceptance stays disabled pending independent observational review.

### Wind

- one shared source-weight gate for paired U/V vectors;
- multivariate energy score;
- U/V/vector/speed diagnostics against delayed ERA5 analysis;
- scalar speed is never blended independently from direction.

### Missing-source acceptance

Every candidate evaluates all 10 combinations consisting of:

- 4 single-source outages;
- 6 two-source outages.

For each outage the adaptive mask gives missing sources zero weight. Acceptance requires the degraded adaptive candidate to beat the equal-weight fallback with an initialization-block confidence interval and to stay within a declared degradation bound relative to the full-source adaptive candidate. An outage configuration is not authorized merely because the software can mathematically re-normalize its weights.

### Event-count and prospective gates

The same research boundary remains:

- at least 6 blocks for a provisional candidate;
- at least 30 total independent daily blocks;
- at least 10 prospective blocks after the recorded deployment timestamp;
- at least 6 held-out blocks;
- source-specific skill/uncertainty gates;
- rainfall independent-reference, missing-source and extreme-event gates;
- institutional scientific approval.

Historical/Open-Meteo backfills may increase bootstrap sample size but never increment the prospective counter.

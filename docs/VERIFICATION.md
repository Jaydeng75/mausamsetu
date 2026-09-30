# Observation import and verification

Use `mausam.verify` after quality-controlled observations become available. The importer does not guess grids, units, rainfall windows or timestamp meanings.

```sh
PYTHONPATH=backend python -m mausam.verify RUN_ID observations.npy observations.json --archive data
```

The numerical file is a two-dimensional latitude × longitude NumPy array. Nonfinite values represent missing observations. For station data, perform and validate collocation first; do not pretend a station observes every grid cell.

The sidecar JSON must contain:

| Field | Meaning |
| --- | --- |
| `reference_id`, `reference_kind`, `revision` | Stable product identity; kind is gauge_analysis, station, satellite, radar, reanalysis or synthetic. |
| `data_kind` | forecast for genuine data, synthetic only for synthetic fixtures. |
| `sha256`, `licence_reference` | Exact observation-file checksum and permitted-use reference. |
| `available_at` | When the observation revision became available, not its valid time. |
| `valid_start`, `valid_end` | Exact UTC interval matching the forecast. |
| `variable`, `units` | Must match the published forecast. |
| `latitude`, `longitude` | Coordinates must match exactly; the importer does not silently interpolate. |
| `region` | Optional descriptive label for this evaluated subset. |

The importer verifies the published forecast and archived source checksums, rejects incompatible or future observation releases, and writes an immutable verification report plus a reference-labeled index. Repeating the same import is idempotent.

Scores include RMSE, MAE, bias, CRPS, Brier score, event contingency counts and CSI/POD/FAR where defined. These initial grid reports use equal valid-cell weights; they are not area-weighted global scores. Keep gauge, satellite and reanalysis scorecards separate.

`available_skill(root, decision_time, reference_id, data_kind)` selects only verification information available before a new forecast decision. Observation revisions retain separate identities. Do not pool revisions or references into an unlabeled accuracy number.

A real 2020 IMD 0.25° daily gridded-rainfall NetCDF is staged privately with checksum and decoded metadata. It is **not yet imported as verification truth** because the file does not encode accumulation bounds; its date labels must be mapped to the exact IMD reporting window and matched to an identical forecast accumulation before scoring.

The automated workflow still needs a provider-specific, authorized observation-ingestion schedule and scientifically reviewed QC/collocation. This module is the verified publication-to-observation step, not evidence that an operational IMD feed has been connected.

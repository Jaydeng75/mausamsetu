"""Train/review candidates using explicitly time-aligned, pre-calibrated NPZ data.

See docs/TRAINING.md for the contract. No random row split is allowed.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
import numpy as np
from .adaptive import crps_terms, fit_gate, mixture_crps, predict_weights, save_candidate


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Split times require an explicit timezone")
    return parsed.timestamp()


def train_archive(path, output, train_end, test_start):
    with np.load(path, allow_pickle=False) as archive:
        data = {name: archive[name] for name in archive.files}
    required = ["features", "samples", "observations", "decision_time", "valid_end",
                "observation_available_at", "feature_available_at", "event_id", "metadata"]
    if any(key not in data for key in required):
        raise ValueError("Training archive is missing required availability/provenance fields")
    meta = json.loads(str(data["metadata"].item()))
    x, s, y = data["features"], data["samples"], data["observations"]
    n = len(y)
    if any(data[key].shape != (n,) for key in required[3:-1]) or x.shape[0] != n or s.shape[0] != n:
        raise ValueError("Unaligned archive dimensions")
    for key in ["decision_time", "valid_end", "observation_available_at", "feature_available_at"]:
        if not np.isfinite(data[key]).all():
            raise ValueError("Nonfinite timestamp in training archive")
    if np.any(data["feature_available_at"] > data["decision_time"]):
        raise ValueError("Hindsight feature detected")
    if np.any(data["valid_end"] < data["decision_time"]) or np.any(data["observation_available_at"] < data["valid_end"]):
        raise ValueError("Invalid forecast or observation availability")
    end, start = timestamp(train_end), timestamp(test_start)
    if end >= start:
        raise ValueError("Training must precede held-out testing")
    if timestamp(meta["calibration_available_at"]) > float(data["decision_time"].min()):
        raise ValueError("Source calibration used future observations")
    train = (data["valid_end"] <= end) & (data["observation_available_at"] <= end)
    test = data["decision_time"] >= start
    if train.sum() < 30 or test.sum() < 30:
        raise ValueError("At least 30 cases are required in each chronological partition")
    if set(data["event_id"][train]) & set(data["event_id"][test]):
        raise ValueError("Weather events overlap training and testing")
    if len(meta["source_ids"]) != s.shape[1] or len(set(meta["source_ids"])) != s.shape[1]:
        raise ValueError("Invalid source roster")
    if meta["data_kind"] not in ["forecast", "synthetic"]:
        raise ValueError("Invalid data kind")
    case_mass = data.get("case_weight", np.ones(n))
    model = fit_gate(x[train], s[train], y[train], case_weights=case_mass[train])
    model.update({key: meta[key] for key in ["source_ids", "feature_names", "variable", "units"]})
    if len(model["feature_names"]) != model["feature_count"]:
        raise ValueError("Invalid feature schema")
    model["validated_missing_source_patterns"] = []
    first, pair = crps_terms(s[test], y[test])
    weights = predict_weights(model, x[test], np.ones(s.shape[1], dtype=bool))
    equal = np.full_like(weights, 1/s.shape[1])
    learned_scores = mixture_crps(weights, first, pair)
    equal_scores = mixture_crps(equal, first, pair)
    mass = case_mass[test] / case_mass[test].sum()
    results = []
    means = s[test].mean(axis=-1)
    for name, w in [(source, np.broadcast_to(np.eye(s.shape[1])[i], weights.shape))
                    for i, source in enumerate(meta["source_ids"])]+[("Equal distribution mixture", equal), ("Adaptive blend", weights)]:
        error = np.sum(w*means, axis=-1)-y[test]
        results.append({"model": name, "crps": float(np.dot(mass, mixture_crps(w, first, pair))),
                        "rmse": float(np.sqrt(np.dot(mass, error**2))),
                        "mae": float(np.dot(mass, np.abs(error))), "bias": float(np.dot(mass, error))})
    events = np.unique(data["event_id"][test])
    differences = []
    for event in events:
        idx = data["event_id"][test] == event
        differences.append(float(np.average(learned_scores[idx]-equal_scores[idx], weights=mass[idx])))
    rng = np.random.default_rng(26081)
    boot = rng.choice(differences, size=(1000, len(events)), replace=True).mean(axis=1)
    interval = np.quantile(boot, [.025, .975]).tolist() if len(events) >= 2 else None
    improved = results[-1]["crps"] < min(row["crps"] for row in results[:-1])
    report = {"schema_version": 1, "data_kind": meta["data_kind"], "reference": meta["reference"],
        "train_end": train_end, "test_start": test_start, "calibration_available_at": meta["calibration_available_at"],
        "training_cases": int(train.sum()), "test_cases": int(test.sum()), "test_event_blocks": len(events),
        "scores": results, "crps_difference_vs_equal_95ci": interval,
        "upstream_training_audited": bool(meta.get("upstream_training_audited", False)),
        "acceptance_passed": bool(improved and len(events) >= 30 and interval is not None and interval[1] < 0),
        "eligible_for_production": False,
        "limitations": ["Source calibration is supplied; audit its training data separately.",
            "Intervals resample provided event blocks, not individual grid cells.",
            "A single experiment is not institutional scientific acceptance.",
            "Production eligibility requires a signed-off acceptance report covering operational sources, seasons and extremes."]}
    save_candidate(output, model, report)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--train-end", required=True)
    p.add_argument("--test-start", required=True)
    args = p.parse_args()
    print(json.dumps(train_archive(args.archive, args.output, args.train_end, args.test_start), indent=2))

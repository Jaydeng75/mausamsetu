"""Prospective live-roster rainfall archive, training, and shadow inference.

The shadow gate uses source point forecasts as an empirical mixture. It is not
source calibration and its exceedance mass is not a calibrated probability.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .adaptive import crps_terms, fit_gate, mixture_crps, predict_weights
from .science import blocked_bootstrap_difference, verification
from .storage import atomic_write, file_lock, json_bytes

SOURCES = ["GFS", "GEFS", "IFS", "AIFS"]
REFERENCE_IDS = ["noaa-cmorph2-nrt-025", "nasa-imerg-early-gis-v07"]
THRESHOLDS_MM = [64.5, 115.6]
SHADOW_CYCLE_HOUR = 0
SHADOW_LEAD_HOURS = 24
MIN_PROVISIONAL_EVENTS = 6
MIN_ACCEPTANCE_EVENTS = 30
MIN_PROSPECTIVE_EVENTS = 10


def utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp requires an explicit timezone")
    return parsed.astimezone(timezone.utc)
def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _product(path):
    path = Path(path)
    product = json.loads(path.read_text())
    if product.get("data_kind") != "forecast" or product.get("coverage", "india") != "india":
        raise ValueError("Shadow archive accepts India forecast products only")
    if product.get("calibrated") is not False:
        raise ValueError("Unexpected calibrated public product")
    if not all(source in product.get("sources", {}) for source in SOURCES):
        raise ValueError("Live roster is incomplete")
    if product.get("source_roles", {}).get("GEFS") != "ensemble_mean":
        raise ValueError("GEFS must remain an ensemble-mean source")
    return product


def archive_forecast(product_path, archive_dir):
    product_path, archive_dir = Path(product_path), Path(archive_dir)
    product = _product(product_path)
    archive_dir.mkdir(parents=True, exist_ok=True)
    stem = product["run_id"]
    metadata_path, values_path = archive_dir / f"{stem}.json", archive_dir / f"{stem}.npz"
    if metadata_path.exists():
        existing = json.loads(metadata_path.read_text())
        if not values_path.exists() or file_sha(values_path) != existing["values_sha256"]:
            raise ValueError("Existing shadow forecast checksum failed")
        return existing
    # Archive only shared daily leads; IFS need not supply intermediate 6-hour leads.
    shared = [h for h in product["leads"] if h % 24 == 0 and all(str(h) in product["sources"][s] for s in SOURCES)]
    if SHADOW_LEAD_HOURS not in shared:
        raise ValueError("Required daily rainfall lead missing")
    leads = np.asarray(shared, dtype=np.int16)
    latitude = np.asarray(product["latitude"], dtype=np.float32)
    longitude = np.asarray(product["longitude"], dtype=np.float32)
    rain = np.full((len(leads), len(SOURCES), len(latitude), len(longitude)), np.nan, dtype=np.float32)
    for li, lead in enumerate(leads):
        for si, source in enumerate(SOURCES):
            values = np.asarray(product["sources"][source][str(int(lead))]["rain"], dtype=float)
            if values.size != len(latitude) * len(longitude):
                raise ValueError("Rainfall grid size changed")
            rain[li, si] = values.reshape(len(latitude), len(longitude))
    temporary = values_path.with_suffix(".npz.part")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, leads=leads, latitude=latitude, longitude=longitude, rain=rain)
        stream.flush()
    temporary.replace(values_path)
    metadata = {
        "schema_version": 1,
        "run_id": product["run_id"],
        "initialization": product["initialization"],
        "retrieved_at": product["retrieved_at"],
        "source_ids": SOURCES,
        "source_status": product.get("source_status", {}),
        "source_roles": product.get("source_roles", {}),
        "forecast_sha256": file_sha(product_path),
        "values_file": values_path.name,
        "values_sha256": file_sha(values_path),
    }
    if metadata_path.exists():
        existing = json.loads(metadata_path.read_text())
        if existing.get("values_sha256") != metadata["values_sha256"]:
            raise ValueError("Immutable shadow forecast conflict")
    else:
        atomic_write(metadata_path, json_bytes(metadata))
    return metadata


def archive_public_forecasts(public_dir, archive_dir):
    archived = []
    for path in sorted(Path(public_dir).glob("public-*.json")):
        try:
            archived.append(archive_forecast(path, archive_dir)["run_id"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return archived


def _reference(path):
    path = Path(path)
    meta = json.loads(path.read_text())
    if meta.get("reference_id") not in REFERENCE_IDS:
        raise ValueError("Unsupported shadow reference")
    values_path = path.parent / meta["values_file"]
    coverage_path = path.parent / meta["coverage_file"]
    if file_sha(values_path) != meta["values_sha256"] or file_sha(coverage_path) != meta["coverage_sha256"]:
        raise ValueError("Reference checksum failed")
    values = np.load(values_path, allow_pickle=False)
    coverage = np.load(coverage_path, allow_pickle=False)
    return meta, values, coverage
def _forecast_archive(path):
    meta = json.loads(Path(path).read_text())
    values_path = Path(path).parent / meta["values_file"]
    if file_sha(values_path) != meta["values_sha256"]:
        raise ValueError("Forecast archive checksum failed")
    with np.load(values_path, allow_pickle=False) as data:
        return meta, {key: data[key] for key in data.files}


def _features(source_values, latitude, longitude, lead, initialization):
    day = utc(initialization).timetuple().tm_yday
    y, x = np.meshgrid(latitude, longitude, indexing="ij")
    mean = np.nanmean(source_values, axis=0)
    std = np.nanstd(source_values, axis=0)
    span = np.nanmax(source_values, axis=0) - np.nanmin(source_values, axis=0)
    columns = [y, x, np.full_like(y, lead), np.full_like(y, math.sin(day * 2 * math.pi / 366)),
               np.full_like(y, math.cos(day * 2 * math.pi / 366))]
    names = ["latitude", "longitude", "lead_hours", "day_sin", "day_cos"]
    for index, source in enumerate(SOURCES):
        columns.append(source_values[index])
        names.append(source.lower() + "_rain_mm")
    columns += [mean, std, span]
    names += ["source_mean_mm", "source_std_mm", "source_range_mm"]
    return np.stack(columns, axis=-1), names
def matched_cases(forecast_dir, reference_dir, reference_id):
    refs = {}
    for path in Path(reference_dir).glob(f"{reference_id}-*.json"):
        try:
            meta, values, coverage = _reference(path)
            refs[utc(meta["valid_end"])] = (meta, values, coverage)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    blocks = []
    for path in sorted(Path(forecast_dir).glob("public-*.json")):
        try:
            meta, data = _forecast_archive(path)
            init = utc(meta["initialization"])
            if init.hour != SHADOW_CYCLE_HOUR:
                continue
            latitude, longitude = data["latitude"], data["longitude"]
            for li, lead in enumerate(data["leads"].astype(int)):
                if int(lead) != SHADOW_LEAD_HOURS:
                    continue
                end = init + timedelta(hours=int(lead))
                if end not in refs:
                    continue
                ref, observed, coverage = refs[end]
                if utc(ref["valid_start"]) != end - timedelta(hours=24):
                    continue
                values = data["rain"][li].astype(float)
                if observed.shape != values.shape[1:] or coverage.shape != observed.shape:
                    raise ValueError("Reference and forecast grids differ")
                features, names = _features(values, latitude, longitude, int(lead), meta["initialization"])
                valid = np.isfinite(observed) & (coverage >= float(ref.get("minimum_target_coverage", 0.9)))
                valid &= np.isfinite(values).all(axis=0)
                if not valid.any():
                    continue
                area = np.cos(np.deg2rad(np.broadcast_to(latitude[:, None], observed.shape)))[valid]
                blocks.append({
                    "event_id": meta["initialization"],
                    "lead": int(lead),
                    "initialization": meta["initialization"],
                    "valid_end": end.isoformat(),
                    "available_at": ref["available_at"],
                    "reference_id": reference_id,
                    "features": features[valid],
                    "feature_names": names,
                    "samples": values[:, valid].T[:, :, None],
                    "observations": observed[valid].astype(float),
                    "case_weight": area.astype(float),
                })
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return blocks


def _concat(blocks):
    if not blocks:
        raise ValueError("No matched shadow cases")
    names = blocks[0]["feature_names"]
    if any(block["feature_names"] != names for block in blocks):
        raise ValueError("Shadow feature schemas differ")
    return {
        "features": np.concatenate([b["features"] for b in blocks]),
        "samples": np.concatenate([b["samples"] for b in blocks]),
        "observations": np.concatenate([b["observations"] for b in blocks]),
        "case_weight": np.concatenate([b["case_weight"] for b in blocks]),
        "event_id": np.concatenate([np.repeat(b["event_id"], len(b["observations"])) for b in blocks]),
        "feature_names": names,
    }
def _score(samples, observations, weights, case_weight):
    first, pair = crps_terms(samples, observations)
    mass = case_weight / case_weight.sum()
    central = np.sum(weights * samples[:, :, 0], axis=1)
    result = {
        "crps": float(np.dot(mass, mixture_crps(weights, first, pair))),
        "rmse": float(np.sqrt(np.dot(mass, (central - observations) ** 2))),
        "mae": float(np.dot(mass, np.abs(central - observations))),
        "bias": float(np.dot(mass, central - observations)),
    }
    thresholds = {}
    for threshold in THRESHOLDS_MM:
        probability = np.sum(weights * (samples[:, :, 0] > threshold), axis=1)
        thresholds[str(threshold)] = verification(central, observations, probability, threshold)
    result["thresholds"] = thresholds
    return result


def _weights_for_source(n, index, sources=len(SOURCES)):
    value = np.zeros((n, sources), dtype=float)
    value[:, index] = 1
    return value


def _event_times(blocks):
    events = {}
    for block in blocks:
        events.setdefault(block["event_id"], utc(block["initialization"]))
    return sorted(events, key=lambda name: events[name])
def train_shadow(forecast_dir, reference_dir, output_dir, reference_id="noaa-cmorph2-nrt-025", prospective_start=None):
    blocks = matched_cases(forecast_dir, reference_dir, reference_id)
    events = _event_times(blocks)
    event_times = {block["event_id"]: utc(block["initialization"]) for block in blocks}
    prospective_start = utc(prospective_start) if prospective_start else None
    prospective_events = [event for event in events if prospective_start and event_times[event] >= prospective_start]
    status = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_id": reference_id,
        "source_ids": SOURCES,
        "shadow_cycle_hour_utc": SHADOW_CYCLE_HOUR,
        "shadow_lead_hours": SHADOW_LEAD_HOURS,
        "event_blocks": len(events),
        "prospective_start": prospective_start.isoformat() if prospective_start else None,
        "prospective_event_blocks": len(prospective_events),
        "bootstrap_event_blocks": len(events) - len(prospective_events),
        "matched_windows": len(blocks),
        "state": "collecting",
        "acceptance_requirements": {
            "minimum_total_event_blocks": MIN_ACCEPTANCE_EVENTS,
            "minimum_prospective_event_blocks": MIN_PROSPECTIVE_EVENTS,
            "minimum_held_out_event_blocks": 6,
            "independent_reference": "nasa-imerg-early-gis-v07",
        },
        "acceptance_passed": False,
        "eligible_for_production": False,
        "limitations": [
            "The gate uses an uncalibrated mixture of source point forecasts.",
            "Satellite rainfall is a verification reference, not gauge truth.",
            "Production promotion is disabled; prospective and institutional acceptance remain separate.",
        ],
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if len(events) < MIN_PROVISIONAL_EVENTS:
        status["reason"] = f"Need at least {MIN_PROVISIONAL_EVENTS} independent initialization blocks for a provisional shadow candidate."
        atomic_write(output_dir / "status.json", json_bytes(status))
        return status
    n_train = max(3, int(len(events) * 0.6))
    n_select = max(1, int(len(events) * 0.2))
    if n_train + n_select >= len(events):
        n_select = 1
        n_train = len(events) - 2
    train_events = set(events[:n_train])
    select_events = set(events[n_train:n_train + n_select])
    test_events = set(events[n_train + n_select:])
    partitions = {
        "train": [b for b in blocks if b["event_id"] in train_events],
        "select": [b for b in blocks if b["event_id"] in select_events],
        "test": [b for b in blocks if b["event_id"] in test_events],
    }
    train = _concat(partitions["train"])
    select = _concat(partitions["select"])
    test = _concat(partitions["test"])
    candidates = []
    for regularization in [0.01, 0.03, 0.1, 0.3]:
        model = fit_gate(train["features"], train["samples"], train["observations"],
                         case_weights=train["case_weight"], regularization=regularization,
                         input_kind="source_point_mixture")
        model["feature_names"] = train["feature_names"]
        weights = predict_weights(model, select["features"], np.ones((len(select["observations"]), len(SOURCES)), bool))
        candidates.append((_score(select["samples"], select["observations"], weights, select["case_weight"])["crps"],
                           regularization))
    selected_regularization = min(candidates)[1]
    fit_blocks = partitions["train"] + partitions["select"]
    fit = _concat(fit_blocks)
    adaptive = fit_gate(fit["features"], fit["samples"], fit["observations"],
                        case_weights=fit["case_weight"], regularization=selected_regularization,
                        input_kind="source_point_mixture")
    adaptive.update({"feature_names": fit["feature_names"], "source_ids": SOURCES, "variable": "rain",
                     "units": "mm", "reference_id": reference_id, "trained_event_blocks": len(train_events | select_events),
                     "trained_leads": sorted({b["lead"] for b in fit_blocks})})
    static = fit_gate(np.zeros((len(fit["observations"]), 1)), fit["samples"], fit["observations"],
                      case_weights=fit["case_weight"], regularization=0,
                      input_kind="source_point_mixture")
    test_available = np.ones((len(test["observations"]), len(SOURCES)), dtype=bool)
    adaptive_weights = predict_weights(adaptive, test["features"], test_available)
    static_weights = predict_weights(static, np.zeros((len(test["observations"]), 1)), test_available)
    equal_weights = np.full_like(adaptive_weights, 1 / len(SOURCES))
    rows = []
    for index, source in enumerate(SOURCES):
        rows.append({"model": source, **_score(test["samples"], test["observations"],
                    _weights_for_source(len(test["observations"]), index), test["case_weight"])})
    rows += [
        {"model": "Equal point mixture", **_score(test["samples"], test["observations"], equal_weights, test["case_weight"])},
        {"model": "Static point mixture", **_score(test["samples"], test["observations"], static_weights, test["case_weight"])},
        {"model": "Adaptive point mixture", **_score(test["samples"], test["observations"], adaptive_weights, test["case_weight"])},
    ]
    first, pair = crps_terms(test["samples"], test["observations"])
    adaptive_error = mixture_crps(adaptive_weights, first, pair)
    static_error = mixture_crps(static_weights, first, pair)
    interval = blocked_bootstrap_difference(adaptive_error, static_error, test["event_id"], seed=26081, repetitions=1000)
    adaptive_row = rows[-1]
    static_row = rows[-2]
    cross_reference = None
    if reference_id == "noaa-cmorph2-nrt-025":
        cross_blocks = [b for b in matched_cases(forecast_dir, reference_dir, "nasa-imerg-early-gis-v07")
                        if b["event_id"] in test_events]
        if cross_blocks:
            cross = _concat(cross_blocks)
            cross_available = np.ones((len(cross["observations"]), len(SOURCES)), dtype=bool)
            cross_adaptive = predict_weights(adaptive, cross["features"], cross_available)
            cross_static = predict_weights(static, np.zeros((len(cross["observations"]), 1)), cross_available)
            cross_equal = np.full_like(cross_adaptive, 1 / len(SOURCES))
            cfirst, cpair = crps_terms(cross["samples"], cross["observations"])
            cadaptive_error = mixture_crps(cross_adaptive, cfirst, cpair)
            cstatic_error = mixture_crps(cross_static, cfirst, cpair)
            cevents = np.unique(cross["event_id"])
            cinterval = blocked_bootstrap_difference(cadaptive_error, cstatic_error, cross["event_id"],
                                                     seed=26082, repetitions=1000) if len(cevents) >= 2 else None
            cross_reference = {
                "reference_id": "nasa-imerg-early-gis-v07",
                "test_event_blocks": len(cevents),
                "scores": [
                    {"model": "Equal point mixture", **_score(cross["samples"], cross["observations"], cross_equal, cross["case_weight"])},
                    {"model": "Static point mixture", **_score(cross["samples"], cross["observations"], cross_static, cross["case_weight"])},
                    {"model": "Adaptive point mixture", **_score(cross["samples"], cross["observations"], cross_adaptive, cross["case_weight"])},
                ],
                "adaptive_minus_static_crps_95ci": cinterval,
            }
    enough = (len(events) >= MIN_ACCEPTANCE_EVENTS and len(test_events) >= 6
              and len(prospective_events) >= MIN_PROSPECTIVE_EVENTS)
    cross_ok = bool(cross_reference and cross_reference["test_event_blocks"] >= 6 and
                    cross_reference["scores"][-1]["crps"] < cross_reference["scores"][-2]["crps"] and
                    cross_reference["adaptive_minus_static_crps_95ci"] is not None and
                    cross_reference["adaptive_minus_static_crps_95ci"][1] < 0)
    passed = bool(enough and adaptive_row["crps"] < static_row["crps"] and interval[1] < 0 and cross_ok)
    report = {
        **status,
        "state": "shadow_candidate",
        "train_event_blocks": len(train_events),
        "selection_event_blocks": len(select_events),
        "test_event_blocks": len(test_events),
        "train_cases": len(train["observations"]),
        "selection_cases": len(select["observations"]),
        "test_cases": len(test["observations"]),
        "selected_regularization": selected_regularization,
        "scores": rows,
        "adaptive_minus_static_crps_95ci": interval,
        "cross_reference": cross_reference,
        "acceptance_passed": passed,
        "evidence_sufficient_for_acceptance": enough,
    }
    model = {**adaptive, "static_model": static, "evaluation": {
        "reference_id": reference_id, "test_events": sorted(test_events), "scores": rows,
        "adaptive_minus_static_crps_95ci": interval, "cross_reference": cross_reference,
    }}
    atomic_write(output_dir / "candidate.json", json_bytes(model))
    atomic_write(output_dir / "status.json", json_bytes(report))
    return report
def shadow_product(product_path, model_path, output_path):
    product = _product(product_path)
    if utc(product["initialization"]).hour != SHADOW_CYCLE_HOUR:
        raise ValueError("Shadow inference is withheld for an untrained initialization cycle")
    model = json.loads(Path(model_path).read_text())
    if model.get("input_kind") != "source_point_mixture" or model.get("source_ids") != SOURCES:
        raise ValueError("Shadow model roster or input kind differs")
    latitude = np.asarray(product["latitude"], dtype=float)
    longitude = np.asarray(product["longitude"], dtype=float)
    trained_leads = set(model.get("trained_leads", []))
    leads = [lead for lead in product["leads"] if lead in trained_leads
             and all(str(lead) in product["sources"][s] for s in SOURCES)]
    result = {"schema_version": 1, "data_kind": "shadow_forecast", "run_id": product["run_id"],
              "initialization": product["initialization"], "generated_at": datetime.now(timezone.utc).isoformat(),
              "source_ids": SOURCES, "reference_used_for_training": model["reference_id"],
              "input_kind": "source_point_mixture", "calibrated": False,
              "latitude": [float(v) for v in latitude], "longitude": [float(v) for v in longitude],
              "trained_leads": sorted(trained_leads), "leads": {}, "production_active": False}
    for lead in leads:
        values = np.stack([np.asarray(product["sources"][s][str(lead)]["rain"], dtype=float)
                           .reshape(len(latitude), len(longitude)) for s in SOURCES])
        valid = np.isfinite(values).all(axis=0)
        features, names = _features(values, latitude, longitude, lead, product["initialization"])
        if names != model["feature_names"]:
            raise ValueError("Shadow feature schema differs")
        flat = features.reshape(-1, features.shape[-1])
        valid_flat = valid.reshape(-1)
        weights = np.full((flat.shape[0], len(SOURCES)), np.nan)
        if valid_flat.any():
            weights[valid_flat] = predict_weights(
                model, flat[valid_flat], np.ones((int(valid_flat.sum()), len(SOURCES)), dtype=bool))
        central = np.sum(weights * values.reshape(len(SOURCES), -1).T, axis=1)
        nullable = lambda array: [float(value) if np.isfinite(value) else None for value in array]
        lead_result = {"mean_mm": nullable(central), "weights": {
            source: nullable(weights[:, index]) for index, source in enumerate(SOURCES)}}
        for threshold in THRESHOLDS_MM:
            mass = np.sum(weights * (values.reshape(len(SOURCES), -1).T > threshold), axis=1)
            lead_result[f"exceedance_mass_{threshold:g}mm"] = nullable(mass)
        result["leads"][str(lead)] = lead_result
    body = json_bytes(result)
    atomic_write(output_path, body)
    return result


def _refresh_shadow_unlocked(runtime, public_dir):
    runtime, public_dir = Path(runtime), Path(public_dir)
    shadow_root = runtime / "shadow-rain"
    forecast_archive = shadow_root / "forecasts"
    model_dir = shadow_root / "model"
    config_path = shadow_root / "config.json"
    shadow_root.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        config = json.loads(config_path.read_text())
        prospective_start = config["prospective_start"]
        utc(prospective_start)
    else:
        prospective_start = datetime.now(timezone.utc).isoformat()
        config = {"schema_version": 1, "prospective_start": prospective_start,
                  "policy": "Only initialization times at/after prospective_start count toward the prospective acceptance gate."}
        atomic_write(config_path, json_bytes(config))
    archive_public_forecasts(public_dir, forecast_archive)
    report = train_shadow(forecast_archive, runtime / "rain-references", model_dir,
                          prospective_start=prospective_start)
    public_status = {k: v for k, v in report.items() if k not in {"scores"}}
    if "scores" in report:
        public_status["scores"] = report["scores"]
    shadow_path = runtime / "shadow-rain" / "latest-shadow.json"
    if report.get("state") == "shadow_candidate":
        pointer = json.loads((public_dir / "latest.json").read_text())
        product_path = public_dir / pointer["path"]
        current = _product(product_path)
        if utc(current["initialization"]).hour == SHADOW_CYCLE_HOUR:
            shadow_product(product_path, model_dir / "candidate.json", shadow_path)
        else:
            shadow_path.unlink(missing_ok=True)
    atomic_write(public_dir / "shadow-rain-status.json", json_bytes(public_status))
    (public_dir / "shadow-rain-status.json").chmod(0o644)
    return report


def refresh_shadow(runtime, public_dir):
    shadow_root = Path(runtime) / "shadow-rain"
    shadow_root.mkdir(parents=True, exist_ok=True)
    with file_lock(shadow_root / ".refresh.lock"):
        return _refresh_shadow_unlocked(runtime, public_dir)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--public", required=True)
    args = parser.parse_args()
    with file_lock(Path(args.runtime) / ".shadow-rain.lock", blocking=False):
        print(json.dumps(refresh_shadow(args.runtime, args.public), indent=2))


if __name__ == "__main__":
    main()

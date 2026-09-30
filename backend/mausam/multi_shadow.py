"""Multi-variable live-roster shadow validation.

Per-lead scalar gates are used for rainfall and 2 m temperature. Wind uses one
shared source-weight gate for paired U/V vectors with the multivariate energy
score. All products remain research-only until prospective and review gates pass.
"""
import itertools
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .adaptive import crps_terms, fit_gate, mixture_crps, predict_weights
from .analysis_references import load_reference as load_analysis_reference
from .live_shadow import file_sha
from .science import blocked_bootstrap_difference, masked_softmax, verification
from .shadow_sources import LEADS, SOURCES, save_cycle
from .storage import atomic_write, file_lock, json_bytes

MIN_PROVISIONAL_EVENTS = 6
MIN_TOTAL_EVENTS = 30
MIN_PROSPECTIVE_EVENTS = 10
MIN_HELDOUT_EVENTS = 6
RAIN_THRESHOLDS = [64.5, 115.6, 204.5]
# Minimum number of independent held-out initialization blocks containing each IMD rainfall category.
RAIN_EXTREME_MIN_BLOCKS = {64.5: 4, 115.6: 3, 204.5: 2}
# A degraded-source candidate must still beat the equal fallback and remain reasonably close to full-source skill.
MISSING_SINGLE_MAX_DEGRADATION = 0.20
MISSING_PAIR_MAX_DEGRADATION = 0.40


def utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _archive(path):
    path = Path(path)
    meta = json.loads(path.read_text())
    values_path = path.parent / meta["values_file"]
    if file_sha(values_path) != meta["values_sha256"]:
        raise ValueError("Multi-shadow forecast archive checksum failed")
    with np.load(values_path, allow_pickle=False) as data:
        values = {key: data[key] for key in data.files}
    if meta.get("source_ids") != SOURCES or values["leads"].tolist() != LEADS:
        raise ValueError("Multi-shadow source roster or lead contract changed")
    return meta, values


def archive_public_product(product_path, archive_dir):
    product_path, archive_dir = Path(product_path), Path(archive_dir)
    product = json.loads(product_path.read_text())
    initialization = utc(product["initialization"])
    if product.get("data_kind") != "forecast" or product.get("coverage", "india") != "india" or initialization.hour != 0:
        raise ValueError("Only 00 UTC India forecast products enter multi-shadow")
    if product.get("calibrated") is not False or product.get("source_roles", {}).get("GEFS") != "ensemble_mean":
        raise ValueError("Unexpected live forecast semantics")
    latitude = np.asarray(product["latitude"], dtype=float)
    longitude = np.asarray(product["longitude"], dtype=float)
    arrays = {name: np.full((len(LEADS), len(SOURCES), len(latitude), len(longitude)), np.nan, dtype=np.float32)
              for name in ["rain", "temperature", "u", "v"]}
    for li, lead in enumerate(LEADS):
        for si, source in enumerate(SOURCES):
            fields = product.get("sources", {}).get(source, {}).get(str(lead))
            if not fields:
                raise ValueError("Complete four-source daily leads are required")
            for name in arrays:
                value = np.asarray(fields[name], dtype=float).reshape(len(latitude), len(longitude))
                if np.isinf(value).any() or not np.isfinite(value).any():
                    raise ValueError("No usable live field in multi-shadow archive")
                # Keep sparse missing cells as NaN. Scoring masks them per variable/lead.
                arrays[name][li, si] = value
    cycle = {
        "initialization": initialization.isoformat(), "source_ids": SOURCES, "leads": LEADS,
        "latitude": latitude.tolist(), "longitude": longitude.tolist(), "fields": arrays,
        "provenance": {"public_product": product["run_id"], "public_product_sha256": file_sha(product_path)},
    }
    return save_cycle(cycle, archive_dir)


def archive_public_forecasts(public_dir, archive_dir):
    result = []
    for path in sorted(Path(public_dir).glob("public-*.json")):
        try:
            result.append(archive_public_product(path, archive_dir))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return result


def _rain_references(folder, reference_id):
    refs = {}
    for path in Path(folder).glob(f"{reference_id}-*.json"):
        try:
            meta = json.loads(path.read_text())
            values_path, coverage_path = path.parent / meta["values_file"], path.parent / meta["coverage_file"]
            if file_sha(values_path) != meta["values_sha256"] or file_sha(coverage_path) != meta["coverage_sha256"]:
                continue
            refs[utc(meta["valid_end"])] = (
                meta, np.load(values_path, allow_pickle=False), np.load(coverage_path, allow_pickle=False)
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return refs


def _analysis_references(folder):
    refs = {}
    paths = list(Path(folder).glob("era5-analysis-*.json")) + list(Path(folder).glob("era5t-arco-*.json"))
    for path in paths:
        try:
            meta, values = load_analysis_reference(path)
            refs[utc(meta["valid_time"])] = (meta, values)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return refs


def _scalar_features(source_values, latitude, longitude, lead, initialization):
    day = utc(initialization).timetuple().tm_yday
    y, x = np.meshgrid(latitude, longitude, indexing="ij")
    columns = [y, x, np.full_like(y, lead), np.full_like(y, math.sin(day*2*math.pi/366)),
               np.full_like(y, math.cos(day*2*math.pi/366))]
    names = ["latitude", "longitude", "lead_hours", "day_sin", "day_cos"]
    for i in range(len(SOURCES)):
        columns.append(source_values[i]); names.append(f"source_{i}_value")
    columns += [np.mean(source_values, axis=0), np.std(source_values, axis=0),
                np.max(source_values, axis=0)-np.min(source_values, axis=0)]
    names += ["source_mean", "source_std", "source_range"]
    return np.stack(columns, axis=-1), names


def _wind_features(u, v, latitude, longitude, lead, initialization):
    day = utc(initialization).timetuple().tm_yday
    y, x = np.meshgrid(latitude, longitude, indexing="ij")
    columns = [y, x, np.full_like(y, lead), np.full_like(y, math.sin(day*2*math.pi/366)),
               np.full_like(y, math.cos(day*2*math.pi/366))]
    names = ["latitude", "longitude", "lead_hours", "day_sin", "day_cos"]
    for i in range(len(SOURCES)):
        columns += [u[i], v[i], np.hypot(u[i], v[i])]
        names += [f"source_{i}_u", f"source_{i}_v", f"source_{i}_speed"]
    columns += [u.mean(axis=0), v.mean(axis=0), np.std(np.hypot(u, v), axis=0)]
    names += ["mean_u", "mean_v", "speed_std"]
    return np.stack(columns, axis=-1), names


def scalar_cases(forecast_dir, variable, lead, reference_dir, reference_id):
    if variable == "rain":
        refs = _rain_references(reference_dir, reference_id)
    else:
        refs = _analysis_references(reference_dir)
    blocks = []
    for path in sorted(Path(forecast_dir).glob("multi-*.json")):
        try:
            meta, data = _archive(path)
            initialization = utc(meta["initialization"])
            li = data["leads"].tolist().index(lead)
            valid = initialization + timedelta(hours=lead)
            latitude, longitude = data["latitude"].astype(float), data["longitude"].astype(float)
            source_values = data[variable][li].astype(float)
            if variable == "rain":
                if valid not in refs:
                    continue
                reference, observed, coverage = refs[valid]
                mask = np.isfinite(observed) & (coverage >= float(reference.get("minimum_target_coverage", .9)))
            else:
                if valid not in refs:
                    continue
                reference, values = refs[valid]
                observed = values["temperature"].astype(float)
                mask = np.isfinite(observed)
            mask &= np.isfinite(source_values).all(axis=0)
            if not mask.any():
                continue
            features, names = _scalar_features(source_values, latitude, longitude, lead, meta["initialization"])
            area = np.cos(np.deg2rad(np.broadcast_to(latitude[:, None], observed.shape)))[mask]
            blocks.append({
                "event_id": meta["initialization"], "initialization": meta["initialization"], "lead": lead,
                "valid_time": valid.isoformat(), "reference_id": reference_id,
                "features": features[mask], "feature_names": names,
                "samples": source_values[:, mask].T[:, :, None], "observations": observed[mask],
                "case_weight": area,
            })
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return blocks


def wind_cases(forecast_dir, lead, reference_dir):
    refs = _analysis_references(reference_dir)
    blocks = []
    for path in sorted(Path(forecast_dir).glob("multi-*.json")):
        try:
            meta, data = _archive(path)
            initialization = utc(meta["initialization"])
            li = data["leads"].tolist().index(lead)
            valid = initialization + timedelta(hours=lead)
            if valid not in refs:
                continue
            reference, values = refs[valid]
            latitude, longitude = data["latitude"].astype(float), data["longitude"].astype(float)
            u, v = data["u"][li].astype(float), data["v"][li].astype(float)
            obs_u, obs_v = values["u"].astype(float), values["v"].astype(float)
            mask = np.isfinite(obs_u) & np.isfinite(obs_v) & np.isfinite(u).all(axis=0) & np.isfinite(v).all(axis=0)
            if not mask.any():
                continue
            features, names = _wind_features(u, v, latitude, longitude, lead, meta["initialization"])
            area = np.cos(np.deg2rad(np.broadcast_to(latitude[:, None], obs_u.shape)))[mask]
            vectors = np.stack([u[:, mask].T, v[:, mask].T], axis=-1)
            observations = np.stack([obs_u[mask], obs_v[mask]], axis=-1)
            blocks.append({
                "event_id": meta["initialization"], "initialization": meta["initialization"], "lead": lead,
                "valid_time": valid.isoformat(), "reference_id": reference["reference_id"],
                "features": features[mask], "feature_names": names, "vectors": vectors,
                "observations": observations, "case_weight": area,
            })
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return blocks


def _events(blocks):
    mapping = {}
    for block in blocks:
        mapping.setdefault(block["event_id"], utc(block["initialization"]))
    return sorted(mapping, key=lambda key: mapping[key]), mapping


def _split(blocks):
    events, mapping = _events(blocks)
    if len(events) < MIN_PROVISIONAL_EVENTS:
        return None
    n_train = max(3, int(len(events) * .6))
    n_select = max(1, int(len(events) * .2))
    if n_train + n_select > len(events) - 2:
        n_train = max(3, len(events) - 3)
        n_select = 1
    train = set(events[:n_train])
    selection = set(events[n_train:n_train+n_select])
    test = set(events[n_train+n_select:])
    return {
        "events": events, "event_times": mapping,
        "train_events": train, "selection_events": selection, "test_events": test,
        "train_blocks": [b for b in blocks if b["event_id"] in train],
        "selection_blocks": [b for b in blocks if b["event_id"] in selection],
        "test_blocks": [b for b in blocks if b["event_id"] in test],
    }


def _concat_scalar(blocks):
    if not blocks:
        raise ValueError("No scalar shadow cases")
    names = blocks[0]["feature_names"]
    if any(block["feature_names"] != names for block in blocks):
        raise ValueError("Scalar feature schema changed")
    return {
        "features": np.concatenate([b["features"] for b in blocks]),
        "samples": np.concatenate([b["samples"] for b in blocks]),
        "observations": np.concatenate([b["observations"] for b in blocks]),
        "case_weight": np.concatenate([b["case_weight"] for b in blocks]),
        "event_id": np.concatenate([np.repeat(b["event_id"], len(b["observations"])) for b in blocks]),
        "feature_names": names,
    }


def _concat_wind(blocks):
    if not blocks:
        raise ValueError("No wind shadow cases")
    names = blocks[0]["feature_names"]
    if any(block["feature_names"] != names for block in blocks):
        raise ValueError("Wind feature schema changed")
    return {
        "features": np.concatenate([b["features"] for b in blocks]),
        "vectors": np.concatenate([b["vectors"] for b in blocks]),
        "observations": np.concatenate([b["observations"] for b in blocks]),
        "case_weight": np.concatenate([b["case_weight"] for b in blocks]),
        "event_id": np.concatenate([np.repeat(b["event_id"], len(b["observations"])) for b in blocks]),
        "feature_names": names,
    }


def _scalar_score(samples, observations, weights, case_weight, thresholds=None):
    first, pair = crps_terms(samples, observations)
    mass = case_weight / case_weight.sum()
    central = np.sum(weights * samples[:, :, 0], axis=1)
    result = {
        "crps": float(np.dot(mass, mixture_crps(weights, first, pair))),
        "rmse": float(np.sqrt(np.dot(mass, (central-observations)**2))),
        "mae": float(np.dot(mass, np.abs(central-observations))),
        "bias": float(np.dot(mass, central-observations)),
    }
    if thresholds:
        result["thresholds"] = {}
        for threshold in thresholds:
            probability = np.sum(weights * (samples[:, :, 0] > threshold), axis=1)
            result["thresholds"][str(threshold)] = verification(central, observations, probability, threshold)
    return result


def energy_terms(vectors, observations):
    vectors = np.asarray(vectors, dtype=float)
    observations = np.asarray(observations, dtype=float)
    if vectors.ndim != 3 or vectors.shape[-1] != 2 or observations.shape != (len(vectors), 2):
        raise ValueError("Paired source U/V vectors and observations required")
    first = np.linalg.norm(vectors-observations[:, None, :], axis=-1)
    pair = np.linalg.norm(vectors[:, :, None, :]-vectors[:, None, :, :], axis=-1)
    return first, pair


def mixture_energy(weights, first, pair):
    return np.sum(weights*first, axis=-1)-.5*np.einsum("bi,bij,bj->b", weights, pair, weights)


def fit_vector_gate(features, vectors, observations, case_weights=None, regularization=.02, maxiter=250):
    x = np.asarray(features, dtype=float)
    vectors = np.asarray(vectors, dtype=float)
    if x.ndim != 2 or len(x) != len(vectors) or len(x) < 30 or not np.isfinite(x).all():
        raise ValueError("At least 30 finite vector training cases required")
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale < 1e-8, 1., scale)
    design = np.column_stack([np.ones(len(x)), (x-mean)/scale])
    first, pair = energy_terms(vectors, observations)
    mass = np.ones(len(x)) if case_weights is None else np.asarray(case_weights, dtype=float)
    mass = mass / mass.sum()
    shape = (design.shape[1], vectors.shape[1])
    def objective(flat):
        beta = flat.reshape(shape)
        weights = masked_softmax(design @ beta, np.ones((len(x), vectors.shape[1]), dtype=bool))
        loss = float(np.dot(mass, mixture_energy(weights, first, pair)))
        derivative = first - np.einsum("bij,bj->bi", pair, weights)
        dz = weights * (derivative-np.sum(derivative*weights, axis=1, keepdims=True))
        gradient = design.T @ (dz*mass[:, None])
        loss += regularization*np.sum(beta[1:]**2)
        gradient[1:] += 2*regularization*beta[1:]
        return loss, gradient.ravel()
    result = minimize(objective, np.zeros(np.prod(shape)), method="L-BFGS-B", jac=True,
                      bounds=[(-15.,15.)]*int(np.prod(shape)), options={"maxiter":maxiter})
    if not result.success or not np.isfinite(result.fun):
        raise ValueError("Vector gate optimizer did not converge")
    return {
        "schema_version": 1, "method": "linear-softmax-energy", "input_kind": "source_vector_point_mixture",
        "mean": mean.tolist(), "scale": scale.tolist(), "coefficients": result.x.reshape(shape).tolist(),
        "source_count": vectors.shape[1], "feature_count": x.shape[1], "regularization": regularization,
        "training_cases": len(x), "objective": float(result.fun),
    }


def _wind_score(vectors, observations, weights, case_weight):
    first, pair = energy_terms(vectors, observations)
    mass = case_weight / case_weight.sum()
    central = np.einsum("bi,bid->bd", weights, vectors)
    du, dv = central[:,0]-observations[:,0], central[:,1]-observations[:,1]
    speed = np.linalg.norm(central, axis=1)
    obs_speed = np.linalg.norm(observations, axis=1)
    return {
        "energy_score": float(np.dot(mass, mixture_energy(weights, first, pair))),
        "vector_rmse": float(np.sqrt(np.dot(mass, du**2+dv**2))),
        "u_rmse": float(np.sqrt(np.dot(mass, du**2))),
        "v_rmse": float(np.sqrt(np.dot(mass, dv**2))),
        "speed_mae": float(np.dot(mass, np.abs(speed-obs_speed))),
        "u_bias": float(np.dot(mass, du)), "v_bias": float(np.dot(mass, dv)),
    }


def _equal_weights(n, available):
    available = np.broadcast_to(np.asarray(available, dtype=bool), (n, len(SOURCES)))
    denominator=available.sum(axis=1,keepdims=True)
    return np.divide(available,denominator,out=np.zeros_like(available,dtype=float),where=denominator>0)


def _scalar_masked_features(features,samples,available):
    x=np.asarray(features,dtype=float).copy()
    raw=np.asarray(samples,dtype=float)[:,:,0]
    mask=np.broadcast_to(np.asarray(available,dtype=bool),(len(raw),len(SOURCES))).copy()
    mask &= np.isfinite(raw)
    count=mask.sum(axis=1)
    good=count>=2
    total=np.sum(np.where(mask,raw,0.),axis=1)
    mean=np.divide(total,count,out=np.zeros(len(raw)),where=count>0)
    filled=np.where(mask,raw,mean[:,None])
    centered=np.where(mask,raw-mean[:,None],0.)
    std=np.sqrt(np.divide(np.sum(centered**2,axis=1),count,out=np.zeros(len(raw)),where=count>0))
    low=np.min(np.where(mask,raw,np.inf),axis=1)
    high=np.max(np.where(mask,raw,-np.inf),axis=1)
    span=np.where(good,high-low,0.)
    x[:,5:5+len(SOURCES)]=filled
    x[:,5+len(SOURCES):5+len(SOURCES)+3]=np.column_stack([mean,std,span])
    return x,mask,good,filled


def _wind_masked_features(features,vectors,available):
    x=np.asarray(features,dtype=float).copy();vectors=np.asarray(vectors,dtype=float)
    mask=np.broadcast_to(np.asarray(available,dtype=bool),(len(vectors),len(SOURCES))).copy()
    mask &= np.isfinite(vectors).all(axis=2)
    count=mask.sum(axis=1);good=count>=2
    u,v=vectors[:,:,0],vectors[:,:,1];speed=np.hypot(u,v)
    mean_u=np.divide(np.sum(np.where(mask,u,0.),axis=1),count,out=np.zeros(len(vectors)),where=count>0)
    mean_v=np.divide(np.sum(np.where(mask,v,0.),axis=1),count,out=np.zeros(len(vectors)),where=count>0)
    mean_speed=np.divide(np.sum(np.where(mask,speed,0.),axis=1),count,out=np.zeros(len(vectors)),where=count>0)
    speed_std=np.sqrt(np.divide(np.sum(np.where(mask,(speed-mean_speed[:,None])**2,0.),axis=1),
                                count,out=np.zeros(len(vectors)),where=count>0))
    filled_u=np.where(mask,u,mean_u[:,None]);filled_v=np.where(mask,v,mean_v[:,None])
    for index in range(len(SOURCES)):
        base=5+3*index
        x[:,base]=filled_u[:,index];x[:,base+1]=filled_v[:,index]
        x[:,base+2]=np.hypot(filled_u[:,index],filled_v[:,index])
    x[:,5+3*len(SOURCES):5+3*len(SOURCES)+3]=np.column_stack([mean_u,mean_v,speed_std])
    return x,mask,good,np.stack([filled_u,filled_v],axis=-1)


def missing_patterns():
    patterns = []
    for missing_count in [1,2]:
        for missing in itertools.combinations(range(len(SOURCES)), missing_count):
            available = np.ones(len(SOURCES), dtype=bool)
            available[list(missing)] = False
            patterns.append((missing, available))
    return patterns


def _extreme_block_counts(blocks, thresholds=RAIN_THRESHOLDS):
    counts={str(threshold):0 for threshold in thresholds}
    for block in blocks:
        observed=np.asarray(block["observations"],dtype=float)
        if not np.isfinite(observed).any():
            continue
        maximum=float(np.nanmax(observed))
        for threshold in thresholds:
            if maximum>=threshold:
                counts[str(threshold)]+=1
    return counts


def _extreme_gate(counts):
    return all(counts.get(str(threshold),0)>=minimum
               for threshold,minimum in RAIN_EXTREME_MIN_BLOCKS.items())


def _event_interval(errors_a, errors_b, event_ids, seed):
    unique = np.unique(event_ids)
    return blocked_bootstrap_difference(errors_a, errors_b, event_ids, seed=seed, repetitions=1000) if len(unique) >= 2 else None


def _rain_extreme_evidence(test, adaptive_score, static_score):
    rows = {}
    for threshold, minimum_blocks in RAIN_EXTREME_MIN_BLOCKS.items():
        key = str(threshold)
        observed_event = np.asarray(test["observations"]) > threshold
        event_blocks = np.unique(np.asarray(test["event_id"])[observed_event])
        adaptive = adaptive_score["thresholds"][key]
        static = static_score["thresholds"][key]
        brier_ok = adaptive["brier"] <= static["brier"]
        csi_ok = (static["csi"] is None or adaptive["csi"] is not None and adaptive["csi"] >= static["csi"])
        support_ok = len(event_blocks) >= minimum_blocks
        rows[key] = {
            "threshold_mm": threshold,
            "observed_event_cells": int(observed_event.sum()),
            "event_blocks_with_observed_event": int(len(event_blocks)),
            "minimum_event_blocks": minimum_blocks,
            "adaptive_brier": adaptive["brier"],
            "static_brier": static["brier"],
            "adaptive_csi": adaptive["csi"],
            "static_csi": static["csi"],
            "adaptive_pod": adaptive["pod"],
            "adaptive_far": adaptive["far"],
            "support_pass": bool(support_ok),
            "skill_pass": bool(brier_ok and csi_ok),
            "acceptance_pass": bool(support_ok and brier_ok and csi_ok),
        }
    return rows


def _scalar_missing_matrix(model, test, full_score):
    first, pair = crps_terms(test["samples"], test["observations"])
    rows = []
    for missing, available in missing_patterns():
        requested = np.broadcast_to(available, (len(test["observations"]), len(SOURCES)))
        masked_features,mask,good,_ = _scalar_masked_features(
            test["features"],test["samples"],requested
        )
        if not good.all():
            raise ValueError("Declared missing-source pattern leaves fewer than two experts")
        adaptive_weights = predict_weights(model, masked_features, mask)
        equal_weights = _equal_weights(len(test["observations"]), mask)
        adaptive = _scalar_score(test["samples"], test["observations"], adaptive_weights, test["case_weight"])
        equal = _scalar_score(test["samples"], test["observations"], equal_weights, test["case_weight"])
        interval = _event_interval(
            mixture_crps(adaptive_weights, first, pair),
            mixture_crps(equal_weights, first, pair),
            test["event_id"], 27000 + sum(missing)
        )
        relative = adaptive["crps"]/full_score["crps"]-1
        bootstrap_pass = bool(adaptive["crps"] <= equal["crps"] and interval is not None and interval[1] <= 0)
        rows.append({
            "missing": [SOURCES[i] for i in missing], "available": available.tolist(),
            "adaptive_crps": adaptive["crps"], "equal_crps": equal["crps"],
            "adaptive_minus_equal_95ci": interval,
            "relative_crps_vs_full_adaptive": relative,
            "bootstrap_pass": bootstrap_pass,
            "maximum_relative_degradation": (
                MISSING_SINGLE_MAX_DEGRADATION if len(missing)==1 else MISSING_PAIR_MAX_DEGRADATION
            ),
            "acceptance_pass": bool(
                bootstrap_pass and relative <= (
                    MISSING_SINGLE_MAX_DEGRADATION if len(missing)==1 else MISSING_PAIR_MAX_DEGRADATION
                )
            ),
        })
    return rows


def train_scalar_model(blocks, variable, lead, prospective_start, cross_blocks=None, require_independent=False):
    split = _split(blocks)
    events, mapping = _events(blocks)
    prospective_start = utc(prospective_start)
    prospective = [event for event in events if mapping[event] >= prospective_start]
    status = {
        "state": "collecting" if split is None else "shadow_candidate",
        "variable": variable, "lead": lead, "source_ids": SOURCES, "event_blocks": len(events),
        "bootstrap_event_blocks": len(events)-len(prospective), "prospective_event_blocks": len(prospective),
        "prospective_start": prospective_start.isoformat(), "acceptance_passed": False,
        "eligible_for_production": False,
        "acceptance_requirements": {
            "minimum_total_event_blocks": MIN_TOTAL_EVENTS,
            "minimum_prospective_event_blocks": MIN_PROSPECTIVE_EVENTS,
            "minimum_held_out_event_blocks": MIN_HELDOUT_EVENTS,
        },
    }
    if split is None:
        status["reason"] = f"Need at least {MIN_PROVISIONAL_EVENTS} independent daily blocks"
        return None, status
    train, selection, test = map(_concat_scalar, [split["train_blocks"], split["selection_blocks"], split["test_blocks"]])
    candidates = []
    for regularization in [.01,.03,.1,.3]:
        candidate = fit_gate(train["features"], train["samples"], train["observations"],
                             case_weights=train["case_weight"], regularization=regularization,
                             input_kind="source_point_mixture")
        candidate["feature_names"] = train["feature_names"]
        weights = predict_weights(candidate, selection["features"],
                                  np.ones((len(selection["observations"]),len(SOURCES)),dtype=bool))
        candidates.append((_scalar_score(selection["samples"],selection["observations"],weights,selection["case_weight"])["crps"],
                           regularization))
    regularization = min(candidates)[1]
    fit = _concat_scalar(split["train_blocks"]+split["selection_blocks"])
    model = fit_gate(fit["features"],fit["samples"],fit["observations"],case_weights=fit["case_weight"],
                     regularization=regularization,input_kind="source_point_mixture")
    model.update({
        "feature_names":fit["feature_names"],"source_ids":SOURCES,"variable":variable,
        "lead_hours":lead,"units":"mm" if variable=="rain" else "degC",
        "validated_missing_source_patterns":[],
    })
    static = fit_gate(np.zeros((len(fit["observations"]),1)),fit["samples"],fit["observations"],
                      case_weights=fit["case_weight"],regularization=0,input_kind="source_point_mixture")
    all_available = np.ones((len(test["observations"]),len(SOURCES)),dtype=bool)
    adaptive_weights = predict_weights(model,test["features"],all_available)
    static_weights = predict_weights(static,np.zeros((len(test["observations"]),1)),all_available)
    equal_weights = np.full_like(adaptive_weights,1/len(SOURCES))
    thresholds = RAIN_THRESHOLDS if variable=="rain" else None
    scores = []
    for i, source in enumerate(SOURCES):
        w=np.zeros_like(adaptive_weights);w[:,i]=1
        scores.append({"model":source,**_scalar_score(test["samples"],test["observations"],w,test["case_weight"],thresholds)})
    equal_score = _scalar_score(test["samples"],test["observations"],equal_weights,test["case_weight"],thresholds)
    static_score = _scalar_score(test["samples"],test["observations"],static_weights,test["case_weight"],thresholds)
    adaptive_score = _scalar_score(test["samples"],test["observations"],adaptive_weights,test["case_weight"],thresholds)
    scores += [{"model":"Equal point mixture",**equal_score},{"model":"Static point mixture",**static_score},
               {"model":"Adaptive point mixture",**adaptive_score}]
    first,pair=crps_terms(test["samples"],test["observations"])
    interval=_event_interval(mixture_crps(adaptive_weights,first,pair),mixture_crps(static_weights,first,pair),
                             test["event_id"],28000+lead)
    missing = _scalar_missing_matrix(model,test,adaptive_score)
    missing_ok = bool(missing and all(row["acceptance_pass"] for row in missing))
    extreme_evidence = _rain_extreme_evidence(test, adaptive_score, static_score) if variable=="rain" else None
    extreme_ok = bool(extreme_evidence and all(row["acceptance_pass"] for row in extreme_evidence.values())) if variable=="rain" else True
    cross_reference = None
    cross_ok = not require_independent
    if cross_blocks:
        cross_selected=[b for b in cross_blocks if b["event_id"] in split["test_events"]]
        if cross_selected:
            cross=_concat_scalar(cross_selected)
            cross_weights=predict_weights(model,cross["features"],np.ones((len(cross["observations"]),len(SOURCES)),bool))
            cross_static=predict_weights(static,np.zeros((len(cross["observations"]),1)),
                                         np.ones((len(cross["observations"]),len(SOURCES)),bool))
            cfirst,cpair=crps_terms(cross["samples"],cross["observations"])
            cinterval=_event_interval(mixture_crps(cross_weights,cfirst,cpair),
                                      mixture_crps(cross_static,cfirst,cpair),cross["event_id"],29000+lead)
            cross_score=_scalar_score(cross["samples"],cross["observations"],cross_weights,cross["case_weight"],thresholds)
            cross_static_score=_scalar_score(cross["samples"],cross["observations"],cross_static,cross["case_weight"],thresholds)
            cross_reference={"event_blocks":len(np.unique(cross["event_id"])),"adaptive":cross_score,
                             "static":cross_static_score,"adaptive_minus_static_95ci":cinterval}
            cross_ok=bool(cross_reference["event_blocks"]>=MIN_HELDOUT_EVENTS and
                          cross_score["crps"]<cross_static_score["crps"] and cinterval and cinterval[1]<0)
    enough=len(events)>=MIN_TOTAL_EVENTS and len(prospective)>=MIN_PROSPECTIVE_EVENTS and len(split["test_events"])>=MIN_HELDOUT_EVENTS
    numerical=bool(enough and adaptive_score["crps"]<static_score["crps"] and interval and interval[1]<0
                   and cross_ok and missing_ok and extreme_ok)
    # ERA5T remains reanalysis, so temperature does not self-authorize production.
    acceptance=bool(numerical and (variable=="rain"))
    if acceptance:
        model["validated_missing_source_patterns"]=[row["available"] for row in missing if row["acceptance_pass"]]
    status.update({
        "train_event_blocks":len(split["train_events"]),"selection_event_blocks":len(split["selection_events"]),
        "test_event_blocks":len(split["test_events"]),"scores":scores,
        "adaptive_minus_static_95ci":interval,"cross_reference":cross_reference,
        "missing_source_matrix":missing,"missing_source_gate_passed":missing_ok,
        "extreme_event_evidence":extreme_evidence,"extreme_event_gate_passed":extreme_ok,
        "numerical_gate_passed":numerical,
        "acceptance_passed":acceptance,"reference_limitation":(
            None if variable=="rain" else "ERA5 reanalysis is not an independent station network; independent observational review remains required."
        ),
    })
    return model,status


def _wind_missing_matrix(model, test, full_score):
    first,pair=energy_terms(test["vectors"],test["observations"])
    rows=[]
    for missing,available in missing_patterns():
        requested=np.broadcast_to(available,(len(test["observations"]),len(SOURCES)))
        masked_features,mask,good,_=_wind_masked_features(
            test["features"],test["vectors"],requested
        )
        if not good.all():
            raise ValueError("Declared wind outage leaves fewer than two experts")
        adaptive_weights=predict_weights(model,masked_features,mask)
        equal_weights=_equal_weights(len(test["observations"]),mask)
        adaptive=_wind_score(test["vectors"],test["observations"],adaptive_weights,test["case_weight"])
        equal=_wind_score(test["vectors"],test["observations"],equal_weights,test["case_weight"])
        interval=_event_interval(mixture_energy(adaptive_weights,first,pair),
                                 mixture_energy(equal_weights,first,pair),
                                 test["event_id"],30000+sum(missing))
        relative=adaptive["energy_score"]/full_score["energy_score"]-1
        bootstrap_pass=bool(adaptive["energy_score"]<=equal["energy_score"] and interval is not None and interval[1]<=0)
        rows.append({
            "missing":[SOURCES[i] for i in missing],"available":available.tolist(),
            "adaptive_energy":adaptive["energy_score"],"equal_energy":equal["energy_score"],
            "adaptive_minus_equal_95ci":interval,
            "relative_energy_vs_full_adaptive":relative,
            "bootstrap_pass":bootstrap_pass,
            "maximum_relative_degradation":(
                MISSING_SINGLE_MAX_DEGRADATION if len(missing)==1 else MISSING_PAIR_MAX_DEGRADATION
            ),
            "acceptance_pass":bool(
                bootstrap_pass and relative<=(
                    MISSING_SINGLE_MAX_DEGRADATION if len(missing)==1 else MISSING_PAIR_MAX_DEGRADATION
                )
            ),
        })
    return rows


def train_wind_model(blocks,lead,prospective_start):
    split=_split(blocks)
    events,mapping=_events(blocks)
    prospective_start=utc(prospective_start)
    prospective=[event for event in events if mapping[event]>=prospective_start]
    status={
        "state":"collecting" if split is None else "shadow_candidate","variable":"wind","lead":lead,
        "source_ids":SOURCES,"event_blocks":len(events),"bootstrap_event_blocks":len(events)-len(prospective),
        "prospective_event_blocks":len(prospective),"prospective_start":prospective_start.isoformat(),
        "acceptance_passed":False,"eligible_for_production":False,
        "acceptance_requirements":{"minimum_total_event_blocks":MIN_TOTAL_EVENTS,
          "minimum_prospective_event_blocks":MIN_PROSPECTIVE_EVENTS,
          "minimum_held_out_event_blocks":MIN_HELDOUT_EVENTS},
    }
    if split is None:
        status["reason"]=f"Need at least {MIN_PROVISIONAL_EVENTS} independent daily blocks"
        return None,status
    train,selection,test=map(_concat_wind,[split["train_blocks"],split["selection_blocks"],split["test_blocks"]])
    candidates=[]
    for regularization in [.01,.03,.1,.3]:
        candidate=fit_vector_gate(train["features"],train["vectors"],train["observations"],
                                  case_weights=train["case_weight"],regularization=regularization)
        candidate["feature_names"]=train["feature_names"]
        weights=predict_weights(candidate,selection["features"],
                                np.ones((len(selection["observations"]),len(SOURCES)),bool))
        candidates.append((_wind_score(selection["vectors"],selection["observations"],weights,
                                       selection["case_weight"])["energy_score"],regularization))
    regularization=min(candidates)[1]
    fit=_concat_wind(split["train_blocks"]+split["selection_blocks"])
    model=fit_vector_gate(fit["features"],fit["vectors"],fit["observations"],
                          case_weights=fit["case_weight"],regularization=regularization)
    model.update({"feature_names":fit["feature_names"],"source_ids":SOURCES,"variable":"wind",
                  "lead_hours":lead,"units":"m s**-1","validated_missing_source_patterns":[]})
    static=fit_vector_gate(np.zeros((len(fit["observations"]),1)),fit["vectors"],fit["observations"],
                           case_weights=fit["case_weight"],regularization=0)
    available=np.ones((len(test["observations"]),len(SOURCES)),bool)
    adaptive_weights=predict_weights(model,test["features"],available)
    static_weights=predict_weights(static,np.zeros((len(test["observations"]),1)),available)
    equal_weights=np.full_like(adaptive_weights,1/len(SOURCES))
    scores=[]
    for i,source in enumerate(SOURCES):
        w=np.zeros_like(adaptive_weights);w[:,i]=1
        scores.append({"model":source,**_wind_score(test["vectors"],test["observations"],w,test["case_weight"])})
    equal_score=_wind_score(test["vectors"],test["observations"],equal_weights,test["case_weight"])
    static_score=_wind_score(test["vectors"],test["observations"],static_weights,test["case_weight"])
    adaptive_score=_wind_score(test["vectors"],test["observations"],adaptive_weights,test["case_weight"])
    scores += [{"model":"Equal vector mixture",**equal_score},{"model":"Static vector mixture",**static_score},
               {"model":"Adaptive vector mixture",**adaptive_score}]
    first,pair=energy_terms(test["vectors"],test["observations"])
    interval=_event_interval(mixture_energy(adaptive_weights,first,pair),mixture_energy(static_weights,first,pair),
                             test["event_id"],31000+lead)
    missing=_wind_missing_matrix(model,test,adaptive_score)
    missing_ok=bool(missing and all(row["acceptance_pass"] for row in missing))
    enough=len(events)>=MIN_TOTAL_EVENTS and len(prospective)>=MIN_PROSPECTIVE_EVENTS and len(split["test_events"])>=MIN_HELDOUT_EVENTS
    numerical=bool(enough and adaptive_score["energy_score"]<static_score["energy_score"] and interval and interval[1]<0
                   and missing_ok)
    status.update({
        "train_event_blocks":len(split["train_events"]),"selection_event_blocks":len(split["selection_events"]),
        "test_event_blocks":len(split["test_events"]),"scores":scores,
        "adaptive_minus_static_95ci":interval,"missing_source_matrix":missing,
        "missing_source_gate_passed":missing_ok,
        "numerical_gate_passed":numerical,"acceptance_passed":False,
        "reference_limitation":"ERA5 reanalysis is not an independent wind-observation network; independent observational review remains required.",
    })
    return model,status


def _config(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    path=root/"config.json"
    if path.exists():
        config=json.loads(path.read_text());utc(config["prospective_start"]);return config
    old=root.parent/"shadow-rain"/"config.json"
    if old.exists():
        prospective_start=json.loads(old.read_text())["prospective_start"];utc(prospective_start)
    else:
        prospective_start=datetime.now(timezone.utc).isoformat()
    config={"schema_version":1,"prospective_start":prospective_start,
            "policy":"Historical backfill never increments the prospective counter."}
    atomic_write(path,json_bytes(config));return config


def _save_model(model_dir, variable, lead, model, report):
    folder=Path(model_dir)/variable
    folder.mkdir(parents=True,exist_ok=True)
    atomic_write(folder/f"{lead:03}.status.json",json_bytes(report))
    if model is not None:
        atomic_write(folder/f"{lead:03}.model.json",json_bytes(model))


def _load_model(model_dir, variable, lead):
    path=Path(model_dir)/variable/f"{lead:03}.model.json"
    return json.loads(path.read_text()) if path.exists() else None


def _public_field(product,source,lead,variable,size):
    values=product.get("sources",{}).get(source,{}).get(str(lead),{}).get(variable)
    if values is None:
        return np.full(size,np.nan,dtype=float)
    array=np.asarray(values,dtype=float)
    if array.size!=size:
        raise ValueError("Current public field size changed")
    return array


def _nullable(array):
    return [float(value) if np.isfinite(value) else None for value in np.asarray(array).ravel()]


def infer_current(public_dir, model_dir, output_path):
    public_dir=Path(public_dir)
    pointer=json.loads((public_dir/"latest.json").read_text())
    product=json.loads((public_dir/pointer["path"]).read_text())
    initialization=utc(product["initialization"])
    if initialization.hour!=0:
        Path(output_path).unlink(missing_ok=True)
        return None
    latitude=np.asarray(product["latitude"],dtype=float);longitude=np.asarray(product["longitude"],dtype=float)
    result={"schema_version":1,"data_kind":"multi_shadow_forecast","run_id":product["run_id"],
            "initialization":product["initialization"],"generated_at":datetime.now(timezone.utc).isoformat(),
            "production_active":False,"calibrated":False,"latitude":latitude.tolist(),"longitude":longitude.tolist(),
            "leads":{}}
    for lead in LEADS:
        lead_result={}
        for variable in ["rain","temperature"]:
            model=_load_model(model_dir,variable,lead)
            if not model: continue
            size=len(latitude)*len(longitude)
            source=np.stack([
                _public_field(product,s,lead,variable,size).reshape(len(latitude),len(longitude))
                for s in SOURCES
            ])
            features,names=_scalar_features(source,latitude,longitude,lead,product["initialization"])
            if names!=model["feature_names"]:raise ValueError("Current scalar feature schema differs")
            flat=features.reshape(-1,features.shape[-1])
            samples=source.reshape(len(SOURCES),-1).T[:,:,None]
            masked_features,available,good,filled=_scalar_masked_features(
                flat,samples,np.ones((len(flat),len(SOURCES)),bool)
            )
            weights=np.full((len(flat),len(SOURCES)),np.nan,dtype=float)
            central=np.full(len(flat),np.nan,dtype=float)
            if good.any():
                weights[good]=predict_weights(model,masked_features[good],available[good])
                central[good]=np.sum(weights[good]*filled[good],axis=1)
            lead_result[variable]={"mean":_nullable(central),"weights":{
                source_name:_nullable(weights[:,i]) for i,source_name in enumerate(SOURCES)}}
        model=_load_model(model_dir,"wind",lead)
        if model:
            size=len(latitude)*len(longitude)
            u=np.stack([_public_field(product,s,lead,"u",size).reshape(len(latitude),len(longitude))
                        for s in SOURCES])
            v=np.stack([_public_field(product,s,lead,"v",size).reshape(len(latitude),len(longitude))
                        for s in SOURCES])
            features,names=_wind_features(u,v,latitude,longitude,lead,product["initialization"])
            if names!=model["feature_names"]:raise ValueError("Current wind feature schema differs")
            flat=features.reshape(-1,features.shape[-1])
            vectors=np.stack([u.reshape(len(SOURCES),-1).T,v.reshape(len(SOURCES),-1).T],axis=-1)
            masked_features,available,good,filled=_wind_masked_features(
                flat,vectors,np.ones((len(flat),len(SOURCES)),bool)
            )
            weights=np.full((len(flat),len(SOURCES)),np.nan,dtype=float)
            central=np.full((len(flat),2),np.nan,dtype=float)
            if good.any():
                weights[good]=predict_weights(model,masked_features[good],available[good])
                central[good]=np.einsum("bi,bid->bd",weights[good],filled[good])
            lead_result["wind"]={"u":_nullable(central[:,0]),"v":_nullable(central[:,1]),
                "speed":_nullable(np.linalg.norm(central,axis=1)),
                "weights":{source_name:_nullable(weights[:,i]) for i,source_name in enumerate(SOURCES)}}
        result["leads"][str(lead)]=lead_result
    atomic_write(output_path,json_bytes(result));return result


def refresh_multi_shadow(runtime, public_dir, fetch_analysis=True):
    runtime,public_dir=Path(runtime),Path(public_dir)
    root=runtime/"multi-shadow";forecast_dir=root/"forecasts";model_dir=root/"models"
    root.mkdir(parents=True,exist_ok=True);forecast_dir.mkdir(parents=True,exist_ok=True)
    config=_config(root);prospective_start=config["prospective_start"]
    archive_public_forecasts(public_dir,forecast_dir)
    if fetch_analysis:
        from .analysis_references import fetch_many
        valid_times=[]
        for path in forecast_dir.glob("multi-*.json"):
            try:
                meta,_=_archive(path);initialization=utc(meta["initialization"])
                valid_times += [initialization+timedelta(hours=lead) for lead in LEADS]
            except Exception: continue
        fetch_many(valid_times,runtime/"analysis-references")
    status={"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),
            "source_ids":SOURCES,"prospective_start":prospective_start,
            "production_active":False,"variables":{}}
    models={}
    for lead in LEADS:
        primary=scalar_cases(forecast_dir,"rain",lead,runtime/"rain-references","noaa-cmorph2-nrt-025")
        cross=scalar_cases(forecast_dir,"rain",lead,runtime/"rain-references","nasa-imerg-early-gis-v07")
        model,report=train_scalar_model(primary,"rain",lead,prospective_start,cross_blocks=cross,require_independent=True)
        _save_model(model_dir,"rain",lead,model,report);models[("rain",lead)]=model
        status["variables"].setdefault("rain",{})[str(lead)]=report
        blocks=scalar_cases(forecast_dir,"temperature",lead,runtime/"analysis-references","era5-analysis")
        model,report=train_scalar_model(blocks,"temperature",lead,prospective_start)
        _save_model(model_dir,"temperature",lead,model,report);models[("temperature",lead)]=model
        status["variables"].setdefault("temperature",{})[str(lead)]=report
        blocks=wind_cases(forecast_dir,lead,runtime/"analysis-references")
        model,report=train_wind_model(blocks,lead,prospective_start)
        _save_model(model_dir,"wind",lead,model,report);models[("wind",lead)]=model
        status["variables"].setdefault("wind",{})[str(lead)]=report
    status["summary"]={
        "candidate_models":sum(1 for model in models.values() if model is not None),
        "production_accepted_models":sum(
            1 for variable in status["variables"].values() for report in variable.values()
            if report.get("acceptance_passed")
        ),
        "missing_source_patterns_tested_per_candidate":10,
        "production_note":"No model is auto-promoted; temperature/wind use delayed ERA5-family reanalysis and require independent observational review."
    }
    atomic_write(public_dir/"multi-shadow-status.json",json_bytes(status))
    (public_dir/"multi-shadow-status.json").chmod(0o644)
    if status["summary"]["candidate_models"] and (public_dir/"latest.json").is_file():
        infer_current(public_dir,model_dir,root/"latest.json")
    else:
        (root/"latest.json").unlink(missing_ok=True)
    return status


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime",required=True);parser.add_argument("--public",required=True)
    parser.add_argument("--no-fetch-analysis",action="store_true")
    args=parser.parse_args()
    with file_lock(Path(args.runtime)/"multi-shadow"/".refresh.lock",blocking=False):
        print(json.dumps(refresh_multi_shadow(args.runtime,args.public,not args.no_fetch_analysis),indent=2))


if __name__=="__main__":
    main()

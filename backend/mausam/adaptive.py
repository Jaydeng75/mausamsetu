"""Small CPU-trainable context gate with an exact empirical-mixture CRPS loss.

This is a regularized linear softmax gate, not a newly trained global weather
model. Source distributions must have been calibrated on an earlier partition.
Artifacts are plain JSON: no executable pickle or framework-dependent weights.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .science import masked_softmax
from .storage import atomic_write, json_bytes


def context_features(samples, latitude, longitude, lead_hours, initialization, context_fields=None):
    from datetime import datetime
    fields = [np.asarray(s, dtype=float) for s in samples]
    shape = fields[0].shape[1:]
    if any(s.ndim != 3 or s.shape[1:] != shape for s in fields):
        raise ValueError("Expected source arrays with member/latitude/longitude axes")
    y, x = np.meshgrid(latitude, longitude, indexing="ij")
    if y.shape != shape:
        raise ValueError("Feature coordinates do not match source grids")
    day = datetime.fromisoformat(initialization.replace("Z", "+00:00")).timetuple().tm_yday
    columns = [y, x, np.full(shape, lead_hours), np.full(shape, np.sin(day * 2*np.pi/366)),
               np.full(shape, np.cos(day * 2*np.pi/366))]
    names = ["latitude", "longitude", "lead_hours", "day_sin", "day_cos"]
    for i, sample in enumerate(fields):
        columns += [sample.mean(axis=0), sample.std(axis=0)]
        names += [f"source_{i}_mean", f"source_{i}_spread"]
    for name, values in sorted((context_fields or {}).items()):
        if not re_fullmatch_feature(name):
            raise ValueError("Invalid context feature name")
        values = np.asarray(values, dtype=float)
        if values.shape != shape or not np.isfinite(values).all():
            raise ValueError("Context feature grid does not match forecast grid")
        columns.append(values); names.append("context_"+name)
    return np.stack(columns, axis=-1), names

def re_fullmatch_feature(name):
    import re
    return bool(re.fullmatch(r"[a-z0-9_]{1,48}", name))


def crps_terms(samples, observations, batch_size=128):
    """Bound intermediate memory; returns E|Xm-y| and E|Xm-Xn| per case."""
    s = np.asarray(samples, dtype=float)
    y = np.asarray(observations, dtype=float)
    if s.ndim != 3 or y.shape != (len(s),) or not np.isfinite(s).all() or not np.isfinite(y).all():
        raise ValueError("Finite case/source/member samples and paired targets required")
    first = np.abs(s-y[:, None, None]).mean(axis=-1)
    pair = np.empty((len(s), s.shape[1], s.shape[1]))
    for start in range(0, len(s), batch_size):
        block = s[start:start+batch_size]
        pair[start:start+batch_size] = np.abs(
            block[:, :, None, :, None]-block[:, None, :, None, :]).mean(axis=(-1, -2))
    return first, pair


def mixture_crps(weights, first, pair):
    return np.sum(weights*first, axis=-1)-.5*np.einsum("bi,bij,bj->b", weights, pair, weights)


def fit_gate(features, samples, observations, available=None, case_weights=None,
             regularization=.02, maxiter=250, input_kind="calibrated_samples"):
    if input_kind not in {"calibrated_samples","source_point_mixture"}:
        raise ValueError("Unsupported gate input kind")
    x = np.asarray(features, dtype=float)
    s = np.asarray(samples, dtype=float)
    if x.ndim != 2 or len(x) != len(s) or len(x) < 30 or not np.isfinite(x).all():
        raise ValueError("At least 30 aligned finite training cases required")
    mask = np.ones(s.shape[:2], dtype=bool) if available is None else np.asarray(available, dtype=bool)
    if mask.shape != s.shape[:2] or not mask.any(axis=-1).all():
        raise ValueError("Each case requires an eligible source")
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale < 1e-8, 1., scale)
    design = np.column_stack([np.ones(len(x)), (x-mean)/scale])
    first, pair = crps_terms(s, observations)
    mass = np.ones(len(x)) if case_weights is None else np.asarray(case_weights, dtype=float)
    if mass.shape != (len(x),) or not np.isfinite(mass).all() or (mass < 0).any() or mass.sum() <= 0:
        raise ValueError("Invalid case weights")
    mass = mass / mass.sum()
    shape = (design.shape[1], s.shape[1])
    def objective(flat):
        beta = flat.reshape(shape)
        weights = masked_softmax(design @ beta, mask)
        loss = float(np.dot(mass, mixture_crps(weights, first, pair)))
        derivative = first - np.einsum("bij,bj->bi", pair, weights)
        dz = weights * (derivative-np.sum(derivative*weights, axis=1, keepdims=True))
        gradient = design.T @ (dz*mass[:, None])
        loss += regularization * np.sum(beta[1:]**2)
        gradient[1:] += 2*regularization*beta[1:]
        return loss, gradient.ravel()
    result = minimize(objective, np.zeros(np.prod(shape)), method="L-BFGS-B", jac=True,
                      bounds=[(-15., 15.)]*int(np.prod(shape)), options={"maxiter": maxiter})
    if not result.success or not np.isfinite(result.fun):
        raise ValueError("Gate optimizer did not converge: " + str(result.message))
    return {"schema_version": 1, "method": "linear-softmax-crps", "input_kind": input_kind,
            "mean": mean.tolist(), "scale": scale.tolist(), "coefficients": result.x.reshape(shape).tolist(),
            "source_count": s.shape[1], "feature_count": x.shape[1], "regularization": regularization,
            "training_cases": len(x), "optimizer_iterations": int(result.nit), "objective": float(result.fun)}


def predict_weights(model, features, available):
    if model.get("schema_version") != 1 or model.get("method") not in {"linear-softmax-crps","linear-softmax-energy"}:
        raise ValueError("Unsupported gate artifact")
    x = np.array(features, dtype=float, copy=True)
    mean, scale = np.asarray(model["mean"]), np.asarray(model["scale"])
    beta = np.asarray(model["coefficients"], dtype=float)
    mask = np.broadcast_to(np.asarray(available,dtype=bool), (*x.shape[:-1],model["source_count"]))
    if not mask.any(axis=-1).all():raise ValueError("No eligible sources")
    # Missing source predictions must not influence another source's gate score.
    for index,name in enumerate(model.get("feature_names",[])):
        for source in range(model["source_count"]):
            if name.startswith(f"source_{source}_"):
                x[...,index]=np.where(mask[...,source],x[...,index],mean[index])
    if x.shape[-1] != model["feature_count"] or not np.isfinite(x).all():
        raise ValueError("Invalid gate features")
    if mean.shape != (x.shape[-1],) or scale.shape != mean.shape or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError("Invalid feature normalization")
    if beta.shape != (x.shape[-1]+1, model["source_count"]) or not np.isfinite(beta).all():
        raise ValueError("Invalid gate coefficient shape")
    design = np.concatenate([np.ones((*x.shape[:-1], 1)), (x-mean)/scale], axis=-1)
    logits = design @ beta
    mask = np.broadcast_to(np.asarray(available, dtype=bool), logits.shape)
    return masked_softmax(logits, mask)


def save_candidate(directory, model, report):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    data, evaluation = json_bytes(model), json_bytes(report)
    atomic_write(directory / "model.json", data)
    atomic_write(directory / "evaluation.json", evaluation)
    manifest = {"status": "candidate", "approved": False, "method": model["method"],
        "data_kind": report["data_kind"], "source_ids": model["source_ids"],
        "variable": model["variable"], "units": model["units"],
        "model_sha256": hashlib.sha256(data).hexdigest(),
        "evaluation_sha256": hashlib.sha256(evaluation).hexdigest(),
        "evaluation_manifest": "evaluation.json", "evaluation_passed": bool(report.get("acceptance_passed", False))}
    atomic_write(directory / "manifest.json", json_bytes(manifest))
    return manifest

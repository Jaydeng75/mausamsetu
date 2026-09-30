"""Verification of public rainfall forecast grids against normalized satellite references."""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .science import verification
from .storage import atomic_write, json_bytes


THRESHOLDS_MM = [64.5, 115.6]


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_reference(metadata_path):
    metadata_path = Path(metadata_path)
    metadata = json.loads(metadata_path.read_text())
    values_path = metadata_path.parent / metadata["values_file"]
    coverage_path = metadata_path.parent / metadata["coverage_file"]
    if file_sha(values_path) != metadata["values_sha256"]:
        raise ValueError("Reference values checksum failed")
    if file_sha(coverage_path) != metadata["coverage_sha256"]:
        raise ValueError("Reference coverage checksum failed")
    values = np.load(values_path, allow_pickle=False)
    coverage = np.load(coverage_path, allow_pickle=False)
    return metadata, values, coverage
def load_public_product(path):
    path = Path(path)
    product = json.loads(path.read_text())
    if product.get("data_kind") != "forecast" or product.get("coverage", "india") != "india":
        raise ValueError("Rainfall live verification requires an India forecast product")
    if product.get("calibrated") is not False:
        raise ValueError("Unexpected calibrated public product")
    if not product.get("sources"):
        raise ValueError("Forecast product has no sources")
    return product


def paired_metrics(prediction, observation, threshold):
    prediction = np.asarray(prediction, dtype=float)
    observation = np.asarray(observation, dtype=float)
    valid = np.isfinite(prediction) & np.isfinite(observation)
    if not valid.any():
        raise ValueError("No paired rainfall cells")
    p, o = prediction[valid], observation[valid]
    deterministic_probability = (p > threshold).astype(float)
    result = verification(p, o, deterministic_probability, threshold)
    result["coverage_fraction"] = float(valid.mean())
    return result


def equal_blend(product, lead):
    fields = []
    for source in product["sources"].values():
        values = np.asarray(source[str(lead)]["rain"], dtype=float)
        fields.append(values)
    stacked = np.stack(fields)
    available = np.isfinite(stacked).all(axis=0)
    result = np.full(stacked.shape[1], np.nan)
    result[available] = stacked[:, available].mean(axis=0)
    return result
def verify_public_rain(product_path, reference_metadata_path):
    product_path = Path(product_path)
    product = load_public_product(product_path)
    reference, observation, coverage = load_reference(reference_metadata_path)
    if reference["variable"] != "rain" or reference["units"] != "mm":
        raise ValueError("Reference must be a rainfall accumulation in millimetres")
    if reference.get("reference_kind") != "satellite":
        raise ValueError("This workflow is for satellite rainfall references")
    if reference["latitude"] != product["latitude"] or reference["longitude"] != product["longitude"]:
        raise ValueError("Reference and forecast grids differ")
    if observation.shape != (len(product["latitude"]), len(product["longitude"])):
        raise ValueError("Reference array shape differs from forecast grid")
    if coverage.shape != observation.shape:
        raise ValueError("Reference coverage shape differs")

    initialization = datetime.fromisoformat(product["initialization"])
    valid_end = datetime.fromisoformat(reference["valid_end"])
    valid_start = datetime.fromisoformat(reference["valid_start"])
    lead_hours = (valid_end - initialization).total_seconds() / 3600
    if not lead_hours.is_integer() or int(lead_hours) not in product["leads"]:
        raise ValueError("Reference interval does not map to a published forecast lead")
    lead = int(lead_hours)
    if valid_end - valid_start != timedelta(hours=24):
        raise ValueError("Reference is not an exact 24-hour accumulation")
    expected_start = initialization + timedelta(hours=lead - 24)
    if expected_start != valid_start:
        raise ValueError("Forecast and reference accumulation windows differ exactly")

    observation_flat = observation.ravel()
    rows = []
    predictions = {
        name: np.asarray(source[str(lead)]["rain"], dtype=float)
        for name, source in product["sources"].items()
    }
    predictions["Equal blend"] = equal_blend(product, lead)
    for name, prediction in predictions.items():
        metrics = {str(threshold): paired_metrics(prediction, observation_flat, threshold)
                   for threshold in THRESHOLDS_MM}
        valid = np.isfinite(prediction) & np.isfinite(observation_flat)
        rows.append({
            "model": name,
            "n": int(valid.sum()),
            "rmse": float(np.sqrt(np.mean((prediction[valid] - observation_flat[valid]) ** 2))),
            "mae": float(np.mean(np.abs(prediction[valid] - observation_flat[valid]))),
            "bias": float(np.mean(prediction[valid] - observation_flat[valid])),
            "thresholds": metrics,
        })

    identity = {"run_id": product["run_id"], "forecast_sha256": file_sha(product_path),
                "reference_values_sha256": reference["values_sha256"], "lead_hours": lead}
    verification_id = hashlib.sha256(json_bytes(identity)).hexdigest()
    report = {
        "schema_version": 1,
        "verification_id": verification_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": product["run_id"],
        "forecast_asset": product_path.name,
        "forecast_sha256": file_sha(product_path),
        "lead_hours": lead,
        "valid_start": reference["valid_start"],
        "valid_end": reference["valid_end"],
        "reference_id": reference["reference_id"],
        "reference_product": reference["product"],
        "reference_revision": reference["revision"],
        "reference_values_sha256": reference["values_sha256"],
        "reference_kind": "satellite precipitation estimate",
        "scores": rows,
        "limitations": [
            "Satellite precipitation is a verification reference, not gauge ground truth.",
            "Forecast values are the current browser-grid fields; this is not an operational calibration study.",
            "Scores from CMORPH and IMERG are kept separate and are not pooled.",
            "Equal blend is an uncalibrated deterministic baseline.",
        ],
    }
    return report


def publish_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = report["verification_id"][:12]
    name = f"{report['reference_id']}-{report['run_id']}-f{report['lead_hours']:03}-{fingerprint}.json"
    target = output / name
    if not target.exists(): atomic_write(target, json_bytes(report))
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("forecast")
    parser.add_argument("reference")
    parser.add_argument("--output", default="./public/data/rain-verification")
    args = parser.parse_args()
    report = verify_public_rain(args.forecast, args.reference)
    path = publish_report(report, args.output)
    print(json.dumps({"report": str(path), "reference": report["reference_id"], "run_id": report["run_id"]}))


if __name__ == "__main__":
    main()

"""Scheduled satellite-rainfall reference ingestion and public scorecards."""
import argparse
import json
import os
import httpx
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .public_data import GRIDS
from .public_rain_verify import publish_report, verify_public_rain
from .rain_references import fetch_cmorph_24h, fetch_imerg_24h, save_reference
from .storage import atomic_write, file_lock, json_bytes


def forecast_assets(public_dir):
    public_dir = Path(public_dir)
    assets = []
    for path in sorted(public_dir.glob("public-*.json"), reverse=True):
        try:
            product = json.loads(path.read_text())
            if product.get("data_kind") != "forecast" or product.get("coverage", "india") != "india":
                continue
            init = datetime.fromisoformat(product["initialization"])
            assets.append((init, path, product))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    unique = {}
    for row in assets:
        unique.setdefault(row[2]["run_id"], row)
    return sorted(unique.values(), reverse=True)


def reference_metadata_path(folder, reference_id, valid_end):
    stem = f"{reference_id}-{valid_end.isoformat()[:13].replace(':','')}"
    path = Path(folder) / f"{stem}.json"
    return path if path.exists() else None
def normalize_reference(kind, valid_end, cache, references, netrc_path=None):
    lat, lon = GRIDS["india"]["lat"], GRIDS["india"]["lon"]
    if kind == "cmorph":
        reference_id = "noaa-cmorph2-nrt-025"
        existing = reference_metadata_path(references, reference_id, valid_end)
        if existing:
            return existing
        values, coverage, metadata = fetch_cmorph_24h(valid_end, cache, lat, lon)
    elif kind == "imerg":
        reference_id = "nasa-imerg-early-gis-v07"
        existing = reference_metadata_path(references, reference_id, valid_end)
        if existing:
            return existing
        if not netrc_path:
            raise FileNotFoundError("IMERG credentials are not configured")
        values, coverage, metadata = fetch_imerg_24h(valid_end, cache, lat, lon, netrc_path)
    else:
        raise ValueError("Unknown rainfall reference")
    save_reference(references, values, coverage, metadata, lat, lon)
    return reference_metadata_path(references, reference_id, valid_end)


def verification_exists(report_dir, reference_id, run_id, lead):
    return any(Path(report_dir).glob(f"{reference_id}-{run_id}-f{lead:03}-*.json"))


def eligible_windows(public_dir, now, max_runs=8):
    for _, path, product in forecast_assets(public_dir)[:max_runs]:
        initialization = datetime.fromisoformat(product["initialization"])
        for lead in product["leads"]:
            if lead % 24:
                continue
            valid_end = initialization + timedelta(hours=lead)
            if valid_end > now - timedelta(hours=4):
                continue
            yield path, product, lead, valid_end
def build_index(report_dir, public_dir):
    rows = []
    for path in sorted(Path(report_dir).glob("*.json"), reverse=True):
        try:
            report = json.loads(path.read_text())
            rows.append({
                "verification_id": report["verification_id"],
                "run_id": report["run_id"],
                "lead_hours": report["lead_hours"],
                "valid_start": report["valid_start"],
                "valid_end": report["valid_end"],
                "reference_id": report["reference_id"],
                "reference_product": report["reference_product"],
                "reference_kind": report["reference_kind"],
                "scores": report["scores"],
                "limitations": report["limitations"],
            })
        except (OSError, KeyError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda row: (row["valid_end"], row["reference_id"]), reverse=True)
    index = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows[:100],
        "policy": "Satellite references are reported separately; scores are never pooled into a single truth metric.",
    }
    target = Path(public_dir) / "rain-verification-index.json"
    atomic_write(target, json_bytes(index))
    target.chmod(0o644)
    return index
def run_once(runtime, cache, public_dir, netrc_path=None, max_windows=4):
    runtime = Path(runtime)
    references = runtime / "rain-references"
    reports = runtime / "rain-verification"
    references.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(), "processed": [], "deferred": []}
    now = datetime.now(timezone.utc)
    with file_lock(runtime / ".rain-reference.lock", blocking=False):
        windows = [w for w in eligible_windows(public_dir, now, max_runs=64)
                   if any(not verification_exists(reports, ref, w[1]["run_id"], w[2])
                          for ref in ("noaa-cmorph2-nrt-025", "nasa-imerg-early-gis-v07"))]
        retry_path=runtime/"rain-window-attempts.json"
        attempts=json.loads(retry_path.read_text()) if retry_path.exists() else {}
        windows.sort(key=lambda w: (attempts.get(f"{w[1]['run_id']}:{w[2]}", ""), w[3]))
        windows=windows[:max_windows]
        for forecast_path, product, lead, valid_end in windows:
            attempts[f"{product['run_id']}:{lead}"]=now.isoformat()
            for kind, reference_id in [("cmorph", "noaa-cmorph2-nrt-025"), ("imerg", "nasa-imerg-early-gis-v07")]:
                if verification_exists(reports, reference_id, product["run_id"], lead):
                    continue
                try:
                    metadata = normalize_reference(kind, valid_end, cache, references, netrc_path)
                    report = verify_public_rain(forecast_path, metadata)
                    report_path = publish_report(report, reports)
                    result["processed"].append({
                        "run_id": product["run_id"], "lead": lead,
                        "reference_id": reference_id, "report": report_path.name,
                    })
                except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
                    result["deferred"].append({
                        "run_id": product["run_id"], "lead": lead,
                        "reference_id": reference_id, "reason": type(error).__name__,
                    })
        atomic_write(retry_path,json_bytes(attempts))
        index = build_index(reports, public_dir)
        result["reports_available"] = len(index["rows"])
        try:
            from .live_shadow import refresh_shadow
            shadow = refresh_shadow(runtime, public_dir)
            result["shadow"] = {key: shadow[key] for key in ["state","event_blocks","matched_windows","acceptance_passed"] if key in shadow}
        except (OSError, ValueError, KeyError) as error:
            result["shadow"] = {"state":"failed","error_type":type(error).__name__}
        try:
            from .multi_shadow import refresh_multi_shadow
            multi = refresh_multi_shadow(runtime, public_dir)
            result["multi_shadow"] = multi.get("summary", {})
        except Exception as error:
            result["multi_shadow"] = {"state":"failed","error_type":type(error).__name__}
        atomic_write(runtime / "rain-service-status.json", json_bytes(result))
    return result
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default=os.getenv("MAUSAM_DATA_DIR", "./data"))
    parser.add_argument("--cache", required=True)
    parser.add_argument("--public", required=True)
    parser.add_argument("--netrc", default=os.getenv("NASA_EARTHDATA_NETRC"))
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--max-windows", type=int, default=4)
    args = parser.parse_args()
    if args.interval < 300 or not 1 <= args.max_windows <= 24:
        parser.error("Invalid interval or max-windows")
    while True:
        try:
            result = run_once(args.runtime, args.cache, args.public, args.netrc, args.max_windows)
        except BlockingIOError:
            result = {"schema_version": 1, "status": "skipped", "reason": "Another rainfall-reference cycle owns the lock"}
        print(json.dumps(result), flush=True)
        if not args.loop:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

"""Private recent-cycle backfill for the live-roster rainfall shadow experiment."""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .live_shadow import SOURCES, SHADOW_CYCLE_HOUR, archive_forecast, refresh_shadow
from .rain_service import normalize_reference
from .storage import atomic_write, file_lock, json_bytes


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Backfill initialization needs an explicit timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed.minute or parsed.second or parsed.microsecond or parsed.hour != SHADOW_CYCLE_HOUR:
        raise ValueError("Shadow backfill must start at 00 UTC")
    return parsed


def schedule(start, count):
    if not 1 <= count <= 16:
        raise ValueError("Backfill count must be between 1 and 16")
    initial = utc(start)
    return [initial + timedelta(days=index) for index in range(count)]


def backfill_cycle(runtime, cache, netrc_path, initialization, deadline=1200):
    runtime, cache = Path(runtime), Path(cache)
    forecast_archive = runtime / "shadow-rain" / "forecasts"
    references = runtime / "rain-references"
    run_id = f"public-{initialization:%Y%m%d}-{initialization.hour:02d}"
    if not (forecast_archive / f"{run_id}.json").exists():
        staging = runtime / "shadow-rain" / "backfill-staging" / run_id
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, "-m", "mausam.public_data",
            "--date", initialization.strftime("%Y%m%d"), "--cycle", str(initialization.hour),
            "--domain", "india", "--step", "24", "--max-lead", "24",
            "--cache", str(cache), "--output", str(staging),
        ]
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=deadline, check=True)
        pointer = json.loads((staging / "latest.json").read_text())
        product_path = staging / pointer["path"]
        product = json.loads(product_path.read_text())
        if product["run_id"] != run_id or set(product.get("sources", {})) != set(SOURCES):
            raise ValueError("Backfill did not produce the complete live source roster")
        if any(product.get("source_status", {}).get(source) != "loaded" for source in SOURCES):
            raise ValueError("Backfill source unavailable")
        archive_forecast(product_path, forecast_archive)
        shutil.rmtree(staging)

    valid_end = initialization + timedelta(hours=24)
    if valid_end > datetime.now(timezone.utc) - timedelta(hours=4):
        return {"run_id": run_id, "forecast_archived": True, "references": "not_yet_available"}
    found = []
    for kind, reference_id in [("cmorph", "noaa-cmorph2-nrt-025"),
                               ("imerg", "nasa-imerg-early-gis-v07")]:
        metadata_path = normalize_reference(kind, valid_end, cache, references, netrc_path)
        found.append({"reference_id": reference_id, "metadata": Path(metadata_path).name})
    return {"run_id": run_id, "forecast_archived": True, "references": found}


def run(runtime, cache, public, netrc_path, start, count, deadline=1200):
    runtime = Path(runtime)
    public = Path(public)
    results = []
    with file_lock(runtime / ".shadow-backfill.lock", blocking=False):
        for initialization in schedule(start, count):
            try:
                row = backfill_cycle(runtime, cache, netrc_path, initialization, deadline)
                results.append({"initialization": initialization.isoformat(), "status": "complete", **row})
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                results.append({"initialization": initialization.isoformat(),
                                "status": "failed", "error_type": type(error).__name__})
        shadow = refresh_shadow(runtime, public)
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cycles": results,
            "shadow": {key: shadow[key] for key in
                       ["state", "event_blocks", "matched_windows", "acceptance_passed"]
                       if key in shadow},
        }
        target = runtime / "shadow-rain" / "backfill-status.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, json_bytes(report))
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--public", required=True)
    parser.add_argument("--netrc", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--deadline", type=int, default=1200)
    args = parser.parse_args()
    print(json.dumps(run(args.runtime, args.cache, args.public, args.netrc,
                         args.start, args.count, args.deadline), indent=2))


if __name__ == "__main__":
    main()

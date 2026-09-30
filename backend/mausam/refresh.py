"""Bounded operational refresh. Failed runs never replace the last good pointer."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .storage import atomic_write, file_lock, json_bytes


def choose_cycle(now=None, lag_hours=8, cycles=(0, 12)):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or lag_hours < 0 or not cycles or any(c not in (0,6,12,18) for c in cycles):
        raise ValueError("Invalid cycle-selection configuration")
    eligible = now-timedelta(hours=lag_hours)
    candidates = [eligible.replace(hour=hour, minute=0, second=0, microsecond=0)-timedelta(days=day)
                  for day in (0,1) for hour in cycles]
    chosen = max(c for c in candidates if c <= eligible)
    return chosen.strftime("%Y%m%d"), chosen.hour


def checked_pointer(directory, pointer_name="latest.json"):
    directory = Path(directory)
    if pointer_name not in {"latest.json", "global-latest.json"}:
        raise ValueError("Unsupported pointer name")
    pointer = json.loads((directory / pointer_name).read_text())
    name = pointer["path"]
    if Path(name).name != name or not name.endswith(".json") or name.startswith("."):
        raise ValueError("Unsafe public product path")
    body = (directory / name).read_bytes()
    if hashlib.sha256(body).hexdigest() != pointer["sha256"]:
        raise ValueError("Public product checksum failed")
    product = json.loads(body)
    if product.get("data_kind") != "forecast" or product.get("calibrated") is not False:
        raise ValueError("Refresh only publishes explicitly uncalibrated public source products")
    expected = "global" if pointer_name == "global-latest.json" else "india"
    if product.get("coverage", "india") != expected:
        raise ValueError("Published product coverage does not match its pointer")
    if not set(product.get("sources", {})) <= {"GFS", "AIFS", "IFS", "GEFS"}:
        raise ValueError("Institutional/restricted sources cannot enter the public projection")
    if not product.get("sources"):
        raise ValueError("Empty public forecast")
    return pointer, product


def refresh_once(root, cache, output, date=None, cycle=None, max_lead=168, step=6, deadline=1800):
    root, cache, output = Path(root), Path(cache), Path(output)
    for path in (root, cache, output):
        path.mkdir(parents=True, exist_ok=True)
    if date is None:
        date, cycle = choose_cycle()
    if cycle not in (0,6,12,18):
        raise ValueError("Explicit date requires a supported cycle")
    datetime.strptime(date, "%Y%m%d")
    with file_lock(root / ".refresh.lock", blocking=False):
        now = datetime.now(timezone.utc).isoformat()
        status = {"schema_version": 1, "state": "running", "started_at": now,
                  "requested_initialization": date+f"-{cycle:02d}Z", "last_success": None,
                  "publication_kind": "deterministic_public_baseline", "calibrated": False}
        status_path = root / "operations.json"
        if status_path.exists():
            previous = json.loads(status_path.read_text())
            status["last_success"] = previous.get("last_success")
        atomic_write(status_path, json_bytes(status))
        staging = root / "refresh-staging" / (date+f"-{cycle:02d}")
        staging.mkdir(parents=True, exist_ok=True)
        log = root / "logs" / (date+f"-{cycle:02d}-refresh.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m", "mausam.public_data", "--date", date, "--cycle", str(cycle),
                   "--cache", str(cache.resolve()), "--output", str(staging.resolve()),
                   "--max-lead", str(max_lead), "--step", str(step)]
        try:
            with log.open("a") as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=deadline, check=True)
            pointer, product = checked_pointer(staging)
            candidate_time = datetime.fromisoformat(product["initialization"])
            current_time = None
            if (output / "latest.json").exists():
                _, current = checked_pointer(output)
                current_time = datetime.fromisoformat(current["initialization"])
            # Publish immutable assets first. Never move the latest pointer backwards.
            atomic_write(output / pointer["path"], (staging / pointer["path"]).read_bytes())
            (output / pointer["path"]).chmod(0o644)
            if current_time is None or candidate_time >= current_time:
                atomic_write(output / "latest.json", json_bytes(pointer))
                (output / "latest.json").chmod(0o644)
            complete = all(value == "loaded" for value in product["source_status"].values())
            status.update(state="complete" if complete else "degraded", run_id=product["run_id"],
                initialization=product["initialization"], sources=product["source_status"],
                last_success=datetime.now(timezone.utc).isoformat(), latest_advanced=current_time is None or candidate_time >= current_time)
        except (OSError, ValueError, subprocess.SubprocessError, KeyError) as error:
            # Only exception class enters the reader-facing status; provider logs stay local.
            status.update(state="failed", error_type=type(error).__name__,
                          message="Refresh failed. Last successful publication is unchanged.")
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write(status_path, json_bytes(status))
        return status


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, default=Path(os.getenv("MAUSAM_DATA_DIR", "./data")))
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--date")
    p.add_argument("--cycle", type=int)
    p.add_argument("--max-lead", type=int, default=168)
    p.add_argument("--step", type=int, choices=[6,24], default=6)
    p.add_argument("--deadline", type=int, default=1800)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval", type=int, default=3600)
    args = p.parse_args()
    if args.interval < 300 or args.deadline < 30 or args.max_lead not in range(24,169,6):
        p.error("Invalid interval, deadline or forecast horizon")
    while True:
        try:
            status = refresh_once(args.archive, args.cache, args.output, args.date, args.cycle, args.max_lead, args.step, args.deadline)
        except BlockingIOError:
            status = {"state": "skipped", "message": "Another refresh owns the lock"}
        print(json.dumps(status), flush=True)
        if not args.loop:
            sys.exit(1 if status["state"] == "failed" else 0)
        time.sleep(args.interval)

"""Scheduled live-global publication using public GFS and AIFS feeds."""
import argparse
import json
import subprocess
import sys
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .refresh import checked_pointer, choose_cycle
from .storage import atomic_write, file_lock, json_bytes


def refresh_global_once(root, cache, output, date=None, cycle=None, deadline=2400, minimum_free_bytes=5_000_000_000, budget_path=None):
    root, cache, output = Path(root), Path(cache), Path(output)
    for folder in (root, cache, output):
        folder.mkdir(parents=True, exist_ok=True)
    if date is None:
        date, cycle = choose_cycle()
    if cycle not in (0, 6, 12, 18):
        raise ValueError("Explicit date requires a supported cycle")
    datetime.strptime(date, "%Y%m%d")
    with file_lock(root / ".global-refresh.lock", blocking=False):
        free=shutil.disk_usage(root).free
        if budget_path and Path(budget_path).exists():free=min(free,shutil.disk_usage(budget_path).free)
        if free < minimum_free_bytes:
            result={"schema_version":1,"state":"withheld","reason":"insufficient_disk_space","disk_free_bytes":free,"finished_at":datetime.now(timezone.utc).isoformat()}
            atomic_write(root / "global-operations.json", json_bytes(result));return result
        if (output / "global-latest.json").exists():
            try:
                _, current=checked_pointer(output,"global-latest.json")
                required={'GFS','GEFS','IFS','AIFS'}
                complete=set(current.get('source_status',{}))==required and all(value=='loaded' for value in current.get('source_status',{}).values())
                if current.get("run_id")==f"global-{date}-{cycle:02d}" and max(current.get("leads",[0]))>=168 and complete:
                    result={"schema_version":1,"state":"unchanged","run_id":current["run_id"],"initialization":current["initialization"],"sources":current["source_status"],"finished_at":datetime.now(timezone.utc).isoformat()}
                    atomic_write(root / "global-operations.json", json_bytes(result));return result
            except (OSError,ValueError,KeyError):pass
        status_path = root / "global-operations.json"
        status = {
            "schema_version": 1,
            "state": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "requested_initialization": date + f"-{cycle:02d}Z",
            "publication_kind": "deterministic_global_public_baseline",
            "calibrated": False,
        }
        atomic_write(status_path, json_bytes(status))
        staging = root / "global-refresh-staging" / (date + f"-{cycle:02d}")
        staging.mkdir(parents=True, exist_ok=True)
        log = root / "logs" / (date + f"-{cycle:02d}-global-refresh.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, "-m", "mausam.public_data",
            "--date", date, "--cycle", str(cycle), "--domain", "global",
            "--cache", str(cache.resolve()), "--output", str(staging.resolve()),
            "--max-lead", "168", "--step", "24",
        ]
        try:
            with log.open("a") as stream:
                subprocess.run(
                    command, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=deadline, check=True
                )
            pointer, product = checked_pointer(staging, "global-latest.json")
            candidate_time = datetime.fromisoformat(product["initialization"])
            current_time = None
            if (output / "global-latest.json").exists():
                _, current = checked_pointer(output, "global-latest.json")
                current_time = datetime.fromisoformat(current["initialization"])
            asset = staging / pointer["path"]
            atomic_write(output / pointer["path"], asset.read_bytes())
            (output / pointer["path"]).chmod(0o644)
            advanced = current_time is None or candidate_time >= current_time
            if advanced:
                atomic_write(output / "global-latest.json", json_bytes(pointer))
                (output / "global-latest.json").chmod(0o644)
            complete = all(value == "loaded" for value in product["source_status"].values())
            status.update(
                state="complete" if complete else "degraded",
                run_id=product["run_id"],
                initialization=product["initialization"],
                sources=product["source_status"],
                latest_advanced=advanced,
                last_success=datetime.now(timezone.utc).isoformat(),
            )
        except (OSError, ValueError, subprocess.SubprocessError, KeyError) as error:
            status.update(
                state="failed",
                error_type=type(error).__name__,
                message="Global refresh failed. The previous global publication is unchanged.",
            )
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write(status_path, json_bytes(status))
        return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path("./data"))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date")
    parser.add_argument("--cycle", type=int)
    parser.add_argument("--deadline", type=int, default=2400)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--minimum-free-bytes", type=int, default=5_000_000_000)
    parser.add_argument("--budget-path")
    args = parser.parse_args()
    if args.interval < 300 or args.deadline < 60:
        parser.error("Invalid interval or deadline")
    while True:
        try:
            result = refresh_global_once(
                args.archive, args.cache, args.output,
                args.date, args.cycle, args.deadline,args.minimum_free_bytes,args.budget_path
            )
        except BlockingIOError:
            result = {"state": "skipped", "message": "Another global refresh owns the lock"}
        print(json.dumps(result), flush=True)
        if not args.loop:
            sys.exit(1 if result.get("state") == "failed" else 0)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

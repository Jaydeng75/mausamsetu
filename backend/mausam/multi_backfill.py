"""Bounded historical bootstrap for the multi-variable live-roster shadow archive."""
import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analysis_references import fetch_many as fetch_era5t_many
from .multi_shadow import refresh_multi_shadow
from .rain_service import normalize_reference
from .shadow_sources import LEADS, fetch_cycle, save_cycle
from .storage import atomic_write, file_lock, json_bytes


def utc(value):
    parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None:raise ValueError("Backfill start must be timezone-aware")
    parsed=parsed.astimezone(timezone.utc)
    if parsed.hour or parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("Multi-shadow backfill uses 00 UTC daily initializations")
    return parsed


def schedule(start,count):
    if not 1<=count<=45:raise ValueError("Backfill count must be between 1 and 45")
    initial=utc(start)
    return [initial+timedelta(days=i) for i in range(count)]


def run(runtime,cache,public,netrc_path,start,count,minimum_free_bytes=3_000_000_000):
    runtime,cache,public=Path(runtime),Path(cache),Path(public)
    root=runtime/"multi-shadow";forecast_dir=root/"forecasts"
    root.mkdir(parents=True,exist_ok=True);forecast_dir.mkdir(parents=True,exist_ok=True)
    cycles=[];valid_times=set()
    with file_lock(root/".backfill.lock",blocking=False):
        for initialization in schedule(start,count):
            if shutil.disk_usage(runtime).free<minimum_free_bytes:
                cycles.append({"initialization":initialization.isoformat(),"status":"withheld_low_disk"})
                break
            stem=f"multi-{initialization:%Y%m%d-%H}.json"
            try:
                if not (forecast_dir/stem).exists():
                    cycle=fetch_cycle(initialization,cache)
                    metadata=save_cycle(cycle,forecast_dir)
                else:
                    metadata=json.loads((forecast_dir/stem).read_text())
                references=[]
                for lead in LEADS:
                    valid=initialization+timedelta(hours=lead)
                    valid_times.add(valid)
                    for kind,reference_id in [("cmorph","noaa-cmorph2-nrt-025"),
                                              ("imerg","nasa-imerg-early-gis-v07")]:
                        path=normalize_reference(kind,valid,cache,runtime/"rain-references",netrc_path)
                        references.append({"lead":lead,"reference_id":reference_id,"metadata":Path(path).name})
                cycles.append({"initialization":initialization.isoformat(),"status":"complete",
                               "archive":metadata["values_file"],"rain_references":references})
            except Exception as error:
                cycles.append({"initialization":initialization.isoformat(),"status":"failed",
                               "error_type":type(error).__name__})
        era5_paths=fetch_era5t_many(valid_times,runtime/"analysis-references")
        shadow=refresh_multi_shadow(runtime,public,fetch_analysis=False)
        result={"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),
                "cycles":cycles,"era5t_references":len(era5_paths),
                "multi_shadow_summary":shadow.get("summary",{})}
        atomic_write(root/"backfill-status.json",json_bytes(result))
        return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime",required=True);parser.add_argument("--cache",required=True)
    parser.add_argument("--public",required=True);parser.add_argument("--netrc",required=True)
    parser.add_argument("--start",required=True);parser.add_argument("--count",type=int,default=30)
    parser.add_argument("--minimum-free-bytes",type=int,default=3_000_000_000)
    args=parser.parse_args()
    print(json.dumps(run(args.runtime,args.cache,args.public,args.netrc,args.start,args.count,
                         args.minimum_free_bytes),indent=2))


if __name__=="__main__":
    main()

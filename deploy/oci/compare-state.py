#!/usr/bin/env python3
import argparse
import json
import urllib.request

def get(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=15) as response:
        return json.load(response)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--local",default="http://127.0.0.1:8000")
    parser.add_argument("--cloud",default="http://127.0.0.1:18000")
    args=parser.parse_args()
    local={name:get(args.local,path) for name,path in {
        "ops":"/public/status","shadow":"/public/shadow-rain",
        "multi":"/public/multi-shadow","imd":"/public/imd-gauge"}.items()}
    cloud={name:get(args.cloud,path) for name,path in {
        "ops":"/public/status","shadow":"/public/shadow-rain",
        "multi":"/public/multi-shadow","imd":"/public/imd-gauge"}.items()}

    if local["shadow"].get("prospective_start") != cloud["shadow"].get("prospective_start"):
        raise SystemExit("Prospective start changed during migration")
    if cloud["shadow"].get("event_blocks",0) < local["shadow"].get("event_blocks",0):
        raise SystemExit("Cloud shadow archive is behind the exported Mac state")
    if cloud["multi"].get("summary",{}).get("candidate_models",0) < local["multi"].get("summary",{}).get("candidate_models",0):
        raise SystemExit("Cloud multi-shadow candidate set is incomplete")
    if len(cloud["imd"].get("rows",[])) < len(local["imd"].get("rows",[])):
        raise SystemExit("Cloud IMD evidence is incomplete")

    print("Prospective start:",cloud["shadow"]["prospective_start"])
    print("Shadow blocks:",local["shadow"].get("event_blocks"),"->",cloud["shadow"].get("event_blocks"))
    print("Prospective blocks:",local["shadow"].get("prospective_event_blocks"),"->",cloud["shadow"].get("prospective_event_blocks"))
    print("India run:",local["ops"].get("run_id"),"->",cloud["ops"].get("run_id"))
    print("Global run:",local["ops"].get("global_forecast",{}).get("run_id"),"->",cloud["ops"].get("global_forecast",{}).get("run_id"))
    print("IMD reports:",len(local["imd"].get("rows",[])),"->",len(cloud["imd"].get("rows",[])))
    print("Candidate models:",cloud["multi"]["summary"].get("candidate_models"))
    print("Migration state comparison: PASS")

if __name__=="__main__":
    main()

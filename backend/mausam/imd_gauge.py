"""Exact-window verification against IMD's public 0.25 degree gauge-gridded rainfall."""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

from .multi_shadow import _scalar_score
from .public_data import GRIDS, decode, validate_run, precipitation_increment
from .shadow_sources import SOURCES, _download_ranges, _ecmwf_retrieve
from .storage import atomic_write, file_lock, json_bytes

IMD_FORM = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/Rain_Download.html"
IMD_POST = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
GRID_SHAPE = (129, 135)
GRID_BYTES = 129 * 135 * 4
LEADS = [24, 48, 72]
THRESHOLDS = [64.5, 115.6, 204.5]


def utc(value):
    parsed=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None: raise ValueError("Timezone-aware timestamp required")
    return parsed.astimezone(timezone.utc)


def sha256(path):
    with Path(path).open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def _sample_imd_grid(array,target_lat,target_lon):
    source_lat=6.5+np.arange(GRID_SHAPE[0])*.25
    source_lon=66.5+np.arange(GRID_SHAPE[1])*.25
    out=np.full((len(target_lat),len(target_lon)),np.nan,dtype=float)
    for yi,lat in enumerate(np.asarray(target_lat,dtype=float)):
        sy=int(round((lat-6.5)/.25))
        if sy<0 or sy>=len(source_lat) or not np.isclose(source_lat[sy],lat):continue
        for xi,lon in enumerate(np.asarray(target_lon,dtype=float)):
            sx=int(round((lon-66.5)/.25))
            if sx<0 or sx>=len(source_lon) or not np.isclose(source_lon[sx],lon):continue
            out[yi,xi]=array[sy,sx]
    return out
def fetch_imd_daily(valid_end,cache,target_lat=None,target_lon=None):
    valid_end=utc(valid_end)
    if valid_end.hour!=3 or valid_end.minute or valid_end.second or valid_end.microsecond:
        raise ValueError("IMD daily rainfall must end exactly at 03:00 UTC")
    target_lat=GRIDS["india"]["lat"] if target_lat is None else np.asarray(target_lat)
    target_lon=GRIDS["india"]["lon"] if target_lon is None else np.asarray(target_lon)
    cache=Path(cache);folder=cache/"imd-gauge";folder.mkdir(parents=True,exist_ok=True)
    raw=folder/f"rain_ind0.25_{valid_end:%Y%m%d}.grd"
    if not raw.exists():
        response=None
        timeout=httpx.Timeout(180.0,connect=60.0)
        headers={"User-Agent":"MausamSetu/0.2 rainfall-verification research client"}
        with httpx.Client(timeout=timeout,follow_redirects=True,headers=headers) as client:
            for attempt in range(3):
                try:
                    # Warm the session through the public form first; the IMD host can reset cold direct POSTs.
                    if attempt==0:
                        try: client.get(IMD_FORM)
                        except httpx.HTTPError: pass
                    response=client.post(IMD_POST,data={"rain":valid_end.strftime("%d%m%Y")})
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt==2: raise
                    time.sleep(3*(attempt+1))
        if response is None:
            raise ValueError("IMD rainfall response unavailable")
        expected=f"rain_ind0.25_{valid_end:%y_%m_%d}.grd"
        disposition=response.headers.get("content-disposition","")
        if response.headers.get("content-type","").split(";")[0]!="application/octet-stream":
            raise ValueError("IMD rainfall response is not a binary file")
        if expected not in disposition or len(response.content)!=GRID_BYTES:
            raise ValueError("IMD rainfall binary filename or size changed")
        atomic_write(raw,response.content)
    payload=raw.read_bytes()
    if len(payload)!=GRID_BYTES:raise ValueError("Cached IMD rainfall binary size changed")
    array=np.frombuffer(payload,dtype="<f4").reshape(GRID_SHAPE).astype(float)
    missing=array<=-900
    if np.any((array<0)&~missing) or np.nanmax(np.where(missing,np.nan,array))>3000:
        raise ValueError("IMD rainfall values outside expected domain")
    array=np.where(missing,np.nan,array)
    sampled=_sample_imd_grid(array,target_lat,target_lon)
    metadata={
        "schema_version":1,"reference_id":"imd-gauge-grid-025-realtime",
        "reference_kind":"gauge_gridded_analysis",
        "product":"IMD 0.25 degree daily gridded rainfall (real-time binary)",
        "valid_start":(valid_end-timedelta(hours=24)).isoformat(),
        "valid_end":valid_end.isoformat(),"retrieved_at":datetime.now(timezone.utc).isoformat(),
        "units":"mm","source_page":IMD_FORM,"download_endpoint":IMD_POST,
        "raw_file":raw.name,"raw_sha256":hashlib.sha256(payload).hexdigest(),
        "raw_grid":{"latitude_start":6.5,"latitude_end":38.5,"longitude_start":66.5,"longitude_end":100.0,
                    "spacing_degrees":.25,"shape":list(GRID_SHAPE),"missing_value":-999.0,
                    "dtype":"little-endian float32"},
        "reporting_window":"24 hours ending 03:00 UTC (08:30 IST)",
        "limitation":"Gauge-gridded analysis; not a direct station-by-station verification.",
    }
    return sampled,metadata
def save_imd_reference(folder,valid_end,cache):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    valid_end=utc(valid_end);stem=f"imd-gauge-grid-025-{valid_end:%Y%m%dT03}"
    meta_path=folder/f"{stem}.json";values_path=folder/f"{stem}.npy"
    if meta_path.exists() and values_path.exists():
        meta=json.loads(meta_path.read_text())
        if sha256(values_path)!=meta["values_sha256"]:raise ValueError("IMD normalized reference checksum failed")
        return meta_path
    values,meta=fetch_imd_daily(valid_end,cache)
    np.save(values_path,np.asarray(values,dtype=np.float32),allow_pickle=False)
    meta.update({"values_file":values_path.name,"values_sha256":sha256(values_path),
                 "latitude":GRIDS["india"]["lat"].astype(float).tolist(),
                 "longitude":GRIDS["india"]["lon"].astype(float).tolist()})
    atomic_write(meta_path,json_bytes(meta));return meta_path


def _precip_for_step(entries,source,step):
    matches=[entry for entry in entries if ":APCP:surface:" in ":"+entry[1]]
    if not matches:raise ValueError("NOAA precipitation index schema changed")
    hour_interval=re.compile(r":(\d+)-(\d+) hour acc fcst:")
    day_interval=re.compile(r":(\d+)-(\d+) day acc fcst:")
    parsed=[]
    for entry in matches:
        text=":"+entry[1]
        found=hour_interval.search(text)
        if found:
            parsed.append((entry,int(found.group(1)),int(found.group(2))))
            continue
        found=day_interval.search(text)
        if found:
            parsed.append((entry,int(found.group(1))*24,int(found.group(2))*24))
    ending=[row for row in parsed if row[2]==step]
    if not ending:raise ValueError("NOAA precipitation interval ending at requested step is missing")
    if source=="GFS":
        # Prefer the cumulative 0→lead product, including 0→N-day fields.
        cumulative=[row for row in ending if row[1]==0]
        if cumulative:return [cumulative[0][0]]
        return [max(ending,key=lambda row:row[1])[0]]
    if source=="GEFS":
        # GEFS ensemble-mean APCP alternates 3 h and 6 h accumulation windows.
        # Selecting the shortest ending interval lets _noaa_increment_series
        # reconstruct the exact 3 h increments by differencing same-origin 6 h fields.
        return [max(ending,key=lambda row:row[1])[0]]
    raise ValueError("Unknown NOAA source")


def _noaa_increment_series(source,date,cycle,max_end,cache,latitude,longitude):
    raw={};provenance=[]
    for step in range(3,max_end+1,3):
        if source=="GFS":
            url=f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{date}/{cycle:02}/atmos/gfs.t{cycle:02}z.pgrb2.0p25.f{step:03}"
        elif source=="GEFS":
            url=f"https://noaa-gefs-pds.s3.amazonaws.com/gefs.{date}/{cycle:02}/atmos/pgrb2sp25/geavg.t{cycle:02}z.pgrb2s.0p25.f{step:03}"
        else:raise ValueError("Unknown NOAA source")
        path=Path(cache)/f"imd-window-{source.lower()}-{date}-{cycle:02}-{step:03}.grib2"
        provider=_download_ranges(url,path,lambda entries,s=source,h=step:_precip_for_step(entries,s,h))
        field=decode(path,latitude,longitude)["tp"];validate_run({"tp":field},date,cycle,step)
        # Older cache entries may have been selected under a previous interval rule.
        # GFS must be cumulative from initialization here; if not, invalidate and
        # reselect the now-preferred 0→lead message from the provider index.
        if source=="GFS" and field["start"]!=0:
            path.unlink(missing_ok=True)
            path.with_suffix(path.suffix+".source.json").unlink(missing_ok=True)
            provider=_download_ranges(url,path,lambda entries,s=source,h=step:_precip_for_step(entries,s,h))
            field=decode(path,latitude,longitude)["tp"];validate_run({"tp":field},date,cycle,step)
            if field["start"]!=0:
                raise ValueError("GFS cumulative rainfall selector did not return a 0-to-lead field")
        if field["units"] not in ("kg m**-2","kg m-2"):raise ValueError("Unexpected NOAA precipitation units")
        raw[step]=field;provenance.append({"lead":step,"sha256":sha256(path),"packing_resolution_mm":field.get("packing_resolution",0),"negative_increment_policy":"clip only within summed source packing precision",**provider})
    increments=[];previous=None
    for step in sorted(raw):
        field=raw[step]
        if previous is None:
            if field["start"]!=0:raise ValueError("NOAA first accumulation does not start at initialization")
            start=0;increment=precipitation_increment(field)
        elif field["start"]==previous["start"]:
            start=previous["end"];increment=precipitation_increment(field,previous)
        elif field["start"]==previous["end"]:
            start=field["start"];increment=precipitation_increment(field)
        else:
            raise ValueError("NOAA accumulation intervals are not contiguous")
        if np.nanmin(increment)<-0.01:raise ValueError("Negative NOAA precipitation increment")
        increments.append((start,step,np.maximum(increment,0)));previous=field
    return increments,provenance
def _sum_window(increments,start,end):
    chosen=[row for row in increments if row[0]>=start and row[1]<=end]
    if not chosen or chosen[0][0]!=start or chosen[-1][1]!=end:
        raise ValueError("Forecast increments do not cover the IMD 24-hour window")
    cursor=start;total=None
    for a,b,array in chosen:
        if a!=cursor:raise ValueError("Gap in forecast rainfall window")
        total=array.copy() if total is None else total+array;cursor=b
    if cursor!=end:raise ValueError("Forecast rainfall window ends at the wrong time")
    return total


def _ecmwf_window(source,date,cycle,start,end,cache,latitude,longitude,target_mask=None):
    model="aifs-single" if source=="AIFS" else "ifs"
    fields={};provenance=[]
    try:
        for step in [start,end]:
            path=Path(cache)/f"imd-window-{source.lower()}-{date}-{cycle:02}-{step:03}.grib2"
            provider=_ecmwf_retrieve(path,date,cycle,step,model)
            field=decode(path,latitude,longitude)["tp"];validate_run({"tp":field},date,cycle,step)
            if field["start"]!=0 or field["units"] not in ("m","kg m**-2","kg m-2"):
                raise ValueError("ECMWF rainfall is not cumulative from initialization")
            fields[step]=field;provenance.append({"lead":step,"sha256":sha256(path),**provider})
        if fields[start]["units"]!=fields[end]["units"]:raise ValueError("ECMWF precipitation units changed")
        scale=1000 if fields[end]["units"]=="m" else 1
        rain=(fields[end]["array"]-fields[start]["array"])*scale
        minimum=float(np.nanmin(rain))
        if minimum < -0.1:
            raise ValueError("ECMWF IMD-window rainfall contains a material negative reset")
        negative=int(np.sum(rain<0))
        if negative:
            provenance.append({"quality_flag":"tiny_negative_accumulation_noise_clipped",
                               "cells":negative,"minimum_mm":minimum,"tolerance_mm":-0.1})
        return np.maximum(rain,0),provenance
    except Exception as direct_error:
        from .open_meteo import precipitation_window_points
        initialization=datetime.strptime(date+f"{cycle:02}","%Y%m%d%H").replace(tzinfo=timezone.utc)
        yy,xx=np.meshgrid(np.asarray(latitude,dtype=float),np.asarray(longitude,dtype=float),indexing="ij")
        mask=np.ones_like(yy,dtype=bool) if target_mask is None else np.asarray(target_mask,dtype=bool)
        if mask.shape!=yy.shape or not mask.any():
            raise ValueError("Open-Meteo IMD fallback requires valid target cells")
        values,supplemental=precipitation_window_points(
            source,initialization,start,end,cache,yy[mask],xx[mask]
        )
        rain=np.full_like(yy,np.nan,dtype=float);rain[mask]=values
        return rain,[{
            "fallback":"Open-Meteo Single Runs",
            "direct_error_type":type(direct_error).__name__,
            "direct_provider_remains_canonical":True,
            "window_hours":[start,end],
        },*supplemental]
def fetch_forecast_window(initialization,nominal_lead,cache,target_mask=None):
    initialization=utc(initialization)
    if initialization.hour!=0 or initialization.minute or initialization.second:
        raise ValueError("IMD exact-window verification currently uses 00 UTC forecast initializations")
    if nominal_lead not in LEADS:raise ValueError("Unsupported IMD gauge verification lead")
    start,end=nominal_lead-21,nominal_lead+3
    date=initialization.strftime("%Y%m%d");cycle=0
    latitude,longitude=GRIDS["india"]["lat"],GRIDS["india"]["lon"]
    result={};provenance={}
    for source in ["GFS","GEFS"]:
        increments,info=_noaa_increment_series(source,date,cycle,end,cache,latitude,longitude)
        result[source]=_sum_window(increments,start,end);provenance[source]=info
    for source in ["IFS","AIFS"]:
        result[source],provenance[source]=_ecmwf_window(
            source,date,cycle,start,end,cache,latitude,longitude,target_mask=target_mask
        )
    return np.stack([result[source] for source in SOURCES]),provenance


def verify_cycle_lead(initialization,nominal_lead,cache,reference_dir,report_dir):
    initialization=utc(initialization);valid_end=initialization+timedelta(hours=nominal_lead+3)
    reference_path=save_imd_reference(reference_dir,valid_end,cache)
    meta=json.loads(reference_path.read_text());values_path=reference_path.parent/meta["values_file"]
    if sha256(values_path)!=meta["values_sha256"]:raise ValueError("IMD reference checksum failed")
    observed=np.load(values_path,allow_pickle=False).astype(float)
    reference_mask=np.isfinite(observed)
    forecast,provenance=fetch_forecast_window(initialization,nominal_lead,cache,target_mask=reference_mask)
    mask=reference_mask&np.isfinite(forecast).all(axis=0)
    if not mask.any():raise ValueError("No collocated IMD gauge/model grid cells")
    latitude=GRIDS["india"]["lat"];area=np.cos(np.deg2rad(np.broadcast_to(latitude[:,None],observed.shape)))[mask]
    samples=forecast[:,mask].T[:,:,None]
    equal=np.full((len(samples),len(SOURCES)),1/len(SOURCES))
    scores=[]
    for i,source in enumerate(SOURCES):
        weights=np.zeros_like(equal);weights[:,i]=1
        scores.append({"model":source,**_scalar_score(samples,observed[mask],weights,area,THRESHOLDS)})
    scores.append({"model":"Equal point mixture",**_scalar_score(samples,observed[mask],equal,area,THRESHOLDS)})
    report={
        "schema_version":1,"data_kind":"gauge_verification","initialization":initialization.isoformat(),
        "nominal_lead_hours":nominal_lead,"forecast_window_start":(valid_end-timedelta(hours=24)).isoformat(),
        "forecast_window_end":valid_end.isoformat(),"reference_id":meta["reference_id"],
        "reference_kind":meta["reference_kind"],"collocated_cells":int(mask.sum()),"scores":scores,
        "source_ids":SOURCES,"source_provenance":provenance,
        "adaptive_evaluated":False,
        "limitation":"Exact 03-03 UTC raw-source/equal-baseline validation. The existing 00-00 adaptive gate is not transferred to this different accumulation window.",
        "generated_at":datetime.now(timezone.utc).isoformat(),
    }
    report_dir=Path(report_dir);report_dir.mkdir(parents=True,exist_ok=True)
    target=report_dir/f"imd-gauge-{initialization:%Y%m%d}-f{nominal_lead:03}.json"
    atomic_write(target,json_bytes(report));return report


def build_status(report_dir,public_dir):
    rows=[]
    for path in sorted(Path(report_dir).glob("imd-gauge-*.json")):
        try: rows.append(json.loads(path.read_text()))
        except (OSError,json.JSONDecodeError):continue
    rows.sort(key=lambda row:(row["initialization"],row["nominal_lead_hours"]),reverse=True)
    status={"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),
            "state":"operational_reference_pipeline","reference_id":"imd-gauge-grid-025-realtime",
            "rows":rows[:50],
            "policy":"IMD gauge-grid comparisons use exact 03:00-03:00 UTC accumulation windows; no 00:00-00:00 substitution is permitted."}
    target=Path(public_dir)/"imd-gauge-status.json";atomic_write(target,json_bytes(status));target.chmod(0o644)
    return status


def _public_initializations(public_dir):
    rows={}
    for path in Path(public_dir).glob("public-*.json"):
        try:
            product=json.loads(path.read_text())
            initialization=utc(product["initialization"])
            if (product.get("data_kind")=="forecast" and product.get("coverage","india")=="india"
                and initialization.hour==0 and all(product.get("source_status",{}).get(s)=="loaded" for s in SOURCES)):
                rows[initialization]=product["run_id"]
        except (OSError,ValueError,KeyError,json.JSONDecodeError):
            continue
    return sorted(rows,reverse=True)


def run_due(runtime,cache,public_dir,max_windows=1,latency_hours=6,now=None):
    runtime,cache,public_dir=Path(runtime),Path(cache),Path(public_dir)
    reference_dir=runtime/"imd-gauge-references";report_dir=runtime/"imd-gauge-reports"
    reference_dir.mkdir(parents=True,exist_ok=True);report_dir.mkdir(parents=True,exist_ok=True)
    now=utc(now or datetime.now(timezone.utc));processed=[];deferred=[]
    with file_lock(runtime/".imd-gauge.lock",blocking=False):
        due=[]
        for initialization in _public_initializations(public_dir):
            for lead in LEADS:
                valid_end=initialization+timedelta(hours=lead+3)
                report_path=report_dir/f"imd-gauge-{initialization:%Y%m%d}-f{lead:03}.json"
                if valid_end<=now-timedelta(hours=latency_hours) and not report_path.exists():
                    due.append((valid_end,initialization,lead))
        # Round-robin retries: an unavailable old window must not starve newer work.
        retry_path=runtime/"imd-window-attempts.json"
        attempts=json.loads(retry_path.read_text()) if retry_path.exists() else {}
        due.sort(key=lambda row:(attempts.get(f"{row[1].isoformat()}:{row[2]}",""),row[0]))
        for _,initialization,lead in due[:max_windows]:
            attempts[f"{initialization.isoformat()}:{lead}"]=now.isoformat()
            try:
                report=verify_cycle_lead(initialization,lead,cache,reference_dir,report_dir)
                processed.append({"initialization":initialization.isoformat(),"lead":lead,
                                  "collocated_cells":report["collocated_cells"]})
            except Exception as error:
                deferred.append({"initialization":initialization.isoformat(),"lead":lead,
                                 "reason":type(error).__name__})
        atomic_write(retry_path,json_bytes(attempts))
        status=build_status(report_dir,public_dir)
        service={"schema_version":1,"checked_at":datetime.now(timezone.utc).isoformat(),
                 "processed":processed,"deferred":deferred,"reports_available":len(status["rows"])}
        atomic_write(runtime/"imd-gauge-service-status.json",json_bytes(service))
        return service


def main():
    import argparse,time
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime",required=True);parser.add_argument("--cache",required=True)
    parser.add_argument("--public",required=True);parser.add_argument("--max-windows",type=int,default=1)
    parser.add_argument("--latency-hours",type=int,default=6);parser.add_argument("--interval",type=int,default=3600)
    parser.add_argument("--loop",action="store_true")
    args=parser.parse_args()
    if not 1<=args.max_windows<=8 or not 3<=args.latency_hours<=48 or args.interval<300:
        parser.error("Invalid IMD gauge scheduling bounds")
    while True:
        try: result=run_due(args.runtime,args.cache,args.public,args.max_windows,args.latency_hours)
        except BlockingIOError: result={"schema_version":1,"status":"skipped","reason":"Another IMD gauge cycle owns the lock"}
        print(json.dumps(result),flush=True)
        if not args.loop:return
        time.sleep(args.interval)


if __name__=="__main__":
    main()

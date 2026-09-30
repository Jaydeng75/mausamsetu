"""Read-only readiness probes for Indian forecast, observation and context providers.

No probe bypasses TLS, logs in implicitly, or turns catalogue availability into
a claim that numerical data are authorized or scientifically accepted.
"""
import argparse,csv,hashlib,io,json,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
import httpx
from .storage import atomic_write,json_bytes

IMD_PORTAL="https://api.imd.gov.in/public/index.php"
IMD_API_DEFAULT="https://mausam.imd.gov.in/api/districtwise_rainfall_api.php"
IMD_REALTIME_FORM="https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/Rain_Download.html"
IMD_REALTIME_POST="https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
IMD_REALTIME_BYTES=129*135*4
MOSDAC_SEARCH="https://mosdac.gov.in/apios/datasets.json"
MOSDAC_RAIN="3SIMG_L2G_IMR"
INCOIS_CATALOG="https://erddap.incois.gov.in/erddap/tabledap/allDatasets.csv?datasetID,title,institution,dataStructure,cdm_data_type"
INCOIS_CONTEXT_IDS={
 "ascat_daily_datasets":"ASCAT ocean-surface wind; through 2023-05-21",
 "incois_valueadded_products_datasets":"Ocean heat/mixed-layer diagnostics; through 2019-03-30",
 "incois_tmi_3day_datasets":"Historical TMI SST/wind/vapour/rain; through 2014-12-31"}

def now_iso():return datetime.now(timezone.utc).isoformat()
def result(name,role,status,**extra):return {"name":name,"role":role,"status":status,**extra}
def probe_imd(client=None):
    own=client is None;client=client or httpx.Client(timeout=15,follow_redirects=False)
    try:
        portal=client.get(IMD_PORTAL)
        if portal.status_code!=200:return result("IMD API","verification","unavailable",http_status=portal.status_code)
        endpoint=os.getenv("IMD_API_URL",IMD_API_DEFAULT);headers={}
        if os.getenv("IMD_API_TOKEN"):headers["Authorization"]="Bearer "+os.environ["IMD_API_TOKEN"]
        response=client.get(endpoint,headers=headers)
        if response.status_code in (401,403):
            return result("IMD API","verification","access_required",http_status=response.status_code,
              note="Official portal is reachable; this numerical endpoint requires approved access/IP whitelisting.")
        if response.status_code>=400:return result("IMD API","verification","endpoint_error",http_status=response.status_code)
        return result("IMD API","verification","authorized_endpoint_reachable",http_status=response.status_code,
          note="Reachability only; response normalization and scientific QC remain separate.")
    except httpx.HTTPError as error:
        return result("IMD API","verification","probe_failed",error_type=type(error).__name__)
    finally:
        if own:client.close()

def probe_imd_realtime(client=None, now=None):
    own=client is None;client=client or httpx.Client(timeout=30,follow_redirects=True)
    now=now or datetime.now(timezone.utc)
    valid_date=now.date() if now.hour>=3 else (now.date()-timedelta(days=1))
    try:
        try: client.get(IMD_REALTIME_FORM)
        except httpx.HTTPError: pass
        response=client.post(IMD_REALTIME_POST,data={"rain":valid_date.strftime("%d%m%Y")})
        response.raise_for_status()
        expected=f"rain_ind0.25_{valid_date:%y_%m_%d}.grd"
        disposition=response.headers.get("content-disposition","")
        mime=response.headers.get("content-type","").split(";")[0]
        if mime!="application/octet-stream" or expected not in disposition or len(response.content)!=IMD_REALTIME_BYTES:
            return result("IMD realtime 0.25° rainfall","gauge_gridded_verification","schema_changed",
              http_status=response.status_code,bytes=len(response.content),
              note="Public endpoint responded, but binary filename/MIME/size no longer match the validated contract.")
        return result("IMD realtime 0.25° rainfall","gauge_gridded_verification","realtime_grid_ready",
          http_status=response.status_code,latest_identifier=expected,
          latest_valid_interval=f"{(valid_date-timedelta(days=1)).isoformat()}T03:00:00Z/{valid_date.isoformat()}T03:00:00Z",
          note="Public 0.25° gauge-gridded binary validated; exact 03:00→03:00 UTC scoring pipeline is enabled.")
    except httpx.HTTPError as error:
        return result("IMD realtime 0.25° rainfall","gauge_gridded_verification","probe_failed",
          error_type=type(error).__name__)
    finally:
        if own:client.close()

def probe_imd_grid(directory=None):
    raw=directory or os.getenv("MAUSAM_IMD_GRID_DIR")
    if not raw:return result("IMD 0.25° rainfall","historical_verification","staged_file_not_configured")
    root=Path(raw)
    if not root.is_dir():return result("IMD 0.25° rainfall","historical_verification","staged_file_not_configured")
    manifests=sorted(root.glob("ind*_rfp25.manifest.json"),reverse=True)
    for manifest in manifests:
        try:
            meta=json.loads(manifest.read_text());data=root/meta["file"]
            if not data.is_file():continue
            if hashlib.sha256(data.read_bytes()).hexdigest()!=meta["sha256"]:continue
            return result("IMD 0.25° rainfall","historical_verification","historical_grid_staged",
              year=meta.get("year"),product=meta.get("product"),units=meta.get("units"),
              note=meta.get("blocking_issue","Exact forecast/observation interval collocation still requires review."))
        except (OSError,ValueError,KeyError,TypeError):continue
    return result("IMD 0.25° rainfall","historical_verification","staged_integrity_failed")

def mosdac_search(dataset_id=MOSDAC_RAIN,client=None,count=1):
    own=client is None;client=client or httpx.Client(timeout=15,follow_redirects=False)
    try:
        response=client.get(MOSDAC_SEARCH,params={"datasetId":dataset_id,"count":count})
        response.raise_for_status();body=response.json();entries=body.get("entries") or []
        return {"dataset_id":dataset_id,"total_results":body.get("totalResults"),"latest":entries[0] if entries else None}
    finally:
        if own:client.close()

def probe_mosdac(client=None):
    try:found=mosdac_search(client=client)
    except (httpx.HTTPError,ValueError,KeyError) as error:
        return result("MOSDAC","satellite_verification_and_context","probe_failed",error_type=type(error).__name__)
    latest=found["latest"];configured=bool(os.getenv("MOSDAC_USERNAME") and os.getenv("MOSDAC_PASSWORD"))
    return result("MOSDAC","satellite_verification_and_context",
      "catalogue_ready_credentials_configured" if configured else "catalogue_ready_download_credentials_required",
      dataset_id=found["dataset_id"],latest_identifier=(latest or {}).get("identifier"),
      latest_valid_interval=(latest or {}).get("dcDate"),catalogue_results=found["total_results"],
      note="Catalogue search is public. Numerical HDF5 download requires an authorized MOSDAC account.")

def parse_erddap_catalog(text):
    rows=list(csv.DictReader(io.StringIO(text)))
    return {r["datasetID"]:r for r in rows if r.get("datasetID") and r["datasetID"]!="allDatasets"}

def probe_incois(client=None):
    own=client is None;verify=os.getenv("INCOIS_CA_BUNDLE") or True
    client=client or httpx.Client(timeout=20,follow_redirects=False,verify=verify)
    try:
        response=client.get(INCOIS_CATALOG);response.raise_for_status();rows=parse_erddap_catalog(response.text)
        active=sorted(set(rows)&set(INCOIS_CONTEXT_IDS))
        return result("INCOIS ERDDAP","historical_ocean_context","catalogue_ready" if active else "catalogue_changed",
          dataset_count=len(rows),datasets=active,
          note="Selected active archives are historical; they are not valid as live 2026 gate context.")
    except httpx.HTTPError as error:
        tls="certificate" in str(error).lower() or "ssl" in str(error).lower()
        return result("INCOIS ERDDAP","historical_ocean_context",
          "tls_configuration_required" if tls else "probe_failed",error_type=type(error).__name__,
          note="TLS verification was not disabled; configure an approved CA bundle if required.")
    finally:
        if own:client.close()
def probe_neps(directory=None):
    raw=directory or os.getenv("MAUSAM_NEPS_RESEARCH_DIR")
    if not raw:return result("NEPS / TIGGE","delayed_research_forecast","adapter_ready_credentials_or_sample_required",delay_hours=48,public_projection=False)
    root=Path(raw);manifest=root/"manifest.json"
    if root.is_dir() and manifest.is_file():
        try:
            data=json.loads(manifest.read_text())
            if "NCMRWF" in str(data.get("provider","")):
                return result("NEPS / TIGGE","delayed_research_forecast","local_research_sample_ready",
                  delay_hours=48,public_projection=False,retrieved_at=data.get("retrieved_at"))
        except (OSError,ValueError,TypeError):pass
    return result("NEPS / TIGGE","delayed_research_forecast","sample_integrity_not_established",delay_hours=48,public_projection=False)

def probe_ncum(directory=None):
    raw=directory or os.getenv("MAUSAM_NCUM_STAGING_DIR")
    if not raw:return result("NCUM","institutional_forecast","access_required",public_projection=False)
    root=Path(raw)
    if not root.is_dir():return result("NCUM","institutional_forecast","access_required",public_projection=False)
    valid=0
    for meta_path in root.glob("*.json"):
        try:
            meta=json.loads(meta_path.read_text());file=root/meta["file"]
            if meta.get("status")!="staged_requires_product_specific_normalization" or not file.is_file():continue
            if hashlib.sha256(file.read_bytes()).hexdigest()!=meta.get("sha256"):continue
            if not meta.get("authorization_reference") or not meta.get("licence"):continue
            valid+=1
        except (OSError,ValueError,KeyError,TypeError):continue
    return result("NCUM","institutional_forecast","authorized_file_staged" if valid else "access_required",
      public_projection=False,numerical_files=valid)
def probe_all(research_neps_dir=None,ncum_staging_dir=None,imd_grid_dir=None):
    providers=[probe_imd(),probe_imd_realtime(),probe_imd_grid(imd_grid_dir),probe_mosdac(),probe_incois(),
               probe_neps(research_neps_dir),probe_ncum(ncum_staging_dir)]
    return {"schema_version":1,"checked_at":now_iso(),"providers":providers,
      "policy":"Readiness only. Provider reachability is not scientific acceptance or redistribution permission.",
      "rules":["No TLS-verification bypass.","Verification sources are not forecast sources.",
               "Historical context is not used after its valid time.","NCUM readiness requires an authorized import manifest plus checksum-matching numerical file."]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--neps-dir");parser.add_argument("--ncum-dir");parser.add_argument("--imd-grid-dir")
    args=parser.parse_args();report=probe_all(args.neps_dir,args.ncum_dir,args.imd_grid_dir)
    args.output.parent.mkdir(parents=True,exist_ok=True);atomic_write(args.output,json_bytes(report))
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()

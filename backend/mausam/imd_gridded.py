"""Retrieve and inventory IMD Pune yearly 0.25-degree gridded rainfall NetCDF."""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import httpx, xarray as xr
from .storage import atomic_write, json_bytes

FORM_URL="https://imdpune.gov.in/cmpg/Griddata/RF25.php"
FILE_BASE="https://imdpune.gov.in/cmpg/Griddata/RF25"
PAGE="https://imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html"

def download_year(year,output,max_bytes=128_000_000):
    now=datetime.now(timezone.utc)
    if year<1901 or year>now.year: raise ValueError("Invalid IMD rainfall year")
    output=Path(output)
    if "public" in output.resolve().parts: raise ValueError("Keep raw IMD observations outside public web assets")
    output.mkdir(parents=True,exist_ok=True);target=output/f"ind{year}_rfp25.nc";part=target.with_suffix(".part")
    url=f"{FILE_BASE}/ind{year}_rfp25.nc"
    with httpx.stream("GET",url,headers={"User-Agent":"MausamSetu-SIH26081/0.1"},
                      timeout=180,follow_redirects=False) as response:
        response.raise_for_status();size=0
        with part.open("wb") as stream:
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>max_bytes: raise ValueError("IMD file exceeds configured size bound")
                stream.write(chunk)
    header=part.read_bytes()[:8]
    if not (header.startswith(b"CDF") or header==b"\x89HDF\r\n\x1a\n"):
        part.unlink(missing_ok=True);raise ValueError("Downloaded IMD object is not NetCDF/HDF")
    part.replace(target);return inventory(target,year)

def inventory(path,year):
    path=Path(path);digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with xr.open_dataset(path) as ds:
        var="RAINFALL" if "RAINFALL" in ds.data_vars else next(iter(ds.data_vars))
        rain=ds[var];units=str(rain.attrs.get("units",""))
        lat_name=next((x for x in ("LATITUDE","latitude","lat") if x in ds.coords),None)
        lon_name=next((x for x in ("LONGITUDE","longitude","lon") if x in ds.coords),None)
        time_name=next((x for x in ("TIME","time") if x in ds.coords),None)
        if not all((lat_name,lon_name,time_name)): raise ValueError("IMD coordinate schema not recognized")
        if units.lower() not in ("mm","millimeter","millimetres","millimeters"): raise ValueError("Unexpected IMD rainfall units")
        meta={"provider":"India Meteorological Department, Climate Research & Services Pune",
          "product":"0.25 degree daily gridded rainfall","year":year,"file":path.name,"sha256":digest,
          "variable":var,"units":units,"shape":list(rain.shape),"latitude_points":int(ds.sizes[lat_name]),
          "longitude_points":int(ds.sizes[lon_name]),"time_points":int(ds.sizes[time_name]),
          "latitude_range":[float(ds[lat_name].min()),float(ds[lat_name].max())],
          "longitude_range":[float(ds[lon_name].min()),float(ds[lon_name].max())],
          "time_units":str(ds[time_name].attrs.get("units","decoded_by_xarray")),
          "time_bounds_present":bool(ds[time_name].attrs.get("bounds")),
          "source_page":PAGE,"form_endpoint":FORM_URL,"download_endpoint":f"{FILE_BASE}/ind{year}_rfp25.nc",
          "retrieved_at":datetime.now(timezone.utc).isoformat(),
          "verification_status":"staged_not_collocated",
          "blocking_issue":"The file does not encode accumulation interval bounds; confirm the IMD daily reporting window before exact forecast verification."}
    atomic_write(path.with_suffix(".manifest.json"),json_bytes(meta));return meta

def main():
    p=argparse.ArgumentParser();p.add_argument("--year",type=int,required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();print(json.dumps(download_year(a.year,a.output),indent=2))

if __name__=="__main__": main()

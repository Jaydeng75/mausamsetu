"""Fetch public GFS/AIFS products and publish bounded browser grids.

India mode: 1 degree display sampling and six-hour forecast steps.
Global mode: 2 degree display sampling and daily forecast steps.
Native provider files and provenance are retained; display sampling is not downscaling.
"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

from .storage import atomic_write, file_lock, json_bytes

GRIDS = {
    "india": {
        "lat": np.arange(38, 4, -1, dtype=float),
        "lon": np.arange(65, 101, 1, dtype=float),
        "bbox": (65, 100, 38, 5),
        "gfs_resolution": "0p25",
        "sample_degrees": 1,
        "default_step": 6,
    },
    "global": {
        "lat": np.arange(90, -91, -2, dtype=float),
        "lon": np.arange(-180, 180, 2, dtype=float),
        "bbox": (0, 360, 90, -90),
        "gfs_resolution": "1p00",
        "sample_degrees": 2,
        "default_step": 24,
    },
}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, separators=(",", ":"), allow_nan=False)
    atomic_write(path, body.encode())


def grid(domain):
    try:
        return GRIDS[domain]
    except KeyError as exc:
        raise ValueError("Unsupported forecast domain") from exc


def _sample_regular_ll(handle, values, latitudes, longitudes):
    from eccodes import codes_get
    if codes_get(handle, "gridType") != "regular_ll":
        raise ValueError("Only regular latitude/longitude GRIB grids are supported")
    ni, nj = int(codes_get(handle, "Ni")), int(codes_get(handle, "Nj"))
    if ni * nj != len(values) or int(codes_get(handle, "jPointsAreConsecutive")):
        raise ValueError("Unexpected GRIB scanning layout")
    if int(codes_get(handle, "alternativeRowScanning")):
        raise ValueError("Alternative row scanning is unsupported")
    first_lat = float(codes_get(handle, "latitudeOfFirstGridPointInDegrees"))
    first_lon = float(codes_get(handle, "longitudeOfFirstGridPointInDegrees")) % 360
    di = float(codes_get(handle, "iDirectionIncrementInDegrees"))
    dj = float(codes_get(handle, "jDirectionIncrementInDegrees"))
    i_negative = bool(codes_get(handle, "iScansNegatively"))
    j_positive = bool(codes_get(handle, "jScansPositively"))
    if di <= 0 or dj <= 0 or i_negative:
        raise ValueError("Unsupported GRIB grid direction")

    yi = np.rint((latitudes - first_lat) / dj if j_positive else (first_lat - latitudes) / dj).astype(int)
    target_lon = np.mod(longitudes, 360)
    xi = np.rint(np.mod(target_lon - first_lon, 360) / di).astype(int)
    if (yi < 0).any() or (yi >= nj).any() or (xi < 0).any() or (xi >= ni).any():
        raise ValueError("Requested display grid is outside provider grid")
    reconstructed_lat = first_lat + yi * dj if j_positive else first_lat - yi * dj
    reconstructed_lon = np.mod(first_lon + xi * di, 360)
    if not np.allclose(reconstructed_lat, latitudes, atol=1e-5) or not np.allclose(
        reconstructed_lon, target_lon, atol=1e-5
    ):
        raise ValueError("Requested display grid is not aligned to provider grid")
    array = np.asarray(values).reshape(nj, ni)
    return array[np.ix_(yi, xi)]


def decode(path, latitudes, longitudes):
    from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release
    fields = {}
    with open(path, "rb") as stream:
        while (handle := codes_grib_new_from_file(stream)) is not None:
            try:
                key = codes_get(handle, "shortName")
                values = codes_get_array(handle, "values")
                sampled = _sample_regular_ll(handle, values, latitudes, longitudes)
                if not np.isfinite(sampled).all() or np.any(np.abs(sampled) > 1e10):
                    raise ValueError("Missing/invalid GRIB values")
                try:
                    ensemble_size = int(codes_get(handle, "numberOfForecastsInEnsemble"))
                except Exception:
                    ensemble_size = None
                # Prefer the shortest precipitation interval ending at this lead.
                # NOMADS also returns cumulative APCP; message order is not a contract.
                if key == "tp" and key in fields and fields[key]["end"] == int(codes_get(handle, "endStep")) and fields[key]["start"] > int(codes_get(handle, "startStep")):
                    continue
                try:
                    packing_resolution = 2.0 ** int(codes_get(handle, "binaryScaleFactor")) * 10.0 ** -int(codes_get(handle, "decimalScaleFactor"))
                except Exception:
                    packing_resolution = 0.0
                fields[key] = {
                    "packing_resolution": packing_resolution,
                    "array": sampled,
                    "ensemble_size": ensemble_size,
                    "units": codes_get(handle, "units"),
                    "start": int(codes_get(handle, "startStep")),
                    "end": int(codes_get(handle, "endStep")),
                    "date": int(codes_get(handle, "dataDate")),
                    "time": int(codes_get(handle, "dataTime")),
                    "edition": int(codes_get(handle, "edition")),
                    "centre": str(codes_get(handle, "centre")),
                    "param_id": int(codes_get(handle, "paramId")),
                    "generating_process": int(codes_get(handle, "generatingProcessIdentifier")),
                    "tables_version": int(codes_get(handle, "tablesVersion")),
                    "native_grid": {
                        "ni": int(codes_get(handle, "Ni")),
                        "nj": int(codes_get(handle, "Nj")),
                        "di": float(codes_get(handle, "iDirectionIncrementInDegrees")),
                        "dj": float(codes_get(handle, "jDirectionIncrementInDegrees")),
                    },
                }
            finally:
                codes_release(handle)
    return fields


def checked_get(url, target, params=None):
    if target.exists():
        cached = target.read_bytes()
        if cached.startswith(b"GRIB") and cached.endswith(b"7777"):
            return
        target.unlink(missing_ok=True)
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                response = client.get(url, params=params)
                response.raise_for_status()
                if not response.content.startswith(b"GRIB") or not response.content.endswith(b"7777"):
                    raise ValueError("Provider did not return a complete GRIB file")
                if len(response.content) > 256_000_000:
                    raise ValueError("Provider file exceeds configured size bound")
                atomic_write(target, response.content)
                return
            except (httpx.HTTPError, ValueError):
                if attempt == 2:
                    raise
                time.sleep(2**attempt)



def _gefs_retrieve(filter_url, params, fallback_url, path):
    path = Path(path)
    sidecar = path.with_suffix(path.suffix + ".source.json")
    if path.exists():
        source = "cached"
        url = None
        if sidecar.exists():
            try:
                cached = json.loads(sidecar.read_text())
                source, url = cached.get("source", "cached"), cached.get("url")
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return source, url
    try:
        checked_get(filter_url, path, params)
        source, url = "nomads_filter", str(httpx.URL(filter_url, params=params))
    except (httpx.HTTPError, ValueError):
        path.unlink(missing_ok=True)
        checked_get(fallback_url, path)
        source, url = "noaa_aws_archive", fallback_url
    atomic_write(sidecar, json_bytes({
        "source": source, "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat()
    }))
    return source, url

def validate_run(fields, date, cycle, lead):
    if not fields:
        raise ValueError("Empty source file")
    for field in fields.values():
        if (field["date"], field["time"], field["end"]) != (int(date), cycle * 100, lead):
            raise ValueError("Source run/lead does not match requested product")


def convert(fields, rain):
    temperature, u, v = fields["2t"], fields["10u"], fields["10v"]
    pressure = fields.get("msl", fields.get("prmsl"))
    if pressure is None:
        raise ValueError("Mean sea level pressure field is missing")
    if temperature["units"] != "K" or pressure["units"] != "Pa":
        raise ValueError("Unexpected temperature or pressure units")
    if u["units"] not in ("m s**-1", "m s-1") or v["units"] != u["units"]:
        raise ValueError("Unexpected wind units")
    if np.any(rain[np.isfinite(rain)] < -0.01):
        raise ValueError("Negative accumulated precipitation")
    arrays = {
        "temperature": temperature["array"] - 273.15,
        "u": u["array"],
        "v": v["array"],
        "wind": np.hypot(u["array"], v["array"]),
        "pressure": pressure["array"] / 100,
        "rain": np.maximum(rain, 0),
    }
    return {
        key: [round(float(value), 3) if np.isfinite(value) else None for value in array.ravel()]
        for key, array in arrays.items()
    }


def precipitation_increment(field, previous=None):
    """Reject resets; clip only negatives bounded by source quantization precision.

    NOAA complex packing may truncate, so use one packing unit per operand.
    Metadata is retained in provider provenance; no fixed physical tolerance is widened.
    """
    delta = field["array"] if previous is None else field["array"] - previous["array"]
    tolerance = sum(float(f.get("packing_resolution", 0.0)) for f in (field, previous) if f is not None)
    if not np.isfinite(tolerance) or tolerance < 0 or tolerance > 0.5:
        raise ValueError("Unsupported precipitation packing precision")
    tolerance = max(0.01, tolerance)
    if np.nanmin(delta) < -tolerance - 1e-8:
        raise ValueError("Precipitation accumulation reset exceeds packing precision")
    return np.maximum(delta, 0)


def gfs(date, cycle, leads, cache, domain):
    config = grid(domain)
    latitudes, longitudes = config["lat"], config["lon"]
    resolution = config["gfs_resolution"]
    left, right, top, bottom = config["bbox"]
    raw, provenance = {}, []
    for hour in range(6, max(leads) + 1, 6):
        filename = f"gfs-{date}-{cycle:02}-{hour:03}.grib2" if domain == "india" else f"gfs-{resolution}-{date}-{cycle:02}-{hour:03}.grib2"
        path = cache / filename
        params = {
            "file": f"gfs.t{cycle:02}z.pgrb2.{resolution}.f{hour:03}",
            "dir": f"/gfs.{date}/{cycle:02}/atmos",
            "subregion": "",
            "leftlon": left,
            "rightlon": right,
            "toplat": top,
            "bottomlat": bottom,
            "lev_2_m_above_ground": "on",
            "lev_10_m_above_ground": "on",
            "lev_mean_sea_level": "on",
            "lev_surface": "on",
            "var_TMP": "on",
            "var_UGRD": "on",
            "var_VGRD": "on",
            "var_PRMSL": "on",
            "var_APCP": "on",
        }
        url = f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_{resolution}.pl"
        checked_get(url, path, params)
        raw[hour] = decode(path, latitudes, longitudes)
        validate_run(raw[hour], date, cycle, hour)
        provenance.append(
            {
                "url": str(httpx.URL(url, params=params)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "lead": hour,
                "native_product": f"GFS pgrb2 {resolution}",
                "field_metadata": {
                    key: {name: value for name, value in field.items() if name != "array"}
                    for key, field in raw[hour].items()
                },
            }
        )
        print(f"GFS {domain} +{hour} decoded", flush=True)

    output = {}
    for hour in leads:
        rain = np.zeros((len(latitudes), len(longitudes)))
        for step in range(hour - 18, hour + 1, 6):
            precip = raw[step]["tp"]
            if precip["end"] != step or precip["units"] not in ("kg m**-2", "kg m-2"):
                raise ValueError("GFS precipitation interval/units changed")
            if precip["start"] == step - 6:
                delta = precipitation_increment(precip)
            elif step > 6 and raw[step - 6]["tp"]["start"] == precip["start"]:
                delta = precipitation_increment(precip, raw[step - 6]["tp"])
            else:
                raise ValueError("No matching GFS accumulation origin")
            if np.min(delta) < -0.01:
                raise ValueError("GFS accumulation reset detected")
            rain += np.maximum(delta, 0)
        output[str(hour)] = convert(raw[hour], rain)
    return output, provenance


def _ecmwf_retrieve(path, date, cycle, hour, model, label):
    from ecmwf.opendata import Client
    path = Path(path)
    sidecar = path.with_suffix(path.suffix + ".source.json")
    last_error = None
    sources = ("google", "ecmwf")
    for source in sources:
        temporary = path.with_suffix(".part")
        temporary.unlink(missing_ok=True)
        try:
            client = Client(source=source, model=model, resol="0p25",
                maximum_retries=2, retry_after=10)
            client.retrieve(date=int(date), time=cycle, step=hour, type="fc", stream="oper",
                param=["2t", "10u", "10v", "msl", "tp"], target=str(temporary))
            if not temporary.exists() or temporary.stat().st_size < 1000:
                raise ValueError(f"{label} mirror returned no usable GRIB")
            temporary.replace(path)
            atomic_write(sidecar, json_bytes({
                "source": source,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "model": model, "date": str(date), "cycle": cycle, "lead": hour,
            }))
            return source
        except Exception as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            print(f"{label} {source} retrieval failed ({type(error).__name__}); trying next mirror",
                  flush=True)
    if last_error is None:
        raise RuntimeError(f"{label} retrieval had no configured mirrors")
    raise last_error


def ecmwf_deterministic(date, cycle, leads, cache, domain, model, label):
    config = grid(domain)
    latitudes, longitudes = config["lat"], config["lon"]
    raw, provenance = {}, []
    needed = sorted(set(leads) | {hour - 24 for hour in leads if hour > 24})
    slug = "aifs" if model == "aifs-single" else "ifs"
    from eccodes import CodesInternalError
    for hour in needed:
        path = cache / f"{slug}-{date}-{cycle:02}-{hour:03}.grib2"
        lock_path = cache / f".{slug}-{date}-{cycle:02}-{hour:03}.lock"
        retrieval_source = "cached"
        with file_lock(lock_path):
            for attempt in range(2):
                if not path.exists():
                    with file_lock(cache / ".ecmwf-open-data.lock"):
                        retrieval_source = _ecmwf_retrieve(
                            path, date, cycle, hour, model, label
                        )
                        time.sleep(1)
                else:
                    sidecar = path.with_suffix(path.suffix + ".source.json")
                    if sidecar.exists():
                        try:
                            retrieval_source = json.loads(sidecar.read_text()).get("source", "cached")
                        except (OSError, ValueError, json.JSONDecodeError):
                            retrieval_source = "cached"
                try:
                    raw[hour] = decode(path, latitudes, longitudes)
                    validate_run(raw[hour], date, cycle, hour)
                    break
                except CodesInternalError:
                    path.unlink(missing_ok=True)
                    path.with_suffix(path.suffix + ".source.json").unlink(missing_ok=True)
                    if attempt == 1:
                        raise
                    print(f"{label} +{hour} cached GRIB failed integrity decode; retrying provider retrieval", flush=True)
        provenance.append({
            "product": f"ECMWF Open Data / {model} / oper / fc / 0p25",
            "date": date, "cycle": cycle, "lead": hour, "retrieval_source": retrieval_source,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "field_metadata": {key:{name:value for name,value in field.items() if name!="array"}
                for key,field in raw[hour].items()},
        })
        print(f"{label} {domain} +{hour} decoded", flush=True)
    output = {}
    for hour in leads:
        precip = raw[hour]["tp"]
        if precip["start"] != 0 or precip["units"] not in ("m", "kg m**-2", "kg m-2"):
            raise ValueError(f"{label} expected precipitation accumulated from initialization with known units")
        prior = raw[hour-24]["tp"]["array"] if hour > 24 else 0
        rain = (precip["array"] - prior) * (1000 if precip["units"] == "m" else 1)
        negative = rain < 0
        if negative.any():
            provenance.append({"lead":hour,"quality_flag":"negative_accumulation_difference",
                "withheld_rain_cells":int(negative.sum()),"minimum_mm":float(rain.min())})
        output[str(hour)] = convert(raw[hour], np.where(negative, np.nan, rain))
    return output, provenance


def aifs(date, cycle, leads, cache, domain):
    return ecmwf_deterministic(date, cycle, leads, cache, domain, "aifs-single", "AIFS")


def ifs(date, cycle, leads, cache, domain):
    return ecmwf_deterministic(date, cycle, leads, cache, domain, "ifs", "IFS")


def gefs(date, cycle, leads, cache, domain):
    config = grid(domain)
    latitudes, longitudes = config["lat"], config["lon"]
    if domain == "india":
        script, resolution, kind, folder = "filter_gefs_atmos_0p25s.pl", "0p25", "pgrb2s", "pgrb2sp25"
        bbox = config["bbox"]
    else:
        script, resolution, kind, folder = "filter_gefs_atmos_0p50a.pl", "0p50", "pgrb2a", "pgrb2ap5"
        bbox = (0, 360, 90, -90)
    url = "https://nomads.ncep.noaa.gov/cgi-bin/" + script
    common = {
        "dir": f"/gefs.{date}/{cycle:02}/atmos/{folder}", "subregion": "",
        "leftlon": bbox[0], "rightlon": bbox[1], "toplat": bbox[2], "bottomlat": bbox[3],
        "lev_2_m_above_ground": "on", "lev_10_m_above_ground": "on",
        "lev_mean_sea_level": "on", "lev_surface": "on", "var_TMP": "on",
        "var_UGRD": "on", "var_VGRD": "on", "var_PRMSL": "on", "var_APCP": "on",
    }
    raw_mean, raw_spread, provenance = {}, {}, []
    for hour in range(6, max(leads) + 1, 6):
        filename = f"geavg.t{cycle:02}z.{kind}.{resolution}.f{hour:03}"
        path = cache / f"gefs-mean-{resolution}-{date}-{cycle:02}-{hour:03}.grib2"
        params = {**common, "file": filename}
        fallback = f"https://noaa-gefs-pds.s3.amazonaws.com/gefs.{date}/{cycle:02}/atmos/{folder}/{filename}"
        retrieval_source, retrieval_url = _gefs_retrieve(url, params, fallback, path)
        raw_mean[hour] = decode(path, latitudes, longitudes)
        validate_run(raw_mean[hour], date, cycle, hour)
        provenance.append({"product": f"NOAA GEFS provider ensemble mean / {resolution}",
            "url": retrieval_url, "retrieval_source": retrieval_source,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "lead": hour})
        print(f"GEFS mean {domain} +{hour} decoded", flush=True)
    for hour in leads:
        filename = f"gespr.t{cycle:02}z.{kind}.{resolution}.f{hour:03}"
        path = cache / f"gefs-spread-{resolution}-{date}-{cycle:02}-{hour:03}.grib2"
        params = {**common, "file": filename}
        fallback = f"https://noaa-gefs-pds.s3.amazonaws.com/gefs.{date}/{cycle:02}/atmos/{folder}/{filename}"
        retrieval_source, retrieval_url = _gefs_retrieve(url, params, fallback, path)
        raw_spread[hour] = decode(path, latitudes, longitudes)
        validate_run(raw_spread[hour], date, cycle, hour)
        provenance.append({"product": f"NOAA GEFS provider ensemble spread / {resolution}",
            "url": retrieval_url, "retrieval_source": retrieval_source,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "lead": hour})
        print(f"GEFS spread {domain} +{hour} decoded", flush=True)
    mean_counts={field.get("ensemble_size") for fields in raw_mean.values() for field in fields.values() if field.get("ensemble_size") is not None}
    spread_counts={field.get("ensemble_size") for fields in raw_spread.values() for field in fields.values() if field.get("ensemble_size") is not None}
    if len(mean_counts)!=1 or mean_counts!=spread_counts:
        raise ValueError("GEFS ensemble-size metadata is missing or inconsistent")
    member_count=next(iter(mean_counts))
    if member_count < 2:
        raise ValueError("GEFS ensemble statistic reports fewer than two forecasts")
    output, spread = {}, {}
    for hour in leads:
        rain = np.zeros((len(latitudes), len(longitudes)))
        for step in range(hour - 18, hour + 1, 6):
            precip = raw_mean[step]["tp"]
            if precip["end"] != step or precip["units"] not in ("kg m**-2", "kg m-2"):
                raise ValueError("GEFS precipitation interval/units changed")
            if precip["start"] != step - 6:
                raise ValueError("GEFS mean precipitation is not a six-hour accumulation")
            if np.min(precip["array"]) < -0.01:
                raise ValueError("Negative GEFS ensemble-mean precipitation")
            rain += np.maximum(precip["array"], 0)
        output[str(hour)] = convert(raw_mean[hour], rain)
        fields = raw_spread[hour]
        t, u, v = fields["2t"], fields["10u"], fields["10v"]
        pressure = fields.get("msl", fields.get("prmsl"))
        if t["units"] != "K" or pressure is None or pressure["units"] != "Pa" or u["units"] not in ("m s**-1","m s-1") or v["units"] != u["units"]:
            raise ValueError("Unexpected GEFS spread units")
        if any(np.nanmin(field["array"]) < -1e-6 for field in (t,u,v,pressure)):
            raise ValueError("GEFS provider spread contains negative values")
        flatten = lambda a: [round(float(value), 3) if np.isfinite(value) else None for value in a.ravel()]
        spread[str(hour)] = {"temperature": flatten(t["array"]), "u": flatten(u["array"]),
            "v": flatten(v["array"]), "pressure": flatten(pressure["array"] / 100)}
    context = {"member_count": member_count, "member_count_source": "GRIB numberOfForecastsInEnsemble", "mean_source": "NOAA GEFS provider ensemble mean",
        "spread_source": "NOAA GEFS provider ensemble spread", "spread": spread,
        "rain_24h_spread": None,
        "rain_spread_note": "Not derived: provider spread files are six-hour APCP spreads and cannot be summed into a 24-hour spread."}
    return output, provenance, context

def publish(args):
    datetime.strptime(args.date, "%Y%m%d")
    config = grid(args.domain)
    args.cache.mkdir(parents=True, exist_ok=True)
    step = args.step or config["default_step"]
    if args.domain == "global" and step < 24:
        raise ValueError("Global browser product is intentionally limited to daily steps")
    leads = list(range(24, args.max_lead + 1, step))
    sources, provenance, status, ensemble_context, source_leads = {}, {}, {}, {}, {}
    for name, adapter in [("GFS", gfs), ("GEFS", gefs), ("IFS", ifs), ("AIFS", aifs)]:
        try:
            requested_leads = [hour for hour in leads if not (
                name == "IFS" and args.domain == "india" and hour % 24
            )]
            result = adapter(args.date, args.cycle, requested_leads, args.cache, args.domain)
            sources[name], provenance[name] = result[:2]
            source_leads[name] = requested_leads
            if len(result) == 3: ensemble_context[name] = result[2]
            status[name] = "loaded"
        except Exception as error:
            status[name] = f"unavailable: {type(error).__name__}: {error}"
            print(name, status[name], flush=True)
    if not sources:
        raise RuntimeError("No source completed; no product published")

    initialization = datetime.strptime(args.date + f"{args.cycle:02}", "%Y%m%d%H").replace(
        tzinfo=timezone.utc
    ).isoformat()
    prefix = "public" if args.domain == "india" else "global"
    pointer_name = "latest.json" if args.domain == "india" else "global-latest.json"
    product = {
        "schema_version": 1,
        "data_kind": "forecast",
        "coverage": args.domain,
        "run_id": f"{prefix}-{args.date}-{args.cycle:02}",
        "initialization": initialization,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "leads": leads,
        "latitude": config["lat"].tolist(),
        "longitude": config["lon"].tolist(),
        "sources": sources,
        "source_status": status,
        "source_leads": source_leads,
        "source_roles": {name: ("ensemble_mean" if name == "GEFS" else "deterministic") for name in sources},
        "ensemble_context": ensemble_context,
        "provenance": provenance,
        "grid_method": (
            f"Exact native grid points sampled every {config['sample_degrees']} degrees; "
            "browser preview, not interpolation or downscaling"
        ),
        "rain_interval_hours": 24,
        "forecast_cadence_hours": step,
        "member_kind": "deterministic sources plus GEFS provider ensemble mean/spread; member count retained from GRIB metadata",
        "calibrated": False,
        "attribution": (
            "NOAA GFS and GEFS. This service is based on ECMWF IFS and AIFS Open Data, CC BY 4.0. "
            "Fields are sampled and units converted. ECMWF accepts no liability for errors, "
            "availability or losses arising from use."
        ),
    }
    digest = hashlib.sha256(json.dumps(product, sort_keys=True).encode()).hexdigest()[:12]
    filename = f"{product['run_id']}-{digest}.json"
    write_json(args.output / filename, product)
    write_json(
        args.output / pointer_name,
        {
            "path": filename,
            "run_id": product["run_id"],
            "sha256": hashlib.sha256((args.output / filename).read_bytes()).hexdigest(),
        },
    )
    print(json.dumps({"published": filename, "pointer": pointer_name, "sources": status}))
    return product


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Explicit UTC initialization date YYYYMMDD")
    parser.add_argument("--cycle", type=int, choices=[0, 6, 12, 18], default=0)
    parser.add_argument("--domain", choices=sorted(GRIDS), default="india")
    parser.add_argument("--step", type=int, choices=[6, 24])
    parser.add_argument("--max-lead", type=int, choices=list(range(24, 169, 6)), default=168)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    publish(parser.parse_args())


if __name__ == "__main__":
    main()

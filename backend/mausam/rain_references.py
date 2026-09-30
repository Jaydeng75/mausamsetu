"""Near-real-time satellite rainfall references with explicit interval semantics."""
import hashlib
import json
import netrc
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import xarray as xr

from .storage import atomic_write, json_bytes


CMORPH_ROOT = "https://ftp.cpc.ncep.noaa.gov/precip/CMORPH2/CMORPH2NRT/DATA"
IMERG_ROOT = "https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/early"
IMERG_HOST = "jsimpsonhttps.pps.eosdis.nasa.gov"


def utc(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("UTC timestamp requires an explicit offset")
    return result.astimezone(timezone.utc)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
def checked_download(url, target, auth=None, minimum_bytes=256):
    target = Path(target)
    if target.exists() and target.stat().st_size >= minimum_bytes:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    with httpx.Client(timeout=120, follow_redirects=True, auth=auth) as client:
        for attempt in range(3):
            try:
                response = client.get(url)
                response.raise_for_status()
                if len(response.content) < minimum_bytes:
                    raise ValueError("Provider returned an undersized file")
                atomic_write(temporary, response.content)
                temporary.replace(target)
                return
            except (httpx.HTTPError, ValueError):
                temporary.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)


def target_step(target_lat, target_lon):
    if len(target_lat) < 2 or len(target_lon) < 2:
        raise ValueError("Target grid needs at least two coordinates")
    lat_step = abs(float(target_lat[1]) - float(target_lat[0]))
    lon_step = abs(float(target_lon[1]) - float(target_lon[0]))
    if not np.isclose(lat_step, lon_step):
        raise ValueError("Only square regular target grids are supported")
    return lat_step
def area_mean_to_grid(values, source_lat, source_lon, target_lat, target_lon, minimum_fraction=0.9):
    values = np.asarray(values, dtype=float)
    source_lat = np.asarray(source_lat, dtype=float)
    source_lon = ((np.asarray(source_lon, dtype=float) + 180) % 360) - 180
    target_lat = np.asarray(target_lat, dtype=float)
    target_lon = ((np.asarray(target_lon, dtype=float) + 180) % 360) - 180
    if values.shape != (len(source_lat), len(source_lon)):
        raise ValueError("Source coordinate shape mismatch")
    step = target_step(target_lat, target_lon)
    result = np.full((len(target_lat), len(target_lon)), np.nan)
    coverage = np.zeros_like(result)

    for yi, latitude in enumerate(target_lat):
        lat_mask = (source_lat >= latitude - step / 2) & (source_lat < latitude + step / 2)
        lat_idx = np.flatnonzero(lat_mask)
        if not len(lat_idx):
            continue
        lat_weights = np.cos(np.deg2rad(source_lat[lat_idx]))
        for xi, longitude in enumerate(target_lon):
            delta = ((source_lon - longitude + 180) % 360) - 180
            lon_idx = np.flatnonzero((delta >= -step / 2) & (delta < step / 2))
            if not len(lon_idx):
                continue
            block = values[np.ix_(lat_idx, lon_idx)]
            valid = np.isfinite(block)
            coverage[yi, xi] = valid.mean()
            if coverage[yi, xi] < minimum_fraction:
                continue
            weights = np.broadcast_to(lat_weights[:, None], block.shape)
            valid_weights = np.where(valid, weights, 0)
            denominator = valid_weights.sum()
            if denominator > 0:
                result[yi, xi] = np.nansum(block * valid_weights) / denominator
    return result, coverage


def cmorph_filename(start):
    return f"CMORPH2_0.25deg-30min_{start:%Y%m%d%H%M}.RT.nc"


def cmorph_url(start):
    return f"{CMORPH_ROOT}/{start:%Y}/{start:%Y%m}/{start:%Y%m%d}/{cmorph_filename(start)}"


def fetch_cmorph_24h(valid_end, cache, target_lat, target_lon):
    valid_end = utc(valid_end)
    if valid_end.minute not in (0, 30) or valid_end.second or valid_end.microsecond:
        raise ValueError("CMORPH verification end must align to a half hour")
    valid_start = valid_end - timedelta(hours=24)
    accumulated = None
    valid_count = None
    source_lat = source_lon = None
    source_files = []
    starts = [valid_start + timedelta(minutes=30 * index) for index in range(48)]
    paths = [Path(cache) / "cmorph" / start.strftime("%Y%m%d") / cmorph_filename(start)
             for start in starts]
    def retrieve(pair):
        start, path = pair
        checked_download(cmorph_url(start), path)
        return path
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(retrieve, zip(starts, paths)))
    for start, path in zip(starts, paths):
        with xr.open_dataset(path) as dataset:
            expected_end = start + timedelta(minutes=30) - timedelta(seconds=1)
            if dataset.attrs.get("time_coverage_start") != start.strftime("%Y-%m-%dT%H:%M:%SZ"):
                raise ValueError("CMORPH start metadata changed")
            if dataset.attrs.get("time_coverage_end") != expected_end.strftime("%Y-%m-%dT%H:%M:%SZ"):
                raise ValueError("CMORPH end metadata changed")
            if dataset.attrs.get("time_coverage_duration") != "PT30M":
                raise ValueError("CMORPH duration metadata changed")
            field = dataset["cmorph"]
            if field.attrs.get("units") != "mm/hr":
                raise ValueError("CMORPH units changed")
            array = np.asarray(field.isel(time=0).values, dtype=float)
            finite = np.isfinite(array) & (array >= 0)
            if accumulated is None:
                accumulated = np.zeros_like(array, dtype=float)
                valid_count = np.zeros_like(array, dtype=np.uint8)
                source_lat = np.asarray(dataset["lat"].values, dtype=float)
                source_lon = np.asarray(dataset["lon"].values, dtype=float)
            accumulated[finite] += array[finite] * 0.5
            valid_count[finite] += 1
        source_files.append({"name": path.name, "sha256": sha256(path)})
    complete = np.where(valid_count == 48, accumulated, np.nan)
    values, coverage = area_mean_to_grid(complete, source_lat, source_lon, target_lat, target_lon)
    metadata = {
        "schema_version": 1,
        "reference_id": "noaa-cmorph2-nrt-025",
        "reference_kind": "satellite",
        "product": "NOAA CPC CMORPH2 NRT 0.25° 30-minute",
        "revision": "CMORPH2NRT",
        "valid_start": valid_start.isoformat(),
        "valid_end": valid_end.isoformat(),
        "available_at": datetime.now(timezone.utc).isoformat(),
        "variable": "rain",
        "units": "mm",
        "aggregation": "48 half-hourly mm/hr fields integrated to 24 h, then cosine-latitude area mean",
        "minimum_target_coverage": 0.9,
        "licence_reference": "https://www.cpc.ncep.noaa.gov/products/janowiak/cmorph.html",
        "source_files": source_files,
    }
    return values, coverage, metadata


def earthdata_auth(netrc_path):
    path = Path(netrc_path)
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Earthdata netrc must exist with owner-only permissions")
    credentials = netrc.netrc(path).authenticators(IMERG_HOST)
    if not credentials:
        raise ValueError("No PPS credentials found in Earthdata netrc")
    login, _, password = credentials
    return httpx.BasicAuth(login, password)


def imerg_directory(valid_end):
    slot = utc(valid_end) - timedelta(minutes=30)
    return slot, f"{IMERG_ROOT}/{slot:%Y}/{slot:%m}/"


def find_imerg_1day(valid_end, netrc_path):
    slot, directory = imerg_directory(valid_end)
    auth = earthdata_auth(netrc_path)
    with httpx.Client(timeout=60, follow_redirects=True, auth=auth) as client:
        response = client.get(directory)
        response.raise_for_status()
    pattern = re.compile(
        rf'href="(3B-HHR-E\.MS\.MRG\.3IMERG\.{slot:%Y%m%d}-S{slot:%H%M}00-E'
        rf'{(slot + timedelta(minutes=29, seconds=59)):%H%M%S}\.[0-9]{{4}}\.V07[A-Z]\.1day\.tif)"'
    )
    matches = pattern.findall(response.text)
    if len(matches) != 1:
        raise ValueError("Could not uniquely resolve the IMERG Early one-day file")
    return directory + matches[0], matches[0], auth
def fetch_imerg_24h(valid_end, cache, target_lat, target_lon, netrc_path):
    import rasterio

    valid_end = utc(valid_end)
    if valid_end.minute not in (0, 30) or valid_end.second or valid_end.microsecond:
        raise ValueError("IMERG verification end must align to a half hour")
    valid_start = valid_end - timedelta(hours=24)
    url, filename, auth = find_imerg_1day(valid_end, netrc_path)
    path = Path(cache) / "imerg-early" / valid_start.strftime("%Y%m%d") / filename
    checked_download(url, path, auth=auth, minimum_bytes=100_000)

    with rasterio.open(path) as dataset:
        tags = dataset.tags()
        description = tags.get("TIFFTAG_IMAGEDESCRIPTION", "")
        if dataset.width != 3600 or dataset.height != 1800 or dataset.crs.to_epsg() != 4326:
            raise ValueError("IMERG GIS grid metadata changed")
        if "ScaleFactor=10" not in description or "Unit=0.1(mm)" not in description:
            raise ValueError("IMERG GIS scale metadata changed")
        array = dataset.read(1).astype(float)
        array[array == 29999] = np.nan
        array /= 10.0
        transform = dataset.transform
        source_lon = transform.c + (np.arange(dataset.width) + 0.5) * transform.a
        source_lat = transform.f + (np.arange(dataset.height) + 0.5) * transform.e
    values, coverage = area_mean_to_grid(array, source_lat, source_lon, target_lat, target_lon)
    version = re.search(r"\.(V07[A-Z])\.1day\.tif$", filename)
    if not version:
        raise ValueError("IMERG filename version could not be parsed")
    metadata = {
        "schema_version": 1,
        "reference_id": "nasa-imerg-early-gis-v07",
        "reference_kind": "satellite",
        "product": "NASA GPM IMERG Early Run GIS one-day accumulation",
        "revision": version.group(1),
        "valid_start": valid_start.isoformat(),
        "valid_end": valid_end.isoformat(),
        "available_at": datetime.now(timezone.utc).isoformat(),
        "variable": "rain",
        "units": "mm",
        "aggregation": "Provider 24-hour accumulation, 0.1 mm scaling, then cosine-latitude area mean",
        "minimum_target_coverage": 0.9,
        "missing_value": 29999,
        "licence_reference": "https://gpm.nasa.gov/data/directory/imerg-early-run-pps-near-real-time-gis",
        "source_files": [{"name": filename, "sha256": sha256(path)}],
    }
    return values, coverage, metadata


def save_reference(output, values, coverage, metadata, latitude, longitude):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stem = f"{metadata['reference_id']}-{metadata['valid_end'][:13].replace(':','')}"
    values_path = output / f"{stem}.npy"
    coverage_path = output / f"{stem}-coverage.npy"
    np.save(values_path, np.asarray(values, dtype=np.float32), allow_pickle=False)
    np.save(coverage_path, np.asarray(coverage, dtype=np.float32), allow_pickle=False)
    metadata = {
        **metadata,
        "latitude": [float(value) for value in latitude],
        "longitude": [float(value) for value in longitude],
        "values_file": values_path.name,
        "values_sha256": sha256(values_path),
        "coverage_file": coverage_path.name,
        "coverage_sha256": sha256(coverage_path),
    }
    atomic_write(output / f"{stem}.json", json_bytes(metadata))
    return metadata

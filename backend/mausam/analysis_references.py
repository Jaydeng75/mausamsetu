"""Delayed ERA5 analysis references for temperature and wind shadow verification."""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import xarray as xr

from .public_data import GRIDS
from .storage import atomic_write, json_bytes

REFERENCE_ID = "era5-analysis"
ARCO_ERA5 = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = {
    "temperature": "2m_temperature",
    "u": "10m_u_component_of_wind",
    "v": "10m_v_component_of_wind",
}


def utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Reference time must be timezone-aware")
    return parsed.astimezone(timezone.utc)
def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def open_era5t():
    return xr.open_zarr(
        ARCO_ERA5, chunks=None, storage_options={"token": "anon"}, consolidated=True,
    )


def valid_stop(dataset):
    value = dataset.attrs.get("valid_time_stop_era5t")
    if not value:
        raise ValueError("ERA5T valid stop metadata missing")
    return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)


def metadata_path(folder, valid_time):
    valid_time = utc(valid_time)
    current = Path(folder) / f"era5-analysis-{valid_time:%Y%m%dT%H}.json"
    legacy = Path(folder) / f"era5t-arco-{valid_time:%Y%m%dT%H}.json"
    return current if current.exists() or not legacy.exists() else legacy


def _values_path(folder, valid_time):
    valid_time = utc(valid_time)
    return Path(folder) / f"era5-analysis-{valid_time:%Y%m%dT%H}.npz"
def save_reference(folder, valid_time, temperature, u, v, source_meta):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    valid_time = utc(valid_time)
    values_path, meta_path = _values_path(folder, valid_time), metadata_path(folder, valid_time)
    arrays = {
        "temperature": np.asarray(temperature, dtype=np.float32),
        "u": np.asarray(u, dtype=np.float32),
        "v": np.asarray(v, dtype=np.float32),
    }
    shape = (len(GRIDS["india"]["lat"]), len(GRIDS["india"]["lon"]))
    if any(array.shape != shape for array in arrays.values()):
        raise ValueError("ERA5 target grid shape changed")
    if not all(np.isfinite(array).all() for array in arrays.values()):
        raise ValueError("ERA5 contains missing target cells")
    temporary = values_path.with_suffix(".npz.part")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
    temporary.replace(values_path)
    meta = {
        "schema_version": 2, "reference_id": REFERENCE_ID, "reference_kind": "reanalysis",
        "product": source_meta["product"], "valid_time": valid_time.isoformat(),
        "available_at": datetime.now(timezone.utc).isoformat(),
        "values_file": values_path.name, "values_sha256": sha256(values_path),
        "units": {"temperature": "degC", "u": "m s**-1", "v": "m s**-1"},
        "grid": "MausamSetu India 1 degree requested points",
        "source": source_meta["source"], "transport": source_meta["transport"],
        "source_metadata": source_meta.get("details", {}),
        "limitation": (
            "ERA5/ERA5T is delayed reanalysis, not an independent station observation network. "
            "When Open-Meteo is the transport, normalized values inherit its nearest-cell serving layer."
        ),
    }
    atomic_write(meta_path, json_bytes(meta))
    return meta_path


def _wind_components(speed_kmh, direction_deg):
    speed = np.asarray(speed_kmh, dtype=float) / 3.6
    direction = np.deg2rad(np.asarray(direction_deg, dtype=float))
    return -speed * np.sin(direction), -speed * np.cos(direction)


def _open_meteo_cache_file(cache, params):
    key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]
    return cache / f"era5-{key}.json"


def _request_open_meteo(params, target):
    if target.exists():
        body = target.read_bytes()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=90, follow_redirects=True,
                          headers={"User-Agent": "MausamSetu/0.4 ERA5-reference research client"}) as client:
            last = None
            for attempt in range(3):
                try:
                    response = client.get(OPEN_METEO_ARCHIVE, params=params)
                    response.raise_for_status()
                    body = response.content
                    parsed = response.json()
                    if isinstance(parsed, dict) and parsed.get("error"):
                        raise ValueError(str(parsed.get("reason", "Open-Meteo ERA5 error")))
                    atomic_write(target, body)
                    break
                except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
                    last = error
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            else:
                raise last
    return json.loads(body), hashlib.sha256(body).hexdigest()


def _fetch_open_meteo(times, folder, batch_size=80):
    if not times:
        return []
    latitude = GRIDS["india"]["lat"].astype(float)
    longitude = GRIDS["india"]["lon"].astype(float)
    yy, xx = np.meshgrid(latitude, longitude, indexing="ij")
    flat_lat, flat_lon = yy.ravel(), xx.ravel()
    arrays = {value: {name: np.full(len(flat_lat), np.nan) for name in ["temperature", "u", "v"]}
              for value in times}
    cache = Path(folder) / "open-meteo-cache"
    hashes = []
    for start in range(0, len(flat_lat), batch_size):
        stop = min(len(flat_lat), start + batch_size)
        lats, lons = flat_lat[start:stop], flat_lon[start:stop]
        params = {
            "latitude": ",".join(f"{value:.6f}" for value in lats),
            "longitude": ",".join(f"{value:.6f}" for value in lons),
            "elevation": ",".join("nan" for _ in lats),
            "start_date": min(times).date().isoformat(),
            "end_date": max(times).date().isoformat(),
            "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
            "timezone": "GMT", "models": "era5", "cell_selection": "nearest",
        }
        rows, digest = _request_open_meteo(params, _open_meteo_cache_file(cache, params))
        rows = rows if isinstance(rows, list) else [rows]
        if len(rows) != len(lats):
            raise ValueError("Open-Meteo ERA5 batch size changed")
        hashes.append(digest)
        for offset, row in enumerate(rows):
            if abs(float(row.get("latitude", 999))-lats[offset]) > .2:
                raise ValueError("Open-Meteo ERA5 latitude moved beyond nearest-cell tolerance")
            if abs(float(row.get("longitude", 999))-lons[offset]) > .2:
                raise ValueError("Open-Meteo ERA5 longitude moved beyond nearest-cell tolerance")
            units, hourly = row.get("hourly_units", {}), row.get("hourly", {})
            if units.get("temperature_2m") != "°C" or units.get("wind_speed_10m") != "km/h":
                raise ValueError("Open-Meteo ERA5 units changed")
            if units.get("wind_direction_10m") != "°":
                raise ValueError("Open-Meteo ERA5 wind direction units changed")
            index = {stamp: i for i, stamp in enumerate(hourly.get("time", []))}
            for valid_time in times:
                key = valid_time.strftime("%Y-%m-%dT%H:%M")
                i = index.get(key)
                if i is None:
                    continue
                values = [hourly.get(name, [])[i] for name in
                          ["temperature_2m", "wind_speed_10m", "wind_direction_10m"]]
                if any(value is None for value in values):
                    continue
                u, v = _wind_components([values[1]], [values[2]])
                position = start + offset
                arrays[valid_time]["temperature"][position] = float(values[0])
                arrays[valid_time]["u"][position] = float(u[0])
                arrays[valid_time]["v"][position] = float(v[0])
    saved = []
    shape = (len(latitude), len(longitude))
    details = {
        "underlying_dataset": "ERA5", "intermediary": "Open-Meteo Archive API",
        "models_parameter": "era5", "cell_selection": "nearest",
        "elevation_parameter": "nan", "response_sha256": hashes,
    }
    for valid_time in times:
        values = arrays[valid_time]
        if not all(np.isfinite(value).all() for value in values.values()):
            continue
        saved.append(save_reference(
            folder, valid_time,
            values["temperature"].reshape(shape), values["u"].reshape(shape), values["v"].reshape(shape),
            {"product": "ECMWF ERA5 via Open-Meteo Archive", "source": OPEN_METEO_ARCHIVE,
             "transport": "open-meteo-era5", "details": details},
        ))
    return saved


def _fetch_arco(times, folder):
    dataset = open_era5t()
    stop = valid_stop(dataset)
    latitude = GRIDS["india"]["lat"].astype(float)
    longitude = GRIDS["india"]["lon"].astype(float)
    saved = []
    try:
        for valid_time in times:
            if valid_time > stop:
                continue
            timestamp = np.datetime64(valid_time.replace(tzinfo=None))
            subset = dataset[list(VARIABLES.values())].sel(
                time=timestamp, latitude=xr.DataArray(latitude, dims="latitude"),
                longitude=xr.DataArray(longitude, dims="longitude"),
            ).load()
            saved.append(save_reference(
                folder, valid_time,
                np.asarray(subset[VARIABLES["temperature"]].values, dtype=float) - 273.15,
                np.asarray(subset[VARIABLES["u"]].values, dtype=float),
                np.asarray(subset[VARIABLES["v"]].values, dtype=float),
                {"product": "ECMWF ERA5T via Google ARCO ERA5", "source": ARCO_ERA5,
                 "transport": "google-arco-zarr",
                 "details": {"valid_time_stop_era5t": dataset.attrs.get("valid_time_stop_era5t"),
                             "last_updated": dataset.attrs.get("last_updated")}},
            ))
    finally:
        dataset.close()
    return saved


def fetch_many(valid_times, folder):
    times = sorted({utc(value) for value in valid_times})
    pending = [value for value in times if not metadata_path(folder, value).exists()]
    if not pending:
        return [metadata_path(folder, value) for value in times]
    delay_hours = int(os.getenv("MAUSAM_ERA5_REFERENCE_DELAY_HOURS", "144"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=delay_hours)
    eligible = [value for value in pending if value <= cutoff]
    provider = os.getenv("MAUSAM_ERA5_REFERENCE_PROVIDER", "open-meteo").lower()
    if eligible:
        if provider == "arco":
            try:
                _fetch_arco(eligible, folder)
            except Exception:
                _fetch_open_meteo(eligible, folder)
        elif provider == "open-meteo":
            _fetch_open_meteo(eligible, folder)
        else:
            raise ValueError("MAUSAM_ERA5_REFERENCE_PROVIDER must be open-meteo or arco")
    return [metadata_path(folder, value) for value in times if metadata_path(folder, value).exists()]
def load_reference(path):
    path = Path(path)
    metadata = json.loads(path.read_text())
    if metadata.get("reference_id") not in {REFERENCE_ID, "era5t-arco-analysis"}:
        raise ValueError("Unsupported ERA5 analysis reference")
    values_path = path.parent / metadata["values_file"]
    if sha256(values_path) != metadata["values_sha256"]:
        raise ValueError("ERA5 reference checksum failed")
    with np.load(values_path, allow_pickle=False) as archive:
        values = {key: archive[key] for key in archive.files}
    return metadata, values

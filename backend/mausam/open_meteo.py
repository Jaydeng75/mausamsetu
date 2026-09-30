"""Optional Open-Meteo Single Runs connector for historical shadow backfills.

Direct NOAA/ECMWF provider files remain canonical. This connector is used only
as a supplemental fallback and always pins an explicit model identifier.
"""
import hashlib
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

from .storage import atomic_write, json_bytes

BASE = "https://single-runs-api.open-meteo.com/v1/forecast"
MODEL_IDS = {
    "IFS": "ecmwf_ifs025",
    "AIFS": "ecmwf_aifs025_single",
}
HOURLY = ["temperature_2m", "precipitation", "wind_speed_10m", "wind_direction_10m"]
LEADS = [24, 48, 72]


def utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Open-Meteo run time must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _cache_key(source, initialization, latitudes, longitudes):
    payload = json.dumps({
        "source": source, "run": utc(initialization).isoformat(),
        "latitude": [round(float(v), 6) for v in latitudes],
        "longitude": [round(float(v), 6) for v in longitudes],
        "hourly": HOURLY,
    }, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:20]


def _request_batch(source, initialization, latitudes, longitudes, cache):
    if source not in MODEL_IDS:
        raise ValueError("Open-Meteo fallback is not approved for this source")
    initialization = utc(initialization)
    if len(latitudes) != len(longitudes) or not latitudes:
        raise ValueError("Aligned Open-Meteo coordinates required")
    cache = Path(cache) / "open-meteo-single-runs"
    cache.mkdir(parents=True, exist_ok=True)
    key = _cache_key(source, initialization, latitudes, longitudes)
    target = cache / f"{source.lower()}-{initialization:%Y%m%d-%H}-{key}.json"
    params = {
        "latitude": ",".join(f"{float(v):.6f}" for v in latitudes),
        "longitude": ",".join(f"{float(v):.6f}" for v in longitudes),
        "elevation": ",".join("nan" for _ in latitudes),
        "run": initialization.strftime("%Y-%m-%dT%H:%M"),
        "hourly": ",".join(HOURLY),
        "models": MODEL_IDS[source],
        "timezone": "GMT",
        "forecast_days": 4,
    }
    if target.exists():
        body = target.read_bytes()
    else:
        with httpx.Client(timeout=90, follow_redirects=True,
                          headers={"User-Agent": "MausamSetu/0.3 research-backfill"}) as client:
            last = None
            for attempt in range(3):
                try:
                    response = client.get(BASE, params=params)
                    response.raise_for_status()
                    body = response.content
                    data = response.json()
                    if isinstance(data, dict) and data.get("error"):
                        raise ValueError(str(data.get("reason", "Open-Meteo API error")))
                    atomic_write(target, body)
                    break
                except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
                    last = error
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            else:
                raise last
    data = json.loads(body)
    rows = data if isinstance(data, list) else [data]
    if len(rows) != len(latitudes):
        raise ValueError("Open-Meteo batch size changed")
    return rows, {
        "provider": "Open-Meteo Single Runs",
        "endpoint": BASE,
        "model": MODEL_IDS[source],
        "run": initialization.isoformat(),
        "cache_file": target.name,
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "coordinates": len(rows),
        "downscaling": "disabled with elevation=nan",
        "role": "supplemental historical fallback; direct provider remains canonical",
    }


def _validate_hourly(row):
    hourly = row.get("hourly", {})
    units = row.get("hourly_units", {})
    if units.get("temperature_2m") != "°C" or units.get("precipitation") != "mm":
        raise ValueError("Open-Meteo temperature/precipitation units changed")
    if units.get("wind_speed_10m") != "km/h" or units.get("wind_direction_10m") != "°":
        raise ValueError("Open-Meteo wind units changed")
    times = hourly.get("time")
    if not isinstance(times, list) or len(times) < 73:
        raise ValueError("Open-Meteo hourly horizon is incomplete")
    return hourly


def _wind_components(speed_kmh, direction_deg):
    speed = np.asarray(speed_kmh, dtype=float) / 3.6
    direction = np.deg2rad(np.asarray(direction_deg, dtype=float))
    return -speed * np.sin(direction), -speed * np.cos(direction)


def fetch_source_cycle(source, initialization, cache, latitude, longitude, batch_size=80):
    """Return +24/+48/+72 24h rain, T2m and paired U/V on a target grid."""
    initialization = utc(initialization)
    lat_grid = np.asarray(latitude, dtype=float)
    lon_grid = np.asarray(longitude, dtype=float)
    yy, xx = np.meshgrid(lat_grid, lon_grid, indexing="ij")
    flat_lat, flat_lon = yy.ravel(), xx.ravel()
    fields = {name: np.full((len(LEADS), len(flat_lat)), np.nan, dtype=float)
              for name in ["rain", "temperature", "u", "v"]}
    provenance = []
    for start in range(0, len(flat_lat), batch_size):
        stop = min(len(flat_lat), start + batch_size)
        rows, info = _request_batch(source, initialization,
                                    flat_lat[start:stop].tolist(), flat_lon[start:stop].tolist(), cache)
        provenance.append(info)
        for offset, row in enumerate(rows):
            hourly = _validate_hourly(row)
            index = {value: i for i, value in enumerate(hourly["time"])}
            precipitation = hourly["precipitation"]
            for li, lead in enumerate(LEADS):
                valid = initialization + timedelta(hours=lead)
                key = valid.strftime("%Y-%m-%dT%H:%M")
                if key not in index:
                    raise ValueError("Open-Meteo valid time missing")
                instant = index[key]
                temp = hourly["temperature_2m"][instant]
                speed = hourly["wind_speed_10m"][instant]
                direction = hourly["wind_direction_10m"][instant]
                if any(value is None for value in [temp, speed, direction]):
                    raise ValueError("Open-Meteo instantaneous field unavailable")
                window_start = initialization + timedelta(hours=lead - 24)
                amounts = []
                for hour in range(lead - 23, lead + 1):
                    timestamp = (initialization + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M")
                    idx = index.get(timestamp)
                    if idx is None or precipitation[idx] is None:
                        raise ValueError("Open-Meteo rainfall window is incomplete")
                    amounts.append(float(precipitation[idx]))
                if min(amounts) < 0:
                    raise ValueError("Open-Meteo rainfall contains negative values")
                u, v = _wind_components([speed], [direction])
                column = start + offset
                fields["rain"][li, column] = sum(amounts)
                fields["temperature"][li, column] = float(temp)
                fields["u"][li, column] = float(u[0])
                fields["v"][li, column] = float(v[0])
    shape = (len(lat_grid), len(lon_grid))
    output = {name: [array[i].reshape(shape) for i in range(len(LEADS))]
              for name, array in fields.items()}
    if not all(np.isfinite(np.stack(values)).all() for values in output.values()):
        raise ValueError("Open-Meteo fallback produced missing grid values")
    return output, provenance


def precipitation_window_grid(source, initialization, start_hour, end_hour, cache,
                              latitude, longitude, batch_size=80):
    """Sum exact preceding-hour precipitation over (start_hour, end_hour]."""
    if source not in MODEL_IDS:
        raise ValueError("Open-Meteo fallback is not approved for this source")
    initialization = utc(initialization)
    if not 0 <= start_hour < end_hour <= 96:
        raise ValueError("Invalid Open-Meteo precipitation window")
    lat_grid, lon_grid = np.asarray(latitude, dtype=float), np.asarray(longitude, dtype=float)
    yy, xx = np.meshgrid(lat_grid, lon_grid, indexing="ij")
    flat_lat, flat_lon = yy.ravel(), xx.ravel()
    result = np.full(len(flat_lat), np.nan, dtype=float)
    provenance = []
    for start in range(0, len(flat_lat), batch_size):
        stop = min(len(flat_lat), start + batch_size)
        rows, info = _request_batch(source, initialization,
                                    flat_lat[start:stop].tolist(), flat_lon[start:stop].tolist(), cache)
        provenance.append(info)
        for offset, row in enumerate(rows):
            hourly = _validate_hourly(row)
            index = {value: i for i, value in enumerate(hourly["time"])}
            amounts = []
            for hour in range(start_hour + 1, end_hour + 1):
                key = (initialization + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M")
                idx = index.get(key)
                if idx is None or hourly["precipitation"][idx] is None:
                    raise ValueError("Open-Meteo exact rainfall window is incomplete")
                amounts.append(float(hourly["precipitation"][idx]))
            if min(amounts) < 0:
                raise ValueError("Open-Meteo rainfall contains negative values")
            result[start + offset] = sum(amounts)
    if not np.isfinite(result).all():
        raise ValueError("Open-Meteo exact-window grid contains missing values")
    return result.reshape(len(lat_grid), len(lon_grid)), provenance


def precipitation_window_points(source, initialization, start_hour, end_hour, cache,
                                latitudes, longitudes, batch_size=40):
    """Exact precipitation totals for aligned coordinate pairs, not a Cartesian grid."""
    if source not in MODEL_IDS:
        raise ValueError("Open-Meteo fallback is not approved for this source")
    initialization = utc(initialization)
    latitudes = np.asarray(latitudes, dtype=float)
    longitudes = np.asarray(longitudes, dtype=float)
    if latitudes.shape != longitudes.shape or latitudes.ndim != 1 or not len(latitudes):
        raise ValueError("Aligned Open-Meteo point coordinates required")
    result = np.full(len(latitudes), np.nan, dtype=float)
    provenance = []
    for start in range(0, len(latitudes), batch_size):
        stop = min(len(latitudes), start + batch_size)
        rows, info = _request_batch(source, initialization,
                                    latitudes[start:stop].tolist(), longitudes[start:stop].tolist(), cache)
        provenance.append(info)
        for offset, row in enumerate(rows):
            hourly = _validate_hourly(row)
            index = {value: i for i, value in enumerate(hourly["time"])}
            amounts = []
            for hour in range(start_hour + 1, end_hour + 1):
                key = (initialization + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M")
                idx = index.get(key)
                if idx is None or hourly["precipitation"][idx] is None:
                    raise ValueError("Open-Meteo exact rainfall window is incomplete")
                amounts.append(float(hourly["precipitation"][idx]))
            if min(amounts) < 0:
                raise ValueError("Open-Meteo rainfall contains negative values")
            result[start + offset] = sum(amounts)
    if not np.isfinite(result).all():
        raise ValueError("Open-Meteo exact-window points contain missing values")
    return result, provenance

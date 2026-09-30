"""Efficient historical/live forecast extraction for multi-variable shadow validation.

Downloads only the rainfall/2m-temperature/10m-vector messages needed for the
00 UTC +24/+48/+72 h shadow experiments. Historical NOAA data use public cloud
archives with GRIB index range requests rather than multi-hundred-MB full files.
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

from .public_data import GRIDS, decode, validate_run
from .storage import atomic_write, file_lock, json_bytes

SOURCES = ["GFS", "GEFS", "IFS", "AIFS"]
LEADS = [24, 48, 72]
ECMWF_ACCUMULATION_PACKING_TOLERANCE_MM = 0.05


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _idx_entries(text):
    entries = []
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        try:
            entries.append((int(parts[1]), parts[2]))
        except ValueError:
            continue
    if not entries or any(entries[i][0] >= entries[i+1][0] for i in range(len(entries)-1)):
        raise ValueError("Invalid NOAA GRIB index")
    return entries


def _download_ranges(url, target, choose):
    target = Path(target)
    sidecar = target.with_suffix(target.suffix + ".source.json")
    if target.exists() and target.stat().st_size > 100 and target.read_bytes()[:4] == b"GRIB":
        return json.loads(sidecar.read_text()) if sidecar.exists() else {"source": "cached", "url": url}
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        index_response = client.get(url + ".idx")
        index_response.raise_for_status()
        entries = _idx_entries(index_response.text)
        selected = choose(entries)
        if not selected:
            raise ValueError("No requested GRIB messages found in provider index")
        positions = {start: i for i, (start, _) in enumerate(entries)}
        chunks = []
        for start, description in selected:
            i = positions[start]
            if i + 1 < len(entries):
                end = entries[i+1][0] - 1
            else:
                head = client.head(url)
                head.raise_for_status()
                end = int(head.headers["content-length"]) - 1
            response = client.get(url, headers={"Range": f"bytes={start}-{end}"})
            response.raise_for_status()
            body = response.content
            if not body.startswith(b"GRIB") or not body.endswith(b"7777"):
                raise ValueError("NOAA range did not return one complete GRIB message")
            chunks.append(body)
    payload = b"".join(chunks)
    atomic_write(target, payload)
    metadata = {
        "source": "noaa_public_cloud_range",
        "url": url,
        "idx_sha256": hashlib.sha256(index_response.content).hexdigest(),
        "messages": [description for _, description in selected],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write(sidecar, json_bytes(metadata))
    return metadata


def _gfs_choose(entries):
    selected = []
    for token in [":TMP:2 m above ground:", ":UGRD:10 m above ground:", ":VGRD:10 m above ground:"]:
        matches = [entry for entry in entries if token in ":" + entry[1]]
        if len(matches) != 1:
            raise ValueError("GFS instantaneous-field index schema changed")
        selected.append(matches[0])
    precip = [entry for entry in entries if ":APCP:surface:" in ":" + entry[1]]
    cumulative = [entry for entry in precip if entry[1].split(":")[-2].startswith("0-")]
    if cumulative:
        selected.append(cumulative[-1])
    elif precip:
        selected.append(precip[-1])
    else:
        raise ValueError("GFS precipitation index entry missing")
    return sorted(selected)


def _gefs_choose(entries, include_instant):
    precip = [entry for entry in entries if ":APCP:surface:" in ":" + entry[1]]
    if len(precip) != 1:
        raise ValueError("GEFS precipitation index schema changed")
    selected = [precip[0]]
    if include_instant:
        for token in [":TMP:2 m above ground:", ":UGRD:10 m above ground:", ":VGRD:10 m above ground:"]:
            matches = [entry for entry in entries if token in ":" + entry[1]]
            if len(matches) != 1:
                raise ValueError("GEFS instantaneous-field index schema changed")
            selected.append(matches[0])
    return sorted(selected)


def _field_arrays(fields):
    t, u, v = fields["2t"], fields["10u"], fields["10v"]
    if t["units"] != "K" or u["units"] not in ("m s**-1", "m s-1") or v["units"] != u["units"]:
        raise ValueError("Unexpected source temperature/wind units")
    return t["array"] - 273.15, u["array"], v["array"]


def gfs(date, cycle, cache, latitude, longitude):
    raw = {}
    provenance = []
    for lead in LEADS:
        base = (
            f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{date}/{cycle:02}/atmos/"
            f"gfs.t{cycle:02}z.pgrb2.0p25.f{lead:03}"
        )
        path = Path(cache) / f"shadow-gfs-{date}-{cycle:02}-{lead:03}.grib2"
        source = _download_ranges(base, path, _gfs_choose)
        fields = decode(path, latitude, longitude)
        validate_run(fields, date, cycle, lead)
        raw[lead] = fields
        provenance.append({"lead": lead, "sha256": sha256(path), **source})
    output = {"rain": [], "temperature": [], "u": [], "v": []}
    previous = 0
    for lead in LEADS:
        precip = raw[lead]["tp"]
        if precip["units"] not in ("kg m**-2", "kg m-2") or precip["start"] != 0:
            raise ValueError("GFS historical precipitation is not cumulative from initialization")
        current = precip["array"]
        rain = current if lead == 24 else current - previous
        if np.nanmin(rain) < -0.01:
            raise ValueError("GFS historical cumulative precipitation reset")
        t, u, v = _field_arrays(raw[lead])
        output["rain"].append(np.maximum(rain, 0))
        output["temperature"].append(t); output["u"].append(u); output["v"].append(v)
        previous = current
    return output, provenance


def gefs(date, cycle, cache, latitude, longitude):
    raw = {}
    provenance = []
    for step in range(6, max(LEADS) + 1, 6):
        base = (
            f"https://noaa-gefs-pds.s3.amazonaws.com/gefs.{date}/{cycle:02}/atmos/pgrb2sp25/"
            f"geavg.t{cycle:02}z.pgrb2s.0p25.f{step:03}"
        )
        path = Path(cache) / f"shadow-gefs-{date}-{cycle:02}-{step:03}.grib2"
        source = _download_ranges(base, path, lambda entries, inc=step in LEADS: _gefs_choose(entries, inc))
        fields = decode(path, latitude, longitude)
        validate_run(fields, date, cycle, step)
        raw[step] = fields
        provenance.append({"lead": step, "sha256": sha256(path), **source})
    output = {"rain": [], "temperature": [], "u": [], "v": []}
    for lead in LEADS:
        rain = np.zeros((len(latitude), len(longitude)), dtype=float)
        for step in range(lead - 18, lead + 1, 6):
            precip = raw[step]["tp"]
            if precip["units"] not in ("kg m**-2", "kg m-2") or precip["start"] != step - 6:
                raise ValueError("GEFS historical rainfall is not a six-hour accumulation")
            if np.nanmin(precip["array"]) < -0.01:
                raise ValueError("Negative GEFS historical ensemble-mean rainfall")
            rain += np.maximum(precip["array"], 0)
        t, u, v = _field_arrays(raw[lead])
        output["rain"].append(rain)
        output["temperature"].append(t); output["u"].append(u); output["v"].append(v)
    return output, provenance


def _ecmwf_retrieve(path, date, cycle, lead, model):
    from ecmwf.opendata import Client
    path = Path(path)
    sidecar = path.with_suffix(path.suffix + ".source.json")
    if path.exists():
        return json.loads(sidecar.read_text()) if sidecar.exists() else {"source": "cached"}
    lock = path.with_suffix(path.suffix + ".lock")
    with file_lock(lock):
        if path.exists():
            return json.loads(sidecar.read_text()) if sidecar.exists() else {"source": "cached"}
        last = None
        for source in ["google", "ecmwf"]:
            temporary = path.with_suffix(".part")
            temporary.unlink(missing_ok=True)
            try:
                client = Client(source=source, model=model, resol="0p25", maximum_retries=3, retry_after=10)
                client.retrieve(
                    date=int(date), time=cycle, step=lead, type="fc", stream="oper",
                    param=["tp", "2t", "10u", "10v"], target=str(temporary)
                )
                if not temporary.exists() or temporary.stat().st_size < 1000:
                    raise ValueError("ECMWF shadow retrieval produced no usable GRIB")
                temporary.replace(path)
                metadata = {
                    "source": source, "model": model, "date": date, "cycle": cycle,
                    "lead": lead, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
                atomic_write(sidecar, json_bytes(metadata))
                return metadata
            except Exception as error:
                last = error
                temporary.unlink(missing_ok=True)
                time.sleep(1)
        if last:
            raise last
        raise RuntimeError("No ECMWF shadow source configured")


def ecmwf(date, cycle, cache, latitude, longitude, model):
    raw = {}
    provenance = []
    slug = "aifs" if model == "aifs-single" else "ifs"
    for lead in LEADS:
        path = Path(cache) / f"shadow-{slug}-{date}-{cycle:02}-{lead:03}.grib2"
        source = _ecmwf_retrieve(path, date, cycle, lead, model)
        fields = decode(path, latitude, longitude)
        validate_run(fields, date, cycle, lead)
        raw[lead] = fields
        provenance.append({"lead": lead, "sha256": sha256(path), **source})
    output = {"rain": [], "temperature": [], "u": [], "v": []}
    previous = 0
    previous_units = None
    for lead in LEADS:
        precip = raw[lead]["tp"]
        if precip["start"] != 0 or precip["units"] not in ("m", "kg m**-2", "kg m-2"):
            raise ValueError("ECMWF shadow precipitation is not cumulative from initialization")
        current = precip["array"]
        scale = 1000 if precip["units"] == "m" else 1
        if previous_units is not None and previous_units != precip["units"]:
            raise ValueError("ECMWF precipitation units changed within one initialization")
        rain = current * scale if lead == 24 else (current - previous) * scale
        minimum=float(np.nanmin(rain))
        if minimum < -ECMWF_ACCUMULATION_PACKING_TOLERANCE_MM:
            raise ValueError("ECMWF cumulative precipitation reset")
        if minimum < 0:
            provenance.append({"lead":lead,"quality_flag":"sub_tolerance_negative_accumulation_difference_clamped",
                               "minimum_mm":minimum,
                               "tolerance_mm":ECMWF_ACCUMULATION_PACKING_TOLERANCE_MM})
        t, u, v = _field_arrays(raw[lead])
        output["rain"].append(np.maximum(rain, 0))
        output["temperature"].append(t); output["u"].append(u); output["v"].append(v)
        previous, previous_units = current, precip["units"]
    return output, provenance


def fetch_cycle(initialization, cache):
    initialization = (
        initialization if isinstance(initialization, datetime)
        else datetime.fromisoformat(str(initialization).replace("Z", "+00:00"))
    )
    if initialization.tzinfo is None:
        raise ValueError("Initialization must be timezone-aware")
    initialization = initialization.astimezone(timezone.utc)
    if initialization.hour != 0 or initialization.minute or initialization.second:
        raise ValueError("Multi-shadow backfill currently uses 00 UTC daily cycles only")
    date, cycle = initialization.strftime("%Y%m%d"), initialization.hour
    grid = GRIDS["india"]
    latitude, longitude = grid["lat"], grid["lon"]
    adapters = {
        "GFS": lambda: gfs(date, cycle, cache, latitude, longitude),
        "GEFS": lambda: gefs(date, cycle, cache, latitude, longitude),
        "IFS": lambda: ecmwf(date, cycle, cache, latitude, longitude, "ifs"),
        "AIFS": lambda: ecmwf(date, cycle, cache, latitude, longitude, "aifs-single"),
    }
    fields = {
        name: np.full((len(LEADS), len(SOURCES), len(latitude), len(longitude)), np.nan, dtype=np.float32)
        for name in ["rain", "temperature", "u", "v"]
    }
    provenance = {}
    for source_index, source in enumerate(SOURCES):
        try:
            values, source_provenance = adapters[source]()
        except Exception as direct_error:
            if source not in {"IFS","AIFS"}:
                raise
            from .open_meteo import fetch_source_cycle
            values, source_provenance = fetch_source_cycle(
                source, initialization, cache, latitude, longitude
            )
            source_provenance = [{
                "fallback": "Open-Meteo Single Runs",
                "direct_error_type": type(direct_error).__name__,
                "direct_provider_remains_canonical": True,
            }, *source_provenance]
        provenance[source] = source_provenance
        for field in fields:
            array = np.stack(values[field]).astype(np.float32)
            if array.shape != fields[field][:, source_index].shape or not np.isfinite(array).all():
                raise ValueError(f"Invalid {source} {field} shadow field")
            fields[field][:, source_index] = array
    return {
        "schema_version": 1,
        "initialization": initialization.isoformat(),
        "source_ids": SOURCES,
        "leads": LEADS,
        "latitude": latitude.astype(float).tolist(),
        "longitude": longitude.astype(float).tolist(),
        "fields": fields,
        "provenance": provenance,
    }


def save_cycle(cycle, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    initialization = datetime.fromisoformat(cycle["initialization"])
    stem = f"multi-{initialization:%Y%m%d-%H}"
    values_path = output / f"{stem}.npz"
    metadata_path = output / f"{stem}.json"
    if metadata_path.exists() and values_path.exists():
        metadata = json.loads(metadata_path.read_text())
        if sha256(values_path) != metadata.get("values_sha256"):
            raise ValueError("Existing multi-shadow archive checksum failed")
        return metadata
    temporary = values_path.with_suffix(".npz.part")
    with temporary.open("wb") as stream:
        np.savez_compressed(
            stream,
            leads=np.asarray(cycle["leads"], dtype=np.int16),
            latitude=np.asarray(cycle["latitude"], dtype=np.float32),
            longitude=np.asarray(cycle["longitude"], dtype=np.float32),
            **{name: np.asarray(values, dtype=np.float32) for name, values in cycle["fields"].items()},
        )
        stream.flush()
    temporary.replace(values_path)
    metadata = {
        "schema_version": 1,
        "initialization": cycle["initialization"],
        "source_ids": cycle["source_ids"],
        "values_file": values_path.name,
        "values_sha256": sha256(values_path),
        "provenance": cycle["provenance"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write(metadata_path, json_bytes(metadata))
    return metadata

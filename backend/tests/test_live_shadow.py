import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from mausam.live_shadow import archive_forecast, matched_cases, shadow_product, train_shadow


SOURCES = ["GFS", "GEFS", "IFS", "AIFS"]


def write_reference(folder, reference_id, valid_end, values):
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{reference_id}-{valid_end.isoformat()[:13].replace(':','')}"
    values_path = folder / f"{stem}.npy"
    coverage_path = folder / f"{stem}-coverage.npy"
    np.save(values_path, values.astype(np.float32), allow_pickle=False)
    np.save(coverage_path, np.ones_like(values, dtype=np.float32), allow_pickle=False)
    product = "CMORPH fixture" if reference_id.startswith("noaa") else "IMERG fixture"
    metadata = {
        "reference_id": reference_id, "reference_kind": "satellite", "product": product,
        "revision": "fixture-v1", "valid_start": (valid_end-timedelta(hours=24)).isoformat(),
        "valid_end": valid_end.isoformat(), "available_at": (valid_end+timedelta(hours=4)).isoformat(),
        "variable": "rain", "units": "mm", "minimum_target_coverage": 0.9,
        "values_file": values_path.name, "coverage_file": coverage_path.name,
        "values_sha256": hashlib.sha256(values_path.read_bytes()).hexdigest(),
        "coverage_sha256": hashlib.sha256(coverage_path.read_bytes()).hexdigest(),
    }
    (folder / f"{stem}.json").write_text(json.dumps(metadata))


def make_product(folder, index):
    init = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    latitude = [12.0, 11.0, 10.0, 9.0]
    longitude = [78.0, 79.0, 80.0, 81.0]
    yy, xx = np.meshgrid(latitude, longitude, indexing="ij")
    truth = 15 + (yy-9)*3 + (xx-78)*2 + index
    north = yy >= 11
    forecasts = {
        "GFS": truth + np.where(north, 0.5, 7.0),
        "GEFS": truth + 3.0,
        "IFS": truth + np.where(north, 6.0, 0.4),
        "AIFS": truth + 2.0,
    }
    sources = {}
    for name in SOURCES:
        source = forecasts[name].ravel().round(3).tolist()
        sources[name] = {"24": {"rain": source, "temperature": source,
            "wind": source, "pressure": source, "u": source, "v": source}}
    product = {
        "schema_version": 1, "data_kind": "forecast", "coverage": "india",
        "run_id": f"public-fixture-{index:02}", "initialization": init.isoformat(),
        "retrieved_at": (init+timedelta(hours=8)).isoformat(), "leads": [24],
        "latitude": latitude, "longitude": longitude, "sources": sources,
        "source_status": {name: "loaded" for name in SOURCES},
        "source_roles": {"GFS":"deterministic","GEFS":"ensemble_mean","IFS":"deterministic","AIFS":"deterministic"},
        "calibrated": False, "grid_method": "fixture", "attribution": "fixture",
    }
    path = folder / f"public-fixture-{index:02}.json"
    path.write_text(json.dumps(product))
    return path, init, truth


def build_fixture(tmp_path, count=6):
    products = tmp_path / "products"
    archive = tmp_path / "archive"
    refs = tmp_path / "refs"
    products.mkdir()
    for index in range(count):
        path, init, truth = make_product(products, index)
        archive_forecast(path, archive)
        end = init + timedelta(hours=24)
        write_reference(refs, "noaa-cmorph2-nrt-025", end, truth)
        write_reference(refs, "nasa-imerg-early-gis-v07", end, truth + 0.25)
    return archive, refs
def test_shadow_waits_for_independent_event_blocks(tmp_path):
    archive, refs = build_fixture(tmp_path, 1)
    report = train_shadow(archive, refs, tmp_path/"model")
    assert report["state"] == "collecting"
    assert report["event_blocks"] == 1
    assert report["acceptance_passed"] is False
    assert not (tmp_path/"model"/"candidate.json").exists()


def test_shadow_candidate_is_chronological_and_not_production_accepted(tmp_path):
    archive, refs = build_fixture(tmp_path, 6)
    blocks = matched_cases(archive, refs, "noaa-cmorph2-nrt-025")
    assert len({block["event_id"] for block in blocks}) == 6
    report = train_shadow(archive, refs, tmp_path/"model", prospective_start="2026-01-06T00:00:00Z")
    assert report["state"] == "shadow_candidate"
    assert report["bootstrap_event_blocks"] == 5
    assert report["prospective_event_blocks"] == 1
    assert report["acceptance_requirements"]["minimum_prospective_event_blocks"] == 10
    assert report["train_event_blocks"] == 3
    assert report["selection_event_blocks"] == 1
    assert report["test_event_blocks"] == 2
    assert report["acceptance_passed"] is False
    assert report["evidence_sufficient_for_acceptance"] is False
    assert report["cross_reference"]["reference_id"] == "nasa-imerg-early-gis-v07"
    assert report["cross_reference"]["test_event_blocks"] == 2
    candidate = json.loads((tmp_path/"model"/"candidate.json").read_text())
    assert candidate["input_kind"] == "source_point_mixture"
    assert candidate["source_ids"] == SOURCES
    assert candidate["evaluation"]["test_events"] == ["2026-01-05T00:00:00+00:00", "2026-01-06T00:00:00+00:00"]


def test_shadow_backfill_schedule_is_bounded_and_utc_aligned():
    from mausam.shadow_backfill import schedule
    rows=schedule("2026-09-24T00:00:00Z",4)
    assert [row.hour for row in rows]==[0,0,0,0]
    assert [(rows[i+1]-rows[i]).total_seconds() for i in range(3)]==[86400,86400,86400]
    with pytest.raises(ValueError):schedule("2026-09-24T01:00:00Z",4)
    with pytest.raises(ValueError):schedule("2026-09-24T00:00:00Z",17)


def test_shadow_inference_rejects_untrained_cycle(tmp_path):
    archive,refs=build_fixture(tmp_path,6)
    train_shadow(archive,refs,tmp_path/"model",prospective_start="2026-01-06T00:00:00Z")
    source=tmp_path/"products"/"public-fixture-05.json"
    product=json.loads(source.read_text())
    product["initialization"]="2026-01-06T12:00:00+00:00"
    twelve=tmp_path/"twelve.json";twelve.write_text(json.dumps(product))
    with pytest.raises(ValueError,match="untrained initialization cycle"):
        shadow_product(twelve,tmp_path/"model"/"candidate.json",tmp_path/"shadow-12.json")

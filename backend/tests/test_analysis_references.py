from datetime import datetime, timezone
import json

import numpy as np

import mausam.analysis_references as ar


def _fake_rows(params, target):
    lats=[float(v) for v in params["latitude"].split(",")]
    lons=[float(v) for v in params["longitude"].split(",")]
    times=["2026-01-01T00:00","2026-01-02T00:00"]
    rows=[]
    for lat,lon in zip(lats,lons):
        rows.append({
            "latitude":lat,"longitude":lon,
            "hourly_units":{"temperature_2m":"°C","wind_speed_10m":"km/h","wind_direction_10m":"°"},
            "hourly":{"time":times,"temperature_2m":[20.,21.],
                      "wind_speed_10m":[36.,18.],"wind_direction_10m":[90.,180.]},
        })
    return rows,"a"*64


def test_open_meteo_era5_batch_is_normalized_with_provenance(monkeypatch,tmp_path):
    monkeypatch.setitem(ar.GRIDS["india"],"lat",np.array([13.,12.]))
    monkeypatch.setitem(ar.GRIDS["india"],"lon",np.array([79.,80.]))
    monkeypatch.setenv("MAUSAM_ERA5_REFERENCE_PROVIDER","open-meteo")
    monkeypatch.setattr(ar,"_request_open_meteo",_fake_rows)
    times=[datetime(2026,1,1,tzinfo=timezone.utc),datetime(2026,1,2,tzinfo=timezone.utc)]
    paths=ar.fetch_many(times,tmp_path)
    assert len(paths)==2
    meta,values=ar.load_reference(paths[0])
    assert meta["reference_id"]=="era5-analysis"
    assert meta["transport"]=="open-meteo-era5"
    assert meta["source_metadata"]["underlying_dataset"]=="ERA5"
    assert values["temperature"].shape==(2,2)
    assert np.allclose(values["temperature"],20)
    assert np.allclose(values["u"],-10,atol=1e-6)
    assert np.allclose(values["v"],0,atol=1e-6)


def test_reference_delay_withholds_future_analysis(monkeypatch,tmp_path):
    called=[]
    monkeypatch.setenv("MAUSAM_ERA5_REFERENCE_PROVIDER","open-meteo")
    monkeypatch.setenv("MAUSAM_ERA5_REFERENCE_DELAY_HOURS","144")
    monkeypatch.setattr(ar,"_fetch_open_meteo",lambda times,folder:called.extend(times))
    result=ar.fetch_many([datetime(2099,1,1,tzinfo=timezone.utc)],tmp_path)
    assert result==[]
    assert called==[]

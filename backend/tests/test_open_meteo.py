from datetime import datetime, timezone

import numpy as np
import pytest

import mausam.open_meteo as om


def row(lat, lon, missing=None):
    times=[f"2026-09-{26 + (h//24):02}T{h%24:02}:00" for h in range(96)]
    precipitation=[None if h==0 else 1.0 for h in range(96)]
    if missing is not None:
        precipitation[missing]=None
    return {
        "latitude":lat,"longitude":lon,
        "hourly_units":{"time":"iso8601","temperature_2m":"°C","precipitation":"mm",
                        "wind_speed_10m":"km/h","wind_direction_10m":"°"},
        "hourly":{"time":times,"temperature_2m":[20.0+h/100 for h in range(96)],
                  "precipitation":precipitation,
                  "wind_speed_10m":[36.0]*96,"wind_direction_10m":[90.0]*96},
    }


def test_open_meteo_exact_models_are_pinned():
    assert om.MODEL_IDS=={
        "IFS":"ecmwf_ifs025",
        "AIFS":"ecmwf_aifs025_single",
    }
    assert "GFS" not in om.MODEL_IDS and "GEFS" not in om.MODEL_IDS


def test_open_meteo_cycle_builds_24h_windows_and_uv(monkeypatch,tmp_path):
    def fake(source,initialization,latitudes,longitudes,cache):
        return [row(a,b) for a,b in zip(latitudes,longitudes)],[{"provider":"fixture"}]
    monkeypatch.setattr(om,"_request_batch",fake)
    out,prov=om.fetch_source_cycle("AIFS",datetime(2026,9,26,tzinfo=timezone.utc),tmp_path,
                                   np.array([13.,12.]),np.array([79.,80.]),batch_size=3)
    assert len(out["rain"])==3
    assert np.allclose(out["rain"][0],24)
    assert np.allclose(out["rain"][1],24)
    assert np.allclose(out["rain"][2],24)
    assert np.allclose(out["u"][0],-10,atol=1e-6)
    assert np.allclose(out["v"][0],0,atol=1e-6)
    assert prov


def test_open_meteo_exact_window_rejects_missing_hour(monkeypatch,tmp_path):
    def fake(source,initialization,latitudes,longitudes,cache):
        return [row(a,b,missing=4) for a,b in zip(latitudes,longitudes)],[{"provider":"fixture"}]
    monkeypatch.setattr(om,"_request_batch",fake)
    with pytest.raises(ValueError,match="window is incomplete"):
        om.precipitation_window_grid("AIFS",datetime(2026,9,26,tzinfo=timezone.utc),
                                     3,27,tmp_path,[13.],[80.])


def test_open_meteo_gefs_is_deliberately_unsupported(tmp_path):
    with pytest.raises(ValueError,match="not approved"):
        om.precipitation_window_grid("GEFS",datetime(2026,9,26,tzinfo=timezone.utc),
                                     3,27,tmp_path,[13.],[80.])

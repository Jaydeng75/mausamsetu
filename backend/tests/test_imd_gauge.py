from datetime import datetime,timezone
import json

import numpy as np
import pytest

from mausam.imd_gauge import GRID_SHAPE, _precip_for_step, _sample_imd_grid, _sum_window, fetch_imd_daily


def test_cached_imd_binary_decodes_little_endian_and_samples_exact_grid(tmp_path):
    cache=tmp_path/"cache";folder=cache/"imd-gauge";folder.mkdir(parents=True)
    valid=datetime(2026,9,26,3,tzinfo=timezone.utc)
    raw=np.full(GRID_SHAPE,-999,dtype="<f4")
    raw[26,54]=12.5  # 13N, 80E
    (folder/"rain_ind0.25_20260926.grd").write_bytes(raw.tobytes())
    values,meta=fetch_imd_daily(valid,cache,np.array([13.,5.]),np.array([80.,65.]))
    assert values.shape==(2,2)
    assert values[0,0]==pytest.approx(12.5)
    assert np.isnan(values[1,1])
    assert meta["valid_start"]=="2026-09-25T03:00:00+00:00"
    assert meta["valid_end"]=="2026-09-26T03:00:00+00:00"
    assert meta["reference_kind"]=="gauge_gridded_analysis"


def test_imd_window_sum_requires_exact_contiguous_coverage():
    arrays=[(3,6,np.ones((2,2))),(6,12,np.ones((2,2))*2),(12,18,np.ones((2,2))*3),
            (18,24,np.ones((2,2))*4),(24,27,np.ones((2,2))*5)]
    total=_sum_window(arrays,3,27)
    assert np.allclose(total,15)
    with pytest.raises(ValueError,match="Gap"):
        _sum_window([arrays[0],arrays[2],arrays[3],arrays[4]],3,27)


def test_imd_reference_rejects_non_03utc_window(tmp_path):
    with pytest.raises(ValueError,match="03:00 UTC"):
        fetch_imd_daily(datetime(2026,9,26,0,tzinfo=timezone.utc),tmp_path)


def test_exact_sampling_does_not_interpolate_outside_imd_grid():
    raw=np.zeros(GRID_SHAPE)
    sampled=_sample_imd_grid(raw,np.array([38.,5.]),np.array([100.,65.]))
    assert sampled[0,0]==0
    assert np.isnan(sampled[1,1])


def test_gfs_precip_selector_understands_day_formatted_cumulative_windows():
    entries=[
        (100, "d=2026092600:APCP:surface:18-24 hour acc fcst:"),
        (200, "d=2026092600:APCP:surface:0-1 day acc fcst:"),
    ]
    selected=_precip_for_step(entries,"GFS",24)
    assert selected==[entries[1]]


def test_gefs_precip_selector_keeps_shortest_interval():
    entries=[
        (100, "d=2026092600:APCP:surface:18-24 hour acc fcst:ens mean"),
        (200, "d=2026092600:APCP:surface:0-24 hour acc fcst:ens mean"),
    ]
    selected=_precip_for_step(entries,"GEFS",24)
    assert selected==[entries[0]]

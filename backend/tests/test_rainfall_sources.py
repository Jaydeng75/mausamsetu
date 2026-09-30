import json
import numpy as np
import pytest
import xarray as xr

from mausam.imd_gridded import inventory
from mausam.rainfall_benchmark import _event_metrics

def test_imd_inventory_preserves_real_schema_without_guessing_window(tmp_path):
    path=tmp_path/'ind2020_rfp25.nc'
    ds=xr.Dataset(
      {'RAINFALL':(('TIME','LATITUDE','LONGITUDE'),np.ones((2,2,2),dtype=np.float32))},
      coords={'TIME':np.array(['2020-01-01','2020-01-02'],dtype='datetime64[D]'),
              'LATITUDE':[10.0,10.25],'LONGITUDE':[80.0,80.25]})
    ds['RAINFALL'].attrs['units']='mm';ds.to_netcdf(path)
    meta=inventory(path,2020)
    assert meta['variable']=='RAINFALL' and meta['units']=='mm'
    assert meta['shape']==[2,2,2] and meta['time_bounds_present'] is False
    assert meta['verification_status']=='staged_not_collocated'
    saved=json.loads(path.with_suffix('.manifest.json').read_text())
    assert saved['sha256']==meta['sha256']

def test_imd_inventory_rejects_unknown_units(tmp_path):
    path=tmp_path/'bad.nc'
    ds=xr.Dataset({'RAINFALL':(('TIME','LATITUDE','LONGITUDE'),np.ones((1,1,1)))},
      coords={'TIME':np.array(['2020-01-01'],dtype='datetime64[D]'),'LATITUDE':[10.0],'LONGITUDE':[80.0]})
    ds['RAINFALL'].attrs['units']='mystery';ds.to_netcdf(path)
    with pytest.raises(ValueError,match='units'):inventory(path,2020)

def test_rainfall_event_metrics_report_detection_and_false_alarm():
    samples=np.array([
      [[70.,80.,90.],[10.,20.,30.]],
      [[5.,10.,15.],[70.,75.,80.]],
    ])
    weights=np.array([[.8,.2],[.2,.8]])
    actual=np.array([75.,5.]);mass=np.ones(2)
    metric=_event_metrics(samples,weights,actual,mass,64.5)
    assert metric['events']==1 and 0<=metric['brier']<=1
    assert metric['pod']==1.0
    assert metric['far']==0.5

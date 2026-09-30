"""MOSDAC scientific unit checks; no network or account required."""
import importlib.util
from pathlib import Path
from datetime import datetime, timezone
import h5py
import numpy as np
import pytest

spec = importlib.util.spec_from_file_location('mosdac', Path(__file__).parents[1] / 'mausam/mosdac.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_fill_mask_precedes_scale(tmp_path):
    with h5py.File(tmp_path/'packed.h5', 'w') as f:
        d = f.create_dataset('rain', data=[-999, 0, 10, 101])
        d.attrs.update({'_FillValue': -999, 'scale_factor': .1, 'add_offset': 1, 'valid_range': [0,100]})
        np.testing.assert_allclose(m.physical(d), [np.nan,1,2,np.nan], equal_nan=True)


def product(tmp_path):
    p = tmp_path/'3SIMG_28SEP2026_0930_L2G_IMR_V01R00.h5'
    with h5py.File(p, 'w') as f:
        f.attrs.update({'Satellite_Name':'INSAT-3DS', 'Processing_Level':'L2G',
            'HDF_Product_File_Name':p.name, 'Acquisition_Start_Time':'28-SEP-2026T09:30:26.622',
            'Acquisition_End_Time':'28-SEP-2026T09:57:20.326'})
        for name, data, unit in [('latitude', np.arange(6,39), 'degrees_north'), ('longitude',np.arange(68,99),'degrees_east'), ('IMR',np.full((1,33,31),2.),'mm/hr')]:
            d=f.create_dataset(name,data=data);d.attrs['units']=unit
    return p, {'identifier':p.name,'dcDate':'2026-09-28T09:30:00Z/2026-09-28T10:00:00Z'}


def test_scan_stays_rate_and_records_coverage(tmp_path):
    p,e=product(tmp_path)
    r=m.summarize(p,e,datetime(2026,9,28,11,tzinfo=timezone.utc))
    assert r['units']=='mm/hr'
    assert len(r['regions'])==7
    for region in r['regions']:
        assert region['mean_rate']==pytest.approx(2)
        assert region['coverage_fraction']==1
        assert region['wet_area_fraction']==1


@pytest.mark.parametrize('invalid', ['units','interval','grid'])
def test_rejects_incompatible_product(tmp_path, invalid):
    p,e=product(tmp_path)
    with h5py.File(p,'a') as f:
        if invalid=='units': f['IMR'].attrs['units']='mm/day'
        if invalid=='interval': f.attrs['Acquisition_End_Time']='28-SEP-2026T10:57:20.326'
        if invalid=='grid': f['latitude'][1]=f['latitude'][0]
    with pytest.raises(ValueError):m.summarize(p,e,datetime(2026,9,28,11,tzinfo=timezone.utc))


def test_rejected_auth_is_not_retried_and_last_good_is_retained(tmp_path):
    import json
    import httpx
    root,public=tmp_path/'archive',tmp_path/'public'
    credentials=tmp_path/'credentials.json'
    credentials.write_text(json.dumps({'username':'test','password':'test-only'}))
    calls=[]
    def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith('datasets.json'):
            return httpx.Response(200,json={'entries':[{'identifier':'3SIMG_28SEP2026_0930_L2G_IMR_V01R00.h5','id':123}]})
        return httpx.Response(401,json={'error':'denied'})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        first=m.cycle(root,public,credentials,client)
        second=m.cycle(root,public,credentials,client)
    assert first['state']==second['state']=='authentication_rejected'
    assert calls.count('/download_api/gettoken')==1
    assert 'password' not in (public/'mosdac-status.json').read_text()

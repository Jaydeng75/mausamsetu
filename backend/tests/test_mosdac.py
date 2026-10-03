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

@pytest.mark.parametrize('download_ok,logout_ok', [(True,True),(False,True),(True,False)])
def test_authenticated_cycle_always_logs_out(tmp_path, download_ok, logout_ok):
    import json,httpx
    p,e=product(tmp_path);e['id']=123
    credentials=tmp_path/'credentials.json'
    credentials.write_text(json.dumps({'username':'test','password':'test-only'}))
    calls=[]
    def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith('datasets.json'):return httpx.Response(200,json={'entries':[e]})
        if request.url.path.endswith('gettoken'):return httpx.Response(200,json={'access_token':'test-token'})
        if request.url.path.endswith('logout'):
            assert json.loads(request.content)=={'username':'test'}
            return httpx.Response(200 if logout_ok else 503)
        return httpx.Response(200,content=p.read_bytes()) if download_ok else httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result=m.cycle(tmp_path/'archive',tmp_path/'public',credentials,client)
    assert calls.count('/download_api/logout')==1
    assert result['session_cleanup']==('complete' if logout_ok else 'failed')
    if not download_ok:assert result['state']=='unavailable'
    assert 'test-token' not in json.dumps(result)


def test_context_failure_and_recovery_recompute_health(tmp_path):
    import json
    from mausam.operational_health import apply_health,attach_mosdac
    now=datetime(2026,10,3,tzinfo=timezone.utc)
    p=tmp_path/'mosdac-status.json'
    p.write_text(json.dumps({'state':'authentication_rejected','checked_at':now.isoformat()}))
    state=apply_health(attach_mosdac({},tmp_path),now)
    assert state['status']=='degraded'
    p.write_text(json.dumps({'state':'available','checked_at':now.isoformat(),'session_cleanup':'complete'}))
    assert apply_health(attach_mosdac(state,tmp_path),now)['status']=='healthy'
    p.write_text(json.dumps({'state':'available','checked_at':'2026-10-01T00:00:00+00:00'}))
    assert apply_health(attach_mosdac(state,tmp_path),now)['alerts'][0]['code']=='mosdac_status_stale'

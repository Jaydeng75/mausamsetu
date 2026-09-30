import hashlib, importlib, json, subprocess
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pytest
from fastapi.testclient import TestClient
from mausam.golden import generate
from mausam.pipeline import publish_aligned
from mausam.storage import Archive
from mausam.refresh import refresh_once, choose_cycle
from mausam.verify import verify_run, available_skill


def test_concurrent_publication_and_pointer_recovery(tmp_path):
    archive=Archive(tmp_path);manifest={'input_hash':'fixed','published_at':'2026-01-01T00:00:00Z'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:archive.publish('same-run',{'data.txt':b'values'},manifest),range(8)))
    assert all(r==results[0] for r in results)
    (tmp_path/'latest.json').unlink()
    archive.publish('same-run',{'data.txt':b'values'},manifest)
    assert archive.latest()['run_id']=='same-run'
    with pytest.raises(ValueError,match='conflict'):
        archive.publish('same-run',{'data.txt':b'changed'},manifest)


def test_backfill_never_overwrites_newer_cycle(tmp_path):
    archive=Archive(tmp_path)
    archive.publish('new',{'data.txt':b'new'},{'input_hash':'new','decision_time':'2026-09-26T00:00:00Z'})
    archive.publish('old',{'data.txt':b'old'},{'input_hash':'old','decision_time':'2026-01-01T00:00:00Z'})
    assert archive.latest()['run_id']=='new'


def test_failed_refresh_preserves_published_pointer(tmp_path,monkeypatch):
    output=tmp_path/'public';output.mkdir();pointer=output/'latest.json';pointer.write_text('{"retained":true}')
    def fail(*args,**kwargs):raise subprocess.TimeoutExpired('test-refresh',30)
    monkeypatch.setattr('mausam.refresh.subprocess.run',fail)
    result=refresh_once(tmp_path/'archive',tmp_path/'cache',output,'20260925',0,24,24,30)
    assert result['state']=='failed' and pointer.read_text()=='{"retained":true}'
    assert json.loads((tmp_path/'archive'/'operations.json').read_text())['error_type']=='TimeoutExpired'


def test_cycle_selection_handles_midnight_and_lag():
    assert choose_cycle(datetime(2026,9,26,5,tzinfo=timezone.utc))==('20260925',12)
    assert choose_cycle(datetime(2026,9,26,22,tzinfo=timezone.utc))==('20260926',12)


@pytest.fixture
def hardened_api(tmp_path,monkeypatch):
    monkeypatch.setenv('MAUSAM_DATA_DIR',str(tmp_path));monkeypatch.setenv('MAUSAM_ALLOW_ANONYMOUS_READ','true')
    monkeypatch.delenv('OIDC_ISSUER',raising=False);monkeypatch.delenv('MAUSAM_ENV',raising=False)
    import mausam.api as module
    module=importlib.reload(module)
    with TestClient(module.app) as client:yield client,module


def test_readiness_and_integrity_are_real_checks(hardened_api):
    client,module=hardened_api
    assert client.get('/health/ready').status_code==503
    run=generate(module.ROOT);assert client.get('/health/ready').status_code==200
    (module.ROOT/'published'/run['run_id']/'forecast.nc').write_bytes(b'corrupt')
    assert client.get('/health/ready').status_code==503


def test_public_projection_is_opt_in_and_source_limited(hardened_api,tmp_path,monkeypatch):
    client,module=hardened_api
    name='public-20260926-00-abcdef123456.json'
    assert client.get('/public/products/'+name).status_code==404
    public=tmp_path/'public-assets';public.mkdir()
    monkeypatch.setenv('MAUSAM_PUBLIC_PRODUCTS','true');monkeypatch.setenv('MAUSAM_PUBLIC_DIR',str(public))
    product={'data_kind':'forecast','calibrated':False,'sources':{'GFS':{}}}
    path=public/name;path.write_text(json.dumps(product))
    assert client.get('/public/products/'+name).status_code==200
    product['sources']={'NEPS':{}};path.write_text(json.dumps(product))
    assert client.get('/public/products/'+name).status_code==503
    assert client.get('/public/products/observation.json').status_code==404


def test_shadow_point_projection_stays_research_only(hardened_api,monkeypatch):
    client,module=hardened_api
    monkeypatch.setenv('MAUSAM_PUBLIC_PRODUCTS','true')
    folder=module.ROOT/'shadow-rain';folder.mkdir(parents=True,exist_ok=True)
    product={'schema_version':1,'data_kind':'shadow_forecast','run_id':'shadow-fixture',
      'initialization':'2026-09-26T00:00:00+00:00','source_ids':['GFS','GEFS','IFS','AIFS'],
      'reference_used_for_training':'noaa-cmorph2-nrt-025','input_kind':'source_point_mixture',
      'calibrated':False,'production_active':False,'latitude':[13.,12.],'longitude':[79.,80.],
      'trained_leads':[24],'leads':{'24':{'mean_mm':[10.,20.,30.,40.],
      'weights':{'GFS':[.1,.1,.1,.1],'GEFS':[.2,.2,.2,.2],'IFS':[.3,.3,.3,.3],'AIFS':[.4,.4,.4,.4]},
      'exceedance_mass_64.5mm':[0.,0.,0.,0.],'exceedance_mass_115.6mm':[0.,0.,0.,0.]}}}
    (folder/'latest-shadow.json').write_text(json.dumps(product))
    response=client.get('/public/shadow-rain/point',params={'lat':13,'lng':79,'lead':24})
    assert response.status_code==200
    data=response.json()
    assert data['production_active'] is False and data['calibrated'] is False
    assert sum(data['weights'].values())==pytest.approx(1)
    assert client.get('/public/shadow-rain/point',params={'lat':13,'lng':79,'lead':48}).status_code==404
    product['initialization']='2026-09-26T12:00:00+00:00'
    (folder/'latest-shadow.json').write_text(json.dumps(product))
    assert client.get('/public/shadow-rain/point',params={'lat':13,'lng':79,'lead':24}).status_code==503

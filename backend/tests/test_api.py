import importlib,os
import pytest
from fastapi.testclient import TestClient
from mausam.golden import generate

@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setenv('MAUSAM_DATA_DIR',str(tmp_path));monkeypatch.setenv('MAUSAM_ALLOW_ANONYMOUS_READ','true');monkeypatch.delenv('OIDC_ISSUER',raising=False)
    import mausam.api as module
    module=importlib.reload(module);generate(tmp_path)
    with TestClient(module.app) as client:yield client,module

def test_point_provenance_and_bounds(api):
    c,m=api;r=c.get('/v1/forecast/point',params={'run_id':'golden-20260926-00-v1','lat':13.08,'lng':80.27});assert r.status_code==200
    d=r.json();assert d['data_kind']=='synthetic' and d['grid_cell']=={'lat':13,'lng':80};assert d['p10']<=d['p90']
    assert c.get('/v1/forecast/point',params={'run_id':'golden-20260926-00-v1','lat':60,'lng':80}).status_code==422

def test_viewer_cannot_mutate(api):
    c,m=api
    assert c.post('/v1/reviews',json={'run_id':'golden-20260926-00-v1','text':'Review fixture','status':'draft','lat':13,'lng':80}).status_code==403
    assert c.post('/v1/model-promotions',json={'version':'test','reason':'reviewed candidate'}).status_code==403

def test_download_protected_when_auth_required(api,monkeypatch):
    c,m=api;monkeypatch.setenv('MAUSAM_ALLOW_ANONYMOUS_READ','false')
    assert c.get('/v1/products/golden-20260926-00-v1/download').status_code==503

def test_replay_cannot_use_future_publication(api):
    c,m=api
    m.app.dependency_overrides[m.identity]=lambda:{'sub':'reviewer','roles':['reviewer']}
    assert c.post('/v1/replay-jobs',json={'run_id':'golden-20260926-00-v1','as_of':'2020-01-01T00:00:00Z'}).status_code==409

def test_unknown_run_is_not_zero_rain(api):
    c,m=api;assert c.get('/v1/runs/missing').status_code==404

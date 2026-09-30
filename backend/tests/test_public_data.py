import json
from pathlib import Path
import numpy as np
import pytest
from mausam.weatherbench import scores,outside_india
from mausam.research_access import tigge_request
from mausam.public_data import validate_run,convert


def test_area_weighting_and_exclusion():
    # A huge Indian-cell error must not contribute; polar rows have lower weight.
    p=np.array([[[2.,999.],[4.,4.]]]);t=np.zeros_like(p)
    r=scores(p,t,np.array([0.,60.]),np.array([[True,False],[True,True]]))
    assert r['rmse']==pytest.approx(np.sqrt(10))
    assert r['mae']==pytest.approx(3)
    assert r['pairs']==3


def test_india_mask():
    countries=json.loads((Path(__file__).parents[2]/'public/data/countries.geojson').read_text())
    m=outside_india([22.,51.],[80.,0.],countries)
    assert not m[0,0] and m[1,1]


def test_missing_observations_fail():
    with pytest.raises(ValueError,match='Missing'):
        scores(np.array([[[np.nan]]]),np.zeros((1,1,1)),np.array([0]),np.ones((1,1),bool))


def test_tigge_member_roster_and_delay():
    with pytest.raises(ValueError,match='roster'):tigge_request('2020-01-01',0,'pf')
    request=tigge_request('2020-01-01',0,'pf',[1,2,3])
    assert request['origin']=='dems' and request['number']=='1/2/3'
    with pytest.raises(ValueError,match='48-hour'):tigge_request('2099-01-01',0,'cf')


def test_wrong_run_rejected():
    with pytest.raises(ValueError,match='run/lead'):
        validate_run({'2t':{'date':20260925,'time':0,'end':24}},'20260925',0,30)


def test_null_rain_preserved_and_vector_speed():
    f={k:{'array':np.array([[v]]),'units':u} for k,v,u in [('2t',300,'K'),('10u',3,'m s**-1'),('10v',4,'m s**-1'),('msl',101000,'Pa')]}
    r=convert(f,np.array([[np.nan]]))
    assert r['rain']==[None] and r['wind']==[5] and r['temperature']==[26.85]


def test_published_assets_have_real_provenance_and_matching_grids():
    import hashlib
    root=Path(__file__).parents[2]/'public/data/products'
    for pointer in ['latest.json','global-latest.json','weatherbench-latest.json']:
        if not (root/pointer).exists():pytest.skip('Public product not generated')
        m=json.loads((root/pointer).read_text());b=(root/m['path']).read_bytes()
        assert hashlib.sha256(b).hexdigest()==m['sha256']
        p=json.loads(b);n=len(p['latitude'])*len(p['longitude'])
        assert p['data_kind'] in ['forecast','historical_evaluation']
        for name,src in p['sources'].items():
            expected=p.get('source_leads',{}).get(name,p['leads'])
            assert set(src)==set(map(str,expected))
            assert set(expected)<=set(p['leads'])
            for fields in src.values():
                for a in fields.values():assert len(a)==n and all(x is None or np.isfinite(x) for x in a)
        if p['data_kind']=='forecast':
            assert set(p['sources']) <= {'GFS','GEFS','IFS','AIFS'} and {'GFS','AIFS'} <= set(p['sources'])
            if 'GEFS' in p['sources']:
                assert p['source_roles']['GEFS']=='ensemble_mean'
                assert p['ensemble_context']['GEFS']['member_count']>1
                assert p['ensemble_context']['GEFS']['member_count_source']=='GRIB numberOfForecastsInEnsemble'
            if pointer=='global-latest.json':
                assert p['coverage']=='global' and p['leads']==[24,48,72,96,120,144,168]
                assert len(p['latitude'])==91 and len(p['longitude'])==180
            else:
                assert p.get('coverage','india')=='india'
                if 'IFS' in p['sources'] and p.get('source_leads'):
                    assert p['source_leads']['IFS']==[24,48,72,96,120,144,168]

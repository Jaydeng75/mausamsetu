import json
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest
from mausam.public_data import precipitation_increment
from mausam.operational_health import apply_health
from mausam.live_shadow import archive_forecast
from mausam.multi_shadow import archive_public_product, _archive
from test_live_shadow import make_product


def test_quantized_accumulations_allow_encoding_noise_but_reject_reset():
    prev={'array':np.array([1.06,2.]),'packing_resolution':.01}
    cur={'array':np.array([1.,3.]),'packing_resolution':.1}
    assert np.allclose(precipitation_increment(cur,prev),[0,1])
    cur['array'][0]=.5
    with pytest.raises(ValueError,match='reset'):precipitation_increment(cur,prev)


def test_rain_archive_accepts_sparse_ifs_leads_and_preserves_original(tmp_path):
    p,_,_=make_product(tmp_path,0);d=json.loads(p.read_text());d['leads']=[24,30]
    p.write_text(json.dumps(d));meta=archive_forecast(p,tmp_path/'archive')
    with np.load(tmp_path/'archive'/meta['values_file']) as a:assert a['leads'].tolist()==[24]
    original=(tmp_path/'archive'/meta['values_file']).read_bytes()
    d['sources']['GFS']['24']['rain'][0]=999;p.write_text(json.dumps(d))
    archive_forecast(p,tmp_path/'archive')
    assert (tmp_path/'archive'/meta['values_file']).read_bytes()==original


def test_multi_archive_preserves_sparse_missing_cells(tmp_path):
    p,_,_=make_product(tmp_path,0);d=json.loads(p.read_text());d['leads']=[24,48,72]
    for source in d['sources'].values():
        source['48']=json.loads(json.dumps(source['24']));source['72']=json.loads(json.dumps(source['24']))
    d['sources']['IFS']['48']['rain'][0]=None;p.write_text(json.dumps(d))
    archive_public_product(p,tmp_path/'archive')
    _,v=_archive(next((tmp_path/'archive').glob('*.json')))
    assert np.isnan(v['rain'][1,2,0,0]);assert np.isfinite(v['temperature']).all()


def test_global_degradation_and_stalled_evidence_are_alerted():
    now=datetime(2026,9,30,tzinfo=timezone.utc)
    d={'alerts':[],'global_forecast':{'sources':{'GFS':'unavailable','GEFS':'loaded','IFS':'loaded','AIFS':'loaded'}},'validation':{'prospective_start':'2026-09-26T00:00:00+00:00','rain_prospective_event_blocks':0}}
    apply_health(d,now)
    assert d['status']=='degraded';assert d['global_forecast']['state']=='degraded'
    assert {a['code'] for a in d['alerts']}=={'global_sources_degraded','prospective_evidence_stalled'}


def test_imd_failed_window_does_not_starve_next_window(tmp_path,monkeypatch):
    import mausam.imd_gauge as m
    initial=datetime(2026,9,26,tzinfo=timezone.utc);seen=[]
    monkeypatch.setattr(m,'_public_initializations',lambda p:[initial])
    def fail(init,lead,*args):seen.append(lead);raise ValueError('provider unavailable')
    monkeypatch.setattr(m,'verify_cycle_lead',fail)
    for h in [0,1]:m.run_due(tmp_path,tmp_path,tmp_path,now=datetime(2026,9,30,h,tzinfo=timezone.utc))
    assert seen==[24,48]


def test_completed_rain_windows_do_not_consume_work_budget(tmp_path,monkeypatch):
    import mausam.rain_service as m
    import mausam.live_shadow as s
    import mausam.multi_shadow as multi
    now=datetime.now(timezone.utc);seen=[]
    windows=[(tmp_path,{'run_id':f'r{i}'},24,now-timedelta(days=5-i)) for i in range(3)]
    monkeypatch.setattr(m,'eligible_windows',lambda *a,**k:iter(windows))
    monkeypatch.setattr(m,'verification_exists',lambda p,ref,run,lead:run=='r0')
    def fetch(kind,end,*a):seen.append(end);raise ValueError('waiting')
    monkeypatch.setattr(m,'normalize_reference',fetch)
    monkeypatch.setattr(s,'refresh_shadow',lambda *a:{})
    monkeypatch.setattr(multi,'refresh_multi_shadow',lambda *a:{})
    m.run_once(tmp_path,tmp_path,tmp_path,max_windows=1)
    assert seen==[windows[1][3]]*2
    seen.clear();m.run_once(tmp_path,tmp_path,tmp_path,max_windows=1)
    assert seen==[windows[2][3]]*2

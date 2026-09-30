import hashlib,json
import numpy as np
import pytest
from mausam.golden import generate
from mausam.pipeline import publish_aligned
from mausam.verify import verify_run,available_skill

@pytest.fixture
def observation_case(tmp_path):
    generate(tmp_path)
    manifest=tmp_path/'golden'/'manifest.json';config=json.loads(manifest.read_text())
    config['run_id']='historical-fixture';config['decision_time']='2025-09-26T02:00:00+00:00'
    for source in config['sources']:
        for key in ['initialization_time_utc','provider_publication_time','ingested_at','valid_start_time','valid_end_time']:
            source['metadata'][key]=source['metadata'][key].replace('2026-','2025-')
    manifest.write_text(json.dumps(config));publish_aligned(manifest,tmp_path)
    values=np.load(manifest.parent/config['sources'][0]['file']).mean(axis=0)
    observation=tmp_path/'observation.npy';np.save(observation,values)
    metadata={'reference_id':'fixture','reference_kind':'synthetic','revision':'v1','data_kind':'synthetic',
      'sha256':hashlib.sha256(observation.read_bytes()).hexdigest(),'available_at':'2025-09-30T00:00:00Z',
      'valid_start':'2025-09-28T00:00:00Z','valid_end':'2025-09-29T00:00:00Z',
      'licence_reference':'CC0 synthetic fixture','units':'mm','variable':'rain',
      'latitude':config['lat'],'longitude':config['lon']}
    path=tmp_path/'observation.json';path.write_text(json.dumps(metadata))
    return tmp_path,observation,path,metadata


def test_verification_is_idempotent(observation_case):
    root,obs,path,meta=observation_case
    first=verify_run(root,'historical-fixture',obs,path)
    second=verify_run(root,'historical-fixture',obs,path)
    assert first==second
    assert first['verification']['n']==870
    assert np.isfinite(first['verification']['crps'])
    assert len(json.loads((root/'verification.json').read_text())['rows'])==1
    assert available_skill(root,'2025-09-29T12:00:00Z','fixture','synthetic')==[]
    assert len(available_skill(root,'2025-10-01T00:00:00Z','fixture','synthetic'))==1
    assert available_skill(root,'2025-10-01T00:00:00Z','other-reference','synthetic')==[]


def test_observation_window_and_units_are_not_guessed(observation_case):
    root,obs,path,meta=observation_case
    meta['units']='metres';path.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='units'):verify_run(root,'historical-fixture',obs,path)
    meta['units']='mm';meta['valid_start']='2025-09-28T03:00:00Z';path.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='interval'):verify_run(root,'historical-fixture',obs,path)


def test_reference_identity_cannot_mix_real_and_synthetic(observation_case):
    root,obs,path,meta=observation_case
    meta['data_kind']='forecast';path.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='combined'):verify_run(root,'historical-fixture',obs,path)


def test_observation_inbox_verifies_once(observation_case):
    import shutil
    from mausam.observation_inbox import process_inbox
    root,obs,path,meta=observation_case
    inbox=root/'observation-inbox';inbox.mkdir()
    shutil.copyfile(obs,inbox/'batch.npy')
    meta.update(ready=True,file='batch.npy',run_id='historical-fixture')
    (inbox/'batch.json').write_text(json.dumps(meta))
    results=process_inbox(root)
    assert len(results)==1 and results[0]['status']=='verified'
    assert process_inbox(root)==[]
    assert len(json.loads((root/'verification.json').read_text())['rows'])==1


def test_observation_inbox_waits_for_published_release(observation_case):
    from mausam.observation_inbox import process_inbox
    root,obs,path,meta=observation_case
    inbox=root/'observation-inbox';inbox.mkdir()
    meta.update(ready=True,file='batch.npy',run_id='historical-fixture',available_at='2099-01-01T00:00:00Z')
    (inbox/'batch.json').write_text(json.dumps(meta))
    assert process_inbox(root)==[]

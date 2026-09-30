import json
from pathlib import Path
from datetime import datetime,timezone
import pytest
import xarray as xr
from mausam.golden import generate
from mausam.pipeline import publish_aligned
from mausam.storage import Archive
from mausam.contracts import SourceMetadata

def test_atomic_publication_idempotency_and_product(tmp_path):
    first=generate(tmp_path);second=generate(tmp_path);assert first==second
    assert Archive(tmp_path).latest()['run_id']==first['run_id']
    with xr.open_dataset(tmp_path/'published'/first['run_id']/'forecast.nc') as ds:
        assert float(ds.source_weights.sum())==pytest.approx(1)
        assert bool((ds.p90>=ds.p10).all());assert bool((ds.probability<=1+1e-9).all())

def test_bad_source_never_replaces_last_published_run(tmp_path):
    original=generate(tmp_path);p=tmp_path/'golden'/'manifest.json';config=json.loads(p.read_text());config['run_id']='bad-run';config['sources'][0]['metadata']['file_checksum']='0'*64;p.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='checksum'):publish_aligned(p,tmp_path)
    assert Archive(tmp_path).latest()['run_id']==original['run_id']

def test_misaligned_windows_rejected(tmp_path):
    generate(tmp_path);p=tmp_path/'golden'/'manifest.json';c=json.loads(p.read_text());c['run_id']='bad-window';c['sources'][0]['metadata']['valid_start_time']='2026-09-27T00:00:00+00:00';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='Incompatible'):publish_aligned(p,tmp_path)

def test_lookahead_source_rejected(tmp_path):
    generate(tmp_path);p=tmp_path/'golden'/'manifest.json';c=json.loads(p.read_text());c['run_id']='future-input';c['decision_time']='2026-09-26T00:30:00+00:00';p.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='Missing-source'):publish_aligned(p,tmp_path)

def test_archive_path_traversal(tmp_path):
    with pytest.raises(ValueError):Archive(tmp_path).publish('../bad',{}, {})


def test_explicit_missing_file_requires_validated_fallback(tmp_path):
    generate(tmp_path)
    path=tmp_path/'golden'/'manifest.json';config=json.loads(path.read_text())
    config['run_id']='missing-source-file'
    config['sources'][0]['unavailable']=True
    config['sources'][0]['file']='not-arrived.npy'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='Missing-source'):
        publish_aligned(path,tmp_path)
    config['model']['validated_missing_source_patterns']=[[False,True,True,True]]
    path.write_text(json.dumps(config));result=publish_aligned(path,tmp_path)
    assert result['quality']=='degraded'
    assert result['sources'][0]['file_checksum'] is None
    with xr.open_dataset(tmp_path/'published'/'missing-source-file'/'forecast.nc') as ds:
        assert float(ds.source_weights.isel(source=0))==0
        assert float(ds.source_weights.sum())==pytest.approx(1)


def test_context_feature_hindsight_and_checksum_are_rejected(tmp_path):
    import hashlib,numpy as np
    generate(tmp_path)
    path=tmp_path/'golden'/'manifest.json';config=json.loads(path.read_text());config['run_id']='context-test'
    values=np.ones((len(config['lat']),len(config['lon'])),dtype=float)
    feature=path.parent/'context.npy';np.save(feature,values)
    digest=hashlib.sha256(feature.read_bytes()).hexdigest()
    config['context_features']=[{'name':'tpw','file':feature.name,'sha256':digest,'available_at':'2026-09-27T00:00:00+00:00'}]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='Hindsight'):publish_aligned(path,tmp_path)
    config['context_features'][0]['available_at']='2026-09-26T01:00:00+00:00'
    config['context_features'][0]['sha256']='0'*64;path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='Context feature checksum'):publish_aligned(path,tmp_path)

import json
from pathlib import Path

import numpy as np
import pytest

from mausam.public_rain_verify import verify_public_rain
from mausam.rain_references import area_mean_to_grid,earthdata_auth
from mausam.storage import json_bytes


def test_area_mean_regridding_preserves_missingness_and_weighting():
    source_lat=np.array([-0.375,-0.125,0.125,0.375])
    source_lon=np.array([0.125,0.375,0.625,0.875])
    values=np.arange(16,dtype=float).reshape(4,4)
    result,coverage=area_mean_to_grid(values,source_lat,source_lon,[0.0,1.0],[0.5,1.5],minimum_fraction=.9)
    weights=np.cos(np.deg2rad(source_lat))[:,None]*np.ones((1,4))
    assert result[0,0]==pytest.approx(np.sum(values*weights)/weights.sum())
    assert coverage[0,0]==1
    values[0,0]=np.nan
    result,coverage=area_mean_to_grid(values,source_lat,source_lon,[0.0,1.0],[0.5,1.5],minimum_fraction=.95)
    assert np.isnan(result[0,0]) and coverage[0,0]==pytest.approx(15/16)


def make_case(tmp_path):
    product={
      'schema_version':1,'data_kind':'forecast','coverage':'india','run_id':'public-test-00',
      'initialization':'2026-09-25T00:00:00+00:00','retrieved_at':'2026-09-25T08:00:00+00:00',
      'leads':[24],'latitude':[1.0,0.0],'longitude':[70.0,71.0],
      'sources':{'GFS':{'24':{'rain':[0.,10.,20.,30.]}},'AIFS':{'24':{'rain':[0.,8.,18.,28.]}}},
      'calibrated':False,'grid_method':'fixture','attribution':'fixture'}
    product_path=tmp_path/'forecast.json';product_path.write_text(json.dumps(product))
    values=np.array([[0.,9.],[19.,29.]],dtype=np.float32)
    coverage=np.ones_like(values)
    values_path=tmp_path/'values.npy';coverage_path=tmp_path/'coverage.npy'
    np.save(values_path,values,allow_pickle=False);np.save(coverage_path,coverage,allow_pickle=False)
    import hashlib
    metadata={
      'reference_id':'test-satellite','reference_kind':'satellite','product':'fixture satellite','revision':'v1',
      'valid_start':'2026-09-25T00:00:00+00:00','valid_end':'2026-09-26T00:00:00+00:00',
      'available_at':'2026-09-26T04:00:00+00:00','variable':'rain','units':'mm',
      'latitude':[1.0,0.0],'longitude':[70.0,71.0],
      'values_file':values_path.name,'coverage_file':coverage_path.name,
      'values_sha256':hashlib.sha256(values_path.read_bytes()).hexdigest(),
      'coverage_sha256':hashlib.sha256(coverage_path.read_bytes()).hexdigest()}
    metadata_path=tmp_path/'reference.json';metadata_path.write_text(json.dumps(metadata))
    return product_path,metadata_path


def test_public_rain_verification_keeps_reference_identity_and_exact_window(tmp_path):
    product,reference=make_case(tmp_path)
    report=verify_public_rain(product,reference)
    assert report['reference_id']=='test-satellite'
    assert report['reference_kind']=='satellite precipitation estimate'
    assert report['lead_hours']==24
    assert {row['model'] for row in report['scores']}=={'GFS','AIFS','Equal blend'}
    aifs=next(row for row in report['scores'] if row['model']=='AIFS')
    assert aifs['rmse']==pytest.approx(np.sqrt(3/4))
    assert len(report['verification_id'])==64


def test_public_rain_verification_rejects_window_mismatch(tmp_path):
    product,reference=make_case(tmp_path)
    metadata=json.loads(reference.read_text())
    metadata['valid_start']='2026-09-25T01:00:00+00:00'
    reference.write_text(json.dumps(metadata))
    with pytest.raises(ValueError,match='24-hour|windows differ'):
        verify_public_rain(product,reference)

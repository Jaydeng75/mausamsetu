"""Explicitly aligned observation verification; reference products stay separate."""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
from .science import crps, mixture, verification
from .storage import Archive, atomic_write, file_lock, json_bytes, safe_id


def utc(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None or result.utcoffset().total_seconds()!=0:
        raise ValueError('Observation timestamps require UTC')
    return result


def verify_run(root,run_id,observation_file,metadata_file):
    root=Path(root);forecast=Archive(root).verify(run_id)
    meta=json.loads(Path(metadata_file).read_text());reference=safe_id(meta['reference_id'])
    body=Path(observation_file).read_bytes();digest=hashlib.sha256(body).hexdigest()
    if digest!=meta['sha256']:raise ValueError('Observation checksum failed')
    if meta['data_kind']!=forecast['data_kind']:raise ValueError('Synthetic and real products cannot be combined')
    if meta['reference_kind'] not in ['gauge_analysis','station','satellite','radar','reanalysis','synthetic']:
        raise ValueError('Explicit verification reference kind required')
    if (meta['reference_kind']=='synthetic')!=(meta['data_kind']=='synthetic'):raise ValueError('Reference labeling mismatch')
    available=utc(meta['available_at']);end=utc(meta['valid_end'])
    if available<end or available>datetime.now(timezone.utc):raise ValueError('Invalid observation availability')
    if not meta.get('licence_reference') or not meta.get('revision'):raise ValueError('Licence and revision required')
    observed=np.load(observation_file,allow_pickle=False)
    with xr.open_dataset(root/'published'/run_id/'forecast.nc',engine='scipy') as ds:
        if observed.shape!=(ds.sizes['lat'],ds.sizes['lon']):raise ValueError('Observation grid shape differs')
        if not np.array_equal(meta['latitude'],ds.lat.values) or not np.array_equal(meta['longitude'],ds.lon.values):
            raise ValueError('Observation coordinates differ')
        if meta['units']!=ds.attrs['units'] or meta['variable']!=forecast['variable']:raise ValueError('Variable or units differ')
        if utc(meta['valid_start'])!=utc(ds.attrs['valid_start']) or end!=utc(ds.attrs['valid_end']):
            raise ValueError('Observation accumulation/valid interval differs')
        valid=np.isfinite(observed)
        if not valid.any():raise ValueError('No quality-controlled observations remain')
        if forecast['variable']=='rain' and (observed[valid]<0).any():raise ValueError('Negative observed rainfall')
        samples=[]
        for source_index,source in enumerate(forecast['sources']):
            if 'declared_unavailable' in source.get('quality_flags',[]):
                if np.any(ds.source_weights.isel(source=source_index).values!=0):
                    raise ValueError('Unavailable source has nonzero published weight')
                samples.append(np.zeros((1,ds.sizes['lat'],ds.sizes['lon'])))
                continue
            checksum=source['file_checksum']
            if len(checksum)!=64 or any(c not in '0123456789abcdef' for c in checksum):
                raise ValueError('Invalid archived source checksum')
            source_path=root/'raw'/checksum
            with source_path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=checksum:
                    raise ValueError('Archived source checksum failed')
            samples.append(np.load(source_path,allow_pickle=False,mmap_mode='r'))
        weights=ds.source_weights.values
        score=verification(ds['mean'].values[valid],observed[valid],ds['probability'].values[valid],forecast['threshold'])
        values=[]
        for index in zip(*np.where(valid)):
            result=mixture([s[(slice(None),)+index] for s in samples],weights[index] if weights.ndim==3 else weights,forecast['threshold'])
            values.append(crps(result['samples'],result['mass'],observed[index]))
        score['crps']=float(np.mean(values))
        score['weighting']='equal valid grid-cell weights; no area-weighted/global claim'
    identifier=hashlib.sha256(json_bytes({'run_id':run_id,'forecast_assets':forecast['assets'],'metadata':meta})).hexdigest()
    row={'id':identifier,'run_id':run_id,'variable':forecast['variable'],'region':meta.get('region','all'),
         'reference_id':reference,'reference_kind':meta['reference_kind'],'reference_revision':meta['revision'],
         'data_kind':forecast['data_kind'],'available_at':available.isoformat(),'valid_start':meta['valid_start'],
         'valid_end':meta['valid_end'],'units':meta['units'],'model_version':forecast['model']['version'],
         'threshold':forecast['threshold'],**score}
    report={'schema_version':1,'verification':row,'observation_metadata':meta,
            'forecast_manifest_sha256':hashlib.sha256(json_bytes(forecast)).hexdigest()}
    with file_lock(root/'.verification.lock'):
        raw=root/'observation-archive'/digest
        if not raw.exists():atomic_write(raw,body)
        path=root/'verification-reports'/(identifier+'.json')
        if path.exists() and path.read_bytes()!=json_bytes(report):raise ValueError('Immutable verification conflict')
        atomic_write(path,json_bytes(report))
        index=root/'verification.json';rows=json.loads(index.read_text())['rows'] if index.exists() else []
        rows=[r for r in rows if r['id']!=identifier]+[row]
        atomic_write(index,json_bytes({'schema_version':1,'rows':rows,'reference_policy':'Different references are not pooled'}))
    return report


def available_skill(root,decision_time,reference_id,data_kind):
    decision=utc(decision_time);path=Path(root)/'verification.json'
    if not path.exists():return []
    return [r for r in json.loads(path.read_text())['rows'] if r['reference_id']==reference_id
            and r['data_kind']==data_kind and utc(r['available_at'])<=decision]


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_id');p.add_argument('observation');p.add_argument('metadata')
    p.add_argument('--archive',default='./data');args=p.parse_args()
    print(json.dumps(verify_run(args.archive,args.run_id,args.observation,args.metadata),indent=2))

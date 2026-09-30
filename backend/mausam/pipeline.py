"""Worker command: validate an operator-provided, aligned source manifest and publish."""
import argparse,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from .science import mixture,masked_softmax
from .storage import Archive
from .contracts import SourceMetadata
from .ingest import eligible

STAGES=['discover','ingest','normalize','quality_control','features','blend','products','validate','publish']
def publish_aligned(manifest_path,root):
    path=Path(manifest_path);raw=path.read_bytes();config=json.loads(raw);decision=datetime.fromisoformat(config['decision_time'])
    if decision.tzinfo is None:raise ValueError('Publication decision must be timezone-aware')
    if config.get('model',{}).get('approved') is not True:raise ValueError('An explicitly approved model configuration is required')
    if config['model']['method'] not in ['equal','static','learned']:raise ValueError('Use the learned-gate worker for a learned artifact; no silent fallback')
    required=['run_id','variable','threshold','sources'];[config[k] for k in required]
    samples=[];availability=[];scores=[];metadata=[];windows=[]
    archive=Archive(root)
    for source in config['sources']:
        meta=SourceMetadata.model_validate(source['metadata']);metadata.append(meta.model_dump(mode='json'))
        if meta.variable!=config['variable']:raise ValueError('Source variable does not match product')
        windows.append((meta.initialization_time_utc,meta.valid_start_time,meta.valid_end_time,meta.units,meta.grid_id,meta.vertical_level_or_height))
        if source.get('unavailable') is True:
            metadata[-1]['quality_flags']=list(meta.quality_flags)+['declared_unavailable']
            metadata[-1]['file_checksum']=None
            availability.append(False)
            samples.append(np.zeros((1,len(config['lat']),len(config['lon']))))
            scores.append(0)
            continue
        data_path=path.parent/source['file'];data=data_path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=meta.file_checksum:raise ValueError('Source checksum failed')
        archive.put_raw(data);sample=np.load(data_path,allow_pickle=False)
        if sample.ndim!=3:raise ValueError('Expected members × latitude × longitude array')
        if not np.isfinite(sample).all():raise ValueError('Missing cells must be masked explicitly; withholding product')
        ok,_=eligible(meta,decision,source['required_members'],sample.shape[0]);availability.append(ok);samples.append(sample)
        scores.append(source.get('logit',0) if config['model']['method']=='static' else 0)
    if len({m['source_id'] for m in metadata})!=len(metadata):raise ValueError('Duplicate source IDs')
    if len({m['data_kind'] for m in metadata})!=1:raise ValueError('Synthetic and provider data cannot share a product')
    if len(set(windows))!=1:raise ValueError('Incompatible source runs, intervals, units, grids or levels')
    if len({x.shape[1:] for x in samples})!=1:raise ValueError('Sources have different grids')
    if not all(availability) and not config['model'].get('validated_missing_source_patterns',[]).__contains__(availability):raise ValueError('Missing-source configuration has not been validated')
    context={}
    for item in config.get('context_features',[]):
        name=item['name'];available_at=datetime.fromisoformat(item['available_at'])
        if available_at.tzinfo is None or available_at>decision:raise ValueError('Hindsight context feature detected')
        context_path=path.parent/item['file'];body=context_path.read_bytes()
        if hashlib.sha256(body).hexdigest()!=item['sha256']:raise ValueError('Context feature checksum failed')
        values=np.load(context_path,allow_pickle=False)
        if values.shape!=samples[0].shape[1:] or not np.isfinite(values).all():raise ValueError('Invalid context feature grid')
        archive.put_raw(body);context[name]=values
    weights=masked_softmax(scores,availability)
    approval=None;model_digest=''
    if config['model']['method']=='learned':
        from .adaptive import context_features,predict_weights
        from .registry import approved_model
        if config['model']['version']=='active':
            from .registry import resolve_active
            config['model']['version']=resolve_active(root,metadata[0]['data_kind'])['version']
        model,candidate,approval=approved_model(root,config['model']['version'],metadata[0]['data_kind'])
        if model['source_ids'] != [m['source_id'] for m in metadata] or model['variable'] != config['variable'] or model['units'] != metadata[0]['units']:
            raise ValueError('Gate source roster, variable or units do not match product')
        if not all(availability) and availability not in model.get('validated_missing_source_patterns',[]):
            raise ValueError('Gate missing-source configuration has not been validated')
        features,names=context_features(samples,config['lat'],config['lon'],metadata[0]['lead_time'],metadata[0]['initialization_time_utc'],context)
        if names != model['feature_names']:
            raise ValueError('Gate feature schema mismatch')
        weights=predict_weights(model,features,availability)
        model_digest=candidate['model_sha256']
    products={k:np.empty(samples[0].shape[1:]) for k in ['mean','median','p10','p90','probability']}
    for index in np.ndindex(products['mean'].shape):
        result=mixture([s[(slice(None),)+index] for s in samples],weights[index] if weights.ndim==3 else weights,config['threshold'])
        for key in products:products[key][index]=result[key]
    if config['variable']=='rain' and np.any(products['p10']<0):raise ValueError('Negative precipitation distribution')
    if np.any(products['p10']>products['p90']):raise ValueError('Quantile ordering failed')
    import xarray as xr
    coords={'lat':config['lat'],'lon':config['lon']}
    dataset=xr.Dataset({k:(('lat','lon'),v) for k,v in products.items()},coords=coords,attrs={'run_id':config['run_id'],'model_version':config['model']['version'],'units':metadata[0]['units'],'valid_start':metadata[0]['valid_start_time'],'valid_end':metadata[0]['valid_end_time'],'publication_status':'experimental','data_kind':metadata[0]['data_kind']})
    dataset['source_weights']=xr.DataArray(weights,dims=['lat','lon','source'] if weights.ndim==3 else ['source'],coords={'source':[m['source_id'] for m in metadata]})
    payload={'forecast.nc':bytes(dataset.to_netcdf(engine='scipy'))}
    output_manifest={'input_hash':hashlib.sha256(raw+model_digest.encode()).hexdigest(),'sources':metadata,'model':config['model'],'quality':'complete' if all(availability) else 'degraded','published_at':datetime.now(timezone.utc).isoformat(),'decision_time':config['decision_time'],'variable':config['variable'],'threshold':config['threshold'],'data_kind':metadata[0]['data_kind'],'stages':STAGES,'approval':approval,'activate':config.get('activate',True)}
    return archive.publish(config['run_id'],payload,output_manifest)

def scheduled_flow(manifest_path,root):
    from prefect import flow,task
    @task(retries=2,retry_delay_seconds=10)
    def process():return publish_aligned(manifest_path,root)
    @flow(name='mausamsetu-forecast-cycle')
    def run():return process()
    return run()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('--archive',default='./data');p.add_argument('--prefect',action='store_true');args=p.parse_args();print(json.dumps((scheduled_flow if args.prefect else publish_aligned)(args.manifest,args.archive),indent=2))

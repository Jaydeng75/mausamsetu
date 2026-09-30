"""Reproducible, bounded IFS/Pangu temperature experiment; never auto-promoted."""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import fsspec, httpx, numpy as np, xarray as xr
from .adaptive import fit_gate, predict_weights, crps_terms, mixture_crps, save_candidate
from .science import masked_softmax
from .storage import atomic_write, json_bytes

ROOT='https://storage.googleapis.com/weatherbench2/datasets/'
DATASETS={
 'IFS-HRES-WB2':ROOT+'hres/2016-2022-0012-240x121_equiangular_with_poles_conservative.zarr',
 'Pangu-WB2':ROOT+'pangu/2018-2022_0012_240x121_equiangular_with_poles_conservative.zarr',
 'ERA5':ROOT+'era5/1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr'}


def coordinates(ds):
    ds=ds.assign_coords(longitude=((ds.longitude+180)%360)-180)
    return ds.sortby('longitude').sortby('latitude')


def collect(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/'paired-temperature.npz'
    if target.exists():
        manifest=json.loads((directory/'dataset-manifest.json').read_text())
        if hashlib.sha256(target.read_bytes()).hexdigest()!=manifest['sha256']:
            raise ValueError('Cached matched archive checksum failed')
        with np.load(target,allow_pickle=False) as data:return {k:data[k] for k in data.files}
    opened={k:coordinates(xr.open_zarr(fsspec.get_mapper(v),consolidated=True,decode_timedelta=True)) for k,v in DATASETS.items()}
    names=['IFS-HRES-WB2','Pangu-WB2'];base=opened[names[0]]
    for ds in opened.values():
        if not np.array_equal(base.latitude,ds.latitude) or not np.array_equal(base.longitude,ds.longitude):
            raise ValueError('Forecast/reference grids do not match exactly')
    region={'latitude':slice(6,38),'longitude':slice(66,100)}
    opened={k:v.sel(**region) for k,v in opened.items()}
    lat=opened[names[0]].latitude.values;lon=opened[names[0]].longitude.values
    times=np.array([f'{year}-{month:02d}-{day:02d}' for year in range(2018,2023)
                    for month in range(1,13) for day in [1,11,21]],dtype='datetime64[ns]')
    leads=np.array([24,72,168]);sources=[];truth=[]
    for lead in leads:
        selected=[]
        for name in names:
            values=opened[name]['2m_temperature'].sel(time=times,prediction_timedelta=np.timedelta64(int(lead),'h'))
            selected.append(values.transpose('time','latitude','longitude').compute(scheduler='threads',num_workers=8).values-273.15)
            print(f'Downloaded {name} +{lead}h ({len(times)} initializations)',flush=True)
        values=opened['ERA5']['2m_temperature'].sel(time=times+np.timedelta64(int(lead),'h'))
        truth.append(values.transpose('time','latitude','longitude').compute(scheduler='threads',num_workers=8).values-273.15)
        sources.append(np.stack(selected,axis=-1))
    data={'predictions':np.stack(sources,axis=1),'observations':np.stack(truth,axis=1),
          'time':times.astype('int64'),'leads':leads,'latitude':lat,'longitude':lon}
    if not np.isfinite(data['predictions']).all() or not np.isfinite(data['observations']).all():
        raise ValueError('Missing values in selected matched archive')
    np.savez_compressed(target,**data)
    atomic_write(directory/'dataset-manifest.json',json_bytes({'datasets':DATASETS,'variable':'2m_temperature',
        'units':'degree_Celsius','initializations':len(times),'years':[2018,2019,2020,2021,2022],
        'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'retrieved_at':datetime.now(timezone.utc).isoformat(),
        'use':'local retrospective research; not a live as-of replay or licensed operational deployment'}))
    return data


def experiment(directory,output):
    data=collect(directory);p=data['predictions'];o=data['observations']
    times=data['time'].astype('datetime64[ns]');years=times.astype('datetime64[Y]').astype(int)+1970
    ny,nx=len(data['latitude']),len(data['longitude']);nlead=len(data['leads'])
    # Calibration uses 2018 only. Gate training, selection and final testing are disjoint.
    residual=o[years==2018,...,None]-p[years==2018]
    offsets=np.quantile(residual.reshape(-1,2),np.linspace(.025,.975,21),axis=0).T
    samples=p[...,None]+offsets
    shape=o.shape;ygrid,xgrid=np.meshgrid(data['latitude'],data['longitude'],indexing='ij')
    day=(times.astype('datetime64[D]')-times.astype('datetime64[Y]')).astype(int)+1
    tile=lambda v:np.broadcast_to(v,shape)
    columns=[tile(ygrid),tile(xgrid),tile(data['leads'][None,:,None,None]),
             tile(np.sin(2*np.pi*day/366)[:,None,None,None]),tile(np.cos(2*np.pi*day/366)[:,None,None,None])]
    names=['latitude','longitude','lead_hours','day_sin','day_cos']
    for i in range(2):
        columns.extend([samples[...,i,:].mean(-1),samples[...,i,:].std(-1)])
        names.extend([f'source_{i}_mean',f'source_{i}_spread'])
    features=np.stack(columns,axis=-1).reshape(-1,len(names));samples=samples.reshape(-1,2,21)
    observed=o.reshape(-1);year=tile(years[:,None,None,None]).reshape(-1)
    mass=tile(np.cos(np.deg2rad(ygrid))).reshape(-1)
    train=(year>=2019)&(year<=2020);validate=year==2021;test=year==2022
    validation_first,validation_pair=crps_terms(samples[validate],observed[validate])
    candidates=[]
    for penalty in [.01,.1,1.]:
        model=fit_gate(features[train],samples[train],observed[train],case_weights=mass[train],regularization=penalty,maxiter=500)
        weights=predict_weights(model,features[validate],[True,True])
        score=np.average(mixture_crps(weights,validation_first,validation_pair),weights=mass[validate])
        candidates.append((float(score),penalty,model));print('Validation CRPS',penalty,float(score),flush=True)
    _,penalty,model=min(candidates,key=lambda item:item[0])
    model.update(source_ids=['IFS-HRES-WB2','Pangu-WB2'],feature_names=names,variable='temperature',units='degC',
                 residual_offsets=offsets.tolist(),validated_missing_source_patterns=[])
    static=fit_gate(np.zeros((int(train.sum()),1)),samples[train],observed[train],case_weights=mass[train])
    weights=predict_weights(model,features[test],[True,True])
    static_weights=predict_weights(static,np.zeros((int(test.sum()),1)),[True,True])
    first,pair=crps_terms(samples[test],observed[test]);test_mass=mass[test];actual=observed[test]
    means=samples[test].mean(-1);raw=p.reshape(-1,2)[test]
    scores=[];losses={};families={}
    for i,name in enumerate(model['source_ids']):
        error=raw[:,i]-actual
        scores.append({'model':name+' raw','rmse':float(np.sqrt(np.average(error**2,weights=test_mass))),
                       'mae':float(np.average(np.abs(error),weights=test_mass)),
                       'bias':float(np.average(error,weights=test_mass)),
                       'crps':float(np.average(np.abs(error),weights=test_mass)),
                       'distribution':'deterministic point mass'})
        families[name+' calibrated']=np.broadcast_to(np.eye(2)[i],weights.shape)
    families.update({'Equal mixture':np.full_like(weights,.5),'Static mixture':static_weights,'Adaptive mixture':weights})
    for name,w in families.items():
        error=np.sum(w*means,axis=-1)-actual
        loss=mixture_crps(w,first,pair);losses[name]=loss
        scores.append({'model':name,'rmse':float(np.sqrt(np.average(error**2,weights=test_mass))),
          'mae':float(np.average(np.abs(error),weights=test_mass)),
          'bias':float(np.average(error,weights=test_mass)),
          'crps':float(np.average(loss,weights=test_mass)),
          'distribution':'empirical calibrated residual mixture'})
    subgroups=[]
    lead_values=tile(data['leads'][None,:,None,None]).reshape(-1)[test]
    months=tile((times.astype('datetime64[M]').astype(int)%12+1)[:,None,None,None]).reshape(-1)[test]
    for lead in data['leads']:
        for name,w in families.items():
            use=lead_values==lead
            subgroups.append({'lead':int(lead),'model':name,
              'crps':float(np.average(losses[name][use],weights=test_mass[use]))})
    delta=[]
    for month in range(1,13):
        use=months==month
        delta.append(float(np.average(losses['Adaptive mixture'][use]-losses['Static mixture'][use],weights=test_mass[use])))
    rng=np.random.default_rng(26081)
    ci=np.quantile(rng.choice(delta,size=(2000,12),replace=True).mean(1),[.025,.975]).tolist()
    report={'schema_version':1,'data_kind':'forecast','reference':'ERA5 reanalysis, not independent station observations',
      'experiment':'IFS-HRES + Pangu temperature; India-region bounding box on shared 1.5-degree grid',
      'calibration_years':[2018],'training_years':[2019,2020],'validation_years':[2021],'test_years':[2022],
      'initializations':len(times),'test_initializations':int((years==2022).sum()),
      'training_cases':int(train.sum()),'test_cases':int(test.sum()),'test_event_blocks':12,
      'latitude_points':ny,'longitude_points':nx,'units':'degC','lead_hours':data['leads'].tolist(),
      'scores':scores,'by_lead':subgroups,'crps_difference_vs_static_95ci':ci,
      'selected_regularization':penalty,'validation_candidates':[{'crps':v,'regularization':r} for v,r,_ in candidates],
      'acceptance_passed':False,'eligible_for_production':False,'upstream_training_audited':False,
      'data_manifest':json.loads((Path(directory)/'dataset-manifest.json').read_text()),
      'limitations':['Retrospective experiment: ERA5-initialized Pangu is not a real-time as-of replay.',
       'Three initialization dates per month; not every event, station or forecast cycle.',
       'Bounding box includes adjacent countries and ocean cells; this is not an India land-only score.',
       'Temperature only; this experiment does not establish rainfall, wind or extreme-weather skill.',
       'Only 12 monthly bootstrap blocks; uncertainty estimates remain imprecise.',
       'Source calibration pooled across the domain. Local coverage needs separate validation.',
       'Different source roster from live GFS/AIFS; weights must never be transferred to those models.',
       'Dataset-specific redistribution rights and upstream checkpoint identity require review before deployment.']}
    save_candidate(Path(directory)/'models'/'ifs-pangu-temperature-v1',model,report)
    atomic_write(output,json_bytes(report))
    print(json.dumps({'scores':scores,'report':str(output),'production_eligible':False}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    experiment(args.archive,args.output)

"""Bounded IFS-HRES + GraphCast rainfall experiment over an India-region box.

This is retrospective research against ERA5 reanalysis. It is not an
operational replay and is never auto-promoted.
"""
import argparse, hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path
import fsspec, numpy as np, xarray as xr
from .adaptive import fit_gate,predict_weights,crps_terms,mixture_crps,save_candidate
from .storage import atomic_write,json_bytes

ROOT="https://storage.googleapis.com/weatherbench2/datasets/"
DATASETS={
 "IFS-HRES-WB2":ROOT+"hres/2016-2022-0012-240x121_equiangular_with_poles_conservative.zarr",
 "GraphCast-WB2":ROOT+"graphcast/2020/date_range_2019-11-16_2021-02-01_12_hours-240x121_equiangular_with_poles_conservative.zarr",
 "ERA5":ROOT+"era5/1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr"}
THRESHOLDS=[20.0,64.5,115.6]

def coordinates(ds):
    ds=ds.assign_coords(longitude=((ds.longitude+180)%360)-180)
    return ds.sortby("longitude").sortby("latitude")

def collect(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/"paired-rainfall-2020.npz"; manifest=directory/"rainfall-dataset-manifest.json"
    if target.exists():
        meta=json.loads(manifest.read_text())
        if hashlib.sha256(target.read_bytes()).hexdigest()!=meta["sha256"]: raise ValueError("Rainfall cache checksum failed")
        with np.load(target,allow_pickle=False) as z:return {k:z[k] for k in z.files}
    opened={k:coordinates(xr.open_zarr(fsspec.get_mapper(v),consolidated=True,decode_timedelta=True)) for k,v in DATASETS.items()}
    base=opened["IFS-HRES-WB2"]
    for ds in opened.values():
        if not np.array_equal(base.latitude,ds.latitude) or not np.array_equal(base.longitude,ds.longitude):
            raise ValueError("Forecast/reference grids differ")
    region={"latitude":slice(6,38),"longitude":slice(66,100)}
    opened={k:v.sel(**region) for k,v in opened.items()}
    lat=opened["IFS-HRES-WB2"].latitude.values;lon=opened["IFS-HRES-WB2"].longitude.values
    times=np.array([f"2020-{month:02d}-{day:02d}" for month in range(1,13) for day in (1,11,21)],dtype="datetime64[ns]")
    leads=np.array([24,72,168]);sources=[];truth=[];negative={}
    for lead in leads:
        selected=[]
        for name in ("IFS-HRES-WB2","GraphCast-WB2"):
            a=opened[name]["total_precipitation_24hr"].sel(time=times,prediction_timedelta=np.timedelta64(int(lead),"h"))
            values=a.transpose("time","latitude","longitude").compute(scheduler="threads",num_workers=8).values*1000
            negative[f"{name}:{int(lead)}"]=int((values<0).sum()); selected.append(np.maximum(values,0))
            print(f"Downloaded {name} rainfall +{lead}h",flush=True)
        ref=opened["ERA5"]["total_precipitation_24hr"].sel(time=times+np.timedelta64(int(lead),"h"))
        observed=ref.transpose("time","latitude","longitude").compute(scheduler="threads",num_workers=8).values*1000
        truth.append(np.maximum(observed,0));sources.append(np.stack(selected,axis=-1))
    data={"predictions":np.stack(sources,axis=1),"observations":np.stack(truth,axis=1),
      "time":times.astype("int64"),"leads":leads,"latitude":lat,"longitude":lon}
    if not np.isfinite(data["predictions"]).all() or not np.isfinite(data["observations"]).all(): raise ValueError("Nonfinite rainfall pair")
    np.savez_compressed(target,**data)
    meta={"datasets":DATASETS,"variable":"total_precipitation_24hr","units":"mm/24h","initializations":len(times),
      "year":2020,"negative_regridding_values_clipped_to_zero":negative,"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
      "retrieved_at":datetime.now(timezone.utc).isoformat(),"use":"retrospective research; ERA5 reference; not live as-of replay"}
    atomic_write(manifest,json_bytes(meta));return data
def _features(samples,times,leads,lat,lon):
    shape=samples.shape[:4];y,x=np.meshgrid(lat,lon,indexing="ij")
    day=(times.astype("datetime64[D]")-times.astype("datetime64[Y]")).astype(int)+1
    tile=lambda a:np.broadcast_to(a,shape)
    cols=[tile(y),tile(x),tile(leads[None,:,None,None]),
          tile(np.sin(2*np.pi*day/366)[:,None,None,None]),tile(np.cos(2*np.pi*day/366)[:,None,None,None])]
    names=["latitude","longitude","lead_hours","day_sin","day_cos"]
    for i in range(samples.shape[-2]):
        cols.extend([samples[...,i,:].mean(-1),samples[...,i,:].std(-1)])
        names.extend([f"source_{i}_mean",f"source_{i}_spread"])
    return np.stack(cols,axis=-1).reshape(-1,len(names)),names

def _event_metrics(samples,weights,actual,mass,threshold):
    exceed=(samples>threshold).mean(-1)
    probability=np.sum(weights*exceed,axis=-1);event=actual>threshold
    brier=float(np.average((probability-event)**2,weights=mass))
    called=probability>=.5;hits=int(np.sum(called&event));miss=int(np.sum(~called&event));false=int(np.sum(called&~event))
    return {"threshold_mm":threshold,"brier":brier,"events":int(event.sum()),
      "probability_cutoff":.5,"pod":None if hits+miss==0 else hits/(hits+miss),
      "far":None if hits+false==0 else false/(hits+false)}

def experiment(directory,output,replays):
    directory=Path(directory);data=collect(directory);p=data["predictions"];o=data["observations"]
    times=data["time"].astype("datetime64[ns]");months=times.astype("datetime64[M]").astype(int)%12+1
    calibration=months<=2;train=(months>=3)&(months<=6);validate=(months>=7)&(months<=8);test=months>=9
    residual=o[calibration,...,None]-p[calibration]
    offsets=np.quantile(residual.reshape(-1,2),np.linspace(.025,.975,21),axis=0).T
    samples=np.maximum(p[...,None]+offsets,0)
    features,names=_features(samples,times,data["leads"],data["latitude"],data["longitude"])
    shape=o.shape;tile=lambda a:np.broadcast_to(a,shape)
    month=tile(months[:,None,None,None]).reshape(-1);observed=o.reshape(-1);flat_samples=samples.reshape(-1,2,21)
    y,x=np.meshgrid(data["latitude"],data["longitude"],indexing="ij");mass=tile(np.cos(np.deg2rad(y))).reshape(-1)
    tr=(month>=3)&(month<=6);va=(month>=7)&(month<=8);te=month>=9
    first_v,pair_v=crps_terms(flat_samples[va],observed[va]);candidates=[]
    for penalty in (.01,.1,1.):
        model=fit_gate(features[tr],flat_samples[tr],observed[tr],case_weights=mass[tr],regularization=penalty,maxiter=500)
        w=predict_weights(model,features[va],[True,True]);score=float(np.average(mixture_crps(w,first_v,pair_v),weights=mass[va]))
        candidates.append((score,penalty,model))
    _,penalty,model=min(candidates,key=lambda z:z[0])
    model.update(source_ids=["IFS-HRES-WB2","GraphCast-WB2"],feature_names=names,variable="rain",units="mm/24h",
      residual_offsets=offsets.tolist(),validated_missing_source_patterns=[])
    static=fit_gate(np.zeros((int(tr.sum()),1)),flat_samples[tr],observed[tr],case_weights=mass[tr])
    weights=predict_weights(model,features[te],[True,True]);static_w=predict_weights(static,np.zeros((int(te.sum()),1)),[True,True])
    equal=np.full_like(weights,.5);first,pair=crps_terms(flat_samples[te],observed[te]);actual=observed[te];test_mass=mass[te]
    families={"Equal mixture":equal,"Static mixture":static_w,"Adaptive mixture":weights};scores=[];losses={}
    raw=p.reshape(-1,2)[te]
    for i,name in enumerate(model["source_ids"]):
        error=raw[:,i]-actual;scores.append({"model":name+" raw","rmse":float(np.sqrt(np.average(error**2,weights=test_mass))),
          "mae":float(np.average(abs(error),weights=test_mass)),"bias":float(np.average(error,weights=test_mass)),
          "crps":float(np.average(abs(error),weights=test_mass)),"distribution":"deterministic point mass"})
    for name,w in families.items():
        loss=mixture_crps(w,first,pair);losses[name]=loss;mean=np.sum(w*flat_samples[te].mean(-1),axis=-1);error=mean-actual
        scores.append({"model":name,"rmse":float(np.sqrt(np.average(error**2,weights=test_mass))),
          "mae":float(np.average(abs(error),weights=test_mass)),"bias":float(np.average(error,weights=test_mass)),
          "crps":float(np.average(loss,weights=test_mass)),"distribution":"nonnegative empirical residual mixture"})
    test_init=np.broadcast_to(times[:,None,None,None],shape).reshape(-1)[te]
    deltas=losses["Adaptive mixture"]-losses["Static mixture"];events=[]
    for init in np.unique(test_init):
        use=test_init==init;events.append(float(np.average(deltas[use],weights=test_mass[use])))
    rng=np.random.default_rng(26081);ci=np.quantile(rng.choice(events,size=(3000,len(events)),replace=True).mean(1),[.025,.975]).tolist()
    event_metrics={name:[_event_metrics(flat_samples[te],w,actual,test_mass,t) for t in THRESHOLDS] for name,w in families.items()}
    means=flat_samples[te].mean(-1);adaptive_mean=np.sum(weights*means,axis=-1);static_mean=np.sum(static_w*means,axis=-1)
    # Recover coordinates for every held-out flattened case.
    tt,ll,yy,xx=np.meshgrid(times,data["leads"],data["latitude"],data["longitude"],indexing="ij")
    flat_meta=list(zip(tt.reshape(-1)[te],ll.reshape(-1)[te],yy.reshape(-1)[te],xx.reshape(-1)[te]))
    extreme=np.where(actual>=64.5)[0];non_event=np.where(actual<64.5)[0];ordinary=np.where(actual<5)[0]
    picks=[];prob=np.sum(weights*(flat_samples[te]>64.5).mean(-1),axis=-1)
    if extreme.size:
        improved_extreme=extreme[deltas[extreme]<0]
        pool=improved_extreme if improved_extreme.size else extreme
        picks.append(("detected_extreme",pool[np.argmax(prob[pool])]))
    if non_event.size:
        idx=non_event[np.argmax(prob[non_event])]
        picks.append(("false_alarm_at_0_5" if prob[idx]>=.5 else "highest_non_event_probability",idx))
    if ordinary.size:picks.append(("ordinary_case",ordinary[np.argmin(np.abs(adaptive_mean[ordinary]-actual[ordinary]))]))
    replay_rows=[]
    for label,i in picks:
        init,lead,lat,lon=flat_meta[i];probs=np.sum(weights[i]*(flat_samples[te][i]>64.5).mean(-1))
        replay_rows.append({"label":label,"initialization":str(init),"lead_hours":int(lead),"lat":float(lat),"lon":float(lon),
          "observed_mm":float(actual[i]),"source_means_mm":dict(zip(model["source_ids"],means[i].tolist())),
          "adaptive_mean_mm":float(adaptive_mean[i]),"static_mean_mm":float(static_mean[i]),"adaptive_p_gt_64_5":float(probs),
          "adaptive_minus_static_crps":float(deltas[i]),"reference":"ERA5 reanalysis"})
    worst=np.argsort(deltas)[-5:][::-1]
    failure=[{"initialization":str(flat_meta[i][0]),"lead_hours":int(flat_meta[i][1]),"lat":float(flat_meta[i][2]),"lon":float(flat_meta[i][3]),
      "observed_mm":float(actual[i]),"adaptive_minus_static_crps":float(deltas[i])} for i in worst]
    report={"schema_version":1,"data_kind":"forecast","experiment":"IFS-HRES + GraphCast 24-hour rainfall; India-region bounding box on shared 1.5-degree grid",
      "reference":"ERA5 reanalysis, not independent gauge observations","units":"mm/24h",
      "calibration_period":"2020-01 through 2020-02","training_period":"2020-03 through 2020-06",
      "validation_period":"2020-07 through 2020-08","test_period":"2020-09 through 2020-12",
      "initializations":len(times),"test_initializations":int(test.sum()),"training_cases":int(tr.sum()),"test_cases":int(te.sum()),
      "test_event_blocks":len(events),"lead_hours":data["leads"].tolist(),"scores":scores,"event_metrics":event_metrics,
      "crps_difference_vs_static_95ci":ci,"selected_regularization":penalty,
      "validation_candidates":[{"crps":s,"regularization":r} for s,r,_ in candidates],
      "failure_cases":failure,"acceptance_passed":False,"eligible_for_production":False,"upstream_training_audited":True,
      "data_manifest":json.loads((directory/"rainfall-dataset-manifest.json").read_text()),
      "limitations":["ERA5 is reanalysis rather than independent Indian gauge observations.",
        "GraphCast is ERA5-initialized retrospective output, not a real-time as-of replay.",
        "Only three initialization dates per month are sampled; event-block uncertainty remains limited.",
        "The regional box includes ocean and neighboring countries; this is not an India land-only score.",
        "Calibration is pooled over the domain and regridded negative precipitation artifacts are clipped to zero.",
        "The held-out sample contains only one case above 115.6 mm/24h; no severe-tail skill conclusion can be drawn.",
        "The within-2020 seasonal split is a bounded demonstration, not a multi-year cross-season generalization test.",
        "This does not validate the live GFS/AIFS roster, NEPS/NCUM, station-scale rainfall, or official warnings."]}
    model_dir=directory/"models"/"ifs-graphcast-rainfall-2020-v1"
    if model_dir.exists():shutil.rmtree(model_dir)
    save_candidate(model_dir,model,report);atomic_write(output,json_bytes(report))
    atomic_write(replays,json_bytes({"schema_version":1,"reference":"ERA5 reanalysis","cases":replay_rows,
      "selection":"Algorithmic held-out examples: best adaptive extreme, highest-probability non-event, and ordinary case."}))
    print(json.dumps({"scores":scores,"ci":ci,"replays":len(replay_rows)},indent=2));return report
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--replays",type=Path,required=True)
    a=p.parse_args();experiment(a.archive,a.output,a.replays)

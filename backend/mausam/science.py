"""Distribution mixtures, calibration, and verification. No forecast score is hard-coded."""
import numpy as np

class NoEligibleSources(ValueError):
    pass

def masked_softmax(logits, available):
    logits=np.asarray(logits,dtype=float); available=np.asarray(available,dtype=bool)
    if logits.shape!=available.shape or not np.isfinite(logits[available]).all():
        raise ValueError('Invalid weights or availability shape')
    if not available.any(axis=-1).all():
        raise NoEligibleSources('Publication withheld: no eligible forecast source')
    scores=np.where(available,logits,-np.inf)
    weights=np.exp(scores-np.max(scores,axis=-1,keepdims=True))
    return weights/weights.sum(axis=-1,keepdims=True)

def mixture(samples, weights, threshold):
    """samples: sources x members. Weights apply to SOURCES, regardless of member counts."""
    weights=np.asarray(weights,dtype=float)
    if len(samples)!=len(weights) or np.any(weights<0) or not np.isfinite(weights).all() or not np.isclose(weights.sum(),1):
        raise ValueError('Source weights must be nonnegative and sum to one')
    vals=[]; masses=[]
    for s,w in zip(samples,weights):
        s=np.asarray(s,dtype=float); s=s[np.isfinite(s)]
        if w>0 and len(s)==0: raise ValueError('Eligible source has no finite members')
        if w>0:
            vals.extend(s.tolist());masses.extend([w/len(s)]*len(s))
    vals=np.asarray(vals); masses=np.asarray(masses)
    order=np.argsort(vals);vals=vals[order];masses=masses[order];cdf=np.cumsum(masses)
    quantile=lambda q: float(vals[min(np.searchsorted(cdf,q),len(vals)-1)])
    return {'mean':float(np.dot(vals,masses)), 'median':quantile(.5), 'p10':quantile(.1), 'p90':quantile(.9),
            'probability':float(masses[vals>threshold].sum()),'samples':vals,'mass':masses}

def crps(samples,weights,observation):
    x=np.asarray(samples,dtype=float);w=np.asarray(weights,dtype=float)
    if not np.isclose(w.sum(),1): raise ValueError('Invalid CRPS masses')
    # O(n log n), equivalent to E|X-y| - 0.5 E|X-X'|.
    order=np.argsort(x);x=x[order];w=w[order]
    preceding=np.cumsum(w)-w
    return float(np.dot(w,np.abs(x-observation))-np.dot(w*x,2*preceding+w-1))

def verification(prediction,observation,probability,threshold):
    p=np.asarray(prediction);o=np.asarray(observation);q=np.asarray(probability)
    if p.shape!=o.shape or q.shape!=o.shape or len(p)==0:raise ValueError('Paired verification arrays required')
    mask=np.isfinite(p)&np.isfinite(o)&np.isfinite(q);p=p[mask];o=o[mask];q=q[mask]
    if len(p)==0:raise ValueError('No valid verification pairs')
    event=o>threshold; warned=q>=.5;hits=int(np.sum(event&warned)); misses=int(np.sum(event&~warned));false=int(np.sum(~event&warned))
    return {'n':len(p),'rmse':float(np.sqrt(np.mean((p-o)**2))),'mae':float(np.mean(np.abs(p-o))),
            'bias':float(np.mean(p-o)),'brier':float(np.mean((q-event)**2)),
            'csi':hits/(hits+misses+false) if hits+misses+false else None,
            'pod':hits/(hits+misses) if hits+misses else None,'far':false/(hits+false) if hits+false else None,
            'hits':hits,'misses':misses,'false_alarms':false}

def reliability(probability,event,bins=10):
    probability=np.asarray(probability);event=np.asarray(event);out=[]
    for i in range(bins):
        mask=(probability>=i/bins)&((probability<(i+1)/bins) if i<bins-1 else (probability<=1))
        out.append({'bin':(i+.5)/bins,'n':int(mask.sum()),'forecast':float(probability[mask].mean()) if mask.any() else None,'observed':float(event[mask].mean()) if mask.any() else None})
    return out

def blocked_bootstrap_difference(errors_a,errors_b,event_ids,seed=42,repetitions=500):
    a=np.asarray(errors_a);b=np.asarray(errors_b);groups=np.asarray(event_ids);unique=np.unique(groups);rng=np.random.default_rng(seed)
    if len(unique)<2:raise ValueError('At least two independent event blocks required')
    delta=[]
    for _ in range(repetitions):
        indexes=np.concatenate([np.flatnonzero(groups==g) for g in rng.choice(unique,len(unique),replace=True)])
        delta.append(float(a[indexes].mean()-b[indexes].mean()))
    return np.quantile(delta,[.025,.975]).tolist()

class ResidualCalibration:
    """Empirical residual distribution fitted on an earlier, separate calibration period."""
    def fit(self,predictions,observations):
        p=np.asarray(predictions,dtype=float);o=np.asarray(observations,dtype=float)
        if p.shape!=o.shape or p.ndim!=1 or len(p)<30 or not np.isfinite(p).all() or not np.isfinite(o).all():raise ValueError('At least 30 valid paired calibration cases required')
        self.residuals=np.quantile(o-p,np.linspace(.005,.995,101));return self
    def predict(self,mean,nonnegative=False):
        samples=np.asarray(mean)[...,None]+self.residuals
        return np.maximum(0,samples) if nonnegative else samples

def blend_wind_components(u_members,v_members,weights,speed_threshold):
    """Shared source weights for u/v; speed probability from paired member vectors."""
    if len(u_members)!=len(v_members):raise ValueError('Paired vector sources required')
    speeds=[]
    for u,v in zip(u_members,v_members):
        u=np.asarray(u);v=np.asarray(v)
        if u.shape!=v.shape:raise ValueError('Paired wind members must align')
        speeds.append(np.hypot(u,v))
    return {'u':sum(w*np.mean(u) for w,u in zip(weights,u_members)),
            'v':sum(w*np.mean(v) for w,v in zip(weights,v_members)),
            'speed_distribution':mixture(speeds,weights,speed_threshold)}

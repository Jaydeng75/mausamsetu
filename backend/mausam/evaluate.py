"""Chronological baseline evaluation for an operator-supplied point-case archive.

NPZ contract: predictions [case,source], observations [case], valid_end [case]
(epoch seconds), event_id [case]. Split boundaries are explicit UTC timestamps.
"""
import argparse,json
from datetime import datetime
from pathlib import Path
import numpy as np
from .science import ResidualCalibration,mixture,crps,verification,blocked_bootstrap_difference

def evaluate(path,calibration_end,test_start,threshold,nonnegative=True):
    d=np.load(path,allow_pickle=False);p=d['predictions'];o=d['observations'];times=d['valid_end'];events=d['event_id']
    if p.ndim!=2 or len(o)!=len(p) or len(times)!=len(p) or len(events)!=len(p):raise ValueError('Archive dimensions disagree')
    before=datetime.fromisoformat(calibration_end);after=datetime.fromisoformat(test_start)
    if before.tzinfo is None or after.tzinfo is None or before>=after:raise ValueError('Ordered, timezone-aware split dates required')
    cal=times<=before.timestamp();test=times>=after.timestamp()
    if cal.sum()<30 or test.sum()<10:raise ValueError('Insufficient calibration or test cases')
    if set(events[cal])&set(events[test]):raise ValueError('Weather events cross the calibration/test boundary')
    # A gap between supplied boundaries must account for the longest accumulation window.
    models=[ResidualCalibration().fit(p[cal,i],o[cal]) for i in range(p.shape[1])]
    distributions=[m.predict(p[test,i],nonnegative) for i,m in enumerate(models)]
    names=[f'source_{i+1}' for i in range(p.shape[1])]+['equal_mixture'];scores={};cases=[]
    for row,y in enumerate(o[test]):
        source_samples=[s[row] for s in distributions];pairs={}
        for i,name in enumerate(names):
            w=np.ones(p.shape[1])/p.shape[1] if name=='equal_mixture' else np.eye(p.shape[1])[i]
            result=mixture(source_samples,w,threshold);pairs[name]={k:result[k] for k in ['mean','p10','p90','probability']};pairs[name]['crps']=crps(result['samples'],result['mass'],y)
        cases.append({'event_id':str(events[test][row]),'observation':float(y),'models':pairs})
    for name in names:
        preds=[r['models'][name] for r in cases];scores[name]={**verification([r['mean'] for r in preds],o[test],[r['probability'] for r in preds],threshold),'crps':float(np.mean([r['crps'] for r in preds])),'p10_p90_coverage':float(np.mean([(r['p10']<=y<=r['p90']) for r,y in zip(preds,o[test])]))}
    return {'status':'evaluation_only_not_approved','calibration_cases':int(cal.sum()),'test_cases':int(test.sum()),'calibration_end':calibration_end,'test_start':test_start,'threshold':threshold,'scores':scores,'cases':cases}
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('archive');a.add_argument('--calibration-end',required=True);a.add_argument('--test-start',required=True);a.add_argument('--threshold',type=float,required=True);a.add_argument('--allow-negative',action='store_true');a.add_argument('--output',required=True);v=a.parse_args();report=evaluate(v.archive,v.calibration_end,v.test_start,v.threshold,not v.allow_negative);Path(v.output).write_text(json.dumps(report,indent=2));print(json.dumps(report['scores'],indent=2))

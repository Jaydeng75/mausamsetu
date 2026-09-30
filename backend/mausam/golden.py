"""Generate a small canonical, aligned synthetic dataset and immutable demonstration product."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,hashlib
import numpy as np
from .pipeline import publish_aligned

def generate(root):
    root=Path(root);inputs=root/'golden';inputs.mkdir(parents=True,exist_ok=True)
    lat=np.arange(8,37,1.0);lon=np.arange(68,98,1.0);xx,yy=np.meshgrid(lon,lat);rng=np.random.default_rng(26081)
    field=2+80*np.exp(-((xx-81)**2/15+(yy-14)**2/16));sources=[];init=datetime(2026,9,26,tzinfo=timezone.utc)
    for i,name in enumerate(['NEPS','AIFS','NCUM','GFS']):
        samples=np.maximum(0,field[None,...]+rng.normal(i*3,10+i*3,(21,len(lat),len(lon))));file=inputs/f'{name}.npy';np.save(file,samples)
        meta=dict(source_id=name,upstream_model_version='synthetic-v1',initialization_time_utc=init.isoformat(),provider_publication_time=(init+timedelta(hours=1)).isoformat(),ingested_at=(init+timedelta(hours=1,minutes=5)).isoformat(),valid_start_time=(init+timedelta(hours=48)).isoformat(),valid_end_time=(init+timedelta(hours=72)).isoformat(),lead_time=72,variable='rain',units='mm',vertical_level_or_height='surface',grid_id='synthetic-india-1deg-v1',quality_flags=[],file_checksum=hashlib.sha256(file.read_bytes()).hexdigest(),licence_reference='CC0 synthetic fixture',data_kind='synthetic')
        sources.append({'file':file.name,'metadata':meta,'required_members':21,'logit':[1.5,1.2,.9,.2][i]})
    config={'run_id':'golden-20260926-00-v1','decision_time':(init+timedelta(hours=2)).isoformat(),'variable':'rain','threshold':64.5,'model':{'version':'synthetic-static-v1','method':'static','approved':True,'approval_scope':'synthetic testing only'},'lat':lat.tolist(),'lon':lon.tolist(),'sources':sources}
    path=inputs/'manifest.json';path.write_text(json.dumps(config,indent=2));return publish_aligned(path,root)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--archive',default='./data');args=p.parse_args();print(json.dumps(generate(args.archive),indent=2))

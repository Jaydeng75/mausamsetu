"""Restricted research ingestion: never writes to the site's public assets."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .public_data import write_json


def tigge_request(date, cycle, forecast_type, members=None):
    init = datetime.strptime(date, '%Y-%m-%d').replace(hour=cycle,tzinfo=timezone.utc)
    if init > datetime.now(timezone.utc)-timedelta(hours=48):
        raise ValueError('TIGGE has a 48-hour access delay')
    if cycle not in (0,12) or forecast_type not in ('cf','pf'):
        raise ValueError('NCMRWF TIGGE requires an explicitly selected control or perturbed forecast')
    request = {'class':'ti','date':date,'expver':'prod','origin':'dems','levtype':'sfc',
        'param':'167/165/166/151/228228','step':'0/to/168/by/6', 'time':f'{cycle:02}:00:00',
        'type':forecast_type,'grid':'1/1','area':'38/65/5/100'}
    if forecast_type == 'pf':
        if not members or any(not isinstance(n,int) or n<1 for n in members):
            raise ValueError('Specify the historical member roster; do not assume the present ensemble size')
        request['number']='/'.join(map(str,members))
    return request


def inventory_grib(path):
    from eccodes import codes_grib_new_from_file,codes_get,codes_release
    rows=[]
    with open(path,'rb') as f:
        while (g:=codes_grib_new_from_file(f)) is not None:
            try:
                def get(key):
                    try:return codes_get(g,key)
                    except Exception:return None
                rows.append({k:get(k) for k in ['centre','subCentre','shortName','paramId','units','dataDate','dataTime','startStep','endStep','typeOfLevel','level','perturbationNumber','typeOfEnsembleForecast','numberOfForecastsInEnsemble','generatingProcessIdentifier','tablesVersion','localTablesVersion','gridType','Ni','Nj']})
            finally:codes_release(g)
    if not rows:raise ValueError('No GRIB records')
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--cycle',type=int,default=0)
    p.add_argument('--members',required=True,help='Comma-separated roster verified for this date')
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    # A caller must deliberately choose non-public storage for these research-only data.
    if 'public' in args.output.resolve().parts:raise ValueError('TIGGE research data cannot be written to public assets')
    token=os.environ.get('ECDS_API_KEY')
    if not token:raise RuntimeError('Set ECDS_API_KEY locally after accepting the TIGGE licence; browser login alone does not configure the Python client')
    import cdsapi
    client=cdsapi.Client(url='https://ecds.ecmwf.int/api',key=token,quiet=True)
    args.output.mkdir(parents=True,exist_ok=True)
    members=[int(n) for n in args.members.split(',')]
    products=[]
    for kind in ('cf','pf'):
        req=tigge_request(args.date,args.cycle,kind,members)
        target=args.output/f'neps-{args.date}-{args.cycle:02}-{kind}.grib2'
        temp=target.with_suffix('.part')
        client.retrieve('tigge-forecasts',req,str(temp))
        records=inventory_grib(temp)
        seen={r['perturbationNumber'] for r in records}
        if kind=='pf' and seen!=set(members):raise ValueError('Returned member roster does not match the requested roster')
        temp.replace(target)
        products.append({'path':target.name,'request':req,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'records':records})
    write_json(args.output/'manifest.json',{'provider':'NCMRWF via TIGGE/ECDS','data_kind':'forecast','distribution':'research_only_no_external_redistribution',
        'licence':'https://apps.ecmwf.int/datasets/licences/tigge/','retrieved_at':datetime.now(timezone.utc).isoformat(),'products':products})


if __name__=='__main__':main()

import os,json,uuid,hashlib,logging,time
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from functools import lru_cache
from fastapi import FastAPI,HTTPException,Depends,Header,Query,Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,JSONResponse
from sqlalchemy import select,text
from prometheus_client import Counter,CollectorRegistry,generate_latest,CONTENT_TYPE_LATEST
from .storage import Archive,database,Record
from .contracts import ReviewInput,PromotionInput,ReplayInput
import jwt

ROOT=Path(os.getenv('MAUSAM_DATA_DIR','./data'));ROOT.mkdir(parents=True,exist_ok=True)
archive=Archive(ROOT);Session=database(os.getenv('DATABASE_URL',f'sqlite:///{ROOT}/metadata.db'))
def check_environment():
    if os.getenv('MAUSAM_ENV','development') != 'production':return
    from urllib.parse import urlparse
    if os.getenv('MAUSAM_ALLOW_ANONYMOUS_READ','false')=='true':
        raise RuntimeError('Production requires authenticated institutional reads')
    external=os.getenv('MAUSAM_EXTERNAL_URL','')
    parsed=urlparse(external)
    if parsed.scheme!='https' or not parsed.hostname or parsed.hostname in {'localhost','127.0.0.1'}:
        raise RuntimeError('Production external URL must be an institutional HTTPS origin')
    for key in ['OIDC_ISSUER','OIDC_JWKS_URL']:
        value=os.getenv(key,'');parsed_oidc=urlparse(value)
        if parsed_oidc.scheme!='https' or not parsed_oidc.hostname:
            raise RuntimeError('Production OIDC requires configured HTTPS endpoints')
    if not os.getenv('OIDC_AUDIENCE'):raise RuntimeError('Production OIDC audience is required')
    algorithm=os.getenv('OIDC_ALGORITHM','RS256')
    if algorithm not in {'RS256','PS256'}:raise RuntimeError('Production OIDC algorithm must be RS256 or PS256')
    try:max_age=int(os.getenv('OIDC_MAX_TOKEN_AGE_SECONDS','3600'))
    except ValueError:raise RuntimeError('OIDC max token age must be an integer')
    if not 300<=max_age<=86400:raise RuntimeError('OIDC max token age must be between 300 and 86400 seconds')
    claim=os.getenv('OIDC_ROLES_CLAIM','realm_access.roles')
    if not claim or any(not part.replace('_','').isalnum() for part in claim.split('.')):
        raise RuntimeError('OIDC roles claim path is invalid')
    origins=[origin.strip() for origin in os.getenv('CORS_ORIGINS','').split(',') if origin.strip()]
    if not origins:raise RuntimeError('Production CORS origins are required')
    if '*' in origins or any(urlparse(origin).scheme!='https' or not urlparse(origin).hostname for origin in origins):
        raise RuntimeError('Production CORS must use explicit HTTPS origins')
    expected=f'{urlparse(external).scheme}://{urlparse(external).netloc}'
    if expected not in origins:raise RuntimeError('Production external origin must be present in CORS origins')
    database=os.getenv('DATABASE_URL','')
    if not database.startswith('postgresql') or 'local-development-only' in database:
        raise RuntimeError('Production requires configured PostgreSQL with non-development credentials')

@asynccontextmanager
async def lifespan(app):
    check_environment()
    yield

app=FastAPI(lifespan=lifespan,title='MausamSetu',version='0.2.0',description='Versioned experimental forecast products. No implicit live-data fallback.')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:3000').split(','),allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])
REGISTRY=CollectorRegistry()
REQUESTS=Counter('mausam_api_requests','API request count',['method','status'],registry=REGISTRY)
@app.middleware('http')
async def monitor(request,call_next):
    request_id=str(uuid.uuid4())
    if request.method in ['POST','PUT','PATCH']:
        length=request.headers.get('content-length')
        if length is None:return JSONResponse({'detail':'Content-Length required','request_id':request_id},status_code=411)
        try:size=int(length)
        except ValueError:return JSONResponse({'detail':'Invalid Content-Length'},status_code=400)
        if size<0 or size>16384:return JSONResponse({'detail':'Request body too large'},status_code=413)
    try:
        response=await call_next(request)
    except Exception:
        logging.getLogger('mausam.api').exception('Request failed: %s',request_id)
        response=JSONResponse({'detail':'Service failure; reference request_id','request_id':request_id},status_code=503)
    REQUESTS.labels(request.method,response.status_code).inc()
    response.headers['X-Request-ID']=request_id
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy']="default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if os.getenv('MAUSAM_ENV','development')=='production':
        response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    response.headers['Cache-Control']='no-store'
    return response

@lru_cache
def jwks_client():return jwt.PyJWKClient(os.environ['OIDC_JWKS_URL'])

def _claim_path(claims,path):
    value=claims
    for part in path.split('.'):
        if not isinstance(value,dict) or part not in value:return None
        value=value[part]
    return value

def identity(authorization:str=Header(default='')):
    if not os.getenv('OIDC_ISSUER'):
        if os.getenv('MAUSAM_ALLOW_ANONYMOUS_READ','false')=='true':return {'sub':'anonymous','roles':['viewer']}
        raise HTTPException(503,'Identity provider not configured')
    try:
        if not authorization.startswith('Bearer '):raise ValueError('Bearer token required')
        token=authorization[7:]
        key=jwks_client().get_signing_key_from_jwt(token).key
        algorithm=os.getenv('OIDC_ALGORITHM','RS256')
        claims=jwt.decode(token,key,algorithms=[algorithm],audience=os.environ['OIDC_AUDIENCE'],
            issuer=os.environ['OIDC_ISSUER'],options={'require':['exp','iat','sub','iss','aud']})
        now=int(time.time());iat=int(claims['iat']);max_age=int(os.getenv('OIDC_MAX_TOKEN_AGE_SECONDS','3600'))
        if iat>now+60 or now-iat>max_age:raise ValueError('Token issuance time outside permitted age')
        roles=_claim_path(claims,os.getenv('OIDC_ROLES_CLAIM','realm_access.roles'))
        if isinstance(roles,str):roles=[roles]
        if not isinstance(roles,list) or not all(isinstance(role,str) for role in roles):
            raise ValueError('OIDC roles claim is not a string list')
        roles=list(dict.fromkeys(roles))
        if not set(roles)&{'viewer','reviewer','approver','admin'}:raise ValueError('No application role')
        return {'sub':claims['sub'],'roles':roles}
    except Exception:raise HTTPException(401,'Valid institutional access token required')

def require(role):
    def check(user=Depends(identity)):
        if role not in user['roles'] and 'admin' not in user['roles']:raise HTTPException(403,f'{role} role required')
        return user
    return check

def record(kind,payload,identifier=None):
    identifier=identifier or str(uuid.uuid4())
    with Session.begin() as db:db.add(Record(id=identifier,kind=kind,payload=json.dumps(payload)))
    return {'id':identifier,**payload}

def manifest(run_id):
    if not run_id.replace('-','').replace('_','').isalnum():raise HTTPException(400,'Invalid run ID')
    p=ROOT/'published'/run_id/'manifest.json'
    if not p.exists():raise HTTPException(404,'Published run not found')
    try:return archive.verify(run_id)
    except (ValueError,OSError):raise HTTPException(503,'Published product integrity check failed')

@app.get('/health')
def health():return {'status':'ok','latest_run':(archive.latest() or {}).get('run_id')}
@app.get('/metrics')
def metrics(user=Depends(require('admin'))):return Response(generate_latest(REGISTRY),media_type=CONTENT_TYPE_LATEST)
@app.get('/v1/runs/latest')
def latest(user=Depends(identity)):
    run=archive.latest()
    if not run:raise HTTPException(404,'No published forecast; run the ingestion and publication worker')
    return run
@app.get('/v1/runs/{run_id}')
def get_run(run_id:str,user=Depends(identity)):return manifest(run_id)
@app.get('/v1/forecast/point')
def point(run_id:str,lat:float=Query(ge=5,le=38),lng:float=Query(ge=65,le=100),user=Depends(identity)):
    import xarray as xr
    meta=manifest(run_id)
    with xr.open_dataset(ROOT/'published'/run_id/'forecast.nc',engine='scipy') as ds:
        if not(float(ds.lat.min())<=lat<=float(ds.lat.max()) and float(ds.lon.min())<=lng<=float(ds.lon.max())):raise HTTPException(404,'Point outside product grid')
        cell=ds.sel(lat=lat,lon=lng,method='nearest')
        return {'run_id':run_id,'requested':{'lat':lat,'lng':lng},'grid_cell':{'lat':float(cell.lat),'lng':float(cell.lon)},'spatial_interpretation':'nearest native grid cell','variable':meta['variable'],'quality':meta['quality'],'data_kind':meta['data_kind'],'model_version':meta['model']['version'],'valid_start':ds.attrs['valid_start'],'valid_end':ds.attrs['valid_end'],'units':ds.attrs['units'],**{k:float(cell[k]) for k in ['mean','median','p10','p90','probability']},'weights':dict(zip(ds.source.values.tolist(),cell.source_weights.values.tolist()))}
@app.get('/v1/weights/point')
def weights(run_id:str,lat:float=Query(ge=5,le=38),lng:float=Query(ge=65,le=100),user=Depends(identity)):
    result=point(run_id,lat,lng,user);return {k:result[k] for k in ['run_id','weights','grid_cell','model_version','quality']}
@app.get('/v1/forecast/region')
def region(run_id:str,south:float,north:float,west:float,east:float,user=Depends(identity)):
    import xarray as xr
    meta=manifest(run_id)
    if not(5<=south<north<=38 and 65<=west<east<=100):raise HTTPException(422,'Invalid region bounds')
    with xr.open_dataset(ROOT/'published'/run_id/'forecast.nc',engine='scipy') as ds:
        subset=ds.where((ds.lat>=south)&(ds.lat<=north)&(ds.lon>=west)&(ds.lon<=east),drop=True)
        if not subset.lat.size or not subset.lon.size:raise HTTPException(404,'No grid cells in region')
        import numpy as np
        area=np.cos(np.deg2rad(subset.lat));return {'run_id':run_id,'mean':float(subset['mean'].weighted(area).mean()),'units':ds.attrs['units'],'spatial_interpretation':'area-weighted mean of grid-cell central forecasts within bounding box','regional_extreme_probability':None,'quality':meta['quality']}
@app.get('/v1/products/{run_id}/download')
def download(run_id:str,user=Depends(identity)):
    manifest(run_id);return FileResponse(ROOT/'published'/run_id/'forecast.nc',media_type='application/x-netcdf',filename=f'{run_id}.nc')
@app.get('/v1/verification')
def scores(variable:str='rain',region:str='all',user=Depends(identity)):
    p=ROOT/'verification.json'
    if not p.exists():raise HTTPException(404,'No verified observation pairs have been published')
    data=json.loads(p.read_text());return {**data,'rows':[r for r in data['rows'] if r['variable']==variable and (region=='all' or r['region']==region)]}
@app.post('/v1/reviews',status_code=201)
def review(body:ReviewInput,user=Depends(require('reviewer'))):
    manifest(body.run_id)
    if body.status=='approved' and not any(r in user['roles'] for r in ['approver','admin']):raise HTTPException(403,'Approval role required')
    data={**body.model_dump(),'author':user['sub'],'created_at':datetime.now(timezone.utc).isoformat()};result=record('review',data);record('audit',{'action':'review_created','review_id':result['id'],'actor':user['sub']});return result
@app.get('/v1/reviews')
def reviews(run_id:str,user=Depends(identity)):
    with Session() as db:return [{'id':r.id,**json.loads(r.payload)} for r in db.scalars(select(Record).where(Record.kind=='review')) if json.loads(r.payload)['run_id']==run_id]
@app.post('/v1/replay-jobs',status_code=202)
def replay(body:ReplayInput,user=Depends(require('reviewer'))):
    m=manifest(body.run_id)
    if body.as_of.tzinfo is None:raise HTTPException(422,'as_of requires a timezone')
    if datetime.fromisoformat(m['published_at'])>body.as_of:raise HTTPException(409,'Forecast was not available at the replay decision time')
    return record('replay',{'status':'queued','run_id':body.run_id,'as_of':body.as_of.isoformat(),'requested_by':user['sub']})
@app.get('/v1/replay-jobs/{job_id}')
def replay_status(job_id:str,user=Depends(identity)):
    with Session() as db:
        r=db.get(Record,job_id)
        if not r or r.kind!='replay':raise HTTPException(404,'Job not found')
        payload=json.loads(r.payload)
        if payload.get('requested_by')!=user['sub'] and 'admin' not in user['roles']:raise HTTPException(403,'Replay belongs to another user')
        return {'id':r.id,**payload}
@app.post('/v1/model-promotions',status_code=201)
def promote(body:PromotionInput,user=Depends(require('approver'))):
    from .registry import activate
    try:event=activate(ROOT,body.version,user['sub'],body.reason)
    except FileNotFoundError:raise HTTPException(404,'Candidate model not found')
    except ValueError as error:raise HTTPException(409,str(error))
    return record('promotion',event,event['event_id'])

@app.get('/health/live')
def live():
    return {'status':'ok','service':'mausamsetu','version':'0.2.0'}

@app.get('/health/ready')
def readiness(response:Response):
    checks={}
    try:
        with Session() as db:db.execute(text('SELECT 1'))
        checks['database']=True
    except Exception:checks['database']=False
    try:
        current=archive.latest()
        checks['published_product']=bool(current)
        if current:archive.verify(current['run_id'])
        checks['integrity']=bool(current)
    except Exception:
        current=None;checks['integrity']=False;checks['published_product']=False
    ready=all(checks.values())
    if not ready:response.status_code=503
    return {'ready':ready,'checks':checks,'run_id':current['run_id'] if current else None,
            'publication_status':'experimental','scientific_acceptance':'external_review_required'}

@app.get('/v1/operations')
def operations(user=Depends(identity)):
    path=ROOT/'operations.json'
    if not path.exists():return {'state':'not_started','message':'No refresh worker has reported a cycle'}
    return json.loads(path.read_text())

@app.get('/v1/models/active')
def active_model(user=Depends(identity)):
    path=ROOT/'models'/'active.json'
    if not path.exists():raise HTTPException(404,'No production model has been approved')
    return json.loads(path.read_text())

@app.get('/public/products/{name}')
def public_product(name:str):
    """Optional public projection: only explicitly public GFS/AIFS-style assets."""
    import re
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':raise HTTPException(404,'Public projection disabled')
    allowed_pointer=name in {'latest.json','global-latest.json'}
    allowed_asset=bool(re.fullmatch(r'(?:public|global)-[0-9]{8}-[0-9]{2}-[a-f0-9]{12}\.json',name))
    if not allowed_pointer and not allowed_asset:
        raise HTTPException(404,'Unknown public asset')
    base=Path(os.getenv('MAUSAM_PUBLIC_DIR',str(ROOT/'public')));path=base/name
    if not path.is_file() or path.is_symlink():raise HTTPException(404,'Public asset unavailable')
    if path.stat().st_size>32000000:raise HTTPException(503,'Public asset exceeds size bound')
    try:
        if name in {'latest.json','global-latest.json'}:
            from .refresh import checked_pointer
            checked_pointer(base,name)
        else:
            product=json.loads(path.read_text())
            if product.get('data_kind')!='forecast' or product.get('calibrated') is not False:
                raise ValueError('Public projection requires an uncalibrated forecast')
            coverage=product.get('coverage','india')
            if coverage not in {'india','global'}:
                raise ValueError('Unsupported public coverage')
            expected='global' if name.startswith('global-') else 'india'
            if coverage!=expected:
                raise ValueError('Public asset coverage does not match its filename')
            if not product.get('sources') or not set(product['sources']) <= {'GFS','AIFS','IFS','GEFS'}:
                raise ValueError('Institutional/restricted sources are not public projections')
            if 'GEFS' in product['sources']:
                context=product.get('ensemble_context',{}).get('GEFS',{})
                if product.get('source_roles',{}).get('GEFS')!='ensemble_mean' or not isinstance(context.get('member_count'),int) or context['member_count']<2 or context.get('member_count_source')!='GRIB numberOfForecastsInEnsemble':
                    raise ValueError('GEFS ensemble metadata is invalid')
    except (ValueError,OSError,KeyError):raise HTTPException(503,'Public asset validation failed')
    return FileResponse(path,media_type='application/json')

@app.post('/v1/model-rollbacks',status_code=201)
def rollback(body:PromotionInput,user=Depends(require('approver'))):
    from .registry import activate
    approval=ROOT/'models'/'approvals'/(body.version+'.json')
    if not body.version.replace('-','').replace('_','').replace('.','').isalnum() or '..' in body.version:
        raise HTTPException(400,'Invalid model version')
    if not approval.exists():raise HTTPException(409,'Rollback requires a previously approved version')
    try:event=activate(ROOT,body.version,user['sub'],'Rollback: '+body.reason)
    except (ValueError,FileNotFoundError):raise HTTPException(409,'Rollback artifact no longer passes approval integrity checks')
    return record('rollback',event,event['event_id'])

@app.get('/public/status')
def public_status():
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':raise HTTPException(404,'Public projection disabled')
    path=Path(os.getenv('MAUSAM_PUBLIC_DIR',str(ROOT/'public')))/'operations.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>65536:
        raise HTTPException(503,'No current operational status')
    result=json.loads(path.read_text())
    if result.get('schema_version')!=1:raise HTTPException(503,'Unsupported status schema')
    global_pointer=Path(os.getenv('MAUSAM_PUBLIC_DIR',str(ROOT/'public')))/'global-latest.json'
    if global_pointer.exists():
        try:
            from .refresh import checked_pointer
            _,global_product=checked_pointer(global_pointer.parent,'global-latest.json')
            result['global_forecast']={'state':'available','run_id':global_product['run_id'],'initialization':global_product['initialization'],'sources':global_product.get('source_status',{}),'leads':global_product.get('leads',[])}
        except (OSError,ValueError,KeyError):result['global_forecast']={'state':'invalid'}
    else:result['global_forecast']={'state':'not_published'}
    from .operational_health import apply_health
    return apply_health(result)

@app.get('/public/rain-verification')
def public_rain_verification():
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':
        raise HTTPException(404,'Public projection disabled')
    path=Path(os.getenv('MAUSAM_PUBLIC_DIR',str(ROOT/'public')))/'rain-verification-index.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>2_000_000:
        raise HTTPException(503,'No rainfall verification index')
    result=json.loads(path.read_text())
    if result.get('schema_version')!=1 or not isinstance(result.get('rows'),list):
        raise HTTPException(503,'Unsupported rainfall verification schema')
    allowed={'noaa-cmorph2-nrt-025','nasa-imerg-early-gis-v07'}
    if any(row.get('reference_id') not in allowed for row in result['rows']):
        raise HTTPException(503,'Unexpected rainfall reference')
    return result

@app.get('/public/shadow-rain')
def public_shadow_rain():
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':
        raise HTTPException(404,'Public projection disabled')
    path=Path(os.getenv('MAUSAM_PUBLIC_DIR',str(ROOT/'public')))/'shadow-rain-status.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>2_000_000:
        raise HTTPException(503,'No shadow-rain status')
    result=json.loads(path.read_text())
    if result.get('schema_version')!=1 or result.get('state') not in {'collecting','shadow_candidate'}:
        raise HTTPException(503,'Unsupported shadow-rain status')
    return result

@app.get('/public/shadow-rain/point')
def public_shadow_rain_point(lat:float,lng:float,lead:int=24):
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':
        raise HTTPException(404,'Public projection disabled')
    if not (-90<=lat<=90 and -180<=lng<=180) or lead<0 or lead>384:
        raise HTTPException(400,'Invalid location or lead')
    path=ROOT/'shadow-rain'/'latest-shadow.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>32_000_000:
        raise HTTPException(503,'No shadow forecast is available')
    try:
        result=json.loads(path.read_text())
        if result.get('schema_version')!=1 or result.get('data_kind')!='shadow_forecast':
            raise ValueError('Unsupported shadow schema')
        if result.get('production_active') is not False or result.get('calibrated') is not False:
            raise ValueError('Shadow boundary changed')
        initialization=datetime.fromisoformat(result['initialization'].replace('Z','+00:00'))
        if initialization.tzinfo is None or initialization.astimezone(timezone.utc).hour!=0:
            raise ValueError('Shadow inference cycle is outside the trained domain')
        latitudes=result['latitude'];longitudes=result['longitude'];key=str(lead)
        if key not in result.get('leads',{}):
            raise HTTPException(404,'Shadow model is not trained for this lead')
        yi=min(range(len(latitudes)),key=lambda i:abs(latitudes[i]-lat))
        longitude=((lng+180)%360)-180
        xi=min(range(len(longitudes)),key=lambda i:abs((((longitudes[i]-longitude)+180)%360)-180))
        index=yi*len(longitudes)+xi
        data=result['leads'][key]
        mean=data['mean_mm'][index]
        if mean is None:
            raise HTTPException(503,'Shadow value withheld at this grid point')
        weights={source:data['weights'][source][index] for source in result['source_ids']}
        if any(value is None for value in weights.values()):
            raise HTTPException(503,'Shadow weights withheld at this grid point')
        return {'run_id':result['run_id'],'initialization':result['initialization'],'lead_hours':lead,
          'grid':{'lat':latitudes[yi],'lng':longitudes[xi]},'mean_mm':mean,'weights':weights,
          'exceedance_mass_64_5mm':data['exceedance_mass_64.5mm'][index],
          'exceedance_mass_115_6mm':data['exceedance_mass_115.6mm'][index],
          'calibrated':False,'production_active':False,'input_kind':result['input_kind'],
          'reference_used_for_training':result['reference_used_for_training']}
    except HTTPException:
        raise
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        raise HTTPException(503,'Shadow forecast validation failed')


@app.get('/public/multi-shadow')
def public_multi_shadow():
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':
        raise HTTPException(404,'Public projection disabled')
    path=Path(os.getenv('MAUSAM_PUBLIC_DIR',str(ROOT/'public')))/'multi-shadow-status.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>8_000_000:
        raise HTTPException(503,'No multi-shadow status')
    result=json.loads(path.read_text())
    if result.get('schema_version')!=1 or result.get('production_active') is not False:
        raise HTTPException(503,'Unsupported multi-shadow status')
    return result


@app.get('/public/multi-shadow/point')
def public_multi_shadow_point(lat:float,lng:float,lead:int=24,variable:str='rain'):
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':
        raise HTTPException(404,'Public projection disabled')
    if variable not in {'rain','temperature','wind'} or lead not in {24,48,72}:
        raise HTTPException(400,'Unsupported multi-shadow variable or lead')
    if not (-90<=lat<=90 and -180<=lng<=180):
        raise HTTPException(400,'Invalid location')
    path=ROOT/'multi-shadow'/'latest.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>32_000_000:
        raise HTTPException(503,'No current multi-shadow forecast')
    try:
        result=json.loads(path.read_text())
        if result.get('schema_version')!=1 or result.get('data_kind')!='multi_shadow_forecast':
            raise ValueError('Unsupported multi-shadow schema')
        if result.get('production_active') is not False or result.get('calibrated') is not False:
            raise ValueError('Multi-shadow boundary changed')
        init=datetime.fromisoformat(result['initialization'].replace('Z','+00:00'))
        if init.tzinfo is None or init.astimezone(timezone.utc).hour!=0:
            raise ValueError('Multi-shadow outside trained cycle')
        data=result.get('leads',{}).get(str(lead),{}).get(variable)
        if not data:raise HTTPException(404,'No trained multi-shadow candidate for this variable/lead')
        latitudes=result['latitude'];longitudes=result['longitude']
        yi=min(range(len(latitudes)),key=lambda i:abs(latitudes[i]-lat))
        longitude=((lng+180)%360)-180
        xi=min(range(len(longitudes)),key=lambda i:abs((((longitudes[i]-longitude)+180)%360)-180))
        index=yi*len(longitudes)+xi
        payload={'run_id':result['run_id'],'initialization':result['initialization'],'lead_hours':lead,
          'variable':variable,'grid':{'lat':latitudes[yi],'lng':longitudes[xi]},
          'weights':{source:data['weights'][source][index] for source in ['GFS','GEFS','IFS','AIFS']},
          'calibrated':False,'production_active':False}
        if variable=='wind':
            payload.update(u=data['u'][index],v=data['v'][index],speed=data['speed'][index])
            if any(payload[name] is None for name in ['u','v','speed']):
                raise HTTPException(503,'Multi-shadow vector withheld at this point')
        else:
            payload['mean']=data['mean'][index]
            if payload['mean'] is None:
                raise HTTPException(503,'Multi-shadow value withheld at this point')
        if any(value is None for value in payload['weights'].values()):
            raise HTTPException(503,'Multi-shadow weights withheld at this point')
        return payload
    except HTTPException:
        raise
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        raise HTTPException(503,'Multi-shadow forecast validation failed')


@app.get('/public/imd-gauge')
def public_imd_gauge():
    if os.getenv('MAUSAM_PUBLIC_PRODUCTS','false')!='true':
        raise HTTPException(404,'Public projection disabled')
    path=Path(os.getenv('MAUSAM_PUBLIC_DIR',str(ROOT/'public')))/'imd-gauge-status.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>8_000_000:
        raise HTTPException(503,'No IMD gauge verification status')
    result=json.loads(path.read_text())
    if result.get('schema_version')!=1 or result.get('state')!='operational_reference_pipeline':
        raise HTTPException(503,'Unsupported IMD gauge status')
    return result

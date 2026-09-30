import type {Variable} from './forecast';
export type GridField = Record<string,(number|null)[]>;
export type PublicProduct = {
 delivery_mode?:'connected_archive'|'packaged_snapshot'|'historical_archive';
 from_cache?:boolean;
 coverage?:'india'|'global';
 forecast_cadence_hours?:number;
 schema_version:number;data_kind:'forecast'|'historical_evaluation';run_id:string;initialization:string;retrieved_at:string;
 leads:number[];latitude:number[];longitude:number[];sources:Record<string,Record<string,GridField>>;
 source_status?:Record<string,string>;source_leads?:Record<string,number[]>;source_roles?:Record<string,'deterministic'|'ensemble_mean'>;
 ensemble_context?:Record<string,{member_count:number;member_count_source?:string;mean_source?:string;spread_source?:string;spread:Record<string,Record<string,(number|null)[]>>;rain_24h_spread:null;rain_spread_note:string}>;
 grid_method:string;attribution:string;calibrated:false;
 initializations?:number;evaluation_start?:string;evaluation_end?:string;reference?:string;
 scores?:{variable:Variable;unit:string;lead:number;rmse:number;mae:number;bias:number;pairs:number;grid_cells:number;initializations:number}[];
};
async function loadNetworkProduct(kind:'india'|'global'|'world',signal:AbortSignal):Promise<PublicProduct>{
 let base='/data/products/';let mode:PublicProduct['delivery_mode']=kind==='world'?'historical_archive':'packaged_snapshot';
 if(kind!=='world'){
  const runtime=await fetch('/api/runtime',{signal,cache:'no-store'});
  if(!runtime.ok)throw Error('Runtime configuration unavailable');
  const config=await runtime.json() as {india_products_base?:unknown;global_products_base?:unknown;mode?:unknown};
  const selected=kind==='global'?config.global_products_base:config.india_products_base;
  if(typeof selected!=='string')throw Error('Invalid product origin');
  if(!['/data/products/','/api/public-products/'].includes(selected)){
   const remote=new URL(selected);
   if(remote.protocol!=='https:'||remote.username||remote.password||remote.pathname!=='/public/products/'||remote.search||remote.hash)throw Error('Invalid product origin');
  }
  base=selected;mode=config.mode==='connected_archive'?'connected_archive':'packaged_snapshot';
 }
 const pointer=kind==='india'?'latest.json':kind==='global'?'global-latest.json':'weatherbench-latest.json';
 const r=await fetch(base+pointer,{signal,cache:'no-cache'});
 if(!r.ok)throw new Error('No published dataset is available.');
 const manifest=await r.json() as {path:string;sha256:string};
 if(!/^[a-zA-Z0-9.-]+\.json$/.test(manifest.path))throw new Error('Invalid product manifest');
 const response=await fetch(base+manifest.path,{signal});if(!response.ok)throw new Error('The published grid could not be loaded.');
 const bytes=await response.arrayBuffer();
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
 if(hash!==manifest.sha256)throw new Error('Product checksum failed.');
 const data=JSON.parse(new TextDecoder().decode(bytes)) as PublicProduct;
 if(data.schema_version!==1||!data.latitude?.length||!data.longitude?.length||!data.leads?.length||!Object.keys(data.sources??{}).length)throw new Error('Unsupported or empty product');
 const n=data.latitude.length*data.longitude.length;
 for(const source of Object.values(data.sources))for(const fields of Object.values(source))for(const values of Object.values(fields))if(values.length!==n||values.some(x=>x!==null&&!Number.isFinite(x)))throw new Error('Invalid grid shape or values');
 validateProduct(data);
 data.delivery_mode=mode;
 return data;
}
export function gridIndex(p:PublicProduct,lat:number,lng:number){
 if(p.data_kind==='forecast'&&p.coverage!=='global'&&(lat<5||lat>38||lng<65||lng>100))return -1;
 const near=(a:number[],v:number)=>a.reduce((best,x,i)=>Math.abs(x-v)<Math.abs(a[best]-v)?i:best,0);
 const longitude=((lng+180)%360+360)%360-180;
 const distance=(a:number,b:number)=>p.data_kind==='historical_evaluation'?Math.min(Math.abs(a-b),360-Math.abs(a-b)):Math.abs(a-b);
 const x=p.longitude.reduce((best,v,i)=>distance(v,longitude)<distance(p.longitude[best],longitude)?i:best,0),y=near(p.latitude,lat);
 return y*p.longitude.length+x;
}
export function fieldValues(p:PublicProduct,source:string,lead:number,variable:Variable):(number|null)[]{
 if(source!=='Equal blend')return p.sources[source]?.[String(lead)]?.[variable]??[];
 const sources=Object.values(p.sources).map(s=>s[String(lead)]).filter(Boolean);
 return Array.from({length:p.latitude.length*p.longitude.length},(_,i)=>{
  if(!sources.length||sources.some(s=>s[variable]?.[i]==null))return null;
  if(variable==='wind'&&sources.every(s=>s.u?.[i]!=null&&s.v?.[i]!=null))return Math.hypot(sources.reduce((a,s)=>a+s.u[i]!,0)/sources.length,sources.reduce((a,s)=>a+s.v[i]!,0)/sources.length);
  return sources.reduce((a,s)=>a+s[variable][i]!,0)/sources.length;
 });
}

export function validateProduct(data:PublicProduct):void {
 const finite=(v:number[])=>Array.isArray(v)&&v.length>0&&v.every(Number.isFinite);
 if(!['forecast','historical_evaluation'].includes(data.data_kind)||data.calibrated!==false)
  throw new Error('Unsupported scientific product type');
 if(data.data_kind==='forecast'&&!['india','global'].includes(data.coverage??'india'))
  throw new Error('Unsupported forecast coverage');
 if(!finite(data.latitude)||!finite(data.longitude)||!finite(data.leads)||
    data.latitude.some(v=>v< -90||v>90)||data.longitude.some(v=>v< -180||v>180)||
    new Set(data.latitude).size!==data.latitude.length||new Set(data.longitude).size!==data.longitude.length||
    new Set(data.leads).size!==data.leads.length||data.leads.some((v,i)=>v<0||!Number.isInteger(v)||(i>0&&v<=data.leads[i-1])))
  throw new Error('Invalid coordinates or forecast leads');
 if(!Number.isFinite(Date.parse(data.initialization))||!Number.isFinite(Date.parse(data.retrieved_at))||!data.attribution)
  throw new Error('Missing time or attribution metadata');
 const n=data.latitude.length*data.longitude.length,covered=new Set<number>();
 for(const [name,source] of Object.entries(data.sources)){
  const sourceLeads=data.source_leads?.[name]??data.leads;
  if(!sourceLeads.length||new Set(sourceLeads).size!==sourceLeads.length||sourceLeads.some(lead=>!data.leads.includes(lead)))
   throw new Error('Invalid source lead roster');
  if(Object.keys(source).some(key=>!sourceLeads.includes(Number(key))))throw new Error('Unexpected source lead');
  for(const lead of sourceLeads){
   const fields=source[String(lead)];if(!fields)throw new Error('Incomplete source lead coverage');covered.add(lead);
   for(const key of ['rain','temperature','wind','pressure']){
    const values=fields[key];
    if(!Array.isArray(values)||values.length!==n||values.some(v=>v!==null&&(!Number.isFinite(v)||((key==='rain'||key==='wind')&&v<0))))
     throw new Error('Invalid or missing numerical field');
   }
  }
 }
 if(data.leads.some(lead=>!covered.has(lead)))throw new Error('Forecast lead has no available source');
 if(data.sources.GEFS&&(data.source_roles?.GEFS!=='ensemble_mean'||!data.ensemble_context?.GEFS))throw new Error('GEFS ensemble metadata missing');
 if(data.ensemble_context)for(const context of Object.values(data.ensemble_context)){
  if(!Number.isInteger(context.member_count)||context.member_count<2||context.member_count_source!=='GRIB numberOfForecastsInEnsemble')throw new Error('Invalid ensemble member count');
  for(const lead of data.leads){const spread=context.spread[String(lead)];if(!spread)throw new Error('Incomplete ensemble spread');
   for(const values of Object.values(spread))if(!Array.isArray(values)||values.length!==n||values.some(v=>v!==null&&(!Number.isFinite(v)||v<0)))throw new Error('Invalid ensemble spread values');}
 }
}
export function forecastAgeHours(data:PublicProduct,now=Date.now()):number {
 return Math.max(0,(now-Date.parse(data.initialization))/3600000);
}

// Only already validated public products are cached. Recheck integrity on restoration.
export async function loadProduct(kind:'india'|'global'|'world',signal:AbortSignal):Promise<PublicProduct>{
 const key='/__mausam_verified_v1/'+kind;
 try{
  const data=await loadNetworkProduct(kind,signal);
  try{const raw=JSON.stringify(data);const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)))).map(x=>x.toString(16).padStart(2,'0')).join('');const cache=await caches.open('mausam-public-v1');await cache.put(key,new Response(JSON.stringify({raw,sha})));}catch{/* Storage may be unavailable; network product remains usable. */}
  return data;
 }catch(error){
  if(signal.aborted)throw error;
  try{const cached=await (await caches.open('mausam-public-v1')).match(key);if(!cached)throw error;
   const stored=await cached.json() as {raw?:unknown;sha?:unknown};if(!stored||typeof stored.raw!=='string'||typeof stored.sha!=='string'||stored.raw.length>32000000||!/^[a-f0-9]{64}$/.test(stored.sha))throw error;const {raw,sha}=stored;const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)))).map(x=>x.toString(16).padStart(2,'0')).join('');if(digest!==sha)throw error;
   const data=JSON.parse(raw) as PublicProduct;validateProduct(data);
   const matches=kind==='world'?data.data_kind==='historical_evaluation':data.data_kind==='forecast'&&(kind==='global'?data.coverage==='global':data.coverage!=='global');
   if(!matches)throw error;return {...data,from_cache:true};
  }catch{throw error;}
 }
}

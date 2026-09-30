'use client';
import {useEffect,useState} from 'react';
import {FlaskConical} from 'lucide-react';

type Variable='rain'|'temperature'|'wind'|'pressure';
type PointData={
 run_id:string;initialization:string;lead_hours:number;variable:'rain'|'temperature'|'wind';
 grid:{lat:number;lng:number};weights:Record<string,number>;mean?:number;u?:number;v?:number;speed?:number;
 calibrated:false;production_active:false;
};
const units:Record<string,string>={rain:'mm / 24h',temperature:'°C',wind:'m/s'};

export default function ShadowPoint({lat,lng,lead,initialization,variable}:{lat:number;lng:number;lead:number;initialization:string;variable:Variable}){
 const[data,setData]=useState<PointData|null>(null),[error,setError]=useState('');
 const cycleHour=new Date(initialization).getUTCHours(),cycleEligible=Number.isFinite(cycleHour)&&cycleHour===0;
 const leadEligible=[24,48,72].includes(lead),variableEligible=variable!=='pressure';
 useEffect(()=>{
  const controller=new AbortController();setData(null);setError('');
  if(!cycleEligible||!leadEligible||!variableEligible)return()=>controller.abort();
  const query=new URLSearchParams({lat:String(lat),lng:String(lng),lead:String(lead),variable});
  fetch('/api/multi-shadow/point?'+query.toString(),{signal:controller.signal,cache:'no-store'}).then(async response=>{
    const value=await response.json() as PointData&{error?:string};
    if(!response.ok||value.production_active!==false||value.calibrated!==false)throw Error(value.error||'Multi-shadow point unavailable');
    setData(value);
  }).catch(e=>{if(!controller.signal.aborted)setError((e as Error).message);});
  return()=>controller.abort();
 },[lat,lng,lead,cycleEligible,leadEligible,variable,variableEligible]);
 return <section className="shadow-point-card">
  <div className="eyebrow"><FlaskConical size={14}/>MULTI-VARIABLE RESEARCH SHADOW · NOT ACTIVE</div>
  {!cycleEligible?<p>Shadow weights are withheld for this {cycleHour.toString().padStart(2,'0')} UTC run. Current candidates are trained on 00 UTC initializations.</p>:
   !leadEligible?<p>Separate candidates are currently trained only for +24, +48 and +72 h. Select one of those leads to inspect shadow weights.</p>:
   !variableEligible?<p>Pressure does not yet have an adaptive shadow candidate.</p>:
   error?<p className="real-warning">{error}</p>:!data?<p>Loading research shadow inference…</p>:<>
    <div className="shadow-point-value">{data.variable==='wind'?(data.speed??NaN).toFixed(1):(data.mean??NaN).toFixed(1)} <span>{units[data.variable]}</span></div>
    {data.variable==='wind'&&<p>Paired vector blend: U {(data.u??NaN).toFixed(1)} m/s · V {(data.v??NaN).toFixed(1)} m/s.</p>}
    <div className="shadow-point-weights">{Object.entries(data.weights).map(([source,weight])=>
     <div key={source}><span>{source}</span><b>{(weight*100).toFixed(1)}%</b></div>)}</div>
    <small>Weights are research-only and are not calibrated source-correctness probabilities. The public equal baseline remains active. Grid {data.grid.lat.toFixed(1)}°, {data.grid.lng.toFixed(1)}°.</small>
   </>}
 </section>;
}

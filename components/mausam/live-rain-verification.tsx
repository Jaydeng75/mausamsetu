'use client';
import {useEffect,useMemo,useState} from 'react';
import {CloudRain,RefreshCw} from 'lucide-react';

type Score={model:string;n:number;rmse:number;mae:number;bias:number};
type Row={verification_id:string;run_id:string;lead_hours:number;valid_start:string;valid_end:string;
 reference_id:string;reference_product:string;reference_kind:string;scores:Score[];limitations:string[]};
type Index={schema_version:number;generated_at:string;policy:string;rows:Row[]};

const utc=(value:string)=>new Date(value).toLocaleString('en-GB',{
 day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'UTC'
})+' UTC';

export default function LiveRainVerification(){
 const[data,setData]=useState<Index|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();
  fetch('/api/rain-verification',{signal:controller.signal,cache:'no-store'}).then(async response=>{
   const value=await response.json() as Index&{error?:string};
   if(!response.ok||value.schema_version!==1||!Array.isArray(value.rows))throw Error(value.error||'Verification unavailable');
   setData(value);setError('');
  }).catch(e=>{if(!controller.signal.aborted)setError((e as Error).message);});
  return()=>controller.abort();
 },[retry]);
 const latest=useMemo(()=>{
  if(!data?.rows.length)return [];
  const end=data.rows[0].valid_end;
  return data.rows.filter(row=>row.valid_end===end);
 },[data]);
 return <section className="readiness-card">
  <div className="readiness-section-title"><h2><CloudRain size={21}/>Near-real-time rainfall verification</h2>
   <button className="real-action" onClick={()=>setRetry(x=>x+1)}><RefreshCw size={14}/>Refresh</button></div>
  <p>Operational forecast grids scored after rainfall estimates arrive. CMORPH and IMERG remain separate satellite references; neither is labelled gauge truth.</p>
  {error&&<p className="real-warning" role="alert">{error}</p>}
  {!data&&!error&&<p>Loading rainfall scorecards…</p>}
  {latest.map(row=><article className="rain-scorecard" key={row.verification_id}>
   <div><strong>{row.reference_product}</strong><span>{row.reference_kind}</span></div>
   <p>Forecast {row.run_id} · +{row.lead_hours}h · {utc(row.valid_start)} → {utc(row.valid_end)}</p>
   <div className="real-score-scroll"><table><thead><tr><th>Forecast</th><th>RMSE ↓</th><th>MAE ↓</th><th>Bias</th><th>Pairs</th></tr></thead>
   <tbody>{row.scores.map(score=><tr key={score.model}><td>{score.model}</td><td>{score.rmse.toFixed(2)} mm</td>
    <td>{score.mae.toFixed(2)} mm</td><td>{score.bias.toFixed(2)} mm</td><td>{score.n.toLocaleString()}</td></tr>)}</tbody></table></div>
  </article>)}
  {data&&!latest.length&&<p>No completed satellite-verification window is available yet.</p>}
  {data&&<p className="fine-print">{data.policy} Index refreshed {utc(data.generated_at)}. These are retrospective checks after the valid period, not inputs available to the original forecast.</p>}
 </section>;
}

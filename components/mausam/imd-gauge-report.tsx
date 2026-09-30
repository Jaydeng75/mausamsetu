'use client';
import {useEffect,useMemo,useState} from 'react';
import {Gauge,RefreshCw} from 'lucide-react';

type Metric={model:string;crps:number;rmse:number;mae:number;bias:number;thresholds?:Record<string,{brier:number;csi:number|null;pod:number|null;far:number|null}>};
type Row={initialization:string;nominal_lead_hours:number;forecast_window_start:string;forecast_window_end:string;collocated_cells:number;scores:Metric[];limitation:string};
type Status={schema_version:number;generated_at:string;state:string;reference_id:string;rows:Row[];policy:string};
const score=(row:Row,name:string)=>row.scores.find(s=>s.model===name);

export default function ImdGaugeReport(){
 const[data,setData]=useState<Status|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{const c=new AbortController();setError('');
  fetch('/api/imd-gauge',{signal:c.signal,cache:'no-store'}).then(async r=>{const d=await r.json() as Status&{error?:string};if(!r.ok||d.schema_version!==1)throw Error(d.error||'IMD gauge verification unavailable');setData(d);})
   .catch(e=>{if(!c.signal.aborted)setError((e as Error).message);});return()=>c.abort();
 },[retry]);
 const rows=useMemo(()=>data?.rows.slice(0,12)??[],[data]);
 return <section className="readiness-card">
  <div className="readiness-section-title"><h2><Gauge size={21}/>IMD gauge-grid exact-window verification</h2>
   <button className="real-action" onClick={()=>setRetry(v=>v+1)}><RefreshCw size={14}/>Refresh</button></div>
  <p>Official IMD 0.25° daily gauge-gridded rainfall. Forecast rainfall is rebuilt for the same 03:00→03:00 UTC 24-hour window before scoring.</p>
  {error&&<p className="real-warning" role="alert">{error}</p>}
  {!data&&!error&&<p>Loading IMD gauge evidence…</p>}
  {data&&<>{!rows.length?<p className="real-warning">Pipeline is configured but no due exact-window verification has completed yet.</p>:
   <div className="real-score-scroll"><table><thead><tr><th>Initialization</th><th>Lead</th><th>Cells</th><th>GFS RMSE</th><th>GEFS RMSE</th><th>IFS RMSE</th><th>AIFS RMSE</th><th>Equal RMSE</th><th>Equal CSI ≥64.5</th><th>Equal CSI ≥115.6</th></tr></thead><tbody>
    {rows.map(row=>{const equal=score(row,'Equal point mixture');return <tr key={row.initialization+row.nominal_lead_hours}><td>{new Date(row.initialization).toISOString().slice(0,10)}</td><td>+{row.nominal_lead_hours}h</td><td>{row.collocated_cells}</td>
     {['GFS','GEFS','IFS','AIFS','Equal point mixture'].map(name=><td key={name}>{score(row,name)?.rmse.toFixed(2)??'—'}</td>)}
     <td>{equal?.thresholds?.['64.5']?.csi?.toFixed(3)??'—'}</td><td>{equal?.thresholds?.['115.6']?.csi?.toFixed(3)??'—'}</td></tr>})}
   </tbody></table></div>}
   <p className="fine-print">{data.policy} IMD is treated as a gauge-gridded analysis, not raw station truth. The 00–00 adaptive gate is not transferred to the 03–03 accumulation window.</p>
  </>}
 </section>;
}

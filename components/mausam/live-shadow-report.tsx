'use client';
import {useEffect,useState} from 'react';
import {FlaskConical,RefreshCw} from 'lucide-react';

type Score={model:string;crps:number;rmse:number;mae:number;bias:number};
type Cross={reference_id:string;test_event_blocks:number;scores:Score[];adaptive_minus_static_crps_95ci:number[]|null};
type Shadow={
 schema_version:number;generated_at:string;state:'collecting'|'shadow_candidate';reference_id:string;
 source_ids:string[];event_blocks:number;bootstrap_event_blocks:number;prospective_event_blocks:number;prospective_start:string|null;matched_windows:number;reason?:string;
 train_event_blocks?:number;selection_event_blocks?:number;test_event_blocks?:number;
 train_cases?:number;selection_cases?:number;test_cases?:number;scores?:Score[];
 adaptive_minus_static_crps_95ci?:number[];cross_reference?:Cross|null;
 acceptance_passed:boolean;evidence_sufficient_for_acceptance?:boolean;limitations:string[];
 acceptance_requirements:{minimum_total_event_blocks:number;minimum_prospective_event_blocks:number;minimum_held_out_event_blocks:number;independent_reference:string};
};
const utc=(v:string)=>new Date(v).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})+' UTC';

export default function LiveShadowReport(){
 const[data,setData]=useState<Shadow|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{const c=new AbortController();setError('');
  fetch('/api/shadow-rain',{signal:c.signal,cache:'no-store'}).then(async r=>{
   const d=await r.json() as Shadow&{error?:string};
   if(!r.ok||d.schema_version!==1)throw Error(d.error||'Shadow status unavailable');
   setData(d);
  }).catch(e=>{if(!c.signal.aborted)setError((e as Error).message);});
  return()=>c.abort();
 },[retry]);
 const provisional=Math.min(100,Math.round(((data?.event_blocks??0)/6)*100));
 const acceptance=Math.min(100,Math.round(((data?.event_blocks??0)/(data?.acceptance_requirements?.minimum_total_event_blocks??30))*100));
 const prospective=Math.min(100,Math.round(((data?.prospective_event_blocks??0)/(data?.acceptance_requirements?.minimum_prospective_event_blocks??10))*100));
 return <section className="readiness-card">
  <div className="readiness-section-title"><h2><FlaskConical size={21}/>Live-roster rainfall shadow blend</h2>
   <button className="real-action" onClick={()=>setRetry(v=>v+1)}><RefreshCw size={14}/>Refresh</button></div>
  <p>Prospective GFS + GEFS + IFS + AIFS rainfall learning. CMORPH is the primary training reference; IMERG is kept as an independent held-out cross-reference. The live public forecast remains unchanged.</p>
  {error&&<p className="real-warning" role="alert">{error}</p>}
  {!data&&!error&&<p>Loading shadow evidence…</p>}
  {data&&<>
   <div className="shadow-progress-grid">
    <article><span>Bootstrap blocks</span><strong>{data.bootstrap_event_blocks}</strong><small>{data.event_blocks} total independent initializations · {data.matched_windows} matched windows</small></article>
    <article><span>Provisional candidate</span><strong>{provisional}%</strong><small>Requires at least 6 total initialization blocks</small></article>
    <article><span>Prospective shadow</span><strong>{prospective}%</strong><small>{data.prospective_event_blocks}/{data.acceptance_requirements.minimum_prospective_event_blocks} blocks initialized after shadow deployment</small></article>
    <article><span>Total acceptance evidence</span><strong>{acceptance}%</strong><small>{data.event_blocks}/{data.acceptance_requirements.minimum_total_event_blocks} blocks, plus held-out improvement on both references</small></article>
   </div>
   {data.state==='collecting'?<div className="readiness-notice"><FlaskConical size={20}/><p><b>Collecting only.</b> {data.reason} No live adaptive forecast has been activated.</p></div>:<>
    <p><b>Chronological split:</b> {data.train_event_blocks} train · {data.selection_event_blocks} selection · {data.test_event_blocks} held-out test blocks.</p>
    <div className="real-score-scroll"><table><thead><tr><th>Held-out CMORPH</th><th>CRPS ↓</th><th>RMSE ↓</th><th>MAE ↓</th><th>Bias</th></tr></thead><tbody>
     {data.scores?.map(s=><tr key={s.model}><td>{s.model}</td><td>{s.crps.toFixed(3)}</td><td>{s.rmse.toFixed(2)}</td><td>{s.mae.toFixed(2)}</td><td>{s.bias.toFixed(2)}</td></tr>)}
    </tbody></table></div>
    {data.adaptive_minus_static_crps_95ci&&<p className="fine-print">CMORPH adaptive − static CRPS 95% initialization-block interval: [{data.adaptive_minus_static_crps_95ci[0].toFixed(3)}, {data.adaptive_minus_static_crps_95ci[1].toFixed(3)}]. An interval crossing zero is not treated as evidence of consistent improvement.</p>}
    {data.cross_reference&&<><p><b>Independent IMERG check:</b> {data.cross_reference.test_event_blocks} held-out blocks.</p>
     <div className="real-score-scroll"><table><thead><tr><th>Held-out IMERG</th><th>CRPS ↓</th><th>RMSE ↓</th><th>MAE ↓</th></tr></thead><tbody>
      {data.cross_reference.scores.map(s=><tr key={s.model}><td>{s.model}</td><td>{s.crps.toFixed(3)}</td><td>{s.rmse.toFixed(2)}</td><td>{s.mae.toFixed(2)}</td></tr>)}
     </tbody></table></div>
     {data.cross_reference.adaptive_minus_static_crps_95ci&&<p className="fine-print">IMERG adaptive − static CRPS 95% initialization-block interval: [{data.cross_reference.adaptive_minus_static_crps_95ci[0].toFixed(3)}, {data.cross_reference.adaptive_minus_static_crps_95ci[1].toFixed(3)}].</p>}</>}
    <p className={data.acceptance_passed?'fine-print':'real-warning'}>{data.acceptance_passed?'Research acceptance criteria passed; institutional review is still required.':'Production acceptance has not passed. The shadow model cannot replace the live baseline.'}</p>
   </>}
   <p className="fine-print">Generated {utc(data.generated_at)}. {data.prospective_start&&<>Prospective counting starts {utc(data.prospective_start)}. </>}Source-point mixture weights and exceedance masses are not calibrated probabilities. Satellite references remain separate.</p>
  </>}
 </section>;
}

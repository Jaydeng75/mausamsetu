'use client';
import {useEffect,useMemo,useState} from 'react';
import {Activity,RefreshCw} from 'lucide-react';

type Score={model:string;crps?:number;energy_score?:number;rmse?:number;vector_rmse?:number;mae?:number;speed_mae?:number};
type Missing={missing:string[];bootstrap_pass:boolean;acceptance_pass:boolean;adaptive_minus_equal_95ci:number[]|null};
type Extreme={threshold_mm:number;event_blocks_with_observed_event:number;minimum_event_blocks:number;support_pass:boolean;skill_pass:boolean;acceptance_pass:boolean};
type Report={
 state:string;variable:string;lead:number;event_blocks:number;bootstrap_event_blocks:number;prospective_event_blocks:number;
 train_event_blocks?:number;selection_event_blocks?:number;test_event_blocks?:number;acceptance_passed:boolean;
 numerical_gate_passed?:boolean;scores?:Score[];adaptive_minus_static_95ci?:number[]|null;
 missing_source_matrix?:Missing[];missing_source_gate_passed?:boolean;
 extreme_event_evidence?:Record<string,Extreme>|null;extreme_event_gate_passed?:boolean;
 reference_limitation?:string;cross_reference?:unknown;
};
type Status={schema_version:number;generated_at:string;prospective_start:string;production_active:false;
 summary:{candidate_models:number;production_accepted_models:number;missing_source_patterns_tested_per_candidate:number;production_note:string};
 variables:Record<string,Record<string,Report>>;
};
const label=(v:string)=>v==='rain'?'Rainfall':v==='temperature'?'2 m temperature':'10 m wind U/V';
const metric=(r:Report,name:string)=>{const row=r.scores?.find(s=>s.model===name);return row?(row.crps??row.energy_score):undefined;};

export default function MultiShadowReport(){
 const[data,setData]=useState<Status|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{const c=new AbortController();setError('');
  fetch('/api/multi-shadow',{signal:c.signal,cache:'no-store'}).then(async r=>{const d=await r.json() as Status&{error?:string};if(!r.ok||d.schema_version!==1)throw Error(d.error||'Multi-shadow status unavailable');setData(d);})
   .catch(e=>{if(!c.signal.aborted)setError((e as Error).message);});return()=>c.abort();
 },[retry]);
 const rows=useMemo(()=>data?Object.entries(data.variables).flatMap(([variable,leads])=>Object.values(leads).map(report=>({variable,report}))):[],[data]);
 return <section className="readiness-card">
  <div className="readiness-section-title"><h2><Activity size={21}/>Multi-variable shadow acceptance matrix</h2>
   <button className="real-action" onClick={()=>setRetry(v=>v+1)}><RefreshCw size={14}/>Refresh</button></div>
  <p>Exact live roster: GFS + GEFS ensemble mean + IFS + AIFS. Separate candidates are trained for +24, +48 and +72 h. Wind uses one shared source-weight gate for paired U/V vectors.</p>
  {error&&<p className="real-warning" role="alert">{error}</p>}
  {!data&&!error&&<p>Loading multi-variable evidence…</p>}
  {data&&<>
   <div className="shadow-progress-grid">
    <article><span>Candidate slots</span><strong>{data.summary.candidate_models}/9</strong><small>rain · temperature · wind × 3 leads</small></article>
    <article><span>Production accepted</span><strong>{data.summary.production_accepted_models}</strong><small>Automatic promotion remains disabled</small></article>
    <article><span>Outage patterns</span><strong>{data.summary.missing_source_patterns_tested_per_candidate}</strong><small>4 single-source + 6 two-source patterns</small></article>
    <article><span>Prospective clock</span><strong>{new Date(data.prospective_start).toLocaleDateString()}</strong><small>Backfill never increments prospective evidence</small></article>
   </div>
   <div className="real-score-scroll"><table><thead><tr><th>Candidate</th><th>Blocks</th><th>Prospective</th><th>Held-out</th><th>Static</th><th>Adaptive</th><th>95% Δ interval</th><th>Outage gate</th><th>Extreme gate</th><th>Status</th></tr></thead><tbody>
    {rows.map(({variable,report})=>{
      const scalar=variable!=='wind',stat=metric(report,scalar?'Static point mixture':'Static vector mixture'),adapt=metric(report,scalar?'Adaptive point mixture':'Adaptive vector mixture');
      const pass=report.missing_source_matrix?.filter(row=>row.acceptance_pass).length??0,ci=report.adaptive_minus_static_95ci;
      return <tr key={variable+report.lead}><td>{label(variable)} · +{report.lead}h</td><td>{report.event_blocks}</td><td>{report.prospective_event_blocks}</td><td>{report.test_event_blocks??'—'}</td>
       <td>{stat?.toFixed(3)??'—'}</td><td>{adapt?.toFixed(3)??'—'}</td><td>{ci?'['+ci[0].toFixed(3)+', '+ci[1].toFixed(3)+']':'—'}</td>
       <td>{report.missing_source_matrix?(report.missing_source_gate_passed?'PASS':pass+'/10'):'—'}</td>
       <td>{variable==='rain'?(report.extreme_event_gate_passed?'PASS':report.extreme_event_evidence?Object.values(report.extreme_event_evidence).filter(row=>row.acceptance_pass).length+'/3':'—'):'n/a'}</td>
       <td>{report.acceptance_passed?'accepted':report.numerical_gate_passed?'review required':report.state.replaceAll('_',' ')}</td></tr>;
    })}
   </tbody></table></div>
   <p className="fine-print">Rainfall is checked against CMORPH and independently against IMERG. Its extreme gate requires held-out support at 64.5, 115.6 and 204.5 mm/24 h. The outage gate evaluates all four single-source and six two-source failures and enforces both skill-vs-equal and degradation limits. Temperature and wind use delayed ERA5-family reanalysis, so even a numerical gate pass still requires independent observational review.</p>
  </>}
 </section>;
}

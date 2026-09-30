'use client';
import {useEffect,useState} from 'react';
type Score={model:string;rmse:number;mae:number;bias:number;crps:number};
type Report={schema_version:number;experiment:string;reference:string;units:string;initializations:number;
 training_cases:number;test_cases:number;test_initializations:number;test_event_blocks:number;
 calibration_years:number[];training_years:number[];validation_years:number[];test_years:number[];
 scores:Score[];limitations:string[];eligible_for_production:boolean;crps_difference_vs_static_95ci:number[]};
export default function BenchmarkReport(){
 const[data,setData]=useState<Report|null>(null),[missing,setMissing]=useState(false);
 useEffect(()=>{const c=new AbortController();fetch('/data/learned-benchmark.json',{signal:c.signal,cache:'no-store'})
  .then(r=>{if(!r.ok)throw Error('No completed report');return r.json();})
  .then(d=>{const value=d as Report;if(value.schema_version!==1||!value.scores?.length)throw Error('Invalid report');setData(value);})
  .catch(()=>{if(!c.signal.aborted)setMissing(true);});return()=>c.abort();},[]);
 return <section className="readiness-card"><h2>Real-data adaptive-blend experiment</h2>
 {!data&&<p>{missing?'No completed scientific experiment report is published. No forecast-improvement claim is being made.':'Loading recorded experiment…'}</p>}
 {data&&<><p><b>{data.experiment}</b></p><p>{data.reference}. Units: {data.units}.</p>
 <p>Calibration: {data.calibration_years.join(', ')} · Gate training: {data.training_years.join(', ')} · Model selection: {data.validation_years.join(', ')} · Held-out test: {data.test_years.join(', ')}</p>
 <p>{data.initializations} initialization dates · {data.training_cases.toLocaleString()} training grid/lead cases · {data.test_cases.toLocaleString()} held-out cases from {data.test_initializations} initialization dates.</p>
 <div className="real-score-scroll"><table><thead><tr><th>Model / distribution</th><th>RMSE</th><th>MAE</th><th>CRPS</th><th>Bias</th></tr></thead>
 <tbody>{data.scores.map(s=><tr key={s.model}><td>{s.model}</td><td>{s.rmse.toFixed(3)}</td><td>{s.mae.toFixed(3)}</td><td>{s.crps.toFixed(3)}</td><td>{s.bias.toFixed(3)}</td></tr>)}</tbody></table></div>
 <p>Adaptive minus static CRPS, 95% interval using {data.test_event_blocks} monthly blocks: {data.crps_difference_vs_static_95ci.map(n=>n.toFixed(3)).join(' to ')}. Lower CRPS is better. {data.crps_difference_vs_static_95ci[1]<0?'This experiment supports lower CRPS for the adaptive mixture under this evaluation setup.':'This interval does not establish lower CRPS for the adaptive mixture.'}</p>
 <p className="real-warning">Research candidate only. These IFS/Pangu weights are not used for live GFS/AIFS forecasts.</p>
 {data.limitations.map(text=><p className="fine-print" key={text}>{text}</p>)}
 <a className="real-action" href="/data/learned-benchmark.json" download="mausamsetu-research-evaluation.json">Export complete evaluation</a></>}
 </section>;
}

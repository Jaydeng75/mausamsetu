'use client';
import {useEffect,useState} from 'react';
type Score={model:string;rmse:number;mae:number;bias:number;crps:number};
type EventMetric={threshold_mm:number;brier:number;events:number;pod:number|null;far:number|null};
type Failure={initialization:string;lead_hours:number;lat:number;lon:number;observed_mm:number;adaptive_minus_static_crps:number};
type Report={schema_version:number;experiment:string;reference:string;units:string;calibration_period:string;training_period:string;
 validation_period:string;test_period:string;initializations:number;test_initializations:number;training_cases:number;test_cases:number;
 test_event_blocks:number;scores:Score[];event_metrics:Record<string,EventMetric[]>;crps_difference_vs_static_95ci:number[];
 failure_cases:Failure[];limitations:string[]};
type Replay={label:string;initialization:string;lead_hours:number;lat:number;lon:number;observed_mm:number;
 adaptive_mean_mm:number;static_mean_mm:number;adaptive_p_gt_64_5:number;adaptive_minus_static_crps:number};
export default function RainfallReport(){
 const[data,setData]=useState<Report|null>(null),[cases,setCases]=useState<Replay[]>([]),[missing,setMissing]=useState(false);
 useEffect(()=>{const c=new AbortController();Promise.all([
  fetch('/data/rainfall-benchmark.json',{signal:c.signal,cache:'no-store'}).then(r=>{if(!r.ok)throw Error();return r.json();}),
  fetch('/data/rainfall-replays.json',{signal:c.signal,cache:'no-store'}).then(r=>{if(!r.ok)throw Error();return r.json();})
 ]).then(([a,b])=>{setData(a as Report);setCases((b as {cases:Replay[]}).cases||[]);}).catch(()=>{if(!c.signal.aborted)setMissing(true);});
 return()=>c.abort();},[]);
 return <section className="readiness-card"><h2>Real-data rainfall blend & replay</h2>
 {!data&&<p>{missing?'Rainfall benchmark has not completed; no rainfall-improvement claim is published.':'Loading rainfall research result…'}</p>}
 {data&&<><p><b>{data.experiment}</b></p><p>{data.reference}. Units: {data.units}.</p>
 <p>Calibration {data.calibration_period} · gate training {data.training_period} · model selection {data.validation_period} · held-out test {data.test_period}.</p>
 <p>{data.initializations} initialization dates · {data.training_cases.toLocaleString()} training cases · {data.test_cases.toLocaleString()} held-out cases from {data.test_initializations} initializations.</p>
 <div className="real-score-scroll"><table><thead><tr><th>Model / distribution</th><th>RMSE</th><th>MAE</th><th>CRPS</th><th>Bias</th></tr></thead>
 <tbody>{data.scores.map(s=><tr key={s.model}><td>{s.model}</td><td>{s.rmse.toFixed(2)}</td><td>{s.mae.toFixed(2)}</td><td>{s.crps.toFixed(2)}</td><td>{s.bias.toFixed(2)}</td></tr>)}</tbody></table></div>
 <p>Adaptive minus static CRPS, 95% initialization-block bootstrap interval: {data.crps_difference_vs_static_95ci.map(x=>x.toFixed(3)).join(' to ')}.
  {data.crps_difference_vs_static_95ci[1]<0?' This experiment supports lower CRPS for the adaptive blend.':' This experiment does not establish lower CRPS for the adaptive blend.'}</p>
 <h3>Fixed rainfall-event diagnostics</h3><div className="real-score-scroll"><table><thead><tr><th>Blend</th><th>Threshold</th><th>Events</th><th>Brier</th><th>POD @ 0.5</th><th>FAR @ 0.5</th></tr></thead><tbody>
 {Object.entries(data.event_metrics).flatMap(([name,rows])=>rows.map(r=><tr key={name+r.threshold_mm}><td>{name}</td><td>{r.threshold_mm} mm</td><td>{r.events}</td><td>{r.brier.toFixed(3)}</td><td>{r.pod==null?'—':r.pod.toFixed(2)}</td><td>{r.far==null?'—':r.far.toFixed(2)}</td></tr>))}</tbody></table></div>
 <h3>Held-out replay cases</h3>{cases.map(c=><div className="readiness-check" key={c.label}><div><b>{c.label.replaceAll('_',' ')}</b>
  <p>{c.initialization.slice(0,10)} · +{c.lead_hours}h · {c.lat.toFixed(1)}°, {c.lon.toFixed(1)}° · observed {c.observed_mm.toFixed(1)} mm · adaptive {c.adaptive_mean_mm.toFixed(1)} mm</p>
  <p className="fine-print">P(&gt;64.5 mm) {Math.round(c.adaptive_p_gt_64_5*100)}% · adaptive − static CRPS {c.adaptive_minus_static_crps.toFixed(2)}</p></div></div>)}
 <h3>Where adaptive blending failed</h3>{data.failure_cases.slice(0,3).map((f,i)=><p className="fine-print" key={i}>
  {f.initialization.slice(0,10)} +{f.lead_hours}h at {f.lat.toFixed(1)}°, {f.lon.toFixed(1)}°: adaptive CRPS worse by {f.adaptive_minus_static_crps.toFixed(2)}; observed {f.observed_mm.toFixed(1)} mm.
 </p>)}
 <p className="real-warning">Research candidate only. These IFS/GraphCast weights are not used for live GFS/AIFS forecasts.</p>
 {data.limitations.map(x=><p className="fine-print" key={x}>{x}</p>)}
 <a className="real-action" href="/data/rainfall-benchmark.json" download="mausamsetu-rainfall-evaluation.json">Export rainfall evaluation</a></>}
 </section>;
}

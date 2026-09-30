'use client';
import MosdacContext from '@/components/mausam/mosdac-context';
import {useEffect,useState} from 'react';
import {ArrowLeft,Download,ShieldCheck,Waypoints} from 'lucide-react';
import './readiness.css';
import ServiceStatus from '@/components/mausam/service-status';
import BenchmarkReport from '@/components/mausam/benchmark-report';
import LiveRainVerification from '@/components/mausam/live-rain-verification';
import LiveShadowReport from '@/components/mausam/live-shadow-report';
import MultiShadowReport from '@/components/mausam/multi-shadow-report';
import ImdGaugeReport from '@/components/mausam/imd-gauge-report';
import SourceReadiness from '@/components/mausam/source-readiness';
import RainfallReport from '@/components/mausam/rainfall-report';
type Check={name:string;status:string;detail?:string};
type Evidence={generated_at:string;revision:string;checks:Check[];production_gates:Check[]};
export default function Readiness(){
 const[evidence,setEvidence]=useState<Evidence|null>(null),[error,setError]=useState('');
 useEffect(()=>{const c=new AbortController();fetch('/data/release-status.json',{signal:c.signal,cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Release evidence unavailable');return r.json();}).then(d=>setEvidence(d as Evidence)).catch(e=>{if(!c.signal.aborted)setError(e.message);});return()=>c.abort();},[]);
 const download=()=>{if(!evidence)return;const u=URL.createObjectURL(new Blob([JSON.stringify(evidence,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='mausamsetu-release-evidence.json';a.click();URL.revokeObjectURL(u);};
 return <main className="readiness-page">
 <header><a className="brand" href="/"><Waypoints/><span>Mausam<span className="brand-accent">Setu</span><small>FORECAST INTELLIGENCE</small></span></a><a className="real-action" href="/preparedness">Preparedness resources</a><a className="real-action" href="/"><ArrowLeft size={16}/>Forecast workbench</a></header>
 <div className="readiness-content"><div className="eyebrow">SIH26081 · RELEASE EVIDENCE</div>
 <h1>Forecast fusion.<br/><span>Every claim inspectable.</span></h1>
 <p className="readiness-intro">A forecast blending and verification workbench for meteorologists. Explore what is implemented, what has been tested, and what still requires scientific or institutional acceptance.</p>
 <div className="readiness-notice"><ShieldCheck size={22}/><p><b>Experimental research deployment.</b> No official warnings, operational approval, or India-wide accuracy advantage is implied.</p></div>
 <div className="readiness-actions"><a href="/" className="readiness-primary">Open forecast workbench</a><button className="real-action" disabled={!evidence} onClick={download}><Download size={16}/>Export evidence</button></div>
 <div className="readiness-columns"><section><h2>Real numerical data</h2><p>Live GFS, GEFS ensemble mean/spread, IFS and AIFS products with exact initialization, lead times, checksums and source-quality flags. The displayed equal blend is a deterministic baseline, not calibrated AI guidance.</p></section>
 <section><h2>Learned blending</h2><p>A trainable context-dependent gate, distribution mixtures, per-grid source weights and checksum-pinned model approval. Synthetic testing cannot authorize a production forecast.</p></section>
 <section><h2>Scientific separation</h2><p>The synthetic demo and WeatherBench reference evaluation remain labeled separately. Model contribution is not the probability that a source is correct.</p></section></div>
 <ServiceStatus/><MosdacContext/><SourceReadiness/><BenchmarkReport/><RainfallReport/><LiveRainVerification/><ImdGaugeReport/><LiveShadowReport/><MultiShadowReport/><section className="readiness-card"><h2>Executed release checks</h2>{error&&<p role="alert">{error}</p>}{!evidence&&!error&&<p>Loading recorded evidence…</p>}
 {evidence?.checks.map(c=><div className="readiness-check" key={c.name}><div><b>{c.name}</b><p>{c.detail}</p></div><span className={'readiness-chip '+c.status}>{c.status.replaceAll('_',' ')}</span></div>)}
 {evidence&&<p className="fine-print">Recorded {new Date(evidence.generated_at).toLocaleString()} · {evidence.revision}. Recorded checks are not continuous operational monitoring.</p>}</section>
 <section className="readiness-card"><h2>Remaining production acceptance gates</h2>{evidence?.production_gates.map(c=><div className="readiness-check" key={c.name}><div><b>{c.name}</b><p>{c.detail}</p></div><span className="readiness-chip blocked">{c.status.replaceAll('_',' ')}</span></div>)}</section>
 <section className="readiness-card"><h2>SIH demonstration sequence</h2><ol><li>Inspect a real India or global grid cell, source values, valid interval and forecast age.</li><li>Compare GFS, GEFS ensemble mean, IFS and AIFS with the explicitly labeled equal-weight baseline.</li><li>Show separate CMORPH and IMERG rainfall scorecards, then the learned-gate tests and recorded release evidence.</li><li>Use the labeled synthetic demo to demonstrate weights, uncertainty, replay and extreme-guidance interactions.</li><li>Explain the remaining data access and scientific acceptance gates without claiming they are complete.</li></ol></section>
 <footer>MausamSetu · India-first, globally extensible · Experimental guidance only</footer>
 </div></main>;
}

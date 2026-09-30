'use client';
import {useEffect,useState} from 'react';
type Provider={name:string;role:string;status:string;note?:string;dataset_id?:string;latest_identifier?:string;
 latest_valid_interval?:string;dataset_count?:number;datasets?:string[];delay_hours?:number;numerical_files?:number;
 year?:number;product?:string;units?:string;http_status?:number;retrieved_at?:string|null};
type Status={schema_version:number;checked_at:string;providers:Provider[];policy:string;rules?:string[]};
const label=(s:string)=>s.replaceAll('_',' ');
const positive=(s:string)=>/(ready|reachable|staged)$/.test(s)||s.includes('sample_ready');
export default function SourceReadiness(){
 const[data,setData]=useState<Status|null>(null),[error,setError]=useState('');
 useEffect(()=>{const c=new AbortController();fetch('/data/india-source-status.json',{signal:c.signal,cache:'no-store'})
  .then(r=>{if(!r.ok)throw Error('India provider probe is unavailable');return r.json();})
  .then(v=>setData(v as Status)).catch(e=>{if(!c.signal.aborted)setError((e as Error).message);});return()=>c.abort();},[]);
 return <section className="readiness-card"><h2>India data-source readiness</h2>
  <p>Provider reachability, credentials, historical archives and local research access are tracked separately from forecast skill.</p>
  {error&&<p role="alert">{error}</p>}{!data&&!error&&<p>Loading provider evidence…</p>}
  {data?.providers.filter(p=>p.name!=='MOSDAC').map(p=><div className="readiness-check" key={p.name}><div><b>{p.name}</b>
   <p>{label(p.role)}{p.dataset_id?' · '+p.dataset_id:''}{p.year?' · '+p.year:''}{p.delay_hours?' · '+p.delay_hours+' h delayed':''}</p>
   {p.latest_identifier&&<p className="fine-print">Latest catalogue item: {p.latest_identifier}{p.latest_valid_interval?' · '+p.latest_valid_interval:''}</p>}
   {p.datasets?.length?<p className="fine-print">Active selected datasets: {p.datasets.join(', ')}</p>:null}
   {p.product&&<p className="fine-print">{p.product}{p.units?' · '+p.units:''}</p>}{p.note&&<p className="fine-print">{p.note}</p>}</div>
   <span className={'readiness-chip '+(positive(p.status)?'passed':'blocked')}>{label(p.status)}</span></div>)}
  {data&&<p className="fine-print">Checked {new Date(data.checked_at).toLocaleString()}. {data.policy}</p>}
 </section>;
}

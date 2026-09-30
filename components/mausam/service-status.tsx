'use client';
import {useEffect,useState} from 'react';
type State={status:string;checked_at?:string;run_id?:string;forecast_age_hours?:number;disk_free_gb?:number;
 sources?:Record<string,string>;backend?:{ready:boolean};backup?:{status:string;created_at?:string};
 global_forecast?:{state:string;run_id?:string;forecast_age_hours?:number;sources?:Record<string,string>};
 refresh?:{state:string};alert_delivery?:string;alerts?:{code:string;severity:string;message:string}[];message?:string};
export default function ServiceStatus(){
 const[state,setState]=useState<State|null>(null),[error,setError]=useState('');
 useEffect(()=>{const control=new AbortController();let active=true;
  const reload=async()=>{try{const response=await fetch('/api/operations',{signal:control.signal,cache:'no-store'});
   const value=await response.json() as State;if(!value||typeof value.status!=='string')throw Error('Invalid status');if(active){setState(value);setError('');}}
   catch{if(active&&!control.signal.aborted)setError('Operational status is unavailable.');}};
  reload();const interval=setInterval(reload,30000);return()=>{active=false;control.abort();clearInterval(interval);};
 },[]);
 const old=state?.checked_at?Date.now()-Date.parse(state.checked_at)>7200000:false;
 return <section className="readiness-card"><h2>Running services and source freshness</h2>
 {error&&<p role="alert">{error}</p>}{!state&&!error&&<p>Checking backend status…</p>}
 {state&&<><div className="readiness-check"><div><b>Service state</b><p>{state.message||state.run_id||'No run reported'}</p></div>
 <span className={'readiness-chip '+(state.status==='healthy'&&!old?'passed':'blocked')}>{old?'monitor stale':state.status.replaceAll('_',' ')}</span></div>
 <div className="readiness-check"><div><b>Newest forecast initialization age</b><p>{state.forecast_age_hours==null?'Not reported':state.forecast_age_hours.toFixed(1)+' hours'}</p></div><span className="readiness-chip">{state.refresh?.state||'not connected'}</span></div>
 {state.sources&&<div className="readiness-check"><div><b>India source arrivals</b><p>{Object.entries(state.sources).map(([name,status])=>name+': '+status).join(' · ')}</p></div></div>}
 {state.global_forecast&&<div className="readiness-check"><div><b>Live-global publication</b><p>{state.global_forecast.state==='available'?`${state.global_forecast.run_id} · ${state.global_forecast.forecast_age_hours?.toFixed(1)??'—'} h old · ${Object.entries(state.global_forecast.sources??{}).map(([name,status])=>name+': '+status).join(' · ')}`:'Not available'}</p></div><span className={'readiness-chip '+(state.global_forecast.state==='available'?'passed':'blocked')}>{state.global_forecast.state.replaceAll('_',' ')}</span></div>}
 <div className="readiness-check"><div><b>Backend / daily backup</b><p>{state.backend?.ready?'Backend checks passed':'Backend readiness not established'} · Backup: {state.backup?.status||'not reported'}</p></div></div>
 {state.alerts?.map(a=><p className="real-warning" key={a.code}>{a.severity.toUpperCase()}: {a.message}</p>)}
 <p className="fine-print">{state.checked_at?'Last checked '+new Date(state.checked_at).toLocaleString()+'. ':''}Local service health is not scientific forecast approval. Alerts are recorded locally; no institutional notification channel is implied.</p></>}
 </section>;
}

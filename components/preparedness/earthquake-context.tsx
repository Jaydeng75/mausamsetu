'use client';
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import dynamic from 'next/dynamic';
import {Activity,RefreshCw,MapPin,ExternalLink} from 'lucide-react';
import {EARTHQUAKE_DOCS,filterEarthquakes,feedIsStale,type QuakeFeed,type QuakeRegion} from '@/lib/preparedness/earthquakes';
const EarthquakeMap=dynamic(()=>import('./earthquake-map'),{ssr:false,loading:()=> <div className="prep-quake-map prep-loading">Loading map…</div>});
const utc=(time:number|string)=>new Date(time).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'})+' UTC';
export default function EarthquakeContext(){
 const[data,setData]=useState<QuakeFeed|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[now,setNow]=useState(0);
 const[region,setRegion]=useState<QuakeRegion>('india-buffer'),[minimum,setMinimum]=useState(2.5),[hours,setHours]=useState(168),[selected,setSelected]=useState<string|null>(null);
 const request=useRef<AbortController|null>(null);
 const load=useCallback(async()=>{
  request.current?.abort();const controller=new AbortController();request.current=controller;setLoading(true);
  try{
   const response=await fetch('/api/earthquakes',{signal:controller.signal,cache:'no-store'});
   if(!response.ok)throw Error('The earthquake feed is unavailable. This is not an all-clear.');
   const body=await response.json() as QuakeFeed;
   if(body.schema_version!==1||body.provider!=='USGS'||body.is_warning!==false||!Array.isArray(body.events)||!Number.isFinite(Date.parse(body.generated_at)))throw Error('Earthquake feed failed validation.');
   setData(body);setError('');setNow(Date.now());
  }catch(e){if(!controller.signal.aborted)setError((e as Error).message);}
  finally{if(!controller.signal.aborted)setLoading(false);}
 },[]);
 useEffect(()=>{const initial=setTimeout(()=>{void load();},0);const clock=setInterval(()=>setNow(Date.now()),60000);const poll=setInterval(()=>{if(document.visibilityState==='visible')void load();},300000);
  return()=>{request.current?.abort();clearTimeout(initial);clearInterval(clock);clearInterval(poll);};},[load]);
 const events=useMemo(()=>data?filterEarthquakes(data.events,region,minimum,hours,now):[],[data,region,minimum,hours,now]);
 const chosen=events.find(e=>e.id===selected),stale=data?feedIsStale(data,now):false;
 return <section className="prep-seismic no-print" id="earthquakes">
 <div className="prep-section-heading"><div><span className="eyebrow">SUPPLEMENTARY HAZARD CONTEXT</span><h2><Activity size={22}/>Recent earthquakes</h2></div><button className="prep-refresh" disabled={loading} onClick={()=>void load()}><RefreshCw size={16}/>{loading?'Checking…':'Refresh feed'}</button></div>
 <p className="prep-muted">USGS M2.5+ summaries for the last seven days. This is an event catalogue, not earthquake prediction, a tsunami warning, or an input to the weather blend.</p>
 <div className="prep-filters"><label>Region<select aria-label="Earthquake region" value={region} onChange={e=>{setRegion(e.target.value as QuakeRegion);setSelected(null);}}><option value="india-buffer">India + neighbouring region</option><option value="world">Global</option></select></label><label>Minimum magnitude<select value={minimum} onChange={e=>setMinimum(Number(e.target.value))}>{[2.5,4,5,6].map(n=><option key={n} value={n}>M {n}+</option>)}</select></label><label>Period<select value={hours} onChange={e=>setHours(Number(e.target.value))}><option value={24}>Last 24 hours</option><option value={168}>Last 7 days</option></select></label></div>
 {error&&<p role="alert" className="prep-warning">{error} {data?'The last loaded catalogue is retained below with its original timestamp.':'No events have been substituted.'}</p>}
 {stale&&<p role="status" className="prep-warning">The provider catalogue is older than 15 minutes. Treat it as stale, not a current status assessment.</p>}
 {data?<><div className="prep-feed-meta"><span>{events.length} matching records</span><span>USGS generated {utc(data.generated_at)}</span><span>Retrieved {utc(data.fetched_at)}</span></div>
 <div className="prep-seismic-layout"><EarthquakeMap events={events} region={region} selected={selected} onSelect={setSelected}/><div className="prep-events" aria-label="Earthquake events">
 {!events.length?<p>No records match these filters in the loaded feed. Coverage is not complete; this does not establish that the area is safe.</p>:events.slice(0,150).map(event=><article key={event.id} className={selected===event.id?'selected':''}><button onClick={()=>setSelected(event.id)} aria-pressed={selected===event.id}><strong className="prep-magnitude">M {event.magnitude?.toFixed(1)??'—'}</strong><span><b>{event.place}</b><small>{utc(event.time)}</small><small>Depth {event.depthKm.toFixed(1)} km · {event.reviewStatus}</small></span></button>{event.url&&<a href={event.url} target="_blank" rel="noreferrer" aria-label={'USGS details: '+event.place}><ExternalLink size={13}/>USGS event details</a>}</article>)}
 {events.length>150&&<p>Showing the newest 150 list entries. The map includes all {events.length} filtered records.</p>}</div></div>
 {chosen&&<div className="prep-selection"><MapPin size={16}/><span><b>{chosen.place}</b> · {chosen.latitude.toFixed(3)}°, {chosen.longitude.toFixed(3)}° · last revised {utc(chosen.updated)}</span></div>}
 <p className="prep-small">India view is a 4–40°N, 60–105°E bounding box, including neighbouring countries and ocean. {data.skipped_records>0?`${data.skipped_records} invalid or non-earthquake records were excluded. `:''}USGS reports may be revised. Magnitude alone does not describe local damage or tsunami risk.</p></>:!error&&<p role="status" className="prep-loading">Checking the USGS catalogue…</p>}
 <a className="prep-source" href={EARTHQUAKE_DOCS} target="_blank" rel="noreferrer">USGS feed format and attribution ↗</a>
 </section>;
}

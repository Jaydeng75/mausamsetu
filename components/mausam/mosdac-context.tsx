'use client';
import {useEffect,useState} from 'react';
type Region={name:string;mean_rate:number;p95_rate:number;max_rate:number;wet_area_fraction:number;coverage_fraction:number};
type Status={schema_version:number;state:string;checked_at:string;dataset_id:string;attribution:string;limitations:string[];latest:null|{identifier:string;scan_start:string;scan_end:string;age_hours:number;sha256:string;units:string;regions:Region[]}};
export default function MosdacContext(){
 const[data,setData]=useState<Status|null>(null),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 useEffect(()=>{const c=new AbortController();setError('');fetch('/api/mosdac',{signal:c.signal,cache:'no-store'}).then(async r=>{if(!r.ok)throw Error('MOSDAC status unavailable');const d=await r.json() as Status;if(d.schema_version!==1)throw Error('Unsupported MOSDAC report');setData(d);}).catch(e=>{if(!c.signal.aborted)setError(e.message)});return()=>c.abort()},[refresh]);
 const old=data?Date.now()-Date.parse(data.checked_at)>90*60*1000:false;
 return <section className="readiness-card" id="mosdac"><h2>INSAT-3DS satellite rainfall context</h2><button className="real-action" onClick={()=>setRefresh(x=>x+1)}>Refresh satellite context</button>
 <p>MOSDAC multispectral rainfall estimates show where rainfall was detected during a satellite scan. These are rain rates, not 24-hour totals, future forecasts or official warnings.</p>
 {error&&<p role="alert">{error}</p>}{!data&&!error&&<p>Checking satellite observations…</p>}
 {data&&<><p><strong>{old?'Update overdue':data.state.replaceAll('_',' ')}</strong> · {data.dataset_id} · checked {new Date(data.checked_at).toLocaleString()}</p>
 {data.latest&&<><p>Scan {new Date(data.latest.scan_start).toLocaleString()} – {new Date(data.latest.scan_end).toLocaleTimeString()} · {Math.max(0,(Date.now()-Date.parse(data.latest.scan_end))/3600000).toFixed(1)} hours old.</p>
 {(old||!['available','delayed'].includes(data.state))&&<p role="status">Showing the last successful observation; the latest retrieval is unavailable or overdue.</p>}
 <div className="real-score-scroll"><table className="evidence-table"><thead><tr><th>Regional box</th><th>Mean mm/h</th><th>95th percentile mm/h</th><th>Wet area ≥0.1 mm/h</th><th>Valid coverage</th></tr></thead><tbody>{data.latest.regions.map(r=><tr key={r.name}><td>{r.name}</td><td>{r.mean_rate.toFixed(2)}</td><td>{r.p95_rate.toFixed(2)}</td><td>{(100*r.wet_area_fraction).toFixed(1)}%</td><td>{(100*r.coverage_fraction).toFixed(1)}%</td></tr>)}</tbody></table></div>
 <details><summary>Method and provenance</summary><p>Mean and wet-area fraction use latitude area weights. Percentiles describe valid grid cells. Boxes include neighbouring countries and ocean; they are not administrative regions. Missing values are excluded, never replaced with zero.</p><p style={{overflowWrap:'anywhere'}}>{data.latest.identifier}<br/>SHA-256: {data.latest.sha256}</p><ul>{data.limitations.map(x=><li key={x}>{x}</li>)}</ul></details></>}
 <p className="fine-print">{data.attribution} · <a href="https://www.mosdac.gov.in/data-access-policy" target="_blank" rel="noreferrer">Data policy</a> · <a href="https://www.mosdac.gov.in/docs/INSAT-3DS_Operational_Products_V1.pdf" target="_blank" rel="noreferrer">INSAT-3DS product definitions</a></p></>}
 </section>
}

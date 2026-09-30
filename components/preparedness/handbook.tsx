'use client';
import {useEffect,useState} from 'react';
import {BookOpen,Download,Printer,Phone,ClipboardCheck} from 'lucide-react';
import {GUIDES,GUIDANCE_REVIEWED,EMERGENCY,OFFICIAL_RESOURCES,KIT_ITEMS,KIT_SOURCE,validKitState,handbookHtml,type KitState} from '@/lib/preparedness/guidance';
import {downloadFile} from '@/components/mausam/controls';
const STORAGE_KEY='mausamsetu.preparedness-kit.v1';
export default function Handbook(){
 const[active,setActive]=useState('flood'),[kit,setKit]=useState<KitState>({version:1,checked:[]});
 const[ready,setReady]=useState(false),[storageError,setStorageError]=useState(false);
 useEffect(()=>{
  const load=()=>{try{const raw=localStorage.getItem(STORAGE_KEY);const value:unknown=raw?JSON.parse(raw):{version:1,checked:[]};if(!validKitState(value))throw Error('Invalid local checklist');setKit(value);}catch{setStorageError(true);}finally{setReady(true);}};
  load();const listener=(event:StorageEvent)=>{if(event.key===STORAGE_KEY||event.key===null)load();};
  window.addEventListener('storage',listener);return()=>window.removeEventListener('storage',listener);
 },[]);
 const save=(next:KitState)=>{setKit(next);try{localStorage.setItem(STORAGE_KEY,JSON.stringify(next));setStorageError(false);}catch{setStorageError(true);}};
 const toggle=(id:string)=>save({version:1,checked:kit.checked.includes(id)?kit.checked.filter(v=>v!==id):[...kit.checked,id]});
 const guide=GUIDES.find(g=>g.id===active)!;
 return <section className="prep-handbook" id="handbook">
 <div className="prep-section-heading"><div><span className="eyebrow">PREPARE BEFORE AN EMERGENCY</span><h2><BookOpen size={22}/>Safety handbook</h2></div><div className="prep-actions no-print">
 <button onClick={()=>window.print()}><Printer size={16}/>Print guide</button>
 <button disabled={!ready} onClick={()=>downloadFile('mausamsetu-preparedness.html',handbookHtml(kit),'text/html')}><Download size={16}/>Save offline handbook</button></div></div>
 <p className="prep-muted">General preparedness summaries, reviewed {GUIDANCE_REVIEWED}. Follow local authorities. This is not a personalized emergency assessment.</p>
 <div className="prep-handbook-layout"><aside className="prep-guide-nav no-print"><nav aria-label="Safety topics">{GUIDES.map(g=><button key={g.id} aria-pressed={g.id===active} onClick={()=>setActive(g.id)}>{g.title}</button>)}</nav>
 <article className="prep-emergency"><span>EMERGENCY ASSISTANCE · INDIA</span><a href="tel:112" className="prep-emergency-number"><Phone size={25}/>112</a><p>Police, fire and rescue, and health emergencies.</p><a href={EMERGENCY.source} target="_blank" rel="noreferrer">Government ERSS information ↗</a><small>Outside India, use your local emergency number.</small></article></aside>
 <article className="prep-guide-content"><h3>{guide.title}</h3><p>{guide.summary}</p><ol>{guide.steps.map(step=><li key={step}>{step}</li>)}</ol><a className="prep-source" href={guide.source} target="_blank" rel="noreferrer">Read source guidance: {guide.sourceName} ↗</a><p className="prep-small">Source summaries are informational. In India use IMD / NDMA / local authorities for official hazard bulletins and evacuation instructions.</p></article></div>
 <section className="prep-kit"><div className="prep-section-heading"><div><h3><ClipboardCheck size={21}/>Your preparedness checklist</h3><p className="prep-muted">Saved only in this browser. A checked item is your record, not a safety certification.</p></div><span className="prep-count" aria-live="polite">{kit.checked.length} / {KIT_ITEMS.length} packed</span></div>
 <div className="prep-kit-grid">{KIT_ITEMS.map(item=><label key={item.id} className={kit.checked.includes(item.id)?'checked':''}><input type="checkbox" checked={kit.checked.includes(item.id)} disabled={!ready} onChange={()=>toggle(item.id)}/><span><b>{item.label}</b><small>{item.detail}</small></span></label>)}</div>
 {storageError&&<p className="prep-warning" role="status">Browser storage could not be read or saved. The checklist still works in this session; save the offline handbook to keep a copy.</p>}
 <div className="prep-actions no-print"><button disabled={!ready||!kit.checked.length} onClick={()=>save({version:1,checked:[]})}>Clear checklist</button><a href={KIT_SOURCE} target="_blank" rel="noreferrer">Supplies reference: USGS ↗</a></div></section>
 <section className="prep-official"><h3>Official information, separate from our forecasts</h3><div>{OFFICIAL_RESOURCES.map(r=><a key={r.title} href={r.url} target="_blank" rel="noreferrer"><b>{r.title} ↗</b><span>{r.description}</span></a>)}</div><p className="prep-small">No official warning feed or verified nearby shelter directory is ingested here. External portals require internet access.</p></section>
 </section>;
}

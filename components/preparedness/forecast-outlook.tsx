'use client';
import {fieldValues,gridIndex,type PublicProduct} from '@/lib/public-data';
import {VARIABLES,type Variable} from '@/lib/forecast';
import styles from './outlook.module.css';
type Props={data:PublicProduct;source:string;variable:Variable;location:{lat:number;lng:number};lead:number;onSelect:(lead:number)=>void;formatValue?:(value:number)=>number;unit?:string};
export default function ForecastOutlook({data,source,variable,location,lead,onSelect,formatValue=(value:number)=>value,unit}:Props){
 if(data.data_kind!=='forecast')return null;
 const index=gridIndex(data,location.lat,location.lng),config=VARIABLES[variable];
 const steps=data.leads.filter(h=>h%24===0);
 return <section className={styles.outlook} aria-label="Seven-day model outlook"><div className="eyebrow">SEVEN-DAY OUTLOOK</div><p>{source} · {config.label} ({unit??config.unit})</p>
 <div>{steps.map(h=>{const value=index<0?null:fieldValues(data,source,h,variable)[index];const valid=new Date(Date.parse(data.initialization)+h*3600000);
  return <button key={h} onClick={()=>onSelect(h)} aria-pressed={lead===h} aria-label={`${config.label} at +${h} hours`}><span>{valid.toLocaleDateString('en-GB',{day:'2-digit',month:'short',timeZone:'UTC'})}</span><strong>{value==null?'—':formatValue(value).toFixed(1)}</strong><small>+{h}h</small></button>;})}</div>
 <small>{variable==='rain'?'Each value is the preceding 24-hour total, not a rain probability.':'Samples at the stated valid times, not daily maxima or minima.'} Missing values remain unavailable.</small></section>;
}

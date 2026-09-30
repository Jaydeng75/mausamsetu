import {z} from 'zod';
export const EARTHQUAKE_FEED='https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson';
export const EARTHQUAKE_DOCS='https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php';
export type Quake={id:string;magnitude:number|null;place:string;time:number;updated:number;longitude:number;latitude:number;depthKm:number;reviewStatus:string;url:string|null};
export type QuakeFeed={schema_version:1;provider:'USGS';generated_at:string;fetched_at:string;source_url:string;events:Quake[];skipped_records:number;is_warning:false};
export type QuakeRegion='india-buffer'|'world';
const time=z.number().finite().nonnegative();
const collection=z.object({type:z.literal('FeatureCollection'),metadata:z.object({generated:time,status:z.literal(200),count:z.number().int().nonnegative()}),features:z.array(z.unknown()).max(10000)});
const feature=z.object({type:z.literal('Feature'),id:z.string().min(1).max(120),geometry:z.object({type:z.literal('Point'),coordinates:z.tuple([z.number().finite().min(-180).max(180),z.number().finite().min(-90).max(90),z.number().finite().min(-20).max(1000)])}),properties:z.object({mag:z.number().finite().min(-3).max(11).nullable(),place:z.string().max(500).nullable(),time,updated:time,status:z.string().max(80),url:z.string().max(1000).nullable(),type:z.string().max(80)})});
export function safeEventUrl(value:string|null):string|null{
 if(!value)return null;
 try{const u=new URL(value);return u.protocol==='https:'&&u.hostname==='earthquake.usgs.gov'&&!u.port&&!u.username&&!u.password&&u.pathname.startsWith('/earthquakes/eventpage/')?u.href:null;}catch{return null;}
}
export function parseEarthquakeFeed(input:unknown,fetchedAt=Date.now()):QuakeFeed{
 const raw=collection.parse(input);
 if(!Number.isFinite(fetchedAt)||raw.metadata.generated>fetchedAt+300000||raw.metadata.count!==raw.features.length)throw Error('Invalid earthquake feed metadata');
 const events=new Map<string,Quake>();let skipped=0;
 for(const candidate of raw.features){
  const parsed=feature.safeParse(candidate);
  if(!parsed.success){skipped++;continue;}
  const f=parsed.data,p=f.properties;
  if(p.type!=='earthquake'||p.time>fetchedAt+300000||p.updated>fetchedAt+300000||p.updated<p.time){skipped++;continue;}
  const [longitude,latitude,depthKm]=f.geometry.coordinates;
  const event:Quake={id:f.id,magnitude:p.mag,place:p.place||'Location description unavailable',time:p.time,updated:p.updated,longitude,latitude,depthKm,reviewStatus:p.status,url:safeEventUrl(p.url)};
  if(!events.has(f.id)||events.get(f.id)!.updated<event.updated)events.set(f.id,event);
 }
 if(raw.features.length&&!events.size)throw Error('No valid earthquake records in provider response');
 return {schema_version:1,provider:'USGS',generated_at:new Date(raw.metadata.generated).toISOString(),fetched_at:new Date(fetchedAt).toISOString(),source_url:EARTHQUAKE_FEED,events:[...events.values()].sort((a,b)=>b.time-a.time),skipped_records:skipped,is_warning:false};
}
export function filterEarthquakes(events:Quake[],region:QuakeRegion,minMagnitude:number,periodHours:number,now=Date.now()):Quake[]{
 if(!['india-buffer','world'].includes(region)||![minMagnitude,periodHours,now].every(Number.isFinite)||periodHours<=0||periodHours>168)throw Error('Invalid earthquake filters');
 return events.filter(e=>(e.magnitude!==null&&e.magnitude>=minMagnitude)&&e.time>=now-periodHours*3600000&&e.time<=now+300000&&
  (region==='world'||(e.latitude>=4&&e.latitude<=40&&e.longitude>=60&&e.longitude<=105))).sort((a,b)=>b.time-a.time);
}
export function feedIsStale(feed:QuakeFeed,now=Date.now()):boolean{
 const generated=Date.parse(feed.generated_at);return !Number.isFinite(generated)||now-generated>900000||generated>now+300000;
}

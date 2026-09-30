import {EARTHQUAKE_FEED,parseEarthquakeFeed,type QuakeFeed} from '@/lib/preparedness/earthquakes';
export const dynamic='force-dynamic';
export const runtime='nodejs';
let cached:{value:QuakeFeed;expires:number}|null=null;
let inFlight:Promise<QuakeFeed>|null=null;
let retryAfter=0;
async function retrieve():Promise<QuakeFeed>{
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
 try{
  const response=await fetch(EARTHQUAKE_FEED,{signal:controller.signal,cache:'no-store',redirect:'error',headers:{Accept:'application/geo+json, application/json'}});
  if(!response.ok||!response.body)throw Error('USGS response unavailable');
  const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;
   if(size>3000000){await reader.cancel();throw Error('USGS response exceeds limit');}chunks.push(value);}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  return parseEarthquakeFeed(JSON.parse(new TextDecoder().decode(bytes)));
 }finally{clearTimeout(timer);}
}
export async function GET(){
 if(process.env.MAUSAM_ENABLE_SEISMIC_CONTEXT==='false')return Response.json({error:'Supplementary earthquake context is disabled.'},{status:503});
 try{
  if(cached&&cached.expires>Date.now())return Response.json(cached.value,{headers:{'Cache-Control':'no-store'}});
  if(retryAfter>Date.now())throw Error('Provider retry cooldown');
  if(!inFlight)inFlight=retrieve().then(value=>{cached={value,expires:Date.now()+300000};return value;}).catch(error=>{retryAfter=Date.now()+30000;throw error;}).finally(()=>{inFlight=null;});
  return Response.json(await inFlight,{headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }catch{
  return Response.json({error:'USGS earthquake context is unavailable. No substitute events or all-clear assessment have been generated.',is_warning:false},{status:503,headers:{'Cache-Control':'no-store','Retry-After':'30'}});
 }
}

import {z} from 'zod';
const providerSchema=z.object({latitude:z.number().finite(),longitude:z.number().finite(),current:z.object({time:z.string(),interval:z.number().positive(),temperature_2m:z.number().finite().nullable(),relative_humidity_2m:z.number().min(0).max(100).nullable(),wind_speed_10m:z.number().nonnegative().nullable(),precipitation:z.number().nonnegative().nullable()}),current_units:z.record(z.string())});
import {NextRequest,NextResponse} from 'next/server';
export const runtime='nodejs';
const cache=new Map<string,{expires:number;data:unknown}>();
export async function GET(request:NextRequest){
 const q=request.nextUrl.searchParams,lat=Number(q.get('lat')),lng=Number(q.get('lng'));
 if(!q.get('lat')||!q.get('lng')||!Number.isFinite(lat)||!Number.isFinite(lng)||Math.abs(lat)>90||Math.abs(lng)>180)return NextResponse.json({error:'Valid latitude and longitude are required.'},{status:400});
 const latitude=lat.toFixed(2),longitude=lng.toFixed(2),key=latitude+','+longitude,cached=cache.get(key);
 if(cached&&cached.expires>Date.now())return NextResponse.json(cached.data);
 const url=new URL('https://api.open-meteo.com/v1/forecast');
 url.search=new URLSearchParams({latitude,longitude,current:'temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation',temperature_unit:'celsius',wind_speed_unit:'ms',precipitation_unit:'mm',timezone:'GMT',forecast_days:'1'}).toString();
 try{
 const response=await fetch(url,{signal:AbortSignal.timeout(8000),cache:'no-store'});if(!response.ok)throw Error('Provider unavailable');
 const raw=providerSchema.parse(await response.json()),c=raw.current,u=raw.current_units;
 if(!c||!u||u.temperature_2m!=='°C'||u.wind_speed_10m!=='m/s'||u.precipitation!=='mm'||u.relative_humidity_2m!=='%'||!Number.isFinite(c.interval)||c.interval<=0||!Number.isFinite(raw.latitude)||!Number.isFinite(raw.longitude)||!Number.isFinite(Date.parse(c.time+'Z')))throw Error('Invalid provider metadata');
 for(const field of ['temperature_2m','relative_humidity_2m','wind_speed_10m','precipitation'] as const)if(c[field]!==null&&!Number.isFinite(c[field]))throw Error('Invalid field');
 const data={provider:'Open-Meteo',data_kind:'modelled_current_conditions',model_selection:'Best Match (provider selected)',requested:{lat:Number(latitude),lng:Number(longitude)},grid:{lat:raw.latitude,lng:raw.longitude},retrieved_at:new Date().toISOString(),time:c.time+'Z',interval_seconds:c.interval,temperature:c.temperature_2m,humidity:c.relative_humidity_2m,wind:c.wind_speed_10m,precipitation:c.precipitation,attribution:'Weather data by Open-Meteo.com',documentation:'https://open-meteo.com/en/docs'};
 if(cache.size>=128)cache.delete(cache.keys().next().value!);cache.set(key,{expires:Date.now()+600000,data});return NextResponse.json(data);
 }catch{return NextResponse.json({error:'Open-Meteo is unavailable. No substitute values have been generated.'},{status:502});}
}

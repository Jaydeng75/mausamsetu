import fs from 'node:fs';
import {forecast,componentSamples,truth,getWeights,LOCATIONS,SOURCES,VARIABLES,RUN,INIT} from '../lib/forecast.ts';
let seed=26081;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
const crps=(samples,mass,y)=>{const order=samples.map((x,i)=>({x,w:mass[i]})).sort((a,b)=>a.x-b.x);let cum=0,result=0;for(const{x,w}of order){result+=w*Math.abs(x-y)-w*x*(2*cum+w-1);cum+=w;}return result;};
const rows=[];
for(let day=1;day<=24;day++)for(const loc of LOCATIONS.filter((_,i)=>[0,1,2,3,6,7,8,9].includes(i)))for(const variable of ['rain','temperature','wind']){
 const eventTime=day*7,base=truth(loc.lat,loc.lng,eventTime,variable),scale=variable==='rain'?8:variable==='temperature'?1.7:2;
 const observation=Math.max(variable==='temperature'?-30:0,base+(random()-.5)*2*scale);
 for(const lead of [24,48,72,120,168]){
  const weights=getWeights(loc.lat,loc.lng,lead,variable);
  const samples=componentSamples(loc.lat,loc.lng,eventTime,variable).map(source=>source.map(x=>Math.max(variable==='temperature'?-30:0,base+(x-base)*(.65+lead/200))));
  const models={};
  SOURCES.forEach((source,i)=>{models[source]={mean:samples[i].reduce((a,b)=>a+b,0)/samples[i].length,probability:samples[i].filter(x=>x>VARIABLES[variable].threshold).length/21,crps:crps(samples[i],samples[i].map(()=>1/21),observation)};});
  const all=samples.flat(),equal=all.map(()=>1/all.length),mass=samples.flatMap((s,i)=>s.map(()=>weights[i]/s.length));
  models.Blend={mean:all.reduce((a,b,i)=>a+b*mass[i],0),probability:all.reduce((a,b,i)=>a+(b>VARIABLES[variable].threshold?mass[i]:0),0),crps:crps(all,mass,observation)};
  models.Equal={mean:all.reduce((a,b)=>a+b,0)/all.length,probability:all.filter(x=>x>VARIABLES[variable].threshold).length/all.length,crps:crps(all,equal,observation)};
  rows.push({id:`case-${day}-${loc.name}-${lead}-${variable}`,date:`2026-09-${String(day).padStart(2,'0')}`,location:loc.name,region:loc.lat<18?'South':loc.lng>84?'East':loc.lng<75?'West':'North',lat:loc.lat,lng:loc.lng,variable,lead,observation,models});
 }
}
fs.mkdirSync('public/data',{recursive:true});fs.writeFileSync('public/data/verification.json',JSON.stringify({data_kind:'synthetic',seed:26081,description:'Deterministic simulation test set. Model names are illustrative; these are not provider forecasts. Context weights are a demonstration rule, not a trained or validated gate.',period:{start:'2026-09-01',end:'2026-09-24'},rows}));
fs.writeFileSync('public/data/manifest.json',JSON.stringify({run_id:RUN,initialization_time:INIT,published_at:'2026-09-26T01:15:00Z',data_kind:'synthetic',model_version:'illustrative-gate-v1',processing_version:'0.1.0',grid:'analytical demonstration field; display sampled on a 220 × 220 raster; no claimed scientific resolution',source_names:SOURCES,source_notice:'All model sources are simulated. NCUM/NEPS authorization and historical validation are pending.',scientific_status:'unvalidated',verification_cases:rows.length},null,2));
console.log(`Generated ${rows.length} reproducible synthetic verification cases.`);

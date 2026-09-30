import assert from 'node:assert/strict';
import fs from 'node:fs';
import {forecast,componentSamples,LOCATIONS,SOURCES,VARIABLES} from '../lib/forecast.ts';
let checked=0;
for(const loc of LOCATIONS)for(const variable of Object.keys(VARIABLES))for(const lead of [24,48,72,120,168]){
 const f=forecast(loc.lat,loc.lng,lead,variable);assert(Math.abs(f.weights.reduce((a,b)=>a+b,0)-1)<1e-10);assert(f.p10<=f.median&&f.median<=f.p90);assert(f.probability>=0&&f.probability<=1+1e-10);
 const s=componentSamples(loc.lat,loc.lng,lead,variable);const mean=s.reduce((a,row,i)=>a+row.reduce((x,y)=>x+y,0)/row.length*f.weights[i],0);assert(Math.abs(f.mean-mean)<1e-9);checked++;
}
assert.throws(()=>forecast(13,80,72,'rain',64.5,[...SOURCES]));
const f=forecast(13,80,72,'rain',64.5,['NEPS']);assert.equal(f.weights[0],0);
const data=JSON.parse(fs.readFileSync('public/data/verification.json','utf8'));assert.equal(data.rows.length,2880);
const observations=new Map();for(const row of data.rows){const key=[row.date,row.location,row.variable].join('-');if(observations.has(key))assert.equal(row.observation,observations.get(key));observations.set(key,row.observation);for(const m of Object.values(row.models)){assert(m.crps>=-1e-9);assert(m.probability>=0&&m.probability<=1+1e-9);}}
console.log(`${checked} forecast combinations passed; 2,880 verification records and fixed-observation replay checked.`);

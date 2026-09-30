export type Variable = 'rain' | 'temperature' | 'wind' | 'pressure';
export type Layer = 'blend' | 'risk' | 'uncertainty' | 'agreement' | 'dominant' | 'weights' | 'NEPS' | 'AIFS' | 'NCUM' | 'GFS';
export const SOURCES = ['NEPS', 'AIFS', 'NCUM', 'GFS'] as const;
export type Source = typeof SOURCES[number];
export const COLORS: Record<Source,string> = { NEPS:'#55d6c8', AIFS:'#a69bff', NCUM:'#55aafa', GFS:'#f4b86b' };
export const INIT = '2026-09-26T00:00:00Z';
export const RUN = 'demo-20260926-00-v1';
export const LOCATIONS = [
 {name:'Chennai',state:'Tamil Nadu',lat:13.083,lng:80.27}, {name:'Mumbai',state:'Maharashtra',lat:19.076,lng:72.878},
 {name:'New Delhi',state:'Delhi',lat:28.614,lng:77.209}, {name:'Kolkata',state:'West Bengal',lat:22.573,lng:88.364},
 {name:'Bengaluru',state:'Karnataka',lat:12.972,lng:77.595}, {name:'Hyderabad',state:'Telangana',lat:17.385,lng:78.487},
 {name:'Guwahati',state:'Assam',lat:26.144,lng:91.736}, {name:'Jaipur',state:'Rajasthan',lat:26.913,lng:75.787},
 {name:'Kochi',state:'Kerala',lat:9.932,lng:76.267}, {name:'Bhubaneswar',state:'Odisha',lat:20.296,lng:85.825},
 {name:'Lucknow',state:'Uttar Pradesh',lat:26.847,lng:80.947}, {name:'Srinagar',state:'Jammu & Kashmir',lat:34.084,lng:74.797},
 {name:'Visakhapatnam',state:'Andhra Pradesh',lat:17.686,lng:83.218}, {name:'Ahmedabad',state:'Gujarat',lat:23.023,lng:72.571},
];
export type Location = typeof LOCATIONS[number];
export const VARIABLES:Record<Variable,{label:string;unit:string;threshold:number;max:number;colors:string[]}> = {
 rain:{label:'Rainfall',unit:'mm',threshold:64.5,max:150,colors:['#173956','#2269a4','#4b96c6','#665cc1','#ab59b5','#ef8fb6']},
 temperature:{label:'Temperature',unit:'°C',threshold:40,max:45,colors:['#3966bc','#51a7c0','#84c5b5','#eac879','#e68864','#c85564']},
 wind:{label:'Wind speed',unit:'m/s',threshold:17,max:30,colors:['#173956','#286c84','#35abac','#9bc695','#e3ca74','#df945e']},
 pressure:{label:'Pressure',unit:'hPa',threshold:1010,max:1025,colors:['#6e629f','#5291be','#4bb3b6','#95c5b9','#d5c283','#dd9c6a']}
};
const gauss=(x:number,y:number,a:number,b:number,sx:number,sy:number)=>Math.exp(-((x-a)**2/sx+(y-b)**2/sy));
export function truth(lat:number,lng:number,lead:number,v:Variable){
 const t=lead/24;
 if(v==='rain')return 2+92*gauss(lng,lat,84-t*.8,14+t*.3,11,14)+72*gauss(lng,lat,73.8,17-t*.2,3,34)+85*gauss(lng,lat,91,26,17,6)+32*gauss(lng,lat,80+t*.3,24,26,13);
 if(v==='temperature')return 32-(lat-20)*.36+6*gauss(lng,lat,73,28,22,20)-9*gauss(lng,lat,81,33,80,14)+2*Math.sin(t*1.3+lng*.13);
 if(v==='wind'){const q=windVector(lat,lng,lead);return Math.hypot(q.u,q.v);}
 return 1014-18*gauss(lng,lat,84-t*.8,14+t*.3,30,25)+4*Math.sin(lat*.1);
}
export function windVector(lat:number,lng:number,lead:number){const dx=lng-(84-lead/30),dy=lat-16;const r=Math.sqrt(dx*dx+dy*dy)+1;return {u:5+dy/r*11,v:2-dx/r*11};}
export function getWeights(lat:number,lng:number,lead:number,v:Variable, unavailable:Source[]=[]){
 const s=[1.1+gauss(lng,lat,82,14,25,35)*1.5,1.25+lead/220+gauss(lng,lat,78,29,25,30),.85+gauss(lng,lat,73,20,15,22)*1.4,.3+gauss(lng,lat,92,27,20,20)*.5];
 if(v==='temperature')s[1]+=.7;
 const raw=s.map((x,i)=>unavailable.includes(SOURCES[i])?0:Math.exp(x));const sum=raw.reduce((a,b)=>a+b,0);
 if(!sum)throw new Error('No eligible forecast sources; publication withheld'); return raw.map(x=>x/sum);
}
function modelCenters(lat:number,lng:number,lead:number,v:Variable){const base=truth(lat,lng,lead,v);const scale=v==='rain'?13:v==='temperature'?2:v==='wind'?3:3;
 return SOURCES.map((_,i)=>{const val=base+scale*(Math.sin(lat*.3+lng*.15+i*1.6+lead/90)*(.5+i*.16)+[.08,-.12,-.24,.65][i]);return v==='rain'||v==='wind'?Math.max(0,val):val;});}
export function componentSamples(lat:number,lng:number,lead:number,v:Variable){return modelCenters(lat,lng,lead,v).map(m=>Array.from({length:21},(_,j)=>{const z=Math.log((j+.5)/(21-j-.5))*.55;const scale=v==='rain'?8+m*.24:v==='temperature'?2.4:v==='wind'?2.5:2;const x=m+z*scale;return v==='rain'||v==='wind'?Math.max(0,x):x;}));}
export function modelValues(lat:number,lng:number,lead:number,v:Variable){return componentSamples(lat,lng,lead,v).map(s=>s.reduce((a,b)=>a+b,0)/s.length);}
export function forecast(lat:number,lng:number,lead:number,v:Variable,threshold=VARIABLES[v].threshold,unavailable:Source[]=[]){
 const weights=getWeights(lat,lng,lead,v,unavailable),values=modelValues(lat,lng,lead,v);const mean=values.reduce((s,x,i)=>s+x*weights[i],0);
 const spread=Math.sqrt(values.reduce((s,x,i)=>s+weights[i]*(x-mean)**2,0));
 // Empirical synthetic component distributions, 21 equally weighted members per source.
 const samples:{x:number,w:number}[]=[];componentSamples(lat,lng,lead,v).forEach((s,i)=>s.forEach(x=>samples.push({x,w:weights[i]/s.length})));samples.sort((a,b)=>a.x-b.x);
 const quantile=(p:number)=>{let c=0;for(const s of samples){c+=s.w;if(c>=p)return s.x;}return samples.at(-1)!.x;};
 return {mean,median:quantile(.5),p10:quantile(.1),p90:quantile(.9),probability:samples.reduce((s,x)=>s+(x.x>threshold?x.w:0),0),weights,values,spread,agreement:Math.max(0,100*(1-spread/(v==='rain'?40:12))),dominant:SOURCES[weights.indexOf(Math.max(...weights))],quality:unavailable.length?'degraded':'demonstration'};
}
export function period(lead:number,v:Variable,tz='UTC'){const end=new Date(Date.parse(INIT)+lead*3600000);const start=new Date(end.getTime()-(v==='rain'?24:0)*3600000);const opts:Intl.DateTimeFormatOptions={day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:tz==='IST'?'Asia/Kolkata':'UTC'};return {start:start.toISOString(),end:end.toISOString(),label:(v==='rain'?start.toLocaleString('en-GB',opts)+' – ':'')+end.toLocaleString('en-GB',opts)+' '+tz};}
export function nearest(lat:number,lng:number):Location{const n=LOCATIONS.reduce((a,b)=>Math.hypot(a.lat-lat,a.lng-lng)<Math.hypot(b.lat-lat,b.lng-lng)?a:b);return Math.hypot(n.lat-lat,n.lng-lng)<.8?{...n,lat,lng}:{name:'Selected grid cell',state:'India region',lat,lng};}
export function color(value:number,colors:string[],min=0,max=150){const t=Math.max(0,Math.min(colors.length-1,(value-min)/(max-min)*(colors.length-1)));const i=Math.min(colors.length-2,Math.floor(t));const f=t-i;const a=colors[i],b=colors[i+1];return [1,3,5].map(k=>Math.round(parseInt(a.slice(k,k+2),16)*(1-f)+parseInt(b.slice(k,k+2),16)*f));}

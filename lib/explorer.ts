import type {Variable} from './forecast';
import {fieldValues,gridIndex,type PublicProduct} from './public-data';
export type Place={name:string;lat:number;lng:number};
export type Units='metric'|'imperial';
export type Region={name:string;bounds:[number,number,number,number]};
export type Preferences={units:Units;favorites:Place[];lastIndia:Place|null;lastWorld:Place|null;guideSeen:boolean;dismissed:string[]};
export const DEFAULT_PREFS:Preferences={units:'metric',favorites:[],lastIndia:null,lastWorld:null,guideSeen:false,dismissed:[]};
export function isPlace(p:unknown):p is Place{const x=p as Place;return !!x&&typeof x.name==='string'&&x.name.length<=100&&Number.isFinite(x.lat)&&Math.abs(x.lat)<=90&&Number.isFinite(x.lng)&&Math.abs(x.lng)<=180;}
export function validPreferences(p:unknown):p is Preferences{const x=p as Preferences;return !!x&&['metric','imperial'].includes(x.units)&&Array.isArray(x.favorites)&&x.favorites.length<=20&&x.favorites.every(isPlace)&&(x.lastIndia===null||isPlace(x.lastIndia))&&(x.lastWorld===null||isPlace(x.lastWorld))&&typeof x.guideSeen==='boolean'&&Array.isArray(x.dismissed)&&x.dismissed.length<=200&&x.dismissed.every(s=>typeof s==='string'&&s.length<300);}
export function displayValue(v:number,variable:Variable,units:Units){if(units==='metric')return v;return variable==='temperature'?v*9/5+32:variable==='rain'?v/25.4:variable==='wind'?v*2.236936:v*0.029529983;}
export function displayUnit(variable:Variable,units:Units){return (units==='metric'?{rain:'mm',temperature:'°C',wind:'m/s',pressure:'hPa'}:{rain:'in',temperature:'°F',wind:'mph',pressure:'inHg'})[variable];}
export type Notice={id:string;variable:Variable;value:number;threshold:number;level:'Watch'|'Elevated';lead:number;valid:string;start:string;source:string;grid:{lat:number;lng:number}};
export function thresholdNotices(p:PublicProduct,place:Place,source:string):Notice[]{
 if(p.data_kind!=='forecast')return [];
 const i=gridIndex(p,place.lat,place.lng);if(i<0)return [];
 const rules:[Variable,number,number][]=[['rain',64.5,115.6],['temperature',40,45],['wind',15,20]];
 return p.leads.flatMap(lead=>rules.flatMap(([variable,threshold,elevated])=>{
 const value=fieldValues(p,source,lead,variable)[i];if(value==null||value<threshold)return [];
 const valid=new Date(Date.parse(p.initialization)+lead*3600000).toISOString();
 return [{id:[p.run_id,source,i,variable,lead].join(':'),variable,value,threshold,level:value>=elevated?'Elevated' as const:'Watch' as const,lead,valid,start:variable==='rain'?new Date(Date.parse(valid)-86400000).toISOString():valid,source,grid:{lat:p.latitude[Math.floor(i/p.longitude.length)],lng:p.longitude[i%p.longitude.length]}}];
 })).sort((a,b)=>a.lead-b.lead);
}

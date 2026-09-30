'use client';
import {useEffect,useRef,useState} from 'react';
import * as ml from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type {FeatureCollection,Point} from 'geojson';
import type {Quake,QuakeRegion} from '@/lib/preparedness/earthquakes';
type Props={events:Quake[];region:QuakeRegion;selected:string|null;onSelect:(id:string)=>void};
export default function EarthquakeMap(props:Props){
 const container=useRef<HTMLDivElement>(null),map=useRef<ml.Map|null>(null),latest=useRef(props);
 useEffect(()=>{latest.current=props;},[props]);
 const[ready,setReady]=useState(false),[error,setError]=useState('');
 useEffect(()=>{
  if(!container.current)return;ml.setWorkerUrl('/maplibre/maplibre-gl-worker.mjs');let m:ml.Map;
  try{m=new ml.Map({container:container.current,center:[82,23],zoom:2.8,minZoom:0,maxZoom:10,renderWorldCopies:false,attributionControl:false,style:{version:8,sources:{land:{type:'geojson',data:'/data/countries.geojson'}},layers:[{id:'sea',type:'background',paint:{'background-color':'#0a1724'}},{id:'land',type:'fill',source:'land',paint:{'fill-color':'#1b3040'}},{id:'borders',type:'line',source:'land',paint:{'line-color':'#738d9f','line-opacity':0.55,'line-width':0.7}}]}});map.current=m;}
  catch{const timer=setTimeout(()=>setError('Map rendering unavailable. All event details remain available in the list.'),0);return()=>clearTimeout(timer);}
  m.addControl(new ml.NavigationControl({showCompass:false}),'top-right');
  m.addControl(new ml.AttributionControl({compact:true,customAttribution:'Earthquake locations: USGS · Boundaries: Natural Earth'}));
  m.on('load',()=>{
   m.addSource('events',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
   m.addLayer({id:'earthquakes',type:'circle',source:'events',paint:{'circle-radius':['interpolate',['linear'],['coalesce',['get','magnitude'],0],0,4,2.5,6,5,10,8,16],
    'circle-color':'#e9b779','circle-opacity':0.8,'circle-stroke-width':1.5,'circle-stroke-color':'#fff3dc'}});setReady(true);
  });
  m.on('click','earthquakes',event=>{const id=event.features?.[0]?.properties?.id;if(typeof id==='string')latest.current.onSelect(id);});
  m.on('mouseenter','earthquakes',()=>{m.getCanvas().style.cursor='pointer';});m.on('mouseleave','earthquakes',()=>{m.getCanvas().style.cursor='';});
  m.on('error',event=>{if(event.error?.message?.includes('WebGL'))setError('Map rendering unavailable; use the event list.');});
  const observer=new ResizeObserver(()=>m.resize());observer.observe(container.current);
  return()=>{observer.disconnect();m.remove();map.current=null;};
 },[]);
 useEffect(()=>{
  if(!ready||!map.current)return;
  const data:FeatureCollection<Point>={type:'FeatureCollection',features:props.events.map(event=>({type:'Feature',id:event.id,geometry:{type:'Point',coordinates:[event.longitude,event.latitude]},properties:{id:event.id,magnitude:event.magnitude}}))};
  (map.current.getSource('events') as ml.GeoJSONSource).setData(data);
 },[props.events,ready]);
 useEffect(()=>{if(!ready||!map.current)return;
  const bounds:ml.LngLatBoundsLike=props.region==='india-buffer'?[[60,4],[105,40]]:[[-175,-58],[175,75]];
  map.current.fitBounds(bounds,{padding:35,duration:0});
 },[props.region,ready]);
 useEffect(()=>{if(!ready||!map.current)return;const event=props.events.find(e=>e.id===props.selected);
  if(event)map.current.easeTo({center:[event.longitude,event.latitude],zoom:Math.max(map.current.getZoom(),4),duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:250});
 },[props.selected,props.events,ready]);
 return <div className="prep-quake-map"><div ref={container} role="region" aria-label="Earthquake epicentre map"/>{error&&<p className="prep-map-error">{error}</p>}<span className="prep-map-caption">USGS coordinates · circle size indicates magnitude, not local impact</span></div>;
}

'use client';
import {useEffect,useRef,useState} from 'react';
import * as ml from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {VARIABLES,color,type Variable} from '@/lib/forecast';
import {gridIndex,type PublicProduct} from '@/lib/public-data';
import type {Region} from '@/lib/explorer';
import {Plus,Minus,LocateFixed} from 'lucide-react';
type Props={region?:Region|null;product:PublicProduct;values:(number|null)[];variable:Variable;location:{lat:number;lng:number};onPick:(lat:number,lng:number)=>void;u?:(number|null)[];v?:(number|null)[];particles:boolean};
export default function DataMap(props:Props){
 const host=useRef<HTMLDivElement>(null),wind=useRef<HTMLCanvasElement>(null),map=useRef<ml.Map|null>(null),marker=useRef<ml.Marker|null>(null),canvas=useRef<HTMLCanvasElement|null>(null),latest=useRef(props);latest.current=props;
 const[ready,setReady]=useState(false),[error,setError]=useState('');const historical=props.product.data_kind==='historical_evaluation',world=historical||props.product.coverage==='global';
 const reset=()=>map.current?.fitBounds(world?[[-178,-65],[178,78]]:[[65,5],[100,38]],{padding:{top:75,bottom:100,left:25,right:25},duration:300});
 useEffect(()=>{if(!host.current)return;ml.setWorkerUrl('/maplibre/maplibre-gl-worker.mjs');let m:ml.Map;
  try{m=new ml.Map({container:host.current,center:world?[0,10]:[80,22],zoom:world?1:3.4,minZoom:0,maxZoom:10,renderWorldCopies:false,attributionControl:false,style:{version:8,sources:{land:{type:'geojson',data:'/data/countries.geojson'}},layers:[{id:'sea',type:'background',paint:{'background-color':'#0b1825'}},{id:'land',type:'fill',source:'land',paint:{'fill-color':'#182b39'}},{id:'borders',type:'line',source:'land',paint:{'line-color':'#d0dce5','line-opacity':.5,'line-width':.7}}]}});map.current=m;}catch{setError('Map unavailable. Use location selection and the data panel.');return;}
  m.addControl(new ml.AttributionControl({compact:true,customAttribution:'Natural Earth · '+(historical?'WeatherBench 2 / ECMWF / Copernicus':props.product.coverage==='global'?'NOAA GFS / ECMWF AIFS':'geoBoundaries / DataMeet (CC BY 2.5 IN) · NOAA / ECMWF (CC BY 4.0)')}));
  m.on('load',()=>{const c=document.createElement('canvas');c.width=world?512:280;c.height=280;canvas.current=c;
   m.addSource('field',{type:'canvas',canvas:c,animate:false,coordinates:world?[[-180,85],[180,85],[180,-85],[-180,-85]]:[[65,38],[100,38],[100,5],[65,5]]});
   m.addLayer({id:'field',type:'raster',source:'field',paint:{'raster-opacity':.8,'raster-fade-duration':200}},'borders');
   if(!world){m.addSource('states',{type:'geojson',data:'/data/india-states.geojson'});m.addLayer({id:'state-hit',type:'fill',source:'states',paint:{'fill-opacity':0}});m.addLayer({id:'state-lines',type:'line',source:'states',paint:{'line-color':'#b1d5df','line-width':.7,'line-opacity':.45}});m.addLayer({id:'state-highlight',type:'fill',source:'states',filter:['==',['get','shapeName'],''],paint:{'fill-color':'#76edcf','fill-opacity':.13}});m.addLayer({id:'state-outline',type:'line',source:'states',filter:['==',['get','shapeName'],''],paint:{'line-color':'#a0ffe1','line-width':2}});m.addLayer({id:'state-hover',type:'line',source:'states',filter:['==',['get','shapeName'],''],paint:{'line-color':'#ffffff','line-width':1.5}});m.on('mousemove',e=>{const f=m.queryRenderedFeatures(e.point,{layers:['state-hit']})[0];m.setFilter('state-hover',['==',['get','shapeName'],String(f?.properties?.shapeName||'')]);});m.getCanvas().addEventListener('mouseleave',()=>{if(m.getLayer('state-hover'))m.setFilter('state-hover',['==',['get','shapeName'],'']);});}
   const el=document.createElement('div');el.className='selected-marker';marker.current=new ml.Marker({element:el}).setLngLat([latest.current.location.lng,latest.current.location.lat]).addTo(m);setReady(true);reset();
  });
  m.on('click',e=>latest.current.onPick(e.lngLat.lat,e.lngLat.lng));
  m.on('error',e=>{if(e.error?.message?.includes('WebGL'))setError('Map rendering is unavailable on this device.');});
  const observer=new ResizeObserver(()=>m.resize());observer.observe(host.current);return()=>{observer.disconnect();m.remove();};
 // Product domain changes remount this map.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[]);
 useEffect(()=>{if(!ready||world||!map.current)return;const m=map.current;for(const id of ['state-highlight','state-outline'])m.setFilter(id,['==',['get','shapeName'],props.region?.name||'']);if(props.region){const [w,s,e,n]=props.region.bounds;m.fitBounds([[w,s],[e,n]],{padding:70,duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:500});}else reset();},[props.region,ready,world]);
 useEffect(()=>{marker.current?.setLngLat([props.location.lng,props.location.lat]);},[props.location,ready]);
 useEffect(()=>{if(!ready||!canvas.current||!map.current)return;const c=canvas.current,ctx=c.getContext('2d')!,img=ctx.createImageData(c.width,c.height),cfg=VARIABLES[props.variable];
  const merc=(v:number)=>Math.log(Math.tan(Math.PI/4+v*Math.PI/360)),top=merc(world?85:38),bottom=merc(world?-85:5);
  for(let y=0;y<c.height;y++)for(let x=0;x<c.width;x++){const lng=(world?-180:65)+x/(c.width-1)*(world?360:35),lat=(2*Math.atan(Math.exp(top+(bottom-top)*y/(c.height-1)))-Math.PI/2)*180/Math.PI;
   const i=gridIndex(props.product,lat,lng),value=props.values[i];if(value==null)continue;const rgb=color(value,cfg.colors,props.variable==='temperature'?(world?-40:5):props.variable==='pressure'?970:0,props.variable==='pressure'?1040:cfg.max);const k=(y*c.width+x)*4;img.data.set([...rgb,185],k);
  }ctx.putImageData(img,0,0);const source=map.current.getSource('field') as ml.CanvasSource;source.play();map.current.triggerRepaint();requestAnimationFrame(()=>{if(!map.current?.isStyleLoaded())return;(map.current.getSource('field') as ml.CanvasSource)?.pause();});
 },[props.product,props.values,props.variable,ready,world]);
 useEffect(()=>{if(!ready||!wind.current)return;const c=wind.current,ctx=c.getContext('2d')!;ctx.clearRect(0,0,c.width,c.height);if(!props.particles||!props.u||!props.v||matchMedia('(prefers-reduced-motion: reduce)').matches)return;let frame=0,last=0;
  const particles=Array.from({length:280},()=>({lat:5+Math.random()*33,lng:65+Math.random()*35,age:Math.random()*100}));
  const draw=(now:number)=>{frame=requestAnimationFrame(draw);const m=map.current;if(!m||now-last<33)return;last=now;const w=m.getCanvas().clientWidth,h=m.getCanvas().clientHeight;if(c.width!==w||c.height!==h){c.width=w;c.height=h;}ctx.globalCompositeOperation='destination-in';ctx.fillStyle='rgba(0,0,0,.87)';ctx.fillRect(0,0,w,h);ctx.globalCompositeOperation='source-over';ctx.strokeStyle='rgba(224,249,255,.65)';ctx.lineWidth=1;
   particles.forEach(p=>{const i=gridIndex(latest.current.product,p.lat,p.lng),u=latest.current.u?.[i],v=latest.current.v?.[i];if(u==null||v==null||p.age++>100){p.lat=5+Math.random()*33;p.lng=65+Math.random()*35;p.age=0;return;}const a=m.project([p.lng,p.lat]);p.lng+=u*.002/Math.cos(p.lat*Math.PI/180);p.lat+=v*.002;const b=m.project([p.lng,p.lat]);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();});};frame=requestAnimationFrame(draw);return()=>{cancelAnimationFrame(frame);ctx.clearRect(0,0,c.width,c.height);};
 },[ready,props.particles,props.u,props.v]);
 return <div className="weather-map"><div ref={host} className="map-host" aria-label={world?'WeatherBench map outside India':'Real forecast map of India'}/><canvas ref={wind} className="wind-canvas" aria-hidden="true"/>{error&&<div className="map-error">{error}</div>}<div className="map-controls"><button aria-label="Zoom in" onClick={()=>map.current?.zoomIn()}><Plus size={18}/></button><button aria-label="Zoom out" onClick={()=>map.current?.zoomOut()}><Minus size={18}/></button><button aria-label="Reset map" onClick={reset}><LocateFixed size={18}/></button></div></div>;
}

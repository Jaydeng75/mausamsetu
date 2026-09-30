'use client';
import Link from 'next/link';
import {useEffect,useState} from 'react';
import {ArrowLeft,Waypoints,ShieldCheck,WifiOff,ArrowDown} from 'lucide-react';
import Handbook from '@/components/preparedness/handbook';
import EarthquakeContext from '@/components/preparedness/earthquake-context';
import './preparedness.css';
export default function Preparedness(){
 const[online,setOnline]=useState(true);
 useEffect(()=>{const update=()=>setOnline(navigator.onLine);update();window.addEventListener('online',update);window.addEventListener('offline',update);return()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update);};},[]);
 return <main className="prep-page">
 <header className="prep-header no-print"><Link className="brand" href="/"><Waypoints/><span>Mausam<span className="brand-accent">Setu</span><small>FORECAST INTELLIGENCE</small></span></Link><nav aria-label="Preparedness navigation"><Link href="/sih">SIH evidence</Link><Link href="/"><ArrowLeft size={15}/>Forecast workbench</Link></nav></header>
 <div className="prep-container"><div className="prep-hero"><span className="eyebrow">A COMPANION TO THE FORECAST WORKBENCH</span><h1>Preparedness.<br/><span>Context, without guesswork.</span></h1><p>Practical, source-linked guidance and recent earthquake observations. Kept separate from model forecasts, probabilistic guidance and official warnings.</p><div className="prep-actions no-print"><a className="prep-primary" href="#handbook">Open safety handbook <ArrowDown size={16}/></a><a href="#earthquakes">Explore earthquake context <ArrowDown size={16}/></a></div></div>
 <div className="prep-boundary"><ShieldCheck size={21}/><p><b>Information, not an emergency assessment.</b> Use IMD, NDMA and local authorities for current warnings. In India call <a href="tel:112">112</a> for emergency assistance.</p></div>
 {!online&&<div className="prep-warning no-print" role="status"><WifiOff size={18}/>You are offline. Loaded guidance remains readable, but hazard updates and official links need connectivity. Save the self-contained handbook for reopening offline.</div>}
 <Handbook/><EarthquakeContext/>
 <footer className="prep-footer">MausamSetu · Experimental forecasting workbench · Preparedness interface inspired by the supplied Weather Project ZIP. No simulated alerts or AI-generated survival instructions are used.</footer>
 </div></main>;
}

'use client';
import {useCallback,useEffect,useState} from 'react';
import {DEFAULT_PREFS,validPreferences,type Preferences} from '@/lib/explorer';
const KEY='mausam-explorer-v1';
export function useExplorerPreferences(){
 const[prefs,setPrefs]=useState<Preferences>(DEFAULT_PREFS),[ready,setReady]=useState(false),[storageError,setError]=useState(false);
 useEffect(()=>{const read=()=>{try{const raw=localStorage.getItem(KEY);if(!raw){setPrefs(DEFAULT_PREFS);return;}const p=JSON.parse(raw);if(validPreferences(p))setPrefs(p);}catch{setError(true);}};read();setReady(true);const changed=(e:StorageEvent)=>{if(e.key===KEY)read();};window.addEventListener('storage',changed);return()=>window.removeEventListener('storage',changed);},[]);
 const update=useCallback((fn:(p:Preferences)=>Preferences)=>setPrefs(old=>{const next=fn(old);if(!validPreferences(next))return old;try{localStorage.setItem(KEY,JSON.stringify(next));setError(false);}catch{setError(true);}return next;}),[]);
 return {prefs,update,ready,storageError};
}

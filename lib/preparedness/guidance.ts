// Newly authored summaries. The supplied ZIP informed navigation, not safety claims.
export const GUIDANCE_REVIEWED='2026-09-26';
export type Guide={id:string;title:string;summary:string;steps:string[];source:string;sourceName:string};
export const GUIDES:Guide[]=[
 {id:'flood',title:'Floods',summary:'Floodwater and electrical hazards can be difficult to see.',source:'https://www.weather.gov/safety/flood-during',sourceName:'NOAA / National Weather Service',steps:[
  'Do not walk or drive through floodwater, or pass road barricades.',
  'Move away from rising water to higher ground when you can do so safely. Follow evacuation instructions from local authorities.',
  'Keep clear of submerged electrical equipment, outlets and fallen power lines.',
  'Keep receiving official updates. Rainfall on this app alone does not establish a flood warning.']},
 {id:'heat',title:'Extreme heat',summary:'Reduce heat exposure and check on people who may need help.',source:'https://www.weather.gov/safety/heat-during',sourceName:'NOAA / National Weather Service',steps:[
  'Reduce strenuous outdoor activity and take breaks in a cooler or shaded place.',
  'Drink water regularly. Follow medical advice if your fluid intake is restricted.',
  'Wear light, loose clothing and check on people who are older, unwell or living alone.',
  'Never leave a child, dependent person or pet unattended in a parked vehicle.']},
 {id:'lightning',title:'Thunderstorms & lightning',summary:'A substantial building is safer than an open shelter.',source:'https://www.weather.gov/safety/lightning-tips',sourceName:'NOAA / National Weather Service',steps:[
  'When you hear thunder, enter a substantial building or an enclosed metal-topped vehicle with its windows closed.',
  'Avoid plumbing, corded phones and equipment connected to mains electricity during the storm.',
  'Stay away from windows and open porches. Do not shelter beneath an isolated tree.',
  'Wait at least 30 minutes after the last thunder before leaving your shelter.']},
 {id:'cyclone',title:'Cyclone preparedness',summary:'Plan with local authorities before conditions deteriorate.',source:'https://www.weather.gov/safety/hurricane-plan',sourceName:'NOAA / National Weather Service',steps:[
  'Find out whether your home is in a local evacuation or storm-surge zone.',
  'Agree on a family communication plan and a destination before a storm arrives.',
  'Prepare essential supplies and check torches, batteries and emergency equipment.',
  'Use IMD and local disaster-management instructions for Indian cyclone warnings and evacuation decisions.']},
 {id:'earthquake',title:'Earthquakes',summary:'Protect yourself while shaking is occurring.',source:'https://www.usgs.gov/faqs/what-should-i-do-during-earthquake',sourceName:'US Geological Survey',steps:[
  'Drop, cover and hold on beneath a sturdy table or desk where possible.',
  'If indoors, stay inside during shaking. Keep away from windows and objects that may fall.',
  'If outside, move to an open space clear of buildings and power lines.',
  'If driving, stop safely away from bridges, overhead structures and power lines; remain in the vehicle until shaking stops.']},
 {id:'tsunami',title:'Coastal tsunami safety',summary:'Natural warning signs can require action before an official bulletin arrives.',source:'https://www.weather.gov/safety/tsunami-during',sourceName:'NOAA / National Weather Service',steps:[
  'In a coastal hazard area, strong or prolonged shaking, unusual rapid sea-level change, or an ocean roar can be natural warning signs.',
  'Protect yourself during shaking; as soon as safe, move to higher ground or inland along evacuation routes. Do not wait for this app to update.',
  'Stay off beaches and out of coastal waterways during a warning.',
  'Return only when authorities say it is safe; later waves may be larger. An earthquake marker is not a tsunami warning.']},
];
export const EMERGENCY={number:'112',label:'Emergency assistance in India',source:'https://www.mha.gov.in/en/commoncontent/emergency-response-support-system-erss'};
export const OFFICIAL_RESOURCES=[
 {title:'IMD weather warnings',description:'Weather warnings, nowcasts and cyclone bulletins.',url:'https://mausam.imd.gov.in/'},
 {title:'NDMA SACHET',description:'Official disaster-alert portal. Open the portal for current notices.',url:'https://sachet.ndma.gov.in/'},
 {title:'ERSS 112',description:'Government information on emergency assistance in India.',url:EMERGENCY.source},
];
export const KIT_SOURCE='https://www.usgs.gov/faqs/what-emergency-supplies-do-i-need-earthquake';
export const KIT_ITEMS=[
 {id:'water',label:'Drinking water and food',detail:'Plan supplies for household needs and local emergency guidance.'},
 {id:'medicines',label:'Essential medicines and first-aid kit',detail:'Check expiry dates and individual medical requirements.'},
 {id:'torch',label:'Torch and spare batteries',detail:'Test the equipment before storing it.'},
 {id:'radio',label:'Portable radio and backup power',detail:'Keep a way to receive information during outages.'},
 {id:'documents',label:'Important documents',detail:'Keep protected copies where you can reach them.'},
 {id:'plan',label:'Family contact and evacuation plan',detail:'Agree on a meeting place and a way to contact each other.'},
 {id:'needs',label:'Child, accessibility and pet needs',detail:'Include household-specific supplies and assistance plans.'},
 {id:'sanitation',label:'Sanitation supplies',detail:'Pack basic hygiene items and waste bags.'},
];
export type KitState={version:1;checked:string[]};
export function validKitState(value:unknown):value is KitState{
 const s=value as KitState;return !!s&&s.version===1&&Array.isArray(s.checked)&&s.checked.length<=KIT_ITEMS.length&&new Set(s.checked).size===s.checked.length&&s.checked.every(id=>KIT_ITEMS.some(item=>item.id===id));
}
export function escapeHtml(text:string):string{return text.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));}
export function handbookHtml(state:KitState):string{
 if(!validKitState(state))throw Error('Invalid preparedness checklist');
 const guides=GUIDES.map(g=>`<section><h2>${escapeHtml(g.title)}</h2><p>${escapeHtml(g.summary)}</p><ol>${g.steps.map(t=>`<li>${escapeHtml(t)}</li>`).join('')}</ol><p>Source: <a href="${escapeHtml(g.source)}" rel="noreferrer">${escapeHtml(g.sourceName)}</a></p></section>`).join('');
 const kit=KIT_ITEMS.map(item=>`<li>${state.checked.includes(item.id)?'[✓]':'[ ]'} <b>${escapeHtml(item.label)}</b> — ${escapeHtml(item.detail)}</li>`).join('');
 const resources=OFFICIAL_RESOURCES.map(r=>`<li><a href="${escapeHtml(r.url)}" rel="noreferrer">${escapeHtml(r.title)}</a>: ${escapeHtml(r.description)}</li>`).join('');
 return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>MausamSetu preparedness handbook</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:850px;margin:40px auto;padding:0 24px;color:#182b39}h1,h2{line-height:1.2}section{border-top:1px solid #ccd5dc;padding:20px 0;break-inside:avoid}a{color:#075a72;overflow-wrap:anywhere}.notice{border:2px solid #8a610e;padding:14px}li{margin:10px 0}@media print{body{margin:0;font-size:11pt}a:after{content:' (' attr(href) ')';font-size:9pt}}</style></head><body><h1>MausamSetu preparedness handbook</h1><p class="notice">General preparedness information, not a live alert or a substitute for local instructions. In India, contact <a href="tel:112">112</a> for emergency assistance. Outside India use the local emergency number.</p><p>Guidance reviewed ${GUIDANCE_REVIEWED}. This file works offline; external links require a connection. No current earthquake or weather warnings are included.</p>${guides}<section><h2>Your preparedness checklist</h2><p>Checked items are your own record, not a safety certification.</p><ul>${kit}</ul><p>Reference: <a href="${KIT_SOURCE}">USGS emergency supplies</a> and the planning sources above.</p></section><section><h2>Official resources</h2><ul>${resources}</ul></section></body></html>`;
}

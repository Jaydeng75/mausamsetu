import {NextRequest} from 'next/server';
export const dynamic='force-dynamic';
export async function GET(request:NextRequest){
 const q=request.nextUrl.searchParams,lat=Number(q.get('lat')),lng=Number(q.get('lng')),lead=Number(q.get('lead')??24),variable=q.get('variable')??'rain';
 if(!Number.isFinite(lat)||!Number.isFinite(lng)||Math.abs(lat)>90||Math.abs(lng)>180||![24,48,72].includes(lead)||!['rain','temperature','wind'].includes(variable))
  return Response.json({error:'Valid location, lead and variable are required.'},{status:400});
 const configured=process.env.MAUSAM_PUBLIC_BACKEND_URL;
 if(!configured)return Response.json({error:'Multi-shadow backend not configured'},{status:503});
 try{
  const origin=new URL(configured);if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password)throw Error('Invalid backend');
  const url=new URL('/public/multi-shadow/point',origin);url.search=new URLSearchParams({lat:String(lat),lng:String(lng),lead:String(lead),variable}).toString();
  const response=await fetch(url,{cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});const text=await response.text();
  if(text.length>100000)throw Error('Response too large');
  return new Response(text,{status:response.status,headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }catch{return Response.json({error:'Multi-shadow point unavailable; no substitute value was generated.'},{status:503,headers:{'Cache-Control':'no-store'}});}
}

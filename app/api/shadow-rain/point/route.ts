import {NextRequest} from 'next/server';
export const dynamic='force-dynamic';
export async function GET(request:NextRequest){
 const lat=Number(request.nextUrl.searchParams.get('lat')),lng=Number(request.nextUrl.searchParams.get('lng')),lead=Number(request.nextUrl.searchParams.get('lead')??24);
 if(!Number.isFinite(lat)||!Number.isFinite(lng)||!Number.isInteger(lead)||Math.abs(lat)>90||Math.abs(lng)>180||lead<0||lead>384)
  return Response.json({error:'Valid latitude, longitude and lead are required.'},{status:400});
 const configured=process.env.MAUSAM_PUBLIC_BACKEND_URL;
 if(!configured)return Response.json({error:'Shadow backend not configured'},{status:503});
 try{
  const origin=new URL(configured);
  if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password)throw Error('Invalid backend');
  const url=new URL('/public/shadow-rain/point',origin);
  url.search=new URLSearchParams({lat:String(lat),lng:String(lng),lead:String(lead)}).toString();
  const response=await fetch(url,{cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});
  const text=await response.text();
  if(text.length>100000)throw Error('Response too large');
  return new Response(text,{status:response.status,headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }catch{
  return Response.json({error:'Shadow point unavailable; no substitute value was generated.'},{status:503,headers:{'Cache-Control':'no-store'}});
 }
}

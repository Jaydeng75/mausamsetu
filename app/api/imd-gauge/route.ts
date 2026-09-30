export const dynamic='force-dynamic';
export async function GET(){
 const configured=process.env.MAUSAM_PUBLIC_BACKEND_URL;
 if(!configured)return Response.json({error:'IMD gauge backend not configured'},{status:503});
 try{
  const origin=new URL(configured);
  if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password)throw Error('Invalid backend');
  const response=await fetch(new URL('/public/imd-gauge',origin),{cache:'no-store',redirect:'error',signal:AbortSignal.timeout(10000)});
  const text=await response.text();
  if(text.length>8_000_000)throw Error('Response too large');
  return new Response(text,{status:response.status,headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }catch{return Response.json({error:'IMD gauge verification unavailable; no substitute evidence was generated.'},{status:503,headers:{'Cache-Control':'no-store'}});}
}

export const dynamic='force-dynamic';
export async function GET(){
 const configured=process.env.MAUSAM_PUBLIC_BACKEND_URL;
 if(!configured)return Response.json({error:'Shadow rainfall backend not configured'},{status:503});
 try{
  const origin=new URL(configured);
  if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password)throw Error('Invalid backend');
  const response=await fetch(new URL('/public/shadow-rain',origin),{cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw Error('Shadow rainfall status unavailable');
  const text=await response.text();
  if(text.length>2000000)throw Error('Response too large');
  return new Response(text,{headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }catch{
  return Response.json({error:'Shadow rainfall status unavailable; no substitute evidence was generated.'},{status:503,headers:{'Cache-Control':'no-store'}});
 }
}

export const dynamic='force-dynamic';
export async function GET(){
 const configured=process.env.MAUSAM_PUBLIC_BACKEND_URL;
 if(!configured)return Response.json({error:'Rainfall verification backend not configured'},{status:503});
 try{
  const origin=new URL(configured);
  if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password)throw Error('Invalid backend');
  const response=await fetch(new URL('/public/rain-verification',origin),{cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw Error('Rainfall verification unavailable');
  const text=await response.text();if(text.length>2000000)throw Error('Response too large');
  return new Response(text,{headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
 }catch{return Response.json({error:'Rainfall verification unavailable; no scores were substituted.'},{status:503,headers:{'Cache-Control':'no-store'}});}
}

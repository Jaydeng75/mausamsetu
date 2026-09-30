export const dynamic='force-dynamic';
export async function GET(){
 try{
  const origin=new URL(process.env.MAUSAM_PUBLIC_BACKEND_URL||'');
  if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password)throw Error('Invalid origin');
  const r=await fetch(new URL('/public/mosdac',origin),{cache:'no-store',redirect:'error',signal:AbortSignal.timeout(10000)});
  if(!r.ok)throw Error('MOSDAC report unavailable');
  const text=await r.text();if(text.length>100000)throw Error('Oversize report');
  const data=JSON.parse(text);if(data.schema_version!==1)throw Error('Unsupported report');
  return Response.json(data,{headers:{'Cache-Control':'no-store'}});
 }catch{return Response.json({error:'MOSDAC satellite context unavailable; no substitute observations generated.'},{status:503,headers:{'Cache-Control':'no-store'}})}
}

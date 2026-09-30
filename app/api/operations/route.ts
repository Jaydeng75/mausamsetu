export const dynamic='force-dynamic';
export async function GET(){
 const configured=process.env.MAUSAM_PUBLIC_BACKEND_URL;
 if(!configured)return Response.json({status:'not_connected',message:'No continuously published backend is configured.'},{headers:{'Cache-Control':'no-store'}});
 try{
  const origin=new URL(configured);
  if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password)throw Error('Invalid origin');
  const response=await fetch(new URL('/public/status',origin),{cache:'no-store',redirect:'error',signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw Error('Status unavailable');
  const text=await response.text();if(text.length>65536)throw Error('Status too large');
  const value=JSON.parse(text);if(value.schema_version!==1)throw Error('Unsupported status');
  return Response.json(value,{headers:{'Cache-Control':'no-store'}});
 }catch{return Response.json({status:'unavailable',message:'The backend has not published current operational status.'},{status:503,headers:{'Cache-Control':'no-store'}});}
}

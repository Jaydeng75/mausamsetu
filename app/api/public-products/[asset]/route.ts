export async function GET(_request:Request,context:{params:Promise<{asset:string}>}){
 const {asset}=await context.params;
 if(!['latest.json','global-latest.json'].includes(asset)&&! /^(?:public|global)-\d{8}-\d{2}-[a-f0-9]{12}\.json$/.test(asset))
  return Response.json({error:'Unknown public asset'},{status:404});
 const configured=process.env.MAUSAM_PUBLIC_BACKEND_URL;
 if(!configured)return Response.json({error:'Published backend archive not configured'},{status:503});
 try{
  const origin=new URL(configured);
  if(!['http:','https:'].includes(origin.protocol)||origin.username||origin.password||origin.search||origin.hash)
   throw Error('Invalid backend configuration');
  const upstream=await fetch(new URL('/public/products/'+asset,origin),{
   signal:AbortSignal.timeout(20000),cache:'no-store',redirect:'error'});
  if(!upstream.ok||!upstream.body)throw Error('Published asset unavailable');
  const reader=upstream.body.getReader(),chunks:Uint8Array[]=[];let size=0;
  while(true){const {done,value}=await reader.read();if(done)break;
   size+=value.byteLength;if(size>32000000){await reader.cancel();throw Error('Asset too large');}chunks.push(value);}
  const bytes=new Uint8Array(size);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  return new Response(bytes,{headers:{'Content-Type':'application/json','X-Content-Type-Options':'nosniff',
   'Cache-Control':['latest.json','global-latest.json'].includes(asset)?'no-store':'public, max-age=31536000, immutable'}});
 }catch{
  return Response.json({error:'Backend archive unavailable; no synthetic or stale fallback was substituted'},{status:503});
 }
}

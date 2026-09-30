export async function GET(){
 const connected=Boolean(process.env.MAUSAM_PUBLIC_BACKEND_URL);
 let productsBase=connected?'/api/public-products/':'/data/products/';
 const direct=process.env.MAUSAM_PUBLIC_PRODUCTS_ORIGIN;
 if(direct){
  try{
   const origin=new URL(direct);
   if(origin.protocol!=='https:'||origin.username||origin.password||origin.pathname!=='/'||origin.search||origin.hash)throw Error('Invalid origin');
   productsBase=new URL('/public/products/',origin).href;
  }catch{return Response.json({error:'Invalid public product origin'},{status:503});}
 }
 return Response.json({
  mode:connected?'connected_archive':'packaged_snapshot',
  india_products_base:productsBase,
  global_products_base:productsBase,
 },{headers:{'Cache-Control':'no-store'}});
}

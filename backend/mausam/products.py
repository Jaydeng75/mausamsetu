"""Optional scientific artifact exports. Rasterio, Zarr, and boto3 are science extras."""
from pathlib import Path
import numpy as np

def export_zarr(dataset,destination):
    if Path(destination).exists():raise FileExistsError('Versioned Zarr products are immutable')
    dataset.to_zarr(destination,mode='w',consolidated=True)

def export_geotiff(field,destination):
    import rasterio
    from rasterio.transform import from_origin
    lat=np.asarray(field.lat);lon=np.asarray(field.lon)
    if len(lat)<2 or len(lon)<2:raise ValueError('At least two coordinates per axis are required')
    dx=np.abs(np.diff(lon));dy=np.abs(np.diff(lat))
    if not np.allclose(dx,dx[0]) or not np.allclose(dy,dy[0]):raise ValueError('COG export requires a regular geographic grid')
    # Raster rows go north to south; coordinate bounds are half a grid spacing from centers.
    field=field.sortby('lat',ascending=False).sortby('lon');data=np.asarray(field,dtype='float32');transform=from_origin(float(field.lon.min())-dx[0]/2,float(field.lat.max())+dy[0]/2,dx[0],dy[0])
    with rasterio.open(destination,'w',driver='COG',height=data.shape[0],width=data.shape[1],count=1,dtype='float32',crs='EPSG:4326',transform=transform,nodata=np.nan,compress='DEFLATE') as dst:
        dst.write(data,1);dst.update_tags(**{k:str(v) for k,v in field.attrs.items()})

def upload_immutable(path,bucket,key,endpoint_url=None):
    import boto3,hashlib
    data=Path(path).read_bytes();digest=hashlib.sha256(data).hexdigest()
    client=boto3.client('s3',endpoint_url=endpoint_url)
    client.put_object(Bucket=bucket,Key=key,Body=data,IfNoneMatch='*',Metadata={'sha256':digest})
    return {'uri':f's3://{bucket}/{key}','sha256':digest}

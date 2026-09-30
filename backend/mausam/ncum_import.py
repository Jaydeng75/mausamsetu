"""Import explicitly authorized NCUM numerical files without assuming a provider API."""
import argparse,hashlib,json,shutil
from pathlib import Path
import xarray as xr
from .public_data import write_json
from .research_access import inventory_grib


def ingest(source,metadata,output):
    source,output=Path(source),Path(output)
    required={'product','model_version','initialization','licence','authorization_reference','expected_sha256','provider_interface'}
    if not required.issubset(metadata) or any(not metadata[k] for k in required):raise ValueError('Missing product/access/provenance metadata')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=metadata['expected_sha256']:raise ValueError('NCUM checksum mismatch')
    if metadata['product'] not in ('NCUM-G','NCUM-R'):raise ValueError('Explicit NCUM product required')
    if 'public' in output.resolve().parts:raise ValueError('Import to private staging; distribution rights must be checked separately')
    if source.suffix in ('.grib','.grib2','.grb2'):
        inventory=inventory_grib(source)
    else:
        with xr.open_dataset(source) as ds:
            if not ({'latitude','longitude'}.issubset(ds.coords) or {'lat','lon'}.issubset(ds.coords)):raise ValueError('Geographic coordinates required')
            inventory={'dimensions':dict(ds.sizes),'variables':{k:{'dimensions':list(v.dims),'units':v.attrs.get('units')} for k,v in ds.data_vars.items()}}
    output.mkdir(parents=True,exist_ok=True)
    target=output/(digest+source.suffix)
    if not target.exists():shutil.copyfile(source,target)
    write_json(output/(digest+'.json'),{**metadata,'sha256':digest,'file':target.name,'inventory':inventory,'status':'staged_requires_product_specific_normalization'})
    return target


def main():
    p=argparse.ArgumentParser();p.add_argument('file',type=Path);p.add_argument('--metadata',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(ingest(a.file,json.loads(a.metadata.read_text()),a.output))


if __name__=='__main__':main()

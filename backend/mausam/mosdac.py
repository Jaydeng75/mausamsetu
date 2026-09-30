"""Private MOSDAC IMR acquisition and public value-added regional summaries.

Rain rates describe a satellite scan, never a 24-hour accumulation or gauge truth.
Official interface: https://www.mosdac.gov.in/downloadapi-manual
"""
import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h5py
import httpx
import numpy as np

ORIGIN = 'https://mosdac.gov.in'
DATASET = '3SIMG_L2G_IMR'
NAME = re.compile(r'3SIMG_\d{2}[A-Z]{3}\d{4}_\d{4}_L2G_IMR_V\d{2}R\d{2}\.h5')
REGIONS = {'India bounding box': (68, 6, 98, 38), 'North': (73, 27, 82, 35),
           'West': (68, 20, 77, 28), 'Central': (77, 19, 85, 27),
           'East': (85, 20, 90, 27), 'Northeast': (89, 22, 98, 29),
           'South': (73, 6, 85, 19)}


def utcnow():
    return datetime.now(timezone.utc)


def atomic(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.part')
    tmp.write_text(json.dumps(value, allow_nan=False, indent=2))
    tmp.chmod(mode)
    tmp.replace(path)


def string(value):
    return value.decode() if isinstance(value, bytes) else str(value)


def physical(dataset):
    raw = np.asarray(dataset[:], dtype=float)
    valid = np.isfinite(raw)
    for key in ('_FillValue', 'missing_value'):
        if key in dataset.attrs:
            for fill in np.atleast_1d(dataset.attrs[key]):
                valid &= raw != float(fill)
    if 'valid_range' in dataset.attrs:
        lo, hi = dataset.attrs['valid_range']
        valid &= (raw >= lo) & (raw <= hi)
    scale = float(np.asarray(dataset.attrs.get('scale_factor', 1)).item())
    offset = float(np.asarray(dataset.attrs.get('add_offset', 0)).item())
    if not np.isfinite([scale, offset]).all() or scale <= 0:
        raise ValueError('Invalid scale')
    return np.where(valid, raw * scale + offset, np.nan)


def summarize(path, entry, now=None):
    now = now or utcnow()
    if not NAME.fullmatch(path.name) or entry['identifier'] != path.name:
        raise ValueError('Unexpected product identity')
    with h5py.File(path, 'r') as f:
        if string(f.attrs['Satellite_Name']) != 'INSAT-3DS' or string(f.attrs['Processing_Level']) != 'L2G':
            raise ValueError('Unsupported satellite or processing level')
        if string(f.attrs['HDF_Product_File_Name']) != path.name:
            raise ValueError('Embedded filename mismatch')
        start = datetime.strptime(string(f.attrs['Acquisition_Start_Time']), '%d-%b-%YT%H:%M:%S.%f').replace(tzinfo=timezone.utc)
        end = datetime.strptime(string(f.attrs['Acquisition_End_Time']), '%d-%b-%YT%H:%M:%S.%f').replace(tzinfo=timezone.utc)
        if not timedelta(0) < end - start <= timedelta(minutes=35) or end > now + timedelta(minutes=5):
            raise ValueError('Invalid acquisition interval')
        cat_start, cat_end = [datetime.fromisoformat(x.replace('Z', '+00:00')) for x in entry['dcDate'].split('/')]
        if not cat_start <= start < end <= cat_end:
            raise ValueError('Catalogue and HDF acquisition disagree')
        units = string(f['IMR'].attrs['units'])
        if units != 'mm/hr' or string(f['latitude'].attrs['units']) != 'degrees_north' or string(f['longitude'].attrs['units']) != 'degrees_east':
            raise ValueError('Unsupported units')
        latitude, longitude = physical(f['latitude']), physical(f['longitude'])
        values = physical(f['IMR'])
        if values.shape != (1, latitude.size, longitude.size) or latitude.ndim != 1 or longitude.ndim != 1:
            raise ValueError('Invalid grid dimensions')
        for axis, limit in ((latitude, 90), (longitude, 180)):
            if not np.isfinite(axis).all() or (np.abs(axis) > limit).any() or not ((np.diff(axis) > 0).all() or (np.diff(axis) < 0).all()):
                raise ValueError('Invalid coordinates')
        values = np.where(values[0] >= 0, values[0], np.nan)
        regions = []
        for label, (west, south, east, north) in REGIONS.items():
            y = (latitude >= south) & (latitude <= north)
            x = (longitude >= west) & (longitude <= east)
            a = values[np.ix_(y, x)]
            good = np.isfinite(a)
            if a.size == 0 or not good.any():
                raise ValueError('Empty region')
            weights = np.broadcast_to(np.cos(np.deg2rad(latitude[y]))[:, None], a.shape)
            regions.append({'name': label, 'bounds': [west, south, east, north],
                            'valid_cells': int(good.sum()), 'coverage_fraction': float(good.mean()),
                            'mean_rate': float(np.average(a[good], weights=weights[good])),
                            'p95_rate': float(np.percentile(a[good], 95)),
                            'max_rate': float(np.max(a[good])),
                            'wet_area_fraction': float(np.average((a[good] >= 0.1), weights=weights[good]))})
        version = string(f.attrs.get('Software_Version', 'not provided'))
    return {'identifier': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'catalogue_interval': entry['dcDate'], 'scan_start': start.isoformat(), 'scan_end': end.isoformat(),
            'retrieved_at': now.isoformat(), 'processing_version': version, 'units': units,
            'age_hours': round((now-end).total_seconds()/3600, 2), 'regions': regions,
            'quality_flags': 'No per-pixel quality flag is provided in this IMR product; fill values and invalid cells are excluded.'}


def cycle(root, public, credentials, client=None):
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    status_path = public / 'mosdac-status.json'
    previous = json.loads(status_path.read_text()) if status_path.exists() else {}
    status = {'schema_version': 1, 'checked_at': utcnow().isoformat(), 'dataset_id': DATASET,
              'state': 'unavailable', 'data_kind': 'satellite_rain_rate_context',
              'attribution': 'Data Source: MOSDAC/SAC/ISRO. https://mosdac.gov.in',
              'catalogue_url': 'https://mosdac.gov.in/catalog-app/satellite.php',
              'policy_url': 'https://www.mosdac.gov.in/data-access-policy',
              'forecast_use': 'Context only; not assimilated, calibrated or used for model weights.',
              'limitations': ['Rain rate during a satellite scan, not a 24-hour rainfall total or a forecast.',
                  'Regional boxes include neighbouring countries and ocean; they are not state or India land-only statistics.',
                  'Satellite retrievals are not gauge truth. No hazard warning is inferred.',
                  'Raw MOSDAC files remain private; only derived regional summaries are published.',
                  'Exact-window verification requires a complete time series and independently validated accumulation semantics.'],
              'latest': previous.get('latest')}
    own = client is None
    client = client or httpx.Client(timeout=45, follow_redirects=False)
    try:
        r = client.get(ORIGIN+'/apios/datasets.json', params={'datasetId': DATASET, 'count': 3})
        r.raise_for_status()
        entries = r.json().get('entries', [])
        if not entries:
            raise ValueError('Empty catalogue')
        status['catalogue_latest'] = {k:entries[0].get(k) for k in ('identifier', 'dcDate')}
        if not credentials.is_file():
            status['state'] = 'credentials_required'
        else:
            # Never retry a rejected password automatically: avoid provider account lockout.
            rejected = root/'authentication-rejected.json'
            if rejected.exists() and rejected.stat().st_mtime >= credentials.stat().st_mtime:
                status['state'] = 'authentication_rejected'
            else:
                token = None
                processed = []
                for entry in entries:
                    name = entry['identifier']
                    if not NAME.fullmatch(name) or not str(entry['id']).isdigit():
                        raise ValueError('Invalid catalogue identity')
                    path = root/name
                    if not path.exists():
                        if token is None:
                            auth = json.loads(credentials.read_text())
                            r = client.post(ORIGIN+'/download_api/gettoken', json={'username':auth['username'], 'password':auth['password']})
                            if r.status_code in (400,401,403):
                                atomic(rejected, {'checked_at': utcnow().isoformat()})
                                status['state'] = 'authentication_rejected'
                                break
                            r.raise_for_status()
                            token = r.json()['access_token']
                        tmp = path.with_suffix('.part')
                        try:
                            with client.stream('GET', ORIGIN+'/download_api/download', params={'id':str(entry['id'])}, headers={'Authorization':'Bearer '+token}) as response:
                                response.raise_for_status()
                                size = 0
                                with tmp.open('wb') as output:
                                    os.chmod(tmp, 0o600)
                                    for chunk in response.iter_bytes():
                                        size += len(chunk)
                                        if size > 8_000_000:
                                            raise ValueError('Product exceeds bound')
                                        output.write(chunk)
                            with tmp.open('rb') as stream:
                                if stream.read(8) != b'\x89HDF\r\n\x1a\n':
                                    raise ValueError('Not HDF5')
                            tmp.replace(path)
                        finally:
                            tmp.unlink(missing_ok=True)
                    try:
                        report = summarize(path, entry)
                    except Exception:
                        if not path.with_suffix('.json').exists():
                            path.unlink(missing_ok=True)
                        raise
                    provenance = path.with_suffix('.json')
                    if provenance.exists():
                        saved = json.loads(provenance.read_text())
                        if saved['sha256'] != report['sha256']:
                            raise ValueError('Archive checksum mismatch')
                        report['retrieved_at'] = saved['retrieved_at']
                    else:
                        atomic(provenance, report)
                    processed.append(report)
                if processed and status['state'] != 'authentication_rejected':
                    status['latest'] = max(processed, key=lambda x:x['scan_end'])
                    status['state'] = 'available' if status['latest']['age_hours'] <= 6 else 'delayed'
                status['private_archive_files'] = len(list(root.glob('*.h5')))
        # Retain two weeks of private samples, never delete arbitrary files or public products.
        cutoff = utcnow().timestamp()-14*86400
        for path in root.glob('*.h5'):
            if NAME.fullmatch(path.name) and path.stat().st_mtime < cutoff:
                path.unlink(); path.with_suffix('.json').unlink(missing_ok=True)
    except Exception as error:
        status['state'] = 'unavailable'
        status['error_type'] = type(error).__name__  # no provider body, URLs with tokens or secrets
    finally:
        if own:
            client.close()
    if status.get('latest'):
        status['latest']['age_hours'] = round((utcnow()-datetime.fromisoformat(status['latest']['scan_end'])).total_seconds()/3600,2)
    atomic(status_path, status, 0o644)
    return status


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--public',type=Path,required=True)
    parser.add_argument('--credentials',type=Path,required=True)
    parser.add_argument('--loop',action='store_true')
    args=parser.parse_args()
    os.umask(0o077)
    while True:
        result=cycle(args.root,args.public,args.credentials)
        print(json.dumps({k:result.get(k) for k in ('checked_at','state','error_type','private_archive_files')}),flush=True)
        if not args.loop: break
        time.sleep(1800)

"""Reproducible WeatherBench 2 HRES vs ERA5 evaluation outside India.

Uses the published 64x32 conservative grids. ERA5 is reanalysis, not station truth.
Date/lead selection is exact; unavailable values fail rather than being filled.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import xarray as xr

from .public_data import write_json

ROOT = 'https://storage.googleapis.com/weatherbench2/datasets/'
HRES = ROOT + 'hres/2016-2022-0012-64x32_equiangular_conservative.zarr'
ERA5 = ROOT + 'era5/1959-2023_01_10-6h-64x32_equiangular_conservative.zarr'
VARIABLES = {'temperature': ('2m_temperature', '°C', 1, -273.15),
    'wind': ('10m_wind_speed', 'm/s', 1, 0),
    'pressure': ('mean_sea_level_pressure', 'hPa', .01, 0),
    'rain': ('total_precipitation_24hr', 'mm', 1000, 0)}


def in_ring(x, y, ring):
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]+ring[:1]):
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
    return inside


def outside_india(lat, lon, geojson):
    country = next(f for f in geojson['features'] if f['properties']['ADMIN'] == 'India')
    g = country['geometry']
    polygons = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
    return np.array([[not any(in_ring(float(x), float(y), p[0]) and not any(in_ring(float(x), float(y), hole) for hole in p[1:]) for p in polygons) for x in lon] for y in lat])


def scores(prediction, truth, latitude, include):
    error = np.asarray(prediction, dtype=float)-np.asarray(truth, dtype=float)
    if error.shape != truth.shape or error.ndim != 3 or error.shape[1:] != include.shape:
        raise ValueError('Evaluation requires aligned time × latitude × longitude arrays')
    if not np.isfinite(error[:, include]).all():
        raise ValueError('Missing forecast or reference values in evaluation domain')
    w = np.broadcast_to(np.cos(np.deg2rad(latitude))[None, :, None]*include[None], error.shape)
    if w.sum() <= 0:
        raise ValueError('Empty evaluation domain')
    error = np.where(w > 0, error, 0)
    return {'rmse': float(np.sqrt(np.sum(w*error**2)/w.sum())),
        'mae': float(np.sum(w*np.abs(error))/w.sum()), 'bias': float(np.sum(w*error)/w.sum()),
        'initializations': error.shape[0], 'grid_cells': int(include.sum()), 'pairs': int(error.shape[0]*include.sum())}


def main():
    import fsspec
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2020-01-01')
    p.add_argument('--days', type=int, default=31)
    p.add_argument('--countries', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 1 <= args.days <= 366:
        raise ValueError('Select 1–366 initialization days per job')
    datasets = [xr.open_zarr(fsspec.get_mapper(url), consolidated=True, decode_timedelta=True) for url in (HRES, ERA5)]
    fc, obs = [d.assign_coords(longitude=((d.longitude+180)%360)-180).sortby('longitude').sortby('latitude', ascending=False) for d in datasets]
    if not np.array_equal(fc.latitude, obs.latitude) or not np.array_equal(fc.longitude, obs.longitude):
        raise ValueError('WeatherBench grids do not match')
    lat, lon = fc.latitude.values, fc.longitude.values
    mask = outside_india(lat, lon, json.loads(args.countries.read_text()))
    times = np.datetime64(args.start, 'ns') + np.arange(args.days)*np.timedelta64(1, 'D')
    leads = list(range(24, 169, 24))
    report, snapshots = [], {'HRES': {}, 'ERA5': {}}
    for lead in leads:
        snapshots['HRES'][str(lead)], snapshots['ERA5'][str(lead)] = {}, {}
        valid = times + np.timedelta64(lead, 'h')
        for key, (name, unit, scale, offset) in VARIABLES.items():
            f = fc[name].sel(time=times, prediction_timedelta=np.timedelta64(lead, 'h')).transpose('time','latitude','longitude').compute().values*scale+offset
            o = obs[name].sel(time=valid).transpose('time','latitude','longitude').compute().values*scale+offset
            report.append({'variable': key, 'unit': unit, 'lead': lead, **scores(f,o,lat,mask)})
            for source, array in [('HRES', f), ('ERA5', o)]:
                snapshots[source][str(lead)][key] = [round(float(v),3) if allowed and np.isfinite(v) else None for v, allowed in zip(array[0].ravel(),mask.ravel())]
        print(f'WeatherBench +{lead}h evaluated for {args.days} initializations', flush=True)
    licences = {}
    for name in ('hres','era5'):
        url = ROOT+name+'/LICENSE'
        r = httpx.get(url, timeout=30); r.raise_for_status()
        licences[name] = {'url': url, 'sha256': hashlib.sha256(r.content).hexdigest()}
    value = {'schema_version': 1, 'data_kind': 'historical_evaluation', 'run_id': 'wb2-hres-era5-'+args.start,
        'initialization': args.start+'T00:00:00Z', 'evaluation_start': str(times[0]), 'evaluation_end': str(times[-1]),
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'initializations': args.days, 'leads': leads,
        'latitude': lat.tolist(), 'longitude': lon.tolist(), 'outside_india': mask.ravel().tolist(), 'sources': snapshots,
        'scores': report, 'dataset_urls': {'HRES': HRES, 'ERA5': ERA5}, 'licences': licences,
        'grid_method': 'WeatherBench 2 published 64×32 conservative grid; India excluded by Natural Earth cell-centre mask',
        'reference': 'ERA5 reanalysis; not independent station observations', 'calibrated': False,
        'attribution': 'HRES © ECMWF, CC BY 4.0; sampled via WeatherBench 2. Contains modified Copernicus Climate Change Service information (2020). Neither the European Commission nor ECMWF is responsible for use. WeatherBench 2: Rasp et al. (2024).'}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]
    name = f'weatherbench-{args.start}-{digest}.json'
    write_json(args.output/name, value)
    write_json(args.output/'weatherbench-latest.json', {'path': name, 'sha256': hashlib.sha256((args.output/name).read_bytes()).hexdigest()})
    print(json.dumps({'published': name, 'scores': len(report), 'excluded_india_cells': int((~mask).sum())}))


if __name__ == '__main__':
    main()

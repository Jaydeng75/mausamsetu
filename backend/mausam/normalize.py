import numpy as np
import xarray as xr

def convert_units(values,variable,units):
    a=np.asarray(values,dtype=float)
    if variable=='rain':
        if units in ('m','m water equivalent'):a=a*1000
        elif units not in ('mm','kg m-2'):raise ValueError('Unsupported precipitation units')
        if (a[np.isfinite(a)]<0).any():raise ValueError('Negative precipitation')
    elif variable=='temperature':
        if units=='K':a=a-273.15
        elif units not in ('degC','°C'):raise ValueError('Unsupported temperature units')
    elif variable in ('wind_u','wind_v'):
        if units=='km h-1':a=a/3.6
        elif units not in ('m s-1','m/s'):raise ValueError('Unsupported wind units')
    elif variable=='pressure':
        if units=='Pa':a=a/100
        elif units!='hPa':raise ValueError('Unsupported pressure units')
    return a

def precipitation_intervals(cumulative,leads,run_ids,interval_hours=6):
    a=np.asarray(cumulative,dtype=float); leads=np.asarray(leads)
    if len(a)!=len(leads) or len(run_ids)!=len(leads):raise ValueError('Mismatched accumulation inputs')
    if len(set(run_ids))!=1:raise ValueError('Cannot subtract accumulations from different runs')
    if not np.all(np.diff(leads)==interval_hours):raise ValueError('Missing or irregular accumulation interval')
    delta=np.diff(a,axis=0)
    if np.any(delta[np.isfinite(delta)] < -1e-6):raise ValueError('Accumulation reset detected; quarantine input')
    return np.maximum(delta,0)

def rotate_wind(u,v,angle_radians):
    return u*np.cos(angle_radians)-v*np.sin(angle_radians),u*np.sin(angle_radians)+v*np.cos(angle_radians)

def regrid(field,target,variable):
    if variable=='rain':
        try:import xesmf as xe
        except ImportError as e:raise RuntimeError('Conservative rain regridding requires xESMF/ESMF and cell bounds') from e
        for grid in [field,target]:
            if 'lat_b' not in grid or 'lon_b' not in grid:raise ValueError('Conservative regridding requires cell bounds')
        return xe.Regridder(field,target,'conservative',unmapped_to_nan=True)(field)
    return field.interp(lat=target.lat,lon=target.lon,method='linear')

def open_forecast(path,variable,units):
    engine='cfgrib' if str(path).endswith(('.grib','.grib2','.grb2')) else None
    ds=xr.open_dataset(path,engine=engine)
    if variable not in ds:raise ValueError(f'Missing variable: {variable}')
    da=ds[variable]
    names={k:('lat' if k=='latitude' else 'lon') for k in ['latitude','longitude'] if k in da.dims}
    da=da.rename(names)
    if not {'lat','lon'}.issubset(da.dims):raise ValueError('A geographic latitude-longitude grid is required')
    if da.lat.ndim!=1 or da.lon.ndim!=1:raise ValueError('Curvilinear grids require a source-specific adapter')
    if np.unique(da.lat).size!=da.lat.size or np.unique(da.lon).size!=da.lon.size:raise ValueError('Duplicate grid coordinates')
    da=da.assign_coords(lon=((da.lon+180)%360)-180).sortby('lon').sortby('lat')
    da.data=convert_units(da.values,variable,units)
    return da

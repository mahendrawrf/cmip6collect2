import myconfig
from mydataset import dir2url
from glob import glob
import os
from subprocess import Popen, PIPE
import pandas as pd
import time

def doit(command,verbose=False): 
    cmd = command.split(' ')
    try:
        p = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
    except:
        print(f'failure: {cmd}')
        return 1
    
    stdout, stderr = p.communicate()

    if verbose:
        print(stdout)
        print(stderr)

    return 0

def set_bnds_as_coords(ds):
    new_coords_vars = [var for var in ds.data_vars if 'bnds' in var
                       or 'bounds' in var]
    ds = ds.set_coords(new_coords_vars)
    return ds

def set_bnds_as_coords_drop_height(ds):
    ds = set_bnds_as_coords(ds)
    if 'height' in ds.coords:
        ds = ds.drop('height')
    return ds

def set_bnds_as_coords_drop_bnds(ds):
    ds = set_bnds_as_coords(ds)
    if 'bnds' in ds.coords:
        ds = ds.drop('bnds')
    return ds


from functools import partial
def getFolderSize(p):
    prepend = partial(os.path.join, p)
    return sum([(os.path.getsize(f) if os.path.isfile(f) else
                                  getFolderSize(f)) for f in
                map(prepend, os.listdir(p))])

def exception_handler(func):   
    def inner_function(*args, **kwargs):
        #print(f'call {func.__name__}:')
        try:
            #print(*args, **kwargs)
            result = func(*args, **kwargs) 
        except:
            result = f"{func.__name__} failed"
        return result
    return inner_function

def str_match(x,y):
    return (x==y)|(x=='all')

def id_match(x,y):
    result = True
    x_tup = x.split('/')
    y_tup = y.split('/')
    result = [str_match(x,y) for x,y in zip(x_tup,y_tup)]
    return False not in result

def read_codes(ds_dir):
    dex = pd.read_csv('csv/error_codes.csv',skipinitialspace=True)
    codes = []
    for item, row in dex.iterrows():
        if id_match(row.ds_dir,ds_dir):
            codes += [row.code]
    return codes

@exception_handler
def Check(ds_dir,version,dir2local):
    exception = ''

    df_GCS = myconfig.df_GCS
    fs = myconfig.fs

    codes = read_codes(ds_dir)
    if 'noUse' in codes:
        exception =  'noUse in codes'
        return 1, exception 

    dGCS = df_GCS[df_GCS.ds_dir == ds_dir]
    if len(dGCS) > 0:
       version_GCS = sorted(df_GCS[df_GCS.ds_dir == ds_dir].version.unique())[-1]
    else:
       version_GCS = '0'

    print('this version:',version,'cloud version:',version_GCS)

    cstore = df_GCS[(df_GCS.ds_dir == ds_dir)&(df_GCS.version==version)]
    if len(cstore) > 0:
        exception = 'same version already in cloud catalog'
        return 1, exception 

    if int(version[-8:]) <= int(version_GCS):
        print('cloud, ESGF versions:', version_GCS, version[-8:])
        exception = 'same or later version already in cloud catalog'
        return 1, exception 

    gsurl_new = dir2url(ds_dir)
    #print('gsurl_new',gsurl_new)
    #gsurl_old = dir2url(ds_dir).replace('/CMIP6/','/')

    exists = False
    try:
        contents = fs.ls(gsurl_new)
        if any(f"/v{version}" in s for s in contents):
            exception = 'store already in cloud'
            exists = True
            return 1, exception
    except:
        exists = False
    #try:
    #    contents = fs.ls(gsurl_old)
    #    if any("zmetadata" in s for s in contents):
    #        exception = 'store already in cloud'
    #        exists = True
    #        return 1, exception
    #except:
    #    exists = False

    # is zarr already in cloud?  Unreliable
    
    # does zarr exist on active drive?  
    zbdir = f"{dir2local(ds_dir)}/v{version}"

    contents = glob(f'{zbdir}/*')

    if any("zmetadata" in s for s in contents):
        exception = 'store already exists locally, but not in cloud'
        return 2, exception 
    
    return 0, exception

import requests
import shutil
@exception_handler
def Download(ds_dir):
    gfiles = []
    check_size = True
    df_needed = myconfig.df_needed

    df = df_needed[df_needed.ds_dir == ds_dir]

    nversions = df.version_id.nunique()
    versions = sorted(df.version_id.unique())
    lastversion = sorted(df.version_id.unique())[-1]
    if nversions > 1:
       codes = read_codes(ds_dir)
       if 'allow_versions' in codes:
           print('allowing multiple versions',versions)
       else:
           print('keeping only last version',lastversion,' of',versions)
           df = df[df.version_id == lastversion]

    # df = df[~df.ncfile.str.contains('areacello_Ofx_historical_NorESM2-LM_r1i1p1f1_gn.nc')]
    df = df[~df.ncfile.str.contains('volcello_Ofx_historical_NorESM2-LM_r1i1p1f1_gr.nc')]

    lendf = len(df)
    dfstartn = df.start.nunique()
    if lendf != dfstartn:
       trouble = f"noUse, netcdf files overlapping in time? {lendf} and {dfstartn}"
       return df.ncfile.values,lastversion,2,trouble

    files = sorted(df.ncfile.unique())
    tmp = myconfig.local_source_prefix

    for file in files:
        save_file = tmp + file
        df_file = df[df.ncfile == file]
        expected_size = int(float(df_file.file_size.values[0]))
        url = df_file.url.values[0]
        print(url)

        if os.path.isfile(save_file):
            if abs(os.path.getsize(save_file) - expected_size) <= 1000 :
                gfiles += [save_file]
                continue  # already have, don't need to get it again
        try:
            #r = requests.get(url, timeout=3.1, stream=True)
            #headers = {'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.111 Safari/537.36'}
            headers = {}
            if 'esgf-data3.diasjp.net' in url:
                r = requests.get(url, headers=headers, timeout=(30, 14), stream=True)
            elif 'esgf-data.ucar.edu' in url:
                r = requests.get(url, headers=headers, timeout=(5, 14), stream=True) 
            else:   
                r = requests.get(url, timeout=(5, 14), stream=True)
            #print(r.headers['content-type'])
            with open(save_file, 'wb') as f:
                shutil.copyfileobj(r.raw, f)  
            command = f'touch {save_file}'
            doit(command)
        except:
            trouble = 'Server not responding for: ' + url 
            return [],lastversion,1,trouble

        if check_size:
            actual_size = os.path.getsize(save_file)
            if actual_size != expected_size:
                if abs(actual_size - expected_size) > 200:
                    trouble = 'netcdf download not complete'
                    return [],lastversion,1,trouble

        gfiles += [save_file]
        time.sleep(2)
                           
    return sorted(gfiles),lastversion,0,''

import warnings
import datetime
import numpy as np
import xarray as xr
@exception_handler
def ReadFiles(ds_dir, gfiles, version, dir2dict):
    table_id = dir2dict(ds_dir)['table_id']

    dstr = ''
    # guess chunk size by looking a first file: (not always a good choice - e.g. cfc11)
    nc_size = os.path.getsize(gfiles[0])

    ds = xr.open_dataset(gfiles[0])
    svar = ds.variable_id
    nt = ds[svar].shape[0]

    chunksize_optimal = 5e7
    chunksize = max(int(nt*chunksize_optimal/nc_size),1)
    preprocess = set_bnds_as_coords
    join = 'exact'

    codes = read_codes(ds_dir)
    if 1==1:
        for code in codes:
            if 'deptht' in code:
                fix_string = '/usr/bin/ncrename -d .deptht\,olevel -v .deptht\,olevel -d .deptht_bounds\,olevel_bounds -v .deptht_bounds\,olevel_bounds '
                for gfile in gfiles:
                    dstr += f'fixing deptht trouble in gfile:{gfile}'
                    if doit(f'{fix_string} {gfile}'):
                        print('fix_string did not execute')
            if 'remove_files' in code:
                command = '/bin/rm nctemp/*NorESM2-LM*1230.nc'
                if doit(command):
                    print('file not removed')
                gfiles = [file for file in gfiles if ('1231.nc' in file)]
            if 'last_only' in code:
                gfiles = [gfiles[-1]]
            if 'fix_time' in code:
                preprocess = convert2gregorian
            if 'drop_height' in codes:
                preprocess = set_bnds_as_coords_drop_height
            if 'drop_bnds' in codes:
                preprocess = set_bnds_as_coords_drop_bnds
            if 'override' in code:
                join = 'override'

    df7 = 'none'
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")

        try:
            if 'time' in ds.coords:  
                df7 = xr.open_mfdataset(gfiles,
                                        preprocess=preprocess,
                                        data_vars='minimal',
                                        chunks={'time': chunksize}, use_cftime=True,
                                        join=join, combine='nested',
                                        concat_dim='time')
            else: # fixed in time, no time grid
                df7 = xr.open_mfdataset(gfiles,
                                        preprocess=set_bnds_as_coords,
                                        combine='by_coords',
                                        join=join,
                                        data_vars='minimal')
        except:
            dstr = 'noUse, error in open_mfdataset'
            return df7,2,dstr
                
    if 1==1:
        allow_disjoint=False
        for code in codes:
            print(code)
            if 'drop_tb' in code: # to_zarr cannot do chunking with time_bounds/time_bnds which is cftime (an object, not float)
                timeb = [var for var in df7.coords if 'time_bnds' in
                         var or 'time_bounds' in var][0]
                df7 = df7.drop(timeb)
            if 'time_' in code:
                [y1,y2] = code.split('_')[-1].split('-')
                df7 = df7.sel(time=slice(str(y1)+'-01-01',str(y2)+'-12-31'))
            if '360_day' in code:
                print(gfiles[0])
                year = gfiles[0].split('-')[-2][-6:-2]
                print(year, df7.time.shape[0])
                df7['time'] = cftime.num2date(np.arange(df7.time.shape[0]), units='months since '+year+'-01-16', calendar='360_day')
                #print('encoding time as 360_day from year = ',year)
            if 'noleap' in code:
                year = gfiles[0].split('-')[-2][-6:-2]
                df7['time'] = xr.cftime_range(start=year,
                                              periods=df7.time.shape[0],
                                              freq='MS',
                                              calendar='noleap').shift(15, 'D')
                #print('encoding time as noleap from year = ',year)
            if 'missing' in code:
                del df7[svar].encoding['missing_value']
            if 'allow_disjoint' in code: 
                allow_disjoint=True

    #     check time grid to make sure there are no gaps in
#     concatenated data (open_mfdataset checks for mis-ordering)
    if 'time' in ds.coords:
        year = sorted(list(set(df7.time.dt.year.values)))
        print(np.diff(year).sum(), len(year))
        if 'abrupt-4xCO2' in ds_dir:
            print('exception made for disjoint time intervals')
        elif allow_disjoint:
            print('exception made for disjoint time intervals')
        elif '3hr' in table_id:
            if not (np.diff(year).sum() == len(year)-1) | (np.diff(year).sum() == len(year)-2):
                dstr = 'noUse, trouble with 3hr time grid'
                return df7,2,dstr
        elif 'dec' in table_id:
            if not (np.diff(year).sum()/10 == len(year)) | (np.diff(year).sum()/10 == len(year)-1):
                dstr = 'noUse, trouble with dec time grid'
                return df7,2,dstr
        elif 'clim' in table_id:
            # IPSL seems to have two disjoint climatologies - ???
            # abrupt-4xCO2 also has multiple climatologies - ???
            # Dec 23, 2020 - decided to allow whatever time grid is provided
            print('exception made for clim table_id time intervals')
            #if len(year) != 1:
            #    dstr = 'noUse, trouble with clim time grid'
            #    return df7,2,dstr
        else:
            if not np.diff(year).sum() == len(year)-1:
                dstr = 'noUse, trouble with time grid'
                return df7,2,dstr

    dsl = xr.open_dataset(gfiles[0])
    tracking_id = dsl.tracking_id
    if len(gfiles) > 1:
        for file in gfiles[1:]:
            dsl = xr.open_dataset(file)
            tracking_id += '\n'+dsl.tracking_id
    df7.attrs['netcdf_tracking_ids'] = tracking_id
    df7.attrs['version_id'] = version

    date = str(datetime.datetime.now().strftime("%Y-%m-%d"))
    nstatus = date + ';created; by gcs.cmip6.ldeo@gmail.com'
    df7.attrs['status'] = nstatus

    if 'time' in df7.coords:
        nt = len(df7.time.values)
        chunksize = min(chunksize,max(1,int(nt/2)))
        df7 = df7.chunk(chunks={'time' : chunksize})   # yes, do it again

    return df7, 0, ''

@exception_handler
def SaveAsZarr(ds_dir, ds, dir2local):
    # need version in path
    version = ds.attrs['version_id']
    zbdir = f"{dir2local(ds_dir)}/{version}"
    #print("nhn2",version,zbdir)
    #return version,1,''

    variable_id = ds.variable_id

    if os.path.isfile(zbdir+'/.zmetadata'):
        exception = 'zarr already exists locally'
        return version,1,exception

    try:
        ds.to_zarr(zbdir, consolidated=True, mode='w')
    except:
        return version,2,f'noUse, to_zarr failure'

    return version,0, ''

@exception_handler
def Upload(ds_dir, version, dir2local):   
    zbdir = f"{dir2local(ds_dir)}/{version}"
    gsurl = f"{dir2url(ds_dir)}/{version}"
    fs = myconfig.fs

    # upload to cloud
    if doit(f'/usr/bin/gsutil -m cp -r {zbdir} {gsurl}'):
        exception = f'/usr/bin/gsutil -m cp -r {zbdir} {gsurl} FAILED'
        return zbdir, gsurl, 1, exception

    size_remote = fs.du(gsurl)
    size_local = getFolderSize(zbdir)
    if abs(size_remote - size_local) > 100: 
        exception = f'{zbdir}/{gsurl} zarr not completely uploaded'
        return zbdir, gsurl, 2, exception

    try:
        ds = xr.open_zarr(fs.get_mapper(gsurl), consolidated=True)
        exception = f'successfully uploaded to {gsurl}'
    except:
        exception =  f'{gsurl} does not load properly'
        return zbdir, gsurl, 3, exception

    return zbdir, gsurl, 0, exception

@exception_handler
def Cleanup(ds_dir, version, gfiles, dir2local, nc_remove = True, zarr_remove = False):   
    zbdir = f"{dir2local(ds_dir)}/{version}"
    
    if zarr_remove:
        if doit(f'/bin/rm -rf {zbdir}'):
            print(f'{zbdir} not removed')

    if nc_remove:
        for gfile in gfiles:
             if doit('/bin/rm -f '+ gfile):
                  print(f'{gfile} not removed')

    return 0, ''

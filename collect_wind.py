"""Download ordinary regional GFS weather grids. Not a dispersion model."""
import argparse, datetime as dt, json, pathlib, time, urllib.request, urllib.parse, hashlib
UTC=dt.timezone.utc
BASE='https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl'
START=dt.datetime(2026,11,25,15,tzinfo=UTC)
END=START+dt.timedelta(days=10)
def hours(run):
    return [h for h in list(range(121))+list(range(123,385,3)) if START<=run+dt.timedelta(hours=h)<=END]
def url(run,h):
    p={'file':f'gfs.t{run:%H}z.pgrb2.0p25.f{h:03d}','dir':f'/gfs.{run:%Y%m%d}/{run:%H}/atmos','subregion':'','leftlon':-100,'rightlon':-80,'toplat':49,'bottomlat':35,'var_UGRD':'on','var_VGRD':'on','lev_10_m_above_ground':'on'}
    return BASE+'?'+urllib.parse.urlencode(p)
def main():
    p=argparse.ArgumentParser();p.add_argument('--run',default='2026-11-25T12:00:00+00:00');p.add_argument('--plan',action='store_true');p.add_argument('--output',default='wind-data');a=p.parse_args()
    run=dt.datetime.fromisoformat(a.run).astimezone(UTC)
    if run.hour not in (0,6,12,18) or run.minute or run.second: p.error('Use a NOAA UTC cycle: 00, 06, 12 or 18')
    out=pathlib.Path(a.output)/run.strftime('%Y%m%dT%HZ');out.mkdir(parents=True,exist_ok=True)
    records=[]
    for h in hours(run):
        target=out/f'f{h:03d}.grib2'; u=url(run,h)
        r={'valid_utc':(run+dt.timedelta(hours=h)).isoformat(),'forecast_hour':h,'source_url':u,'file':target.name,'status':'planned'}
        if not a.plan:
            try:
                if not target.exists():
                    with urllib.request.urlopen(u,timeout=90) as response: data=response.read()
                    if not data.startswith(b'GRIB') or not data.endswith(b'7777'): raise ValueError('Invalid GRIB response')
                    target.write_bytes(data);time.sleep(1)
                data=target.read_bytes();r.update(status='downloaded',sha256=hashlib.sha256(data).hexdigest())
            except Exception as e:r.update(status='unavailable',error=str(e))
        records.append(r)
        print(r['valid_utc'],r['status'],flush=True)
    manifest={'model':'NOAA GFS','run_utc':run.isoformat(),'window_start_utc':START.isoformat(),'window_end_utc':END.isoformat(),'grid_degrees':0.25,'variables':['10m eastward wind (m/s)','10m northward wind (m/s)'],'records':records,'warning':'Weather forecast only; not observed contamination or an exposure estimate.'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    if not a.plan and any(r['status']!='downloaded' for r in records): raise SystemExit('Incomplete download; rerun to retry missing files.')
if __name__=='__main__':main()

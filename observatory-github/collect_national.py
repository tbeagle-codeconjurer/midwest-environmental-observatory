"""Public national monitoring snapshot; no private data or API keys."""
import json, datetime as dt, math
from pathlib import Path
from urllib.request import Request,urlopen
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent/'data'
FEEDS={'earthquakes':'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson','alerts':'https://api.weather.gov/alerts/active'}
def get(url):
    with urlopen(Request(url,headers={'User-Agent':'Midwest Environmental Observatory public research','Accept':'application/geo+json'}),timeout=45) as r: return json.load(r)
def point(f):
    g=f.get('geometry') or {}; c=g.get('coordinates',[])
    return c if g.get('type')=='Point' and len(c)>=2 and all(isinstance(x,(float,int)) and math.isfinite(x) for x in c[:2]) else None
def parse(kind,d):
    if not isinstance(d.get('features'),list): raise ValueError('Missing features')
    out=[]
    for f in d['features']:
        p=f.get('properties') or {}; id=f.get('id');
        if not id: continue
        if kind=='earthquakes':
            c=point(f)
            if c is None: continue
            out.append(dict(id=id,lat=c[1],lon=c[0],depth=c[2] if len(c)>2 else None,mag=p.get('mag'),title=p.get('place'),time=p.get('time'),url=p.get('url'),type=p.get('type'),updated=p.get('updated')))
        else:
            out.append(dict(id=id,title=p.get('event'),area=p.get('areaDesc'),severity=p.get('severity'),time=p.get('sent'),expires=p.get('expires'),instruction=p.get('instruction'),url=p.get('web') or id,states=list({x[:2] for x in (p.get('geocode') or {}).get('UGC',[]) if isinstance(x,str) and len(x)>=2}),geometry=f.get('geometry')))
    return out
def main():
    ROOT.mkdir(exist_ok=True); path=ROOT/'national.json'; old=json.loads(path.read_text()) if path.exists() else {}; now=dt.datetime.now(dt.timezone.utc).isoformat()
    def run(item):
        k,u=item
        try: return k,dict(status='retrieved',retrieved_at=now,source=u,records=parse(k,get(u)))
        except Exception as e: return k,dict(old.get(k,{'records':[]}),status='unavailable',source=u,error=str(e),attempted_at=now)
    with ThreadPoolExecutor(max_workers=2) as pool: result=dict(pool.map(run,FEEDS.items()))
    result['checked_at']=now; tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(result,allow_nan=False)); tmp.replace(path)
def extra():
    import csv, io, os
    from urllib.parse import urlencode
    from collect_region import air
    path=ROOT/'national_extra.json'; old=json.loads(path.read_text()) if path.exists() else {}; now=dt.datetime.now(dt.timezone.utc); result={}
    def store(key, source, fn):
        try: result[key]=dict(status='retrieved',retrieved_at=now.isoformat(),source=source,records=fn())
        except Exception as e: result[key]=dict(old.get(key,{'records':[]}),status='unavailable',source=source,error=str(e),attempted_at=now.isoformat())
    # A bounded selection of river gauges, rather than an incomplete national census.
    base='https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items'
    def water():
        rows=[]
        for site in ['USGS-05474500','USGS-05586100','USGS-05515500','USGS-03339000','USGS-01646500','USGS-11447650']:
            d=get(base+'?'+urlencode({'monitoring_location_id':site,'limit':100,'f':'json'}))
            for f in d['features']:
                p=f['properties']; code=p.get('parameter_code')
                if code not in ('00060','00065','00010','00400','00095','00300'): continue
                c=point(f) or [None,None]
                rows.append(dict(lat=c[1],lon=c[0],station=site,metric=code,value=p.get('value'),unit=p.get('unit_of_measure'),time=p.get('time'),quality=p.get('approval_status'),source=base))
        return rows
    store('water',base,water)
    def nationwide_air():
        from collect_region import get as get_text,numeric
        for offset in range(1,5):
            hour=now.replace(minute=0,second=0,microsecond=0)-dt.timedelta(hours=offset)
            url=f'https://files.airnowtech.org/airnow/{hour:%Y/%Y%m%d}/HourlyAQObs_{hour:%Y%m%d%H}.dat'
            try: text=get_text(url)
            except Exception: continue
            rows=[]
            for r in csv.reader(io.StringIO(text)):
                if len(r)<34 or r[8].strip().upper() not in ('US','USA'): continue
                for metric,idx,flag in [('PM2.5',22,20),('PM10',32,19),('Ozone',24,18)]:
                    v=numeric(r[idx]); unit=r[idx+1].strip(); lat=numeric(r[4]); lon=numeric(r[5])
                    if r[flag].strip()!='1' or v is None or v<=-999 or lat is None or lon is None or unit.lower().replace('µ','u').replace('μ','u').replace('³','3').replace('^','') not in (('ppb',) if metric=='Ozone' else ('ug/m3','ug/m 3')): continue
                    rows.append(dict(station=r[0],name=r[1],metric=metric,value=v,unit=unit,time=dt.datetime.strptime(r[10]+' '+r[11],'%m/%d/%y %H:%M').replace(tzinfo=dt.timezone.utc).isoformat(),lat=lat,lon=lon,source=url))
            if rows: return rows
        raise ValueError('No usable recent AirNow file')
    store('air','https://files.airnowtech.org/',nationwide_air)
    # Public FIRMS API requires a user-provided secret. Never serialize it.
    key=os.environ.get('FIRMS_MAP_KEY','').strip()
    def fires():
        from collect_region import get as get_text
        try:
            data=get_text('https://firms.modaps.eosdis.nasa.gov/api/area/csv/'+key+'/VIIRS_NOAA20_NRT/-125,24,-66,50/1')
            reader=csv.DictReader(io.StringIO(data))
            if not {'latitude','longitude','acq_date','acq_time'}.issubset(reader.fieldnames or []): raise ValueError('Unexpected feed format')
            return [dict(lat=float(r['latitude']),lon=float(r['longitude']),time=dt.datetime.strptime(r['acq_date']+' '+r['acq_time'].zfill(4),'%Y-%m-%d %H%M').replace(tzinfo=dt.timezone.utc).isoformat(),value=r.get('frp'),unit='MW',metric='Fire radiative power',quality=r.get('confidence'),station='VIIRS NOAA-20') for r in reader]
        except Exception: raise ValueError('FIRMS request or parsing failed') from None
    if key: store('fire','https://firms.modaps.eosdis.nasa.gov/',fires)
    else: result['fire']=dict(status='not configured',records=[],source='https://firms.modaps.eosdis.nasa.gov/')
    store('radiation',RADNET,lambda: radiation(now))
    for k,d in result.items():
        print(k, d.get('status'), len(d.get('records',[])), d.get('error',''), flush=True)
    archive(result,now)
    result['checked_at']=now.isoformat(); tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(result,allow_nan=False)); tmp.replace(path)

RADNET='https://www.epa.gov/radnet/radnet-csv-file-downloads'
RAD_STATIONS=[('IA','FORT MADISON'),('IA','DES MOINES'),('IL','CHICAGO'),('IL','CHAMPAIGN'),('IL','AURORA'),('IN','FORT WAYNE'),('IN','INDIANAPOLIS'),('MI','GRAND RAPIDS')]
def number(v):
    try:
        n=float(v); return n if math.isfinite(n) else None
    except (TypeError,ValueError): return None

def rad_parse(raw,station,url,now):
    import csv,io,re,zipfile
    if raw[:2]==b'PK':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return [r for i in z.infolist() if i.filename.lower().endswith('.csv') and i.file_size<40_000_000 for r in rad_parse(z.read(i),station,url,now)]
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    headers=reader.fieldnames or []
    def norm(x): return re.sub(r'[^a-z0-9]','',x.lower())
    dates=[h for h in headers if ('date' in h.lower() and ('time' in h.lower() or 'measurement' in h.lower())) or norm(h) in ('datetime','timestamp','dateutc')]
    dates.sort(key=lambda h: ('end' not in h.lower(), 'utc' not in h.lower()))
    cols=[]
    for h in headers:
        n=norm(h)
        if 'gamma' in n and ('cpm' in n or 'countsperminute' in n): cols.append((h,'CPM'))
        elif ('exposure' in n) and ('mrhr' in n or 'mrh' in n): cols.append((h,'mR/h'))
        elif 'dose' in n and ('nsvh' in n or 'nsvhr' in n): cols.append((h,'nSv/h'))
    if not dates or not cols: raise ValueError('Unrecognized RadNet CSV headers: '+str(headers)[:350])
    out=[]
    for row in reader:
        text=(row.get(dates[0]) or '').strip(); t=None
        try: t=dt.datetime.fromisoformat(text.replace('Z','+00:00'))
        except ValueError:
            for fmt in ('%m/%d/%Y %H:%M:%S','%m/%d/%Y %H:%M','%m/%d/%Y %I:%M:%S %p','%m/%d/%Y %I:%M %p'):
                try: t=dt.datetime.strptime(text,fmt); break
                except ValueError: pass
        if t is None: continue
        if t.tzinfo is None: t=t.replace(tzinfo=dt.timezone.utc)
        if not now-dt.timedelta(days=7)<=t<=now: continue
        for h,u in cols:
            v=number(row.get(h))
            if v is not None and v>=0: out.append(dict(station=station,metric=h,value=v,unit=u,time=t.isoformat(),source=url,quality='EPA published; preliminary'))
    return out

def radiation(now):
    from urllib.parse import quote
    def station(pair):
        st,city=pair; url=f'https://radnet.epa.gov/cdx-radnet-rest/api/rest/csv/{now.year}/fixed/{st}/{quote(city)}'
        try:
            with urlopen(Request(url,headers={'User-Agent':'Midwest Environmental Observatory'}),timeout=40) as r: raw=r.read(40_000_001)
            if len(raw)>40_000_000: raise ValueError('Download too large')
            rows=rad_parse(raw,city.title()+', '+st,url,now)
            print('RadNet',city,len(rows),'records',flush=True); return rows
        except Exception as e: print('RadNet',city,'unavailable',str(e),flush=True); return []
    with ThreadPoolExecutor(max_workers=3) as pool: rows=[r for group in pool.map(station,RAD_STATIONS) for r in group]
    if not rows: raise ValueError('No usable RadNet readings; inspect per-station collection log for format or retrieval errors')
    return rows

def archive(result,now):
    # Bounded rolling archive; keep observations distinct by station, metric, unit and time.
    path=ROOT/'national_extra_history.json'
    old=json.loads(path.read_text()) if path.exists() else {}
    for k,d in result.items():
        if d.get('status')!='retrieved': continue
        rows=old.get(k,[])+d.get('records',[]); unique={}
        for r in rows:
            try: t=dt.datetime.fromisoformat(str(r.get('time','')).replace('Z','+00:00'))
            except ValueError: continue
            if t.tzinfo is None or t<now-dt.timedelta(days=7): continue
            key=tuple(str(r.get(x,'')) for x in ('station','metric','unit','time','lat','lon'))
            unique[key]=r
        old[k]=sorted(unique.values(),key=lambda r:r['time'])[-40000:]
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(old,allow_nan=False)); tmp.replace(path)

if __name__=='__main__':
    main(); extra()


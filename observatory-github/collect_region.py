"""Read-only regional observations and active public weather alerts."""
import csv, datetime as dt, io, json, math
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor
UTC=dt.timezone.utc
ROOT=Path(__file__).resolve().parent/'data'; ROOT.mkdir(exist_ok=True)
NOW=dt.datetime.now(UTC)
STATIONS='BRL EOK IRK UIN GBG PIA DVN VPZ SBN'.split()

def get(url):
    with urlopen(Request(url,headers={'User-Agent':'Midwest Environmental Observatory public research','Accept':'*/*'}),timeout=30) as r: return r.read().decode('utf-8-sig')
def save(name,obj):
    p=ROOT/name; t=p.with_suffix('.tmp'); t.write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False)); t.replace(p)
def load(name,default):
    p=ROOT/name; return json.loads(p.read_text()) if p.exists() else default
def numeric(v):
    try:
        n=float(v); return n if math.isfinite(n) else None
    except (ValueError,TypeError): return None

def air(hour):
    stamp=hour.strftime('%Y%m%d%H'); url=f'https://files.airnowtech.org/airnow/{hour:%Y/%Y%m%d}/HourlyAQObs_{stamp}.dat'
    try:
        rows=[]; text=get(url)
        for r in csv.reader(io.StringIO(text)):
            if len(r)<34 or r[8].strip().upper() not in ('US','USA'): continue
            lat,lon=numeric(r[4]),numeric(r[5])
            if lat is None or lon is None or not (39<=lat<=43 and -94<=lon<=-85): continue
            # ValidDate/ValidTime are already UTC per AirNow file specification.
            timestamp=None
            for fmt in ('%m/%d/%y %H:%M','%m/%d/%Y %H:%M','%Y-%m-%d %H:%M'):
                try: timestamp=dt.datetime.strptime(r[10]+' '+r[11],fmt).replace(tzinfo=UTC); break
                except ValueError: pass
            if timestamp is None: continue
            for metric,idx,flag in [('pm25',22,20),('pm10',32,19)]:
                if r[flag].strip() != '1': continue
                v=numeric(r[idx]); unit=r[idx+1].strip()
                if v is None or v<=-999 or unit.lower().replace('µ','u').replace('μ','u').replace('³','3').replace('^','') not in ('ug/m3','ug/m 3'): continue
                rows.append(dict(time=timestamp.isoformat(),station=r[0],site=r[1],metric=metric,value=v,unit=unit,lat=lat,lon=lon,kind='Measured',quality='AirNow preliminary; negative values retained as reported',source=url))
        return rows,dict(hour=stamp,status='retrieved',regional_records=len(rows))
    except Exception as e: return [],dict(hour=stamp,status='unavailable',error=str(e))

def iem():
    start=dt.date(2026,11,22); end=dt.date(2026,11,26)
    params=[('station',s) for s in STATIONS]+[('data',s) for s in ['tmpf','relh','sknt','drct','p01i','mslp']]+[('year1',start.year),('month1',start.month),('day1',start.day),('year2',end.year),('month2',end.month),('day2',end.day),('tz','Etc/UTC'),('format','onlycomma'),('latlon','yes'),('missing','M'),('trace','T'),('report_type',3),('report_type',4)]
    url='https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?'+urlencode(params)
    rows=[]
    for r in csv.DictReader(io.StringIO(get(url))):
        if r.get('station') not in STATIONS: continue
        try: timestamp=dt.datetime.fromisoformat(r['valid']).replace(tzinfo=UTC).isoformat()
        except (ValueError,KeyError): continue
        for metric,key,factor,unit in [('temp','tmpf',1,'°F'),('humidity','relh',1,'%'),('wind','sknt',1.150779,'mph'),('direction','drct',1,'degrees'),('rain','p01i',25.4,'mm'),('pressure','mslp',1,'hPa')]:
            v=numeric(r.get(key));
            if v is None: continue
            rows.append(dict(time=timestamp,station='K'+r['station'],metric=metric,value=round(v*factor,3),unit=unit,kind='Measured',quality='IEM archive; QA flag unavailable; trace precipitation omitted',source=url))
    return rows

def alerts(state):
    url='https://api.weather.gov/alerts/active?area='+state
    try:
        data=json.loads(get(url)); return {'state':state,'status':'success','alerts':[dict(id=f['id'],**{k:f['properties'].get(k) for k in ['event','headline','sent','expires','areaDesc','severity','instruction','description','web']}) for f in data['features']]}
    except Exception as e: return {'state':state,'status':'unavailable','error':str(e),'alerts':[]}

def main():
    old=load('regional.json',{'records':[]}); records={(r['time'],r['station'],r['metric'],r['source'].split('?')[0] if 'mesonet' in r['source'] else 'airnow'):r for r in old['records']}
    checked=NOW.isoformat(); statuses=[]
    # One-time baseline backfill in bounded batches; retry missing hours on subsequent runs.
    start=dt.datetime(2026,11,22,6,tzinfo=UTC); end=dt.datetime(2026,11,25,6,tzinfo=UTC)
    done=set(old.get('airnow_completed_hours',[])); backlog=[start+dt.timedelta(hours=i) for i in range(int((end-start).total_seconds()/3600)) if (start+dt.timedelta(hours=i)).strftime('%Y%m%d%H') not in done]
    current=NOW.replace(minute=0,second=0,microsecond=0); hours=list(dict.fromkeys([current-dt.timedelta(hours=i) for i in range(1,7)]+backlog[:12]))
    with ThreadPoolExecutor(max_workers=4) as pool:
        for rows,status in pool.map(air,hours):
            statuses.append(status)
            if status['status']=='retrieved' and status['regional_records']>0: done.add(status['hour'])
            for r in rows: records[(r['time'],r['station'],r['metric'],'airnow')]=r
        alertdata=list(pool.map(alerts,['IA','MO','IL','IN']))
    iem_ok=old.get('iem_complete',False)
    if not iem_ok or NOW.date()<=dt.date(2026,11,26):
        try:
            rows=iem(); iem_ok=bool(rows) and NOW.date()>dt.date(2026,11,25); statuses.append({'source':'IEM','status':'retrieved','records':len(rows)})
            for r in rows: records[(r['time'],r['station'],r['metric'],r['source'].split('?')[0])]=r
        except Exception as e: statuses.append({'source':'IEM','status':'unavailable','error':str(e)})
    save('regional.json',dict(checked_at=checked,records=sorted(records.values(),key=lambda r:(r['time'],r['station'],r['metric'])),statuses=statuses,airnow_completed_hours=sorted(done),iem_complete=iem_ok))
    save('alerts.json',dict(checked_at=checked,states=alertdata))
if __name__=='__main__': main()

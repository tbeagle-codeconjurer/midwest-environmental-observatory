import json, pathlib, datetime, urllib.request, math
from concurrent.futures import ThreadPoolExecutor
P=pathlib.Path('data/weather.json'); P.parent.mkdir(exist_ok=True)
old=json.loads(P.read_text()) if P.exists() else {'records':[]}
ids='KBRL KEOK KIRK KUIN KGBG KPIA KDVN KVPZ KSBN'.split()
def collect(s):
    url=f'https://api.weather.gov/stations/{s}/observations/latest'
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Midwest Environmental Observatory (public research dashboard)','Accept':'application/geo+json'})
        with urllib.request.urlopen(req,timeout=25) as f: p=json.load(f)['properties']
        rows=[]
        for metric,key,unit,convert in [('temp','temperature','wmoUnit:degC',lambda v:v*1.8+32),('wind','windSpeed','wmoUnit:km_h-1',lambda v:v/1.609344),('direction','windDirection','wmoUnit:degree_(angle)',lambda v:v)]:
            a=p.get(key) or {}; v=a.get('value')
            if isinstance(v,(int,float)) and math.isfinite(v) and a.get('unitCode')==unit:
                rows.append(dict(time=p['timestamp'],station=s,metric=metric,value=round(convert(v),3),kind='Measured',quality='NOAA flag: '+str(a.get('qualityControl') or 'not provided'),source=url))
        return rows,{'station':s,'status':f'{len(rows)} values returned','observation_time':p.get('timestamp')}
    except Exception as e: return [],{'station':s,'status':str(e)}
with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(collect,ids))
rows={(r['time'],r['station'],r['metric']):r for r in old['records']}
for records,status in results:
    for r in records: rows[(r['time'],r['station'],r['metric'])]=r
P.write_text(json.dumps({'records':list(rows.values()),'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'statuses':[s for _,s in results]},indent=2))

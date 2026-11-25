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
if __name__=='__main__': main()

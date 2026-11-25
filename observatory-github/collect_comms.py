"""Public communications archive. No radio interception; no emergency delivery guarantee."""
import json, hashlib, re, datetime as dt
from pathlib import Path
from html.parser import HTMLParser
from urllib.request import Request,urlopen
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent/'data'; ROOT.mkdir(exist_ok=True)
NOW=dt.datetime.now(dt.timezone.utc).isoformat()
SOURCES={
 'Army community notifications':'https://www.army.mil/asc',
 'Illinois EPA incident updates':'https://epa.illinois.gov/iowa-plant-updates.html',
 'EPA incident response':'https://response.epa.gov/site/site_profile.aspx?site_id=17211',
 'Missouri DNR incident updates':'https://dnr.mo.gov/iowa-lead-azide-detonation',
}
SEED=[('2026-11-24','EPA','Pre-event interagency public update','https://www.epa.gov/newsreleases/epa-army-and-other-federal-partners-provide-public-update-iowa-army-ammunition-plant'),('2026-11-25','EPA','Initial airborne lead non-detection announcement; preliminary agency report','https://www.epa.gov/newsreleases/initial-air-monitoring-shows-zero-detection-airborne-lead-following-controlled'),('2026-11-25','EPA','Pre-event sampling announcement: more than 1,200 samples','https://www.epa.gov/newsreleases/epa-collects-over-1200-air-land-and-water-samples-ahead-iowa-army-ammunition-plant'),('2026-11-25','Illinois EPA','Post-event regional standby statement','https://epa.illinois.gov/about-us/illinois-epa-news/illinois-remains-on-standby-following-lead-azide-detonation-at-t.html')]
class Extract(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True); self.stack=[]; self.all=[]; self.main=[]
 def handle_starttag(self,tag,attrs):
  if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'): self.stack.append(tag)
 def handle_startendtag(self,tag,attrs): pass
 def handle_endtag(self,tag):
  if tag in self.stack: self.stack=self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]
 def handle_data(self,data):
  if any(t in self.stack for t in ('script','style','noscript','header','footer','nav','head','svg')): return
  s=' '.join(data.split())
  if s: self.all.append(s); self.main.extend([s] if any(t in self.stack for t in ('main','article')) else [])
def scan(item):
 name,url=item
 try:
  with urlopen(Request(url,headers={'User-Agent':'Midwest Environmental Observatory public-source monitoring','Accept':'text/html'}),timeout=25) as r:
   if 'html' not in r.headers.get('Content-Type','').lower(): raise ValueError('Not HTML')
   p=Extract(); p.feed(r.read(4_000_000).decode(r.headers.get_content_charset() or 'utf-8',errors='replace'))
  body=' '.join(p.main or p.all)
  if len(body)<150 or re.search(r'access denied|verify you are human|request blocked|enable javascript',body[:500],re.I): raise ValueError('No usable public page text')
  return dict(source=name,url=url,status='retrieved',fingerprint=hashlib.sha256(body.encode()).hexdigest(),scope='main/article' if p.main else 'page text')
 except Exception as e: return dict(source=name,url=url,status='unavailable',error=str(e)[:300])
def load(name,default):
 p=ROOT/name; return json.loads(p.read_text()) if p.exists() else default
def main():
 old=load('communications.json',{}); events={e['key']:e for e in old.get('events',[])}; fingerprints=old.get('fingerprints',{})
 for day,source,title,url in SEED:
  key='seed:'+url; events.setdefault(key,dict(key=key,time=day,category='Official announcement',source=source,title=title,url=url,detail='Publication date only; read original announcement for context.'))
 with ThreadPoolExecutor(max_workers=4) as pool: statuses=list(pool.map(scan,SOURCES.items()))
 for s in statuses:
  if s['status']!='retrieved': continue
  name=s['source']; h=s['fingerprint']; prev=fingerprints.get(name)
  if h!=prev:
   key='page:'+name+':'+NOW
   events[key]=dict(key=key,time=NOW,category='Source change' if prev else 'Source baseline',source=name,title='Public page text changed' if prev else 'Initial public page check',url=s['url'],detail='Detected text fingerprint change; may be routine page editing, not a new advisory. Open source to verify.' if prev else 'Initial fingerprint recorded; not a new announcement.')
   fingerprints[name]=h
 alert=load('alerts.json',{}); alert_status=[]
 for st in alert.get('states',[]):
  alert_status.append(dict(state=st.get('state'),status=st.get('status'),error=st.get('error')))
  if st.get('status')!='success': continue
  for a in st.get('alerts',[]):
   if not a.get('id') or not a.get('sent'): continue
   key='nws:'+a['id']+':'+a['sent']; prior=events.get(key,{})
   events[key]=dict(key=key,time=a['sent'],category='NWS alert',source='National Weather Service',title=a.get('headline') or a.get('event') or 'Public alert',url=a['id'],detail=a.get('instruction') or a.get('description') or '',expires=a.get('expires'),severity=a.get('severity'),area=a.get('areaDesc'),states=sorted(set(prior.get('states',[])+[st['state']])),last_seen=alert.get('checked_at'))
 obj=dict(checked_at=NOW,alert_checked_at=alert.get('checked_at'),alert_status=alert_status,source_status=statuses,fingerprints=fingerprints,events=sorted(events.values(),key=lambda e:e['time'],reverse=True))
 p=ROOT/'communications.json'; t=p.with_suffix('.tmp'); t.write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False)); t.replace(p)
if __name__=='__main__': main()

"""Read-only collection of the public EPA Xact view; retain records by global ID."""
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/IAAAP_Xact_Data_Public_Viewer/FeatureServer/0'
ROOT = Path(__file__).resolve().parent / 'data'
ROOT.mkdir(exist_ok=True)
ARCHIVE = ROOT / 'epa-xact.json'
STATUS = ROOT / 'epa-xact-status.json'

def get(path='', **params):
    url = BASE + path + '?' + urlencode(dict(f='json', **params))
    with urlopen(Request(url, headers={'User-Agent': 'Midwest Environmental Observatory/1.0'}), timeout=60) as response:
        payload = json.load(response)
    if 'error' in payload:
        raise RuntimeError(str(payload['error']))
    return payload

def save(path, obj):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temp.replace(path)

def main():
    checked = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        meta = get()
        ids = get('/query', where='1=1', returnIdsOnly='true')['objectIds']
        rows = []
        for i in range(0, len(ids), 500):
            result = get('/query', objectIds=','.join(map(str, ids[i:i+500])), outFields='*', returnGeometry='true', outSR=4326)
            if result.get('exceededTransferLimit'):
                raise RuntimeError('Unexpected transfer limit')
            rows.extend(result['features'])
        if {r['attributes']['objectid'] for r in rows} != set(ids):
            raise RuntimeError('Incomplete or changing source snapshot; archive retained')
        old = json.loads(ARCHIVE.read_text()) if ARCHIVE.exists() else {'features': []}
        merged = {r['attributes']['globalid']: r for r in old['features']}
        merged.update({r['attributes']['globalid']: r for r in rows})
        save(ARCHIVE, dict(source=BASE, retrieved_at=checked, features=sorted(merged.values(), key=lambda r:(r['attributes'].get('Mon_Date_Time') or 0,r['attributes']['objectid']))))
        save(ROOT/'epa-xact-metadata.json', meta)
        save(STATUS, dict(checked_at=checked, status='success', source_records=len(rows), archived_records=len(merged)))
    except Exception as e:
        save(STATUS, dict(checked_at=checked, status='error', error=str(e), archive_retained=True))
        raise

if __name__ == '__main__':
    main()

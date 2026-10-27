import json, pathlib, datetime, hashlib, time
from toolbox.cache import _scraper_body_path, cache_key
root = pathlib.Path('.cache')
cands = [
 "https://fantasy-api.llt-services.com/api/v1/competition/1/league/018668579/market?x-lang=es",
 "https://fantasy-api.llt-services.com/api/v1/competition/1/league/018668579/market?x-lang=es&limit=1",
 "https://fantasy-api.llt-services.com/api/v1/competition/1/leagues/018668579/market?x-lang=es",
 "https://api-fantasy.llt-services.com/api/v1/competition/1/league/018668579/market?x-lang=es",
 "https://fantasy-api.llt-services.com/api/v1/competition/1/league/7/market?x-lang=es",
]
folder = root/'scraper_bodies'
index = {}
for p in folder.iterdir():
    try:
        row = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        continue
    index[p.name] = row
print('entries', len(index))
# Find entries whose body mentions the league id and looks like a market
for key,row in index.items():
    body = row.get('body') or ''
    if '"marketValue"' not in body and '"market"' not in body[:2000]:
        continue
    stored = row.get('stored_at')
    print(key[:12], row.get('stored_at'), datetime.datetime.fromtimestamp(stored, datetime.timezone.utc).isoformat() if isinstance(stored,(int,float)) else None, 'exp', row.get('expires_at'), 'len', len(body), 'league?', '018668579' in body[:5000])

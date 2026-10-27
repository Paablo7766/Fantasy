import json, pathlib, datetime, hashlib
from urllib.parse import urlparse
# find market cache entry stored_at
urls = [
 "https://fantasy-api.llt-services.com/api/v1/competition/1/league/018668579/market?x-lang=es",
 "https://fantasy-api.llt-services.com/api/v1/competition/1/league/018668579/market",
 "https://fantasy-api.llt-services.com/api/v1/competition/1/leagues/018668579/market?x-lang=es",
]
root = pathlib.Path('.cache')
for u in urls:
    key = hashlib.sha256(u.encode()).hexdigest()
    p = root/'scraper_bodies'/key
    print(p.exists(), u[:80])
    if p.exists():
        row = json.loads(p.read_text(encoding='utf-8'))
        print('  stored_at', datetime.datetime.fromtimestamp(row['stored_at'], datetime.timezone.utc).isoformat(), 'expires', datetime.datetime.fromtimestamp(row['expires_at'], datetime.timezone.utc).isoformat(), 'kind', row.get('kind'), 'len', len(row.get('body') or ''))

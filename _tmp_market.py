import json, hashlib, datetime
from pathlib import Path

root = Path(".cache")
urls = [
    "https://fantasy-api.llt-services.com/api/v4/leagues/7/market?x-lang=es",
    "https://fantasy-api.llt-services.com/api/v4/leagues/7/market",
    "https://fantasy-api.llt-services.com/api/v1/competition/1/league/018668579/market?x-lang=es",
    "https://fantasy-api.llt-services.com/api/v4/leagues/018668579/market?x-lang=es",
]
for u in urls:
    key = hashlib.sha256(u.encode()).hexdigest()
    p = root / "scraper_bodies" / key
    print("\n", u)
    print("  key", key, "exists", p.is_file())
    if p.is_file():
        st = p.stat()
        print("  mtime", datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc))
        d = json.loads(p.read_text(encoding="utf-8"))
        print("  meta", {k: v for k, v in d.items() if k != "body"})
        body = d.get("body")
        try:
            payload = json.loads(body) if isinstance(body, str) else body
            if isinstance(payload, dict):
                print("  keys", list(payload)[:12])
                items = payload.get("market") or payload.get("elements") or payload.get("data")
                if isinstance(items, list) and items:
                    print("  n items", len(items))
                    print("  first", json.dumps(items[0], ensure_ascii=False)[:400])
        except Exception as exc:
            print("  body parse err", exc)

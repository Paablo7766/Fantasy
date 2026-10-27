import json, os, sys, hashlib, datetime
from pathlib import Path

root = Path(".cache")
bodies = root / "scraper_bodies"
print("bodies exists:", bodies.is_dir())
files = list(bodies.glob("*"))
print("files:", len(files))
rows = []
for p in files:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        continue
    if not isinstance(d, dict):
        continue
    url = str(d.get("url") or "")
    stored = d.get("stored_at")
    kind = d.get("kind")
    rows.append((stored, url, kind, p.name, d.get("expires_at")))
rows.sort(key=lambda r: (r[0] or 0))
for stored, url, kind, name, exp in rows[-25:]:
    human = datetime.datetime.fromtimestamp(stored, datetime.timezone.utc) if isinstance(stored, (int, float)) else stored
    print(human, "|", kind, "|", url[:100])

target = 1792856889.528247
print("\nmatch target stored_at:")
for stored, url, kind, name, exp in rows:
    if isinstance(stored, (int, float)) and abs(stored - target) < 1:
        print(name, kind, url)

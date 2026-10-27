import json, datetime
from pathlib import Path

rows = []
for p in (Path(".cache") / "scraper_bodies").glob("*"):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        continue
    if isinstance(d, dict):
        rows.append((d.get("stored_at"), d, p.name))

rows = [r for r in rows if r[1].get("kind") == "json"]
rows.sort(key=lambda r: r[0] or 0)
for stored, d, name in rows[-12:]:
    human = datetime.datetime.fromtimestamp(stored, datetime.timezone.utc) if isinstance(stored, (int, float)) else stored
    print(human, "|", list(d)[:8])
    print("   ", json.dumps({k: v for k, v in d.items() if k != "body"}, ensure_ascii=False)[:400])

print("\nsearch 1792856889 ->", datetime.datetime.fromtimestamp(1792856889.528247, datetime.timezone.utc))
for stored, d, name in rows:
    if isinstance(stored, (int, float)) and abs(stored - 1792856889.528247) < 2:
        print("MATCH", name, {k: v for k, v in d.items() if k != "body"})

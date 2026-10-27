import json, pathlib, time

root = pathlib.Path(".cache/scraper_bodies")
now = time.time()
rows = []
for path in root.iterdir():
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(row, dict) or row.get("kind") != "json":
        continue
    stored = row.get("stored_at")
    body = row.get("body") or ""
    try:
        payload = json.loads(body)
    except Exception:
        payload = None
    head = ""
    if isinstance(payload, dict):
        head = ",".join(list(payload)[:6])
    elif isinstance(payload, list):
        head = f"list[{len(payload)}]"
    rows.append((stored if isinstance(stored, (int, float)) else 0, len(body), head, path.name))

rows.sort(reverse=True)
for stored, size, head, name in rows:
    print(f"{(now - stored) / 60:8.1f}min size={size:8d} {name[:12]} {head}")
print("total json bodies", len(rows))

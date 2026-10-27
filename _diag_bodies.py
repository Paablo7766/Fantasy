import json, pathlib, time

root = pathlib.Path(".cache/scraper_bodies")
now = time.time()
rows = []
for path in root.iterdir():
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("ERR", path.name, exc)
        continue
    if not isinstance(row, dict):
        print("NOT DICT", path.name, type(row))
        continue
    stored = row.get("stored_at")
    rows.append((stored if isinstance(stored, (int, float)) else 0, path, row))

rows.sort(key=lambda item: item[0], reverse=True)
for stored, path, row in rows[:12]:
    body = row.get("body") or ""
    print(
        f"{(now - stored) / 60:8.1f}min",
        row.get("kind"),
        f"len={len(body)}",
        body[:110].replace("\n", " "),
    )

import json, pathlib, time
from toolbox.cache import cache_key
from toolbox import net

now = time.time()
urls = net.market_urls("7")
for url in urls:
    key = cache_key(url)
    path = pathlib.Path(".cache/scraper_bodies") / key
    print("-" * 100)
    print(url)
    print("  file", path.is_file())
    if not path.is_file():
        continue
    row = json.loads(path.read_text(encoding="utf-8"))
    stored = row.get("stored_at")
    print(
        "  kind", row.get("kind"),
        "stored_at", stored,
        "age_min", round((now - float(stored)) / 60, 1) if isinstance(stored, (int, float)) else None,
        "expires_in_min", round((float(row.get("expires_at")) - now) / 60, 1) if isinstance(row.get("expires_at"), (int, float)) else None,
        "body_len", len(row.get("body") or ""),
    )
    try:
        payload = json.loads(row.get("body") or "{}")
    except Exception as exc:
        print("  body parse error", exc)
        continue
    print("  payload keys", list(payload)[:8] if isinstance(payload, dict) else type(payload))

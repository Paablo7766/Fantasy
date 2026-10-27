import json, pathlib, collections

rows = [json.loads(l) for l in pathlib.Path(".cache/network_logs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
slow = [r for r in rows if (r.get("duracion_ms") or 0) >= 50]
print("total", len(rows), "dur>=50ms", len(slow))
for r in slow[-15:]:
    print(r["timestamp"], r["fuente"], r["status"], r["duracion_ms"], r["url"][:70])

buckets = collections.Counter()
for r in rows:
    d = r.get("duracion_ms") or 0
    buckets["<5ms" if d < 5 else ("5-50ms" if d < 50 else ("50-500ms" if d < 500 else ">=500ms"))] += 1
print(buckets)

by_day = collections.Counter(r["timestamp"][:13] for r in rows)
for k in sorted(by_day)[-12:]:
    print(k, by_day[k])

import json, collections

rows = [json.loads(l) for l in open('.cache/network_logs.jsonl', encoding='utf-8') if l.strip()]
print("total", len(rows))
buckets = collections.Counter()
for r in rows:
    d = r.get('duracion_ms')
    try:
        d = float(d)
    except Exception:
        d = -1
    if d < 3:
        buckets['<3ms'] += 1
    elif d < 20:
        buckets['3-20ms'] += 1
    elif d < 100:
        buckets['20-100ms'] += 1
    elif d < 1000:
        buckets['0.1-1s'] += 1
    else:
        buckets['>1s'] += 1
print(buckets)

print("\nby day, count of >=20ms:")
byday = collections.Counter()
for r in rows:
    try:
        d = float(r.get('duracion_ms'))
    except Exception:
        continue
    if d >= 20:
        byday[r['timestamp'][:10]] += 1
print(byday)

print("\nsample of slowest:")
for r in sorted(rows, key=lambda r: -float(r.get('duracion_ms') or 0))[:10]:
    print(r['timestamp'], r['fuente'], r['status'], r['duracion_ms'], r['url'])

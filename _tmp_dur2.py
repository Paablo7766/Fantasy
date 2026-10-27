import json, collections

rows = [json.loads(l) for l in open('.cache/network_logs.jsonl', encoding='utf-8') if l.strip()]
ok = [r for r in rows if r.get('status') == 200]
print("200s:", len(ok))
buckets = collections.Counter()
for r in ok:
    d = float(r.get('duracion_ms') or 0)
    if d < 3:
        buckets['<3ms'] += 1
    elif d < 20:
        buckets['3-20'] += 1
    elif d < 200:
        buckets['20-200'] += 1
    else:
        buckets['>200ms'] += 1
print(buckets)
print("\nby hour of 200s with >=20ms:")
c = collections.Counter(r['timestamp'][:13] for r in ok if float(r.get('duracion_ms') or 0) >= 20)
for k in sorted(c):
    print("  ", k, c[k])
print("\nby hour of 200s with <3ms (sospechosas):")
c2 = collections.Counter(r['timestamp'][:13] for r in ok if float(r.get('duracion_ms') or 0) < 3)
for k in sorted(c2):
    print("  ", k, c2[k])

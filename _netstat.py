import json, collections, pathlib
p = pathlib.Path('.cache/network_logs.jsonl')
lines = p.read_text(encoding='utf-8').splitlines()
print('lines', len(lines))
st = collections.Counter(); fast = collections.Counter(); ts = []
bad = 0
for l in lines:
    if not l.strip(): continue
    try: r = json.loads(l)
    except Exception: bad += 1; continue
    st[str(r.get('status'))] += 1
    if (r.get('duracion_ms') or 0) < 2.0: fast[str(r.get('status'))] += 1
    ts.append(r.get('timestamp') or '')
print('bad', bad)
print('status', st.most_common())
print('sub-2ms', fast.most_common())
ts.sort()
print('first', ts[0], 'last', ts[-1])
# count per hour
h = collections.Counter(t[:13] for t in ts)
for k in sorted(h): print(k, h[k])

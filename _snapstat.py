import json, pathlib, collections
rows = json.loads(pathlib.Path('.cache/supabase-local/price_snapshots.json').read_text(encoding='utf-8'))
print(type(rows), len(rows))
if isinstance(rows, dict):
    print(list(rows)[:5])
    items = rows.get('rows') or []
else:
    items = rows
c = collections.Counter(str(r.get('day')) for r in items)
print(sorted(c.items())[-10:])
last = sorted(c)[-1]
sample = [r for r in items if str(r.get('day'))==last][:5]
print(json.dumps(sample, ensure_ascii=False, indent=1)[:1500])
print('stored_at max', max(str(r.get('stored_at')) for r in items))

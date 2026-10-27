import json, pathlib, datetime, sqlite3
d = json.loads(pathlib.Path('.cache/dashboard/_default/full.json').read_text(encoding='utf-8'))
v = d['value']
m = v.get('market') or {}
print('saved_at', d.get('saved_at'))
print('market fetched_at', m.get('fetched_at'), 'age', m.get('source_age_seconds'), 'stored_at', datetime.datetime.fromtimestamp(m['source_stored_at'], datetime.timezone.utc).isoformat() if m.get('source_stored_at') else None)
print('sources', json.dumps({k: {kk: vv for kk, vv in (val or {}).items() if kk in ('ok','count','from_cache','error')} for k, val in (v.get('trends') or {}).get('sources', {}).items()}, ensure_ascii=False)[:800])
print()
con = sqlite3.connect('.cache/responses.sqlite')
print([r for r in con.execute("select name from sqlite_master where type='table'")])
try:
    rows = con.execute("select key, stored_at, ttl_seconds, length(body) from responses order by stored_at desc limit 10").fetchall()
    for r in rows: print(r[0][:60], datetime.datetime.fromtimestamp(r[1], datetime.timezone.utc).isoformat(), r[2], r[3])
except Exception as e:
    print('err', e)

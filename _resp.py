import sqlite3, datetime, json
con = sqlite3.connect('.cache/responses.sqlite')
con.row_factory = sqlite3.Row
print([r[1] for r in con.execute("pragma table_info(responses)")])
for r in con.execute("select * from responses order by stored_at desc limit 6"):
    d = dict(r)
    body = d.get('body') or b''
    print('---', d.get('url','')[:90])
    print('   stored_at', datetime.datetime.fromtimestamp(d['stored_at'], datetime.timezone.utc).isoformat(), 'ttl', d.get('ttl_seconds'), 'len', len(body) if hasattr(body,'__len__') else None, 'kind', d.get('kind'))

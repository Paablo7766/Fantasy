import json, pathlib, datetime
def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
for p in ['.cache/dashboard/_default/core.json', '.cache/dashboard/_default/full.json', '.cache/dashboard/018668579/core.json']:
    d = load(p)
    print('===', p)
    print(' keys', list(d)[:14])
    print(' ok', d.get('ok'), 'last_updated', d.get('last_updated'), 'dashboard_at', d.get('dashboard_at'), 'photo_age', d.get('photo_age_seconds'), 'is_stale', d.get('is_stale'))
    m = d.get('market') or {}
    print(' market keys', list(m)[:10])
    print(' market fetched_at', m.get('fetched_at'), 'source_stored_at', m.get('source_stored_at'))
    if m.get('source_stored_at'):
        print(' market source_stored_at UTC', datetime.datetime.fromtimestamp(m['source_stored_at'], datetime.timezone.utc).isoformat())
    if isinstance(d.get('error'), dict): print(' error', d['error'])
    t = d.get('trends') or {}
    players = t.get('players') or []
    print(' trends players', len(players), 'fetched_at', t.get('fetched_at'))
    for pl in players[:4]:
        print('  ', pl.get('name'), pl.get('market_value'), 'mvc', pl.get('market_value_change'), 'pd', pl.get('price_delta'))

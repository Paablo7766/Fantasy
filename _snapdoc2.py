import json, pathlib, datetime
for p in ['.cache/dashboard/_default/full.json', '.cache/dashboard/018668579/core.json']:
    d = json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    v = d.get('value') or {}
    print('===', p, 'saved_at', d.get('saved_at'), 'saved_unix', d.get('saved_unix'))
    print('  value keys', list(v)[:14])
    print('  dashboard_at', v.get('dashboard_at'), 'last_updated', v.get('last_updated'), 'photo_age', v.get('photo_age_seconds'))
    m = v.get('market') or {}
    ssa = m.get('source_stored_at')
    print('  market fetched_at', m.get('fetched_at'), 'source_stored_at', ssa, datetime.datetime.fromtimestamp(ssa, datetime.timezone.utc).isoformat() if isinstance(ssa,(int,float)) else None)
    t = v.get('trends') or {}
    ps = t.get('players') or []
    print('  trends', len(ps), 'fetched_at', t.get('fetched_at'))
    for pl in ps[:5]:
        print('   ', pl.get('name'), pl.get('market_value'), 'mvc', pl.get('market_value_change'), 'pd', pl.get('price_delta'), 'acc', pl.get('acceleration'))
    o = v.get('optimize') or {}
    print('  optimize keys', list(o)[:12])
    for row in (o.get('xi') or [])[:5]:
        print('   xi', row.get('name'), row.get('price_delta'), row.get('market_value_change'), row.get('expected_points'))

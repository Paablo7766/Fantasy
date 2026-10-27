import json, pathlib, datetime, collections
rows = [json.loads(l) for l in pathlib.Path('.cache/network_logs.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
slow = [r for r in rows if (r.get('duracion_ms') or 0) >= 20]
print('total', len(rows), '>=20ms', len(slow))
for r in slow[-60:]:
    print(r['timestamp'], r['fuente'], r['status'], r['duracion_ms'], r['url'])

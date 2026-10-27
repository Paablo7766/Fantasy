import json, pathlib, collections
rows = [json.loads(l) for l in pathlib.Path('.cache/network_logs.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
sel = [r for r in rows if str(r.get('timestamp','')).startswith('2026-10-25') and (r.get('duracion_ms') or 0) >= 5]
print('count', len(sel))
for r in sel:
    print(r['timestamp'][:19], r['fuente'], r['status'], r['duracion_ms'], r['url'][:95])

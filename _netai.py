import json, pathlib
lines = pathlib.Path('.cache/network_logs.jsonl').read_text(encoding='utf-8').splitlines()
rows = [json.loads(l) for l in lines if l.strip()]
sel = [r for r in rows if str(r.get('timestamp','')).startswith('2026-10-25T12') or str(r.get('timestamp','')).startswith('2026-10-25T11:1') or str(r.get('timestamp','')).startswith('2026-10-25T11:2')]
for r in sel[-40:]:
    print(r['timestamp'], r['fuente'], r['status'], r['duracion_ms'], r['url'])
print('total selected', len(sel))

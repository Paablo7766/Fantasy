import json, pathlib
rows = [json.loads(l) for l in pathlib.Path('.cache/network_logs.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
rows.sort(key=lambda r: str(r.get('timestamp')))
for day in ('2026-10-25T10:11','2026-10-25T11:3'):
    sel = [r for r in rows if str(r.get('timestamp','')).startswith(day)]
    print('===', day, len(sel))
    for r in sel[:40]:
        print(' ', r['timestamp'][11:23], r['fuente'], r['status'], r['duracion_ms'], r['url'][:80])

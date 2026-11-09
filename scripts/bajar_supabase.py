"""Baja a ``.cache/supabase-local/`` lo que hay en Supabase (solo lectura remota).

Desde el 5 nov la app guarda en Supabase y el espejo local se quedó congelado
(precios hasta el 4 nov, libro de caja del 4 nov). Este script lo pone al día
para que los análisis offline vean la misma foto que la app.

- ``price_snapshots``: unión por (player_id, day). Si una fila existe en los dos
  sitios gana la remota. Nunca se pierde un día que solo esté en local.
- ``cash_ledgers``: se sustituye por la copia remota (es una foto entera).

Antes de escribir deja ``*.bak-AAAAMMDD-HHMMSS`` junto al fichero. No escribe
nada en Supabase.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".cache" / "supabase-local"
PAGE = 1000


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def _fetch(client, table: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        batch = client.table(table).select("*").range(offset, offset + PAGE - 1).execute().data
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def _backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{stamp}"))


def _write(path: Path, rows: list[dict]) -> None:
    _backup(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf8")
    tmp.replace(path)


def main() -> int:
    _load_env()
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")):
        print("Faltan SUPABASE_URL y SUPABASE_KEY en .env")
        return 1
    from supabase import create_client

    client = create_client(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_KEY"].strip())
    LOCAL.mkdir(parents=True, exist_ok=True)

    remote_prices = _fetch(client, "price_snapshots")
    path = LOCAL / "price_snapshots.json"
    local_prices = json.loads(path.read_text(encoding="utf8")) if path.exists() else []
    merged = {(r["player_id"], r["day"]): r for r in local_prices}
    merged.update({(r["player_id"], r["day"]): r for r in remote_prices})
    rows = sorted(merged.values(), key=lambda r: (r["day"], r["player_id"]))
    _write(path, rows)
    days = sorted({r["day"] for r in rows})
    print(f"price_snapshots: {len(local_prices)} local + {len(remote_prices)} remotas -> {len(rows)} ({days[0]} a {days[-1]})")

    ledgers = _fetch(client, "cash_ledgers")
    _write(LOCAL / "cash_ledgers.json", ledgers)
    print(f"cash_ledgers: {len(ledgers)} equipos")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Siembra el historial de cláusulas con el valor de mercado de cada día.

Las fotos de cláusulas anteriores al 15-nov-2026 se guardaron sin el valor del
día, y sin él una subida automática (gratis) no se distingue de una pagada.
Este script toma ``.cache/clause_snapshot_history.json``, busca el valor de
cada jugador en las fuentes locales (``price_snapshots`` del espejo y de
``responses.sqlite``, ``player_signal_log`` y ``market_listing_log``), y:

* reescribe el historial local en formato v2 (``days`` + ``values``), con
  copia ``.bak`` del original;
* con ``--subir``, lo copia en Supabase (``dashboard_snapshots``, clave
  ``clausulas:historial``) para que Render no lo pierda en cada despliegue.

Uso::

    .venv/Scripts/python.exe scripts/sembrar_historial_clausulas.py          # solo local
    .venv/Scripts/python.exe scripts/sembrar_historial_clausulas.py --subir  # y Supabase
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from toolbox import caja_rival, snapshot_remote  # noqa: E402
from toolbox.cache import cache_root  # noqa: E402
from toolbox.rival_intel import CLAUSE_SNAPSHOTS_FILENAME  # noqa: E402


def _valores_locales(cache: Path) -> dict[tuple[str, str], tuple[float, int]]:
    """``{(jugador, día): (guardado, valor)}`` con la foto guardada más tarde de cada día."""
    out: dict[tuple[str, str], tuple[float, int]] = {}

    def add(pid: object, day: object, value: object, stored: object) -> None:
        if pid is None or not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return
        if not isinstance(stored, (int, float)):
            stored = 0.0
        key = (str(pid), str(day))
        if key not in out or float(stored) >= out[key][0]:
            out[key] = (float(stored), value)

    mirror = cache / "supabase-local" / "price_snapshots.json"
    if mirror.exists():
        for row in json.loads(mirror.read_text(encoding="utf-8")):
            add(row.get("player_id"), row.get("day"), row.get("market_value"), row.get("stored_at"))
    db = cache / "responses.sqlite"
    if db.exists():
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        for sql in (
            "select player_id, day, market_value, stored_at from price_snapshots",
            "select player_id, day, price, stored_at from player_signal_log",
            "select player_id, day, market_value, stored_at from market_listing_log",
        ):
            try:
                for pid, day, value, stored in con.execute(sql):
                    add(pid, day, value, stored)
            except sqlite3.Error:
                continue
        con.close()
    return out


def sembrar(path: Path, cache: Path) -> dict:
    original = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    days = caja_rival.fusionar_historial(original)
    previos = caja_rival.valores_de_fotos(original)
    fuentes = _valores_locales(cache)
    values: dict[str, dict[str, int]] = {}
    huecos = 0
    for day, teams in days.items():
        prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        del_dia: dict[str, int] = {}
        for players in teams.values():
            for pid in players:
                value = previos.get((pid, day))
                if value is None:
                    hit = fuentes.get((pid, day)) or fuentes.get((pid, prev))
                    value = hit[1] if hit else None
                if value is None:
                    huecos += 1
                    continue
                del_dia[pid] = value
        if del_dia:
            values[day] = del_dia
    payload = {
        "version": 2,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "days": days,
        "values": values,
    }
    return {"payload": payload, "huecos": huecos, "dias": len(days), "con_valor": sum(len(v) for v in values.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subir", action="store_true", help="copiar también en Supabase")
    args = parser.parse_args()

    cache = cache_root()
    path = cache / CLAUSE_SNAPSHOTS_FILENAME
    res = sembrar(path, cache)
    print(f"Días: {res['dias']}; jugador-día con valor: {res['con_valor']}; sin valor: {res['huecos']}")

    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(json.dumps(res["payload"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Historial local reescrito en v2: {path}")

    if args.subir:
        url, key = os.getenv("SUPABASE_URL", "").strip(), os.getenv("SUPABASE_KEY", "").strip()
        if not (url and key):
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env")
            url, key = os.getenv("SUPABASE_URL", "").strip(), os.getenv("SUPABASE_KEY", "").strip()
        if not (url and key):
            print("Sin SUPABASE_URL / SUPABASE_KEY: no se sube nada.")
            return 1
        from supabase import create_client

        snapshot_remote._client_factory = lambda: create_client(url, key)
        remoto = caja_rival.leer_remoto()
        payload = res["payload"]
        if remoto:
            # Lo que Render guardó después de la copia local también cuenta.
            payload["days"] = caja_rival.fusionar_historial(payload, remoto)
            for (pid, day), value in caja_rival.valores_de_fotos(remoto).items():
                payload["values"].setdefault(day, {}).setdefault(pid, value)
        ok = caja_rival.publicar_remoto(payload)
        print("Copiado en Supabase (clausulas:historial)." if ok else "No se pudo copiar en Supabase.")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Congela la foto de la próxima jornada y la sube a Supabase.

Descarga las cuotas que OddsPapi deja ver (como mucho 9 días por delante),
las archiva, y guarda alineaciones, p_titular, xP y precios de la última
señal anterior al primer saque. La foto se reescribe en cada pasada mientras
ese saque no haya llegado.

Uso, desde la carpeta del proyecto:

    .\\.venv\\Scripts\\python.exe scripts\\foto_previa.py

Para que haya al menos una foto en las 24 h previas al primer saque, este
mismo comando tiene que ejecutarse solo en ese tramo (el Programador de
tareas de Windows, a diario). Pulsar Actualizar también la reescribe, pero
si nadie lo pulsa esa tarde la foto no existe.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _stdout_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main() -> int:
    _stdout_utf8()
    if not os.getenv("ODDSPAPI_API_KEY", "").strip():
        print("Falta ODDSPAPI_API_KEY: sin ella no hay cuotas que guardar.")
        return 1
    os.environ["LALIGA_ENV"] = "production"

    from toolbox.cache import cache_root
    from toolbox.history_remote import push
    from toolbox.net import ExternalClient
    from toolbox.odds_archive import archive_match_odds
    from toolbox.pre_lock import cierre_proximo, freeze_pre_lock, leer, players_desde_senales
    from toolbox.scrapers import _fetch_oddspapi

    now = datetime.now(timezone.utc)
    client = ExternalClient()
    try:
        index, cached, error = _fetch_oddspapi(client, ttl=1, fresh=True, now=now)
    finally:
        client.close()
    print(f"cuotas: {len(index)} partidos, caché={cached}, error={error}")
    if not index:
        print("OddsPapi no ha devuelto partidos. No guardo una foto vacía.")
        return 1
    n_scorers = sum(len(row.get("anytime_scorers") or []) for row in index.values())
    print(f"goleadores en esta descarga: {n_scorers}")
    archive_match_odds(index)

    cierre = cierre_proximo(index, now)
    if cierre is None:
        print("Ningún partido de esta descarga cae en el calendario de la temporada.")
        return 1
    jornada, kickoff = cierre
    conn = sqlite3.connect(cache_root() / "responses.sqlite")
    try:
        players = players_desde_senales(kickoff.timestamp(), conn=conn)
    finally:
        conn.close()
    print(f"J{jornada} cierra {kickoff.isoformat()} · señales previas: {len(players)} jugadores")
    foto = freeze_pre_lock(players, index, now=now)
    print(f"foto: {foto}")
    subida = push()
    print(f"supabase: {'subida' if subida else 'no se ha subido (faltan SUPABASE_URL/KEY o falló la copia)'}")
    guardada = leer(jornada)
    if guardada is None:
        return 1
    payload = guardada["payload"]
    cuando = datetime.fromtimestamp(guardada["stored_at"], tz=timezone.utc)
    print(f"guardada {cuando.isoformat()} · jugadores {len(payload['players'])} · partidos {len(payload['matches'])} · goleadores {len(payload['scorers'])}")
    for match in payload["matches"]:
        print(f"  {match['match_key']} {match['kickoff']} 1X2={match['odds_1x2']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

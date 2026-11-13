"""Sube los puntos del catálogo a Supabase y reescribe la foto de la J13.

No llama a LaLiga ni a OddsPapi. Lee el catálogo y las actas que ya están
en disco, y la foto previa que ya se guardó.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    os.environ.setdefault("LALIGA_ENV", "production")

    from toolbox import snapshot_remote
    from toolbox.actas_catalogo import KEY, KIND, acuerdo_puntos_y_minutos, documento, guardar
    from toolbox.history_remote import push
    from toolbox.pre_lock import freeze_pre_lock, leer

    doc = documento()
    jugadores = doc["players"]
    con_puntos = sum(1 for p in jugadores if any(w.get("points") is not None for w in p["weeks"]))
    con_minutos = sum(1 for p in jugadores if any(w.get("minutes") is not None for w in p["weeks"]))
    print(f"catálogo {len(jugadores)} · con puntos {con_puntos} · con minutos {con_minutos}")
    print("acuerdo", acuerdo_puntos_y_minutos(doc))
    print("supabase actas", "subidas" if guardar() else "no subidas")
    remoto = snapshot_remote.load(KIND, KEY)
    remoto_n = len((remoto or {}).get("value", {}).get("players") or [])
    print("supabase lectura", remoto_n)

    foto = leer(13)
    if foto is None:
        print("no hay foto de la J13")
        return 1
    payload = foto["payload"]
    odds: dict = {}
    for match in payload["matches"]:
        goleadores = [s for s in payload["scorers"] if s.get("match_key") == match["match_key"]]
        odds[match["match_key"]] = {
            "source": match.get("source") or "oddspapi",
            "kickoff": match.get("kickoff"),
            "odds_1x2": tuple(match["odds_1x2"]),
            "odds_ou25": tuple(match["odds_ou25"]) if match.get("odds_ou25") else None,
            "anytime_scorers": goleadores,
        }
    escrita = freeze_pre_lock(
        payload["players"],
        odds,
        lock=(13, datetime.fromisoformat(foto["kickoff"])),
    )
    print("foto", escrita)
    print("supabase histórico", "subido" if push() else "no subido")
    nueva = leer(13)
    if nueva is None:
        return 1
    gente = nueva["payload"]["players"]
    prod = sum(1 for p in gente if p.get("p_titular_prod") is not None)
    reaj = sum(1 for p in gente if p.get("p_titular_reajuste") is not None)
    print(f"foto jugadores {len(gente)} · p producción {prod} · p reajuste {reaj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

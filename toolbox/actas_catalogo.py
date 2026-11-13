"""Puntos por jornada del catálogo, y minutos solo donde la plantilla los trae.

La ficha suelta del jugador no existe en la API (responde 404), así que los
minutos de quien no está en una plantilla de la liga no se pueden bajar. Lo
que sí trae el catálogo es ``weekPoints``. Esta copia vive en Supabase
(``dashboard_snapshots``, clave ``actas:2026-27``), no en un archivo de
``.cache``.
"""

from __future__ import annotations

import time
from typing import Any

from toolbox import snapshot_remote

KIND = "actas"
KEY = "2026-27"


def documento() -> dict[str, Any]:
    from toolbox.net import LaligaClient, no_network
    from toolbox.player_history import actas_en_cache

    with no_network():
        client = LaligaClient()
        try:
            catalogo = client.players_document(fresh=False)
        finally:
            client.close()
    actas = actas_en_cache()
    jugadores: list[dict[str, Any]] = []
    for row in catalogo:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "")
        if not pid:
            continue
        semanas: dict[int, dict[str, Any]] = {}
        serie = row.get("weekPoints")
        if isinstance(serie, list):
            for item in serie:
                if not isinstance(item, dict) or not isinstance(item.get("weekNumber"), int):
                    continue
                puntos = item.get("points")
                if isinstance(puntos, bool) or not isinstance(puntos, (int, float)):
                    continue
                semanas[int(item["weekNumber"])] = {"points": float(puntos), "minutes": None}
        acta = actas.get(pid)
        if isinstance(acta, dict):
            for week, valor in (acta.get("weeks") or {}).items():
                if not isinstance(week, int):
                    continue
                minutos = float(valor[1])
                previa = semanas.get(week)
                if previa is None:
                    semanas[week] = {"points": None, "minutes": minutos}
                else:
                    previa["minutes"] = minutos
        jugadores.append(
            {
                "id": pid,
                "nickname": row.get("nickname") if isinstance(row.get("nickname"), str) else None,
                "status": row.get("playerStatus") if isinstance(row.get("playerStatus"), str) else None,
                "position_id": row.get("positionId"),
                "team_id": row.get("teamId"),
                "weeks": [{"j": j, **semanas[j]} for j in sorted(semanas)],
            }
        )
    return {"season": "2026/27", "players": jugadores}


def guardar() -> bool:
    """Sube el documento. ``False`` si Supabase no está configurado o falla."""
    return snapshot_remote.save(KIND, KEY, {"saved_unix": time.time(), "value": documento()})


def acuerdo_puntos_y_minutos(doc: dict[str, Any]) -> dict[str, int]:
    """En quien tiene las dos cosas: puntos > 0 contra titular de 45 minutos."""
    cuenta = {"ambos": 0, "puntos_sin_45": 0, "cero_y_45": 0, "cero_sin_45": 0, "sin_minutos": 0}
    for player in doc.get("players") or []:
        if not isinstance(player, dict):
            continue
        for week in player.get("weeks") or []:
            if not isinstance(week, dict):
                continue
            minutos = week.get("minutes")
            puntos = week.get("points")
            if not isinstance(minutos, (int, float)) or isinstance(minutos, bool):
                if isinstance(puntos, (int, float)) and not isinstance(puntos, bool):
                    cuenta["sin_minutos"] += 1
                continue
            if not isinstance(puntos, (int, float)) or isinstance(puntos, bool):
                continue
            titular = minutos >= 45
            jugo = puntos > 0
            if jugo and titular:
                cuenta["ambos"] += 1
            elif jugo and not titular:
                cuenta["puntos_sin_45"] += 1
            elif not jugo and titular:
                cuenta["cero_y_45"] += 1
            else:
                cuenta["cero_sin_45"] += 1
    return cuenta

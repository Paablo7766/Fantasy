"""Historial por jugador a partir de ``playerMaster.lastStats`` en la caché.

Lo comparten el backtest del xP y el reajuste automático de ``p_titular``:
una sola lectura de los cuerpos del scraper para ambos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POSITION_BY_ID = {1: "POR", 2: "DEF", 3: "MC", 4: "DEL"}

#: Cada acción del acta viene como ``[cantidad, puntos]``. Se agrupan en los
#: bloques del xP 2.0: el suelo (minutos, valoración de cronistas, acciones,
#: paradas y tarjetas) es estable de una semana a otra; gol, asistencia y
#: portería dependen del partido. ``marca_points`` trae ``-1`` como cantidad y
#: los puntos de valoración (0–4) en la segunda posición.
CATEGORIA_ACCION = {
    "mins_played": "min",
    "goals": "goal",
    "goal_assist": "ast",
    "offtarget_att_assist": "ast",
    "goals_conceded": "def",
    "saves": "gk",
    "penalty_save": "gk",
    "marca_points": "rating",
    "ball_recovery": "act",
    "effective_clearance": "act",
    "won_contest": "act",
    "pen_area_entries": "act",
    "total_scoring_att": "act",
    "poss_lost_all": "act",
    "penalty_won": "act",
    "yellow_card": "neg",
    "second_yellow_card": "neg",
    "red_card": "neg",
    "own_goals": "neg",
    "penalty_failed": "neg",
    "penalty_conceded": "neg",
}


def desglose_acta(stats: Any) -> dict[str, Any] | None:
    """Puntos por bloque y cantidades de un ``lastStats[].stats``."""
    if not isinstance(stats, dict):
        return None
    puntos: dict[str, float] = {}
    cantidades: dict[str, float] = {}
    for clave, valor in stats.items():
        if not isinstance(valor, list) or len(valor) < 2:
            continue
        cantidad, pts = valor[0], valor[1]
        if isinstance(pts, (int, float)) and not isinstance(pts, bool):
            bloque = CATEGORIA_ACCION.get(clave, "otros")
            puntos[bloque] = puntos.get(bloque, 0.0) + float(pts)
        if isinstance(cantidad, (int, float)) and not isinstance(cantidad, bool):
            cantidades[clave] = float(cantidad)
    if not puntos:
        return None
    return {"puntos": puntos, "cantidades": cantidades}


def _walk(node: Any):
    if isinstance(node, dict):
        if isinstance(node.get("lastStats"), list):
            yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _read_json(path: Path) -> Any:
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    body = wrapper.get("body")
    return json.loads(body) if isinstance(body, str) else body


def load_history(bodies: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Jugadores con equipo y, si está en caché, el payload de Understat."""
    players: dict[str, dict[str, Any]] = {}
    understat: dict[str, Any] | None = None
    for path in bodies.iterdir():
        try:
            payload = _read_json(path)
        except (OSError, ValueError, AttributeError):
            continue
        if understat is None and _looks_like_understat(payload):
            understat = payload
        for master in _walk(payload):
            pid = str(master.get("id") or "")
            if not pid:
                continue
            team = master.get("team") if isinstance(master.get("team"), dict) else {}
            entry = players.setdefault(
                pid,
                {
                    "name": master.get("nickname") or master.get("name"),
                    "position": POSITION_BY_ID.get(master.get("positionId"), "MC"),
                    "team": team.get("name") if isinstance(team.get("name"), str) else None,
                    "weeks": {},
                    "desglose": {},
                },
            )
            if isinstance(team.get("name"), str):
                entry["team"] = team["name"]
            for stat in master["lastStats"]:
                week = stat.get("weekNumber")
                points = stat.get("totalPoints")
                if not isinstance(week, int) or not isinstance(points, (int, float)):
                    continue
                minutes = (stat.get("stats") or {}).get("mins_played") or [0]
                mins = float(minutes[0] or 0) if isinstance(minutes, list) else float(minutes or 0)
                entry["weeks"][week] = (float(points), mins)
                desglose = desglose_acta(stat.get("stats"))
                if desglose is not None:
                    entry.setdefault("desglose", {})[week] = desglose
    return players, understat


_CACHE_ACTAS: dict[str, Any] = {"firma": None, "jugadores": {}}


def actas_en_cache() -> dict[str, dict[str, Any]]:
    """``load_history`` de ``.cache/scraper_bodies``, releído solo si cambia la carpeta."""
    from toolbox.cache import cache_root

    carpeta = cache_root() / "scraper_bodies"
    try:
        ficheros = list(carpeta.iterdir())
        firma = (str(carpeta), len(ficheros), max((f.stat().st_mtime_ns for f in ficheros), default=0))
    except OSError:
        return {}
    if _CACHE_ACTAS["firma"] != firma:
        try:
            jugadores, _ = load_history(carpeta)
        except Exception:  # noqa: BLE001 — sin actas el motor vuelve a la fórmula de respaldo
            jugadores = {}
        _CACHE_ACTAS["firma"] = firma
        _CACHE_ACTAS["jugadores"] = jugadores
    return _CACHE_ACTAS["jugadores"]


def _looks_like_understat(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    dates = payload.get("dates")
    return isinstance(dates, list) and bool(dates) and isinstance(dates[0], dict) and "isResult" in dates[0]

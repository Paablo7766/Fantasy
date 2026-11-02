"""Historial por jugador a partir de ``playerMaster.lastStats`` en la caché.

Lo comparten el backtest del xP y el reajuste automático de ``p_titular``:
una sola lectura de los cuerpos del scraper para ambos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POSITION_BY_ID = {1: "POR", 2: "DEF", 3: "MC", 4: "DEL"}


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
    return players, understat


def _looks_like_understat(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    dates = payload.get("dates")
    return isinstance(dates, list) and bool(dates) and isinstance(dates[0], dict) and "isResult" in dates[0]

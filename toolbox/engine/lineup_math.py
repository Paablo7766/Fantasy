"""Once de máxima puntuación y WAR de cada titular.

El WAR es la bajada de puntos del once si ese jugador sale hoy y el mejor
suplente disponible ocupa su sitio, respetando una formación válida. Si sin
él no se puede juntar un once, la jornada queda a cero y se pierde todo.

Dentro de una formación el once óptimo son los mejores de cada puesto: no
hay más restricciones que el cupo. No hace falta un solver para eso.
"""

from __future__ import annotations

from typing import Any

from toolbox.analyzer import FORMATIONS, POSITIONS, XI_SIZE


def _rows(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id")
        position = player.get("position")
        points = player.get("jornada")
        if not isinstance(player_id, str) or not player_id or player_id in seen:
            continue
        if position not in POSITIONS:
            continue
        if isinstance(points, bool) or not isinstance(points, (int, float)):
            continue
        seen.add(player_id)
        rows.append(player)
    return rows


def solve_best_xi(players: list[dict[str, Any]]) -> dict[str, Any]:
    """Maximiza la suma de ``jornada`` con una formación de LaLiga.

    Sin once legal el resultado es ``ok: False`` y cero puntos: en el
    reglamento un hueco anula la jornada.
    """
    rows = _rows(players)
    empty = {"ok": False, "puntos": 0.0, "player_ids": [], "formacion": None}
    if len(rows) < XI_SIZE:
        return empty
    by_position: dict[str, list[dict[str, Any]]] = {position: [] for position in POSITIONS}
    for row in rows:
        by_position[row["position"]].append(row)
    for pool in by_position.values():
        pool.sort(key=lambda row: (-float(row["jornada"]), str(row["player_id"])))

    best: tuple[float, list[dict[str, Any]], str] | None = None
    for name, slots in FORMATIONS.items():
        if any(len(by_position[position]) < need for position, need in slots.items()):
            continue
        picked: list[dict[str, Any]] = []
        for position, need in slots.items():
            picked.extend(by_position[position][:need])
        total = sum(float(row["jornada"]) for row in picked)
        if best is None or total > best[0]:
            best = (total, picked, name)
    if best is None:
        return empty
    total, picked, name = best
    return {
        "ok": True,
        "puntos": round(total, 4),
        "player_ids": [row["player_id"] for row in picked],
        "formacion": name,
    }


def war_del_once(
    xi: list[dict[str, Any]],
    banquillo: list[dict[str, Any]],
) -> dict[str, float]:
    """Puntos que pierde el once publicado si se vende cada titular.

    La bajada se mide contra ese once, no contra otro reparto. Si al quitarlo
    el mejor once legal no baja, la pérdida es cero.
    """
    titulares = [row for row in xi if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    suplentes = [row for row in banquillo if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    if len(titulares) != XI_SIZE:
        return {}
    if not solve_best_xi(titulares)["ok"]:
        return {}
    actual = round(sum(float(row.get("jornada") or 0.0) for row in titulares), 4)
    perdidas: dict[str, float] = {}
    for jugador in titulares:
        player_id = jugador["player_id"]
        resto = [row for row in titulares + suplentes if row.get("player_id") != player_id]
        nuevo = solve_best_xi(resto)
        if not nuevo["ok"]:
            perdidas[player_id] = round(actual, 2)
            continue
        perdidas[player_id] = round(max(0.0, actual - float(nuevo["puntos"])), 2)
    return perdidas

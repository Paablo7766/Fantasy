"""Once de máxima puntuación y WAR de cada titular.

El WAR es la bajada de puntos del once si ese jugador sale hoy y el mejor
de la plantilla ocupa su sitio en el once, respetando una formación válida.
Esta liga no tiene banquillo: si un titular no juega, ese hueco hace 0 y
nadie entra por él. Quien no está en los 11 no suma. Si sin el jugador no se
puede juntar un once, la jornada queda a cero y se pierde todo.

Dentro de una formación el once óptimo son los mejores de cada puesto: no
hay más restricciones que el cupo. No hace falta un solver para eso.
"""

from __future__ import annotations

from typing import Any

from toolbox.analyzer import FORMATIONS, POSITIONS, XI_SIZE


#: Peso de la varianza de titularidad: un once que depende de un dudoso vale menos
#: que su media. 0,05 es el castigo conservador de la ruleta rusa (p · (1 − p) · xP²).
LAMBDA_VAR = 0.05
#: Un titular con esta probabilidad o menos es un hueco que hay que tapar.
UMBRAL_HUECO = 0.30
HUECO_OBLIGATORIO = "HUECO_OBLIGATORIO"


def prob_titular(row: dict[str, Any]) -> float | None:
    """Probabilidad de titularidad en 0–1 (acepta 0–100). ``None`` si no se conoce."""
    for key in ("p_titular", "prob_titular"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            continue
        number = float(value)
        if number > 1.0:
            number /= 100.0
        return number if number <= 1.0 else None
    return None


def penalizacion_varianza(row: dict[str, Any], lambda_var: float = LAMBDA_VAR) -> float:
    """``lambda · p · (1 − p) · xP_cond²``: la varianza de jugar o no jugar.

    ``xP_cond`` son los puntos si sale de titular (``si_titular``); sin ese dato
    se usa ``jornada``. Sin probabilidad conocida no hay penalización.
    """
    p = prob_titular(row)
    if p is None or lambda_var <= 0:
        return 0.0
    cond = row.get("si_titular")
    if isinstance(cond, bool) or not isinstance(cond, (int, float)):
        cond = row.get("jornada")
    cond = float(cond) if isinstance(cond, (int, float)) and not isinstance(cond, bool) else 0.0
    return lambda_var * p * (1.0 - p) * cond * cond


def huecos_obligatorios(titulares: list[dict[str, Any]]) -> list[str]:
    """Titulares con ``p_titular <= 30 %``: el plan debe priorizar taparlos."""
    ids: list[str] = []
    for row in titulares:
        p = prob_titular(row) if isinstance(row, dict) else None
        if p is not None and p <= UMBRAL_HUECO and isinstance(row.get("player_id"), str):
            ids.append(row["player_id"])
    return ids


def _ajustado(row: dict[str, Any], lambda_var: float) -> float:
    return float(row["jornada"]) - penalizacion_varianza(row, lambda_var)


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


def solve_best_xi(players: list[dict[str, Any]], *, lambda_var: float = LAMBDA_VAR) -> dict[str, Any]:
    """Maximiza la suma de ``jornada`` menos la varianza de titularidad.

    ``puntos`` es la suma real de ``jornada`` del once elegido; el criterio de
    elección usa ``puntos_ajustados``.

    Sin once legal el resultado es ``ok: False`` y cero puntos: en el
    reglamento un hueco anula la jornada.
    """
    rows = _rows(players)
    empty = {
        "ok": False,
        "puntos": 0.0,
        "puntos_ajustados": 0.0,
        "huecos_obligatorios": [],
        "player_ids": [],
        "formacion": None,
    }
    if len(rows) < XI_SIZE:
        return empty
    by_position: dict[str, list[dict[str, Any]]] = {position: [] for position in POSITIONS}
    for row in rows:
        by_position[row["position"]].append(row)
    for pool in by_position.values():
        pool.sort(key=lambda row: (-_ajustado(row, lambda_var), str(row["player_id"])))

    best: tuple[float, list[dict[str, Any]], str] | None = None
    for name, slots in FORMATIONS.items():
        if any(len(by_position[position]) < need for position, need in slots.items()):
            continue
        picked: list[dict[str, Any]] = []
        for position, need in slots.items():
            picked.extend(by_position[position][:need])
        total = sum(_ajustado(row, lambda_var) for row in picked)
        if best is None or total > best[0]:
            best = (total, picked, name)
    if best is None:
        return empty
    ajustado, picked, name = best
    total = sum(float(row["jornada"]) for row in picked)
    return {
        "ok": True,
        "puntos": round(total, 4),
        "puntos_ajustados": round(ajustado, 4),
        "huecos_obligatorios": huecos_obligatorios(picked),
        "player_ids": [row["player_id"] for row in picked],
        "formacion": name,
    }


def war_del_once(
    xi: list[dict[str, Any]],
    banquillo: list[dict[str, Any]],
) -> dict[str, float]:
    """Puntos que pierde el once publicado si se vende cada titular.

    La bajada se mide contra ese once, no contra otro reparto. El relevo es
    alguien a quien alineas en su lugar antes del cierre, no un suplente que
    entre solo si el titular no juega. Si al quitarlo el mejor once legal no
    baja, la pérdida es cero. Nunca supera los puntos del propio jugador: sin
    recambio en su puesto se ficha otro, no se pierde la jornada entera.
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
        propios = float(jugador.get("jornada") or 0.0)
        if not nuevo["ok"]:
            # Sin recambio en su puesto el hueco se tapa fichando: se pierden sus puntos, no el once entero.
            perdidas[player_id] = round(max(0.0, propios), 2)
            continue
        perdidas[player_id] = round(min(max(0.0, actual - float(nuevo["puntos"])), max(0.0, propios)), 2)
    return perdidas

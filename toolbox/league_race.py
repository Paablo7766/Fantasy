"""Capa relativa de liga: contra quién se juega la jornada.

El motor de once optimiza contra el vacío. Aquí se añade el contexto que
cambia la decisión: la brecha con el líder, el once esperado de cada rival,
la postura (ventaja o remontada) y el valor de negación de un fichaje.

No scrapea nada y no envía órdenes: solo ordena lo que ya está en ``squads``
y ``trends``.
"""

from __future__ import annotations

from typing import Any

from toolbox.analyzer import (
    FORMATIONS,
    POSITIONS,
    REMONTADA_POSTURE,
    VENTAJA_POSTURE,
    NEUTRAL_POSTURE,
    RiskPosture,
    XI_SIZE,
    Candidate,
    candidates_from_squad,
    index_trends,
    own_squad,
    projected_lineup_points,
)

# Una jornada normal mueve decenas de puntos. Por debajo de esta brecha no
# se renuncia a nada: se juega "neutro" hasta que la distancia es de una
# jornada completa.
REMODELADA_GAP = -20
VENTAJA_GAP = 0

MODE_COPY = {
    "ventaja": {
        "label": "Modo ventaja",
        "headline": "Protege lo que ya tienes",
        "detail": "El once prioriza minutos y titularidad segura sobre picos altos.",
    },
    "remontada": {
        "label": "Modo remontada",
        "headline": "Necesitas techo, no suelo",
        "detail": "El once paga el P90: delanteros con picos antes que rotación segura.",
    },
    "neutro": {
        "label": "Modo ajustado",
        "headline": "Peleas sin regalar nada",
        "detail": "La brecha aún no obliga a elegir entre suelo y techo.",
    },
    "sin_tabla": {
        "label": "Sin clasificación",
        "headline": "La liga no trae puntos todavía",
        "detail": "Sin ranking ni puntos no se inventa la brecha: el motor va neutro.",
    },
}

POSTURES = {
    "ventaja": VENTAJA_POSTURE,
    "remontada": REMONTADA_POSTURE,
    "neutro": NEUTRAL_POSTURE,
    "sin_tabla": NEUTRAL_POSTURE,
}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _project_roster(roster: list[Candidate]) -> dict[str, Any]:
    """Once esperado de una plantilla rival, sin ILP.

    Se prueban las formaciones válidas y se colocan los mejores por objetivo.
    Es una proyección, no una alineación: el rival puede alinear peor.
    """
    eligible = [candidate for candidate in roster if candidate.eligible]
    if not eligible:
        return {
            "expected_points": None,
            "ceiling_points": None,
            "formation": None,
            "players_available": 0,
            "gaps": [],
        }
    best: tuple[float, str, list[Candidate], list[str]] | None = None
    for name, slots in FORMATIONS.items():
        placed: list[Candidate] = []
        gaps: list[str] = []
        for position in POSITIONS:
            pool = sorted(
                (candidate for candidate in eligible if candidate.position == position),
                key=lambda candidate: (candidate.objective, candidate.jornada_ev),
                reverse=True,
            )
            need = slots[position]
            placed.extend(pool[:need])
            if len(pool) < need:
                gaps.append(position)
        if len(placed) != XI_SIZE:
            continue
        total = round(sum(candidate.jornada_ev for candidate in placed), 4)
        if best is None or total > best[0]:
            best = (total, name, placed, gaps)
    if best is None:
        return {
            "expected_points": None,
            "ceiling_points": None,
            "formation": None,
            "players_available": len(eligible),
            "gaps": sorted({candidate.position for candidate in eligible}),
        }
    total, formation, placed, gaps = best
    ceilings = [
        float(candidate.ceiling_points) * (candidate.p_titular if candidate.p_titular is not None else 1.0)
        for candidate in placed
        if isinstance(candidate.ceiling_points, (int, float)) and not isinstance(candidate.ceiling_points, bool)
    ]
    return {
        "expected_points": round(total, 2),
        "ceiling_points": round(sum(ceilings), 2) if len(ceilings) == len(placed) else None,
        "formation": formation,
        "players_available": len(eligible),
        "gaps": gaps,
    }


def _thin_positions(roster: list[Candidate]) -> list[str]:
    """Posiciones donde el rival no tiene ni un recambio.

    Se compara con la formación que ese rival puede alinear: si tiene
    exactamente los defensas que exige su once, cualquier baja le abre un
    hueco. Sin spare, la posición está floja.
    """
    eligible = [candidate for candidate in roster if candidate.eligible]
    counts = {position: 0 for position in POSITIONS}
    for candidate in eligible:
        if candidate.position in counts:
            counts[candidate.position] += 1
    best_slots: dict[str, int] | None = None
    best_filled = -1
    for slots in FORMATIONS.values():
        filled = sum(min(counts[position], slots[position]) for position in POSITIONS)
        if filled > best_filled:
            best_filled = filled
            best_slots = slots
    if best_slots is None:
        return list(POSITIONS)
    return [position for position in POSITIONS if counts[position] <= best_slots[position]]


def _mode_for(gap: int | None) -> str:
    if gap is None:
        return "sin_tabla"
    if gap >= VENTAJA_GAP:
        return "ventaja"
    if gap <= REMODELADA_GAP:
        return "remontada"
    return "neutro"


def posture_from_squads(squads: dict[str, Any] | None) -> RiskPosture:
    """Postura del motor a partir de la tabla. Sin puntos, neutro."""
    mode = mode_from_squads(squads)
    return POSTURES.get(mode["name"], NEUTRAL_POSTURE)


def mode_from_squads(squads: dict[str, Any] | None) -> dict[str, Any]:
    """Brecha y postura usando solo ``squads`` (sin trends ni mercado)."""
    document = squads if isinstance(squads, dict) else {}
    own = own_squad(document)
    own_points = _int(own.get("points")) if own else None
    ranked = [
        squad
        for squad in document.get("squads") or []
        if isinstance(squad, dict) and squad.get("rank") is not None and squad.get("error") is None
    ]
    ranked.sort(key=lambda squad: _int(squad.get("rank")) or 999)
    leader = ranked[0] if ranked else None
    leader_points = _int(leader.get("points")) if leader else None
    gap = (own_points - leader_points) if own_points is not None and leader_points is not None else None
    mode = _mode_for(gap)
    copy = MODE_COPY[mode]
    return {
        "name": mode,
        "label": copy["label"],
        "headline": copy["headline"],
        "detail": copy["detail"],
        "gap_to_leader": gap,
        "own_points": own_points,
        "own_rank": _int(own.get("rank")) if own else None,
    }


def build_league_race(
    squads: dict[str, Any] | None,
    trends: dict[str, Any] | None,
    optimize: dict[str, Any] | None,
    *,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Brecha, tabla proyectada, postura y valor de negación."""
    document = squads if isinstance(squads, dict) else {}
    own = own_squad(document)
    indexed = index_trends(trends)
    roster_by_team: dict[str, list[Candidate]] = {}
    rows: list[dict[str, Any]] = []
    rivals_raw = [
        squad
        for squad in document.get("squads") or []
        if isinstance(squad, dict) and squad.get("error") is None
    ]
    for squad in rivals_raw:
        team_id = squad.get("team_id") if isinstance(squad.get("team_id"), str) else None
        roster = candidates_from_squad(squad, indexed)
        if team_id:
            roster_by_team[team_id] = roster
        projection = _project_roster(roster)
        rows.append(
            {
                "team_id": team_id,
                "manager_name": squad.get("manager_name") if isinstance(squad.get("manager_name"), str) else None,
                "fantasy_team_name": squad.get("fantasy_team_name")
                if isinstance(squad.get("fantasy_team_name"), str)
                else None,
                "is_self": squad.get("is_self") is True,
                "rank": _int(squad.get("rank")),
                "points": _int(squad.get("points")),
                "cash_eur": _int(squad.get("cash")),
                "player_count": len(squad.get("players") or []),
                "thin_positions": _thin_positions(roster),
                "projection": projection,
            }
        )

    own_row = next((row for row in rows if row["is_self"]), None)
    own_points = own_row["points"] if own_row else None
    own_rank = own_row["rank"] if own_row else None
    ranked = [row for row in rows if row["rank"] is not None]
    ranked.sort(key=lambda row: row["rank"])
    leader = ranked[0] if ranked else None
    gap = (own_points - leader["points"]) if own_points is not None and leader and leader["points"] is not None else None
    mode = _mode_for(gap)
    copy = MODE_COPY[mode]

    # Vecinos directos: el que está justo encima y justo debajo.
    above = None
    below = None
    if own_rank is not None:
        for row in ranked:
            rank = row["rank"]
            if rank is None or row["is_self"]:
                continue
            if rank < own_rank:
                above = row
            elif rank > own_rank and below is None:
                below = row
                break

    def _edge(row: dict[str, Any] | None, *, ahead: bool) -> dict[str, Any] | None:
        if row is None or own_points is None or row.get("points") is None:
            return None
        delta = own_points - int(row["points"])
        return {
            "team_id": row.get("team_id"),
            "manager_name": row.get("manager_name"),
            "rank": row.get("rank"),
            "points": row.get("points"),
            "edge_points": delta,
            # Si estoy por delante, edge > 0 es colchón. Si voy detrás, < 0 es déficit.
            "ahead": ahead,
        }

    my_projection = _project_roster(roster_by_team.get(own.get("team_id"), [])) if own else None
    if isinstance(optimize, dict) and optimize.get("ok") is not False and optimize.get("matchday_void") is not True:
        points = projected_lineup_points(optimize)
        if points is not None:
            my_projection = {
                **(my_projection or {}),
                "expected_points": points,
                "formation": optimize.get("formation") if isinstance(optimize.get("formation"), str) else None,
                "source": "optimize",
            }

    rivals = [row for row in rows if not row["is_self"]]
    projected = [
        row["projection"]["expected_points"]
        for row in rivals
        if isinstance(row["projection"].get("expected_points"), (int, float))
    ]
    league_projection = round(sum(projected) / len(projected), 2) if projected else None

    denial = _denial_rows(rivals, market=market, indexed=indexed, own_team_id=own.get("team_id") if own else None)

    headline = _headline(gap, mode, leader, own_rank)
    return {
        "ok": True,
        "command": "league-race",
        "league_id": document.get("league_id"),
        "team_id": own.get("team_id") if own else None,
        "mode": {
            "name": mode,
            "label": copy["label"],
            "headline": copy["headline"],
            "detail": copy["detail"],
            "gap_to_leader": gap,
            "own_points": own_points,
            "own_rank": own_rank,
            "leader": {
                "team_id": leader.get("team_id"),
                "manager_name": leader.get("manager_name"),
                "points": leader.get("points"),
                "rank": leader.get("rank"),
            }
            if leader
            else None,
            "above": _edge(above, ahead=True),
            "below": _edge(below, ahead=False),
        },
        "headline": headline,
        "my_projection": my_projection,
        "league_projection": league_projection,
        "table": sorted(rows, key=lambda row: (row["rank"] is None, row["rank"] or 99, row["manager_name"] or "")),
        "rivals": rivals,
        "denial": denial,
        "sends": False,
    }


def _headline(gap: int | None, mode: str, leader: dict[str, Any] | None, own_rank: int | None) -> str:
    if gap is None:
        return "Sin clasificación: no hay brecha que jugar."
    if gap > 0:
        return f"Vas {gap} pts arriba del líder." if own_rank == 1 else f"Vas {gap} pts por delante."
    if gap == 0:
        return "Empatas con el líder: cualquier punto desempata."
    return f"Vas {abs(gap)} pts abajo del líder."


def _denial_rows(
    rivals: list[dict[str, Any]],
    *,
    market: dict[str, Any] | None,
    indexed: dict[str, dict[str, Any]],
    own_team_id: Any,
) -> list[dict[str, Any]]:
    """Cuánto duele que un rival directo se lleve ese fichaje.

    No es una probabilidad: es el recuento de rivales que (a) tienen esa
    posición floja y (b) pueden pagar el precio de salida.
    """
    listings = [
        row
        for row in ((market or {}).get("listings") or [])
        if isinstance(row, dict) and isinstance(row.get("player_id"), str)
    ]
    if not listings:
        return []
    rows: list[dict[str, Any]] = []
    for listing in listings:
        player_id = listing["player_id"]
        if isinstance(own_team_id, str) and listing.get("seller_team_id") == own_team_id:
            continue
        position = listing.get("position") if isinstance(listing.get("position"), str) else None
        if position is None:
            trend = indexed.get(player_id) or {}
            position = trend.get("position") if isinstance(trend.get("position"), str) else None
        if position is None:
            continue
        price = _int(listing.get("sale_price")) or _int(listing.get("leading_bid")) or 0
        needy: list[str] = []
        for row in rivals:
            if position not in (row.get("thin_positions") or []):
                continue
            cash = _int(row.get("cash_eur"))
            if cash is not None and price and cash < price:
                continue
            name = row.get("manager_name") or row.get("fantasy_team_name")
            if isinstance(name, str) and name:
                needy.append(name)
        if not needy:
            continue
        rows.append(
            {
                "player_id": player_id,
                "name": listing.get("name"),
                "nickname": listing.get("nickname"),
                "position": position,
                "sale_price": price or None,
                "managers": needy[:4],
                "count": len(needy),
                "label": f"{len(needy)} rival{'es' if len(needy) > 1 else ''} con {position} flojo",
            }
        )
    rows.sort(key=lambda row: (-int(row["count"]), str(row.get("player_id") or "")))
    return rows[:12]

"""A quién pagar cláusula y qué propios puede pagar un rival.

Solo recomienda. Pagar o subir una cláusula no se envía. Un jugador sin
cláusula, blindado o con el candado cerrado no entra. Si ``is_locked`` no
viene como falso, no se da por desbloqueado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from toolbox.analyzer import (
    ObjectiveWeights,
    candidate_from_player,
    candidates_from_squad,
    index_trends,
    own_squad,
    solve_lineup,
)
from toolbox.normalize import SCHEMA_VERSION

_MAX_SOLVES = 8


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _unlocked(player: dict[str, Any]) -> bool:
    if player.get("is_shielded") is True:
        return False
    lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
    return lock.get("is_locked") is False


def _raise_cost(current: int, target: int) -> int | None:
    """Relación 1:2 del reglamento: subir 2 € de cláusula cuesta 1 €, redondeando al alza."""
    if target <= current:
        return 0
    increase = target - current
    return (increase + 1) // 2


def build_clause_intel(
    squads: dict[str, Any] | None,
    trends: dict[str, Any] | None,
    optimize: dict[str, Any] | None,
    rivals: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    own = own_squad(squads) if isinstance(squads, dict) else None
    if not isinstance(own, dict):
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "command": "clause-intel",
            "error": {"code": "own_squad_missing", "message": "Sin plantilla propia no hay clausulazo."},
        }
    cash = _int(own.get("cash"))
    indexed = index_trends(trends)
    weights = ObjectiveWeights()
    roster = candidates_from_squad(own, indexed, weights=weights)
    owned = {candidate.player_id for candidate in roster if candidate.player_id}
    solved_now = optimize if isinstance(optimize, dict) and optimize.get("ok") is not False else None
    baseline = solved_now.get("expected_points") if isinstance(solved_now, dict) else None
    if not isinstance(baseline, (int, float)) or isinstance(baseline, bool):
        baseline = None
    xi_rows = solved_now.get("xi") if isinstance(solved_now, dict) and isinstance(solved_now.get("xi"), list) else []
    worst = _worst_objective(xi_rows)
    xi_ids = {
        row.get("player_id")
        for row in xi_rows
        if isinstance(row, dict) and isinstance(row.get("player_id"), str)
    }

    offers: list[dict[str, Any]] = []
    if isinstance(cash, int) and cash >= 0 and isinstance(squads, dict):
        offers = _pay_candidates(
            squads,
            indexed,
            roster=roster,
            owned=owned,
            cash=cash,
            baseline=float(baseline) if baseline is not None else None,
            worst=worst,
            weights=weights,
        )

    best_id = offers[0]["player_id"] if offers else None
    for row in offers:
        row["decision"] = "PAGAR" if row.get("player_id") == best_id and row.get("enters_xi") is True else "NO"
        if row["decision"] == "NO" and row.get("enters_xi") is not True:
            row["reason"] = row.get("reason") or "no_entra_en_el_xi"
        elif row["decision"] == "NO":
            row["reason"] = "hay_un_delta_mejor"

    protect = _protect_own(
        own,
        rivals or [],
        cash=cash,
        xi_ids=xi_ids,
        roster=roster,
    )
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "clause-intel",
        "fetched_at": current.astimezone(timezone.utc).isoformat(),
        "cash_eur": cash,
        "baseline_points": baseline,
        "offers": offers,
        "protect": protect,
        "sends": False,
    }


def _worst_objective(xi_rows: list[Any]) -> dict[str, float]:
    worst: dict[str, float] = {}
    for row in xi_rows:
        if not isinstance(row, dict):
            continue
        position = row.get("position") if isinstance(row.get("position"), str) else None
        objective = row.get("objective")
        if position is None or isinstance(objective, bool) or not isinstance(objective, (int, float)):
            continue
        current = worst.get(position)
        if current is None or float(objective) < current:
            worst[position] = float(objective)
    return worst


def _pay_candidates(
    squads: dict[str, Any],
    indexed: dict[str, dict[str, Any]],
    *,
    roster: list[Any],
    owned: set[str],
    cash: int,
    baseline: float | None,
    worst: dict[str, float],
    weights: ObjectiveWeights,
) -> list[dict[str, Any]]:
    pending: list[tuple[float, dict[str, Any], Any, str | None, str | None]] = []
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict) or squad.get("is_self") is True or squad.get("error"):
            continue
        manager = squad.get("manager_name") if isinstance(squad.get("manager_name"), str) else None
        team_id = squad.get("team_id") if isinstance(squad.get("team_id"), str) else None
        for player in squad.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else None
            if player_id is None or player_id in owned:
                continue
            clause = _int(player.get("buyout_clause"))
            if clause is None or not _unlocked(player):
                continue
            if cash - clause < 0:
                continue
            position = player.get("position") if isinstance(player.get("position"), str) else None
            trend = indexed.get(player_id)
            candidate = candidate_from_player(player, trend, weights=weights, ordinal=9000)
            if candidate is None or not candidate.eligible:
                continue
            floor = worst.get(position) if position else None
            if floor is not None and candidate.objective <= floor:
                continue
            gap = candidate.objective - (floor if floor is not None else 0.0)
            pending.append((gap, player, candidate, manager, team_id))
    pending.sort(key=lambda item: (-item[0], str(item[1].get("player_id") or "")))
    offers: list[dict[str, Any]] = []
    for _gap, player, candidate, manager, team_id in pending[:_MAX_SOLVES]:
        clause = _int(player.get("buyout_clause"))
        if clause is None:
            continue
        solved = solve_lineup([*roster, candidate], cash=cash - clause, weights=weights)
        xi = solved.get("xi") if isinstance(solved.get("xi"), list) else []
        enters = any(isinstance(row, dict) and row.get("player_id") == candidate.player_id for row in xi)
        points = solved.get("expected_points")
        delta = None
        if enters and baseline is not None and isinstance(points, (int, float)) and not isinstance(points, bool):
            delta = round(float(points) - baseline, 4)
        if not enters or delta is None or delta <= 0 or solved.get("matchday_void") is True:
            continue
        lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else None
        offers.append(
            {
                "decision": "NO",
                "player_id": candidate.player_id,
                "name": candidate.name,
                "nickname": candidate.nickname,
                "position": candidate.position,
                "club": candidate.club,
                "image_url": candidate.image_url,
                "team_id": team_id,
                "manager_name": manager,
                "buyout_clause_eur": clause,
                "cash_after_eur": cash - clause,
                "objective": round(float(candidate.objective), 4),
                "points_delta": delta,
                "enters_xi": True,
                "requires_confirmation": True,
                "reason": "entra_en_el_xi",
                "clause_lock": lock,
            }
        )
    offers.sort(key=lambda row: (-float(row.get("points_delta") or 0.0), row.get("buyout_clause_eur") or 0, str(row.get("player_id") or "")))
    return offers


def _protect_own(
    own: dict[str, Any],
    rivals: list[dict[str, Any]],
    *,
    cash: int | None,
    xi_ids: set[Any],
    roster: list[Any],
) -> list[dict[str, Any]]:
    by_position: dict[str, int] = {}
    eligible_count = 0
    for candidate in roster:
        if candidate.eligible:
            eligible_count += 1
            by_position[candidate.position] = by_position.get(candidate.position, 0) + 1
    rows: list[dict[str, Any]] = []
    for player in own.get("players") or []:
        if not isinstance(player, dict):
            continue
        clause = _int(player.get("buyout_clause"))
        player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else None
        if clause is None or player_id is None or player.get("is_shielded") is True:
            continue
        threats = []
        unknown_cash = False
        for rival in rivals:
            if not isinstance(rival, dict):
                continue
            rival_cash = rival.get("cash_eur")
            if not isinstance(rival_cash, int) or isinstance(rival_cash, bool):
                unknown_cash = True
                continue
            if rival_cash >= clause:
                threats.append(rival)
        if not threats:
            continue
        richest_rival = max(threats, key=lambda item: int(item.get("cash_eur") or 0))
        richest = int(richest_rival.get("cash_eur") or 0)
        options: list[dict[str, Any]] = []
        target = richest + 1
        cost = _raise_cost(clause, target)
        if isinstance(cost, int) and cost > 0 and isinstance(cash, int) and cash - cost >= 0:
            options.append(
                {
                    "kind": "subir_clausula",
                    "amount_eur": cost,
                    "target_clause_eur": clause + (2 * cost),
                    "cash_after_eur": cash - cost,
                    "requires_confirmation": True,
                    "eligible": True,
                }
            )
        elif isinstance(cost, int) and cost > 0:
            options.append(
                {
                    "kind": "subir_clausula",
                    "amount_eur": cost,
                    "target_clause_eur": clause + (2 * cost) if cost else clause,
                    "cash_after_eur": cash - cost if isinstance(cash, int) else None,
                    "requires_confirmation": True,
                    "eligible": False,
                    "reason": "caja_insuficiente",
                }
            )
        sell_ok, sell_reason = _can_sell(
            player,
            player_id=player_id,
            xi_ids=xi_ids,
            by_position=by_position,
            eligible_count=eligible_count,
        )
        options.append(
            {
                "kind": "vender",
                "amount_eur": None,
                "cash_after_eur": None,
                "requires_confirmation": True,
                "eligible": sell_ok,
                "reason": None if sell_ok else sell_reason,
            }
        )
        if player.get("shield_available") is True or own.get("shield_available") is True:
            options.append(
                {
                    "kind": "blindar",
                    "amount_eur": 0,
                    "cash_after_eur": cash,
                    "requires_confirmation": True,
                    "eligible": True,
                }
            )
        rows.append(
            {
                "player_id": player_id,
                "name": player.get("name"),
                "nickname": player.get("nickname"),
                "position": player.get("position"),
                "club": player.get("club"),
                "image_url": player.get("image_url") if isinstance(player.get("image_url"), str) else None,
                "buyout_clause_eur": clause,
                "threat_count": len(threats),
                "richest_cash_eur": richest,
                "top_rival": {
                    "team_id": richest_rival.get("team_id"),
                    "manager_name": richest_rival.get("manager_name"),
                    "cash_eur": richest_rival.get("cash_eur"),
                },
                "cash_unknown": unknown_cash,
                "clause_lock": player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else None,
                "options": options,
            }
        )
    rows.sort(key=lambda row: (-int(row.get("threat_count") or 0), str(row.get("player_id") or "")))
    return rows


def _can_sell(
    player: dict[str, Any],
    *,
    player_id: str,
    xi_ids: set[Any],
    by_position: dict[str, int],
    eligible_count: int,
) -> tuple[bool, str | None]:
    if eligible_count - 1 < 11:
        return False, "xi_bajaria_de_11"
    position = player.get("position") if isinstance(player.get("position"), str) else None
    if player_id in xi_ids and position and by_position.get(position, 0) <= 1:
        return False, "sin_recambio_en_el_xi"
    return True, None


def build_clause_intel_command(
    client: Any,
    *,
    league: str | None,
    fresh: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Plantillas, once y rivales → clausulazos a pagar y jugadores propios a proteger."""
    from toolbox.analyzer import optimize_from_documents, own_squad
    from toolbox.bidding import load_activity, needs_from_documents
    from toolbox.cache import ResponseCache
    from toolbox.jornada_plan import attach_clause_window
    from toolbox.scrapers import build_trends

    market = client.market_document(league, fresh=fresh)
    squads = client.squads_document(league, fresh=fresh)
    trends = build_trends(league=league, fresh=fresh, laliga=client, market=market, squads=squads)
    store = ResponseCache()
    current = now or datetime.now(timezone.utc)
    try:
        optimized = optimize_from_documents(squads, trends, cache=store, fresh=fresh, market=market)
        own = own_squad(squads)
        team_id = own.get("team_id") if isinstance(own, dict) else None
        if isinstance(team_id, str) and team_id and hasattr(client, "saved_lineup"):
            optimized["saved_lineup"] = client.saved_lineup(team_id, fresh=fresh)
        league_id = squads.get("league_id") if isinstance(squads.get("league_id"), str) else None
        activity = load_activity(client, league_id, fresh=fresh)
        needs = needs_from_documents(
            market,
            squads,
            trends,
            activity,
            now=current,
            cache=store,
            fresh=fresh,
        )
    finally:
        store.close()
    rivals = needs.get("rivals") if isinstance(needs, dict) and isinstance(needs.get("rivals"), list) else []
    document = build_clause_intel(squads, trends, optimized, rivals, now=current)
    if document.get("ok") is False:
        return document
    document["league_id"] = squads.get("league_id") if isinstance(squads, dict) else None
    document["league_name"] = squads.get("league_name") if isinstance(squads, dict) else None
    return attach_clause_window(document, trends=trends, squads=squads, now=current)

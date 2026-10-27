"""Rentabilidad de fichajes y perfiles de actividad por manager.

El coste de un jugador en plantilla sale del último movimiento de compra o
cláusula en el historial de la liga; una venta posterior lo elimina del mapa.
Sin evento conocido no se inventa un precio de adquisición.
"""

from __future__ import annotations

from typing import Any

_KIND_SPANISH = {
    "initial": "Presupuesto",
    "premium": "Prima",
    "buy": "Compra",
    "clause": "Cláusula",
    "sell": "Venta",
}

_ACQUISITION = {
    "buy": "mercado",
    "clause": "clausula",
}


def _team_key(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def ledger_index(ledgers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Índice por team_id del ledger (puede ser id de mánager si no hubo bind)."""
    indexed: dict[str, dict[str, Any]] = {}
    for row in ledgers:
        if not isinstance(row, dict):
            continue
        team_id = _team_key(row.get("team_id"))
        if team_id:
            indexed[team_id] = row
    return indexed


def ledger_for_squad(
    squad: dict[str, Any],
    indexed: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    team_id = _team_key(squad.get("team_id"))
    if team_id and team_id in indexed:
        return indexed[team_id]
    manager_id = _team_key(squad.get("manager_id"))
    if manager_id and manager_id in indexed:
        return indexed[manager_id]
    return None


def merge_ledgers(
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefiere el libro en memoria; si no trae eventos, usa el persistido."""
    by_team = ledger_index(primary)
    for row in fallback:
        if not isinstance(row, dict):
            continue
        team_id = row.get("team_id")
        if not isinstance(team_id, str) or not team_id:
            continue
        events = row.get("events") if isinstance(row.get("events"), list) else []
        current = by_team.get(team_id)
        current_events = current.get("events") if isinstance(current, dict) and isinstance(current.get("events"), list) else []
        if current is None or (not current_events and events):
            by_team[team_id] = row
    return list(by_team.values())


def player_name_index(squads: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for squad in squads:
        if not isinstance(squad, dict):
            continue
        for player in squad.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = player.get("player_id")
            if not isinstance(player_id, str) or not player_id:
                continue
            label = player.get("nickname") or player.get("name")
            names[player_id] = str(label) if isinstance(label, str) and label else player_id
    return names


def holdings_from_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Coste de adquisición vigente por jugador."""
    ordered = sorted(
        [event for event in events if isinstance(event, dict)],
        key=lambda item: (item.get("at") is None, item.get("at") or "", item.get("kind") or ""),
    )
    holdings: dict[str, dict[str, Any]] = {}
    for event in ordered:
        kind = event.get("kind")
        player_id = _team_key(event.get("player_id"))
        amount = event.get("amount_eur")
        if not player_id:
            continue
        if not isinstance(amount, int) or isinstance(amount, bool):
            continue
        if kind in {"buy", "clause"}:
            holdings[player_id] = {
                "cost_eur": amount,
                "acquired_at": event.get("at") if isinstance(event.get("at"), str) else None,
                "acquisition_kind": _ACQUISITION.get(str(kind), str(kind)),
            }
        elif kind == "sell":
            holdings.pop(player_id, None)
    return holdings


def _gain_row(
    player: dict[str, Any],
    holding: dict[str, Any] | None,
) -> dict[str, Any]:
    player_id = player.get("player_id")
    market_value = player.get("market_value")
    cost = holding.get("cost_eur") if isinstance(holding, dict) else None
    gain = None
    roi = None
    if isinstance(cost, int) and cost > 0 and isinstance(market_value, int):
        gain = market_value - cost
        roi = gain / cost
    row = dict(player)
    row["cost_eur"] = cost if isinstance(cost, int) else None
    row["gain_eur"] = gain
    row["roi"] = roi
    row["acquired_at"] = holding.get("acquired_at") if isinstance(holding, dict) else None
    row["acquisition_kind"] = holding.get("acquisition_kind") if isinstance(holding, dict) else None
    return row


def build_portfolio(
    players: list[dict[str, Any]],
    ledger: dict[str, Any] | None,
    names: dict[str, str] | None = None,
) -> dict[str, Any]:
    events = ledger.get("events") if isinstance(ledger, dict) and isinstance(ledger.get("events"), list) else []
    holdings = holdings_from_events(events)
    enriched = []
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = _team_key(player.get("player_id"))
        holding = holdings.get(player_id) if player_id else None
        enriched.append(_gain_row(player, holding))
    enriched.sort(
        key=lambda row: (
            row.get("gain_eur") is None,
            -(row["gain_eur"] if isinstance(row.get("gain_eur"), int) else 0),
            str(row.get("nickname") or row.get("name") or ""),
        )
    )
    cost_total = 0
    value_total = 0
    gain_total = 0
    priced = 0
    for row in enriched:
        cost = row.get("cost_eur")
        value = row.get("market_value")
        gain = row.get("gain_eur")
        if isinstance(cost, int):
            cost_total += cost
            priced += 1
        if isinstance(value, int):
            value_total += value
        if isinstance(gain, int):
            gain_total += gain
    roi_total = None if cost_total <= 0 else gain_total / cost_total
    return {
        "players": enriched,
        "summary": {
            "player_count": len(enriched),
            "priced_count": priced,
            "cost_eur": cost_total if priced else None,
            "market_value_eur": value_total if value_total > 0 else None,
            "gain_eur": gain_total if priced else None,
            "roi": roi_total,
        },
        "recent_events": recent_events(events, names, limit=16),
    }


def realized_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Plusvalía realizada: venta menos el coste de compra/cláusula vigente."""
    ordered = sorted(
        [event for event in events if isinstance(event, dict)],
        key=lambda item: (item.get("at") is None, item.get("at") or "", item.get("kind") or ""),
    )
    holdings: dict[str, int] = {}
    realized = 0
    priced = 0
    sales = 0
    for event in ordered:
        kind = event.get("kind")
        player_id = _team_key(event.get("player_id"))
        amount = event.get("amount_eur")
        if not player_id or not isinstance(amount, int) or isinstance(amount, bool):
            continue
        if kind in {"buy", "clause"}:
            holdings[player_id] = amount
        elif kind == "sell":
            sales += 1
            cost = holdings.pop(player_id, None)
            if isinstance(cost, int):
                realized += amount - cost
                priced += 1
    return {
        "realized_gain_eur": realized if priced else None,
        "priced_sales": priced,
        "sale_count": sales,
    }


def team_activity_profile(
    ledger: dict[str, Any] | None,
    names: dict[str, str] | None = None,
    *,
    limit: int = 14,
) -> dict[str, Any] | None:
    if not isinstance(ledger, dict):
        return None
    events = ledger.get("events") if isinstance(ledger.get("events"), list) else []
    purchases = ledger.get("purchases_eur") if isinstance(ledger.get("purchases_eur"), int) else 0
    clauses = ledger.get("clauses_eur") if isinstance(ledger.get("clauses_eur"), int) else 0
    sales = ledger.get("sales_eur") if isinstance(ledger.get("sales_eur"), int) else 0
    premiums = ledger.get("premiums_eur") if isinstance(ledger.get("premiums_eur"), int) else 0
    realized = realized_from_events(events)
    return {
        "initial_budget_eur": ledger.get("initial_budget_eur") if isinstance(ledger.get("initial_budget_eur"), int) else None,
        "premiums_eur": premiums,
        "purchases_eur": purchases,
        "clauses_eur": clauses,
        "sales_eur": sales,
        "net_outflow_eur": purchases + clauses - sales,
        "realized_gain_eur": realized["realized_gain_eur"],
        "priced_sales": realized["priced_sales"],
        "sale_count": realized["sale_count"],
        "event_count": len(events),
        "recent_events": recent_events(events, names, limit=limit),
    }


def recent_events(
    events: list[dict[str, Any]],
    names: dict[str, str] | None = None,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ordered = sorted(
        [event for event in events if isinstance(event, dict)],
        key=lambda item: (item.get("at") is None, item.get("at") or ""),
        reverse=True,
    )
    rows: list[dict[str, Any]] = []
    for event in ordered[:limit]:
        kind = str(event.get("kind") or "")
        player_id = event.get("player_id")
        amount = event.get("amount_eur")
        signed = event.get("signed_eur")
        if not isinstance(amount, int):
            continue
        label = _KIND_SPANISH.get(kind, kind)
        player_label = None
        if isinstance(player_id, str) and player_id:
            player_label = (names or {}).get(player_id, player_id)
        rows.append(
            {
                "kind": kind,
                "label": label,
                "amount_eur": amount,
                "signed_eur": signed if isinstance(signed, int) else None,
                "player_id": player_id if isinstance(player_id, str) else None,
                "player_name": player_label,
                "at": event.get("at") if isinstance(event.get("at"), str) else None,
            }
        )
    return rows


def league_activity_feed(
    ledgers: list[dict[str, Any]],
    squads: list[dict[str, Any]],
    names: dict[str, str] | None = None,
    *,
    limit: int = 24,
) -> list[dict[str, Any]]:
    manager_by_team = {
        str(squad.get("team_id")): squad.get("manager_name") or squad.get("fantasy_team_name")
        for squad in squads
        if isinstance(squad, dict) and isinstance(squad.get("team_id"), str)
    }
    merged: list[dict[str, Any]] = []
    for ledger in ledgers:
        if not isinstance(ledger, dict):
            continue
        team_id = ledger.get("team_id")
        if not isinstance(team_id, str):
            continue
        events = ledger.get("events") if isinstance(ledger.get("events"), list) else []
        for row in recent_events(events, names, limit=limit):
            merged.append(
                {
                    **row,
                    "team_id": team_id,
                    "manager_name": manager_by_team.get(team_id),
                }
            )
    merged.sort(key=lambda item: (item.get("at") is None, item.get("at") or ""), reverse=True)
    return merged[:limit]

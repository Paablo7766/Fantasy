"""Rentabilidad de fichajes y perfiles de actividad por manager.

El coste de un jugador en plantilla sale del último movimiento de compra o
cláusula en el historial de la liga; una venta posterior lo elimina del mapa.
Sin evento conocido no se inventa un precio de adquisición.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
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
    rounds_by_player: dict[str, dict[int, float]] | None = None,
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
    attach_points(enriched, catalog_rounds() if rounds_by_player is None else rounds_by_player)
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


def squad_value_history(
    players: list[dict[str, Any]],
    history: dict[str, list[dict[str, Any]]] | None,
    *,
    min_coverage: float = 0.6,
) -> list[dict[str, Any]]:
    """Valor diario de la plantilla actual a partir de las fotos de precio.

    Suma, día a día, el valor de mercado de los jugadores que tienes hoy. Si a un
    jugador le falta la foto de un día se arrastra la última conocida; si aún no
    tiene ninguna, ese día no lo cubre. Solo se publican los días en que la parte
    cubierta llega a ``min_coverage``: una suma con media plantilla no es tu valor.
    """
    ids: list[str] = []
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = _team_key(player.get("player_id"))
        if player_id and player_id not in ids:
            ids.append(player_id)
    if not ids or not isinstance(history, dict):
        return []
    by_player: dict[str, dict[str, int]] = {}
    days: set[str] = set()
    for player_id in ids:
        rows = history.get(player_id) or []
        values: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = row.get("day")
            value = row.get("market_value")
            if isinstance(day, str) and day and isinstance(value, int) and not isinstance(value, bool):
                values[day] = value
        if values:
            by_player[player_id] = values
            days.update(values)
    last: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for day in sorted(days):
        total = 0
        covered = 0
        for player_id in ids:
            value = by_player.get(player_id, {}).get(day)
            if value is not None:
                last[player_id] = value
            known = last.get(player_id)
            if known is None:
                continue
            total += known
            covered += 1
        coverage = covered / len(ids)
        if covered and coverage >= min_coverage:
            out.append({"day": day, "value_eur": total, "coverage": round(coverage, 3)})
    return out


# ---------------------------------------------------------------------------
# Amortización: puntos desde que el jugador es tuyo y lo que valen en caja.
# ---------------------------------------------------------------------------

#: Una jornada por semana: la API no fecha las jornadas, solo las numera.
_ROUND_DAYS = 7


def _parse_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def round_points(*sources: Any) -> dict[int, float]:
    """Une varios mapas jornada → puntos. El primero que trae la jornada manda."""
    merged: dict[int, float] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            try:
                week = int(key)
            except (TypeError, ValueError):
                continue
            if week in merged or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            merged[week] = float(value)
    return merged


def current_round(maps: list[dict[int, float]]) -> int | None:
    weeks = [week for mapping in maps for week in mapping]
    return max(weeks) if weeks else None


def round_start(round_number: int, latest_round: int, now: datetime) -> datetime:
    """Inicio aproximado de una jornada: viernes de su fin de semana.

    La última jornada con puntos es la de este fin de semana si hoy es de
    viernes a domingo, o la del anterior si no. Las demás se cuentan hacia
    atrás de semana en semana.
    """
    local = now.astimezone(timezone.utc)
    back = (local.weekday() - 4) % 7  # días desde el último viernes
    friday = (local - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
    return friday - timedelta(days=_ROUND_DAYS * (latest_round - round_number))


def points_while_owned(
    rounds: dict[int, float],
    acquired_at: str | None,
    latest_round: int | None,
    now: datetime,
) -> dict[str, Any]:
    """Puntos de la temporada y los sumados desde la compra (estimados por fecha)."""
    total = round(sum(rounds.values()), 1) if rounds else None
    acquired = _parse_at(acquired_at)
    if not rounds or latest_round is None:
        return {"points_total": total, "points_owned": None, "rounds_owned": None, "points_owned_estimated": False}
    if acquired is None:
        # Sin compra conocida es de la plantilla inicial: todos sus puntos son tuyos.
        owned = list(rounds.items())
        estimated = False
    else:
        owned = [(week, pts) for week, pts in rounds.items() if round_start(week, latest_round, now) >= acquired]
        estimated = True
    rounds_owned = len(owned) if acquired is None else sum(
        1 for week in range(1, latest_round + 1) if round_start(week, latest_round, now) >= acquired
    )
    return {
        "points_total": total,
        "points_owned": round(sum(pts for _, pts in owned), 1),
        "rounds_owned": rounds_owned,
        "points_owned_estimated": estimated,
    }


_CATALOG_TTL_S = 120.0
_catalog_memo: dict[str, Any] = {"at": 0.0, "rounds": {}}


def catalog_rounds() -> dict[str, dict[int, float]]:
    """Jornada → puntos de toda la temporada por jugador, del catálogo en disco.

    Nunca sale a red. Se memoriza un par de minutos: la cartera se monta para
    cada plantilla de la liga y el catálogo no cambia entre una y otra.
    """
    now = time.monotonic()
    if now - float(_catalog_memo["at"]) < _CATALOG_TTL_S:
        return _catalog_memo["rounds"]
    rounds: dict[str, dict[int, float]] = {}
    try:
        from toolbox.normalize import normalize_catalog
        from toolbox.quant_valuation import cached_catalog

        for row in normalize_catalog(cached_catalog()):
            player_id = _team_key(row.get("player_id"))
            if player_id:
                rounds[player_id] = round_points(row.get("week_points_by_round"))
    except Exception:  # noqa: BLE001 — sin catálogo no hay puntos, la cartera sigue
        rounds = {}
    _catalog_memo.update(at=now, rounds=rounds)
    return rounds


def attach_points(
    players: list[dict[str, Any]],
    rounds_by_player: dict[str, dict[int, float]],
    now: datetime | None = None,
) -> None:
    """Añade a cada jugador sus puntos de temporada y los sumados desde la compra."""
    moment = now or datetime.now(timezone.utc)
    latest = current_round(list(rounds_by_player.values()))
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = _team_key(player.get("player_id"))
        rounds = rounds_by_player.get(player_id or "", {})
        player.update(points_while_owned(rounds, player.get("acquired_at"), latest, moment))


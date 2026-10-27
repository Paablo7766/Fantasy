"""Caja, pujas de último segundo y riesgo de rivales.

La caja reconstruida es presupuesto inicial + primas - compras + ventas.
Si el historial no trae el presupuesto inicial, la cifra reconstruida queda
en null. El saldo observado de la plantilla no se usa para rellenar ese hueco.

Una puja que pueda dejar la caja en negativo no es elegible. El clausulazo
contra un rival se agenda con la hora y el minuto de la API; si la marca no
viene, no se inventa.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from toolbox.analyzer import (
    POSITIONS,
    CatalogClient,
    ObjectiveWeights,
    candidates_from_squad,
    index_trends,
    objective_value,
    official_price_delta,
    optimize_from_documents,
    own_squad,
    relevo_bonus,
    trend_usable,
    unavailable_reason,
)
from toolbox.analyzer import (
    expected_opta_points as _expected_opta_points,
)
from toolbox.analyzer import (
    probability as _probability,
)
from toolbox.cache import CashLedgerStore, ResponseCache
from toolbox.normalize import SCHEMA_VERSION, display_zone

SNIPE_LEAD_SECONDS = 8
DIRECT_RIVAL_RANK_WINDOW = 3
MIN_HEADCOUNT = {"POR": 1, "DEF": 3, "MC": 3, "DEL": 1}
LEDGER_TTL_SECONDS = 300.0
_WEIGHTS = ObjectiveWeights()
_MONEY_KEYS = (
    "reserva_caja_eur",
    "puja_silenciosa_max_eur",
    "puja_silenciosa_max_pct_caja",
    "suelo_venta_eur",
)
_KINDS = {
    "initial": "initial",
    "budget": "initial",
    "presupuesto": "initial",
    "presupuestoinicial": "initial",
    "premium": "premium",
    "prima": "premium",
    "prize": "premium",
    "reward": "premium",
    "buy": "buy",
    "purchase": "buy",
    "compra": "buy",
    "bid": "buy",
    "puja": "buy",
    "clause": "clause",
    "buyout": "clause",
    "clausula": "clause",
    "clausulazo": "clause",
    "sell": "sell",
    "sale": "sell",
    "venta": "sell",
}
_KIND_FIELDS = ("type", "kind", "operation", "event", "action", "newsType", "transactionType")
_AMOUNT_FIELDS = ("money", "amount", "value", "price", "cash", "cost")
_TIME_FIELDS = ("createdAt", "date", "at", "timestamp", "time", "publishedAt")
_TEAM_FIELDS = ("teamId", "team_id", "fantasyTeamId")
_PLAYER_FIELDS = ("playerId", "player_id")


class ActivityClient(CatalogClient, Protocol):
    def activity_payload(self, league_id: str, *, fresh: bool) -> dict[str, Any]: ...


def load_activity(client: ActivityClient, league_id: str | None, *, fresh: bool) -> dict[str, Any]:
    """Historial de la liga. Si el endpoint no existe, el libro queda abierto."""
    if not isinstance(league_id, str) or not league_id:
        return {"ok": False, "events": [], "source_url": None, "error": "league_missing", "attempts": []}
    fetched = client.activity_payload(league_id, fresh=fresh)
    if not fetched.get("ok"):
        return {
            "ok": False,
            "events": [],
            "source_url": None,
            "error": fetched.get("error") or "endpoint_not_found",
            "attempts": fetched.get("attempts") or [],
        }
    return {
        "ok": True,
        "events": parse_events(fetched.get("payload")),
        "source_url": fetched.get("source_url"),
        "error": None,
        "attempts": [],
    }


def parse_events(payload: Any) -> list[dict[str, Any]]:
    rows = _event_rows(payload)
    events: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_event(row)
        if parsed is not None:
            events.append(parsed)
    events.sort(key=lambda item: (item["at"] is None, item["at"] or "", item["team_id"], item["kind"]))
    return events


def reconstruct_ledgers(
    squads: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Presupuesto inicial + primas - compras - cláusulas + ventas."""
    by_team: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_team.setdefault(str(event["team_id"]), []).append(event)
    known = {str(squad.get("team_id")) for squad in squads if isinstance(squad.get("team_id"), str)}
    team_ids = list(dict.fromkeys([*known, *by_team.keys()]))
    squad_by_id = {str(squad.get("team_id")): squad for squad in squads if isinstance(squad.get("team_id"), str)}
    ledgers: list[dict[str, Any]] = []
    for team_id in team_ids:
        if not team_id:
            continue
        ledgers.append(_ledger(team_id, by_team.get(team_id, []), squad_by_id.get(team_id)))
    return ledgers


def schedule_snipe(
    listing: dict[str, Any],
    *,
    cash: int | None,
    lineup_void: bool,
    own_team_id: str | None,
    now: datetime,
    unavailable: str | None = None,
    lead_seconds: int = SNIPE_LEAD_SECONDS,
) -> dict[str, Any]:
    """La puja no se publica hasta ``lead_seconds`` antes del cierre."""
    amount = bid_amount(listing)
    expires = _parse_iso(listing.get("listing_expires_at"))
    seller = listing.get("seller_team_id")
    own_listing = isinstance(own_team_id, str) and seller == own_team_id
    purchase = assess_purchase(cash=cash, cost=amount, lineup_void=lineup_void)
    fire = expires - timedelta(seconds=lead_seconds) if expires is not None else None
    clock = _clock(fire) if fire is not None else None
    close = _clock(expires) if expires is not None else None
    if expires is None or fire is None:
        status = "unschedulable"
    elif now >= expires:
        status = "window_passed"
    elif now >= fire:
        status = "inside_window"
    else:
        status = "hidden"
    reasons = list(purchase["reasons"])
    if own_listing:
        reasons.append("listing_propio")
    if unavailable:
        reasons.append(unavailable)
    if status == "unschedulable":
        reasons.append("sin_cierre")
    if status == "window_passed":
        reasons.append("mercado_cerrado")
    eligible = purchase["eligible"] and not own_listing and unavailable is None and status in {"hidden", "inside_window"}
    return {
        "market_id": listing.get("market_id") if isinstance(listing.get("market_id"), str) else None,
        "player_id": listing.get("player_id") if isinstance(listing.get("player_id"), str) else None,
        "name": listing.get("name") if isinstance(listing.get("name"), str) else None,
        "nickname": listing.get("nickname") if isinstance(listing.get("nickname"), str) else None,
        "position": listing.get("position") if isinstance(listing.get("position"), str) else None,
        "bid_eur": amount,
        "cash_after_eur": purchase["cash_after_eur"],
        "listing_expires_at": close["at"] if close else None,
        "listing_expires_local_date": close["local_date"] if close else None,
        "listing_expires_local_time": close["local_time"] if close else listing.get("listing_expires_local_time"),
        "listing_expires_local_clock": close["local_clock"] if close else None,
        "fire_at": clock["at"] if clock else None,
        "fire_local_date": clock["local_date"] if clock else None,
        "fire_local_time": clock["local_time"] if clock else None,
        "fire_local_clock": clock["local_clock"] if clock else None,
        "lead_seconds": lead_seconds,
        "status": status,
        "interest_hidden": status == "hidden",
        "xi_remains_valid": not lineup_void and purchase["cash_after_eur"] is not None and purchase["cash_after_eur"] >= 0,
        "eligible": eligible,
        "reasons": reasons,
    }


def bid_amount(listing: dict[str, Any]) -> int | None:
    """Un euro por encima de la puja líder, o el precio de venta si no hay puja."""
    leading = listing.get("leading_bid")
    sale = listing.get("sale_price")
    if isinstance(leading, int) and not isinstance(leading, bool):
        return leading + 1
    if isinstance(sale, int) and not isinstance(sale, bool):
        return sale
    return None


def assess_purchase(*, cash: int | None, cost: int | None, lineup_void: bool) -> dict[str, Any]:
    reasons: list[str] = []
    if not isinstance(cost, int):
        reasons.append("precio_desconocido")
    if not isinstance(cash, int):
        reasons.append("caja_desconocida")
    if lineup_void:
        reasons.append("xi_invalido")
    after = cash - cost if isinstance(cash, int) and isinstance(cost, int) else None
    if isinstance(after, int) and after < 0:
        reasons.append("negative_cash")
    eligible = isinstance(after, int) and after >= 0 and not lineup_void and isinstance(cost, int)
    return {"eligible": eligible, "cash_after_eur": after, "reasons": reasons}


def sabotage_alerts(
    squads: dict[str, Any],
    market: dict[str, Any],
    trends: dict[str, Any] | None,
    ledgers: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rival directo al mínimo de una posición, sin recambio o sin liquidez."""
    own = own_squad(squads)
    if own is None:
        return []
    current = now or datetime.now(timezone.utc)
    indexed = index_trends(trends)
    listings = market.get("listings") if isinstance(market.get("listings"), list) else []
    ledger_by_team = {str(item["team_id"]): item for item in ledgers}
    rivals = []
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict) or squad.get("is_self") is True or squad.get("error"):
            continue
        rivals.append(
            _rival_risk(
                squad,
                own=own,
                listings=listings,
                trends=indexed,
                ledger=ledger_by_team.get(str(squad.get("team_id"))),
                now=current,
            )
        )
    return rivals


def flip_from_documents(
    market: dict[str, Any],
    squads: dict[str, Any],
    trends: dict[str, Any] | None,
    *,
    lineup: dict[str, Any] | None = None,
    now: datetime | None = None,
    cache: ResponseCache | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    own = own_squad(squads)
    if own is None:
        return _failure("flip", "own_squad_missing", "Sin plantilla propia no se calcula la caja de una puja.", squads.get("league_id"))
    solved = lineup if lineup is not None else optimize_from_documents(squads, trends, cache=cache, fresh=fresh)
    if solved.get("ok") is False:
        return solved
    current = now or datetime.now(timezone.utc)
    cash = own.get("cash") if isinstance(own.get("cash"), int) else None
    void = bool(solved.get("matchday_void"))
    indexed = index_trends(trends)
    owned = {
        player.get("player_id")
        for player in own.get("players") or []
        if isinstance(player, dict) and isinstance(player.get("player_id"), str)
    }
    listings = [row for row in market.get("listings") or [] if isinstance(row, dict)]
    by_player = {}
    for listing in listings:
        player_id = listing.get("player_id")
        if isinstance(player_id, str):
            by_player[player_id] = listing
    signings: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    players = trends.get("players") if isinstance(trends, dict) and isinstance(trends.get("players"), list) else []
    seen: set[str] = set()
    for trend in players:
        if not isinstance(trend, dict):
            continue
        player_id = trend.get("player_id")
        if not isinstance(player_id, str) or player_id in seen:
            continue
        listing = by_player.get(player_id)
        if listing is None:
            continue
        seen.add(player_id)
        decision = _signing(
            trend,
            listing,
            cash=cash,
            lineup_void=void,
            own_team_id=own.get("team_id") if isinstance(own.get("team_id"), str) else None,
            owned=player_id in owned,
            now=current,
        )
        if decision["eligible"]:
            signings.append(decision)
        else:
            rejected.append(decision)
    signings.sort(key=lambda item: (-int(item["acceleration"] or 0), item["player_id"] or ""))
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "flip",
        "league_id": squads.get("league_id") or market.get("league_id"),
        "team_id": own.get("team_id"),
        "cash_eur": cash,
        "matchday_void": void,
        "from_cache": False,
        "count": len(signings),
        "signings": signings,
        "rejected": rejected,
        "bid_run": [item["snipe"] for item in signings if item.get("snipe") and item["snipe"].get("eligible")],
    }


def needs_from_documents(
    market: dict[str, Any],
    squads: dict[str, Any],
    trends: dict[str, Any] | None,
    activity: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    cache: ResponseCache | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    events = activity.get("events") if isinstance(activity, dict) and isinstance(activity.get("events"), list) else []
    roster = squads.get("squads") if isinstance(squads.get("squads"), list) else []
    snapshots = _snapshot_index(cache)
    fingerprint = {
        "events": events,
        "cash": [
            {"team_id": squad.get("team_id"), "cash": squad.get("cash"), "manager_id": squad.get("manager_id")}
            for squad in roster
            if isinstance(squad, dict)
        ],
        "snapshots": sorted((player_id, day, value) for (player_id, day), value in snapshots.items()),
    }

    def build_books() -> dict[str, Any]:
        from toolbox.league_history import books_from_activity

        ledgers, history = books_from_activity(
            [squad for squad in roster if isinstance(squad, dict)],
            [event for event in events if isinstance(event, dict)],
            snapshots,
        )
        return {"ledgers": ledgers, "history": history}

    books = _cached_value("ledgers", fingerprint, build_books, cache=cache, fresh=fresh)
    ledgers = books["ledgers"] if isinstance(books, dict) else []
    history = books["history"] if isinstance(books, dict) and isinstance(books.get("history"), dict) else {}
    league_id = squads.get("league_id") if isinstance(squads.get("league_id"), str) else None
    if cache is not None and league_id:
        CashLedgerStore(root=cache.root, client=cache.client).replace_league(league_id, ledgers)
    rivals = sabotage_alerts(squads, market, trends, ledgers, now=now)
    scheduled = [
        alert
        for rival in rivals
        for alert in rival["clause_alerts"]
        if alert.get("scheduled") is True
    ]
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "needs",
        "league_id": squads.get("league_id"),
        "from_cache": False,
        "activity": {
            "ok": bool(activity.get("ok")) if isinstance(activity, dict) else False,
            "source_url": activity.get("source_url") if isinstance(activity, dict) else None,
            "error": activity.get("error") if isinstance(activity, dict) else "missing",
            "event_count": len(events),
        },
        "ledger_note": (
            "Caja reconstruida = presupuesto inicial + primas - compras - cláusulas + ventas. "
            "Si el historial no trae el presupuesto, se infiere del residual de tu caja y se aplica a todos. "
            "En un rival esa cifra es un techo: subir la cláusula no sale en el historial."
            if history.get("initial_source") == "caja_propia"
            else "Caja reconstruida = presupuesto inicial + primas - compras - cláusulas + ventas. "
            "Sin presupuesto inicial en el historial, reconstructed_cash_eur es null."
        ),
        "history": history,
        "ledgers": ledgers,
        "rival_count": len(rivals),
        "rivals": rivals,
        "clause_alerts": scheduled,
    }


def build_flip_command(
    client: ActivityClient,
    *,
    league: str | None,
    fresh: bool,
    trends_document: dict[str, Any] | None = None,
    cache: ResponseCache | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    market, squads, trends, store, owns = _bundle(client, league=league, fresh=fresh, trends_document=trends_document, cache=cache)
    try:
        lineup = optimize_from_documents(squads, trends, cache=store, fresh=fresh)
        return flip_from_documents(market, squads, trends, lineup=lineup, now=now, cache=store, fresh=fresh)
    finally:
        if owns:
            store.close()


def build_needs_command(
    client: ActivityClient,
    *,
    league: str | None,
    fresh: bool,
    trends_document: dict[str, Any] | None = None,
    cache: ResponseCache | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    market, squads, trends, store, owns = _bundle(client, league=league, fresh=fresh, trends_document=trends_document, cache=cache)
    try:
        activity = load_activity(client, squads.get("league_id") if isinstance(squads.get("league_id"), str) else None, fresh=fresh)
        return needs_from_documents(market, squads, trends, activity, now=now, cache=store, fresh=fresh)
    finally:
        if owns:
            store.close()


def read_governance(text: str, *, execute: bool) -> dict[str, Any]:
    thresholds = {key: _field(text, key) for key in (*_MONEY_KEYS, "clausula_max_sin_preguntar_eur")}
    silent_numbers = all(_integer_token(thresholds[key]) for key in _MONEY_KEYS)
    clause_blocked = thresholds.get("clausula_max_sin_preguntar_eur") == "0"
    reasons: list[str] = []
    if not silent_numbers:
        reasons.append("Los umbrales de puja silenciosa no son enteros. El gasto queda bloqueado.")
    if not clause_blocked:
        reasons.append("Pagar o subir una cláusula no entra en el silencio.")
    orders: list[dict[str, Any]] = []
    if execute:
        orders.append(
            {
                "operation": "alineacion",
                "status": "not_sent",
                "reason": "El once no mueve caja. Esta fase no escribe la alineación en la API.",
            }
        )
        orders.append(
            {
                "operation": "puja",
                "status": "blocked" if not silent_numbers else "not_sent",
                "reason": reasons[0] if not silent_numbers else "La puja de último segundo queda planificada, no enviada.",
            }
        )
        orders.append(
            {
                "operation": "clausula",
                "status": "blocked",
                "reason": "Un clausulazo exige un sí en Telegram. No se envía.",
            }
        )
    return {
        "execute_requested": execute,
        "silent_money_enabled": silent_numbers,
        "clause_requires_telegram": True,
        "thresholds": thresholds,
        "reasons": reasons,
        "orders": orders,
    }


def build_agent_command(
    client: ActivityClient,
    *,
    league: str | None,
    fresh: bool,
    execute: bool,
    trends_document: dict[str, Any] | None = None,
    cache: ResponseCache | None = None,
    now: datetime | None = None,
    governance_text: str | None = None,
) -> dict[str, Any]:
    """Plan del ciclo. ``--execute`` no mueve dinero: los umbrales abiertos lo impiden."""
    market, squads, trends, store, owns = _bundle(client, league=league, fresh=fresh, trends_document=trends_document, cache=cache)
    current = now or datetime.now(timezone.utc)
    try:
        activity = load_activity(client, squads.get("league_id") if isinstance(squads.get("league_id"), str) else None, fresh=fresh)
        optimized = optimize_from_documents(squads, trends, cache=store, fresh=fresh)
        flipped = (
            flip_from_documents(market, squads, trends, lineup=optimized, now=current, cache=store, fresh=fresh)
            if optimized.get("ok")
            else _failure("flip", "own_squad_missing", "Sin plantilla propia no hay lista de fichajes.", squads.get("league_id"))
        )
        needs = needs_from_documents(market, squads, trends, activity, now=current, cache=store, fresh=fresh)
        text = governance_text if governance_text is not None else _read_user_file()
        governance = read_governance(text, execute=execute)
        document = {
            "ok": bool(optimized.get("ok")),
            "schema_version": SCHEMA_VERSION,
            "command": "agent",
            "league_id": squads.get("league_id"),
            "fetched_at": _iso(current),
            "execute_requested": execute,
            "from_cache": False,
            "governance": governance,
            "optimize": optimized,
            "flip": flipped,
            "needs": needs,
            "memory_entry": _memory_entry(
                league_id=squads.get("league_id"),
                optimized=optimized,
                flipped=flipped,
                needs=needs,
                governance=governance,
                now=current,
            ),
        }
        if not document["ok"]:
            document["error"] = optimized.get("error")
        return document
    finally:
        if owns:
            store.close()


def _signing(
    trend: dict[str, Any],
    listing: dict[str, Any],
    *,
    cash: int | None,
    lineup_void: bool,
    own_team_id: str | None,
    owned: bool,
    now: datetime,
) -> dict[str, Any]:
    player_id = trend.get("player_id") if isinstance(trend.get("player_id"), str) else None
    reasons: list[str] = []
    if owned:
        reasons.append("ya_en_plantilla")
    speculative, why = _speculative(trend)
    if why:
        reasons.append(why)
    blocked = unavailable_reason(listing, trend if trend_usable(trend) else None)
    if blocked:
        reasons.append(blocked)
    amount = bid_amount(listing)
    purchase = assess_purchase(cash=cash, cost=amount, lineup_void=lineup_void)
    reasons.extend(reason for reason in purchase["reasons"] if reason not in reasons)
    usable = trend_usable(trend)
    opta, components = _expected_opta_points(
        listing.get("position") if isinstance(listing.get("position"), str) else "",
        trend.get("form") if usable and isinstance(trend.get("form"), dict) else None,
    )
    bonus = relevo_bonus(trend.get("relevo_bonus")) if usable else None
    p_titular = _probability(trend.get("p_titular")) if usable else None
    points = round(opta + (float(bonus) if bonus is not None else 0.0), 4)
    snipe = schedule_snipe(
        listing,
        cash=cash,
        lineup_void=lineup_void,
        own_team_id=own_team_id,
        now=now,
        unavailable=blocked,
    )
    eligible = purchase["eligible"] and speculative and not owned and blocked is None
    if snipe["status"] == "window_passed":
        eligible = False
        if "mercado_cerrado" not in reasons:
            reasons.append("mercado_cerrado")
    acceleration = trend.get("acceleration") if isinstance(trend.get("acceleration"), int) and not isinstance(trend.get("acceleration"), bool) else None
    listing_change = (
        listing.get("market_value_change")
        if isinstance(listing.get("market_value_change"), int)
        and not isinstance(listing.get("market_value_change"), bool)
        else None
    )
    listing_value = listing.get("market_value") if isinstance(listing.get("market_value"), int) else None
    listing_sale = listing.get("sale_price") if isinstance(listing.get("sale_price"), int) else None
    day_delta = official_price_delta(trend)
    if day_delta is None:
        day_delta = official_price_delta(
            {
                "market_value_change": listing_change if listing_change is not None else trend.get("market_value_change"),
                "price_delta": trend.get("price_delta"),
                "market_value": trend.get("fantasy_price")
                if isinstance(trend.get("fantasy_price"), int)
                else listing_value if listing_value is not None else trend.get("market_value"),
                "fantasy_price": trend.get("fantasy_price"),
                "sale_price": listing_sale if listing_sale is not None else trend.get("sale_price"),
            }
        )
    return {
        "player_id": player_id,
        "name": trend.get("name") if isinstance(trend.get("name"), str) else listing.get("name"),
        "nickname": trend.get("nickname") if isinstance(trend.get("nickname"), str) else listing.get("nickname"),
        "position": listing.get("position") if isinstance(listing.get("position"), str) else trend.get("position"),
        "action": "bid",
        "acceleration": acceleration,
        "price_delta": day_delta,
        "matching_confidence": trend.get("matching_confidence") if isinstance(trend.get("matching_confidence"), (int, float)) else None,
        "p_titular": p_titular,
        "expected_points": points,
        "objective": objective_value(
            p_titular=p_titular,
            expected_points=opta,
            relevo=bonus,
            weights=_WEIGHTS,
        ),
        "components": components,
        "relevo_bonus": bonus,
        "bid_eur": amount,
        "af_ideal_bid": trend.get("af_ideal_bid") if isinstance(trend.get("af_ideal_bid"), int) else None,
        "af_max_bid": trend.get("af_max_bid") if isinstance(trend.get("af_max_bid"), int) else None,
        "af_market_signal": trend.get("af_market_signal") if isinstance(trend.get("af_market_signal"), str) else None,
        "af_signal_strength": trend.get("af_signal_strength")
        if isinstance(trend.get("af_signal_strength"), (int, float))
        else None,
        "af_expected_points": trend.get("af_expected_points")
        if isinstance(trend.get("af_expected_points"), (int, float))
        else None,
        "own_ideal_bid": trend.get("own_ideal_bid") if isinstance(trend.get("own_ideal_bid"), int) else None,
        "own_max_bid": trend.get("own_max_bid") if isinstance(trend.get("own_max_bid"), int) else None,
        "own_market_signal": trend.get("own_market_signal")
        if isinstance(trend.get("own_market_signal"), str)
        else None,
        "own_expected_points": trend.get("own_expected_points")
        if isinstance(trend.get("own_expected_points"), (int, float))
        else None,
        "cash_after_eur": purchase["cash_after_eur"],
        "xi_remains_valid": not lineup_void and isinstance(purchase["cash_after_eur"], int) and purchase["cash_after_eur"] >= 0,
        "eligible": eligible,
        "reasons": reasons,
        "snipe": snipe,
    }


def _speculative(trend: dict[str, Any]) -> tuple[bool, str | None]:
    if not trend_usable(trend):
        return False, "matching_confidence"
    acceleration = trend.get("acceleration")
    rising = isinstance(acceleration, int) and not isinstance(acceleration, bool) and acceleration > 0
    own_up = trend.get("own_market_signal") == "up"
    af_up = trend.get("af_market_signal") == "up"
    if rising or own_up or af_up or trend.get("flip_candidate") is True:
        return True, None
    return False, "sin_aceleracion"


def _rival_risk(
    squad: dict[str, Any],
    *,
    own: dict[str, Any],
    listings: list[dict[str, Any]],
    trends: dict[str, dict[str, Any]],
    ledger: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    roster = candidates_from_squad(squad, trends)
    available = {position: 0 for position in POSITIONS}
    for candidate in roster:
        if candidate.eligible and candidate.position in available:
            available[candidate.position] += 1
    observed = squad.get("cash") if isinstance(squad.get("cash"), int) else None
    reconstructed = (
        ledger.get("reconstructed_cash_eur")
        if isinstance(ledger, dict) and isinstance(ledger.get("reconstructed_cash_eur"), int)
        else None
    )
    cash = observed if observed is not None else reconstructed
    direct = _direct(own.get("rank"), squad.get("rank"))
    thin = [position for position in POSITIONS if available[position] <= MIN_HEADCOUNT[position]]
    alerts: list[dict[str, Any]] = []
    if direct is True:
        for position in thin:
            alerts.extend(
                _clause_alerts(
                    squad,
                    position=position,
                    available=available[position],
                    cash=cash,
                    listings=listings,
                    trends=trends,
                    own_cash=own.get("cash") if isinstance(own.get("cash"), int) else None,
                    now=now,
                )
            )
    lacks_liquidity = _lacks_liquidity(cash, thin, listings)
    return {
        "team_id": squad.get("team_id"),
        "manager_name": squad.get("manager_name"),
        "fantasy_team_name": squad.get("fantasy_team_name"),
        "rank": squad.get("rank") if isinstance(squad.get("rank"), int) else None,
        "direct": direct,
        "cash_eur": cash,
        "cash_is_ceiling": bool(observed is None and isinstance(ledger, dict) and ledger.get("cash_is_ceiling") is True),
        "ledger": ledger,
        "depth": available,
        "minimum": dict(MIN_HEADCOUNT),
        "thin_positions": thin,
        "lacks_replacements": any(
            available[position] <= MIN_HEADCOUNT[position] and not _affordable(listings, position, cash) for position in thin
        ),
        "lacks_liquidity": lacks_liquidity,
        "clause_alerts": alerts,
    }


def _clause_alerts(
    squad: dict[str, Any],
    *,
    position: str,
    available: int,
    cash: int | None,
    listings: list[dict[str, Any]],
    trends: dict[str, dict[str, Any]],
    own_cash: int | None,
    now: datetime,
) -> list[dict[str, Any]]:
    cover = max(0, available - MIN_HEADCOUNT[position])
    affordable = _affordable(listings, position, cash)
    lacks_replacements = cover <= 0 and not affordable
    lacks_liquidity = isinstance(cash, int) and (cash <= 0 or (bool(_priced(listings, position)) and not affordable))
    if not (lacks_replacements or lacks_liquidity):
        return []
    alerts: list[dict[str, Any]] = []
    for player in squad.get("players") or []:
        if not isinstance(player, dict) or player.get("position") != position:
            continue
        trend = trends.get(player["player_id"]) if isinstance(player.get("player_id"), str) else None
        if unavailable_reason(player, trend):
            continue
        lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
        shielded = player.get("is_shielded")
        clause = player.get("buyout_clause") if isinstance(player.get("buyout_clause"), int) else None
        present = lock.get("present") is True and isinstance(lock.get("local_time"), str) and isinstance(lock.get("local_date"), str)
        scheduled = shielded is False and present and isinstance(clause, int)
        reason = "desbloqueo con hora y minuto"
        if shielded is not False:
            scheduled = False
            reason = "blindado_o_sin_dato"
        elif not present:
            scheduled = False
            reason = "la API no envió marca de desbloqueo"
        elif not isinstance(clause, int):
            scheduled = False
            reason = "clausula_desconocida"
        we_can_pay = isinstance(own_cash, int) and isinstance(clause, int) and own_cash >= clause
        if we_can_pay and isinstance(own_cash, int) and isinstance(clause, int) and own_cash - clause < 0:
            we_can_pay = False
        alerts.append(
            {
                "team_id": squad.get("team_id"),
                "manager_name": squad.get("manager_name"),
                "player_id": player.get("player_id"),
                "name": player.get("name"),
                "nickname": player.get("nickname"),
                "position": position,
                "available": available,
                "minimum": MIN_HEADCOUNT[position],
                "squad_cover": cover,
                "lacks_replacements": lacks_replacements,
                "lacks_liquidity": lacks_liquidity,
                "buyout_clause_eur": clause,
                "is_shielded": shielded if isinstance(shielded, bool) else None,
                "clause_lock": {
                    "present": lock.get("present") is True,
                    "is_locked": lock.get("is_locked") if isinstance(lock.get("is_locked"), bool) else None,
                    "local_date": lock.get("local_date") if isinstance(lock.get("local_date"), str) else None,
                    "local_time": lock.get("local_time") if isinstance(lock.get("local_time"), str) else None,
                    "expires_at": lock.get("expires_at") if isinstance(lock.get("expires_at"), str) else None,
                    "timezone": lock.get("timezone") if isinstance(lock.get("timezone"), str) else display_zone()[0],
                },
                "alert_local_date": lock.get("local_date") if scheduled else None,
                "alert_local_time": lock.get("local_time") if scheduled else None,
                "already_open": bool(present and lock.get("is_locked") is False),
                "scheduled": scheduled,
                "schedule_reason": reason,
                "we_can_pay": we_can_pay,
                "eligible": scheduled and we_can_pay,
                "observed_at": _iso(now),
            }
        )
    return alerts


def _affordable(listings: list[dict[str, Any]], position: str, cash: int | None) -> bool:
    if not isinstance(cash, int) or cash < 0:
        return False
    return any(price <= cash for price in _priced(listings, position))


def _priced(listings: list[dict[str, Any]], position: str) -> list[int]:
    prices: list[int] = []
    for listing in listings:
        if listing.get("position") != position:
            continue
        price = listing.get("sale_price")
        if not isinstance(price, int):
            price = listing.get("leading_bid")
        if isinstance(price, int) and not isinstance(price, bool):
            prices.append(price)
    return prices


def _lacks_liquidity(cash: int | None, thin: list[str], listings: list[dict[str, Any]]) -> bool | None:
    if not isinstance(cash, int):
        return None
    if cash <= 0:
        return True
    for position in thin:
        prices = _priced(listings, position)
        if prices and cash < min(prices):
            return True
    return False


def _direct(own_rank: Any, rival_rank: Any) -> bool | None:
    if not isinstance(own_rank, int) or not isinstance(rival_rank, int):
        return None
    return abs(own_rank - rival_rank) <= DIRECT_RIVAL_RANK_WINDOW


def _ledger(team_id: str, events: list[dict[str, Any]], squad: dict[str, Any] | None) -> dict[str, Any]:
    initial: int | None = None
    premiums = 0
    purchases = 0
    clauses = 0
    sales = 0
    ignored = 0
    lines: list[dict[str, Any]] = []
    for event in events:
        kind = str(event["kind"])
        amount = event["amount_eur"]
        if not isinstance(amount, int):
            ignored += 1
            continue
        if kind == "initial":
            if initial is None:
                initial = amount
            else:
                ignored += 1
                continue
        elif kind == "premium":
            premiums += amount
        elif kind == "buy":
            purchases += amount
        elif kind == "clause":
            clauses += amount
        elif kind == "sell":
            sales += amount
        else:
            ignored += 1
            continue
        signed = amount if kind in {"initial", "premium", "sell"} else -amount
        lines.append(
            {
                "kind": kind,
                "amount_eur": amount,
                "signed_eur": signed,
                "player_id": event.get("player_id"),
                "label": event.get("label"),
                "at": event.get("at"),
            }
        )
    reconstructed = None if initial is None else initial + premiums - purchases - clauses + sales
    observed = squad.get("cash") if isinstance(squad, dict) and isinstance(squad.get("cash"), int) else None
    gap = None if reconstructed is None or observed is None else observed - reconstructed
    return {
        "team_id": team_id,
        "manager_name": squad.get("manager_name") if isinstance(squad, dict) else None,
        "initial_budget_eur": initial,
        "premiums_eur": premiums,
        "purchases_eur": purchases,
        "clauses_eur": clauses,
        "sales_eur": sales,
        "reconstructed_cash_eur": reconstructed,
        "observed_cash_eur": observed,
        "balanced": None if gap is None else gap == 0,
        "gap_eur": gap,
        "ignored_events": ignored,
        "events": lines,
    }


def _parse_event(row: dict[str, Any]) -> dict[str, Any] | None:
    if "activityTypeId" in row or "activity_type_id" in row:
        from toolbox.league_history import parse_activity_row

        return parse_activity_row(row)
    kind = _kind(row)
    amount = _amount(row)
    team_id = _team_id(row)
    if kind is None or amount is None or team_id is None:
        return None
    return {
        "team_id": team_id,
        "kind": kind,
        "amount_eur": amount,
        "player_id": _text(_first(row, *_PLAYER_FIELDS)) or _nested_player(row),
        "label": _text(_first(row, "label", "description", "title", "message")),
        "at": _text(_first(row, *_TIME_FIELDS)),
    }


def _event_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("events", "transactions", "news", "activity", "elements", "items", "data", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    if _kind(payload) and _team_id(payload):
        return [payload]
    return []


def _kind(row: dict[str, Any]) -> str | None:
    raw = _first(row, *_KIND_FIELDS)
    if not isinstance(raw, str):
        return None
    return _KINDS.get(_fold(raw))


def _amount(row: dict[str, Any]) -> int | None:
    value = _first(row, *_AMOUNT_FIELDS)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return abs(value)
    if isinstance(value, float) and value == int(value):
        return abs(int(value))
    if isinstance(value, str):
        digits = value.replace(".", "").replace(" ", "").replace("€", "")
        if digits.startswith("-"):
            digits = digits[1:]
        if digits.isdigit():
            return int(digits)
    return None


def _team_id(row: dict[str, Any]) -> str | None:
    found = _text(_first(row, *_TEAM_FIELDS))
    if found:
        return found
    team = row.get("team") if isinstance(row.get("team"), dict) else {}
    return _text(_first(team, "id", "teamId"))


def _nested_player(row: dict[str, Any]) -> str | None:
    player = row.get("player") if isinstance(row.get("player"), dict) else {}
    master = player.get("playerMaster") if isinstance(player.get("playerMaster"), dict) else {}
    return _text(_first(player, "id", "playerId")) or _text(_first(master, "id", "playerId"))


def _first(row: dict[str, Any], *keys: str) -> Any:
    folded = {_fold(str(key)): value for key, value in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        alias = folded.get(_fold(key))
        if alias not in (None, ""):
            return alias
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(character for character in normalized if not unicodedata.combining(character)).lower().strip()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clock(moment: datetime) -> dict[str, str]:
    zone_name, zone = display_zone()
    local = moment.astimezone(zone)
    return {
        "at": moment.astimezone(timezone.utc).isoformat(),
        "local_date": local.date().isoformat(),
        "local_time": local.strftime("%H:%M"),
        "local_clock": local.strftime("%H:%M:%S"),
        "timezone": zone_name,
    }


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _field(text: str, key: str) -> str | None:
    import re

    match = re.search(rf"(?m)^-?\s*{re.escape(key)}:\s*(\S+)", text)
    if match is None:
        return None
    return match.group(1).strip()


def _integer_token(value: str | None) -> bool:
    if value is None:
        return False
    token = value[1:] if value.startswith("-") else value
    return token.isdigit()


def _memory_entry(
    *,
    league_id: Any,
    optimized: dict[str, Any],
    flipped: dict[str, Any],
    needs: dict[str, Any],
    governance: dict[str, Any],
    now: datetime,
) -> str:
    zone_name, zone = display_zone()
    local = now.astimezone(zone)
    points = optimized.get("expected_points") if optimized.get("ok") else None
    formation = optimized.get("formation") if optimized.get("ok") else None
    cash = optimized.get("cash_eur") if optimized.get("ok") else None
    void = optimized.get("void_reasons") if optimized.get("matchday_void") else []
    signings = flipped.get("count") if flipped.get("ok") else 0
    alerts = len(needs.get("clause_alerts") or [])
    government = "rechazada" if governance.get("execute_requested") and governance.get("orders") else "silencio"
    if governance.get("execute_requested") and any(order.get("status") == "blocked" for order in governance.get("orders") or []):
        government = "rechazada"
    lines = [
        f"## {local.strftime('%Y-%m-%d %H:%M')} {zone_name} · jornada desconocida · ciclo",
        "",
        f"- liga: {league_id if isinstance(league_id, str) else 'desconocida'}",
        f"- hechos: optimize esperado {points} formación {formation} caja {cash} eur; flip {signings}; clausulazos agendados {alerts}",
        f"- supuestos: jornada no viene en el JSON; bonus Relevo solo si el dato está en el jugador; {void or 'sin anulación'}",
        "- plan: sin envío a la API en esta fase",
        f"- gobierno: {government}",
        "- ejecutado: no",
    ]
    return "\n".join(lines)


def _read_user_file() -> str:
    from toolbox import project_root

    path = project_root() / "context" / "USER.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _failure(command: str, code: str, message: str, league_id: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "league_id": league_id if isinstance(league_id, str) else None,
        "from_cache": False,
        "error": {"code": code, "message": message, "status": None},
    }


def _bundle(
    client: CatalogClient,
    *,
    league: str | None,
    fresh: bool,
    trends_document: dict[str, Any] | None,
    cache: ResponseCache | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, ResponseCache, bool]:
    market = client.market_document(league, fresh=fresh)
    squads = client.squads_document(league, fresh=fresh)
    trends = trends_document
    if trends is None:
        from toolbox.scrapers import build_trends

        trends = build_trends(league=league, fresh=fresh, laliga=client)
    if cache is not None:
        return market, squads, trends, cache, False
    store = ResponseCache()
    return market, squads, trends, store, True


def _snapshot_index(cache: ResponseCache | None) -> dict[tuple[str, str], int]:
    from toolbox.cache import PriceSnapshotStore

    store = PriceSnapshotStore(
        root=cache.root if cache is not None else None,
        client=cache.client if cache is not None else None,
    )
    grouped = store.list_history(days=120)
    index: dict[tuple[str, str], int] = {}
    for player_id, rows in grouped.items():
        if not isinstance(player_id, str):
            continue
        for row in rows:
            day = row.get("day")
            value = row.get("market_value")
            if isinstance(day, str) and isinstance(value, int) and not isinstance(value, bool):
                index[(player_id, day)] = value
    return index


def _cached_value(
    kind: str,
    fingerprint: dict[str, Any],
    build: Callable[[], dict[str, Any]],
    *,
    cache: ResponseCache | None,
    fresh: bool,
) -> dict[str, Any]:
    if cache is None or fresh:
        return build()
    from toolbox.analyzer import _digest

    url = f"phase3://{kind}/{_digest(fingerprint)}"
    cached = cache.get_json(url)
    if isinstance(cached, dict) and isinstance(cached.get("ledgers"), list) and isinstance(cached.get("history"), dict):
        return cached
    books = build()
    cache.put_json(url, books, LEDGER_TTL_SECONDS)
    return books


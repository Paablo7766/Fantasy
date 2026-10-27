"""Decisión de mercado: PUJAR / ESPERAR / NO.

Solo usa campos presentes en market + trends (AF) + flip + optimize.
No inventa techos, puntos ni señales. Los componentes ausentes suman 0
y se listan en ``missing_inputs``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from toolbox.own_intel import markets_until_kickoff

from toolbox.analyzer import (
    CatalogClient,
    index_trends,
    optimize_from_documents,
    own_squad,
    trend_usable,
    unavailable_reason,
)
from toolbox.bid_war import overbid_risk, plan_market_auction_bid, profiles_for_listing, public_bids, recommend_bid, rival_snapshots
from toolbox.league_history import fit_rival_profiles_eb
from toolbox.bidding import assess_purchase, bid_amount, schedule_snipe
from toolbox.cache import ResponseCache
from toolbox.normalize import SCHEMA_VERSION, titularity_overrides_injury

DECISION_PUJAR = "PUJAR"
DECISION_ESPERAR = "ESPERAR"
DECISION_NO = "NO"

# Pesos de ordenación: solo se aplican si el componente está presente.
W_FLIP = 3.0
W_POINTS = 2.0
W_GAP = 2.5
W_CALENDAR = 1.0
W_BARGAIN = 1.5
W_FAIR = 0.5
W_OVERPAY = -2.0
W_SIGNAL_DOWN = -2.5
MIN_POINTS_ROI = 0.5  # pts por millón para contar como motivo de puntos


class MarketIntelClient(CatalogClient, Protocol):
    pass


def price_band(bid_eur: int | None, ideal: int | None, maximum: int | None) -> str:
    """Compara la puja operativa con ideal/máx AF. Sin techos → unknown."""
    if not isinstance(bid_eur, int) or isinstance(bid_eur, bool):
        return "unknown"
    if not isinstance(ideal, int) or isinstance(ideal, bool):
        return "unknown"
    if bid_eur <= ideal:
        return "bargain"
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        if bid_eur <= maximum:
            return "fair"
        return "overpay"
    # Ideal sin máx: por encima del ideal es overpay relativo
    return "overpay"


def allocate_day_budget(
    decisions: list[dict[str, Any]],
    *,
    cash: int | None,
    trends: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """Reparte la caja entre las PUJAR del día. No trata cada listing como si tuviera el saldo entero.

    Si hay N mercados diarios hasta el primer saque, hoy toca caja//N. Un hueco
    de XI puede usar más, hasta la caja, porque el cero de jornada manda.
    """
    empty = {
        "markets_left": None,
        "day_budget_eur": cash if isinstance(cash, int) else None,
        "plan_spend_eur": 0,
        "plan_cash_after_eur": cash if isinstance(cash, int) else None,
    }
    if not isinstance(cash, int) or isinstance(cash, bool) or cash < 0:
        return empty
    kickoff = _jornada_kickoff(trends, now)
    markets = markets_until_kickoff(kickoff, now=now)
    if markets is None or markets < 1:
        markets = 1
        future = False
    else:
        future = markets > 1
    day_budget = cash // markets
    running_total = cash
    running_day = day_budget
    spent = 0
    for row in decisions:
        if row.get("decision") != DECISION_PUJAR:
            continue
        amount = row.get("suggested_bid")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            amount = row.get("bid_eur")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            continue
        gap = _is_gap_fill(row)
        cap = running_total if gap else min(running_day, running_total)
        if amount <= cap:
            running_total -= amount
            running_day = max(0, running_day - amount)
            spent += amount
            row["cash_after_eur"] = running_total
            continue
        row["decision"] = DECISION_ESPERAR
        reason = "caja_otros_mercados" if future else "caja_otras_pujas"
        row["primary_motive"] = reason
        reasons = row.get("reasons") if isinstance(row.get("reasons"), list) else []
        if reason not in reasons:
            reasons.append(reason)
        row["reasons"] = reasons
        motives = row.get("motives") if isinstance(row.get("motives"), list) else []
        if reason not in motives:
            motives.append(reason)
        row["motives"] = motives
        row["cash_after_eur"] = running_total
    return {
        "markets_left": markets,
        "day_budget_eur": day_budget,
        "plan_spend_eur": spent,
        "plan_cash_after_eur": running_total,
    }


def _is_gap_fill(row: dict[str, Any]) -> bool:
    if row.get("primary_motive") == "hueco":
        return True
    motives = row.get("motives") if isinstance(row.get("motives"), list) else []
    return any(item in {"hueco", "hueco_xi", "hueco_posicion"} for item in motives)


def _jornada_kickoff(trends: dict[str, Any] | None, now: datetime) -> str | None:
    """Saque de la jornada: el día Madrid con más clubes pendientes, primer silbato de ese día.

    Un partido entre semana de dos clubes no cierra el horizonte: el mercado diario
    sigue hasta la jornada en la que juega el grueso del catálogo.
    """
    if not isinstance(trends, dict):
        return None
    madrid = ZoneInfo("Europe/Madrid")
    by_day: dict[Any, dict[str, datetime]] = {}
    players = trends.get("players") if isinstance(trends.get("players"), list) else []
    for index, player in enumerate(players):
        if not isinstance(player, dict):
            continue
        fixture = player.get("fixture") if isinstance(player.get("fixture"), dict) else {}
        kick = _parse_kickoff(fixture.get("kickoff"))
        if kick is None:
            calendar = player.get("own_calendar") if isinstance(player.get("own_calendar"), list) else []
            if calendar and isinstance(calendar[0], dict):
                kick = _parse_kickoff(calendar[0].get("kickoff"))
        if kick is None or kick < now:
            continue
        club = player.get("club") if isinstance(player.get("club"), str) and player["club"].strip() else None
        key = club.strip() if club else f"id:{player.get('player_id') or index}"
        day = kick.astimezone(madrid).date()
        slot = by_day.setdefault(day, {})
        previous = slot.get(key)
        if previous is None or kick < previous:
            slot[key] = kick
    if not by_day:
        return None
    best_day = max(by_day, key=lambda day: (len(by_day[day]), -day.toordinal()))
    return min(by_day[best_day].values()).astimezone(timezone.utc).isoformat()


def _parse_kickoff(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_market_decisions(
    market: dict[str, Any],
    trends: dict[str, Any] | None,
    flip: dict[str, Any] | None,
    optimize: dict[str, Any] | None,
    *,
    owned_ids: set[str] | None = None,
    rivals: list[dict[str, Any]] | None = None,
    squads: dict[str, Any] | None = None,
    history: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Veredicto por listing del mercado del día."""
    current = now or datetime.now(timezone.utc)
    listings = [row for row in (market or {}).get("listings") or [] if isinstance(row, dict)]
    indexed = index_trends(trends)
    cash = flip.get("cash_eur") if isinstance(flip, dict) and isinstance(flip.get("cash_eur"), int) else None
    lineup_void = bool(flip.get("matchday_void")) if isinstance(flip, dict) else False
    own_team_id = flip.get("team_id") if isinstance(flip, dict) and isinstance(flip.get("team_id"), str) else None

    owned: set[str] = set(owned_ids or ())
    for bucket in ("signings", "rejected"):
        rows = flip.get(bucket) if isinstance(flip, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            reasons = row.get("reasons") if isinstance(row.get("reasons"), list) else []
            if "ya_en_plantilla" in reasons:
                pid = row.get("player_id")
                if isinstance(pid, str):
                    owned.add(pid)

    gap_positions = _gap_positions(optimize)
    gap_player_ids = _gap_player_ids(optimize)
    xi_margins = _xi_margins(optimize, indexed)
    pressure = rivals if isinstance(rivals, list) else rival_snapshots(squads, trends)
    activity_buys = (
        history.get("activity_buys")
        if isinstance(history, dict) and isinstance(history.get("activity_buys"), list)
        else []
    )
    rival_states = [dict(row) for row in pressure if isinstance(row, dict)]
    base_rival_profiles = fit_rival_profiles_eb(
        [item for item in activity_buys if isinstance(item, dict)],
        rival_states,
    )
    peers_by_position: dict[str, int] = {}
    for row in listings:
        pos = row.get("position") if isinstance(row.get("position"), str) else None
        if pos:
            peers_by_position[pos] = peers_by_position.get(pos, 0) + 1

    decisions: list[dict[str, Any]] = []
    for listing in listings:
        player_id = listing.get("player_id") if isinstance(listing.get("player_id"), str) else None
        if not player_id:
            continue
        trend = indexed.get(player_id) or {}
        decisions.append(
            _decide_listing(
                listing,
                trend,
                cash=cash,
                lineup_void=lineup_void,
                own_team_id=own_team_id,
                owned=player_id in owned,
                gap_positions=gap_positions,
                gap_player_ids=gap_player_ids,
                rivals=pressure,
                xi_margins=xi_margins,
                history=history,
                base_rival_profiles=base_rival_profiles,
                free_tier_peers_count=peers_by_position.get(
                    listing.get("position") if isinstance(listing.get("position"), str) else "", 0
                ),
                now=current,
            )
        )

    decisions.sort(
        key=lambda row: (
            _decision_rank(row.get("decision")),
            -float(row.get("score") or 0.0),
            str(row.get("player_id") or ""),
        )
    )
    budget = allocate_day_budget(decisions, cash=cash, trends=trends, now=current)
    decisions.sort(
        key=lambda row: (
            _decision_rank(row.get("decision")),
            -float(row.get("score") or 0.0),
            str(row.get("player_id") or ""),
        )
    )
    summary = {
        "pujar": sum(1 for row in decisions if row.get("decision") == DECISION_PUJAR),
        "esperar": sum(1 for row in decisions if row.get("decision") == DECISION_ESPERAR),
        "no": sum(1 for row in decisions if row.get("decision") == DECISION_NO),
        "cash_eur": cash,
        "count": len(decisions),
        "liga": sum(1 for row in decisions if row.get("offer_source") == "liga"),
        "rival": sum(1 for row in decisions if row.get("offer_source") == "rival"),
        "propio": sum(1 for row in decisions if row.get("offer_source") == "propio"),
        "markets_left": budget.get("markets_left"),
        "day_budget_eur": budget.get("day_budget_eur"),
        "plan_spend_eur": budget.get("plan_spend_eur"),
        "plan_cash_after_eur": budget.get("plan_cash_after_eur"),
        "league_war_count": history.get("war_count") if isinstance(history, dict) and isinstance(history.get("war_count"), int) else 0,
        "league_priced_count": history.get("priced_count") if isinstance(history, dict) and isinstance(history.get("priced_count"), int) else 0,
        "league_buy_count": history.get("buy_count") if isinstance(history, dict) and isinstance(history.get("buy_count"), int) else 0,
        "league_median_premium": history.get("median_premium") if isinstance(history, dict) and isinstance(history.get("median_premium"), (int, float)) and not isinstance(history.get("median_premium"), bool) else None,
        "league_bomb_count": history.get("bomb_count") if isinstance(history, dict) and isinstance(history.get("bomb_count"), int) else 0,
    }
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "market-intel",
        "league_id": market.get("league_id") if isinstance(market.get("league_id"), str) else None,
        "league_name": market.get("league_name") if isinstance(market.get("league_name"), str) else None,
        "fetched_at": market.get("fetched_at"),
        "from_cache": False,
        "summary": summary,
        "jornada_board": build_jornada_board(trends, listings),
        "decisions": decisions,
    }


def build_market_intel_command(
    client: MarketIntelClient,
    *,
    league: str | None,
    fresh: bool,
    trends_document: dict[str, Any] | None = None,
    cache: ResponseCache | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    from toolbox.bidding import flip_from_documents
    from toolbox.scrapers import build_trends

    market = client.market_document(league, fresh=fresh)
    squads = client.squads_document(league, fresh=fresh)
    trends = trends_document
    if trends is None:
        trends = build_trends(league=league, fresh=fresh, laliga=client, market=market, squads=squads)
    owns = cache is None
    store = cache if cache is not None else ResponseCache()
    current = now or datetime.now(timezone.utc)
    try:
        optimized = optimize_from_documents(squads, trends, cache=store, fresh=fresh, market=market)
        flipped = flip_from_documents(
            market,
            squads,
            trends,
            lineup=optimized if optimized.get("ok") else None,
            now=current,
            cache=store,
            fresh=fresh,
        )
        from toolbox.bidding import load_activity, needs_from_documents

        activity = load_activity(client, squads.get("league_id") if isinstance(squads.get("league_id"), str) else None, fresh=fresh)
        needs = needs_from_documents(market, squads, trends, activity, now=current, cache=store, fresh=fresh)
        document = build_market_decisions(
            market,
            trends,
            flipped,
            optimized,
            owned_ids=_owned_ids(squads),
            rivals=needs.get("rivals") if isinstance(needs.get("rivals"), list) else None,
            squads=squads,
            history=needs.get("history") if isinstance(needs.get("history"), dict) else None,
            now=current,
        )
        document["league_id"] = (
            squads.get("league_id")
            if isinstance(squads.get("league_id"), str)
            else document.get("league_id")
        )
        return document
    finally:
        if owns:
            store.close()


def decisions_from_board(board: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Construye decisions desde la foto del dashboard (server)."""
    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    flip = board.get("flip") if isinstance(board.get("flip"), dict) else None
    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else None
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else None
    rivals = needs.get("rivals") if isinstance(needs, dict) and isinstance(needs.get("rivals"), list) else None
    return build_market_decisions(
        market,
        trends,
        flip,
        optimize,
        owned_ids=_owned_ids(squads) if isinstance(squads, dict) else set(),
        rivals=rivals,
        squads=squads,
        history=needs.get("history") if isinstance(needs, dict) and isinstance(needs.get("history"), dict) else None,
        now=now,
    )


def _owned_ids(squads: dict[str, Any] | None) -> set[str]:
    owned: set[str] = set()
    own = own_squad(squads) if isinstance(squads, dict) else None
    if not isinstance(own, dict):
        return owned
    for player in own.get("players") or []:
        if isinstance(player, dict) and isinstance(player.get("player_id"), str):
            owned.add(player["player_id"])
    return owned


def _decide_listing(
    listing: dict[str, Any],
    trend: dict[str, Any],
    *,
    cash: int | None,
    lineup_void: bool,
    own_team_id: str | None,
    owned: bool,
    gap_positions: set[str],
    gap_player_ids: set[str],
    rivals: list[dict[str, Any]] | None = None,
    xi_margins: dict[str, dict[str, Any]] | None = None,
    history: dict[str, Any] | None = None,
    base_rival_profiles: dict[str, Any] | None = None,
    free_tier_peers_count: int = 0,
    now: datetime,
) -> dict[str, Any]:
    player_id = listing.get("player_id") if isinstance(listing.get("player_id"), str) else None
    position = (
        listing.get("position")
        if isinstance(listing.get("position"), str)
        else trend.get("position") if isinstance(trend.get("position"), str) else None
    )
    amount = bid_amount(listing)
    purchase = assess_purchase(cash=cash, cost=amount, lineup_void=lineup_void)
    usable = trend_usable(trend)
    p_titular = _probability(trend.get("p_titular"))
    blocked = unavailable_reason(listing, trend if usable else None)
    af_injury = trend.get("af_injury") if isinstance(trend.get("af_injury"), dict) else None
    af_suspension = trend.get("af_suspension") if isinstance(trend.get("af_suspension"), dict) else None
    if af_injury and not blocked and not titularity_overrides_injury(
        p_titular,
        source=trend.get("p_titular_source") if isinstance(trend.get("p_titular_source"), str) else None,
        lineup_status=trend.get("lineup_status") if isinstance(trend.get("lineup_status"), str) else None,
    ):
        blocked = "lesionado"
    if af_suspension and not blocked:
        blocked = "sancionado"

    offer_source, seller_id, seller_name = _offer_source(listing, own_team_id)
    seller = seller_id
    own_listing = offer_source == "propio"
    snipe = schedule_snipe(
        listing,
        cash=cash,
        lineup_void=lineup_void,
        own_team_id=own_team_id,
        now=now,
        unavailable=blocked,
    )

    # Cascada: own_* → af_* → LALIGA/OPTA.
    own_ideal = trend.get("own_ideal_bid") if isinstance(trend.get("own_ideal_bid"), int) else None
    own_maximum = trend.get("own_max_bid") if isinstance(trend.get("own_max_bid"), int) else None
    af_ideal = trend.get("af_ideal_bid") if isinstance(trend.get("af_ideal_bid"), int) else None
    af_maximum = trend.get("af_max_bid") if isinstance(trend.get("af_max_bid"), int) else None
    ideal = own_ideal if own_ideal is not None else af_ideal
    maximum = own_maximum if own_maximum is not None else af_maximum
    band = price_band(amount, ideal, maximum)

    missing: list[str] = []
    motives: list[str] = []
    reasons: list[str] = []
    score = 0.0

    # --- Campos numéricos (solo si existen) ---
    acceleration = _signed_int(trend.get("acceleration"))
    own_predicted = _signed_number(trend.get("own_predicted_delta"))
    af_predicted = _signed_number(trend.get("af_predicted_delta"))
    af_price_delta = _signed_number(trend.get("af_price_delta"))
    price_delta = _signed_number(trend.get("price_delta"))
    day_delta = (
        own_predicted
        if own_predicted is not None
        else acceleration
        if acceleration is not None
        else af_predicted
        if af_predicted is not None and usable
        else af_price_delta
        if af_price_delta is not None and usable
        else price_delta
    )
    own_signal = trend.get("own_market_signal") if isinstance(trend.get("own_market_signal"), str) else None
    own_strength = _signed_number(trend.get("own_signal_strength"))
    af_signal = trend.get("af_market_signal") if isinstance(trend.get("af_market_signal"), str) else None
    af_strength = _signed_number(trend.get("af_signal_strength"))
    own_expected = _signed_number(trend.get("own_expected_points"))
    af_expected = _signed_number(trend.get("af_expected_points"))
    opta_expected = _signed_number(trend.get("expected_points"))
    expected_pts, expected_source = _expected_points_cascade(
        own_expected, af_expected, opta_expected, usable=usable
    )
    # p_titular de alineaciones no depende del matching AF (ya leído arriba).
    own_ppm = _signed_number(trend.get("own_points_per_million"))
    af_ppm = _signed_number(trend.get("af_points_per_million"))
    own_rec = _signed_number(trend.get("own_recommendation_pct"))
    af_rec = _signed_number(trend.get("af_recommendation_pct"))
    calendar_rec, calendar_diff = _next_calendar(trend)
    if calendar_rec is None and own_rec is not None:
        calendar_rec = own_rec

    if ideal is None:
        missing.append("ideal_bid")
    if maximum is None:
        missing.append("max_bid")
    if expected_pts is None:
        missing.append("expected_points")
    if p_titular is None:
        missing.append("p_titular")
    if day_delta is None:
        missing.append("price_delta")
    if own_signal is None and af_signal is None:
        missing.append("market_signal")
    if not usable and trend:
        missing.append("matching_confidence")

    # --- Vetos duros ---
    hard_veto = False
    if owned:
        hard_veto = True
        reasons.append("ya_en_plantilla")
    if own_listing:
        hard_veto = True
        reasons.append("listing_propio")
    if blocked:
        hard_veto = True
        reasons.append(blocked)
    if not purchase["eligible"]:
        hard_veto = True
        for reason in purchase["reasons"]:
            if reason not in reasons:
                reasons.append(reason)
    if snipe.get("status") == "window_passed":
        hard_veto = True
        if "mercado_cerrado" not in reasons:
            reasons.append("mercado_cerrado")

    # Matching bajo: no se puede usar AF como única señal positiva
    af_only_blocked = False
    if not usable:
        af_only_blocked = True

    # --- Motivos positivos / negativos ---
    # Cascada flip: aceleración LALIGA → own → AF (AF solo si matching usable).
    flip_up = False
    if acceleration is not None and acceleration > 0:
        flip_up = True
        motives.append("aceleracion")
        score += W_FLIP
    elif own_predicted is not None and own_predicted > 0:
        flip_up = True
        motives.append("own_predicted_up")
        score += W_FLIP * (min(own_strength or 1.0, 1.0) if own_strength is not None else 1.0)
    elif own_signal == "up":
        flip_up = True
        motives.append("own_signal_up")
        score += W_FLIP * 0.85
    elif af_predicted is not None and af_predicted > 0 and usable:
        flip_up = True
        motives.append("af_predicted_up")
        score += W_FLIP * (min(af_strength or 1.0, 1.0) if af_strength is not None else 1.0)
    elif af_signal == "up" and usable:
        flip_up = True
        motives.append("af_signal_up")
        score += W_FLIP * 0.8

    flip_down = False
    if acceleration is not None and acceleration < 0:
        flip_down = True
        motives.append("aceleracion_baja")
        score += W_SIGNAL_DOWN
    elif own_predicted is not None and own_predicted < 0:
        flip_down = True
        motives.append("own_predicted_down")
        score += W_SIGNAL_DOWN
    elif own_signal == "down":
        flip_down = True
        motives.append("own_signal_down")
        score += W_SIGNAL_DOWN
    elif af_predicted is not None and af_predicted < 0 and usable:
        flip_down = True
        motives.append("af_predicted_down")
        score += W_SIGNAL_DOWN
    elif af_signal == "down" and usable:
        flip_down = True
        motives.append("af_signal_down")
        score += W_SIGNAL_DOWN

    # Si matching bajo, anular solo motivos AF (own_* y aceleración se mantienen).
    if af_only_blocked:
        af_motives = {"af_predicted_up", "af_signal_up", "af_predicted_down", "af_signal_down"}
        # Se recalculan TODOS los motivos de mercado desde los motivos que
        # sobreviven: antes solo el signo positivo recalculaba ``score``/``flip_up``
        # y ``flip_down`` quedaba congelado a True aunque su motivo ya no
        # estuviera en la lista, así que "aceleración +" podía acabar en NO por
        # una señal AF que no se estaba mostrando.
        motives = [m for m in motives if m not in af_motives]
        score = 0.0
        flip_up = False
        flip_down = False
        if "aceleracion" in motives:
            flip_up = True
            score += W_FLIP
        elif "own_predicted_up" in motives:
            flip_up = True
            score += W_FLIP * (min(own_strength or 1.0, 1.0) if own_strength is not None else 1.0)
        elif "own_signal_up" in motives:
            flip_up = True
            score += W_FLIP * 0.85
        if "aceleracion_baja" in motives:
            flip_down = True
            score += W_SIGNAL_DOWN
        elif "own_predicted_down" in motives:
            flip_down = True
            score += W_SIGNAL_DOWN
        elif "own_signal_down" in motives:
            flip_down = True
            score += W_SIGNAL_DOWN
        if not flip_up and not flip_down:
            reasons.append("matching_confidence")

    points_motive = False
    jornada_ev: float | None = None
    points_roi: float | None = None
    ppm = own_ppm if own_ppm is not None else (af_ppm if usable else None)
    if expected_pts is not None:
        jornada_ev = _jornada_ev(expected_pts, p_titular, expected_source)
        if jornada_ev is not None and isinstance(amount, int) and amount > 0:
            points_roi = round(jornada_ev / (amount / 1_000_000), 4)
        elif ppm is not None:
            points_roi = float(ppm)
        if points_roi is not None and points_roi >= MIN_POINTS_ROI:
            points_motive = True
            motives.append("puntos_jornada")
            score += W_POINTS * min(points_roi / 2.0, 2.0)
    elif ppm is not None and ppm >= MIN_POINTS_ROI:
        points_roi = float(ppm)
        points_motive = True
        motives.append("own_points_per_million" if own_ppm is not None else "af_points_per_million")
        score += W_POINTS

    gap_motive = False
    if player_id and player_id in gap_player_ids:
        gap_motive = True
        motives.append("hueco_xi")
        score += W_GAP
    elif position and position in gap_positions:
        gap_motive = True
        motives.append("hueco_posicion")
        score += W_GAP * 0.7

    calendar_motive = False
    rec = calendar_rec if calendar_rec is not None else (af_rec if usable else None)
    # Calendario own no requiere matching AF.
    if rec is not None:
        if rec >= 60:
            calendar_motive = True
            motives.append("calendario_favorable")
            score += W_CALENDAR * (rec / 100.0)
        elif rec <= 35:
            motives.append("calendario_duro")
            score -= W_CALENDAR

    if band == "bargain":
        motives.append("precio_chollo")
        score += W_BARGAIN
    elif band == "fair":
        motives.append("precio_justo")
        score += W_FAIR
    elif band == "overpay":
        motives.append("sobreprecio")
        score += W_OVERPAY

    xi_edge = _xi_edge(position, trend, usable, xi_margins)
    points_delta = xi_edge.get("points_delta")
    if isinstance(points_delta, (int, float)) and not isinstance(points_delta, bool) and points_delta > 0:
        motives.append("mejora_xi")
        score += W_GAP * min(float(points_delta) / 2.0, 2.0)
    elif isinstance(points_delta, (int, float)) and not isinstance(points_delta, bool) and points_delta <= 0:
        if points_motive and not flip_up and not gap_motive:
            points_motive = False
        motives.append("no_mejora_xi")

    # ``positive`` (lo que lleva a ESPERAR en vez de NO) exigía antes
    # ``score > 0``, pero los motivos BAJISTAS también restan y el precio de
    # chollo también suma: cualquier listing con una señal mala o con precio
    # bueno salía "positivo" y ``senal_debil`` era casi inalcanzable. Se decide
    # por motivos, no por el saldo del score.
    positive = (
        flip_up
        or points_motive
        or gap_motive
        or calendar_motive
        or "mejora_xi" in motives
        or band in ("bargain", "fair")
    )
    # Motivo positivo de precio solo no basta para PUJAR sin flip/puntos/hueco/mejora
    strong_positive = flip_up or points_motive or gap_motive or "mejora_xi" in motives

    decision = DECISION_NO
    primary: str | None = None

    if hard_veto:
        decision = DECISION_NO
        primary = reasons[0] if reasons else "veto"
    elif not strong_positive and flip_down and not gap_motive:
        decision = DECISION_NO
        primary = "senal_bajista"
        if "senal_bajista" not in reasons:
            reasons.append("senal_bajista")
    elif strong_positive and band == "overpay":
        decision = DECISION_ESPERAR
        primary = "sobreprecio"
        if "sobreprecio" not in reasons:
            reasons.append("sobreprecio")
    elif strong_positive and snipe.get("status") == "hidden" and snipe.get("eligible"):
        # Cierre futuro: no pujar aún; el snipe dispara en fire_local_clock.
        decision = DECISION_ESPERAR
        primary = "snipe"
        motives.append("snipe_programado")
        if "esperar_snipe" not in reasons:
            reasons.append("esperar_snipe")
    elif strong_positive and band in ("bargain", "fair", "unknown"):
        # unknown sin techo: se permite con motivo fuerte LALIGA/own/hueco/puntos
        own_flip = flip_up and any(
            m in motives for m in ("aceleracion", "own_predicted_up", "own_signal_up")
        )
        if band == "unknown" and af_only_blocked and not (
            own_flip or gap_motive or points_motive or "mejora_xi" in motives
        ):
            decision = DECISION_NO
            primary = "matching_confidence"
            if "matching_confidence" not in reasons:
                reasons.append("matching_confidence")
        else:
            decision = DECISION_PUJAR
            primary = _primary_motive(
                motives, flip_up=flip_up, points=points_motive, gap=gap_motive, mejora="mejora_xi" in motives
            )
    elif positive and not strong_positive:
        decision = DECISION_ESPERAR
        primary = "senal_debil"
        if flip_down:
            reasons.append("senal_bajista")
        reasons.append("senal_debil")
    else:
        decision = DECISION_NO
        primary = "sin_motivo"
        if "sin_motivo" not in reasons:
            reasons.append("sin_motivo")

    bid_plan = recommend_bid(
        listing,
        ideal=ideal,
        maximum=maximum,
        cash=cash,
        snipe_status=snipe.get("status") if isinstance(snipe.get("status"), str) else None,
    )
    bid_plan["overbid"] = overbid_risk(position, ideal, rivals)
    if not hard_veto and decision == DECISION_ESPERAR and primary == "snipe" and bid_plan.get("how") == "ahora":
        decision = DECISION_PUJAR
        primary = _primary_motive(
            motives, flip_up=flip_up, points=points_motive, gap=gap_motive, mejora="mejora_xi" in motives
        )
        motives.append("puja_temprana")
        reasons = [reason for reason in reasons if reason != "esperar_snipe"]
    elif not hard_veto and decision == DECISION_PUJAR and bid_plan.get("reason") in {
        "lider_supera_ideal",
        "suelo_sobre_ideal",
        "sobreprecio",
    }:
        decision = DECISION_ESPERAR
        primary = str(bid_plan.get("reason"))
        if primary not in reasons:
            reasons.append(primary)

    conflict = _source_conflict(
        own_expected=own_expected,
        af_expected=af_expected,
        own_max=own_maximum,
        af_max=af_maximum,
        own_signal=own_signal,
        af_signal=af_signal,
        usable=usable,
    )

    leading = listing.get("leading_bid") if isinstance(listing.get("leading_bid"), int) else None
    snipe_status = snipe.get("status") if isinstance(snipe.get("status"), str) else None
    populates_slot = bool(
        (player_id and player_id in gap_player_ids)
        or (position and position in gap_positions)
    )
    listing_profiles = profiles_for_listing(
        base_rival_profiles or {},
        listing=listing,
        own_team_id=own_team_id,
    )
    econ = plan_market_auction_bid(
        listing,
        trend,
        to_lead=amount,
        leading=leading,
        own_max=own_maximum,
        af_max=af_maximum,
        af_usable=usable,
        ideal=ideal,
        cash=cash,
        snipe_status=snipe_status,
        position=position,
        expected_pts=expected_pts,
        points_delta_xi=xi_edge.get("points_delta"),
        populates_empty_slot=populates_slot,
        free_tier_peers_count=free_tier_peers_count,
        rivals=rivals,
        rival_profiles=listing_profiles,
        own_team_id=own_team_id,
        history=history,
    )
    if hard_veto or decision == DECISION_NO:
        econ["suggested_bid"] = None
        econ["raise_to"] = None
        if econ.get("bid_limit") not in {"sobre_techo", "fuentes_no_coinciden", "sin_caja"}:
            econ["bid_limit"] = "no"
    elif decision == DECISION_PUJAR and econ.get("suggested_bid") is None and econ.get("bid_limit") in {
        "sobre_techo",
        "fuentes_no_coinciden",
        "sin_caja",
    }:
        decision = DECISION_ESPERAR
        primary = str(econ.get("bid_limit"))
        if primary not in reasons:
            reasons.append(primary)

    action, is_vetoed, action_reason = _action_from_decision(
        decision,
        conflict=conflict,
        bid_limit=econ.get("bid_limit") if isinstance(econ.get("bid_limit"), str) else None,
        hard_veto=hard_veto,
        reasons=reasons,
        expected_surplus_eur=econ.get("expected_surplus_eur"),
    )
    if is_vetoed:
        # Un veto no deja cifra: la interfaz no debe ofrecer "puja esto" y "NO"
        # a la vez. Se conserva el techo como dato, no como recomendación.
        econ["suggested_bid"] = None
        econ["raise_to"] = None

    return {
        "player_id": player_id,
        "name": trend.get("name") if isinstance(trend.get("name"), str) else listing.get("name"),
        "nickname": trend.get("nickname") if isinstance(trend.get("nickname"), str) else listing.get("nickname"),
        "position": position,
        "club": listing.get("club") if isinstance(listing.get("club"), str) else trend.get("club"),
        "offer_source": offer_source,
        "seller_team_id": seller_id,
        "seller_manager": seller_name,
        "image_url": listing.get("image_url")
        if isinstance(listing.get("image_url"), str)
        else trend.get("image_url") if isinstance(trend.get("image_url"), str) else None,
        "decision": decision,
        "primary_motive": primary,
        "motives": motives,
        "price_band": band,
        "bid_eur": amount,
        "sale_price": listing.get("sale_price") if isinstance(listing.get("sale_price"), int) else None,
        "ideal_bid": ideal,
        "max_bid": maximum,
        "own_ideal_bid": own_ideal,
        "own_max_bid": own_maximum,
        "af_ideal_bid": af_ideal,
        "af_max_bid": af_maximum,
        "expected_points": expected_pts,
        "expected_points_source": expected_source,
        "own_expected_points": own_expected,
        "af_expected_points": af_expected,
        "jornada_ev": jornada_ev,
        "points_roi": points_roi,
        "p_titular": p_titular,
        "price_delta": day_delta,
        "acceleration": acceleration,
        "own_market_signal": own_signal,
        "own_signal_strength": own_strength,
        "af_market_signal": af_signal if usable else None,
        "af_signal_strength": af_strength if usable else None,
        "own_recommendation_pct": own_rec,
        "af_recommendation_pct": af_rec if usable else None,
        "calendar_recommendation_pct": calendar_rec,
        "calendar_difficulty": calendar_diff,
        "cash_after_eur": purchase["cash_after_eur"],
        "matching_confidence": trend.get("matching_confidence")
        if isinstance(trend.get("matching_confidence"), (int, float))
        else None,
        "score": round(score, 4),
        "reasons": reasons,
        "missing_inputs": missing,
        "snipe": {
            "status": snipe.get("status"),
            "eligible": snipe.get("eligible"),
            "fire_at": snipe.get("fire_at"),
            "fire_local_clock": snipe.get("fire_local_clock"),
            "fire_local_time": snipe.get("fire_local_time"),
            "expires_local_clock": snipe.get("listing_expires_local_clock"),
        }
        if isinstance(snipe, dict)
        else None,
        "bid_plan": bid_plan,
        "suggested_bid": econ.get("suggested_bid"),
        "raise_to": econ.get("raise_to"),
        "bid_limit": econ.get("bid_limit"),
        "league_bid": econ.get("league_bid") if isinstance(econ.get("league_bid"), int) else None,
        "stretch_bid": econ.get("stretch_bid") if isinstance(econ.get("stretch_bid"), int) else None,
        "league_bid_blocked": econ.get("league_bid_blocked") is True,
        "league_war_count": history.get("war_count") if isinstance(history, dict) and isinstance(history.get("war_count"), int) else 0,
        "league_priced_count": history.get("priced_count") if isinstance(history, dict) and isinstance(history.get("priced_count"), int) else 0,
        "league_buy_count": history.get("buy_count") if isinstance(history, dict) and isinstance(history.get("buy_count"), int) else 0,
        "league_median_premium": history.get("median_premium")
        if isinstance(history, dict)
        and isinstance(history.get("median_premium"), (int, float))
        and not isinstance(history.get("median_premium"), bool)
        else None,
        "value_ceiling": econ.get("value_ceiling"),
        "value_ceiling_source": econ.get("value_ceiling_source"),
        "aggressive_ceiling": econ.get("aggressive_ceiling"),
        "aggressive_ceiling_source": econ.get("aggressive_ceiling_source"),
        "leading_bid": leading,
        "optimal_bid_eur": econ.get("optimal_bid_eur"),
        "win_probability": econ.get("win_probability"),
        "intrinsic_valuation_eur": econ.get("intrinsic_valuation_eur"),
        "expected_surplus_eur": econ.get("expected_surplus_eur"),
        "rival_knockout_targets": econ.get("rival_knockout_targets") or [],
        "bid_intent": econ.get("bid_intent"),
        "rival_bids": public_bids(listing, own_team_id),
        "replaces": xi_edge.get("replaces"),
        "points_delta": xi_edge.get("points_delta"),
        "points_delta_source": xi_edge.get("points_source"),
        "fixture": _fixture_view(trend, usable),
        "af_injury": af_injury,
        "af_suspension": af_suspension,
        "action": action,
        "is_vetoed": is_vetoed,
        "action_reason": action_reason,
        "source_conflict": conflict,
    }


def _offer_source(listing: dict[str, Any], own_team_id: str | None) -> tuple[str, str | None, str | None]:
    """Liga si el JSON no trae vendedor. Rival si el vendedor es otro equipo."""
    seller = listing.get("seller_team_id")
    seller_id = seller.strip() if isinstance(seller, str) and seller.strip() else None
    manager = listing.get("seller_manager")
    seller_name = manager.strip() if isinstance(manager, str) and manager.strip() else None
    if seller_id is None:
        return "liga", None, None
    if isinstance(own_team_id, str) and seller_id == own_team_id:
        return "propio", seller_id, seller_name
    return "rival", seller_id, seller_name


def _gap_positions(optimize: dict[str, Any] | None) -> set[str]:
    positions: set[str] = set()
    if not isinstance(optimize, dict) or optimize.get("ok") is False:
        return positions
    for key in ("gaps", "market_fills"):
        rows = optimize.get(key)
        if not isinstance(rows, list):
            continue
        for gap in rows:
            if not isinstance(gap, dict):
                continue
            missing = gap.get("missing")
            if isinstance(missing, int) and missing <= 0:
                continue
            pos = gap.get("position")
            if isinstance(pos, str) and pos:
                positions.add(pos)
    return positions


def _gap_player_ids(optimize: dict[str, Any] | None) -> set[str]:
    ids: set[str] = set()
    if not isinstance(optimize, dict) or optimize.get("ok") is False:
        return ids
    for key in ("gaps", "market_fills"):
        rows = optimize.get(key)
        if not isinstance(rows, list):
            continue
        for gap in rows:
            if not isinstance(gap, dict):
                continue
            for option in gap.get("options") or []:
                if isinstance(option, dict) and isinstance(option.get("player_id"), str):
                    ids.add(option["player_id"])
    return ids


def _next_calendar(trend: dict[str, Any]) -> tuple[float | None, str | None]:
    """Prefer own_calendar; fallback af_calendar."""
    for key in ("own_calendar", "af_calendar"):
        calendar = trend.get(key)
        if not isinstance(calendar, list) or not calendar:
            continue
        first = calendar[0]
        if not isinstance(first, dict):
            continue
        rec = _signed_number(first.get("recommendation_pct"))
        diff = first.get("difficulty") if isinstance(first.get("difficulty"), str) else None
        return rec, diff
    return None, None


def _source_conflict(
    *,
    own_expected: float | None,
    af_expected: float | None,
    own_max: int | None,
    af_max: int | None,
    own_signal: str | None,
    af_signal: str | None,
    usable: bool,
) -> str | None:
    """Discrepancia severa entre el motor propio y la fuente externa.

    Solo cuenta con las dos fuentes presentes. Una diferencia de techo del
    60 % o un signo opuesto en la previsión no se resuelven en la interfaz:
    el motor propio manda y la acción baja a NO.
    """
    if not usable:
        return None
    if isinstance(own_max, int) and isinstance(af_max, int) and own_max > 0 and af_max > 0:
        ratio = max(own_max, af_max) / min(own_max, af_max)
        if ratio >= 1.6:
            return "techo"
    if isinstance(own_expected, float) and isinstance(af_expected, float):
        low = min(own_expected, af_expected)
        high = max(own_expected, af_expected)
        if low > 0 and high / low >= 1.5:
            return "puntos"
    if own_signal in {"up", "down"} and af_signal in {"up", "down"} and own_signal != af_signal:
        return "senal"
    return None


def _action_from_decision(
    decision: str,
    *,
    conflict: str | None,
    bid_limit: str | None,
    hard_veto: bool,
    reasons: list[str],
    expected_surplus_eur: int | None = None,
) -> tuple[str, bool, str]:
    """Comando de una sola palabra para la interfaz.

    La discrepancia no se enseña como tabla: se convierte en un veto. El
    usuario ve ``NO`` y una frase, no dos cifras enfrentadas.

    Excepción: un conflicto de ``puntos`` con plusvalía esperada positiva no
    bloquea una operación rentable. Baja a ``ESPERAR`` (sin cifra de puja, no
    vetada) para revisarla antes de gastar caja.
    """
    if hard_veto:
        return "NO", True, _reason_copy(reasons[0] if reasons else None)
    surplus = expected_surplus_eur if isinstance(expected_surplus_eur, int) and not isinstance(expected_surplus_eur, bool) else None
    if conflict == "puntos" and surplus is not None and surplus > 0:
        return "ESPERAR", False, "Las fuentes discrepan en puntos, pero la plusvalía esperada es positiva: se revisa antes de pujar."
    if conflict or bid_limit == "fuentes_no_coinciden":
        return "NO", True, "Las fuentes no cuadran: el motor propio manda y no se puja."
    if bid_limit == "sobre_techo":
        return "NO", True, "El precio ya supera el techo: no se persigue."
    if decision == DECISION_PUJAR:
        return "PUJAR", False, "Señal y precio alineados."
    if decision == DECISION_ESPERAR:
        return "ESPERAR", False, "Hay señal, pero el precio o la caja todavía no acompañan."
    return "NO", True, "Sin motivo suficiente para gastar caja."


_REASON_COPY = {
    "ya_en_plantilla": "Ya es tuyo.",
    "listing_propio": "Es tu propio anuncio.",
    "lesionado": "Está lesionado.",
    "sancionado": "Está sancionado.",
    "sin_caja": "La caja no llega.",
    "caja_negativa": "La caja está en negativo: la jornada vale 0.",
    "mercado_cerrado": "El mercado ya cerró.",
    "sin_slots": "No queda hueco en la plantilla.",
}


def _reason_copy(reason: str | None) -> str:
    if not reason:
        return "No se puja."
    return _REASON_COPY.get(reason, reason.replace("_", " "))


def _slim_decision(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row.get("player_id"),
        "name": row.get("name"),
        "nickname": row.get("nickname"),
        "position": row.get("position"),
        "club": row.get("club"),
        "image_url": row.get("image_url") if isinstance(row.get("image_url"), str) else None,
        "action": row.get("action"),
        "is_vetoed": row.get("is_vetoed") is True,
        "action_reason": row.get("action_reason"),
        "decision": row.get("decision"),
        "expected_points": row.get("expected_points"),
        "expected_points_source": row.get("expected_points_source"),
        "suggested_bid": row.get("suggested_bid"),
        "bid_eur": row.get("bid_eur"),
        "raise_to": row.get("raise_to"),
        "points_delta": row.get("points_delta"),
        "cash_after_eur": row.get("cash_after_eur"),
        "when_local_time": (row.get("snipe") or {}).get("fire_local_time")
        if isinstance(row.get("snipe"), dict)
        else None,
    }


def _primary_motive(
    motives: list[str], *, flip_up: bool, points: bool, gap: bool, mejora: bool = False
) -> str:
    if gap and ("hueco_xi" in motives or "hueco_posicion" in motives):
        return "hueco"
    if mejora:
        return "mejora_xi"
    if flip_up:
        return "flip"
    if points:
        return "puntos"
    if "calendario_favorable" in motives:
        return "calendario"
    return motives[0] if motives else "senal"


def _expected_points_cascade(
    own_expected: float | None,
    af_expected: float | None,
    opta_expected: float | None,
    *,
    usable: bool,
) -> tuple[float | None, str | None]:
    """own_* ya es valor de jornada. AF/OPTA son proyección del partido, sin titularidad."""
    if own_expected is not None:
        return own_expected, "own"
    if af_expected is not None and usable:
        return af_expected, "af"
    if opta_expected is not None:
        return opta_expected, "opta"
    return None, None


def _jornada_ev(expected_pts: float, p_titular: float | None, source: str | None) -> float | None:
    """Valor esperado de la jornada.

    ``own_expected_points`` ya pondera minutos y titularidad. AF y OPTA de
    temporada no: hay que cruzarlos con ``p_titular``.
    """
    if source == "own":
        return round(float(expected_pts), 4)
    if p_titular is None:
        return None
    return round(float(expected_pts) * float(p_titular), 4)


def _matched_points(trend: dict[str, Any], usable: bool) -> tuple[float | None, str | None]:
    """Puntos de jornada comparables: own, o AF si el matching sirve. OPTA de temporada no entra."""
    own = _signed_number(trend.get("own_expected_points"))
    if own is not None:
        return own, "own"
    if usable:
        af = _signed_number(trend.get("af_expected_points"))
        if af is not None:
            return af, "af"
    return None, None


def _xi_margins(
    optimize: dict[str, Any] | None,
    indexed: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """El titular más flojo de cada posición, medido con la misma fuente de puntos."""
    margins: dict[str, dict[str, Any]] = {}
    if not isinstance(optimize, dict) or optimize.get("ok") is False:
        return margins
    xi = optimize.get("xi")
    if not isinstance(xi, list):
        return margins
    for row in xi:
        if not isinstance(row, dict):
            continue
        position = row.get("position")
        if position not in {"POR", "DEF", "MC", "DEL"}:
            continue
        player_id = row.get("player_id") if isinstance(row.get("player_id"), str) else None
        trend = indexed.get(player_id) if player_id else None
        if not isinstance(trend, dict):
            trend = {}
        points, source = _matched_points(trend, trend_usable(trend))
        candidate = {
            "player_id": player_id,
            "name": row.get("nickname") if isinstance(row.get("nickname"), str) else row.get("name"),
            "position": position,
            "club": row.get("club") if isinstance(row.get("club"), str) else trend.get("club"),
            "points": points,
            "points_source": source,
        }
        current = margins.get(position)
        if current is None:
            margins[position] = candidate
            continue
        current_points = current.get("points")
        if points is None:
            continue
        if current_points is None or float(points) < float(current_points):
            margins[position] = candidate
    return margins


def _xi_edge(
    position: str | None,
    trend: dict[str, Any],
    usable: bool,
    margins: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    empty: dict[str, Any] = {"replaces": None, "points_delta": None, "points_source": None}
    if not position or not isinstance(margins, dict):
        return empty
    slot = margins.get(position)
    if not isinstance(slot, dict):
        return empty
    market_points, market_source = _matched_points(trend, usable)
    slot_points = slot.get("points")
    slot_source = slot.get("points_source")
    delta = None
    source = None
    if (
        market_points is not None
        and isinstance(slot_points, (int, float))
        and not isinstance(slot_points, bool)
        and market_source
        and market_source == slot_source
    ):
        delta = round(float(market_points) - float(slot_points), 4)
        source = market_source
    name = slot.get("name") if isinstance(slot.get("name"), str) else None
    return {
        "replaces": {
            "player_id": slot.get("player_id"),
            "name": name,
            "position": slot.get("position"),
            "club": slot.get("club") if isinstance(slot.get("club"), str) else None,
            "points": slot_points if isinstance(slot_points, (int, float)) and not isinstance(slot_points, bool) else None,
            "points_source": slot_source if isinstance(slot_source, str) else None,
        },
        "points_delta": delta,
        "points_source": source,
    }


def _calendar_cell(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
        return None
    cell = raw[0]
    rec = _signed_number(cell.get("recommendation_pct"))
    if rec is None:
        return None
    return {
        "opponent": cell.get("opponent") if isinstance(cell.get("opponent"), str) else None,
        "is_home": cell.get("is_home") if isinstance(cell.get("is_home"), bool) else None,
        "predicted_score": cell.get("predicted_score") if isinstance(cell.get("predicted_score"), str) else None,
        "recommendation_pct": rec,
        "difficulty": cell.get("difficulty") if isinstance(cell.get("difficulty"), str) else None,
    }


def _fixture_view(trend: dict[str, Any], usable: bool) -> dict[str, Any] | None:
    own = _calendar_cell(trend.get("own_calendar"))
    af = _calendar_cell(trend.get("af_calendar")) if usable else None
    primary = own or af
    if primary is None:
        return None
    view = dict(primary)
    view["source"] = "own" if own else "af"
    if af is not None:
        view["af_recommendation_pct"] = af.get("recommendation_pct")
        view["af_difficulty"] = af.get("difficulty")
        view["af_opponent"] = af.get("opponent")
        view["af_predicted_score"] = af.get("predicted_score")
    return view


def build_jornada_board(
    trends: dict[str, Any] | None,
    listings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Equipos de la jornada ordenados por calendario contrastado. Sin celda, no entra."""
    from toolbox.matching import normalize_club, normalize_name

    clubs: dict[str, dict[str, Any]] = {}
    players = trends.get("players") if isinstance(trends, dict) else None
    if not isinstance(players, list):
        return []
    for player in players:
        if not isinstance(player, dict):
            continue
        club = player.get("club")
        if not isinstance(club, str) or not club.strip():
            continue
        key = normalize_club(club) or normalize_name(club)
        if not key:
            continue
        slot = clubs.setdefault(key, {"club": club, "own": None, "af": None})
        if slot["own"] is None:
            slot["own"] = _calendar_cell(player.get("own_calendar"))
        if slot["af"] is None and trend_usable(player):
            slot["af"] = _calendar_cell(player.get("af_calendar"))

    on_market: dict[str, int] = {}
    for listing in listings:
        club = listing.get("club") if isinstance(listing, dict) else None
        if not isinstance(club, str) or not club.strip():
            continue
        key = normalize_club(club) or normalize_name(club)
        if key:
            on_market[key] = on_market.get(key, 0) + 1

    rows: list[dict[str, Any]] = []
    for key, slot in clubs.items():
        own = slot.get("own") if isinstance(slot.get("own"), dict) else None
        af = slot.get("af") if isinstance(slot.get("af"), dict) else None
        primary = own or af
        if primary is None:
            continue
        rec = primary.get("recommendation_pct")
        if not isinstance(rec, (int, float)) or isinstance(rec, bool):
            continue
        row = {
            "club": slot.get("club"),
            "opponent": primary.get("opponent"),
            "is_home": primary.get("is_home"),
            "predicted_score": primary.get("predicted_score"),
            "recommendation_pct": rec,
            "difficulty": primary.get("difficulty"),
            "source": "own" if own else "af",
            "market_count": on_market.get(key, 0),
        }
        if af is not None:
            row["af_recommendation_pct"] = af.get("recommendation_pct")
            row["af_difficulty"] = af.get("difficulty")
            row["af_opponent"] = af.get("opponent")
            row["af_predicted_score"] = af.get("predicted_score")
        rows.append(row)
    rows.sort(key=lambda item: (-float(item["recommendation_pct"]), str(item.get("club") or "")))
    return rows


def _decision_rank(decision: Any) -> int:
    if decision == DECISION_PUJAR:
        return 0
    if decision == DECISION_ESPERAR:
        return 1
    return 2


def _signed_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _signed_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number > 1.0:
        number /= 100.0
    if number < 0.0 or number > 1.0:
        return None
    return round(number, 4)

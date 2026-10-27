"""Cómo pujar: ahora o en el snipe, con tope, y si un rival puede pasar por encima.

No cambia el veredicto PUJAR / ESPERAR / NO. No inventa un precio justo cuando
no hay techo ``own_*`` ni ``af_*``. La puja de ``flip`` sigue siendo líder+1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import norm

from toolbox.analyzer import POSITIONS, candidates_from_squad, index_trends, own_squad
from toolbox.bidding import MIN_HEADCOUNT
from toolbox.league_history import RivalProfile, apply_league_clearing, clearing_quote


# Escala del codo en ``premium_b``. No es un suelo: una puja por debajo del
# valor de referencia (premium <= 0) deja ``P(win)`` en la rama de cola del
# logit, más alta pero estrictamente monótona. Elevarla a un mínimo constante
# devolvía a todos los rivales la misma probabilidad y colapsaba la curva.
PREMIUM_SCALE = 0.03
PREMIUM_PERSISTENCE = 0.05


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def bid_floor(listing: dict[str, Any]) -> int | None:
    """Suelo observable: valor, precio de venta y líder+1. Solo enteros del JSON."""
    parts: list[int] = []
    for key in ("market_value", "sale_price"):
        number = _int(listing.get(key))
        if number is not None:
            parts.append(number)
    leading = _int(listing.get("leading_bid"))
    if leading is not None:
        parts.append(leading + 1)
    if not parts:
        return None
    return max(parts)


def recommend_bid(
    listing: dict[str, Any],
    *,
    ideal: int | None,
    maximum: int | None,
    cash: int | None,
    snipe_status: str | None,
) -> dict[str, Any]:
    """Ideal ahora si no hay líder. Snipe con tope si ya hay líder y hay cierre.

    Un empate lo gana quien pujó antes. Sin líder, esperar al último segundo
    regala ese empate. Con líder por encima del ideal, no se persigue.
    """
    floor = bid_floor(listing)
    leading = _int(listing.get("leading_bid"))
    how = "unknown"
    amount: int | None = None
    reason = "sin_techo"

    if leading is None:
        if ideal is not None and floor is not None and ideal < floor:
            how, reason = "esperar", "suelo_sobre_ideal"
        elif (
            ideal is not None
            and isinstance(cash, int)
            and ideal <= cash
            and (floor is None or ideal >= floor)
            and (maximum is None or ideal <= maximum)
        ):
            how, amount, reason = "ahora", ideal, "empate_gana_la_primera"
        elif ideal is not None and isinstance(cash, int) and ideal > cash:
            how, reason = "esperar", "caja_insuficiente"
        elif ideal is None and floor is not None:
            how, amount, reason = "unknown", floor, "sin_techo"
    else:
        cap = leading + 1
        if ideal is not None and leading > ideal:
            how, reason = "esperar", "lider_supera_ideal"
        else:
            ceiling = maximum if maximum is not None else ideal
            if ceiling is None:
                how, amount, reason = "unknown", cap, "sin_techo"
            elif cap > ceiling:
                how, reason = "esperar", "sobreprecio"
            elif snipe_status in {"hidden", "inside_window"}:
                how, amount, reason = "snipe", min(ceiling, cap), "snipe_con_tope"
            else:
                how, amount, reason = "ahora", min(ceiling, cap), "puja_visible"

    return {
        "floor_eur": floor,
        "ideal_bid": ideal,
        "max_bid": maximum,
        "how": how,
        "recommended_bid_eur": amount,
        "reason": reason,
    }


def rival_snapshots(squads: dict[str, Any] | None, trends: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Caja observada y posiciones flojas. Sin caja, el campo queda ausente."""
    if not isinstance(squads, dict):
        return []
    indexed = index_trends(trends)
    own = own_squad(squads)
    own_id = own.get("team_id") if isinstance(own, dict) else None
    rows: list[dict[str, Any]] = []
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict) or squad.get("error"):
            continue
        if squad.get("is_self") is True:
            continue
        if isinstance(own_id, str) and squad.get("team_id") == own_id:
            continue
        roster = candidates_from_squad(squad, indexed)
        available = {position: 0 for position in POSITIONS}
        for candidate in roster:
            if candidate.eligible and candidate.position in available:
                available[candidate.position] += 1
        thin = [position for position in POSITIONS if available[position] <= MIN_HEADCOUNT[position]]
        cash = squad.get("cash") if isinstance(squad.get("cash"), int) and not isinstance(squad.get("cash"), bool) else None
        rows.append(
            {
                "team_id": squad.get("team_id"),
                "manager_name": squad.get("manager_name"),
                "cash_eur": cash,
                "thin_positions": thin,
            }
        )
    return rows


def overbid_risk(
    position: str | None,
    ideal: int | None,
    rivals: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Cuenta rivales con caja conocida que cubre el ideal y tienen esa posición floja.

    Si falta la caja de alguien y nadie conocido puede cubrir, el riesgo es
    ``unknown``. No se devuelve un porcentaje.
    """
    if not isinstance(ideal, int) or isinstance(ideal, bool) or not isinstance(position, str) or not position:
        return {"status": "unknown", "count": None, "reason": "sin_ideal"}
    roster = [row for row in rivals or [] if isinstance(row, dict)]
    if not roster:
        return {"status": "unknown", "count": None, "reason": "sin_rivales"}
    known = [row for row in roster if isinstance(row.get("cash_eur"), int) and not isinstance(row.get("cash_eur"), bool)]
    unknown_cash = len(roster) - len(known)
    able: list[str] = []
    for row in known:
        thin = row.get("thin_positions") if isinstance(row.get("thin_positions"), list) else []
        if position in thin and row["cash_eur"] >= ideal:
            team_id = row.get("team_id")
            able.append(team_id if isinstance(team_id, str) else "")
    if able:
        return {"status": "high", "count": len(able), "reason": "caja_y_hueco", "team_ids": [item for item in able if item]}
    if unknown_cash:
        return {"status": "unknown", "count": None, "reason": "caja_desconocida"}
    return {"status": "low", "count": 0, "reason": "nadie_cubre"}


def public_bids(listing: dict[str, Any], own_team_id: str | None) -> list[dict[str, Any]]:
    """Pujas ya registradas en el JSON del mercado. Las que aún no existen no se inventan."""
    raw = listing.get("bids")
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        amount = _int(item.get("amount"))
        if amount is None:
            continue
        team_id = item.get("team_id") if isinstance(item.get("team_id"), str) else None
        rows.append(
            {
                "amount": amount,
                "manager_name": item.get("manager_name") if isinstance(item.get("manager_name"), str) else None,
                "team_id": team_id,
                "own": bool(own_team_id and team_id == own_team_id),
            }
        )
    rows.sort(key=lambda row: (-row["amount"], row.get("manager_name") or "", row.get("team_id") or ""))
    return rows


def economic_bid(
    *,
    to_lead: int | None,
    leading: int | None,
    own_max: int | None,
    af_max: int | None,
    af_usable: bool,
    ideal: int | None,
    cash: int | None,
    snipe_status: str | None,
) -> dict[str, Any]:
    """Importe para llevártelo sin pasar el techo más bajo de las fuentes presentes.

    ``own_max`` y ``af_max`` solo entran si existen. AF no cuenta si el matching
    no es usable. Sin techo, la puja es solo la necesaria para ir primero.
    """
    caps: list[tuple[str, int]] = []
    own_cap = _int(own_max)
    af_cap = _int(af_max)
    if own_cap is not None:
        caps.append(("own", own_cap))
    if af_usable and af_cap is not None:
        caps.append(("af", af_cap))

    result: dict[str, Any] = {
        "value_ceiling": None,
        "value_ceiling_source": None,
        "aggressive_ceiling": None,
        "aggressive_ceiling_source": None,
        "suggested_bid": None,
        "raise_to": None,
        "bid_limit": "sin_puja",
    }
    if not isinstance(to_lead, int) or isinstance(to_lead, bool):
        return result

    if not caps:
        if isinstance(cash, int) and not isinstance(cash, bool) and to_lead > cash:
            result["bid_limit"] = "sin_caja"
            return result
        result["suggested_bid"] = to_lead
        result["bid_limit"] = "sin_techo"
        return result

    strict_src, strict = min(caps, key=lambda item: (item[1], item[0]))
    loose_src, loose = max(caps, key=lambda item: (item[1], item[0]))
    if len(caps) == 2 and strict == loose:
        result["value_ceiling_source"] = "own+af"
    else:
        result["value_ceiling_source"] = strict_src
    result["value_ceiling"] = strict
    if loose > strict:
        result["aggressive_ceiling"] = loose
        result["aggressive_ceiling_source"] = loose_src

    if to_lead > strict:
        result["bid_limit"] = "sobre_techo" if len(caps) == 1 or to_lead > loose else "fuentes_no_coinciden"
        return result

    ceiling = strict
    if isinstance(cash, int) and not isinstance(cash, bool):
        ceiling = min(ceiling, cash)
    if ceiling < to_lead:
        result["bid_limit"] = "sin_caja"
        return result

    has_leader = isinstance(leading, int) and not isinstance(leading, bool)
    schedulable = snipe_status in {"hidden", "inside_window"}
    if not has_leader:
        open_bid = to_lead
        ideal_bid = _int(ideal)
        if ideal_bid is not None and to_lead <= ideal_bid <= ceiling:
            open_bid = ideal_bid
        elif ideal_bid is not None and ideal_bid > ceiling:
            open_bid = ceiling
        result["suggested_bid"] = open_bid
        result["raise_to"] = ceiling if ceiling > open_bid else None
        result["bid_limit"] = "abrir"
        return result

    if schedulable:
        result["suggested_bid"] = ceiling
        result["bid_limit"] = "snipe_techo"
        return result

    result["suggested_bid"] = to_lead
    result["raise_to"] = ceiling if ceiling > to_lead else None
    result["bid_limit"] = "ir_primero"
    return result


@dataclass
class OptimalBidResult:
    intent: str
    intrinsic_valuation_eur: int
    optimal_bid_eur: int
    win_probability: float
    expected_surplus_eur: int
    rival_knockout_targets: list[str]
    decision: str


def _log_premium(premium_b: float) -> float:
    """``log(premium_b)`` suave en todo el dominio, sin suelo duro.

    Una puja posicionada en el valor de referencia (premium 0) o por debajo
    sigue empujando a los rivales hacia la cola agresiva, pero sin el salto
    discontinuo de un mínimo: la curva log-normal es continua y monótona.
    """
    return math.log(premium_b + math.sqrt(premium_b * premium_b + PREMIUM_SCALE**2) + PREMIUM_PERSISTENCE)


def probability_of_winning_bid(
    bid_eur: float,
    v_ref: float,
    min_legal_bid: float,
    position: str,
    expected_pts: float,
    rivals: list[RivalProfile],
    *,
    beta_liquidity: float = 0.18,
    beta_urgency: float = 0.25,
) -> float:
    """P(ganar | B) modelando participación rival y puja truncada por caja."""
    if bid_eur < min_legal_bid:
        return 0.0

    premium_b = (bid_eur - v_ref) / max(1.0, v_ref)
    log_prem_b = _log_premium(premium_b)
    p_win_all = 1.0

    for rv in rivals:
        if rv.cash_eur + 2.0 * rv.cash_uncertainty_eur < min_legal_bid and not rv.already_bidding:
            continue

        has_gap = 1.0 if position in rv.xi_gaps else 0.0
        is_thin = 1.0 if position in rv.thin_positions else 0.0
        no_rep = 1.0 if rv.lacks_replacements else 0.0
        urgency_level = 2.0 if has_gap else (1.0 if is_thin else 0.0)
        cash_ratio = max(0.05, rv.cash_eur / max(1.0, v_ref))

        if rv.already_bidding:
            theta_j = 1.0
        else:
            logit = (
                -2.20
                + 1.65 * has_gap
                + 0.95 * is_thin
                + 0.60 * no_rep
                + 0.22 * (expected_pts - 4.5)
                + 0.35 * math.log(cash_ratio)
            )
            theta_j = 1.0 / (1.0 + math.exp(-logit))

        liq_term = math.log(1.0 + cash_ratio)
        star_boost = 0.10 * max(0.0, expected_pts - 6.0)
        mu_ji = rv.alpha_aggressiveness + beta_liquidity * liq_term + beta_urgency * urgency_level + star_boost

        cdf_valuation = float(norm.cdf((log_prem_b - mu_ji) / rv.sigma_dispersion))
        cdf_budget_ceiling = float(norm.cdf((bid_eur - rv.cash_eur) / rv.cash_uncertainty_eur))
        f_j = 1.0 - (1.0 - cdf_valuation) * (1.0 - cdf_budget_ceiling)
        p_beat_rival = (1.0 - theta_j) + theta_j * f_j
        p_win_all *= p_beat_rival

    return float(np.clip(p_win_all, 0.0, 1.0))


def _apply_psychological_anti_cluster_nudge(raw_bid: float, max_budget: float) -> int:
    rounded_50k = math.ceil(raw_bid / 50_000.0) * 50_000.0
    if abs(rounded_50k - raw_bid) <= 12_000.0:
        cand = rounded_50k + 2_411.0
    else:
        cand = raw_bid + 1_109.0
    return int(min(max_budget, max(raw_bid, cand)))


def solve_optimal_bid_v2(
    market_value: float,
    sale_price: float,
    leading_bid: float,
    own_cash_eur: float,
    position: str,
    expected_pts: float,
    points_delta_xi: float,
    populates_empty_slot: bool,
    free_tier_peers_count: int,
    projected_daily_deltas: list[float],
    delta_volatility: float,
    rivals: list[RivalProfile],
    *,
    median_league_ppm: float = 0.45,
    planning_horizon_weeks: int = 6,
    value_ceiling: float | None = None,
) -> OptimalBidResult:
    """Puja óptima B* maximizando (V_val - B) * P(Win | B)."""
    v_ref = max(market_value, sale_price)
    min_legal_bid = max(sale_price, leading_bid + 1.0 if leading_bid > 0 else sale_price)

    if own_cash_eur < min_legal_bid:
        return OptimalBidResult("NONE", 0, 0, 0.0, 0, [], "NO")

    is_structural = populates_empty_slot or (points_delta_xi >= 0.45)
    h_days = min(len(projected_daily_deltas), 5)
    gamma = 0.82
    expected_capital_gain = sum((gamma**d) * projected_daily_deltas[d] for d in range(h_days))

    if not is_structural:
        intent = "FLIP"
        risk_penalty = 1.036 * delta_volatility * math.sqrt(max(1, h_days))
        lockup_cost = 0.004 * max(1, h_days) * market_value
        v_val = market_value + expected_capital_gain - risk_penalty - lockup_cost
        min_required_surplus = 120_000.0
        min_win_prob = 0.25
    else:
        intent = "STRUCTURAL"
        short_gain = sum((gamma**d) * projected_daily_deltas[d] for d in range(min(3, h_days)))
        v_terminal = market_value + short_gain
        scarcity_mult = (
            1.0
            + 0.85 * math.exp(-0.35 * max(0, free_tier_peers_count))
            + (0.50 if populates_empty_slot else 0.0)
        )
        avg_rival_cash = float(np.mean([r.cash_eur for r in rivals])) if rivals else own_cash_eur
        cash_abundance = float(np.clip(own_cash_eur / max(1_000_000.0, avg_rival_cash), 0.5, 2.0))
        shadow_ppm = max(0.20, median_league_ppm * (cash_abundance**-0.45))
        effective_delta_pts = max(points_delta_xi, expected_pts if populates_empty_slot else 0.5)
        structural_premium_eur = ((effective_delta_pts * planning_horizon_weeks) / shadow_ppm) * 1_000_000.0
        v_val = v_terminal + structural_premium_eur * scarcity_mult
        min_required_surplus = 50_000.0
        min_win_prob = 0.35

    upper_bound = min(own_cash_eur, v_val)
    if value_ceiling is not None:
        upper_bound = min(upper_bound, value_ceiling)
    if upper_bound <= min_legal_bid:
        return OptimalBidResult(intent, int(v_val), int(min_legal_bid), 0.0, 0, [], "ESPERAR")

    def neg_expected_utility(b: float) -> float:
        p_w = probability_of_winning_bid(b, v_ref, min_legal_bid, position, expected_pts, rivals)
        return -((v_val - b) * p_w)

    res = minimize_scalar(neg_expected_utility, bounds=(min_legal_bid, upper_bound), method="bounded")
    best_b = float(res.x)
    best_eu = -float(res.fun)

    # Los knockouts se evalúan todos contra el óptimo base, no encadenados: si
    # cada candidato se comparaba con el mejor anterior, un primer rival débil
    # subía el listón y el resto quedaba descartado sin evaluar su puja hasta
    # agotar su caja.
    knockouts: list[str] = []
    base_b = best_b
    base_eu = best_eu
    for rv in rivals:
        if position in rv.xi_gaps or position in rv.thin_positions or rv.already_bidding:
            ko_bid = rv.cash_eur + 3_500.0
            if min_legal_bid <= ko_bid <= upper_bound:
                eu_ko = -neg_expected_utility(ko_bid)
                if eu_ko >= base_eu * 0.97 and eu_ko > best_eu:
                    best_b = ko_bid
                    best_eu = eu_ko
                if eu_ko >= base_eu * 0.97:
                    knockouts.append(rv.manager_name)

    final_bid = _apply_psychological_anti_cluster_nudge(best_b, own_cash_eur)
    final_p_win = probability_of_winning_bid(final_bid, v_ref, min_legal_bid, position, expected_pts, rivals)
    expected_surplus = int(round((v_val - final_bid) * final_p_win))

    if expected_surplus >= min_required_surplus and final_p_win >= min_win_prob:
        decision = "PUJAR"
    elif v_val > min_legal_bid:
        decision = "ESPERAR"
    else:
        decision = "NO"

    return OptimalBidResult(
        intent=intent,
        intrinsic_valuation_eur=int(round(v_val)),
        optimal_bid_eur=final_bid,
        win_probability=round(final_p_win, 4),
        expected_surplus_eur=expected_surplus,
        rival_knockout_targets=knockouts,
        decision=decision,
    )


def profiles_for_listing(
    base_profiles: dict[str, RivalProfile],
    *,
    listing: dict[str, Any],
    own_team_id: str | None,
) -> list[RivalProfile]:
    """Actualiza already_bidding según pujas visibles en el listing."""
    bidding_teams = {
        row.get("team_id")
        for row in public_bids(listing, own_team_id)
        if isinstance(row, dict) and isinstance(row.get("team_id"), str) and not row.get("own")
    }
    return [
        replace(profile, already_bidding=profile.team_id in bidding_teams)
        for profile in base_profiles.values()
    ]


def rivals_state_for_auction(
    rivals: list[dict[str, Any]] | None,
    *,
    listing: dict[str, Any],
    own_team_id: str | None,
) -> list[dict[str, Any]]:
    """Enriquece filas de needs/rival_snapshots con flags de puja activa."""
    bidding_teams = {
        row.get("team_id")
        for row in public_bids(listing, own_team_id)
        if isinstance(row, dict) and isinstance(row.get("team_id"), str) and not row.get("own")
    }
    states: list[dict[str, Any]] = []
    for row in rivals or []:
        if not isinstance(row, dict):
            continue
        team_id = row.get("team_id")
        if not isinstance(team_id, str):
            continue
        item = dict(row)
        item["already_bidding"] = team_id in bidding_teams
        if "reconstructed_cash_eur" not in item:
            ledger = row.get("ledger")
            if isinstance(ledger, dict) and isinstance(ledger.get("reconstructed_cash_eur"), int):
                item["reconstructed_cash_eur"] = ledger["reconstructed_cash_eur"]
        states.append(item)
    return states


def _projected_deltas(trend: dict[str, Any], *, usable: bool) -> tuple[list[float], float]:
    own_pred = trend.get("own_predicted_delta")
    accel = trend.get("acceleration")
    af_pred = trend.get("af_predicted_delta") if usable else None
    daily = None
    for candidate in (own_pred, accel, af_pred):
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            continue
        daily = float(candidate)
        break
    if daily is None:
        daily = 0.0
    series = [daily] * 5
    vol = abs(daily) * 0.35 + 25_000.0
    return series, vol


def plan_market_auction_bid(
    listing: dict[str, Any],
    trend: dict[str, Any],
    *,
    to_lead: int | None,
    leading: int | None,
    own_max: int | None,
    af_max: int | None,
    af_usable: bool,
    ideal: int | None,
    cash: int | None,
    snipe_status: str | None,
    position: str | None,
    expected_pts: float | None,
    points_delta_xi: float | None,
    populates_empty_slot: bool,
    free_tier_peers_count: int,
    rivals: list[dict[str, Any]] | None,
    rival_profiles: list[RivalProfile] | None,
    own_team_id: str | None,
    history: dict[str, Any] | None,
) -> dict[str, Any]:
    """Puja operativa (suggested_bid) + métricas v2 (optimal_bid_eur, win_probability, …)."""
    caps = economic_bid(
        to_lead=to_lead,
        leading=leading,
        own_max=own_max,
        af_max=af_max,
        af_usable=af_usable,
        ideal=ideal,
        cash=cash,
        snipe_status=snipe_status,
    )
    sale = listing.get("sale_price") if isinstance(listing.get("sale_price"), int) else None
    if isinstance(sale, int):
        caps = apply_league_clearing(caps, clearing_quote(sale, history), to_lead=to_lead, cash=cash)

    pos = position if isinstance(position, str) and position else "MC"
    pts = float(expected_pts) if isinstance(expected_pts, (int, float)) and not isinstance(expected_pts, bool) else 5.0
    delta_xi = float(points_delta_xi) if isinstance(points_delta_xi, (int, float)) and not isinstance(points_delta_xi, bool) else 0.0
    market_value = listing.get("market_value") if isinstance(listing.get("market_value"), int) else sale or 0
    sale_price = float(sale or market_value or 0)
    mv = float(market_value or sale_price)
    lead = float(leading) if isinstance(leading, int) and not isinstance(leading, bool) else 0.0
    own_cash = float(cash) if isinstance(cash, int) and not isinstance(cash, bool) else 0.0
    projected, vol = _projected_deltas(trend, usable=af_usable)
    profiles = rival_profiles or []

    v2 = solve_optimal_bid_v2(
        market_value=mv,
        sale_price=sale_price,
        leading_bid=lead,
        own_cash_eur=own_cash,
        position=pos,
        expected_pts=pts,
        points_delta_xi=delta_xi,
        populates_empty_slot=populates_empty_slot,
        free_tier_peers_count=free_tier_peers_count,
        projected_daily_deltas=projected,
        delta_volatility=vol,
        rivals=profiles,
        value_ceiling=float(caps["value_ceiling"]) if isinstance(caps.get("value_ceiling"), int) else None,
    )

    caps["bid_intent"] = v2.intent
    caps["intrinsic_valuation_eur"] = v2.intrinsic_valuation_eur
    caps["optimal_bid_eur"] = v2.optimal_bid_eur if v2.optimal_bid_eur > 0 else None
    caps["win_probability"] = v2.win_probability if v2.optimal_bid_eur > 0 else None
    caps["expected_surplus_eur"] = v2.expected_surplus_eur if v2.optimal_bid_eur > 0 else None
    caps["rival_knockout_targets"] = v2.rival_knockout_targets
    caps["auction_decision"] = v2.decision

    if caps.get("suggested_bid") is not None and isinstance(v2.optimal_bid_eur, int) and v2.optimal_bid_eur > 0:
        ceiling = caps.get("value_ceiling")
        cap = float(ceiling) if isinstance(ceiling, int) else own_cash
        if isinstance(cash, int) and not isinstance(cash, bool):
            cap = min(cap, float(cash))
        merged = max(int(caps["suggested_bid"]), v2.optimal_bid_eur)
        if merged <= cap:
            caps["suggested_bid"] = merged
            caps["optimal_bid_eur"] = merged
            if caps.get("raise_to") is not None and isinstance(caps["raise_to"], int) and merged > caps["raise_to"]:
                caps["raise_to"] = merged

    return caps

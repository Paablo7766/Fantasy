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
from toolbox.bidding import URGENCIA_HUECO, URGENCIA_JUSTO, _depth, hidden_auction_count, urgencia_posicional
from toolbox.rival_intel import ROJO_SEGURO, estado_rojo
from toolbox.engine.auction_intel import techo_puja_dinamico
from toolbox.league_history import RivalProfile, apply_league_clearing, clearing_quote


# Escala del codo en ``premium_b``. No es un suelo: una puja por debajo del
# valor de referencia (premium <= 0) deja ``P(win)`` en la rama de cola del
# logit, más alta pero estrictamente monótona. Elevarla a un mínimo constante
# devolvía a todos los rivales la misma probabilidad y colapsaba la curva.
PREMIUM_SCALE = 0.03
PREMIUM_PERSISTENCE = 0.05
# Anchura (en prima relativa) con la que se suaviza el empate contra una puja a valor.
EXACT_BID_SMOOTH = 0.004

# Puja genérica al estilo de La Pizarra. El techo financiero es dinámico
# (prima +15 %, previsión a 7 días y dificultad) y nunca pasa del +30 %.
APP_BID_PREMIUM = 1.047
FINANCIAL_OVERBID_CAP = 1.30
# Las cifras de esta medida se expresan al décimo de millón (100 k€).
SMART_BID_STEP_EUR = 100_000
DEFAULT_SAFETY_MARGIN_EUR = 100_000


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
    hidden = hidden_auction_count(listing)
    how = "unknown"
    amount: int | None = None
    reason = "sin_techo"

    if leading is None and hidden > 0:
        # Hay gente dentro y LaLiga no dice cuánto. No eres el primero: el
        # precio de apertura pierde el empate y puede quedar por debajo.
        ceiling = maximum if maximum is not None else ideal
        if ceiling is None:
            how, amount, reason = "unknown", floor, "puja_oculta"
        elif isinstance(cash, int) and not isinstance(cash, bool) and ceiling > cash:
            how, reason = "esperar", "caja_insuficiente"
        elif floor is not None and ceiling < floor:
            how, reason = "esperar", "sobreprecio"
        elif snipe_status in {"hidden", "inside_window"}:
            how, amount, reason = "snipe", ceiling, "puja_oculta"
        else:
            how, amount, reason = "ahora", ceiling, "puja_oculta"
        return {
            "floor_eur": floor,
            "ideal_bid": ideal,
            "max_bid": maximum,
            "how": how,
            "recommended_bid_eur": amount,
            "reason": reason,
        }

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
        depth = _depth(candidates_from_squad(squad, indexed))
        urgencia = urgencia_posicional(depth)
        cash = squad.get("cash") if isinstance(squad.get("cash"), int) and not isinstance(squad.get("cash"), bool) else None
        rojo = estado_rojo(cash)
        legal = _legal_limit(cash, squad.get("debt_limit_eur"))
        rows.append(
            {
                "team_id": squad.get("team_id"),
                "manager_name": squad.get("manager_name"),
                "cash_eur": cash,
                "en_rojo": rojo,
                "en_rojo_seguro": rojo == ROJO_SEGURO,
                "bid_limit_eur": 0 if rojo else cash,
                "legal_bid_limit_eur": legal,
                # En rojo el tope global es 0. Solo el puesto con 0 sanos recupera el tope legal.
                "bid_limit_por_puesto": _bid_limit_por_puesto(depth, urgencia, legal) if rojo else None,
                "depth": depth,
                "urgencia": urgencia,
                "thin_positions": [position for position in POSITIONS if position in urgencia],
                "xi_gaps": [position for position in POSITIONS if urgencia.get(position) == URGENCIA_HUECO],
            }
        )
    return rows


def _bid_limit(row: dict[str, Any]) -> int | None:
    """Lo que el rival puede pujar: 0 en rojo, si no su caja."""
    for key in ("bid_limit_eur", "cash_eur"):
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _legal_limit(cash: int | None, debt: Any) -> int | None:
    """Caja más endeudamiento permitido. Sin caja no hay cota que dar."""
    if cash is None:
        return None
    extra = debt if isinstance(debt, int) and not isinstance(debt, bool) else 0
    return max(0, cash + max(0, extra))


def _bid_limit_por_puesto(
    depth: dict[str, int],
    urgencia: dict[str, str],
    legal: int | None,
) -> dict[str, int]:
    """En rojo, 0 en cada puesto salvo el hueco sin ningún sano, que conserva el tope legal."""
    techo = legal if isinstance(legal, int) and not isinstance(legal, bool) else 0
    return {
        position: techo if depth.get(position, 0) == 0 and urgencia.get(position) == URGENCIA_HUECO else 0
        for position in POSITIONS
    }


def _cero_sanos(row: dict[str, Any], position: str) -> bool:
    """Hueco de verdad: 0 sanos en ese puesto. Sin recuento, vale el hueco declarado."""
    if _urgencia_en(row, position) != URGENCIA_HUECO:
        return False
    depth = row.get("depth") if isinstance(row.get("depth"), dict) else None
    if depth is None or position not in depth:
        return True
    value = depth.get(position)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and int(value) == 0


def _rojo_leve_con_hueco(row: dict[str, Any], position: str, price: int | float) -> int | None:
    """Tope legal de un rival en rojo que aun así puja por cubrir un hueco.

    En rojo (su tope legal supera el precio) y con 0 sanos justo en este
    puesto, puja hoy a crédito y vende el jueves: su ``bid_limit`` de ese
    puesto es el tope legal. En el resto de puestos se queda en 0.
    """
    if not row.get("en_rojo") or not _cero_sanos(row, position):
        return None
    por_puesto = row.get("bid_limit_por_puesto") if isinstance(row.get("bid_limit_por_puesto"), dict) else None
    legal = por_puesto.get(position) if por_puesto is not None and position in por_puesto else row.get("legal_bid_limit_eur")
    if isinstance(legal, bool) or not isinstance(legal, (int, float)) or legal <= price:
        return None
    return int(legal)


def _urgencia_en(row: dict[str, Any], position: str) -> str | None:
    urgencia = row.get("urgencia") if isinstance(row.get("urgencia"), dict) else None
    if urgencia is not None:
        value = urgencia.get(position)
        return value if value in {URGENCIA_HUECO, URGENCIA_JUSTO} else None
    gaps = row.get("xi_gaps") if isinstance(row.get("xi_gaps"), list) else []
    if position in gaps:
        return URGENCIA_HUECO
    thin = row.get("thin_positions") if isinstance(row.get("thin_positions"), list) else []
    return URGENCIA_JUSTO if position in thin else None


def overbid_risk(
    position: str | None,
    ideal: int | None,
    rivals: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Rivales que necesitan la posición y pueden pagar el ideal.

    ``guerra``: alguien tiene un hueco ahí (sin fichar no forma 11) y caja
    para el ideal. ``high``: alguien va justo en esa línea y tiene caja.
    ``low``: quien necesita la posición no puede pagarla o nadie la necesita.
    Un rival en rojo no puja, salvo que tenga 0 sanos en ese puesto y su tope
    legal supere el precio: entonces puja a crédito. Si falta la caja de
    alguien y nadie conocido puede cubrir, el riesgo es ``unknown``. No se
    devuelve un porcentaje.
    """
    if not isinstance(ideal, int) or isinstance(ideal, bool) or not isinstance(position, str) or not position:
        return {"status": "unknown", "count": None, "reason": "sin_ideal"}
    roster = [row for row in rivals or [] if isinstance(row, dict)]
    if not roster:
        return {"status": "unknown", "count": None, "reason": "sin_rivales"}
    known = [row for row in roster if _bid_limit(row) is not None]
    unknown_cash = len(roster) - len(known)
    hueco: list[dict[str, Any]] = []
    justo: list[dict[str, Any]] = []
    sin_caja: list[str] = []
    for row in known:
        urgencia = _urgencia_en(row, position)
        if urgencia is None:
            continue
        limite = _rojo_leve_con_hueco(row, position, ideal) or _bid_limit(row) or 0
        if limite < ideal:
            sin_caja.append(_rival_name(row))
            continue
        (hueco if urgencia == URGENCIA_HUECO else justo).append(row)
    able = [*hueco, *justo]
    base = {
        "rivales_hueco": [_rival_name(row) for row in hueco],
        "rivales_justo": [_rival_name(row) for row in justo],
        "rivales_sin_caja": sin_caja,
    }
    if able:
        team_ids = [row.get("team_id") for row in able if isinstance(row.get("team_id"), str)]
        if hueco:
            nombres = ", ".join(base["rivales_hueco"])
            verbo = "necesita" if len(hueco) == 1 else "necesitan"
            return {
                **base,
                "status": "guerra",
                "count": len(able),
                "reason": "hueco_y_caja",
                "team_ids": team_ids,
                "etiqueta": f"Habrá guerra de pujas: {nombres} {verbo} cubrir este puesto",
            }
        return {
            **base,
            "status": "high",
            "count": len(able),
            "reason": "caja_y_hueco",
            "team_ids": team_ids,
            "etiqueta": f"Competencia: {', '.join(base['rivales_justo'])} {'van' if len(justo) > 1 else 'va'} justo en este puesto",
        }
    if unknown_cash:
        return {**base, "status": "unknown", "count": None, "reason": "caja_desconocida"}
    return {
        **base,
        "status": "low",
        "count": 0,
        "reason": "nadie_cubre",
        "etiqueta": "Sin competencia: ningún rival necesita este puesto"
        if not sin_caja
        else "Sin competencia: quien lo necesita no tiene caja",
    }


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
    hidden_bids: int = 0,
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
        result["bid_limit"] = "puja_oculta" if hidden_bids > 0 else "sin_techo"
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
    if not has_leader and hidden_bids > 0:
        # El líder existe pero su cifra no. Para no quedarte corto se puja el
        # tope: leader+1 no se puede calcular.
        result["suggested_bid"] = ceiling
        result["bid_limit"] = "snipe_techo" if schedulable else "puja_oculta"
        return result
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
        # Rojo con 0 sanos en este puesto: puja a crédito y vende después.
        # Sin recuento de sanos, el hueco declarado sigue valiendo.
        huecos_credito = rv.xi_gaps
        if rv.cero_sanos is not None:
            huecos_credito = [puesto for puesto in rv.xi_gaps if puesto in rv.cero_sanos]
        credito = (
            rv.legal_bid_limit_eur
            if rv.en_rojo and position in huecos_credito and rv.legal_bid_limit_eur is not None
            and rv.legal_bid_limit_eur > min_legal_bid
            else None
        )
        if rv.en_rojo and not rv.already_bidding and credito is None:
            continue
        caja = max(rv.cash_eur, credito or 0.0)
        if caja + 2.0 * rv.cash_uncertainty_eur < min_legal_bid and not rv.already_bidding:
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

        cdf_overbid = float(norm.cdf((log_prem_b - mu_ji) / rv.sigma_dispersion))
        # Hurdle: con probabilidad ``p_exact`` el rival puja a valor de mercado, sin
        # prima de riesgo; solo el resto sigue la curva de sobrepuja.
        cdf_exact = float(norm.cdf((premium_b - rv.exact_premium) / EXACT_BID_SMOOTH))
        cdf_valuation = rv.p_exact * cdf_exact + (1.0 - rv.p_exact) * cdf_overbid
        cdf_budget_ceiling = float(norm.cdf((bid_eur - caja) / rv.cash_uncertainty_eur))
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
    profiles = [
        replace(profile, already_bidding=profile.team_id in bidding_teams)
        for profile in base_profiles.values()
    ]
    if bidding_teams:
        return profiles
    hidden = hidden_auction_count(listing)
    if hidden <= 0:
        return profiles
    # Alguien ya pujó y la API no dice quién. Los rivales con más motivos
    # para estar dentro se tratan como comprometidos, hasta cubrir el recuento.
    position = listing.get("position") if isinstance(listing.get("position"), str) else None
    ranked = sorted(profiles, key=lambda profile: _commit_rank(profile, position), reverse=True)
    able = [profile for profile in ranked if profile.cash_eur > 0 or (profile.legal_bid_limit_eur or 0) > 0]
    chosen = {profile.team_id for profile in able[:hidden]}
    if not chosen:
        return profiles
    return [replace(profile, already_bidding=profile.team_id in chosen) for profile in profiles]


def _commit_rank(profile: RivalProfile, position: str | None) -> tuple[int, int, float, float]:
    gap = 1 if position and position in profile.xi_gaps else 0
    thin = 1 if position and position in profile.thin_positions else 0
    return (gap, thin, profile.cash_eur, profile.alpha_aggressiveness)


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


def _round_tenth_million(amount: float) -> int:
    """Redondeo al décimo de millón, el mismo grano que ``round(millones, 1)``."""
    return int(round(amount / SMART_BID_STEP_EUR) * SMART_BID_STEP_EUR)


def _within_cash(amount: int, cash: float) -> int:
    """Una puja recomendada no puede dejar la caja en negativo."""
    if cash <= 0:
        return 0
    if amount <= cash:
        return amount
    floored = int(math.floor(cash / SMART_BID_STEP_EUR) * SMART_BID_STEP_EUR)
    return floored if floored > 0 else int(cash)


def _rival_cash(rival: dict[str, Any]) -> float | None:
    for key in ("dineroEstimado", "bid_limit_eur", "cash_eur", "reconstructed_cash_eur"):
        value = rival.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        return float(value)
    return None


def _weak_positions(rival: dict[str, Any]) -> set[str]:
    positions: set[str] = set()
    for key in ("posiciones_debiles", "thin_positions", "xi_gaps"):
        raw = rival.get(key)
        if not isinstance(raw, list):
            continue
        positions.update(item for item in raw if isinstance(item, str) and item)
    return positions


def _rival_name(rival: dict[str, Any]) -> str:
    for key in ("nombre", "manager_name", "team_id"):
        value = rival.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "rival"


def _dificultad_de(jugador: dict[str, Any]) -> str | None:
    for key in ("dificultad", "difficulty", "calendar_difficulty"):
        value = jugador.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    fixture = jugador.get("fixture")
    if isinstance(fixture, dict):
        value = fixture.get("difficulty")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _dificultad_calendario(trend: dict[str, Any]) -> str | None:
    for key in ("own_calendar", "af_calendar"):
        calendar = trend.get(key)
        if not isinstance(calendar, list) or not calendar or not isinstance(calendar[0], dict):
            continue
        value = calendar[0].get("difficulty")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _prevision_de(jugador: dict[str, Any]) -> Any:
    for key in ("prevision_7d_pct", "pct"):
        if jugador.get(key) is not None:
            return jugador.get(key)
    return None


def calcular_puja_optima(
    jugador: dict[str, Any],
    rivales: list[dict[str, Any]],
    tu_saldo: float,
    margen_seguridad: float = DEFAULT_SAFETY_MARGIN_EUR,
) -> dict[str, Any]:
    """Puja smart: base +4,7 %, techo dinámico y knockout de la caja rival.

    Un rival cuenta si tiene saldo positivo, cubre el valor de mercado y
    necesita la posición (hueco de titular o línea floja). Si nadie llega,
    se puja la base. Si alguien llega, se supera su saldo en el margen
    siempre que eso no pase del techo dinámico ni de la caja propia.
    El techo es ``valor × (1,15 + 0,55·previsión_7d + bono de partido)``
    y nunca supera el +30 %.
    """
    raw_value = jugador.get("valor", jugador.get("market_value"))
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or raw_value <= 0:
        return {
            "puja_base_app": None,
            "puja_maxima": None,
            "puja_smart": None,
            "probabilidad_exito": None,
            "analisis": "Sin valor de mercado para calcular la puja.",
            "rivales_peligrosos": [],
        }

    valor_mercado = float(raw_value)
    posicion = jugador.get("posicion", jugador.get("position"))
    posicion = posicion if isinstance(posicion, str) else ""
    saldo = float(tu_saldo) if isinstance(tu_saldo, (int, float)) and not isinstance(tu_saldo, bool) else 0.0
    margen = float(margen_seguridad) if isinstance(margen_seguridad, (int, float)) and not isinstance(margen_seguridad, bool) else DEFAULT_SAFETY_MARGIN_EUR

    puja_base_app = _round_tenth_million(valor_mercado * APP_BID_PREMIUM)
    puja_max_financiera = techo_puja_dinamico(
        valor_mercado,
        _prevision_de(jugador),
        _dificultad_de(jugador),
        paso=SMART_BID_STEP_EUR,
    )

    rivales_peligrosos: list[str] = []
    max_saldo_rival_interesado = 0.0
    for rival in rivales:
        if not isinstance(rival, dict):
            continue
        saldo_rival = _rival_cash(rival)
        if saldo_rival is None or saldo_rival <= 0:
            continue
        necesita_posicion = bool(posicion) and posicion in _weak_positions(rival)
        if necesita_posicion and saldo_rival >= valor_mercado:
            rivales_peligrosos.append(_rival_name(rival))
            if saldo_rival > max_saldo_rival_interesado:
                max_saldo_rival_interesado = saldo_rival

    if not rivales_peligrosos:
        objetivo = _round_tenth_million(max(valor_mercado + DEFAULT_SAFETY_MARGIN_EUR, float(puja_base_app)))
        puja_smart = _within_cash(objetivo, saldo)
        if puja_smart <= 0:
            probabilidad = 0
            motivo = "Sin caja para la puja base."
        elif puja_smart < objetivo:
            probabilidad = 20
            motivo = "All-in. La puja base supera tu saldo y ningún rival necesita la posición."
        else:
            probabilidad = 95
            motivo = "Ningún rival tiene saldo o necesidad crítica en esta posición."
    else:
        puja_necesaria = max_saldo_rival_interesado + margen
        puja_necesaria_redondeada = _round_tenth_million(puja_necesaria)
        if puja_necesaria_redondeada <= max_saldo_rival_interesado:
            puja_necesaria_redondeada += SMART_BID_STEP_EUR
        nombres = ", ".join(rivales_peligrosos)
        saldo_txt = f"{max_saldo_rival_interesado / 1_000_000:.1f}"
        if saldo >= puja_necesaria_redondeada:
            if puja_necesaria_redondeada <= puja_max_financiera:
                puja_smart = puja_necesaria_redondeada
                probabilidad = 99
                motivo = f"Supera el saldo máximo de {nombres} ({saldo_txt}M)."
            else:
                puja_smart = _within_cash(puja_max_financiera, saldo)
                probabilidad = 40
                motivo = (
                    f"Riesgo de sobrepuja. {nombres} tienen más dinero ({saldo_txt}M) "
                    "que el valor sensato del jugador."
                )
        else:
            puja_smart = _within_cash(int(saldo), saldo)
            probabilidad = 20 if puja_smart > 0 else 0
            motivo = f"All-in. Tienes menos saldo que {nombres}."

    return {
        "puja_base_app": puja_base_app,
        "puja_maxima": puja_max_financiera,
        "puja_smart": int(puja_smart) if puja_smart else None,
        "probabilidad_exito": probabilidad,
        "analisis": motivo,
        "rivales_peligrosos": rivales_peligrosos,
    }


def _rivals_for_smart_bid(
    profiles: list[RivalProfile],
    rivals: list[dict[str, Any]] | None,
    position: str,
) -> list[dict[str, Any]]:
    """Adapta perfiles o snapshots al contrato de ``calcular_puja_optima``."""
    if profiles:
        rows: list[dict[str, Any]] = []
        for profile in profiles:
            weak = [*profile.thin_positions, *profile.xi_gaps]
            if profile.already_bidding and position:
                weak.append(position)
            rows.append(
                {
                    "nombre": profile.manager_name or profile.team_id,
                    "dineroEstimado": profile.cash_eur,
                    "posiciones_debiles": weak,
                }
            )
        return rows
    adapted: list[dict[str, Any]] = []
    for row in rivals or []:
        if not isinstance(row, dict):
            continue
        weak = list(_weak_positions(row))
        if row.get("already_bidding") is True and position:
            weak.append(position)
        adapted.append(
            {
                "nombre": _rival_name(row),
                "dineroEstimado": _rival_cash(row),
                "posiciones_debiles": weak,
            }
        )
    return adapted


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
    hidden = hidden_auction_count(listing)
    caps = economic_bid(
        to_lead=to_lead,
        leading=leading,
        own_max=own_max,
        af_max=af_max,
        af_usable=af_usable,
        ideal=ideal,
        cash=cash,
        snipe_status=snipe_status,
        hidden_bids=hidden,
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

    smart = calcular_puja_optima(
        {
            "valor": mv,
            "posicion": pos,
            "prevision_7d_pct": _prevision_de(listing) if _prevision_de(listing) is not None else _prevision_de(trend),
            "dificultad": _dificultad_de(listing) or _dificultad_de(trend) or _dificultad_calendario(trend),
        },
        _rivals_for_smart_bid(profiles, rivals, pos),
        own_cash,
    )
    caps["app_bid_eur"] = smart["puja_base_app"]
    caps["financial_max_bid_eur"] = smart["puja_maxima"]
    caps["smart_bid_eur"] = smart["puja_smart"]
    # La regla de calcular_puja_optima da porcentajes fijos (0/20/40/95/99).
    # La tarjeta enseña la puja smart con su probabilidad: con perfiles de
    # rivales se mide esa misma puja con el modelo de P(ganar), el que se
    # calibra en el Laboratorio. La regla queda como referencia.
    caps["smart_bid_rule_pct"] = smart["probabilidad_exito"]
    caps["smart_bid_success_pct"] = smart["probabilidad_exito"]
    if hidden > 0:
        # La puja de apertura asume que eres el primero. Con gente ya dentro
        # y el importe oculto, la cifra que se enseña es el tope financiero.
        ceiling_eur = caps.get("financial_max_bid_eur")
        current = caps.get("smart_bid_eur")
        if isinstance(ceiling_eur, int) and isinstance(current, int) and current < ceiling_eur:
            raised = _within_cash(ceiling_eur, own_cash)
            if raised > current:
                caps["smart_bid_eur"] = raised
        if lead <= 0 and sale_price > 0:
            lead = sale_price
    smart_bid = caps.get("smart_bid_eur")
    if profiles and isinstance(smart_bid, int) and not isinstance(smart_bid, bool) and smart_bid > 0:
        min_legal = max(sale_price, lead + 1.0 if lead > 0 else sale_price)
        caps["smart_bid_success_pct"] = int(
            round(100.0 * probability_of_winning_bid(float(smart_bid), max(mv, sale_price), min_legal, pos, pts, profiles))
        )
    caps["smart_bid_analysis"] = smart["analisis"]
    if hidden > 0:
        offers = listing.get("offer_count")
        bids_only = listing.get("bid_count")
        noun = "oferta" if isinstance(offers, int) and offers > 0 and not (isinstance(bids_only, int) and bids_only > 0) else "puja"
        label = f"1 {noun}" if hidden == 1 else f"{hidden} {noun}s"
        caps["smart_bid_analysis"] = f"Hay {label} y LaLiga no publica el importe. {caps['smart_bid_analysis'] or ''}".strip()
    caps["smart_bid_rivals"] = smart["rivales_peligrosos"]

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

    # P(ganar) de la puja que se recomienda de verdad. La de v2 es la de su
    # óptimo, y cuando v2 no encuentra hueco vale 0 aunque haya puja sugerida:
    # salían PUJAR con un 0 % que no medía esa puja.
    final_bid = caps.get("suggested_bid")
    if isinstance(final_bid, int) and not isinstance(final_bid, bool) and final_bid > 0:
        min_legal = max(sale_price, lead + 1.0 if lead > 0 else sale_price)
        caps["win_probability"] = round(
            probability_of_winning_bid(float(final_bid), max(mv, sale_price), min_legal, pos, pts, profiles),
            4,
        )

    return caps

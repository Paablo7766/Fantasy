"""E[pts] de jornada.

Los puntos que se publican salen de la serie fantasy del jugador (titular
contra revulsivo, contracción al prior del puesto y rival). El bloque de
eventos solo alimenta P(gol) y P(asistencia).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.special import gammainc
from scipy.stats import norm

from toolbox.engine.xp2 import prediccion_xp2, prob_titular_portero
from toolbox.rival_posicional import ajuste_rival_posicional
from toolbox.engine.xp_calculator import predecir_desde_jugador

GOAL_PTS = {"POR": 6.0, "DEF": 6.0, "MC": 5.0, "DEL": 4.0}
UEFA_FATIGUE_RHO = {"POR": 0.02, "DEF": 0.14, "MC": 0.18, "DEL": 0.16}
PROBIT_THRESHOLDS = np.array([6.75, 7.10, 7.45, 7.90], dtype=np.float64)
MC_SIMS_DEFAULT = 4000


SPARSE_MINUTES = 45.0
#: Ritmo máximo plausible por 90'. Ningún jugador sostiene más de un gol por
#: 90' con volumen real; sin techo, 30' jugados con un gol de suerte devolvían
#: una tasa mayor que la de un delantero titular de la liga.
RATE_PER90_CEILING = 2.5


def rate_per90(raw: float, minutes: float, *, sparse_cap: float = 1.25) -> float:
    """Pasa totales de temporada (Understat/FBref) a ritmo por 90'.

    ``sparse_cap`` solo acota cuanto más pequeño es el ritmo por 90' si la
    muestra está por debajo de ``SPARSE_MINUTES``. En cuanto la muestra llega
    al umbral, el tope pasa a ser ``RATE_PER90_CEILING``: nunca se deja una
    tasa en cero por haber jugado un rato más de 45'.
    """
    if raw <= 0:
        return 0.0
    ceiling = max(sparse_cap, RATE_PER90_CEILING) if minutes >= SPARSE_MINUTES else sparse_cap
    per90 = raw / max(1.0, minutes / 90.0)
    return min(per90, ceiling)


def _p_titular_value(raw: Any, default: float = 0.5) -> float:
    """``p_titular`` del scraper sin colapsar el ``0.0`` legítimo.

    Un ``0.0`` explícito (banquillo/no elegible) se respeta; solo la ausencia
    del dato, un ``None`` o un ``NaN`` caen al valor por defecto.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    value = float(raw)
    if math.isnan(value) or math.isinf(value):
        return default
    return value


def poisson_step_expectation(mu: float, k: int, max_steps: int = 6) -> float:
    """E[floor(X / k)] para X ~ Poisson(mu) vía ``gammainc``."""
    if mu <= 1e-6 or k <= 0:
        return 0.0
    m_vals = np.arange(1, max_steps + 1, dtype=np.float64) * k
    return float(np.sum(gammainc(m_vals, mu)))


def infer_opta_performance_bonus(
    avg_rating: float,
    lambda_own: float,
    lambda_opp: float,
    key_passes_90: float,
    duels_won_90: float,
    p_start_eff: float,
    p_sub_eff: float,
) -> float:
    """Bonus Relevo / valoración OPTA (0–4) con Ordered Probit."""
    mu_r = (
        avg_rating
        + 0.14 * (lambda_own - lambda_opp)
        + 0.06 * (key_passes_90 - 1.0)
        + 0.03 * (duels_won_90 - 4.0)
    )
    sigma_r = 0.42
    p_exceed_start = 1.0 - norm.cdf((PROBIT_THRESHOLDS - mu_r) / sigma_r)
    p_exceed_sub = 1.0 - norm.cdf((PROBIT_THRESHOLDS - (mu_r - 0.35)) / sigma_r)
    e_bonus_start = float(np.sum(p_exceed_start))
    e_bonus_sub = float(np.sum(p_exceed_sub))
    return p_start_eff * e_bonus_start + p_sub_eff * e_bonus_sub


def _player_ineligible(player: dict[str, Any]) -> bool:
    from toolbox.normalize import titularity_overrides_injury

    status = str(player.get("player_status") or "ok").lower()
    sanction = player.get("sanction") if isinstance(player.get("sanction"), dict) else {}
    fitness = player.get("fitness")
    if isinstance(fitness, str) and any(token in fitness.lower() for token in ("lesion", "injured", "baja", "out")):
        if not titularity_overrides_injury(
            player.get("p_titular"),
            source=player.get("p_titular_source") if isinstance(player.get("p_titular_source"), str) else None,
            lineup_status=player.get("lineup_status") if isinstance(player.get("lineup_status"), str) else None,
        ):
            return True
    if status in {"injured", "suspended", "out", "lesionado", "baja"}:
        if status in {"suspended"}:
            return True
        if not titularity_overrides_injury(
            player.get("p_titular"),
            source=player.get("p_titular_source") if isinstance(player.get("p_titular_source"), str) else None,
            lineup_status=player.get("lineup_status") if isinstance(player.get("lineup_status"), str) else None,
        ):
            return True
    if sanction.get("suspended") or player.get("af_suspension"):
        return True
    return False


def _empty_result() -> dict[str, float]:
    return {
        "expected_points": 0.0,
        "ceiling_points": 0.0,
        "p_start_eff": 0.0,
        "expected_minutes": 0.0,
        "inferred_bonus": 0.0,
        "next_match_survival": 1.0,
        "goal_probability": 0.0,
        "assist_probability": 0.0,
    }


def compute_expected_opta_points_v2(
    player: dict[str, Any],
    *,
    lambda_own: float = 1.35,
    lambda_opp: float = 1.25,
    p_cs_own: float | None = None,
    has_midweek_cup: bool = False,
    days_rest: int = 6,
    run_monte_carlo: bool = True,
    n_sims: int = MC_SIMS_DEFAULT,
) -> dict[str, float]:
    """Valor de jornada, puntos si sale de inicio y techo.

    ``run_monte_carlo`` y ``n_sims`` se conservan para quien ya llama con
    ellos. El techo ya no sale de una simulación: es la proyección de
    titular más la volatilidad de sus puntos.
    """
    if _player_ineligible(player):
        return _empty_result()

    pos = str(player.get("position") or "MC").upper()
    if pos not in GOAL_PTS:
        pos = "MC"

    form = player.get("form") if isinstance(player.get("form"), dict) else {}
    sanction = player.get("sanction") if isinstance(player.get("sanction"), dict) else {}
    p_titular_raw = _p_titular_value(player.get("p_titular"))
    if p_titular_raw > 1.0:
        p_titular_raw /= 100.0
    on_verge = bool(sanction.get("on_verge", False))

    rho_fatigue = UEFA_FATIGUE_RHO[pos]
    cup_penalty = (
        rho_fatigue * math.exp(-0.45 * max(0, days_rest - 2))
        if has_midweek_cup and days_rest <= 4
        else 0.0
    )
    p_start_eff = float(np.clip(p_titular_raw * (1.0 - cup_penalty), 0.0, 1.0))
    # Portero: el último partido decide (suplente 0,03 / titular 0,95).
    p_start_eff = float(np.clip(prob_titular_portero(player, p_start_eff), 0.0, 1.0))

    minutes_total = float(form.get("minutes") or 0.0)
    starts_count = float(form.get("starts") or 0.0)
    minutes_pct = float(form.get("minutes_pct") or p_titular_raw)

    if pos == "POR":
        p_sub_eff = 0.0
        mu_m_start = 90.0
        eff_m_start = mu_m_start
    else:
        p_sub_eff = (1.0 - p_start_eff) * float(np.clip(0.65 * p_titular_raw + 0.25 * minutes_pct, 0.0, 0.75))
        raw_m_start = (minutes_total / starts_count) if starts_count >= 2 else (68.0 + 18.0 * minutes_pct)
        mu_m_start = float(np.clip(raw_m_start, 55.0, 90.0))
        # ``on_verge`` (tarjetas) recorta los minutos esperados una sola vez.
        eff_m_start = mu_m_start - (4.5 if on_verge else 0.0)

    expected_minutes = p_start_eff * eff_m_start + p_sub_eff * 22.0
    tau = expected_minutes / 90.0
    if tau <= 0.01:
        out = _empty_result()
        return out

    raw_xg = float(form.get("xg") or 0.0)
    raw_xa = float(form.get("xa") or 0.0)
    xg_90 = rate_per90(raw_xg, minutes_total)
    xa_90 = rate_per90(raw_xa, minutes_total)
    phi_atk = float(np.clip(lambda_own / 1.32, 0.45, 2.40))
    phi_def = float(np.clip(lambda_opp / 1.32, 0.45, 2.40))

    fantasy = predecir_desde_jugador(
        player,
        prob_titular=p_start_eff,
        lambda_favor=lambda_own,
        lambda_contra=lambda_opp,
        prob_clean_sheet=p_cs_own,
    )
    xp_pizarra = float(fantasy["xp_pizarra"])
    xp_condicional = float(fantasy["xp_condicional"])
    techo = float(fantasy["techo"])
    # xP 2.0 (suelo + gol + asistencia + portería) para quien tiene actas
    # desglosadas. Sin ellas (fichajes del mercado) queda la fórmula de respaldo.
    xp2 = prediccion_xp2(
        player,
        prob_titular=p_start_eff,
        lambda_favor=lambda_own,
        lambda_contra=lambda_opp,
        prob_porteria_cero=p_cs_own,
        ajuste_rival=ajuste_rival_posicional(player.get("rival"), pos),
    )
    if xp2 is not None:
        volatilidad = techo - xp_condicional
        xp_pizarra = float(xp2["xp"])
        xp_condicional = float(xp2["xp_condicional"])
        techo = xp_condicional + max(0.0, volatilidad)
    jp_mult = float(form.get("jp_multiplier") or 1.0)
    if jp_mult != 1.0:
        jp_scale = 1.0 + 0.35 * (jp_mult - 1.0)
        xp_pizarra *= jp_scale
        xp_condicional *= jp_scale
        techo *= jp_scale

    play_mass = max(1e-4, p_start_eff + p_sub_eff)
    p_goal = (1.0 - math.exp(-max(0.0, xg_90 * phi_atk * tau / play_mass))) * play_mass
    p_assist = (1.0 - math.exp(-max(0.0, xa_90 * phi_atk * tau / play_mass))) * play_mass

    p_yc_base = {"POR": 0.04, "DEF": 0.22, "MC": 0.19, "DEL": 0.12}[pos]
    p_yc = float(np.clip(p_yc_base * (phi_def**0.3) * tau, 0.02, 0.45))
    next_match_survival = 1.0 - (p_start_eff * p_yc) if on_verge else 1.0

    salida = {
        "expected_points": round(max(0.0, xp_pizarra), 3),
        "ceiling_points": round(max(xp_pizarra, techo), 2),
        "xp_condicional": round(xp_condicional, 2),
        "xp_pizarra": round(max(0.0, xp_pizarra), 3),
        "base_titular": fantasy["base_titular"],
        "factor_partido": fantasy["factor_partido"],
        "n_titular": fantasy["n_titular"],
        "prob_clean_sheet": fantasy["prob_clean_sheet"],
        "p_start_eff": round(p_start_eff, 4),
        "expected_minutes": round(expected_minutes, 1),
        "next_match_survival": round(next_match_survival, 4),
        "goal_probability": round(float(np.clip(p_goal, 0.0, 1.0)), 4),
        "assist_probability": round(float(np.clip(p_assist, 0.0, 1.0)), 4),
        "xp_modelo": "2.0" if xp2 is not None else "respaldo",
    }
    if xp2 is not None:
        salida["xp_desglose"] = {
            "suelo": xp2["suelo"],
            "gol": xp2["gol"],
            "asistencia": xp2["asistencia"],
            "porteria": xp2["porteria"],
        }
        salida["xp_breakout"] = xp2["breakout"]
        salida["xp_balon_parado"] = xp2["balon_parado"]
        salida["xp_ajuste_rival"] = xp2.get("ajuste_rival_posicional")
        salida["xp_ajuste_club"] = xp2.get("ajuste_club")
        salida["xp_cambio_cronico"] = xp2.get("cambio_cronico")
        salida["xp_produccion_pura_90"] = xp2.get("produccion_pura_90")
        salida["xp_suelo_muro"] = xp2.get("suelo_muro")
    return salida

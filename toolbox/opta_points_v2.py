"""Motor E[Pts] OPTA v2.0: escalones Poisson, Ordered Probit y Monte Carlo."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.special import gammainc
from scipy.stats import norm

GOAL_PTS = {"POR": 6.0, "DEF": 6.0, "MC": 5.0, "DEL": 4.0}
CS_PTS = {"POR": 4.0, "DEF": 3.0, "MC": 2.0, "DEL": 1.0}
GC_PTS_PER_2 = {"POR": -2.0, "DEF": -2.0, "MC": -1.0, "DEL": -1.0}
LOSS_DIVISOR = {"POR": 8, "DEF": 8, "MC": 10, "DEL": 12}
BASE_LOSSES_90 = {"POR": 5.2, "DEF": 9.8, "MC": 11.4, "DEL": 10.6}
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
    """E[Pts] determinista + techo P90 (Monte Carlo vectorizado)."""
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

    minutes_total = float(form.get("minutes") or 0.0)
    starts_count = float(form.get("starts") or 0.0)
    minutes_pct = float(form.get("minutes_pct") or p_titular_raw)

    if pos == "POR":
        p_sub_eff = 0.0
        mu_m_start = 90.0
        eff_m_start = mu_m_start
        p_60_given_start = 0.985
    else:
        p_sub_eff = (1.0 - p_start_eff) * float(np.clip(0.65 * p_titular_raw + 0.25 * minutes_pct, 0.0, 0.75))
        raw_m_start = (minutes_total / starts_count) if starts_count >= 2 else (68.0 + 18.0 * minutes_pct)
        mu_m_start = float(np.clip(raw_m_start, 55.0, 90.0))
        # ``on_verge`` (tarjetas) recorta los minutos de una sola vez aquí: el
        # ajuste se propaga a ``expected_minutes`` y a ``p_60_given_start`` sin
        # restarse otra vez en cada fórmula.
        eff_m_start = mu_m_start - (4.5 if on_verge else 0.0)
        p_60_given_start = float(norm.cdf((eff_m_start - 60.0) / 11.5))

    expected_minutes = p_start_eff * eff_m_start + p_sub_eff * 22.0
    tau = expected_minutes / 90.0
    if tau <= 0.01:
        out = _empty_result()
        return out

    pts_minutes = p_start_eff * (1.0 + p_60_given_start) + p_sub_eff * 1.0

    raw_xg = float(form.get("xg") or 0.0)
    raw_xa = float(form.get("xa") or 0.0)
    xg_90 = rate_per90(raw_xg, minutes_total)
    xa_90 = rate_per90(raw_xa, minutes_total)

    phi_atk = float(np.clip(lambda_own / 1.32, 0.45, 2.40))
    phi_def = float(np.clip(lambda_opp / 1.32, 0.45, 2.40))

    lam_g = xg_90 * phi_atk * tau
    lam_a = xa_90 * phi_atk * tau

    raw_kp = float(form.get("key_passes") or 0.0)
    kp_90 = rate_per90(raw_kp, minutes_total, sparse_cap=3.0)
    lam_kp = kp_90 * phi_atk * tau
    pts_direct_atk = GOAL_PTS[pos] * lam_g + 3.0 * lam_a + 0.28 * max(0.0, lam_kp - lam_a)

    raw_duels = float(form.get("duels_won") or 0.0)
    duels_90 = rate_per90(raw_duels, minutes_total, sparse_cap=8.0)

    mu_sot = (2.6 * xg_90 + (0.25 if pos in {"MC", "DEL"} else 0.05)) * phi_atk * tau
    mu_drib = (0.28 * duels_90 if pos in {"MC", "DEL"} else 0.08 * duels_90) * tau
    mu_box = (1.8 * xg_90 + 0.9 * xa_90) * phi_atk * tau
    pts_atk_vol = (
        poisson_step_expectation(mu_sot, 2)
        + poisson_step_expectation(mu_drib, 2)
        + poisson_step_expectation(mu_box, 2)
    )

    p_cs = p_cs_own if p_cs_own is not None else math.exp(-lambda_opp)
    pts_cs = CS_PTS[pos] * p_start_eff * p_60_given_start * p_cs
    pts_gc = GC_PTS_PER_2[pos] * poisson_step_expectation(lambda_opp * tau, 2)

    pts_saves = 0.0
    if pos == "POR":
        raw_saves = float(form.get("saves") or 2.8)
        saves_90 = rate_per90(raw_saves, minutes_total, sparse_cap=6.0)
        mu_saves = saves_90 * (phi_def**0.65) * tau
        p_pen_saved = p_start_eff * (0.14 * phi_def) * 0.22
        pts_saves = poisson_step_expectation(mu_saves, 2) + 5.0 * p_pen_saved

    raw_clr = float(form.get("clearances") or (3.2 if pos == "DEF" else 0.8))
    clr_90 = rate_per90(raw_clr, minutes_total, sparse_cap=6.0)
    rec_90 = max(1.5, 0.85 * duels_90)
    pts_def_vol = poisson_step_expectation(clr_90 * (phi_def**0.50) * tau, 3) + poisson_step_expectation(
        rec_90 * (phi_def**0.35) * tau, 5
    )

    losses_90 = BASE_LOSSES_90[pos] + 1.4 * kp_90 + 0.9 * duels_90
    pts_losses = -1.0 * poisson_step_expectation(losses_90 * tau, LOSS_DIVISOR[pos])

    p_yc_base = {"POR": 0.04, "DEF": 0.22, "MC": 0.19, "DEL": 0.12}[pos]
    p_yc = float(np.clip(p_yc_base * (phi_def**0.3) * tau, 0.02, 0.45))
    p_rc = 0.012 * tau if pos == "DEF" else 0.006 * tau
    pts_cards = -1.0 * p_yc - 3.0 * p_rc

    explicit_bonus = player.get("relevo_bonus")
    if isinstance(explicit_bonus, bool) or not isinstance(explicit_bonus, int):
        explicit_bonus = None
    if explicit_bonus is not None and 0 <= explicit_bonus <= 4:
        inferred_bonus = float(explicit_bonus) * (p_start_eff + p_sub_eff)
    else:
        avg_points = float(player.get("average_points") or 4.0)
        avg_rating = float(
            form.get("average_rating") or form.get("rating") or (6.75 + 0.08 * (avg_points - 4.0))
        )
        # El bonus es una valoración (nota media), no un subproducto de los
        # minutos: se acota el rating al rango del probe y se reescala por
        # ``p_start_eff`` para que acumular minutos con nota baja no infle el
        # bonus (el sustituto cobra el bonus de suplente, no el de titular).
        inferred_bonus = infer_opta_performance_bonus(
            avg_rating=float(np.clip(avg_rating, 5.6, 8.4)),
            lambda_own=lambda_own,
            lambda_opp=lambda_opp,
            key_passes_90=kp_90,
            duels_won_90=duels_90,
            p_start_eff=p_start_eff,
            p_sub_eff=p_sub_eff,
        )

    expected_pts = (
        pts_minutes
        + pts_direct_atk
        + pts_atk_vol
        + pts_cs
        + pts_gc
        + pts_saves
        + pts_def_vol
        + pts_losses
        + pts_cards
        + inferred_bonus
    )

    jp_mult = float(form.get("jp_multiplier") or 1.0)
    if jp_mult != 1.0:
        expected_pts *= 1.0 + 0.35 * (jp_mult - 1.0)

    play_mass = max(1e-4, p_start_eff + p_sub_eff)
    p_goal = (1.0 - math.exp(-max(0.0, xg_90 * phi_atk * tau / play_mass))) * play_mass
    p_assist = (1.0 - math.exp(-max(0.0, xa_90 * phi_atk * tau / play_mass))) * play_mass

    if run_monte_carlo and n_sims > 0:
        seed = abs(hash(str(player.get("player_id") or player.get("name") or "0"))) % (2**32)
        rng = np.random.default_rng(seed=seed)
        u_play = rng.random(n_sims)
        is_starter = u_play < p_start_eff
        is_sub = (~is_starter) & (u_play < (p_start_eff + p_sub_eff))
        active = is_starter | is_sub

        plays_60 = is_starter & (rng.random(n_sims) < p_60_given_start)
        sim_pts = np.where(plays_60, 2.0, np.where(active, 1.0, 0.0))

        opp_goals = rng.poisson(lambda_opp, size=n_sims)
        cs_achieved = plays_60 & (opp_goals == 0)
        sim_pts += np.where(cs_achieved, CS_PTS[pos], 0.0)
        sim_pts += np.where(active, GC_PTS_PER_2[pos] * (opp_goals // 2), 0.0)

        # ``tau / play_mass`` es el tiempo condicionado a jugar. El antiguo suelo
        # de 0.25 truncaba esa condición al alza en muestras bajas: un suplente
        # de 10' recibía el xG de un titular de 22'. Se acota a ``[0, 1]`` (nadie
        # juega más de 90') y se aplica solo a los que juegan, sin alterar la
        # media: ``tau`` ya es el tiempo esperado.
        tau_cond = float(np.clip(tau / play_mass, 0.0, 1.0))
        g_sim = rng.poisson(max(0.0, xg_90 * phi_atk * tau_cond), size=n_sims)
        a_sim = rng.poisson(max(0.0, xa_90 * phi_atk * tau_cond), size=n_sims)
        sim_pts += np.where(active, GOAL_PTS[pos] * g_sim + 3.0 * a_sim, 0.0)

        vol_mean = (pts_atk_vol + pts_saves + pts_def_vol + pts_losses + pts_cards + inferred_bonus) / play_mass
        vol_noise = rng.normal(loc=vol_mean, scale=1.65, size=n_sims)
        sim_pts += np.where(active, np.round(vol_noise + 0.8 * (g_sim > 0) + 0.5 * cs_achieved), 0.0)
        ceiling_pts = float(np.percentile(sim_pts, 90))
    else:
        ceiling_pts = expected_pts * 1.65 + 2.0

    next_match_survival = 1.0 - (p_start_eff * p_yc) if on_verge else 1.0

    return {
        "expected_points": round(max(0.0, expected_pts), 3),
        "ceiling_points": round(max(expected_pts, ceiling_pts), 2),
        "p_start_eff": round(p_start_eff, 4),
        "expected_minutes": round(expected_minutes, 1),
        "inferred_bonus": round(inferred_bonus, 3),
        "next_match_survival": round(next_match_survival, 4),
        "goal_probability": round(float(np.clip(p_goal, 0.0, 1.0)), 4),
        "assist_probability": round(float(np.clip(p_assist, 0.0, 1.0)), 4),
    }

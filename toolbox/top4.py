"""Probabilidad de quedar entre los 4 primeros de la jornada.

El objetivo de la liga no es la general: quien queda fuera del top 4 de la
jornada paga multa. Aquí se simula esa jornada.

* Media de cada mánager: la suma de xP de su once esperado (la proyección de
  ``league_race``, que sale de ``own_intel.own_expected_points``, única fuente).
* Dispersión: se calibra con las jornadas reales (residuo de puntos tras quitar
  el nivel de la jornada y el de cada mánager). Ninguna cifra inventada.
* Regla oficial: con menos de 11 jugadores en la plantilla la jornada entera
  puntúa 0. Esa plantilla simula como un cero; para el propio mánager se
  calcula además el escenario con el once completado.
* Estar dentro del top 4 es ``puntos >= 4.º mejor de los otros 9``: los empates
  en el corte cuentan a favor (no hay desempate publicado en la jornada).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

TOP_N = 4
MIN_PLAYERS = 11
SIMULATIONS = 20_000
# Sin al menos tres jornadas el residuo no se puede estimar con sentido.
MIN_ROUNDS = 3
# Dispersión de reserva (puntos por jornada) si no hay jornadas: la mediana de
# lo observado en la liga en J9-J12. Solo se usa y se avisa cuando faltan datos.
FALLBACK_SIGMA = 9.0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def calibrate_sigma(rounds: dict[int, dict[str, int]]) -> dict[str, Any]:
    """Desviación de la jornada de un mánager respecto a su propio nivel.

    Modelo aditivo ``puntos = jornada + mánager + error``. Se estima el error
    con el residuo de dos vías sobre los mánagers presentes en todas las
    jornadas usadas, con sus grados de libertad.
    """
    numbers = sorted(rounds)
    if len(numbers) < MIN_ROUNDS:
        return {"sigma": FALLBACK_SIGMA, "rounds_used": len(numbers), "calibrated": False}
    common = set(rounds[numbers[0]])
    for number in numbers[1:]:
        common &= set(rounds[number])
    names = sorted(common)
    if len(names) < TOP_N + 1:
        return {"sigma": FALLBACK_SIGMA, "rounds_used": len(numbers), "calibrated": False}
    grid = np.array([[rounds[n][name] for name in names] for n in numbers], dtype=float)
    resid = grid - grid.mean(axis=1, keepdims=True) - grid.mean(axis=0, keepdims=True) + grid.mean()
    dof = (grid.shape[0] - 1) * (grid.shape[1] - 1)
    sigma = float(math.sqrt((resid**2).sum() / dof))
    return {
        "sigma": round(sigma, 2),
        "rounds_used": len(numbers),
        "managers_used": len(names),
        "calibrated": True,
    }


def _fill_value(xi: list[dict[str, Any]]) -> float:
    """xP de un recambio a falta de uno mejor: el peor titular del once."""
    values = [v for v in (_number(row.get("expected_points")) for row in xi) if v is not None]
    return min(values) if values else 0.0


def simulate(
    means: list[float],
    sigma: float,
    *,
    self_index: int,
    seed: int = 20260,
    n: int = SIMULATIONS,
    forced_zero: set[int] | None = None,
) -> dict[str, Any]:
    """Reparto de puntos de la jornada y probabilidad de top 4 de cada uno."""
    rng = np.random.default_rng(seed)
    mu = np.array(means, dtype=float)
    draws = np.rint(rng.normal(mu, sigma, size=(n, len(mu))))
    draws = np.clip(draws, 0, None)
    for idx in forced_zero or set():
        draws[:, idx] = 0
    kth = np.sort(draws, axis=1)[:, ::-1][:, TOP_N - 1]
    in_top = draws >= kth[:, None]
    others = np.delete(draws, self_index, axis=1)
    cutoff = np.sort(others, axis=1)[:, ::-1][:, TOP_N - 1]
    rank = 1 + (draws > draws[:, [self_index]]).sum(axis=1)
    return {
        "p_top4": in_top.mean(axis=0),
        "cutoff_median": float(np.median(cutoff)),
        "cutoff_p25": float(np.percentile(cutoff, 25)),
        "cutoff_p75": float(np.percentile(cutoff, 75)),
        "expected_rank": float(rank.mean()),
        "p_win": float((rank == 1).mean()),
    }


class Top4Model:
    """Probabilidad de top 4 como función de MIS puntos esperados.

    Los rivales se simulan una sola vez (números aleatorios comunes), así que
    comparar dos escenarios mide la diferencia real y no ruido de simulación.
    """

    def __init__(
        self,
        rival_means: list[float],
        sigma: float,
        *,
        rival_void: list[bool] | None = None,
        seed: int = 20260,
        n: int = SIMULATIONS,
    ) -> None:
        rng = np.random.default_rng(seed)
        mu = np.array(rival_means, dtype=float)
        draws = np.clip(np.rint(rng.normal(mu, sigma, size=(n, len(mu)))), 0, None)
        for idx, void in enumerate(rival_void or []):
            if void:
                draws[:, idx] = 0
        self.cutoff = np.sort(draws, axis=1)[:, ::-1][:, TOP_N - 1]
        self._z = rng.standard_normal(n)
        self.sigma = float(sigma)

    def p(self, my_points: float, *, void: bool = False) -> float:
        """Probabilidad de igualar o superar al 4.º de los demás con esa media."""
        if void:
            return 0.0
        mine = np.clip(np.rint(my_points + self.sigma * self._z), 0, None)
        return float((mine >= self.cutoff).mean())


def model_from_race(race: dict[str, Any] | None, rounds: dict[int, dict[str, int]] | None) -> dict[str, Any] | None:
    """``Top4Model`` de la jornada y los datos propios que hacen falta para usarlo."""
    table = [row for row in (race or {}).get("table") or [] if isinstance(row, dict)]
    me = next((row for row in table if row.get("is_self")), None)
    if me is None:
        return None
    calibration = calibrate_sigma(rounds or {})
    leagues = [
        v for v in (_number((row.get("projection") or {}).get("expected_points")) for row in table) if v is not None
    ]
    league_mean = sum(leagues) / len(leagues) if leagues else 0.0
    rivals = [row for row in table if not row.get("is_self")]
    means = [_number((row.get("projection") or {}).get("expected_points")) for row in rivals]
    model = Top4Model(
        [m if m is not None else league_mean for m in means],
        float(calibration["sigma"]),
        rival_void=[int(row.get("player_count") or 0) < MIN_PLAYERS for row in rivals],
    )
    mine = _number(((race or {}).get("my_projection") or {}).get("expected_points"))
    if mine is None:
        mine = _number((me.get("projection") or {}).get("expected_points"))
    xi = ((race or {}).get("my_projection") or {}).get("xi") or []
    return {
        "model": model,
        "mu": mine if mine is not None else league_mean,
        "players": int(me.get("player_count") or 0),
        "xi": xi,
        "calibration": calibration,
        "cutoff_median": float(np.median(model.cutoff)),
    }


def build_top4(race: dict[str, Any] | None, rounds: dict[int, dict[str, int]] | None) -> dict[str, Any]:
    """Probabilidad de top 4 de la próxima jornada a partir de la carrera."""
    table = [row for row in (race or {}).get("table") or [] if isinstance(row, dict)]
    if not table or not any(row.get("is_self") for row in table):
        return {"ok": False, "reason": "sin_tabla", "detail": "No hay plantillas para simular la jornada."}
    calibration = calibrate_sigma(rounds or {})
    sigma = float(calibration["sigma"])

    league_mu = [
        v for v in (_number((row.get("projection") or {}).get("expected_points")) for row in table) if v is not None
    ]
    league_mean = sum(league_mu) / len(league_mu) if league_mu else 0.0

    my_projection = (race or {}).get("my_projection") or {}
    members: list[dict[str, Any]] = []
    for row in table:
        projection = row.get("projection") or {}
        mu = _number(projection.get("expected_points"))
        if row.get("is_self"):
            mine = _number(my_projection.get("expected_points"))
            mu = mine if mine is not None else mu
        has_xp = mu is not None
        players = int(row.get("player_count") or 0)
        void = players < MIN_PLAYERS
        members.append(
            {
                "team_id": row.get("team_id"),
                "manager_name": row.get("manager_name"),
                "is_self": row.get("is_self") is True,
                "player_count": players,
                "mu": mu if has_xp else league_mean,
                "has_xp": has_xp,
                "void": void,
                "xi": (my_projection.get("xi") if row.get("is_self") else projection.get("xi")) or [],
            }
        )
    self_index = next(i for i, m in enumerate(members) if m["is_self"])
    me = members[self_index]

    base = simulate(
        [m["mu"] for m in members],
        sigma,
        self_index=self_index,
        forced_zero={i for i, m in enumerate(members) if m["void"]},
    )

    completed = None
    if me["void"]:
        missing = MIN_PLAYERS - me["player_count"]
        fill = _fill_value(me["xi"])
        filled_mu = me["mu"] + missing * fill
        means = [m["mu"] for m in members]
        means[self_index] = filled_mu
        completed_sim = simulate(
            means,
            sigma,
            self_index=self_index,
            forced_zero={i for i, m in enumerate(members) if m["void"] and i != self_index},
        )
        completed = {
            "missing_players": missing,
            "fill_xp": round(fill, 2),
            "expected_points": round(filled_mu, 2),
            "p_top4": round(float(completed_sim["p_top4"][self_index]), 4),
            "cutoff_median": completed_sim["cutoff_median"],
            "xp_gap_to_cutoff": round(completed_sim["cutoff_median"] - filled_mu, 2),
            "expected_rank": round(completed_sim["expected_rank"], 2),
        }

    live = completed if me["void"] and completed else None
    reference = live or {
        "expected_points": round(me["mu"], 2),
        "cutoff_median": base["cutoff_median"],
        "xp_gap_to_cutoff": round(base["cutoff_median"] - me["mu"], 2),
    }
    p_top4 = float(base["p_top4"][self_index])
    managers = []
    for i, m in enumerate(members):
        managers.append(
            {
                "team_id": m["team_id"],
                "manager_name": m["manager_name"],
                "is_self": m["is_self"],
                "expected_points": round(m["mu"], 2),
                "has_xp": m["has_xp"],
                "player_count": m["player_count"],
                "void": m["void"],
                "p_top4": round(float(base["p_top4"][i]), 4),
            }
        )
    managers.sort(key=lambda r: (-r["p_top4"], -r["expected_points"]))
    return {
        "ok": True,
        "top_n": TOP_N,
        "simulations": SIMULATIONS,
        "p_top4": round(p_top4, 4),
        "void": me["void"],
        "player_count": me["player_count"],
        "expected_points": round(me["mu"], 2),
        "cutoff_median": base["cutoff_median"],
        "cutoff_range": [base["cutoff_p25"], base["cutoff_p75"]],
        # Positivo = te faltan xP para el corte; negativo = vas por encima.
        "xp_gap_to_cutoff": round(base["cutoff_median"] - me["mu"], 2),
        "expected_rank": round(base["expected_rank"], 2),
        "p_win": round(base["p_win"], 4),
        "if_completed": completed,
        "reference": reference,
        "managers": managers,
        "calibration": calibration,
        "league_mean_xp": round(league_mean, 2),
        "note": (
            "Con menos de 11 jugadores la jornada puntúa 0 (regla oficial); "
            "'si_completas' simula el once con el hueco cubierto por un recambio del peor titular."
        ),
    }

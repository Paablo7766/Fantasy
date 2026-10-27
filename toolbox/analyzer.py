"""Motor ILP del once titular.

La jornada vale 0 si el XI no tiene 11 jugadores o si la caja es negativa.
Esas dos condiciones no se penalizan con un número finito: el hueco y el
saldo negativo dejan la jornada a cero. El solver solo reparte el once cuando
ambas se sostienen.

Los puntos esperados salen de la tabla OPTA de ``context/SKILL.md``. El bonus
Relevo solo entra si el dato viene en el jugador, entero de 0 a 4. No se
deduce de la nota ni de los goles.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol

import pulp

from toolbox.cache import ResponseCache
from toolbox.normalize import (
    SCHEMA_VERSION,
    display_player_status,
    exclusion_from_status,
    official_week_points,
    reconcile_fitness,
    stale_injury_overridden,
    titularity_overrides_injury,
)
from toolbox.opta_points_v2 import (
    compute_expected_opta_points_v2,
    infer_opta_performance_bonus,
    poisson_step_expectation,
    rate_per90,
)

POSITIONS = ("POR", "DEF", "MC", "DEL")
FORMATIONS: dict[str, dict[str, int]] = {
    "3-4-3": {"POR": 1, "DEF": 3, "MC": 4, "DEL": 3},
    "3-5-2": {"POR": 1, "DEF": 3, "MC": 5, "DEL": 2},
    "4-3-3": {"POR": 1, "DEF": 4, "MC": 3, "DEL": 3},
    "4-4-2": {"POR": 1, "DEF": 4, "MC": 4, "DEL": 2},
    "4-5-1": {"POR": 1, "DEF": 4, "MC": 5, "DEL": 1},
    "5-3-2": {"POR": 1, "DEF": 5, "MC": 3, "DEL": 2},
    "5-4-1": {"POR": 1, "DEF": 5, "MC": 4, "DEL": 1},
}
GOAL_POINTS = {"POR": 6, "DEF": 6, "MC": 5, "DEL": 4}
ASSIST_POINTS = 3
MATCH_THRESHOLD = 0.85
P_TITULAR_WEIGHT = 1.0
EXPECTED_POINTS_WEIGHT = 1.0
OPTIMIZE_TTL_SECONDS = 120.0
XI_SIZE = 11
INFINITE_LAMBDA = "inf"
CLAUSE_RISK_MULTIPLE = 1.25
CLAUSE_RULE_A_POINTS = 3.0
CLAUSE_RULE_A_MULTIPLE = 1.6
CLAUSE_RULE_B_POINTS = 6.0
CLAUSE_RULE_B_MULTIPLE = 2.2
FALLBACK_TITULAR_CAP = 0.55
DOUBT_TITULAR_FACTOR = 0.45
_INJURED = {"lesionado", "baja", "injured", "out"}
_DOUBTFUL = {"doubtful", "duda", "doubt"}
_CALIBRATION_NOTE = (
    "En el once se muestra jornada_ev (valor esperado de la jornada). "
    "OPTA v2 ya incluye titularidad y minutos; el motor v1 multiplica por p_titular. "
    "Un emparejamiento con matching_confidence < 0.85 no aporta titularidad ni forma. "
    "Sin scraper, la titularidad sale de week_points: participaciones recientes / 5, tope 55 %. "
    "En duda se aplica un recorte adicional sobre p_titular."
)


class CatalogClient(Protocol):
    def market_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]: ...

    def squads_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ObjectiveWeights:
    p_titular: float = P_TITULAR_WEIGHT
    expected_points: float = EXPECTED_POINTS_WEIGHT


@dataclass(frozen=True)
class RiskPosture:
    """Cómo se juega la jornada contra la liga.

    ``ventaja`` protege el suelo (minutos y titularidad segura) y castiga la
    rotación. ``remontada`` paga el techo: el P90 de puntos pesa más que la
    media. ``neutro`` es el motor de siempre, sin inventar nada.
    """

    name: str = "neutro"
    ceiling_weight: float = 0.0
    titular_exponent: float = 1.0

    @property
    def active(self) -> bool:
        return self.name in {"ventaja", "remontada"}


NEUTRAL_POSTURE = RiskPosture()
VENTAJA_POSTURE = RiskPosture(name="ventaja", ceiling_weight=0.0, titular_exponent=1.35)
REMONTADA_POSTURE = RiskPosture(name="remontada", ceiling_weight=0.35, titular_exponent=1.0)


@dataclass(frozen=True)
class Candidate:
    key: str
    player_id: str | None
    name: str | None
    nickname: str | None
    position: str
    club: str | None
    p_titular: float | None
    expected_points: float
    jornada_ev: float
    points_if_starts: float | None
    relevo_bonus: int | None
    objective: float
    components: dict[str, float]
    player_status: str | None
    excluded_reason: str | None
    p_titular_source: str | None = None
    image_url: str | None = None
    ceiling_points: float | None = None

    @property
    def eligible(self) -> bool:
        return self.excluded_reason is None


def relevo_bonus(value: Any) -> int | None:
    """Entero 0-4. Un booleano no cuenta: en Python ``bool`` es ``int``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 0 <= value <= 4:
        return value
    return None


def probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number:
        return None
    if number > 1.0:
        if number > 100.0:
            return None
        number /= 100.0
    if number < 0.0 or number > 1.0:
        return None
    return round(number, 4)


def _euros(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _real(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number:
        return None
    return number


def clause_multiple(player: dict[str, Any]) -> float | None:
    """Cláusula dividida por el valor de mercado. Sin valor no hay múltiplo."""
    clause = _euros(player.get("buyout_clause"))
    value = _euros(player.get("market_value"))
    if clause is None or value is None or value <= 0:
        return None
    return round(clause / value, 4)


def is_at_risk(player: dict[str, Any]) -> bool:
    """La cláusula propia está en 1,25 veces el valor, o por debajo."""
    multiple = clause_multiple(player)
    return multiple is not None and multiple <= CLAUSE_RISK_MULTIPLE


def official_price_delta(trend: dict[str, Any] | None) -> int | None:
    """Subida (o bajada) oficial del día para reglas internas. Nunca usa aceleración.

    Preferencia:
    1. ``market_value_change`` de la API (``marketValueChange``). Hoy siempre
       es ``None`` porque la API no publica el campo (ver
       CONTEXTO_ALGORITMO_ACTUAL.md).
    2. ``price_delta`` homologado (``diferencia1`` de FútbolFantasy). Es una
       estimación de un tercero, no el número oficial; se usa como respaldo
       declarado, nunca disfrazado de oficial.
    3. ``market_value`` − ``sale_price`` (valor actual frente a la puja base)
    """
    if not isinstance(trend, dict):
        return None
    for key in ("market_value_change", "price_delta"):
        value = _euros_signed(trend.get(key))
        if value is not None:
            return value
    current = _euros(trend.get("market_value"))
    if current is None:
        current = _euros(trend.get("fantasy_price"))
    base = _euros(trend.get("sale_price"))
    if current is not None and base is not None:
        return current - base
    return None


def display_price_delta(source: dict[str, Any] | None) -> int | None:
    """Δ del día en tablas y UI: mismo criterio que la app (API LaLiga)."""
    return official_price_delta(source)


def sell_signal(trend: dict[str, Any] | None) -> bool:
    """Pico de valor: venía subiendo y el tramo de 1 a 3 días se aplana o cae.

    Si ``sell_signal_status`` está poblado (cinemática v2 desde ``price_snapshots``),
    devuelve el booleano ``sell_signal`` ya calculado. Si no, aplica la regla legacy.
    """
    if not isinstance(trend, dict):
        return False
    status = trend.get("sell_signal_status")
    if isinstance(status, str) and status:
        value = trend.get("sell_signal")
        if isinstance(value, bool):
            return value
    day = official_price_delta(trend)
    span = _euros_signed(trend.get("price_delta_3"))
    accel = _euros_signed(trend.get("acceleration"))
    was_rising = (accel is not None and accel > 0) or (span is not None and span > 0)
    if was_rising and day is not None and day <= 0:
        return True
    if span is not None and span > 0 and accel is not None and accel <= 0:
        return True
    return False


def _euros_signed(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def exposed_clause_rule(player: dict[str, Any]) -> str | None:
    """Regla de oro. ``A`` es el chollo ajustado; ``B`` el de media alta.

    A: media >= 3 y cláusula <= 1,6× el valor.
    B: media >= 6 y cláusula <= 2,2× el valor.
    Si cumple las dos, gana A.
    """
    average = _real(player.get("average_points"))
    multiple = clause_multiple(player)
    if average is None or multiple is None:
        return None
    if average >= CLAUSE_RULE_A_POINTS and multiple <= CLAUSE_RULE_A_MULTIPLE:
        return "A"
    if average >= CLAUSE_RULE_B_POINTS and multiple <= CLAUSE_RULE_B_MULTIPLE:
        return "B"
    return None


def starter_fallback(player: dict[str, Any]) -> float | None:
    """Participación reciente sin scraper: jornadas con puntos / ventana, tope 55 %."""
    weeks = official_week_points(player)
    if not weeks:
        return None
    played = sum(1 for score in weeks if score > 0)
    return round(min(FALLBACK_TITULAR_CAP, played / len(weeks)), 4)


def _source_is_doubtful(source: dict[str, Any]) -> bool:
    status = source.get("player_status")
    if isinstance(status, str) and status.strip().lower() in _DOUBTFUL:
        return True
    lineup = source.get("lineup_status")
    if isinstance(lineup, str) and lineup.strip().lower() == "duda":
        return True
    fitness = source.get("fitness")
    if isinstance(fitness, str) and fitness.strip().lower() == "duda":
        return True
    return False


def apply_doubt_titular_discount(
    p_titular: float | None,
    player: dict[str, Any],
    trend: dict[str, Any] | None,
) -> float | None:
    if p_titular is None:
        return None
    doubtful = _source_is_doubtful(player)
    if not doubtful and isinstance(trend, dict):
        doubtful = _source_is_doubtful(trend)
    if not doubtful:
        return p_titular
    return round(float(p_titular) * DOUBT_TITULAR_FACTOR, 4)


def trend_usable(trend: dict[str, Any] | None) -> bool:
    if not trend:
        return False
    confidence = trend.get("matching_confidence")
    if confidence is None:
        return False
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    return float(confidence) >= MATCH_THRESHOLD


def unavailable_reason(player: dict[str, Any], trend: dict[str, Any] | None) -> str | None:
    """Lesión o sanción. Una duda no expulsa: la titularidad ya la descuenta.

    Si la API trae ``playerStatus``, manda sobre el parte scrapeado. Así un
    ``doubtful`` no se convierte en baja porque otra web lo liste como lesionado.
    """
    sources: list[dict[str, Any]] = [player]
    if trend_usable(trend):
        sources.append(trend or {})
    official = player.get("player_status")
    if isinstance(official, str) and official.strip():
        reason = exclusion_from_status(official)
        if reason == "lesionado":
            for source in sources:
                if stale_injury_overridden(
                    p_titular=source.get("p_titular"),
                    p_titular_source=source.get("p_titular_source")
                    if isinstance(source.get("p_titular_source"), str)
                    else None,
                    lineup_status=source.get("lineup_status") if isinstance(source.get("lineup_status"), str) else None,
                ):
                    reason = None
                    break
        if reason:
            return reason
        folded_official = official.strip().lower()
        if folded_official in {"doubtful", "duda", "doubt"}:
            for source in sources:
                sanction = source.get("sanction") if isinstance(source.get("sanction"), dict) else {}
                if source.get("suspended") is True or sanction.get("suspended") is True:
                    return "sancionado"
                if source.get("af_suspension"):
                    return "sancionado"
            return None
    for source in sources:
        if stale_injury_overridden(
            p_titular=source.get("p_titular"),
            p_titular_source=source.get("p_titular_source") if isinstance(source.get("p_titular_source"), str) else None,
            lineup_status=source.get("lineup_status") if isinstance(source.get("lineup_status"), str) else None,
        ):
            continue
        fitness = reconcile_fitness(
            source.get("fitness") if isinstance(source.get("fitness"), str) else None,
            p_titular=source.get("p_titular"),
            p_titular_source=source.get("p_titular_source") if isinstance(source.get("p_titular_source"), str) else None,
            lineup_status=source.get("lineup_status") if isinstance(source.get("lineup_status"), str) else None,
        )
        if isinstance(fitness, str) and fitness.strip().lower() in _INJURED:
            return "lesionado"
        sanction = source.get("sanction") if isinstance(source.get("sanction"), dict) else {}
        if source.get("suspended") is True or sanction.get("suspended") is True:
            return "sancionado"
    return None


def _minutes_factor(form: dict[str, Any]) -> float | None:
    """Descuenta titulares de pocos minutos. 60 %+ de minutos = factor 1."""
    pct = form.get("minutes_pct")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool):
        share = float(pct)
        if share > 1:
            share /= 100.0
        if share < 0:
            return None
        if share >= 0.6:
            return 1.0
        return round(max(0.4, share / 0.6), 4)
    minutes = form.get("minutes")
    starts = form.get("starts")
    if (
        isinstance(minutes, (int, float))
        and not isinstance(minutes, bool)
        and isinstance(starts, (int, float))
        and not isinstance(starts, bool)
        and float(starts) > 0
    ):
        share = float(minutes) / (90.0 * float(starts))
        if share >= 0.6:
            return 1.0
        return round(max(0.4, min(1.0, share / 0.6)), 4)
    return None


def expected_opta_points(position: str, form: dict[str, Any] | None) -> tuple[float, dict[str, float]]:
    """Tarifa OPTA sobre xG/xA, ajustada por minutos, FDR y tip de Jornada Perfecta."""
    components: dict[str, float] = {}
    if position not in GOAL_POINTS or not isinstance(form, dict):
        return 0.0, components
    total = 0.0
    minutes = form.get("minutes")
    minutes_total = float(minutes) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) else 0.0
    xg = form.get("xg")
    xa = form.get("xa")
    if isinstance(xg, (int, float)) and not isinstance(xg, bool):
        xg_rate = rate_per90(float(xg), minutes_total)
        points = round(xg_rate * GOAL_POINTS[position], 4)
        components["xg"] = points
        total += points
    if isinstance(xa, (int, float)) and not isinstance(xa, bool):
        xa_rate = rate_per90(float(xa), minutes_total)
        points = round(xa_rate * ASSIST_POINTS, 4)
        components["xa"] = points
        total += points
    if total <= 0:
        return 0.0, components

    minutes_factor = _minutes_factor(form)
    if minutes_factor is not None and minutes_factor != 1.0:
        total = round(total * minutes_factor, 4)
        components["minutes_factor"] = minutes_factor

    try:
        from toolbox.understat import points_multiplier

        fdr = form.get("fdr")
        fdr_int = int(fdr) if isinstance(fdr, (int, float)) and not isinstance(fdr, bool) else None
        home = form.get("home") if isinstance(form.get("home"), bool) else None
        fixture_mult = points_multiplier(fdr=fdr_int, home=home)
        if fixture_mult != 1.0:
            total = round(total * fixture_mult, 4)
            components["fixture_factor"] = fixture_mult
    except Exception:
        pass

    jp_mult = form.get("jp_multiplier")
    if isinstance(jp_mult, (int, float)) and not isinstance(jp_mult, bool) and float(jp_mult) != 1.0:
        try:
            from toolbox.jornada_perfecta import JP_TIP_MULT_FLOOR, JP_TIP_WEIGHT

            # Variación relativa acotada: la etiqueta de rol nunca destruye los
            # puntos base de Opta (suelo JP_TIP_MULT_FLOOR).
            adjusted = float(total) * (1.0 + JP_TIP_WEIGHT * (float(jp_mult) - 1.0))
            floor = float(total) * JP_TIP_MULT_FLOOR
            total = round(max(adjusted, floor), 4)
            components["jp_factor"] = float(jp_mult)
        except Exception:
            pass

    return round(total, 4), components


def _opta_v2_payload(
    player: dict[str, Any],
    trend: dict[str, Any] | None,
    *,
    position: str,
) -> dict[str, Any]:
    usable = trend if isinstance(trend, dict) else {}
    form = usable.get("form") if isinstance(usable.get("form"), dict) else None
    if form is None and isinstance(player.get("form"), dict):
        form = player["form"]
    sanction = usable.get("sanction") if isinstance(usable.get("sanction"), dict) else player.get("sanction")
    p_titular = usable.get("p_titular") if usable.get("p_titular") is not None else player.get("p_titular")
    return {
        "player_id": player.get("player_id") or usable.get("player_id"),
        "position": position,
        "p_titular": p_titular,
        "form": form if isinstance(form, dict) else {},
        "sanction": sanction if isinstance(sanction, dict) else {},
        "player_status": player.get("player_status") or usable.get("player_status"),
        "fitness": usable.get("fitness") if isinstance(usable.get("fitness"), str) else player.get("fitness"),
        "af_suspension": usable.get("af_suspension") or player.get("af_suspension"),
        "average_points": player.get("average_points") or usable.get("average_points"),
        "relevo_bonus": player.get("relevo_bonus") if player.get("relevo_bonus") is not None else usable.get("relevo_bonus"),
        "has_midweek_cup": bool(usable.get("has_midweek_cup") or player.get("has_midweek_cup")),
        "days_rest": int(usable.get("days_rest") or player.get("days_rest") or 6),
    }


def _lambdas_for_opta(trend: dict[str, Any] | None, form: dict[str, Any] | None) -> tuple[float, float, float | None]:
    lam_own = 1.32
    lam_opp = 1.32
    p_cs = None
    if isinstance(form, dict):
        for key, target in (("lambda_for", "own"), ("lambda_against", "opp")):
            val = form.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                if target == "own":
                    lam_own = float(val)
                else:
                    lam_opp = float(val)
        p_cs_val = form.get("p_cs_for")
        if isinstance(p_cs_val, (int, float)) and not isinstance(p_cs_val, bool):
            p_cs = float(p_cs_val)
    if isinstance(trend, dict):
        calendar = trend.get("own_calendar")
        if isinstance(calendar, list) and calendar and isinstance(calendar[0], dict):
            cell = calendar[0]
            if isinstance(cell.get("lambda_for"), (int, float)):
                lam_own = float(cell["lambda_for"])
            if isinstance(cell.get("lambda_against"), (int, float)):
                lam_opp = float(cell["lambda_against"])
    return lam_own, lam_opp, p_cs


def _opta_v2_enabled(form: dict[str, Any] | None, trend: dict[str, Any] | None) -> bool:
    if isinstance(trend, dict) and isinstance(trend.get("own_calendar"), list) and trend["own_calendar"]:
        return True
    if not isinstance(form, dict):
        return False
    minutes = form.get("minutes")
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and float(minutes) > 0:
        return True
    return False


def expected_opta_points_v2_for_candidate(
    player: dict[str, Any],
    trend: dict[str, Any] | None,
    *,
    position: str,
    run_monte_carlo: bool = False,
) -> dict[str, float] | None:
    payload = _opta_v2_payload(player, trend, position=position)
    form = payload.get("form")
    if not isinstance(form, dict):
        form = {}
    if not _opta_v2_enabled(form, trend if isinstance(trend, dict) else None):
        return None
    lam_own, lam_opp, p_cs = _lambdas_for_opta(trend if isinstance(trend, dict) else None, form)
    return compute_expected_opta_points_v2(
        payload,
        lambda_own=lam_own,
        lambda_opp=lam_opp,
        p_cs_own=p_cs,
        has_midweek_cup=bool(payload.get("has_midweek_cup")),
        days_rest=int(payload.get("days_rest") or 6),
        run_monte_carlo=run_monte_carlo,
    )


def objective_value(
    *,
    p_titular: float | None,
    expected_points: float,
    relevo: int | None,
    weights: ObjectiveWeights,
) -> float:
    """Valor esperado de jornada del jugador.

    Sin ``p_titular`` el coeficiente es 0: no se imputa una probabilidad.
    El jugador puede entrar igual para cerrar el once, porque un hueco anula
    la jornada entera.
    """
    points = expected_points + (float(relevo) if relevo is not None else 0.0)
    if p_titular is None:
        return 0.0
    return round(weights.p_titular * p_titular * weights.expected_points * points, 4)


def objective_with_posture(
    *,
    base_objective: float,
    p_titular: float | None,
    ceiling_ev: float | None,
    posture: RiskPosture,
) -> float:
    """Reajusta un objetivo ya calculado según se juegue suelo o techo.

    ``base_objective`` es el valor de jornada que ya usa el motor (con
    titularidad dentro, v1 o v2). La postura no recalcula puntos: mueve el
    peso de lo que el jugador ya vale. Sin postura activa se devuelve igual,
    así el resultado no cambia cuando no hay brecha de liga.
    """
    if not posture.active:
        return base_objective
    if p_titular is None:
        return base_objective
    share = min(1.0, max(0.0, float(p_titular)))
    if posture.name == "ventaja":
        # Un 55 % de titularidad pesa menos que su media: el suelo manda.
        return round(base_objective * (share ** (posture.titular_exponent - 1.0)), 4)
    ceiling = ceiling_ev if isinstance(ceiling_ev, (int, float)) and ceiling_ev > 0 else None
    if ceiling is None:
        return base_objective
    return round(
        (1.0 - posture.ceiling_weight) * base_objective + posture.ceiling_weight * float(ceiling),
        4,
    )


def index_trends(document: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if not isinstance(document, dict):
        return indexed
    players = document.get("players")
    if not isinstance(players, list):
        return indexed
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id")
        if isinstance(player_id, str) and player_id:
            indexed[player_id] = player
    return indexed


def _ceiling_points_for(usable: dict[str, Any] | None, v2: dict[str, Any] | None) -> float | None:
    """Techo P90 disponible. Si no viene, no se inventa."""
    for source in ((v2 or {}), (usable or {})):
        for key in ("ceiling_points", "own_ceiling_points", "af_ceiling_points"):
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0:
                return float(value)
    return None


def candidate_from_player(
    player: dict[str, Any],
    trend: dict[str, Any] | None,
    *,
    weights: ObjectiveWeights,
    ordinal: int,
    posture: RiskPosture | None = None,
) -> Candidate | None:
    position = player.get("position")
    if not isinstance(position, str) or position not in POSITIONS:
        return None
    player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else None
    key = player_id or str(player.get("player_team_id") or f"slot-{ordinal}")
    usable = trend if trend_usable(trend) else None
    reason = unavailable_reason(player, trend)
    if reason is None and position not in POSITIONS:
        reason = "posicion"
    scraped = probability(usable.get("p_titular")) if usable else None
    if scraped is not None:
        p_titular = scraped
        p_titular_source = "scraper"
    else:
        explicit = probability(player.get("p_titular"))
        if explicit is not None:
            p_titular = explicit
            p_titular_source = "roster"
        else:
            p_titular = starter_fallback(player)
            p_titular_source = "week_points" if p_titular is not None else None
    p_titular = apply_doubt_titular_discount(p_titular, player, usable)
    form = usable.get("form") if usable and isinstance(usable.get("form"), dict) else None
    if form is None and isinstance(player.get("form"), dict):
        form = player["form"]
    model_player = dict(player)
    if p_titular is not None:
        model_player["p_titular"] = p_titular
    model_trend = dict(usable) if isinstance(usable, dict) else usable
    if isinstance(model_trend, dict) and p_titular is not None:
        model_trend = {**model_trend, "p_titular": p_titular}
    v2 = expected_opta_points_v2_for_candidate(model_player, model_trend, position=position, run_monte_carlo=False)
    components: dict[str, float] = {}
    bonus = relevo_bonus(player.get("relevo_bonus"))
    if bonus is None and usable is not None:
        bonus = relevo_bonus(usable.get("relevo_bonus"))
    uses_v2 = v2 is not None
    external_ev = False
    if uses_v2:
        opta = float(v2["expected_points"])
        components["opta_v2"] = opta
        if bonus is not None:
            bonus = None
    else:
        opta, components = expected_opta_points(position, form)
    points = round(opta + (float(bonus) if bonus is not None else 0.0), 4)
    if points <= 0 and usable:
        for key in ("own_expected_points", "af_expected_points"):
            alt = usable.get(key)
            if isinstance(alt, (int, float)) and not isinstance(alt, bool) and float(alt) > 0:
                points = round(float(alt), 4)
                external_ev = True
                break
    if points <= 0:
        average = _real(player.get("average_points"))
        if average is not None and average > 0:
            points = round(average, 4)
    weak_titularity = p_titular is not None and float(p_titular) <= FALLBACK_TITULAR_CAP
    if uses_v2 or external_ev:
        jornada_ev = round(points, 4)
        # E[pts] de OPTA v2 ya pondera por ``p_start_eff``. Un suplente
        # (titularidad estimada ≤ tope del fallback) no puede publicar ese
        # número como «puntos si titular»: el fallback inflaría el suplente
        # hasta los puntos del titular. O hay titularidad real (scraper o
        # roster) o el campo queda vacío y la UI usa ``jornada_ev``.
        points_if_starts = points if (not weak_titularity and not external_ev) else None
        objective = round(weights.expected_points * jornada_ev, 4)
    else:
        points_if_starts = points
        share = float(p_titular) if p_titular is not None else 0.0
        jornada_ev = round(points * share, 4)
        objective = objective_value(
            p_titular=p_titular,
            expected_points=opta,
            relevo=bonus,
            weights=weights,
        )
    image_url = player.get("image_url") if isinstance(player.get("image_url"), str) else None
    if image_url is None and usable is not None and isinstance(usable.get("image_url"), str):
        image_url = usable["image_url"]
    trend_p = usable.get("p_titular") if usable else None
    trend_src = usable.get("p_titular_source") if usable and isinstance(usable.get("p_titular_source"), str) else None
    trend_lineup = usable.get("lineup_status") if usable and isinstance(usable.get("lineup_status"), str) else None
    shown_status = display_player_status(
        player.get("player_status") if isinstance(player.get("player_status"), str) else None,
        p_titular=trend_p if trend_p is not None else p_titular,
        p_titular_source=trend_src or p_titular_source,
        lineup_status=trend_lineup,
    )
    posted = objective
    ceiling_points = _ceiling_points_for(usable, v2)
    if posture is not None and posture.active:
        ceiling_ev = None
        if ceiling_points is not None:
            share = float(p_titular) if p_titular is not None else 1.0
            ceiling_ev = round(ceiling_points * share, 4)
        posted = objective_with_posture(
            base_objective=objective,
            p_titular=p_titular,
            ceiling_ev=ceiling_ev,
            posture=posture,
        )
    return Candidate(
        key=f"{ordinal}:{key}",
        player_id=player_id,
        name=player.get("name") if isinstance(player.get("name"), str) else None,
        nickname=player.get("nickname") if isinstance(player.get("nickname"), str) else None,
        position=position,
        club=player.get("club") if isinstance(player.get("club"), str) else None,
        p_titular=p_titular,
        expected_points=points_if_starts if points_if_starts is not None else jornada_ev,        jornada_ev=jornada_ev,
        points_if_starts=points_if_starts,
        relevo_bonus=bonus,
        objective=posted,
        components=components,
        player_status=shown_status,
        excluded_reason=reason,
        p_titular_source=p_titular_source,
        image_url=image_url,
        ceiling_points=ceiling_points,
    )


def candidates_from_squad(
    squad: dict[str, Any],
    trends: dict[str, dict[str, Any]],
    *,
    weights: ObjectiveWeights | None = None,
    posture: RiskPosture | None = None,
) -> list[Candidate]:
    scale = weights or ObjectiveWeights()
    players = squad.get("players") if isinstance(squad.get("players"), list) else []
    built: list[Candidate] = []
    for ordinal, player in enumerate(players):
        if not isinstance(player, dict):
            continue
        candidate = candidate_from_player(
            player,
            trends.get(str(player.get("player_id") or "")),
            weights=scale,
            ordinal=ordinal,
            posture=posture,
        )
        if candidate is not None:
            built.append(candidate)
    return built


def own_squad(document: dict[str, Any]) -> dict[str, Any] | None:
    squads = document.get("squads") if isinstance(document.get("squads"), list) else []
    for squad in squads:
        if isinstance(squad, dict) and squad.get("is_self") is True and not squad.get("error"):
            return squad
    return None


def _listing_price(listing: dict[str, Any]) -> int | None:
    for key in ("sale_price", "leading_bid", "market_value"):
        value = listing.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def market_fills(
    gaps: list[dict[str, Any]],
    listings: list[dict[str, Any]] | None,
    owned_ids: set[str] | None = None,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Los fichajes más baratos del mercado que tapan cada hueco."""
    used = set(owned_ids or ())
    rows = [row for row in listings or [] if isinstance(row, dict)]
    fills: list[dict[str, Any]] = []
    for gap in gaps:
        position = str(gap.get("position") or "")
        missing = int(gap.get("missing") or 0)
        pool: list[tuple[int, dict[str, Any]]] = []
        for listing in rows:
            if listing.get("position") != position:
                continue
            player_id = listing.get("player_id")
            if isinstance(player_id, str) and player_id in used:
                continue
            price = _listing_price(listing)
            if price is None:
                continue
            pool.append((price, listing))
        pool.sort(key=lambda item: (item[0], str(item[1].get("nickname") or item[1].get("name") or "")))
        options: list[dict[str, Any]] = []
        for price, listing in pool[:limit]:
            options.append(
                {
                    "player_id": listing.get("player_id") if isinstance(listing.get("player_id"), str) else None,
                    "name": listing.get("name") if isinstance(listing.get("name"), str) else None,
                    "nickname": listing.get("nickname") if isinstance(listing.get("nickname"), str) else None,
                    "position": position,
                    "club": listing.get("club") if isinstance(listing.get("club"), str) else None,
                    "image_url": listing.get("image_url") if isinstance(listing.get("image_url"), str) else None,
                    "sale_price": price,
                }
            )
        fills.append(
            {
                "position": position,
                "missing": missing,
                "label": gap.get("label") or f"Falta {missing} {position}",
                "options": options,
            }
        )
    return fills


def _gap_cost(gaps: list[dict[str, Any]], listings: list[dict[str, Any]] | None) -> tuple[int, int]:
    """Huecos sin precio en el mercado, y la suma de los más baratos."""
    uncovered = 0
    total = 0
    priced = [row for row in listings or [] if isinstance(row, dict)]
    for gap in gaps:
        position = gap["position"]
        missing = int(gap["missing"])
        prices = sorted(
            price
            for row in priced
            if row.get("position") == position
            for price in [_listing_price(row)]
            if price is not None
        )
        take = prices[:missing]
        total += sum(take)
        short = missing - len(take)
        if short > 0:
            uncovered += short
            total += short * 10**12
    return uncovered, total


def _partial_rank_key(candidate: Candidate) -> tuple[float, float, float]:
    """Orden de mérito del once parcial sin depender del ``objective``.

    ``objective_value`` vale 0 cuando no hay ``p_titular`` (regla deliberada del
    solver), así que ordenar por él dejaba a todos los candidatos sin
    probabilidad empatados a 0. Un once parcial con p_titular=0 sigue teniendo
    puntos que se pueden perder, y eso es lo que debe decidir quién entra.
    """
    ev = candidate.jornada_ev if isinstance(candidate.jornada_ev, (int, float)) else 0.0
    pts = candidate.expected_points if isinstance(candidate.expected_points, (int, float)) else 0.0
    share = candidate.p_titular if isinstance(candidate.p_titular, (int, float)) else 0.0
    return (float(ev), float(pts) * float(share), float(share))


def _best_partial(
    eligible: list[Candidate],
    listings: list[dict[str, Any]] | None,
) -> tuple[str | None, list[Candidate], list[dict[str, Any]]]:
    """Formación que más jugadores coloca. El empate lo gana el hueco más barato."""
    best: tuple[tuple[int, int, int, float, str], str, list[Candidate], list[dict[str, Any]]] | None = None
    for name, slots in FORMATIONS.items():
        placed: list[Candidate] = []
        gaps: list[dict[str, Any]] = []
        for position in POSITIONS:
            pool = sorted(
                (candidate for candidate in eligible if candidate.position == position),
                key=_partial_rank_key,
                reverse=True,
            )
            need = slots[position]
            placed.extend(pool[:need])
            missing = need - min(need, len(pool))
            if missing:
                gaps.append(
                    {
                        "position": position,
                        "missing": missing,
                        "label": f"Falta {missing} {position}",
                    }
                )
        uncovered, cost = _gap_cost(gaps, listings)
        # ``objective`` vale 0 sin p_titular; el once parcial se juzga por sus
        # puntos de jornada (ver ``_partial_rank_key``).
        score = round(sum(_partial_rank_key(candidate)[0] for candidate in placed), 4)
        rank = (len(placed), -uncovered, -cost, score, name)
        if best is None or rank > best[0]:
            best = (rank, name, placed, gaps)
    if best is None:
        return None, [], []
    return best[1], best[2], best[3]


def _lineup_points(xi: list[Candidate]) -> tuple[float | None, float | None]:
    """E[pts] del once y su techo P90. Sin dato de techo, el techo no se inventa."""
    total = 0.0
    ceiling_total = 0.0
    ceiling_found = False
    points_found = False
    for candidate in xi:
        ev = candidate.jornada_ev
        if isinstance(ev, (int, float)) and not isinstance(ev, bool):
            total += float(ev)
            points_found = True
        ceiling = candidate.ceiling_points
        share = candidate.p_titular if candidate.p_titular is not None else 1.0
        if isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool) and ceiling > 0:
            ceiling_total += float(ceiling) * float(share)
            ceiling_found = True
    return (round(total, 4) if points_found else None), (round(ceiling_total, 4) if ceiling_found else None)


def solve_lineup(
    candidates: list[Candidate],
    *,
    cash: int | None,
    weights: ObjectiveWeights | None = None,
    solver: pulp.LpSolver | None = None,
    listings: list[dict[str, Any]] | None = None,
    owned_ids: set[str] | None = None,
    posture: RiskPosture | None = None,
) -> dict[str, Any]:
    """Once óptimo. Caja negativa o plantilla imposible: la jornada vale 0.

    Si no hay 11 elegibles para una formación válida, el césped no se queda
    vacío: entra el mejor once parcial y la lista de huecos por posición.
    """
    scale = weights or ObjectiveWeights()
    stance = posture or NEUTRAL_POSTURE
    penalties = {"empty_slot_lambda": INFINITE_LAMBDA, "negative_cash_lambda": INFINITE_LAMBDA}
    eligible = [candidate for candidate in candidates if candidate.eligible]
    excluded = [_candidate_payload(candidate) for candidate in candidates if not candidate.eligible]
    void_reasons: list[str] = []
    if isinstance(cash, int) and cash < 0:
        void_reasons.append("negative_cash")
    if len(eligible) < XI_SIZE:
        void_reasons.append("empty_slot")
    counts = _position_counts(eligible)
    if not void_reasons and not _any_formation_fits(counts):
        void_reasons.append("empty_slot")
    base = {
        "penalties": penalties,
        "cash_eur": cash if isinstance(cash, int) else None,
        "cash_known": isinstance(cash, int),
        "cash_negative": isinstance(cash, int) and cash < 0,
        "eligible_count": len(eligible),
        "eligible_counts": counts,
        "excluded": excluded,
        "calibration_note": _CALIBRATION_NOTE,
        "weights": {"p_titular": scale.p_titular, "expected_points": scale.expected_points},
        "posture": {
            "name": stance.name,
            "ceiling_weight": stance.ceiling_weight,
            "titular_exponent": stance.titular_exponent,
        },
    }
    if void_reasons:
        xi_candidates: list[Candidate] = []
        gaps: list[dict[str, Any]] = []
        formation = None
        placed_counts = {position: 0 for position in POSITIONS}
        benched = list(eligible)
        if "empty_slot" in void_reasons and eligible:
            formation, xi_candidates, gaps = _best_partial(eligible, listings)
            placed_counts = _position_counts(xi_candidates)
            chosen_keys = {candidate.key for candidate in xi_candidates}
            benched = [candidate for candidate in eligible if candidate.key not in chosen_keys]
        # La jornada vale 0, pero los puntos del once parcial SÍ existen: se
        # reportan para que el plan pueda compararlos con el once guardado y
        # pedir un cierre de hueco con cifras reales.
        partial_points, _ = _lineup_points(xi_candidates)
        return {
            **base,
            "matchday_void": True,
            "void_reasons": void_reasons,
            "partial": bool(xi_candidates),
            "formation": formation,
            "counts": placed_counts,
            "gaps": gaps,
            "market_fills": market_fills(gaps, listings, owned_ids),
            "xi": [_candidate_payload(candidate) for candidate in xi_candidates],
            "benched": [_candidate_payload(candidate) for candidate in benched],
            "objective": 0.0,
            "expected_points": 0.0,
            "lineup_expected_points": partial_points,
            "solver": {"name": None, "status": "Partial" if xi_candidates else "NotSolved"},
        }

    problem = pulp.LpProblem("laliga_xi", pulp.LpMaximize)
    chosen = {
        candidate.key: pulp.LpVariable(f"x_{index}", cat=pulp.LpBinary)
        for index, candidate in enumerate(eligible)
    }
    formation_vars = {
        name: pulp.LpVariable(f"f_{name.replace('-', '_')}", cat=pulp.LpBinary) for name in FORMATIONS
    }
    problem += pulp.lpSum(formation_vars.values()) == 1, "una_formacion"
    problem += pulp.lpSum(chosen.values()) == XI_SIZE, "once_exacto"
    for position in POSITIONS:
        problem += (
            pulp.lpSum(chosen[candidate.key] for candidate in eligible if candidate.position == position)
            == pulp.lpSum(FORMATIONS[name][position] * formation_vars[name] for name in FORMATIONS)
        ), f"cupo_{position}"
    problem += pulp.lpSum(chosen[candidate.key] * candidate.objective for candidate in eligible)
    engine = solver or pulp.PULP_CBC_CMD(msg=False, timeLimit=10)
    status_code = problem.solve(engine)
    status_name = pulp.LpStatus.get(status_code, "NotSolved")
    if status_name != "Optimal":
        return _partial_void(
            base,
            eligible,
            listings,
            owned_ids,
            solver_name=engine.name,
            solver_status=status_name,
        )

    selected = [candidate for candidate in eligible if (chosen[candidate.key].value() or 0.0) > 0.5]
    benched = [candidate for candidate in eligible if candidate not in selected]
    selected_counts = _position_counts(selected)
    formation = _formation_name(formation_vars, selected_counts)
    if formation is None or len(selected) != XI_SIZE:
        return _partial_void(
            base,
            eligible,
            listings,
            owned_ids,
            solver_name=engine.name,
            solver_status=status_name,
        )
    objective = round(sum(candidate.objective for candidate in selected), 4)
    xi_points, xi_ceiling = _lineup_points(selected)
    return {
        **base,
        "matchday_void": False,
        "void_reasons": [],
        "partial": False,
        "formation": formation,
        "counts": selected_counts,
        "gaps": [],
        "market_fills": [],
        "xi": [_candidate_payload(candidate) for candidate in selected],
        "benched": [_candidate_payload(candidate) for candidate in benched],
        "objective": objective,
        # ``objective`` es lo que maximiza el solver (puede incluir postura de
        # liga o pesos). Los puntos del once son otra cifra: suman jornada_ev
        # y son la única comparable con un once guardado.
        "expected_points": objective,
        "lineup_expected_points": xi_points,
        "lineup_ceiling_points": xi_ceiling,
        "solver": {"name": engine.name, "status": status_name},
    }


def optimize_from_documents(
    squads: dict[str, Any],
    trends: dict[str, Any] | None,
    *,
    weights: ObjectiveWeights | None = None,
    cache: ResponseCache | None = None,
    fresh: bool = False,
    market: dict[str, Any] | None = None,
    posture: RiskPosture | None = None,
) -> dict[str, Any]:
    squad = own_squad(squads)
    if squad is None:
        return _failure(
            "optimize",
            "own_squad_missing",
            "La plantilla propia no está en squads. Sin ella no hay once.",
            league_id=squads.get("league_id"),
        )
    scale = weights or ObjectiveWeights()
    stance = posture or NEUTRAL_POSTURE
    indexed = index_trends(trends)
    from toolbox.scrapers import refresh_squad_titularity_in_index

    refresh_squad_titularity_in_index(squad, indexed, fresh=fresh)
    roster = candidates_from_squad(squad, indexed, weights=scale, posture=stance)
    cash = squad.get("cash") if isinstance(squad.get("cash"), int) else None
    listings = [row for row in (market or {}).get("listings") or [] if isinstance(row, dict)] if isinstance(market, dict) else []
    owned_ids = {candidate.player_id for candidate in roster if candidate.player_id}
    fingerprint = {
        "cash": cash,
        "posture": stance.name,
        "weights": {"p_titular": scale.p_titular, "expected_points": scale.expected_points},
        "players": [
            {
                "key": candidate.key,
                "position": candidate.position,
                "objective": candidate.objective,
                "excluded": candidate.excluded_reason,
                "points": candidate.expected_points,
                "p": candidate.p_titular,
            }
            for candidate in roster
        ],
        "market": [
            (row.get("player_id"), row.get("position"), row.get("sale_price"))
            for row in listings
        ],
    }

    def build() -> dict[str, Any]:
        solved = solve_lineup(
            roster,
            cash=cash,
            weights=scale,
            listings=listings,
            owned_ids=owned_ids,
            posture=stance,
        )
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "command": "optimize",
            "league_id": squads.get("league_id"),
            "team_id": squad.get("team_id"),
            "manager_name": squad.get("manager_name"),
            "partial": bool(trends.get("partial")) if isinstance(trends, dict) else True,
            "from_cache": False,
            **solved,
        }

    document = _cached("optimize", fingerprint, build, cache=cache, fresh=fresh)
    # La caché del once puede ser anterior a image_url: se rellena desde el roster actual.
    images = {
        candidate.player_id: candidate.image_url
        for candidate in roster
        if candidate.player_id and isinstance(candidate.image_url, str)
    }
    listing_images = {
        row["player_id"]: row["image_url"]
        for row in listings
        if isinstance(row.get("player_id"), str) and isinstance(row.get("image_url"), str)
    }
    for key in ("xi", "benched", "excluded"):
        for row in document.get(key) or []:
            if not isinstance(row, dict):
                continue
            player_id = row.get("player_id")
            if isinstance(player_id, str) and not isinstance(row.get("image_url"), str):
                row["image_url"] = images.get(player_id) or listing_images.get(player_id)
    for gap in list(document.get("gaps") or []) + list(document.get("market_fills") or []):
        if not isinstance(gap, dict):
            continue
        for row in gap.get("options") or []:
            if not isinstance(row, dict):
                continue
            player_id = row.get("player_id")
            if isinstance(player_id, str) and not isinstance(row.get("image_url"), str):
                row["image_url"] = listing_images.get(player_id) or images.get(player_id)
    return document


def build_optimize_command(
    client: CatalogClient,
    *,
    league: str | None,
    fresh: bool,
    trends_document: dict[str, Any] | None = None,
    cache: ResponseCache | None = None,
) -> dict[str, Any]:
    squads = client.squads_document(league, fresh=fresh)
    trends = trends_document
    if trends is None:
        from toolbox.scrapers import build_trends

        trends = build_trends(league=league, fresh=fresh, laliga=client)
    store = cache if cache is not None else _default_cache()
    try:
        return optimize_from_documents(squads, trends, cache=store, fresh=fresh)
    finally:
        if cache is None:
            store.close()


def played_points(row: dict[str, Any] | None) -> float | None:
    """Puntos esperados de jornada de un jugador si juega (el pase por titularidad ya va dentro).

    ``jornada_ev`` es el valor esperado de jornada con titularidad. Para
    comparar un once contra otro hay que sumar la misma métrica: nunca
    ``expected_points`` (puntos condicionados a ser titular) contra ``jornada_ev``.
    """
    if not isinstance(row, dict):
        return None
    ev = row.get("jornada_ev")
    if isinstance(ev, (int, float)) and not isinstance(ev, bool):
        return float(ev)
    # ``jornada_ev: None`` explícito no puede tumbar el pase a expected_points.
    pts = row.get("expected_points")
    if isinstance(pts, (int, float)) and not isinstance(pts, bool):
        return float(pts)
    return None

def lineup_points(xi: list[dict[str, Any]] | None) -> tuple[float | None, list[str]]:
    """Suma E[pts] de un once. Devuelve la suma y los jugadores sin dato de puntos."""
    rows = [row for row in xi or [] if isinstance(row, dict)]
    if not rows:
        return None, []
    total = 0.0
    missing: list[str] = []
    for row in rows:
        value = played_points(row)
        if value is None:
            name = row.get("nickname") or row.get("name") or row.get("player_id") or "jugador"
            missing.append(str(name))
            continue
        total += value
    return round(total, 4), missing


def projected_lineup_points(document: dict[str, Any] | None) -> float | None:
    """Suma E[pts] del XI usando ``jornada_ev`` cuando existe."""
    if not isinstance(document, dict):
        return None
    total, _ = lineup_points(document.get("xi") if isinstance(document.get("xi"), list) else None)
    return round(total, 2) if total is not None else None


def _candidate_payload(candidate: Candidate) -> dict[str, Any]:
    return {
        "player_id": candidate.player_id,
        "name": candidate.name,
        "nickname": candidate.nickname,
        "position": candidate.position,
        "club": candidate.club,
        "image_url": candidate.image_url,
        "p_titular": candidate.p_titular,
        "expected_points": candidate.expected_points,
        "jornada_ev": candidate.jornada_ev,
        "points_if_starts": candidate.points_if_starts,
        "relevo_bonus": candidate.relevo_bonus,
        "objective": candidate.objective,
        "components": candidate.components,
        "player_status": candidate.player_status,
        "excluded_reason": candidate.excluded_reason,
        "p_titular_source": candidate.p_titular_source,
        "ceiling_points": candidate.ceiling_points,
    }


def _partial_void(
    base: dict[str, Any],
    eligible: list[Candidate],
    listings: list[dict[str, Any]] | None,
    owned_ids: set[str] | None,
    *,
    solver_name: str | None,
    solver_status: str,
) -> dict[str, Any]:
    formation, xi_candidates, gaps = _best_partial(eligible, listings) if eligible else (None, [], [])
    chosen_keys = {candidate.key for candidate in xi_candidates}
    benched = [candidate for candidate in eligible if candidate.key not in chosen_keys]
    return {
        **base,
        "matchday_void": True,
        "void_reasons": ["empty_slot"],
        "partial": bool(xi_candidates),
        "formation": formation,
        "counts": _position_counts(xi_candidates),
        "gaps": gaps,
        "market_fills": market_fills(gaps, listings, owned_ids),
        "xi": [_candidate_payload(candidate) for candidate in xi_candidates],
        "benched": [_candidate_payload(candidate) for candidate in benched],
        "objective": 0.0,
        "expected_points": 0.0,
        "lineup_expected_points": _lineup_points(xi_candidates)[0],
        "solver": {"name": solver_name, "status": "Partial" if xi_candidates else solver_status},
    }


def _position_counts(candidates: list[Candidate]) -> dict[str, int]:
    counts = {position: 0 for position in POSITIONS}
    for candidate in candidates:
        if candidate.position in counts:
            counts[candidate.position] += 1
    return counts


def _any_formation_fits(counts: dict[str, int]) -> bool:
    return any(all(counts.get(position, 0) >= slots[position] for position in POSITIONS) for slots in FORMATIONS.values())


def _formation_name(formation_vars: dict[str, pulp.LpVariable], counts: dict[str, int]) -> str | None:
    selected = [name for name, variable in formation_vars.items() if (variable.value() or 0.0) > 0.5]
    if len(selected) == 1 and FORMATIONS[selected[0]] == counts:
        return selected[0]
    matches = [name for name, slots in FORMATIONS.items() if slots == counts]
    if len(matches) == 1:
        return matches[0]
    return None


def _failure(command: str, code: str, message: str, *, league_id: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "league_id": league_id if isinstance(league_id, str) else None,
        "from_cache": False,
        "error": {"code": code, "message": message, "status": None},
    }


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached(
    kind: str,
    fingerprint: dict[str, Any],
    build: Any,
    *,
    cache: ResponseCache | None,
    fresh: bool,
    ttl: float = OPTIMIZE_TTL_SECONDS,
) -> dict[str, Any]:
    if cache is None or fresh or ttl <= 0:
        document = build()
        document["from_cache"] = False
        return document
    url = f"phase3://{kind}/{_digest(fingerprint)}"
    cached = cache.get_json(url)
    if isinstance(cached, dict) and cached.get("ok") is True:
        hit = dict(cached)
        hit["from_cache"] = True
        return hit
    document = build()
    document["from_cache"] = False
    if document.get("ok") is True:
        cache.put_json(url, document, ttl)
    return document


def _default_cache() -> ResponseCache:
    return ResponseCache()

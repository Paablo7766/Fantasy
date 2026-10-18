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
from dataclasses import dataclass
from typing import Any, Protocol

import pulp

from toolbox.cache import ResponseCache
from toolbox.normalize import SCHEMA_VERSION, exclusion_from_status, official_week_points

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
STARTER_WEEK_SHARE = 0.20
_INJURED = {"lesionado", "baja", "injured", "out"}
_CALIBRATION_NOTE = (
    "Puntos esperados = p_titular * (xg * tarifa de gol OPTA + xa * 3 + bonus Relevo). "
    "Porterías a cero, penaltis y tarjetas no entran: el JSON no trae su probabilidad. "
    "El bonus Relevo solo se suma si llega como entero de 0 a 4. "
    "Un emparejamiento con matching_confidence < 0.85 no aporta titularidad ni forma. "
    "Si el scraper no trae titularidad, el % sale de las últimas 5 jornadas oficiales: "
    "20 puntos porcentuales por cada una con weekPoints > 0."
)


class CatalogClient(Protocol):
    def market_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]: ...

    def squads_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ObjectiveWeights:
    p_titular: float = P_TITULAR_WEIGHT
    expected_points: float = EXPECTED_POINTS_WEIGHT


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
    relevo_bonus: int | None
    objective: float
    components: dict[str, float]
    player_status: str | None
    excluded_reason: str | None
    p_titular_source: str | None = None

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


def sell_signal(trend: dict[str, Any] | None) -> bool:
    """Pico de valor: venía subiendo y el tramo de 1 a 3 días se aplana o cae.

    ``acceleration`` > 0 o un ``price_delta_3`` > 0 cuentan como subida previa.
    El cierre es ``price_delta`` <= 0, o una ventana de 3 días aún positiva
    cuya aceleración ya no empuja.
    """
    if not isinstance(trend, dict):
        return False
    day = _euros_signed(trend.get("price_delta"))
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
    """20 % por cada una de las últimas 5 jornadas con puntos oficiales > 0.

    Sin serie oficial no se inventa un porcentaje.
    """
    weeks = official_week_points(player)
    if not weeks:
        return None
    played = sum(1 for score in weeks if score > 0)
    return round(min(1.0, played * STARTER_WEEK_SHARE), 4)


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
    official = player.get("player_status")
    if isinstance(official, str) and official.strip():
        return exclusion_from_status(official)
    sources: list[dict[str, Any]] = [player]
    if trend_usable(trend):
        sources.append(trend or {})
    for source in sources:
        fitness = source.get("fitness")
        if isinstance(fitness, str) and fitness.strip().lower() in _INJURED:
            return "lesionado"
        sanction = source.get("sanction") if isinstance(source.get("sanction"), dict) else {}
        if source.get("suspended") is True or sanction.get("suspended") is True:
            return "sancionado"
    return None


def expected_opta_points(position: str, form: dict[str, Any] | None) -> tuple[float, dict[str, float]]:
    """Tarifa OPTA aplicada a xG y xA tal como vienen. Sin reescalar."""
    components: dict[str, float] = {}
    if position not in GOAL_POINTS or not isinstance(form, dict):
        return 0.0, components
    total = 0.0
    xg = form.get("xg")
    xa = form.get("xa")
    if isinstance(xg, (int, float)) and not isinstance(xg, bool):
        points = round(float(xg) * GOAL_POINTS[position], 4)
        components["xg"] = points
        total += points
    if isinstance(xa, (int, float)) and not isinstance(xa, bool):
        points = round(float(xa) * ASSIST_POINTS, 4)
        components["xa"] = points
        total += points
    return round(total, 4), components


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


def candidate_from_player(
    player: dict[str, Any],
    trend: dict[str, Any] | None,
    *,
    weights: ObjectiveWeights,
    ordinal: int,
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
    form = usable.get("form") if usable and isinstance(usable.get("form"), dict) else None
    if form is None and isinstance(player.get("form"), dict):
        form = player["form"]
    opta, components = expected_opta_points(position, form)
    bonus = relevo_bonus(player.get("relevo_bonus"))
    if bonus is None and usable is not None:
        bonus = relevo_bonus(usable.get("relevo_bonus"))
    points = round(opta + (float(bonus) if bonus is not None else 0.0), 4)
    return Candidate(
        key=f"{ordinal}:{key}",
        player_id=player_id,
        name=player.get("name") if isinstance(player.get("name"), str) else None,
        nickname=player.get("nickname") if isinstance(player.get("nickname"), str) else None,
        position=position,
        club=player.get("club") if isinstance(player.get("club"), str) else None,
        p_titular=p_titular,
        expected_points=points,
        relevo_bonus=bonus,
        objective=objective_value(
            p_titular=p_titular,
            expected_points=opta,
            relevo=bonus,
            weights=weights,
        ),
        components=components,
        player_status=player.get("player_status") if isinstance(player.get("player_status"), str) else None,
        excluded_reason=reason,
        p_titular_source=p_titular_source,
    )


def candidates_from_squad(
    squad: dict[str, Any],
    trends: dict[str, dict[str, Any]],
    *,
    weights: ObjectiveWeights | None = None,
) -> list[Candidate]:
    scale = weights or ObjectiveWeights()
    players = squad.get("players") if isinstance(squad.get("players"), list) else []
    built: list[Candidate] = []
    for ordinal, player in enumerate(players):
        if not isinstance(player, dict):
            continue
        candidate = candidate_from_player(player, trends.get(str(player.get("player_id") or "")), weights=scale, ordinal=ordinal)
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
                key=lambda candidate: (candidate.objective, candidate.expected_points, candidate.p_titular or 0.0),
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
        score = round(sum(candidate.objective for candidate in placed), 4)
        rank = (len(placed), -uncovered, -cost, score, name)
        if best is None or rank > best[0]:
            best = (rank, name, placed, gaps)
    if best is None:
        return None, [], []
    return best[1], best[2], best[3]


def solve_lineup(
    candidates: list[Candidate],
    *,
    cash: int | None,
    weights: ObjectiveWeights | None = None,
    solver: pulp.LpSolver | None = None,
    listings: list[dict[str, Any]] | None = None,
    owned_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Once óptimo. Caja negativa o plantilla imposible: la jornada vale 0.

    Si no hay 11 elegibles para una formación válida, el césped no se queda
    vacío: entra el mejor once parcial y la lista de huecos por posición.
    """
    scale = weights or ObjectiveWeights()
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
        "expected_points": objective,
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
    indexed = index_trends(trends)
    roster = candidates_from_squad(squad, indexed, weights=scale)
    cash = squad.get("cash") if isinstance(squad.get("cash"), int) else None
    listings = [row for row in (market or {}).get("listings") or [] if isinstance(row, dict)] if isinstance(market, dict) else []
    owned_ids = {candidate.player_id for candidate in roster if candidate.player_id}
    fingerprint = {
        "cash": cash,
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
        solved = solve_lineup(roster, cash=cash, weights=scale, listings=listings, owned_ids=owned_ids)
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

    return _cached("optimize", fingerprint, build, cache=cache, fresh=fresh)


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


def _candidate_payload(candidate: Candidate) -> dict[str, Any]:
    return {
        "player_id": candidate.player_id,
        "name": candidate.name,
        "nickname": candidate.nickname,
        "position": candidate.position,
        "club": candidate.club,
        "p_titular": candidate.p_titular,
        "expected_points": candidate.expected_points,
        "relevo_bonus": candidate.relevo_bonus,
        "objective": candidate.objective,
        "components": candidate.components,
        "player_status": candidate.player_status,
        "excluded_reason": candidate.excluded_reason,
        "p_titular_source": candidate.p_titular_source,
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

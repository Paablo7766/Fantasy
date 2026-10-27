"""Value Investing puro sobre datos ya cacheados.

Tres preguntas, una sola foto y **cero peticiones nuevas**:

1. ¿Cuánto cuesta cada punto que este jugador produce de verdad?
   ``coste por punto = valor de mercado / mediana de puntos``. Se compara con
   la mediana de su posición: un MC de 2 M que puntúa como uno de 6 M es una
   ineficiencia del mercado, no una corazonada.
2. ¿Hacia dónde va el dinero de la plataforma?
   ``acceleration > 0`` con ``price_delta > 0`` es la segunda derivada del
   precio: hoy sube más de lo que subió ayer. Eso es acumulación de smart
   money antes de que la noticia llegue a la liga.
3. ¿Sobrevive el chollo a la varianza?
   ``blank_rate`` = probabilidad histórica de puntuar <= 2. Un activo barato
   que deja la jornada en blanco una de cada dos veces no es una ganga, es
   una trampa. El ranking final mezcla valor, supervivencia y momentum.

El módulo no imprime, no escribe y no sale a la red: lee el catálogo público
(ya en ``.cache/``), la tabla de mercado y las señales de FútbolFantasy que
viajan en la foto del tablero.
"""

from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from toolbox.cache import cache_root
from toolbox.normalize import SCHEMA_VERSION

logger = logging.getLogger("fantasy.quant")

POSITIONS = ("POR", "DEF", "MC", "DEL")
_POSITION_BY_ID = {"1": "POR", "2": "DEF", "3": "MC", "4": "DEL"}
BLANK_THRESHOLD = 2.0
MIN_GAMES = 3
MIN_MEDIAN_POINTS = 1.0
# Un activo es «radicalmente» más barato cuando su coste por punto queda al
# menos un 30 % por debajo de la mediana de su posición.
UNDERVALUED_DISCOUNT = 0.30
# «Cerca del umbral»: aún no es una compra, pero se vigila. Dos tercios del
# descuento exigido ya es una señal, no una casualidad.
NEAR_DISCOUNT = 0.20
MAX_BLANK_RATE = 0.40
# ``blank_rate`` es una probabilidad, no un umbral binario: el ranking la usa
# como factor de supervivencia (``1 - blank_rate``). El veredicto TOXICO solo
# se reserva a una racha casi segura, imposible de compensar con precio.
TOXIC_BLANK_RATE = 0.75
DEFAULT_LIMIT = 12
MAX_CANDIDATES = 40

# Pesos del ranking final. Están juntos y a la vista: el orden no es magia.
W_VALUE = 0.55
W_DISCOUNT = 0.25
W_MOMENTUM = 0.20


# --------------------------------------------------------------------------- #
# Tipos suaves: la API mezcla str, int y None en el mismo campo.
# --------------------------------------------------------------------------- #


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number):
        return None
    return number


def _int(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _position(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in POSITIONS:
        return text
    return _POSITION_BY_ID.get(text)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * max(0.0, min(1.0, q))
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Emparejamiento de nombres: FútbolFantasy usa el nombre completo y el
# catálogo el corto («Antonio Sivera» vs «Sivera»). Se empareja por apellido.
# --------------------------------------------------------------------------- #


def _name_tokens(text: Any) -> list[str]:
    if not isinstance(text, str):
        return []
    try:
        from toolbox.matching import normalize_name

        folded = normalize_name(text)
    except Exception:  # noqa: BLE001 — sin matching, el apellido en crudo
        folded = text.lower()
    return [token for token in folded.split() if token]


class NameMatcher:
    """Índice por apellido con desempate por posición y club.

    Solo se acepta un emparejamiento por debajo de ``threshold`` si es único:
    dos candidatos a menos de dos centésimas se tratan como ambiguos y el
    jugador se queda sin señal en lugar de recibir la de otro.
    """

    def __init__(self, catalog: Iterable[dict[str, Any]], *, threshold: float = 0.90) -> None:
        self.threshold = threshold
        self._by_surname: dict[str, list[dict[str, Any]]] = {}
        for row in catalog:
            if not isinstance(row, dict):
                continue
            for key in (row.get("nickname"), row.get("name")):
                tokens = _name_tokens(key)
                if not tokens:
                    continue
                self._by_surname.setdefault(tokens[-1], []).append(row)
                break

    def match(self, name: Any, position: Any = None) -> tuple[dict[str, Any] | None, float]:
        tokens = _name_tokens(name)
        if not tokens:
            return None, 0.0
        candidates = self._by_surname.get(tokens[-1]) or []
        if not candidates:
            return None, 0.0
        wanted = _position(position)
        scored: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            label = candidate.get("nickname") or candidate.get("name") or ""
            score = _surname_score(label, tokens)
            if wanted is not None:
                theirs = _position(candidate.get("positionId", candidate.get("position")))
                if theirs is not None:
                    score += 0.03 if theirs == wanted else -0.40
            scored.append((round(score, 4), candidate))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
        best_score, best = scored[0]
        if len(scored) > 1 and abs(scored[1][0] - best_score) < 0.02:
            return None, best_score
        if best_score < self.threshold:
            return None, best_score
        return best, best_score


def _surname_score(catalog_label: Any, incoming: list[str]) -> float:
    tokens = _name_tokens(catalog_label)
    if not tokens or not incoming:
        return 0.0
    if tokens[-1] != incoming[-1]:
        return 0.0
    score = 0.90
    if tokens[0] == incoming[0]:
        return 0.98
    if len(tokens[0]) == 1 and incoming[0].startswith(tokens[0]):
        return 0.95
    if tokens[0][0] == incoming[0][0]:
        score = 0.92
    try:
        from toolbox.matching import name_similarity

        return max(score, min(0.94, name_similarity(catalog_label, " ".join(incoming))))
    except Exception:  # noqa: BLE001
        return score


# --------------------------------------------------------------------------- #
# Series de puntos: catálogo (weekPoints) y plantillas (week_points).
# --------------------------------------------------------------------------- #


def week_series(player: dict[str, Any]) -> list[float]:
    """Serie completa de jornadas, ordenada por ``weekNumber`` cuando lo trae.

    Acepta el catálogo (``weekPoints: [{weekNumber, points}]``), la plantilla
    normalizada (``week_points: [..]``) y ``lastStats``. No recorta a 5: la
    mediana necesita toda la muestra disponible para no depender de una
    jornada buena.
    """
    if not isinstance(player, dict):
        return []
    raw = player.get("weekPoints")
    if raw is None:
        raw = player.get("week_points")
    if raw is None:
        raw = player.get("lastStats")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        value = _number(raw)
        return [] if value is None else [value]
    if not isinstance(raw, list):
        return []

    numbered: list[tuple[float, int, float]] = []
    plain: list[float] = []
    for index, item in enumerate(raw):
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            value = _number(item)
            if value is not None:
                plain.append(value)
            continue
        if not isinstance(item, dict):
            continue
        value = _number(
            item.get("points")
            if item.get("points") is not None
            else item.get("weekPoints")
            if item.get("weekPoints") is not None
            else item.get("totalPoints")
        )
        if value is None:
            continue
        week = _number(item.get("weekNumber", item.get("week")))
        numbered.append((week if week is not None else float(index), index, value))

    if numbered and len(numbered) >= len(plain):
        numbered.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in numbered]
    return plain


def point_stats(series: Iterable[float]) -> dict[str, Any]:
    """Mediana, media, volatilidad y riesgo de dejarla en blanco."""
    values = [float(value) for value in series if value is not None]
    games = len(values)
    if games == 0:
        return {
            "games": 0,
            "median_points": None,
            "mean_points": None,
            "stdev_points": None,
            "blank_rate": None,
            "floor_rate": None,
            "boom_rate": None,
            "best_points": None,
            "worst_points": None,
        }
    blank = sum(1 for value in values if value <= BLANK_THRESHOLD)
    return {
        "games": games,
        "median_points": round(statistics.median(values), 4),
        "mean_points": round(statistics.fmean(values), 4),
        "stdev_points": round(statistics.pstdev(values), 4) if games > 1 else 0.0,
        "blank_rate": round(blank / games, 4),
        # Un cero es una jornada perdida; un <= 2 es un activo que no paga.
        "floor_rate": round(sum(1 for value in values if value <= 0.0) / games, 4),
        "boom_rate": round(sum(1 for value in values if value >= 8.0) / games, 4),
        "best_points": round(max(values), 2),
        "worst_points": round(min(values), 2),
    }


# --------------------------------------------------------------------------- #
# 1. Valor intrínseco: el «PER» del jugador.
# --------------------------------------------------------------------------- #


def _catalog_entry(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normaliza una fila del catálogo público a lo que necesita el motor."""
    if not isinstance(row, dict):
        return None
    player_id = row.get("id", row.get("player_id"))
    if player_id is None or isinstance(player_id, bool):
        return None
    player_id = str(player_id).strip()
    if not player_id:
        return None
    stats = point_stats(week_series(row))
    average = _number(row.get("averagePoints", row.get("average_points")))
    club = row.get("club") if isinstance(row.get("club"), str) else None
    if club is None:
        club = _club_from_team(row.get("teamId", row.get("team_id")))
    return {
        "player_id": player_id,
        "name": row.get("name") if isinstance(row.get("name"), str) else None,
        "nickname": row.get("nickname") if isinstance(row.get("nickname"), str) else None,
        "position": _position(row.get("positionId", row.get("position"))),
        "club": club,
        "image_url": row.get("image") if isinstance(row.get("image"), str) else row.get("image_url"),
        "market_value": _int(row.get("marketValue", row.get("market_value"))),
        "average_points": round(average, 4) if average is not None else None,
        **stats,
    }


def _club_from_team(team_id: Any) -> str | None:
    """``teamId`` del catálogo → nombre del club, sin deducirlo del payload."""
    if team_id is None or isinstance(team_id, bool):
        return None
    try:
        from toolbox.normalize import club_for_team

        club = club_for_team(team_id)
    except Exception:  # noqa: BLE001 — sin mapa, el club se queda vacío
        return None
    if isinstance(club, dict) and isinstance(club.get("name"), str):
        return club["name"]
    return None


def calculate_intrinsic_value(
    catalog_data: Iterable[dict[str, Any]] | dict[str, Any] | None,
    *,
    market_data: dict[str, Any] | None = None,
    squads_data: dict[str, Any] | None = None,
    momentum: dict[str, Any] | None = None,
    min_games: int = MIN_GAMES,
    min_median_points: float = MIN_MEDIAN_POINTS,
    undervalued_discount: float = UNDERVALUED_DISCOUNT,
) -> dict[str, Any]:
    """Coste por punto esperado y comparación contra la mediana de su posición.

    ``catalog_data`` puede ser la lista del catálogo, un documento con
    ``players``/``catalog`` o una foto del tablero. ``market_data`` y
    ``squads_data`` solo aportan precio y puntos cuando el catálogo no los
    trae (jugadores que únicamente aparecen en el mercado o en una plantilla).
    """
    rows = _rows_from(catalog_data, "players")
    seen: set[str] = set()
    players: list[dict[str, Any]] = []

    for row in rows:
        entry = _catalog_entry(row)
        if entry is None or entry["player_id"] in seen:
            continue
        seen.add(entry["player_id"])
        entry["price_source"] = "catalog"
        players.append(entry)

    # Relleno: un jugador en mercado o en plantilla que el catálogo no trajo.
    for origin, document in (("market", market_data), ("squads", squads_data)):
        for extra in _price_rows(document):
            entry = _catalog_entry(extra)
            if entry is None or entry["player_id"] in seen:
                continue
            seen.add(entry["player_id"])
            entry["price_source"] = origin
            players.append(entry)

    _attach_prices(players, market_data, squads_data)
    _attach_ownership(players, squads_data, market_data)
    _attach_momentum(players, market_data, momentum)

    # Mediana de cada serie: si no hay muestra, la media oficial es la única
    # referencia y se marca como tal para no venderla como rendimiento real.
    for entry in players:
        if entry["games"] >= min_games and entry["median_points"] is not None:
            entry["points_source"] = "weekPoints"
        elif entry["average_points"] is not None:
            entry["median_points"] = entry["average_points"]
            entry["points_source"] = "averagePoints"
        else:
            entry["points_source"] = None

        value = entry.get("market_value")
        median = entry.get("median_points")
        if isinstance(value, int) and value > 0 and isinstance(median, (int, float)) and median > 0:
            entry["cost_per_point_eur"] = round(value / float(median), 2)
            entry["points_per_million"] = round(float(median) / (value / 1_000_000), 4)
        else:
            entry["cost_per_point_eur"] = None
            entry["points_per_million"] = None

    baselines = _position_baselines(players, min_games=min_games, min_median_points=min_median_points)
    undervalued: list[dict[str, Any]] = []
    for entry in players:
        _apply_baseline(entry, baselines, undervalued_discount)
        if entry.get("undervalued") is True:
            undervalued.append(entry)

    undervalued.sort(
        key=lambda row: (
            -(row.get("discount_vs_position") or 0.0),
            -(row.get("median_points") or 0.0),
            row["player_id"],
        )
    )
    players.sort(
        key=lambda row: (
            row.get("cost_per_point_eur") is None,
            row.get("cost_per_point_eur") or math.inf,
            row["player_id"],
        )
    )
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "quant-intrinsic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample": {
            "players": len(players),
            "with_real_series": sum(1 for row in players if row.get("points_source") == "weekPoints"),
            "with_price": sum(1 for row in players if row.get("market_value")),
            "undervalued": len(undervalued),
        },
        "baselines": baselines,
        "players": players,
        "undervalued": undervalued,
    }


def _rows_from(document: Any, key: str) -> list[dict[str, Any]]:
    """Acepta lista, documento ``{key: [...]}`` o foto del tablero."""
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)]
    if not isinstance(document, dict):
        return []
    rows = document.get(key)
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if key != "catalog":
        catalog = document.get("catalog")
        if isinstance(catalog, list):
            return [row for row in catalog if isinstance(row, dict)]
    return []


def _price_rows(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("listings", "players", "squads"):
        bucket = document.get(key)
        if isinstance(bucket, list):
            for row in bucket:
                if not isinstance(row, dict):
                    continue
                target = row.get("players") if isinstance(row.get("players"), list) else row
                if isinstance(target, list):
                    rows.extend(item for item in target if isinstance(item, dict))
                elif isinstance(target, dict):
                    rows.append(target)
    return rows


def _attach_prices(players: list[dict[str, Any]], market_data: Any, squads_data: Any) -> None:
    """Completa valor de mercado, venta y serie con la foto local."""
    index = {row["player_id"]: row for row in players}
    for document in (market_data, squads_data):
        if not isinstance(document, dict):
            continue
        for bucket in ("listings", "squads", "players"):
            rows = document.get(bucket)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                members = row.get("players") if isinstance(row.get("players"), list) else [row]
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    player_id = str(member.get("player_id") or member.get("id") or "").strip()
                    entry = index.get(player_id)
                    if entry is None:
                        continue
                    value = _int(member.get("market_value", member.get("marketValue")))
                    change = _int(member.get("market_value_change", member.get("marketValueChange")))
                    sale = _int(member.get("sale_price", member.get("salePrice")))
                    if value and value > 0:
                        entry["market_value"] = value
                        entry["price_source"] = "market" if bucket == "listings" else entry.get("price_source") or "squads"
                    if sale and sale > 0:
                        entry["sale_price"] = sale
                    if change is not None:
                        entry["market_value_change"] = change
                    if not entry.get("games"):
                        stats = point_stats(week_series(member))
                        if stats["games"]:
                            entry.update(stats)
                    if entry.get("average_points") is None:
                        average = _number(member.get("average_points", member.get("averagePoints")))
                        if average is not None:
                            entry["average_points"] = round(average, 4)


def _attach_ownership(players: list[dict[str, Any]], squads_data: Any, market_data: Any) -> None:
    """Dueño real y precio de venta: sin esto el radar recomendaría lo imposible."""
    owners: dict[str, dict[str, Any]] = {}
    if isinstance(squads_data, dict):
        for squad in squads_data.get("squads") or []:
            if not isinstance(squad, dict):
                continue
            kind = "propio" if squad.get("is_self") is True else "rival"
            for member in squad.get("players") or []:
                if not isinstance(member, dict):
                    continue
                player_id = str(member.get("player_id") or member.get("id") or "").strip()
                if not player_id:
                    continue
                owners[player_id] = {
                    "owner": kind,
                    "team_id": squad.get("team_id") if isinstance(squad.get("team_id"), str) else None,
                    "manager_name": squad.get("manager_name") if isinstance(squad.get("manager_name"), str) else None,
                }
    listings: dict[str, dict[str, Any]] = {}
    if isinstance(market_data, dict):
        for row in market_data.get("listings") or []:
            if not isinstance(row, dict):
                continue
            player_id = str(row.get("player_id") or "").strip()
            if not player_id:
                continue
            listings[player_id] = {
                "sale_price": _int(row.get("sale_price")),
                "seller_team_id": row.get("seller_team_id") if isinstance(row.get("seller_team_id"), str) else None,
                "seller_manager": row.get("seller_manager") if isinstance(row.get("seller_manager"), str) else None,
                "listing_expires_at": row.get("listing_expires_at"),
            }

    for entry in players:
        player_id = entry["player_id"]
        owner = owners.get(player_id) or {}
        listing = listings.get(player_id) or {}
        entry["owner"] = owner.get("owner") or ("mercado" if listing else "libre")
        entry["team_id"] = owner.get("team_id") or listing.get("seller_team_id")
        entry["manager_name"] = owner.get("manager_name") or listing.get("seller_manager")
        entry["on_market"] = bool(listing)
        if listing.get("sale_price"):
            entry["sale_price"] = listing["sale_price"]
        if listing.get("listing_expires_at"):
            entry["listing_expires_at"] = listing["listing_expires_at"]
        # El radar solo firma lo que se puede firmar: agente libre o anunciado.
        entry["signable"] = entry["owner"] == "libre" or entry["on_market"] is True
        if entry["owner"] == "propio":
            entry["blocked_reason"] = "ya_en_plantilla"
        elif entry["on_market"] is True and entry["owner"] == "rival":
            entry["blocked_reason"] = None  # se puede comprar al rival
        elif entry["owner"] == "rival":
            entry["blocked_reason"] = "sin_clausula_ni_venta"


def _attach_momentum(
    players: list[dict[str, Any]],
    market_data: Any,
    momentum: dict[str, Any] | None = None,
) -> None:
    if momentum is None:
        momentum = detect_global_momentum(market_data)
    index = {row["player_id"]: row for row in momentum.get("players") or []}
    for entry in players:
        signal = index.get(entry["player_id"])
        if signal is None:
            entry["acceleration"] = None
            entry["price_delta"] = None
            entry["ff_price_delta"] = None
            entry["relative_acceleration"] = None
            entry["smart_money"] = None
            entry["momentum_signal"] = "sin_dato"
            continue
        entry["acceleration"] = signal.get("acceleration")
        entry["price_delta"] = signal.get("price_delta")
        entry["ff_price_delta"] = signal.get("ff_price_delta")
        entry["relative_acceleration"] = signal.get("relative_acceleration")
        entry["smart_money"] = signal.get("smart_money")
        entry["momentum_signal"] = signal.get("direction")
        if entry.get("market_value") is None and signal.get("market_value"):
            entry["market_value"] = signal["market_value"]


def _position_baselines(
    players: list[dict[str, Any]],
    *,
    min_games: int,
    min_median_points: float,
) -> dict[str, Any]:
    """Mediana de coste por punto y de puntos por posición.

    Solo entran jugadores con muestra real y mediana suficiente: un suplente
    con 3 jornadas de 0 puntos no puede mover el suelo de su posición.
    """
    buckets: dict[str, list[dict[str, Any]]] = {position: [] for position in POSITIONS}
    for entry in players:
        position = entry.get("position")
        if position not in buckets:
            continue
        if entry.get("points_source") != "weekPoints":
            continue
        cost = entry.get("cost_per_point_eur")
        median = entry.get("median_points")
        if not isinstance(cost, (int, float)) or cost <= 0:
            continue
        if not isinstance(median, (int, float)) or median < min_median_points:
            continue
        if entry.get("games", 0) < min_games:
            continue
        buckets[position].append(entry)

    baselines: dict[str, Any] = {}
    for position, rows in buckets.items():
        costs = [float(row["cost_per_point_eur"]) for row in rows]
        medians = [float(row["median_points"]) for row in rows]
        if not costs:
            baselines[position] = {
                "count": 0,
                "median_cost_per_point_eur": None,
                "p25_cost_per_point_eur": None,
                "median_points": None,
                "median_points_per_million": None,
            }
            continue
        median_cost = _percentile(costs, 0.5)
        median_points = _percentile(medians, 0.5)
        baselines[position] = {
            "count": len(rows),
            "median_cost_per_point_eur": round(float(median_cost), 2) if median_cost else None,
            "p25_cost_per_point_eur": round(float(_percentile(costs, 0.25) or 0.0), 2),
            "median_points": round(float(median_points), 4) if median_points is not None else None,
            "median_points_per_million": round(
                float(median_points) / (median_cost / 1_000_000), 4
            )
            if median_cost and median_points
            else None,
        }
    return baselines


def _apply_baseline(entry: dict[str, Any], baselines: dict[str, Any], discount: float) -> None:
    baseline = baselines.get(entry.get("position") or "")
    entry["position_baseline_cost_per_point_eur"] = (
        baseline.get("median_cost_per_point_eur") if isinstance(baseline, dict) else None
    )
    entry["position_baseline_points"] = baseline.get("median_points") if isinstance(baseline, dict) else None
    cost = entry.get("cost_per_point_eur")
    reference = entry["position_baseline_cost_per_point_eur"]
    if not isinstance(cost, (int, float)) or not isinstance(reference, (int, float)) or reference <= 0:
        entry["discount_vs_position"] = None
        entry["undervalued"] = False
        return
    gap = 1.0 - (float(cost) / float(reference))
    entry["discount_vs_position"] = round(gap, 4)
    median = entry.get("median_points")
    reference_points = entry.get("position_baseline_points")
    enough_points = (
        isinstance(median, (int, float))
        and isinstance(reference_points, (int, float))
        and reference_points > 0
        and float(median) >= float(reference_points) * 0.6
    )
    entry["undervalued"] = bool(
        gap >= discount
        and entry.get("points_source") == "weekPoints"
        and entry.get("games", 0) >= MIN_GAMES
        and enough_points
    )


# --------------------------------------------------------------------------- #
# 2. Momentum global: hacia dónde va el dinero de la plataforma.
# --------------------------------------------------------------------------- #


def _momentum_source(market_data: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(market_data, list):
        return "players", [row for row in market_data if isinstance(row, dict)]
    if not isinstance(market_data, dict):
        return "none", []
    trends = market_data.get("trends")
    if isinstance(trends, dict) and isinstance(trends.get("players"), list):
        return "trends", [row for row in trends["players"] if isinstance(row, dict)]
    players = market_data.get("players")
    if isinstance(players, list):
        return "trends", [row for row in players if isinstance(row, dict)]
    board_trends = market_data.get("trends")
    if isinstance(board_trends, list):
        return "trends", [row for row in board_trends if isinstance(row, dict)]
    listings = market_data.get("listings")
    if isinstance(listings, list):
        return "market", [row for row in listings if isinstance(row, dict)]
    return "none", []


def detect_global_momentum(
    market_data: Any,
    *,
    catalog: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``acceleration > 0`` y ``price_delta > 0``: el dinero acelera, no solo sube.

    ``price_delta`` es la variación del día. ``acceleration`` es cuánto cambió
    esa variación respecto a la de ayer. Positiva y con precio subiendo es
    acumulación: el mercado global compra antes de que la noticia sea pública.

    Con ``catalog`` se añade la tabla global de FútbolFantasy (los ~670
    jugadores con más movimiento de la plataforma, no solo los 148 de la liga).
    Las señales de la liga mandan: ya vienen con ``player_id`` exacto.
    """
    source, rows = _momentum_source(market_data)
    players: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _ingest(row: dict[str, Any], *, origin: str) -> None:
        player_id = row.get("player_id", row.get("id"))
        if player_id is None or isinstance(player_id, bool):
            return
        player_id = str(player_id).strip()
        if not player_id or player_id in seen:
            return
        seen.add(player_id)
        price_delta = _int(row.get("price_delta", row.get("market_value_change")))
        acceleration = _int(row.get("acceleration", row.get("price_acceleration")))
        ff_delta = _int(row.get("ff_price_delta"))
        # Acumulados de 2 y 3 días de la misma fuente, para poder declarar la
        # ventana temporal en la UI en vez de dejar dos cifras sin contexto.
        ff_delta_2 = _int(row.get("ff_price_delta_2"))
        ff_delta_3 = _int(row.get("ff_price_delta_3"))
        value = _int(row.get("market_value", row.get("marketValue", row.get("fantasy_price"))))
        sale = _int(row.get("sale_price"))

        reference = abs(price_delta) if price_delta else 0
        relative = round(acceleration / max(reference, 1), 4) if acceleration is not None else None
        if acceleration is None and price_delta is None:
            direction = "sin_dato"
        elif (price_delta or 0) > 0:
            direction = "up"
        elif (price_delta or 0) < 0:
            direction = "down"
        else:
            direction = "flat"
        smart_money = (
            bool(acceleration > 0 and (price_delta or 0) > 0) if acceleration is not None else None
        )
        players.append(
            {
                "player_id": player_id,
                "name": row.get("name") if isinstance(row.get("name"), str) else None,
                "nickname": row.get("nickname") if isinstance(row.get("nickname"), str) else None,
                "position": _position(row.get("position")) or (
                    row.get("position") if isinstance(row.get("position"), str) else None
                ),
                "club": row.get("club") if isinstance(row.get("club"), str) else None,
                "image_url": row.get("image_url") if isinstance(row.get("image_url"), str) else None,
                "market_value": value,
                "sale_price": sale,
                "price_delta": price_delta,
                "acceleration": acceleration,
                "ff_price_delta": ff_delta,
                "ff_price_delta_2": ff_delta_2,
                "ff_price_delta_3": ff_delta_3,
                "relative_acceleration": relative,
                "direction": direction,
                "smart_money": smart_money,
                "on_market": row.get("on_market") is True or sale is not None,
                "origin": origin,
            }
        )

    for row in rows:
        _ingest(row, origin=source)
    for row in catalog or ():
        if isinstance(row, dict):
            _ingest(row, origin="futbolfantasy")

    smart = [row for row in players if row["smart_money"]]
    smart.sort(
        key=lambda row: (
            -(row.get("acceleration") or 0),
            -(row.get("price_delta") or 0),
            row["player_id"],
        )
    )
    movers = [row for row in players if row["direction"] in {"up", "down"}]
    movers.sort(key=lambda row: (-abs(row.get("price_delta") or 0), row["player_id"]))
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "quant-momentum",
        "source": source,
        "counts": {
            "players": len(players),
            "up": sum(1 for row in players if row["direction"] == "up"),
            "down": sum(1 for row in players if row["direction"] == "down"),
            "flat": sum(1 for row in players if row["direction"] == "flat"),
            "unknown": sum(1 for row in players if row["direction"] == "sin_dato"),
            "smart_money": len(smart),
        },
        "smart_money": smart,
        "movers": movers,
        "players": players,
    }


def cached_global_market_rows(
    catalog: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Tabla de mercado de FútbolFantasy ya cacheada, con ``player_id`` resuelto.

    La foto de liga solo trae los ~148 jugadores de mi liga. La plataforma
    mueve precios en los 864 del catálogo: esta tabla es la que permite leer
    el smart money global antes de que llegue a mi liga. Cero red: si la
    página no está en ``.cache/``, se devuelve una lista vacía y el radar se
    queda con las señales de la liga.
    """
    matcher = NameMatcher(catalog or [])
    try:
        from toolbox.cache import ResponseCache
        from toolbox.net import no_network
        from toolbox.scrapers import FF_MARKET_URL, parse_market_board

        with no_network():
            cache = ResponseCache()
            try:
                body = cache.get_page_stale(FF_MARKET_URL)
            finally:
                cache.close()
        if not body:
            return []
        parsed = parse_market_board(body)
    except Exception as exc:  # noqa: BLE001 — sin tabla global se sigue con la liga
        logger.debug("Mercado global de FútbolFantasy no disponible: %s", exc)
        return []

    rows: list[dict[str, Any]] = []
    for item in parsed:
        player, _score = matcher.match(item.name, item.position)
        if player is None:
            continue
        rows.append(
            {
                "player_id": str(player.get("id")),
                "name": player.get("nickname") if isinstance(player.get("nickname"), str) else item.name,
                "nickname": item.name,
                "position": _position(player.get("positionId")) or _position(item.position),
                "club": item.club if isinstance(item.club, str) else None,
                "acceleration": item.acceleration,
                "price_delta": item.price_delta,
                "market_value": _int(player.get("marketValue")),
                "source": "futbolfantasy",
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# 3. Supervivencia y 4. ranking de compras.
# --------------------------------------------------------------------------- #


def _verdict(entry: dict[str, Any], *, max_blank_rate: float, min_games: int) -> tuple[str, list[str]]:
    """Veredicto del radar: primero se puede fichar, luego sobrevive, luego vale.

    ``COMPRAR`` no exige que el dinero acelere: el valor intrínseco y la
    supervivencia son la puerta; el momentum solo ordena y se marca aparte.
    ``VIGILAR`` es lo contrario: el dinero acelera pero el precio todavía no
    está por debajo de su posición, así que no hay margen de seguridad.
    """
    reasons: list[str] = []
    if entry.get("blocked_reason"):
        return "NO_FICHABLE", [entry["blocked_reason"]]
    if entry.get("signable") is not True:
        return "NO_FICHABLE", ["sin_venta_ni_libre"]
    if entry.get("points_source") != "weekPoints" or entry.get("games", 0) < min_games:
        return "SIN_MUESTRA", ["pocas_jornadas"]
    if entry.get("median_points") is None or entry.get("median_points") <= 0:
        return "SIN_MUESTRA", ["sin_puntos"]
    blank = entry.get("blank_rate")
    # ``blank_rate`` es una probabilidad de dejarla en blanco, no un veto: un
    # 45 % no es «siempre en blanco» ni un 55 % lo es. Solo se marca tóxico con
    # una racha casi segura; el resto entra en el ranking ya ponderado por
    # supervivencia en ``_score``.
    if isinstance(blank, (int, float)) and blank >= TOXIC_BLANK_RATE:
        return "TOXICO", ["blank_rate_alto"]
    if entry.get("fitness") in {"lesionado", "sancionado"}:
        return "NO_FICHABLE", [f"fitness_{entry['fitness']}"]
    if entry.get("undervalued") is True:
        reasons.append("infravalorado")
        if entry.get("smart_money") is True:
            reasons.append("smart_money")
        else:
            reasons.append("sin_momentum")
        if isinstance(blank, (int, float)) and blank >= TOXIC_BLANK_RATE * 0.75:
            reasons.append("volatilidad")
        return "COMPRAR", reasons
    discount = entry.get("discount_vs_position")
    if isinstance(discount, (int, float)) and discount >= NEAR_DISCOUNT:
        # Cerca del umbral: no hay margen de seguridad para comprar, pero
        # tampoco se paga de más. Es la lista de la que saldrá la próxima compra.
        reasons.append("cerca_del_umbral")
        if entry.get("smart_money") is True:
            reasons.append("smart_money")
        return "VIGILAR", reasons
    if entry.get("smart_money") is True:
        return "VIGILAR", ["precio_en_linea", "smart_money"]
    return "MERCADO", ["precio_en_linea"]


def _score(entry: dict[str, Any], baselines: dict[str, Any]) -> float | None:
    """Ranking 0-100: valor (55 %), descuento (25 %) y momentum (20 %)."""
    value = entry.get("market_value")
    median = entry.get("median_points")
    blank = entry.get("blank_rate")
    if not isinstance(value, int) or value <= 0 or not isinstance(median, (int, float)) or median <= 0:
        return None
    survival = 1.0 - (float(blank) if isinstance(blank, (int, float)) else 0.35)
    survival = _clamp(survival)
    risk_adjusted_ppm = (float(median) * survival) / (value / 1_000_000)
    entry["risk_adjusted_points_per_million"] = round(risk_adjusted_ppm, 4)
    # ``blank_rate`` no es una puerta que se cruza: es la probabilidad de que la
    # jornada salga en blanco. El propio ranking ya la descuenta en
    # ``survival``, así que castigarla otra vez como componente restaba dos
    # veces y aplastaba al jugador barato de racha irregular.
    entry["survival_component"] = round(survival, 4)

    baseline = baselines.get(entry.get("position") or "") or {}
    reference_ppm = baseline.get("median_points_per_million")
    if isinstance(reference_ppm, (int, float)) and reference_ppm > 0:
        value_component = _clamp((risk_adjusted_ppm / float(reference_ppm) - 1.0) / 1.5)
    else:
        value_component = 0.0

    discount = entry.get("discount_vs_position")
    discount_component = _clamp(float(discount) / 0.6) if isinstance(discount, (int, float)) else 0.0

    acceleration = entry.get("acceleration")
    price_delta = entry.get("price_delta")
    if acceleration is None:
        momentum_component = 0.5  # sin dato: ni premia ni castiga
    else:
        relative = float(acceleration) / max(abs(float(price_delta or 0)), 1.0)
        momentum_component = ( _clamp(relative, -1.0, 1.0) + 1.0) / 2.0
    entry["momentum_component"] = round(momentum_component, 4)
    entry["value_component"] = round(value_component, 4)

    score = 100.0 * (
        W_VALUE * value_component + W_DISCOUNT * discount_component + W_MOMENTUM * momentum_component
    )
    return round(score, 2)


def _public_row(entry: dict[str, Any], *, cash_eur: int | None) -> dict[str, Any]:
    price = entry.get("sale_price") if isinstance(entry.get("sale_price"), int) else entry.get("market_value")
    return {
        "player_id": entry["player_id"],
        "name": entry.get("name"),
        "nickname": entry.get("nickname"),
        "position": entry.get("position"),
        "club": entry.get("club"),
        "image_url": entry.get("image_url"),
        "market_value": entry.get("market_value"),
        "sale_price": entry.get("sale_price"),
        "effective_price": price,
        "affordable": (price <= cash_eur) if isinstance(price, int) and isinstance(cash_eur, int) else None,
        "owner": entry.get("owner"),
        "manager_name": entry.get("manager_name"),
        "on_market": entry.get("on_market") is True,
        "listing_expires_at": entry.get("listing_expires_at"),
        "games": entry.get("games"),
        "median_points": entry.get("median_points"),
        "mean_points": entry.get("mean_points"),
        "stdev_points": entry.get("stdev_points"),
        "blank_rate": entry.get("blank_rate"),
        "floor_rate": entry.get("floor_rate"),
        "boom_rate": entry.get("boom_rate"),
        "points_source": entry.get("points_source"),
        "average_points": entry.get("average_points"),
        "cost_per_point_eur": entry.get("cost_per_point_eur"),
        "points_per_million": entry.get("points_per_million"),
        "risk_adjusted_points_per_million": entry.get("risk_adjusted_points_per_million"),
        "position_baseline_cost_per_point_eur": entry.get("position_baseline_cost_per_point_eur"),
        "discount_vs_position": entry.get("discount_vs_position"),
        "undervalued": entry.get("undervalued") is True,
        "acceleration": entry.get("acceleration"),
        "price_delta": entry.get("price_delta"),
        "ff_price_delta": entry.get("ff_price_delta"),
        # Tramo de 2 y 3 días de la misma fuente. La app oficial enseña a veces
        # el acumulado de 2 días: sin declararlo, una subida real de 519.675 €
        # parecía un fallo cuando el panel mostraba 257.864 €.
        "ff_price_delta_2": entry.get("ff_price_delta_2"),
        "ff_price_delta_3": entry.get("ff_price_delta_3"),
        "relative_acceleration": entry.get("relative_acceleration"),
        "smart_money": entry.get("smart_money"),
        "momentum_signal": entry.get("momentum_signal"),
        "fitness": entry.get("fitness"),
        "p_titular": entry.get("p_titular"),
        "own_expected_points": entry.get("own_expected_points"),
        "score": entry.get("score"),
        "verdict": entry.get("verdict"),
        "reasons": entry.get("reasons") or [],
    }


def _attach_trend_fields(players: list[dict[str, Any]], trends: Any) -> None:
    """Titularidad, estado físico y expectativa del motor propio, si están."""
    if not isinstance(trends, dict):
        return
    rows = trends.get("players")
    if not isinstance(rows, list):
        return
    index = {
        str(row.get("player_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("player_id") is not None
    }
    for entry in players:
        trend = index.get(entry["player_id"])
        if not trend:
            continue
        fitness = trend.get("fitness")
        if isinstance(fitness, str):
            entry["fitness"] = fitness
        p_titular = _number(trend.get("p_titular"))
        if p_titular is not None:
            entry["p_titular"] = round(p_titular, 4)
        expected = _number(trend.get("own_expected_points", trend.get("expected_points")))
        if expected is not None:
            entry["own_expected_points"] = round(expected, 4)
        if entry.get("club") is None and isinstance(trend.get("club"), str):
            entry["club"] = trend["club"]
        if entry.get("position") is None and isinstance(trend.get("position"), str):
            entry["position"] = trend["position"]
        if entry.get("name") is None and isinstance(trend.get("name"), str):
            entry["name"] = trend["name"]


def _attach_league_fitness(players: list[dict[str, Any]], trends: Any) -> None:
    """Lesión o sanción de la foto manda sobre cualquier señal de precio."""
    if not isinstance(trends, dict):
        return
    rows = trends.get("players")
    if not isinstance(rows, list):
        return
    index = {
        str(row.get("player_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("player_id") is not None
    }
    for entry in players:
        trend = index.get(entry["player_id"])
        if not trend:
            continue
        fitness = trend.get("fitness")
        if isinstance(fitness, str) and fitness:
            entry["fitness"] = fitness
        sanction = trend.get("sanction") if isinstance(trend.get("sanction"), dict) else {}
        if sanction.get("suspended") is True:
            entry["fitness"] = "sancionado"


def build_quant_radar(
    board: dict[str, Any] | None = None,
    *,
    catalog: Iterable[dict[str, Any]] | dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
    min_games: int = MIN_GAMES,
    undervalued_discount: float = UNDERVALUED_DISCOUNT,
    max_blank_rate: float = MAX_BLANK_RATE,
) -> dict[str, Any]:
    """Radar final: qué libre o anunciado se ficha hoy y por qué.

    Todo sale de la foto: catálogo cacheado + mercado + plantillas + señales
    FF. Ningún camino de este módulo abre un socket.
    """
    snapshot = board if isinstance(board, dict) else read_cached_board()
    if snapshot is None:
        snapshot = {}
    trends = snapshot.get("trends") if isinstance(snapshot.get("trends"), dict) else {}
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    squads = snapshot.get("squads") if isinstance(snapshot.get("squads"), dict) else {}
    flip = snapshot.get("flip") if isinstance(snapshot.get("flip"), dict) else {}
    cash = flip.get("cash_eur") if isinstance(flip.get("cash_eur"), int) else _own_cash(squads)

    catalog_origin = "argument"
    rows = catalog
    if rows is None:
        rows = cached_catalog()
        catalog_origin = "cache"
    if not rows:
        # Sin catálogo en disco, la foto todavía sirve: plantillas + mercado.
        rows = (squads.get("squads") or []) + (market.get("listings") or [])
        catalog_origin = "board"

    catalog_rows = _rows_from(rows, "players")
    # Momentum global: liga (player_id exacto) + tabla FF cacheada (545 de 864).
    global_rows = cached_global_market_rows(catalog_rows)
    momentum = detect_global_momentum(
        trends if trends.get("players") else market,
        catalog=global_rows,
    )

    intrinsic = calculate_intrinsic_value(
        rows,
        market_data=market,
        squads_data=squads,
        momentum=momentum,
        min_games=min_games,
        undervalued_discount=undervalued_discount,
    )
    players = intrinsic["players"]
    _attach_trend_fields(players, trends)
    _attach_trend_fields_from_squads(players, squads)
    _attach_league_fitness(players, trends)
    baselines = intrinsic["baselines"]

    for entry in players:
        score = _score(entry, baselines)
        entry["score"] = score
        verdict, reasons = _verdict(entry, max_blank_rate=max_blank_rate, min_games=min_games)
        entry["verdict"] = verdict
        entry["reasons"] = reasons

    def _ranked(verdicts: set[str]) -> list[dict[str, Any]]:
        bucket = [row for row in players if row.get("verdict") in verdicts]
        bucket.sort(
            key=lambda row: (
                -(row.get("score") or 0.0),
                -(row.get("risk_adjusted_points_per_million") or 0.0),
                row["player_id"],
            )
        )
        return bucket

    buys = _ranked({"COMPRAR"})
    watchlist = _ranked({"VIGILAR"})
    toxic = _ranked({"TOXICO"})
    candidates = [row for row in players if row.get("undervalued") is True]
    candidates.sort(
        key=lambda row: (
            -(row.get("discount_vs_position") or 0.0),
            -(row.get("median_points") or 0.0),
            row["player_id"],
        )
    )

    momentum_index = {row["player_id"]: row for row in momentum.get("players") or []}
    smart_money: list[dict[str, Any]] = []
    for signal in momentum.get("smart_money") or []:
        entry = next((row for row in players if row["player_id"] == signal["player_id"]), None)
        base = _public_row(entry, cash_eur=cash) if entry is not None else _momentum_row(signal)
        base.update(
            {
                "acceleration": signal.get("acceleration"),
                "price_delta": signal.get("price_delta"),
                "relative_acceleration": signal.get("relative_acceleration"),
                "smart_money": True,
                "in_catalog": entry is not None,
                "score": entry.get("score") if entry else None,
                "verdict": entry.get("verdict") if entry else "SIN_MUESTRA",
            }
        )
        smart_money.append(base)

    public_buys = [_public_row(row, cash_eur=cash) for row in buys[: max(1, limit)]]
    public_watch = [_public_row(row, cash_eur=cash) for row in watchlist[: max(1, limit)]]
    public_toxic = [_public_row(row, cash_eur=cash) for row in toxic[: max(1, limit)]]
    public_candidates = [_public_row(row, cash_eur=cash) for row in candidates[:MAX_CANDIDATES]]

    signable = [row for row in players if row.get("signable") is True]
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "quant-radar",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "league_id": snapshot.get("trends", {}).get("league_id")
        if isinstance(snapshot.get("trends"), dict)
        else market.get("league_id"),
        "league_name": trends.get("league_name") or market.get("league_name"),
        "photo_saved_at": snapshot.get("dashboard_at") or snapshot.get("saved_at"),
        "cash_eur": cash,
        "sources": {
            "catalog_origin": catalog_origin,
            "catalog_rows": len(_rows_from(rows, "players")),
            "players_scored": len(players),
            "real_series": intrinsic["sample"]["with_real_series"],
            "market_listings": len(market.get("listings") or []),
            "trend_players": len(trends.get("players") or []),
            "momentum_source": momentum.get("source"),
            "network": "none",
        },
        "assumptions": {
            "blank_threshold_points": BLANK_THRESHOLD,
            "min_games": min_games,
            "undervalued_discount": undervalued_discount,
            "max_blank_rate": max_blank_rate,
            "weights": {"value": W_VALUE, "discount": W_DISCOUNT, "momentum": W_MOMENTUM},
            "notes": [
                "Coste por punto = valor de mercado / mediana real de jornadas.",
                "La referencia es la mediana de la posición, no la media de la liga.",
                "Smart money = aceleración positiva con delta de precio positivo.",
                "Blank rate = proporción de jornadas con <= 2 puntos.",
            ],
        },
        "baselines": baselines,
        "summary": {
            "buys": len(buys),
            "watchlist": len(watchlist),
            "toxic": len(toxic),
            "undervalued": len(candidates),
            "signable": len(signable),
            "smart_money": len(momentum.get("smart_money") or []),
            "scanned": len(players),
            "momentum_up": momentum.get("counts", {}).get("up", 0),
            "momentum_down": momentum.get("counts", {}).get("down", 0),
        },
        "buys": public_buys,
        "watchlist": public_watch,
        "toxic": public_toxic,
        "candidates": public_candidates,
        "momentum": {
            "counts": momentum.get("counts"),
            "source": momentum.get("source"),
            "smart_money": smart_money[: max(1, limit)],
            "top": [_momentum_row(signal) for signal in (momentum.get("movers") or [])[: max(1, limit)]],
        },
    }


def _momentum_row(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": signal.get("player_id"),
        "name": signal.get("name"),
        "nickname": signal.get("nickname"),
        "position": signal.get("position"),
        "club": signal.get("club"),
        "market_value": signal.get("market_value"),
        "sale_price": signal.get("sale_price"),
        "price_delta": signal.get("price_delta"),
        "acceleration": signal.get("acceleration"),
        "ff_price_delta": signal.get("ff_price_delta"),
        "relative_acceleration": signal.get("relative_acceleration"),
        "direction": signal.get("direction"),
        "smart_money": signal.get("smart_money") is True,
    }


def _attach_trend_fields_from_squads(players: list[dict[str, Any]], squads: Any) -> None:
    if not isinstance(squads, dict):
        return
    index: dict[str, dict[str, Any]] = {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        for member in squad.get("players") or []:
            if isinstance(member, dict) and member.get("player_id") is not None:
                index[str(member["player_id"])] = member
    for entry in players:
        member = index.get(entry["player_id"])
        if not member:
            continue
        if entry.get("average_points") is None:
            average = _number(member.get("average_points"))
            if average is not None:
                entry["average_points"] = round(average, 4)
        if entry.get("club") is None and isinstance(member.get("club"), str):
            entry["club"] = member["club"]
        if entry.get("position") is None and isinstance(member.get("position"), str):
            entry["position"] = member["position"]
        if entry.get("name") is None and isinstance(member.get("name"), str):
            entry["name"] = member["name"]


def _own_cash(squads: Any) -> int | None:
    if not isinstance(squads, dict):
        return None
    for squad in squads.get("squads") or []:
        if isinstance(squad, dict) and squad.get("is_self") is True:
            cash = squad.get("cash")
            if isinstance(cash, int) and not isinstance(cash, bool):
                return cash
    return None


# --------------------------------------------------------------------------- #
# Lectura de la foto guardada. Sin red, sin crear clientes si no hace falta.
# --------------------------------------------------------------------------- #


def read_cached_board(league: str | None = None) -> dict[str, Any] | None:
    """Foto del tablero desde ``.cache/dashboard`` (o ``FANTASY_CACHE_DIR``)."""
    key = (league or "").strip()
    root = cache_root() / "dashboard"
    preferred = [root / key / "full.json", root / key / "core.json"] if key else []
    fallbacks = [root / "_default" / "full.json", root / "_default" / "core.json"]
    for path in [*preferred, *fallbacks]:
        board = _read_board_file(path)
        if board is not None:
            return board
    return None


def _read_board_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        import json

        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    value = document.get("value")
    if isinstance(value, dict):
        board = dict(value)
        if isinstance(document.get("saved_at"), str):
            board.setdefault("saved_at", document["saved_at"])
        return board
    return document


def cached_catalog() -> list[dict[str, Any]]:
    """Catálogo de la competición desde la caché local. Nunca descarga."""
    try:
        from toolbox.net import LaligaClient, no_network

        with no_network():
            client = LaligaClient()
            try:
                rows = client.players_document(fresh=False)
            finally:
                client.close()
    except Exception as exc:  # noqa: BLE001 — sin catálogo se degrada a la foto
        logger.debug("Catálogo no disponible en caché: %s", exc)
        return []
    return [row for row in rows if isinstance(row, dict)]


def build_quant_radar_from_cache(
    league: str | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
    board: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atajo para CLI/pruebas: foto de disco + catálogo de disco."""
    return build_quant_radar(board or read_cached_board(league), limit=limit)

"""Puntuación esperada de LaLiga Fantasy a partir de lo que el jugador ya ha sumado.

La media de temporada por la probabilidad de titular arrastra suplencias de
diez minutos y ceros por no jugar. Este motor separa los partidos de titular,
contrae la media hacia el prior del puesto cuando hay poca muestra y reparte
el valor entre «si sale» y «lo que esperas en el once».
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Priors de un titular estándar de LaLiga (>=45') y de un revulsivo (<45').
PRIORS_TITULAR = {"PT": 4.4, "DF": 4.3, "MC": 4.8, "DL": 5.0}
PRIORS_SUPLENTE = {"PT": 0.5, "DF": 1.6, "MC": 2.1, "DL": 2.3}
STD_DEFAULT = {"PT": 2.8, "DF": 3.1, "MC": 3.8, "DL": 4.5}
LIGA_AVG_XG = 1.25
# Partidos de titular que vale el prior. Con n=0 manda el puesto; con n grande, el jugador.
K_PRIOR = 4.0
# Ventana de forma. El recuento bayesiano sigue usando todos los partidos de titular.
EWMA_WINDOW = 5
EWMA_DECAY = 0.25
# En el reglamento, jugar ya suma 1 y llegar a 60' suma otro. Sin minutos por
# jornada, 2 o más puntos es la firma de quien cumplió minutos de titular.
TITULAR_POINTS_FLOOR = 2.0
STARTER_MINUTES = 45
CS_BASELINE = 0.28


@dataclass
class PartidoHistorico:
    puntos: float
    minutos: int
    jornada: int


@dataclass
class ContextoEquipo:
    xg_favor_90: float
    xg_contra_90: float
    es_local: bool


_POSITION = {
    "PT": "PT",
    "POR": "PT",
    "GK": "PT",
    "DF": "DF",
    "DEF": "DF",
    "MC": "MC",
    "MED": "MC",
    "MID": "MC",
    "DL": "DL",
    "DEL": "DL",
    "FW": "DL",
    "ATT": "DL",
}


def canonical_slot(position: str | None) -> str:
    """``POR``/``DEF``/``MC``/``DEL`` de la app → hueco del motor."""
    key = str(position or "MC").strip().upper()
    return _POSITION.get(key, "MC")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _ewma(partidos: list[PartidoHistorico]) -> float:
    """Media de los últimos partidos de titular, con más peso en el más reciente."""
    ordered = sorted(partidos, key=lambda partido: partido.jornada)[-EWMA_WINDOW:]
    weights = [math.exp(EWMA_DECAY * index) for index in range(len(ordered))]
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(partido.puntos * weight for partido, weight in zip(ordered, weights)) / total


def _std_titular(partidos: list[PartidoHistorico], posicion: str) -> float:
    count = len(partidos)
    if count < 3:
        return STD_DEFAULT.get(posicion, 3.5)
    mean = sum(partido.puntos for partido in partidos) / count
    variance = sum((partido.puntos - mean) ** 2 for partido in partidos) / count
    return max(math.sqrt(variance), 2.0)


def _infer_minutes(puntos: float) -> int:
    """Sin el acta de minutos, el propio marcador dice si cumplió titular.

    Un 0 es no jugar (o un dato vacío): no entra en la media de titular ni en
    la de revulsivo. Entre 0 y 2 jugó sin el punto de los 60'. De 2 en adelante
    cumplió minutos de titular, también si el marcador se fue a negativo.
    """
    if puntos == 0:
        return 0
    if 0 < puntos < TITULAR_POINTS_FLOOR:
        return 20
    return 75


def _partido_from_mapping(item: dict[str, Any], index: int) -> PartidoHistorico | None:
    raw_points = None
    for key in ("puntos", "points", "totalPoints", "weekPoints"):
        raw_points = _number(item.get(key))
        if raw_points is not None:
            break
    if raw_points is None:
        return None
    minutes = None
    for key in ("minutos", "minutes", "minutesPlayed", "totalPlayingTime"):
        minutes = _number(item.get(key))
        if minutes is not None:
            break
    week = None
    for key in ("jornada", "weekNumber", "week"):
        week = _number(item.get(key))
        if week is not None:
            break
    return PartidoHistorico(
        puntos=raw_points,
        minutos=int(minutes) if minutes is not None else _infer_minutes(raw_points),
        jornada=int(week) if week is not None else index + 1,
    )


def historial_desde_jugador(player: dict[str, Any]) -> list[PartidoHistorico]:
    """Actas del jugador. Si solo hay la serie de puntos, infiere el régimen."""
    if not isinstance(player, dict):
        return []
    form = player.get("form") if isinstance(player.get("form"), dict) else {}
    for source in (player, form):
        for key in ("historial", "match_history", "lastStats", "last_stats"):
            raw = source.get(key)
            if not isinstance(raw, list):
                continue
            parsed: list[PartidoHistorico] = []
            for index, item in enumerate(raw):
                if isinstance(item, PartidoHistorico):
                    parsed.append(item)
                    continue
                if isinstance(item, dict):
                    partido = _partido_from_mapping(item, index)
                    if partido is not None:
                        parsed.append(partido)
            if parsed:
                return parsed

    series = player.get("week_points")
    if not isinstance(series, list):
        series = form.get("week_points")
    if isinstance(series, list) and series:
        partidos: list[PartidoHistorico] = []
        for index, item in enumerate(series):
            if isinstance(item, dict):
                partido = _partido_from_mapping(item, index)
            else:
                puntos = _number(item)
                partido = (
                    PartidoHistorico(puntos=puntos, minutos=_infer_minutes(puntos), jornada=index + 1)
                    if puntos is not None
                    else None
                )
            if partido is not None:
                partidos.append(partido)
        if partidos:
            return partidos

    # Sin serie, la media de la API solo vale si ya es la de un titular habitual.
    # Un canterano con 1,8 de media y un partido suelto no puede usar ese 1,8.
    starts = _number(form.get("starts"))
    minutes = _number(form.get("minutes"))
    average = _number(player.get("average_points"))
    if average is None:
        average = _number(form.get("average_points"))
    if (
        starts is not None
        and starts >= 3
        and minutes is not None
        and minutes / starts >= 60
        and average is not None
    ):
        count = int(starts)
        return [
            PartidoHistorico(puntos=average, minutos=80, jornada=index + 1) for index in range(count)
        ]
    return []


def _rating(player: dict[str, Any]) -> float | None:
    form = player.get("form") if isinstance(player.get("form"), dict) else {}
    for source in (player, form):
        for key in ("sofascore_rating_medio", "sofascore_rating", "average_rating"):
            rating = _number(source.get(key))
            if rating is not None and 5.5 <= rating <= 9.5:
                return rating
    return None


def _status_token(player: dict[str, Any]) -> str:
    for key in ("player_status", "fitness", "lineup_status"):
        value = player.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


class FantasyXPEngine:
    """E[pts] condicional, E[pts] de jornada y techo, sin scrapers de predicción."""

    PRIORS_TITULAR = PRIORS_TITULAR
    PRIORS_SUPLENTE = PRIORS_SUPLENTE
    STD_DEFAULT = STD_DEFAULT
    LIGA_AVG_XG = LIGA_AVG_XG

    @classmethod
    def prob_titular_heuristica(
        cls,
        historial: list[PartidoHistorico],
        *,
        player_status: str | None = None,
    ) -> float | None:
        """Titularidad interna cuando no hay un once publicado.

        Lesión o sanción → 0. Duda → 0,25. Disponible → peso 50/30/20 de si
        fue titular en las tres últimas jornadas, entre 15 % y 90 %.
        """
        status = (player_status or "").strip().lower()
        if status in {"injured", "suspended", "out", "lesionado", "baja", "sancionado"}:
            return 0.0
        if status in {"doubtful", "duda", "doubt"}:
            return 0.25
        if not historial:
            return None
        recent = sorted(historial, key=lambda partido: partido.jornada)[-3:]
        weights = (0.20, 0.30, 0.50)[-len(recent) :]
        weight_total = sum(weights)
        share = sum(
            weight * (1.0 if partido.minutos >= STARTER_MINUTES else 0.0)
            for weight, partido in zip(weights, recent)
        ) / weight_total
        return round(min(0.90, max(0.15, share)), 4)

    @classmethod
    def calcular_prediccion_completa(
        cls,
        posicion: str,
        historial: list[PartidoHistorico],
        prob_titular: float,
        equipo_propio: ContextoEquipo,
        equipo_rival: ContextoEquipo,
        sofascore_rating_medio: float | None = None,
        *,
        lambda_favor: float | None = None,
        lambda_contra: float | None = None,
        prob_clean_sheet: float | None = None,
    ) -> dict[str, float]:
        slot = canonical_slot(posicion)
        partidos_titular = [partido for partido in historial if partido.minutos >= STARTER_MINUTES]
        partidos_suplente = [partido for partido in historial if 0 < partido.minutos < STARTER_MINUTES]

        n_tit = len(partidos_titular)
        if n_tit > 0:
            media_titular_real = _ewma(partidos_titular)
            std_jugador = _std_titular(partidos_titular, slot)
        else:
            media_titular_real = 0.0
            std_jugador = STD_DEFAULT.get(slot, 3.5)

        prior_pos = PRIORS_TITULAR.get(slot, 4.5)
        base_titular = ((n_tit * media_titular_real) + (K_PRIOR * prior_pos)) / (n_tit + K_PRIOR)
        if sofascore_rating_medio is not None and sofascore_rating_medio > 6.70:
            bonus_sofa = (sofascore_rating_medio - 6.80) * 2.8
            base_titular += max(-0.6, min(1.8, bonus_sofa))

        # Los λ de partido que ya calcula el calendario llevan la localía dentro.
        # Recalcularlos y volver a multiplicar el bono la contaría dos veces.
        if lambda_favor is not None and lambda_contra is not None:
            lambda_goles_favor = max(0.05, float(lambda_favor))
            lambda_goles_contra = max(0.05, float(lambda_contra))
        else:
            bono_local = 1.08 if equipo_propio.es_local else 0.94
            lambda_goles_contra = (
                equipo_propio.xg_contra_90 * (equipo_rival.xg_favor_90 / LIGA_AVG_XG)
            ) / bono_local
            lambda_goles_favor = (
                equipo_propio.xg_favor_90 * (equipo_rival.xg_contra_90 / LIGA_AVG_XG)
            ) * bono_local

        if prob_clean_sheet is None:
            prob_clean_sheet = math.exp(-max(0.0, lambda_goles_contra))
        else:
            prob_clean_sheet = min(1.0, max(0.0, float(prob_clean_sheet)))
        if slot in {"PT", "DF"}:
            delta_cs = (prob_clean_sheet - CS_BASELINE) * 3.5
            factor_partido = max(0.72, min(1.35, 1.0 + delta_cs / max(base_titular, 0.5)))
        elif slot == "MC":
            ratio_ofensivo = (lambda_goles_favor / LIGA_AVG_XG) ** 0.35
            factor_partido = max(0.78, min(1.40, ratio_ofensivo))
        else:
            ratio_ofensivo = (lambda_goles_favor / LIGA_AVG_XG) ** 0.48
            factor_partido = max(0.75, min(1.50, ratio_ofensivo))

        xp_condicional = base_titular * factor_partido

        probabilidad = min(1.0, max(0.0, float(prob_titular)))
        if probabilidad <= 0.01:
            xp_pizarra = 0.0
        else:
            factor_banquillo = 0.05 if slot == "PT" else 0.55
            prob_revulsivo = (1.0 - probabilidad) * factor_banquillo
            media_sup = (
                sum(partido.puntos for partido in partidos_suplente) / len(partidos_suplente)
                if len(partidos_suplente) >= 2
                else PRIORS_SUPLENTE.get(slot, 1.8)
            )
            xp_pizarra = (probabilidad * xp_condicional) + (prob_revulsivo * media_sup * factor_partido)

        multiplicador_volatilidad = 1.85 if slot in {"MC", "DL"} else 1.50
        techo = xp_condicional + (multiplicador_volatilidad * std_jugador * math.sqrt(factor_partido))

        return {
            "xp_pizarra": round(xp_pizarra, 2),
            "xp_condicional": round(xp_condicional, 2),
            "techo": round(techo, 2),
            "prob_clean_sheet": round(prob_clean_sheet, 4),
            "base_titular": round(base_titular, 4),
            "n_titular": float(n_tit),
            "factor_partido": round(factor_partido, 4),
            "std_jugador": round(std_jugador, 4),
        }


def predecir_desde_jugador(
    player: dict[str, Any],
    *,
    prob_titular: float | None = None,
    lambda_favor: float | None = None,
    lambda_contra: float | None = None,
    es_local: bool | None = None,
    prob_clean_sheet: float | None = None,
) -> dict[str, float]:
    """Adapta un jugador de la app (serie de jornadas, forma, λ) al motor."""
    historial = historial_desde_jugador(player)
    probabilidad = _number(prob_titular)
    if probabilidad is None:
        probabilidad = FantasyXPEngine.prob_titular_heuristica(
            historial,
            player_status=_status_token(player),
        )
    if probabilidad is None:
        probabilidad = 0.5
    if probabilidad > 1.0:
        probabilidad /= 100.0

    local = bool(es_local) if isinstance(es_local, bool) else False
    propio = ContextoEquipo(
        xg_favor_90=lambda_favor if lambda_favor is not None else LIGA_AVG_XG,
        xg_contra_90=lambda_contra if lambda_contra is not None else LIGA_AVG_XG,
        es_local=local,
    )
    rival = ContextoEquipo(xg_favor_90=LIGA_AVG_XG, xg_contra_90=LIGA_AVG_XG, es_local=not local)
    return FantasyXPEngine.calcular_prediccion_completa(
        str(player.get("position") or "MC"),
        historial,
        probabilidad,
        propio,
        rival,
        _rating(player),
        lambda_favor=lambda_favor,
        lambda_contra=lambda_contra,
        prob_clean_sheet=prob_clean_sheet,
    )

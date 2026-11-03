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

from toolbox.engine.p_titular_model import STARTER_MINUTES, current_weights, features_from_minutes, predict

# Priors de un titular estándar de LaLiga (>=45') y de un revulsivo (<45').
# El portero no puede compartir cifra con un defensa: quien juega de inicio
# ronda los 8 pts (portería, paradas y valla). El 4,4 anterior absorbía el
# 65 % de la base con solo dos partidos y dejaba el xP ~2 pts corto.
# El delantero sale de la media de titulares anterior a la ventana J9–J11
# (5,9 sobre 32 partidos). Defensa y medio ya coincidían con esa ventana.
PRIORS_TITULAR = {"PT": 8.0, "DF": 4.3, "MC": 4.8, "DL": 5.8}
PRIORS_SUPLENTE = {"PT": 0.5, "DF": 1.6, "MC": 2.1, "DL": 2.3}
STD_DEFAULT = {"PT": 2.8, "DF": 3.1, "MC": 3.8, "DL": 4.5}

# Deciles del valor de mercado por puesto (catálogo, nov 2026). El mercado ya
# descuenta el estatus del jugador en la temporada, así que sirve de prior con
# pocos partidos: separa al titular caro del suplente barato desde el primer día.
PRECIO_DECILES = {
    "PT": (564_000, 589_000, 597_000, 621_000, 691_000, 774_000, 1_605_000, 13_547_000, 22_263_000, 37_535_000, 59_713_000),
    "DF": (580_000, 596_000, 665_000, 794_000, 1_041_000, 2_376_000, 4_175_000, 6_310_000, 13_090_000, 24_386_000, 90_781_000),
    "MC": (587_000, 604_000, 633_000, 742_000, 1_053_000, 1_661_000, 3_909_000, 6_801_000, 14_233_000, 31_545_000, 130_727_000),
    "DL": (582_000, 599_000, 648_000, 712_000, 988_000, 2_455_000, 4_172_000, 8_849_000, 23_825_000, 47_215_000, 189_253_000),
}
# Ajuste del prior del puesto en puntos: recta sobre el percentil de precio,
# recortada. El percentil 0 resta 1 punto y el 1 suma 1,8.
AJUSTE_PRIOR_BASE = -1.0
AJUSTE_PRIOR_PENDIENTE = 2.8
AJUSTE_PRIOR_MIN = -1.0
AJUSTE_PRIOR_MAX = 1.8


def percentil_precio(slot: str, precio: float | None) -> float | None:
    """Percentil 0..1 del valor de mercado dentro de su puesto (interpolado en deciles)."""
    anclas = PRECIO_DECILES.get(slot)
    if anclas is None or precio is None or not math.isfinite(precio) or precio <= 0:
        return None
    if precio <= anclas[0]:
        return 0.0
    if precio >= anclas[-1]:
        return 1.0
    for indice in range(1, len(anclas)):
        if precio <= anclas[indice]:
            lo, hi = anclas[indice - 1], anclas[indice]
            return ((indice - 1) + (precio - lo) / (hi - lo)) / (len(anclas) - 1)
    return 1.0


def ajuste_prior_por_precio(slot: str, precio: float | None) -> float:
    percentil = percentil_precio(slot, precio)
    if percentil is None:
        return 0.0
    ajuste = AJUSTE_PRIOR_BASE + AJUSTE_PRIOR_PENDIENTE * percentil
    return max(AJUSTE_PRIOR_MIN, min(AJUSTE_PRIOR_MAX, ajuste))


LIGA_AVG_XG = 1.25
# Partidos de titular que vale el prior. Con n=0 manda el puesto; con n grande, el jugador.
K_PRIOR = 4.0
# Racha viva: los últimos partidos seguidos con >= 60' y una media de 6 en los 3 finales.
# Ahí el prior de 4 aplasta un cambio de rol (7, 8, 9). Para el resto de la liga sigue en 4:
# un parche de uno o dos partidos no abre la puerta.
K_PRIOR_RACHA = 2.0
RACHA_PARTIDOS = 3
RACHA_MINUTOS = 60
RACHA_MEDIA = 6.0
# Ventana de forma. El recuento bayesiano sigue usando todos los partidos de titular.
EWMA_WINDOW = 5
EWMA_DECAY = 0.25
# Aparecer ya suma 1. Sin el acta, un marcador positivo no dice si fue titular:
# un 1 puede ser un titular que no llegó a 60' y un 3 un suplente que marcó.
# Esos partidos quedan fuera de las dos medias (ver ``_infer_minutes``).
MINUTOS_ROL_DESCONOCIDO = -1
# Solo para la logística de titularidad: por debajo de 45, así que no es un
# titular, pero tampoco un cero. Sirve cuando el marcador dice que jugó y no
# hay acta. No entra en la media de titular ni en la de revulsivo.
MINUTOS_APARICION_DESCONOCIDA = 40
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


def lambdas_de_fuerzas(
    xg_propio: float,
    xga_propio: float,
    xg_rival: float,
    xga_rival: float,
    *,
    es_local: bool,
    liga_xg: float = LIGA_AVG_XG,
) -> tuple[float, float]:
    """λ a favor y en contra a partir de las medias previas al partido.

    La localía entra una sola vez. Quien ya traiga los λ del calendario no
    debe volver a multiplicar este bono.
    """
    liga = liga_xg if liga_xg > 0 else LIGA_AVG_XG
    bono = 1.08 if es_local else 0.94
    en_contra = (xga_propio * (xg_rival / liga)) / bono
    a_favor = (xg_propio * (xga_rival / liga)) * bono
    return a_favor, en_contra


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def racha_viva(partidos: list[PartidoHistorico]) -> list[PartidoHistorico]:
    """Sufijo de partidos seguidos con al menos 60 minutos.

    Se recorre el historial desde el más reciente. El primer partido por debajo
    de 60' (o sin acta) corta la racha: un revulsivo no alarga el estado de gracia.
    """
    ordered = sorted(partidos, key=lambda partido: partido.jornada)
    viva: list[PartidoHistorico] = []
    for partido in reversed(ordered):
        if partido.minutos >= RACHA_MINUTOS:
            viva.append(partido)
        else:
            break
    viva.reverse()
    return viva


def k_prior_efectivo(partidos: list[PartidoHistorico]) -> float:
    """Peso del prior. Baja a 2 solo si la racha viva consolida un cambio de rol.

    Hacen falta al menos 3 partidos seguidos de 60' o más, y la media de los 3
    más recientes de esa racha tiene que llegar a 6. La EWMA no se toca: lo que
    se afloja es el ancla del prior sobre esa media. Medir solo los 3 últimos
    evita que un pasado mediocre de 60' (que el prior ya representa) diluya
    un 7-8-9 recién consolidado.
    """
    viva = racha_viva(partidos)
    if len(viva) < RACHA_PARTIDOS:
        return K_PRIOR
    cola = viva[-RACHA_PARTIDOS:]
    media = sum(partido.puntos for partido in cola) / len(cola)
    if media >= RACHA_MEDIA:
        return K_PRIOR_RACHA
    return K_PRIOR


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
    """Sin acta ni otra fuente, no se inventa la titularidad a partir de los puntos.

    Un 0 es no jugar: pisar el campo ya suma 1, así que no entra en ninguna
    media. Cualquier otro marcador solo dice que jugó. Clasificarlo como
    suplente (el 1 de un titular corto) o como titular (el 3 de un revulsivo)
    corrompe la media. Esos partidos quedan fuera de las dos, con un minuto
    negativo que ni ``>= 45`` ni el tramo de revulsivo recogen.
    """
    if puntos == 0:
        return 0
    return MINUTOS_ROL_DESCONOCIDO


def _minutos_explicitos(item: dict[str, Any], puntos: float) -> int | None:
    """Minutos del acta, o el papel que declara el propio partido.

    ``started`` / ``titular`` es una fuente fiable: manda sobre el marcador.
    Un titular declarado con 1 punto sigue siendo titular; un suplente
    declarado con 3 puntos sigue siendo suplente.
    """
    for key in ("minutos", "minutes", "minutesPlayed", "totalPlayingTime"):
        minutes = _number(item.get(key))
        if minutes is not None:
            return int(minutes)
    for key in ("started", "is_starter", "titular", "was_starter"):
        value = item.get(key)
        if value is True:
            return 75
        if value is False:
            return 0 if puntos == 0 else 20
    return None


def _reparto_fiable(puntos: list[float], player: dict[str, Any]) -> list[int] | None:
    """Reparte los minutos de temporada solo cuando el papel no admite duda.

    Si cada aparición fue titular (los starts cubren los partidos con puntos y
    la media de minutos pasa de 45), esos partidos son de titular. Si no hubo
    ningún start, son revulsivos. Si hubo de las dos cosas, no se adivina cuál
    jornada fue cuál.
    """
    form = player.get("form") if isinstance(player.get("form"), dict) else {}
    starts = _number(form.get("starts"))
    minutes = _number(form.get("minutes"))
    if starts is None or minutes is None or starts < 0 or minutes < 0:
        return None
    jugados = [valor for valor in puntos if valor != 0]
    if not jugados:
        return [0 for _ in puntos]
    if starts >= len(jugados) and minutes / len(jugados) >= STARTER_MINUTES:
        each = int(min(90, round(minutes / len(jugados))))
        return [each if valor != 0 else 0 for valor in puntos]
    if starts == 0:
        each = int(min(STARTER_MINUTES - 1, max(1, round(minutes / len(jugados))))) if minutes > 0 else 1
        return [each if valor != 0 else 0 for valor in puntos]
    return None


def _partido_from_mapping(item: dict[str, Any], index: int) -> PartidoHistorico | None:
    raw_points = None
    for key in ("puntos", "points", "totalPoints", "weekPoints"):
        raw_points = _number(item.get(key))
        if raw_points is not None:
            break
    if raw_points is None:
        return None
    minutes = _minutos_explicitos(item, raw_points)
    week = None
    for key in ("jornada", "weekNumber", "week"):
        week = _number(item.get(key))
        if week is not None:
            break
    return PartidoHistorico(
        puntos=raw_points,
        minutos=minutes if minutes is not None else _infer_minutes(raw_points),
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
        numeros = [_number(item) for item in series]
        serie_desnuda = all(not isinstance(item, dict) for item in series) and all(valor is not None for valor in numeros)
        reparto = _reparto_fiable([float(valor) for valor in numeros], player) if serie_desnuda else None
        partidos: list[PartidoHistorico] = []
        for index, item in enumerate(series):
            if isinstance(item, dict):
                partido = _partido_from_mapping(item, index)
            else:
                puntos = numeros[index]
                if puntos is None:
                    partido = None
                else:
                    minutos = reparto[index] if reparto is not None else _infer_minutes(puntos)
                    partido = PartidoHistorico(puntos=puntos, minutos=minutos, jornada=index + 1)
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


def _precio(player: dict[str, Any]) -> float | None:
    for key in ("fantasy_price", "market_value", "sale_price", "precio"):
        valor = _number(player.get(key))
        if valor is not None and valor > 0:
            return valor
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

        Lesión o sanción → 0. Duda → 0,25. Disponible → logística sobre la
        fracción de partidos de titular de la temporada y los minutos
        recientes (media de las tres últimas jornadas, sobre 90').

        Los pesos los gestiona ``toolbox.engine.p_titular_model`` y se
        reajustan solos con cada actualización (``toolbox.p_titular_refit``).
        Los iniciales salen de J9–J11 (n=334) con validación dejando una
        jornada fuera: Brier 0,201 → 0,180. La regla anterior («fue titular
        las 3 últimas») daba 22 % a quien luego jugaba el 44 % de las veces:
        no distinguía al que entra desde el banquillo del que no pisa el campo.
        """
        status = (player_status or "").strip().lower()
        if status in {"injured", "suspended", "out", "lesionado", "baja", "sancionado"}:
            return 0.0
        if status in {"doubtful", "duda", "doubt"}:
            return 0.25
        if not historial:
            return None
        ordered = sorted(historial, key=lambda partido: partido.jornada)
        # El papel desconocido no es un cero: jugó, pero no sabemos si salió.
        minutos = [
            MINUTOS_APARICION_DESCONOCIDA if partido.minutos == MINUTOS_ROL_DESCONOCIDO else partido.minutos
            for partido in ordered
        ]
        features = features_from_minutes(minutos)
        if features is None:
            return None
        probability = predict(current_weights(), features)
        return round(min(0.95, max(0.05, probability)), 4)

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
        ajuste_prior: float = 0.0,
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

        prior_pos = PRIORS_TITULAR.get(slot, 4.5) + ajuste_prior
        # La racha se mide sobre todo el historial: un partido de 50' es titular
        # para la media (>= 45') pero corta el estado de gracia, que pide 60'.
        viva = racha_viva(historial)
        k_prior = k_prior_efectivo(historial)
        cola = viva[-RACHA_PARTIDOS:] if len(viva) >= RACHA_PARTIDOS else []
        racha_media = sum(partido.puntos for partido in cola) / len(cola) if cola else 0.0
        base_titular = ((n_tit * media_titular_real) + (k_prior * prior_pos)) / (n_tit + k_prior)
        if sofascore_rating_medio is not None and sofascore_rating_medio > 6.70:
            bonus_sofa = (sofascore_rating_medio - 6.80) * 2.8
            base_titular += max(-0.6, min(1.8, bonus_sofa))

        # Los λ de partido que ya calcula el calendario llevan la localía dentro.
        # Recalcularlos y volver a multiplicar el bono la contaría dos veces.
        if lambda_favor is not None and lambda_contra is not None:
            lambda_goles_favor = max(0.05, float(lambda_favor))
            lambda_goles_contra = max(0.05, float(lambda_contra))
        else:
            lambda_goles_favor, lambda_goles_contra = lambdas_de_fuerzas(
                equipo_propio.xg_favor_90,
                equipo_propio.xg_contra_90,
                equipo_rival.xg_favor_90,
                equipo_rival.xg_contra_90,
                es_local=equipo_propio.es_local,
            )

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
            "k_prior": k_prior,
            "racha_partidos": float(len(viva)),
            "racha_media": round(racha_media, 4),
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
        ajuste_prior=ajuste_prior_por_precio(canonical_slot(str(player.get("position") or "MC")), _precio(player)),
    )

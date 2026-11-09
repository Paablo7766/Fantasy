"""xP 2.0: puntos esperados por bloques (suelo, gol, asistencia y portería).

Cada acta de LaLiga trae los puntos de cada acción (``toolbox.player_history``).
El backtest de J8–J11 (503 jugador-jornada, nov 2026) separó dos cosas que la
fórmula anterior mezclaba en un solo total:

* El **suelo** (minutos, valoración de cronistas, recuperaciones, paradas y
  tarjetas) se repite de una semana a otra (correlación 0,50 entre jornadas).
* **Gol y asistencia** de medios y delanteros no se repiten en ventanas cortas
  (−0,03): un gol aislado es ruido. Se contraen con fuerza hacia el puesto.
* La **portería a cero** es del partido, no del jugador (0,15): sale de la
  probabilidad de encajar 0, 1, 2… goles de ESTA jornada (cuotas / λ).

Con eso el error medio bajó de 2,92 a 2,75 puntos por jugador frente al motor
anterior, con el mismo dato de titularidad. Los pesos salen de ese backtest
(ajustados con tres jornadas y examinados en la cuarta).

Si el jugador no tiene actas desglosadas (fichajes del mercado sin
``lastStats``) este módulo devuelve ``None`` y manda la fórmula de respaldo
de ``toolbox.engine.xp_calculator``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from toolbox.engine.xp_calculator import canonical_slot, percentil_precio

# --- Medias por puesto en partidos de titular (>= 45'), actas J5–J11 ---------
#: Suelo = minutos + valoración + acciones + paradas + tarjetas.
SUELO_PUESTO = {"PT": 6.77, "DF": 4.34, "MC": 3.94, "DL": 4.33}
#: Goles por partido de titular.
GOLES_PUESTO = {"PT": 0.0, "DF": 0.062, "MC": 0.083, "DL": 0.221}
#: Puntos de asistencia (gol + ocasión) por partido de titular.
ASIST_PUESTO = {"PT": 0.03, "DF": 0.14, "MC": 0.315, "DL": 0.70}
#: Media de quien sale desde el banquillo (< 45').
REVULSIVO_PUESTO = {"PT": 1.5, "DF": 2.4, "MC": 1.9, "DL": 2.5}
#: Fracción de titularidades que llegan a 60' (la portería solo puntúa ahí).
LLEGA_60 = {"PT": 1.0, "DF": 0.94, "MC": 0.91, "DL": 0.88}
#: Puntos por gol según el puesto.
PUNTOS_GOL = {"PT": 6.0, "DF": 6.0, "MC": 5.0, "DL": 4.0}
#: Puntos de portería por goles encajados (0, 1, 2, …) jugando >= 60'.
TABLA_PORTERIA = {
    "PT": (4, 0, -2, -2, -4, -4, -6),
    "DF": (3, 0, -2, -2, -4, -4, -6),
    "MC": (2, 0, -1, -1, -2, -2, -3),
    "DL": (1, 0, -1, -1, -2, -2, -3),
}
#: Suelo de un partido en el 25 % alto del puesto (umbral del «breakout»).
SUELO_TOP25 = {"PT": 8.0, "DF": 6.0, "MC": 5.0, "DL": 6.0}

# --- Pesos (backtest J8–J11, validación dejando una jornada fuera) ----------
#: Partidos que vale la media del puesto en el suelo.
K_SUELO = 5.0
#: Breakout: jugador con suelo de élite reciente, el puesto pesa la mitad.
K_SUELO_BREAKOUT = 2.5
#: Peso extra por partido más reciente en el suelo (e^1,2 ≈ ×3,3 por jornada).
DECAY_SUELO = 1.2
#: Partidos que vale la media del puesto en goles y asistencias (contracción fuerte).
K_GOL = 10.0
K_ASIST = 8.0
#: Puntos por cada punto de P(victoria) sobre la media (0,36): valoración y juego.
BONO_VICTORIA = 3.0
P_VICTORIA_MEDIA = 0.36
#: Puntos por percentil de precio dentro del puesto (±1,5 en los extremos).
PESO_PRECIO = 3.0
#: Elasticidad de gol/asistencia a los goles esperados del equipo. El backtest
#: no encontró señal fuera de muestra (0–0,5): el rival ya entra por P(victoria).
ELASTICIDAD_ATAQUE = 0.25
LIGA_LAMBDA = 1.30
#: Prob. de entrar desde el banquillo si no es titular (portero: casi nunca).
FACTOR_BANQUILLO = {"PT": 0.05, "DF": 0.55, "MC": 0.55, "DL": 0.55}

# --- Balón parado (Analítica Fantasy) ---------------------------------------
#: Penaltis a favor por equipo y partido en LaLiga (~0,13) × acierto (~0,78).
GOLES_PENALTI_POR_PARTIDO = 0.10
#: Lanzador de córners / faltas indirectas: asistencias extra por partido.
ASIST_BALON_PARADO = 0.04
PUNTOS_ASISTENCIA = 3.0


@dataclass
class ActaDesglosada:
    jornada: int
    minutos: float
    puntos: float
    bloques: dict[str, float]
    cantidades: dict[str, float]

    @property
    def suelo(self) -> float:
        return sum(self.bloques.get(b, 0.0) for b in ("min", "rating", "act", "gk", "neg"))


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def actas_del_jugador(player: dict[str, Any]) -> list[ActaDesglosada]:
    """Actas con desglose: del propio ``historial`` o de la caché por ``player_id``."""
    actas: list[ActaDesglosada] = []
    historial = player.get("historial") if isinstance(player.get("historial"), list) else []
    for item in historial:
        if not isinstance(item, dict) or not isinstance(item.get("desglose"), dict):
            continue
        d = item["desglose"]
        jornada = _num(item.get("jornada"))
        puntos = _num(item.get("puntos"))
        minutos = _num(item.get("minutos"))
        if jornada is None or puntos is None or minutos is None:
            continue
        actas.append(ActaDesglosada(int(jornada), minutos, puntos, dict(d.get("puntos") or {}), dict(d.get("cantidades") or {})))
    if actas:
        return sorted(actas, key=lambda a: a.jornada)
    pid = player.get("player_id")
    if not isinstance(pid, str) or not pid:
        return []
    from toolbox.player_history import actas_en_cache

    entry = actas_en_cache().get(pid) or {}
    semanas = entry.get("weeks") or {}
    for jornada, desglose in (entry.get("desglose") or {}).items():
        if jornada not in semanas:
            continue
        puntos, minutos = semanas[jornada]
        actas.append(ActaDesglosada(int(jornada), float(minutos), float(puntos), dict(desglose["puntos"]), dict(desglose["cantidades"])))
    return sorted(actas, key=lambda a: a.jornada)


# --- Cambio cronico, produccion pura y suelo muro (Frentes 4 y 8) ----------
#: Un titular sustituido entre el 45' y el 59' no llega a los 60' de la porteria.
MINUTO_TITULAR = 45
MINUTO_CAMBIO_TARDIO = 60
#: Titularidades recientes que se miran y las que hacen falta para llamarlo cronico.
VENTANA_CAMBIO = 4
MIN_TITULARIDADES_CAMBIO = 3
MIN_CAMBIOS_TEMPRANOS = 2
RATIO_CAMBIO_CRONICO = 0.5
#: Minutos de un titular que juega entero: el techo real se mide contra esto.
MINUTOS_TITULAR_TIPICO = 80.0
#: Suelo muro: minimo de puntos en partidos largos.
MINUTOS_PARTIDO_LARGO = 70
PUNTOS_SUELO_MURO = 6.0
MIN_PARTIDOS_SUELO_MURO = 3


def cambio_cronico(titular: list[ActaDesglosada]) -> dict[str, Any] | None:
    """Titular al que cambian de forma repetida entre el 45' y el 59'.

    Mira sus ultimas ``VENTANA_CAMBIO`` titularidades. Cronico: al menos
    ``MIN_CAMBIOS_TEMPRANOS`` salidas tempranas y la mitad o mas. Devuelve su
    techo real de minutos y la fraccion de titularidades que llegan a 60'.
    """
    recientes = titular[-VENTANA_CAMBIO:]
    if len(recientes) < MIN_TITULARIDADES_CAMBIO:
        return None
    tempranos = sum(1 for a in recientes if a.minutos < MINUTO_CAMBIO_TARDIO)
    if tempranos < MIN_CAMBIOS_TEMPRANOS or tempranos / len(recientes) < RATIO_CAMBIO_CRONICO:
        return None
    techo = sum(a.minutos for a in recientes) / len(recientes)
    return {
        "activo": True,
        "n_titularidades": len(recientes),
        "n_cambios_antes_60": tempranos,
        "minutos_techo": round(techo, 1),
        "llega_60": round(1.0 - tempranos / len(recientes), 3),
        "factor_minutos": round(min(1.0, techo / MINUTOS_TITULAR_TIPICO), 3),
    }


def produccion_pura_90(actas: list[ActaDesglosada]) -> float | None:
    """(valoracion + acciones) por 90 minutos, sobre todas sus actas con minutos."""
    jugadas = [a for a in actas if a.minutos > 0]
    minutos = sum(a.minutos for a in jugadas)
    if minutos < MINUTO_TITULAR:
        return None
    total = sum(a.bloques.get("rating", 0.0) + a.bloques.get("act", 0.0) for a in jugadas)
    return round(total / minutos * 90.0, 2)


def suelo_muro(actas: list[ActaDesglosada]) -> dict[str, Any] | None:
    """Minimo de puntos en partidos de mas de 70'. Muro: ese minimo es >= 6."""
    largos = [a for a in actas if a.minutos >= MINUTOS_PARTIDO_LARGO]
    if len(largos) < MIN_PARTIDOS_SUELO_MURO:
        return None
    minimo = min(a.puntos for a in largos)
    return {"activo": minimo >= PUNTOS_SUELO_MURO, "minimo": round(minimo, 1), "n_partidos": len(largos)}


def _pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def prob_victoria(lambda_favor: float, lambda_contra: float) -> float:
    """P(marcar más que el rival) con dos Poisson independientes."""
    gana = 0.0
    for propios in range(1, 11):
        p_propios = _pois(propios, lambda_favor)
        gana += p_propios * sum(_pois(ajenos, lambda_contra) for ajenos in range(propios))
    return gana


def puntos_porteria(slot: str, lambda_contra: float, p_cero: float | None = None) -> float:
    """E[puntos de portería] jugando >= 60', con la distribución de goles encajados.

    Si llega una P(portería a cero) del calendario (cuotas con Dixon-Coles), manda
    esa en el 0 y el resto de la masa se reparte como Poisson.
    """
    tabla = TABLA_PORTERIA[slot]
    lam = max(0.05, lambda_contra)
    probs = [_pois(k, lam) for k in range(12)]
    if p_cero is not None and 0.0 <= p_cero < 1.0 and probs[0] < 1.0:
        resto = (1.0 - p_cero) / (1.0 - probs[0])
        probs = [p_cero] + [p * resto for p in probs[1:]]
    return sum(p * tabla[min(k, len(tabla) - 1)] for k, p in enumerate(probs))


def _contrae(valores: list[float], prior: float, k: float) -> float:
    return (sum(valores) + k * prior) / (len(valores) + k)


def _roles_balon_parado(player: dict[str, Any]) -> set[str]:
    roles = player.get("af_set_pieces")
    if not isinstance(roles, list):
        return set()
    return {str(r.get("role")) for r in roles if isinstance(r, dict) and r.get("role")}


def _precio(player: dict[str, Any]) -> float | None:
    for key in ("fantasy_price", "market_value", "sale_price", "precio"):
        valor = _num(player.get(key))
        if valor is not None and valor > 0:
            return valor
    return None


def es_breakout(slot: str, titularidades: list[ActaDesglosada]) -> bool:
    """Dos titularidades recientes seguidas con suelo en el 25 % alto del puesto.

    Mide solo el suelo (sin goles): un barato que marcó de rebote no entra; uno
    que genera juego real cada semana (Félix Correia, Redondo) sí.
    """
    if len(titularidades) < 2:
        return False
    umbral = SUELO_TOP25[slot]
    return all(acta.suelo >= umbral for acta in titularidades[-2:])


def prediccion_xp2(
    player: dict[str, Any],
    *,
    prob_titular: float,
    lambda_favor: float,
    lambda_contra: float,
    prob_porteria_cero: float | None = None,
    ajuste_rival: float = 0.0,
) -> dict[str, Any] | None:
    """xP de jornada, xP si es titular y su desglose. ``None`` sin actas desglosadas.

    ``ajuste_rival`` (puntos, de ``toolbox.rival_posicional``) suma o resta a
    valoración + acciones según lo que ese rival concede a este puesto.
    """
    slot = canonical_slot(str(player.get("position") or "MC"))
    actas = actas_del_jugador(player)
    titular = [a for a in actas if a.minutos >= 45]
    if not titular:
        return None
    revulsivo = [a.puntos for a in actas if 0 < a.minutos < 45]

    breakout = es_breakout(slot, titular)
    cronico = cambio_cronico(titular)
    factor_min = float(cronico["factor_minutos"]) if cronico else 1.0

    # 1) Suelo, con más peso en lo reciente.
    pesos = [math.exp(DECAY_SUELO * i) for i in range(len(titular))]
    media_suelo = sum(a.suelo * w for a, w in zip(titular, pesos)) / sum(pesos)
    k_suelo = K_SUELO_BREAKOUT if breakout else K_SUELO
    # El prior del puesto supone un titular que juega entero: a quien salen antes del 60' se le
    # aplica su techo real de minutos.
    suelo = (len(titular) * media_suelo + k_suelo * SUELO_PUESTO[slot] * factor_min) / (len(titular) + k_suelo)

    # 2) Partido: el favorito puntúa más (valoración, juego, resultado).
    lam_f = max(0.05, float(lambda_favor))
    lam_c = max(0.05, float(lambda_contra))
    p_victoria = prob_victoria(lam_f, lam_c)
    bono_partido = BONO_VICTORIA * (p_victoria - P_VICTORIA_MEDIA)

    # 3) Precio: el mercado sabe quién es bueno. Un breakout barato no se castiga.
    percentil = percentil_precio(slot, _precio(player))
    ajuste_precio = PESO_PRECIO * (percentil - 0.5) if percentil is not None else 0.0
    if breakout and ajuste_precio < 0:
        ajuste_precio = 0.0

    # 4) Gol y asistencia: contracción fuerte hacia el puesto + balón parado.
    roles = _roles_balon_parado(player)
    ataque = (lam_f / LIGA_LAMBDA) ** ELASTICIDAD_ATAQUE
    goles = _contrae([a.cantidades.get("goals", 0.0) for a in titular], GOLES_PUESTO[slot], K_GOL)
    if "penalties" in roles and slot != "PT":
        goles += GOLES_PENALTI_POR_PARTIDO
    puntos_gol = goles * ataque * PUNTOS_GOL[slot] * factor_min
    asist = _contrae([a.bloques.get("ast", 0.0) for a in titular], ASIST_PUESTO[slot], K_ASIST)
    if roles & {"corners", "indirect"}:
        asist += ASIST_BALON_PARADO * PUNTOS_ASISTENCIA
    puntos_asist = asist * ataque * factor_min

    # 5) Portería de esta jornada.
    llega_60 = float(cronico["llega_60"]) if cronico else LLEGA_60[slot]
    puntos_cero = puntos_porteria(slot, lam_c, prob_porteria_cero) * llega_60

    ajuste_rival = float(ajuste_rival) * factor_min if math.isfinite(float(ajuste_rival)) else 0.0
    suelo_partido = suelo + bono_partido + ajuste_precio + ajuste_rival
    condicional = suelo_partido + puntos_gol + puntos_asist + puntos_cero

    # 6) Titularidad y rosco.
    p = min(1.0, max(0.0, float(prob_titular)))
    media_revulsivo = _contrae(revulsivo, REVULSIVO_PUESTO[slot], 3.0)
    if p <= 0.01:
        jornada = 0.0
    else:
        jornada = p * condicional + (1.0 - p) * FACTOR_BANQUILLO[slot] * media_revulsivo

    return {
        "xp": round(max(0.0, jornada), 3),
        "xp_condicional": round(condicional, 3),
        "suelo": round(suelo_partido, 3),
        "ajuste_rival_posicional": round(ajuste_rival, 3),
        "gol": round(puntos_gol, 3),
        "asistencia": round(puntos_asist, 3),
        "porteria": round(puntos_cero, 3),
        "p_victoria": round(p_victoria, 4),
        "breakout": breakout,
        "balon_parado": sorted(roles),
        "n_titular": len(titular),
        "cambio_cronico": cronico,
        "produccion_pura_90": produccion_pura_90(actas),
        "suelo_muro": suelo_muro(actas),
    }


def prob_titular_portero(player: dict[str, Any], prob_titular: float) -> float:
    """Regla dura del portero: el último partido decide (26/26 en el backtest).

    El suplente que no jugó la última jornada baja a 0,03; el que la jugó de
    inicio sube a 0,95. Si una fuente de once (AF, FútbolFantasy, alineación)
    dice claramente lo contrario, manda la fuente: una lesión del titular o un
    cambio de portero se ve ahí antes que en el acta.
    """
    if canonical_slot(str(player.get("position") or "")) != "PT":
        return prob_titular
    actas = actas_del_jugador(player)
    minutos: list[float] = [a.minutos for a in actas]
    if not minutos:
        historial = player.get("historial") if isinstance(player.get("historial"), list) else []
        ordenado = sorted(
            (i for i in historial if isinstance(i, dict) and _num(i.get("jornada")) is not None),
            key=lambda i: float(i["jornada"]),
        )
        minutos = [m for m in (_num(i.get("minutos")) for i in ordenado) if m is not None]
    if not minutos:
        return prob_titular
    # Una titularidad con fuente (once de AF, FútbolFantasy, alineación) es externa;
    # sin fuente es la heurística de minutos, y ahí manda la regla.
    externa = _num(player.get("p_titular")) if player.get("p_titular_source") else None
    if externa is not None and externa > 1.0:
        externa /= 100.0
    ultimo = minutos[-1]
    if ultimo == 0:
        if externa is not None and externa >= 0.6:
            return prob_titular
        return min(prob_titular, 0.03)
    if ultimo >= 45:
        if externa is not None and externa < 0.4:
            return prob_titular
        return max(prob_titular, 0.95)
    return prob_titular

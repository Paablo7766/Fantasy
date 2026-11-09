"""Predicción del precio de mercado de LaLiga Fantasy.

El cambio diario no es un paseo aleatorio: arrastra la inercia de hoy, la
aceleración respecto a ayer y una fuerza que empuja el precio hacia lo que
el jugador vale por puntos esperados. Un punto esperado de jornada equivale
a 16,4 M€.

La función no lee caché ni sale a la red. Recibe el precio y los dos últimos
deltas y devuelve el movimiento de mañana y el precio dentro de siete días.
Si esos dos días van al mismo ritmo, los siete lo repiten. Si el día de hoy
es un pico, el impulso se apaga.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_MADRID = ZoneInfo("Europe/Madrid")

# 1 punto esperado de jornada = 16,4 millones de valor de mercado.
EUROS_POR_PUNTO = 16_400_000

# Calibrado el 2026-11-06 con el histórico real (225 pares a 1 día, 333 a 4):
# el error medio bajó de 0,36 % a 0,21 % a un día y de 2,3 % a 1,65 % a cuatro
# con inercia 0,9 y amortiguación 0,95. Los precios de LaLiga persisten más
# de lo que suponían las constantes iniciales (0,75 y 0,85).
# delta_mañana = inercia * delta_hoy + peso * aceleración + fuerza de retorno.
PESO_INERCIA = 0.9
PESO_ACELERACION = 0.35
# Con delta de hoy aún positivo y aceleración negativa la curva ya frena.
# El peso pleno haría caer el pronóstico de golpe; este lo suaviza.
PESO_ACELERACION_FRENADA = 0.15
# Fracción del hueco (valor justo − precio) que se corrige en un día.
FACTOR_RETORNO = 0.02

# Cada día el delta hereda el 85 % del anterior: el impulso se apaga.
# Solo aplica cuando el movimiento es un pico. Un ritmo parecido dos días
# seguidos no es un pico y no se apaga en la ventana de siete días.
AMORTIGUACION = 0.95
HORIZONTE_DIAS = 7
# Hoy y ayer cuentan como el mismo ritmo si no se separan más de un 35 %.
TOLERANCIA_RITMO = 0.35
# Por debajo de medio punto del precio, el movimiento es ruido.
RITMO_MINIMO_PCT = 0.005

# La plataforma mueve el precio en escalones de 10.000 €.
PASO_PRECIO = 10_000

# El valor de mercado descuenta unas cuatro jornadas. El ratio de liga se
# mide en € por punto de una jornada; el valor justo reparte ese ratio entre
# las cuatro: xp_4 * (ratio / 4) = xp_jornada * ratio.
HORIZONTE_JORNADAS = 4
# Por debajo de esta muestra el ratio vuelve a la referencia de 16,4 M€.
MUESTRA_MINIMA_TITULARES = 8


def _numero(value: Any, nombre: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{nombre} tiene que ser un número")
    numero = float(value)
    if not math.isfinite(numero):
        raise ValueError(f"{nombre} tiene que ser finito")
    return numero


def _al_paso(valor: float, paso: int = PASO_PRECIO) -> int:
    """Redondeo al escalón de precio más cercano (mitad hacia el par, como ``round``)."""
    if paso <= 0:
        raise ValueError("el paso de precio tiene que ser positivo")
    return int(round(valor / paso)) * paso


def predecir_precio(
    precio_actual: int | float,
    delta_hoy: int | float,
    delta_ayer: int | float,
    xp_jornada: int | float,
) -> dict[str, int | float]:
    """Pronóstico de un día y proyección a siete, en euros y en porcentaje.

    Aceleración = delta de hoy − delta de ayer.
    Valor justo = xp de la jornada × 16,4 M€.
    Fuerza de retorno = (valor justo − precio) × 0,02: negativa si está
    caro, positiva si es chollo.
    Delta de mañana = 0,75 × delta de hoy + peso × aceleración + fuerza.
    El peso de la aceleración baja de 0,35 a 0,15 cuando hoy todavía sube
    pero la aceleración ya es negativa.

    Los siete días siguientes acumulan ese delta y cada jornada lo multiplican
    por 0,85. ``pct_cambio`` es la variación porcentual del precio actual al
    valor de dentro de siete días.
    """
    precio = _numero(precio_actual, "precio_actual")
    hoy = _numero(delta_hoy, "delta_hoy")
    ayer = _numero(delta_ayer, "delta_ayer")
    xp = _numero(xp_jornada, "xp_jornada")
    if precio <= 0:
        raise ValueError("precio_actual tiene que ser positivo")

    aceleracion = hoy - ayer
    valor_justo = xp * EUROS_POR_PUNTO
    fuerza_retorno = (valor_justo - precio) * FACTOR_RETORNO

    peso = PESO_ACELERACION
    if hoy > 0 and aceleracion < 0:
        peso = PESO_ACELERACION_FRENADA

    delta_bruto = (PESO_INERCIA * hoy) + (peso * aceleracion) + fuerza_retorno
    # La aceleración no puede empujar el día siguiente por encima del
    # movimiento de hoy: un pico no se extrapola.
    if hoy * delta_bruto > 0 and abs(delta_bruto) > abs(hoy):
        delta_bruto = hoy
    delta_manana = _al_paso(delta_bruto)

    delta = float(delta_manana)
    acumulado = 0.0
    for _dia in range(HORIZONTE_DIAS):
        acumulado += delta
        delta *= AMORTIGUACION

    valor_en_7_dias = _al_paso(precio + acumulado)
    pct_cambio = round((valor_en_7_dias - precio) / precio * 100.0, 2)

    return {
        "delta_manana": delta_manana,
        "valor_en_7_dias": valor_en_7_dias,
        "pct_cambio": pct_cambio,
    }


# ---------------------------------------------------------------------------
# Ley de inercia medida (9 nov 2026, precios reales de la liga)
# ---------------------------------------------------------------------------
# cambio%(t+1) = 0,041 % + 0,944 * cambio%(t), R2 = 0,858. El signo del cambio
# se repite el 95,7 % de los dias. Los domingos el precio no se mueve (0,0 %).
LEY_INERCIA_ALFA_PCT = 0.041
LEY_INERCIA_BETA = 0.944
SIGNO_REPETIDO_PCT = 95.7
#: La ley se ajusto con cambios diarios normales; un pico mayor se trata como este tope
#: (extrapolar un +11 % a 0,944 por dia compuesto no esta medido).
CAMBIO_MAX_EXTRAPOLABLE_PCT = 5.0
#: Un cambio diario por encima de esto es «claramente positivo»: el jugador sigue en racha.
CAMBIO_CLARAMENTE_POSITIVO_PCT = 0.5
#: Impulso de arranque tras puntuar (residuo medio sobre la ley, por tramo de precio):
#: (precio_min, precio_max, puntos_minimos, impulso_pct). En 3-15 M, de 6 puntos para
#: arriba el residuo medio fue +0,43 % a +0,73 % y positivo en 35 de 40 casos.
#: En >20 M no se midio impulso positivo (8 pts: -0,16 %, 3 de 10 positivos), asi que
#: su impulso es 0 hasta que haya muestra; el umbral queda registrado.
IMPULSOS_POST_JORNADA: tuple[tuple[int, int | None, int, float], ...] = (
    (3_000_000, 15_000_000, 6, 0.58),
    (20_000_000, None, 8, 0.0),
)


def cambio_pct_desde_delta(precio: int | float, delta: int | float) -> float:
    """Cambio de hoy en % respecto al precio de ayer (``precio`` ya incluye el delta)."""
    base = float(precio) - float(delta)
    if base <= 0:
        return 0.0
    return float(delta) / base * 100.0


def impulso_post_jornada_pct(precio: int | float, puntos: int | float | None) -> float:
    """Impulso (en %) del primer dia tras una jornada con puntos altos. 0 si no aplica."""
    if puntos is None or isinstance(puntos, bool) or not math.isfinite(float(puntos)):
        return 0.0
    for minimo, maximo, umbral, impulso in IMPULSOS_POST_JORNADA:
        if float(precio) >= minimo and (maximo is None or float(precio) < maximo) and float(puntos) >= umbral:
            return impulso
    return 0.0


def proyectar_inercia(
    precio_actual: int | float,
    cambio_pct_hoy: int | float,
    dias: int | float,
    *,
    desde: date | None = None,
    puntos_jornada: int | float | None = None,
    post_jornada: bool = False,
) -> dict[str, Any]:
    """Precio dentro de ``dias`` con la ley 0,041 % + 0,944 * cambio de ayer.

    Los domingos no se mueve y no gastan inercia. Con ``post_jornada`` (lunes o
    martes tras jugar) el primer dia suma el impulso de arranque medido para los
    puntos de la jornada; despues lo arrastra la propia inercia.
    """
    precio = _numero(precio_actual, "precio_actual")
    pct = _numero(cambio_pct_hoy, "cambio_pct_hoy")
    if precio <= 0:
        raise ValueError("precio_actual tiene que ser positivo")
    pct = max(-CAMBIO_MAX_EXTRAPOLABLE_PCT, min(CAMBIO_MAX_EXTRAPOLABLE_PCT, pct))
    pasos = max(0, int(round(float(dias))))
    dia = desde or datetime.now(_MADRID).date()
    impulso = impulso_post_jornada_pct(precio, puntos_jornada) if post_jornada else 0.0
    valor = precio
    serie: list[float] = []
    for _paso in range(pasos):
        dia = dia + timedelta(days=1)
        if dia.weekday() == 6:
            serie.append(0.0)
            continue
        pct = LEY_INERCIA_ALFA_PCT + LEY_INERCIA_BETA * pct + impulso
        impulso = 0.0
        valor *= 1.0 + pct / 100.0
        serie.append(round(pct, 4))
    final = _al_paso(valor)
    return {
        "valor": final,
        "pct": round((final - precio) / precio * 100.0, 2),
        "serie_pct": serie,
    }


def vender_en_pico_prohibido(cambio_pct_hoy: int | float | None, *, dia_limite_caja: bool = False) -> bool:
    """``True`` si vender hoy es prematuro: sigue subiendo con fuerza y no hay urgencia de caja.

    El signo del cambio se repite el 95,7 % de los dias: mientras hoy suba con
    claridad, mañana (casi seguro) sube otra vez. Solo el dia limite de caja lo salta.
    """
    if dia_limite_caja or cambio_pct_hoy is None or isinstance(cambio_pct_hoy, bool):
        return False
    return float(cambio_pct_hoy) > CAMBIO_CLARAMENTE_POSITIVO_PCT


def formatear_pct(pct: float) -> str:
    """``+10.9%`` o ``-2.1%``. El cero no lleva signo."""
    numero = round(float(pct), 1)
    if numero == 0:
        return "0.0%"
    return f"{numero:+.1f}%"


def ratio_mercado_liga(
    titulares: list[tuple[float, float]],
) -> dict[str, float | int | bool | None]:
    """€ por punto esperado de jornada.

    ``titulares`` son pares ``(valor_de_mercado, xp_de_jornada)`` de quienes
    salen de inicio. Con menos de ocho pares válidos se usa la referencia de
    16,4 M€ por punto, que es el ancla del motor de inercia.
    """
    validos = [(valor, xp) for valor, xp in titulares if valor > 0 and xp > 0]
    if len(validos) < MUESTRA_MINIMA_TITULARES:
        return {
            "ratio_mercado": float(EUROS_POR_PUNTO),
            "xp_medio_titulares": None,
            "valor_medio_titulares": None,
            "muestra_titulares": len(validos),
            "usa_referencia": True,
        }
    valor_medio = sum(valor for valor, _xp in validos) / len(validos)
    xp_medio = sum(xp for _valor, xp in validos) / len(validos)
    if xp_medio <= 0:
        return {
            "ratio_mercado": float(EUROS_POR_PUNTO),
            "xp_medio_titulares": None,
            "valor_medio_titulares": None,
            "muestra_titulares": len(validos),
            "usa_referencia": True,
        }
    return {
        "ratio_mercado": valor_medio / xp_medio,
        "xp_medio_titulares": round(xp_medio, 4),
        "valor_medio_titulares": int(round(valor_medio)),
        "muestra_titulares": len(validos),
        "usa_referencia": False,
    }


#: Curva de valor justo: xP de los titulares de la liga y sus valores, ordenados por separado.
CurvaValorJusto = dict[str, list[float]]


def curva_valor_justo(titulares: list[tuple[float, float]]) -> CurvaValorJusto | None:
    """Curva por percentiles: el n-ésimo xP de la liga vale el n-ésimo valor de mercado.

    El mercado no paga los puntos en línea recta: un titular de 8 xP no vale el doble
    que uno de 4, vale lo que valen los mejores. Con la recta (xP × € medio por punto)
    las estrellas salían «sobrevaloradas» a la mitad de su precio (Isco 70 M€ → 31 M€).
    Sin muestra suficiente, ``None`` y se usa la recta.
    """
    validos = [(float(valor), float(xp)) for valor, xp in titulares if valor > 0 and xp > 0]
    if len(validos) < MUESTRA_MINIMA_TITULARES:
        return None
    return {"xps": sorted(xp for _valor, xp in validos), "valores": sorted(valor for valor, _xp in validos)}


def _percentil(valores: list[float], x: float) -> float:
    """Posición fraccional de ``x`` en ``valores`` (ordenados), entre 0 y len-1."""
    if x <= valores[0]:
        return 0.0
    if x >= valores[-1]:
        return float(len(valores) - 1)
    for indice in range(1, len(valores)):
        if x <= valores[indice]:
            bajo, alto = valores[indice - 1], valores[indice]
            tramo = (x - bajo) / (alto - bajo) if alto > bajo else 0.0
            return indice - 1 + tramo
    return float(len(valores) - 1)


def _cuantil(valores: list[float], posicion: float) -> float:
    bajo = int(math.floor(posicion))
    alto = min(len(valores) - 1, bajo + 1)
    tramo = posicion - bajo
    return valores[bajo] * (1.0 - tramo) + valores[alto] * tramo


def valor_justo_jugador(xp_jornada: float, ratio: float, curva: CurvaValorJusto | None = None) -> int:
    """Lo que el mercado de esta liga paga por ``xp_jornada`` puntos esperados.

    Con ``curva``, por percentiles (ver ``curva_valor_justo``); fuera del rango de la
    muestra se prolonga en proporción al xP del extremo. Sin curva, la recta
    ``xp × ratio`` (``xp_4_jornadas * (ratio / 4)``).
    """
    xp = _numero(xp_jornada, "xp_jornada")
    if xp <= 0:
        return 0
    if curva and curva.get("xps") and curva.get("valores"):
        xps, valores = curva["xps"], curva["valores"]
        if xp > xps[-1]:
            return int(round(valores[-1] * xp / xps[-1]))
        if xp < xps[0]:
            return int(round(valores[0] * xp / xps[0]))
        return int(round(_cuantil(valores, _percentil(xps, xp))))
    precio_punto = _numero(ratio, "ratio_mercado")
    if precio_punto <= 0:
        return 0
    xp_4 = xp * HORIZONTE_JORNADAS
    ratio_4 = precio_punto / HORIZONTE_JORNADAS
    return int(round(xp_4 * ratio_4))


def _ritmo_asentado(precio: float, delta_hoy: float, delta_ayer: float) -> float | None:
    """Media de hoy y ayer si los dos días van al mismo lado y el paso es parecido.

    None si el movimiento cambia de signo, nace de cero o hoy se separa más
    de un 35 % de ayer. Eso es un pico, y el pico sí se apaga.
    """
    if delta_hoy == 0 or delta_ayer == 0 or delta_hoy * delta_ayer < 0:
        return None
    referencia = max(abs(delta_hoy), abs(delta_ayer))
    if abs(delta_hoy - delta_ayer) > TOLERANCIA_RITMO * referencia:
        return None
    ritmo = (delta_hoy + delta_ayer) / 2.0
    if abs(ritmo) < max(10_000.0, RITMO_MINIMO_PCT * precio):
        return None
    return ritmo


def proyectar_7d(
    precio_actual: int | float,
    delta_hoy: int | float,
    delta_ayer: int | float,
    xp_jornada: int | float,
    ratio: int | float,
    *,
    en_forma: bool,
    curva: CurvaValorJusto | None = None,
    desde: date | None = None,
    puntos_jornada: int | float | None = None,
    post_jornada: bool = False,
) -> dict[str, int | float | str]:
    """Precio dentro de siete días.

    Con movimiento hoy (``delta_hoy`` distinto de cero) manda la ley medida
    ``0,041 % + 0,944 * cambio`` (``proyectar_inercia``): sustituye al ritmo
    asentado y a la inercia que se apaga. Sin movimiento no hay inercia que
    proyectar y entra la fuerza hacia el valor justo.

    Si hoy y ayer se mueven al mismo lado y con un paso parecido, esos siete
    días repiten ese ritmo. El valor justo no lo corrige: una racha de un
    millón al día no se convierte en 390.000 € al día siguiente por estar
    caro respecto a los puntos.

    Si el movimiento es un pico de un solo día, o no hay ritmo, entra la
    inercia que se apaga (cada día conserva el 85 %) y la fuerza hacia el
    valor justo. La fuerza de subida, en ese caso, solo actúa cuando el
    jugador viene de puntuar bien. La de bajada entra siempre.
    """
    precio = _numero(precio_actual, "precio_actual")
    hoy = _numero(delta_hoy, "delta_hoy")
    ayer = _numero(delta_ayer, "delta_ayer")
    if precio <= 0:
        raise ValueError("precio_actual tiene que ser positivo")
    justo = valor_justo_jugador(xp_jornada, ratio, curva)
    if hoy != 0:
        ley = proyectar_inercia(
            precio,
            cambio_pct_desde_delta(precio, hoy),
            HORIZONTE_DIAS,
            desde=desde,
            puntos_jornada=puntos_jornada,
            post_jornada=post_jornada,
        )
        valor_en_7 = int(ley["valor"])
        pct = float(ley["pct"])
    else:
        # El motor de inercia valora 1 punto de jornada a 16,4 M€. Se le pasa el
        # xp equivalente al justo de esta liga para reutilizar la misma fuerza.
        if justo > precio and not en_forma:
            xp_fuerza = precio / EUROS_POR_PUNTO
        else:
            xp_fuerza = justo / EUROS_POR_PUNTO
        crudo = predecir_precio(precio, hoy, ayer, xp_fuerza)
        valor_en_7 = int(crudo["valor_en_7_dias"])
        pct = float(crudo["pct_cambio"])
    return {
        "valor_justo": justo,
        "xp_4_jornadas": round(max(0.0, float(xp_jornada)) * HORIZONTE_JORNADAS, 2),
        "valor_en_7d": valor_en_7,
        "prevision_7d_pct": formatear_pct(pct),
        "pct": pct,
    }

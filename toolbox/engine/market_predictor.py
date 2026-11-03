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
from typing import Any

# 1 punto esperado de jornada = 16,4 millones de valor de mercado.
EUROS_POR_PUNTO = 16_400_000

# delta_mañana = inercia * delta_hoy + peso * aceleración + fuerza de retorno.
PESO_INERCIA = 0.75
PESO_ACELERACION = 0.35
# Con delta de hoy aún positivo y aceleración negativa la curva ya frena.
# El peso pleno haría caer el pronóstico de golpe; este lo suaviza.
PESO_ACELERACION_FRENADA = 0.15
# Fracción del hueco (valor justo − precio) que se corrige en un día.
FACTOR_RETORNO = 0.02

# Cada día el delta hereda el 85 % del anterior: el impulso se apaga.
# Solo aplica cuando el movimiento es un pico. Un ritmo parecido dos días
# seguidos no es un pico y no se apaga en la ventana de siete días.
AMORTIGUACION = 0.85
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


def valor_justo_jugador(xp_jornada: float, ratio: float) -> int:
    """``xp_4_jornadas * (ratio_de_jornada / 4)``.

    Así un titular medio vale, en justo, lo que el mercado paga de media por
    ese punto, y la referencia de 16,4 M€ sigue siendo € por punto de jornada.
    """
    xp = _numero(xp_jornada, "xp_jornada")
    precio_punto = _numero(ratio, "ratio_mercado")
    if xp <= 0 or precio_punto <= 0:
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
) -> dict[str, int | float | str]:
    """Precio dentro de siete días.

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
    justo = valor_justo_jugador(xp_jornada, ratio)
    ritmo = _ritmo_asentado(precio, hoy, ayer)
    if ritmo is not None:
        valor_en_7 = _al_paso(precio + ritmo * HORIZONTE_DIAS)
        pct = round((valor_en_7 - precio) / precio * 100.0, 2)
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

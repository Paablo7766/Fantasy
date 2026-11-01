"""Predicción del precio de mercado de LaLiga Fantasy.

El cambio diario no es un paseo aleatorio: arrastra la inercia de hoy, la
aceleración respecto a ayer y una fuerza que empuja el precio hacia lo que
el jugador vale por puntos esperados. Un punto esperado de jornada equivale
a 16,4 M€.

La función no lee caché ni sale a la red. Recibe el precio y los dos últimos
deltas y devuelve el movimiento de mañana y el precio dentro de siete días.
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
AMORTIGUACION = 0.85
HORIZONTE_DIAS = 7

# La plataforma mueve el precio en escalones de 10.000 €.
PASO_PRECIO = 10_000


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

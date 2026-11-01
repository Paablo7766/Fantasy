"""Pujas, rivales obligados a vender y los dos capitanes del once."""

from __future__ import annotations

import math
from typing import Any

from toolbox.engine.market_predictor import PASO_PRECIO

# La Pizarra puja un 4,7 % por encima del valor. El tope racional es +25 %.
PRIMA_PUJA = 1.047
TOPE_SOBREPUJA = 1.25
# Por encima del rival con más caja que necesita el puesto.
MARGEN_RIVAL_EUR = 100_000
# Una proyección de +5 % en siete días ya es una subida alta.
PREVISION_ALTA_PCT = 5.0
# Por encima de esto, vender al titular duele de verdad.
UMBRAL_WAR_OFERTA = 1.5
# Titularidad mínima del capitán seguro.
TITULAR_SEGURO = 0.80


def _paso(valor: float, paso: int = PASO_PRECIO) -> int:
    if paso <= 0:
        return int(round(valor))
    return int(round(valor / paso)) * paso


def calcular_pujas(
    valor_actual: int | float,
    delta_hoy: int | float,
    valor_justo: int | float,
    *,
    tu_saldo: int | float | None,
    rivales: list[dict[str, Any]],
    posicion: str | None,
) -> dict[str, int | None]:
    """Puja recomendada, tope racional y puja que deja atrás al rival.

    ``puja_recomendada`` es el valor por 1,047 más la subida de hoy, si la hay.
    ``puja_maxima`` no pasa de ``min(valor_justo, valor × 1,25)``.
    ``puja_smart`` suma 0,1 M€ al rival interesado con más saldo cuando todos
    los que necesitan el puesto tienen menos caja que tú, y nunca supera el tope.
    """
    vacio = {"puja_recomendada": None, "puja_maxima": None, "puja_smart": None}
    if isinstance(valor_actual, bool) or not isinstance(valor_actual, (int, float)) or valor_actual <= 0:
        return vacio
    valor = float(valor_actual)
    subida = float(delta_hoy) if isinstance(delta_hoy, (int, float)) and not isinstance(delta_hoy, bool) else 0.0
    if subida < 0:
        subida = 0.0
    recomendada = _paso(valor * PRIMA_PUJA + subida)
    justo = float(valor_justo) if isinstance(valor_justo, (int, float)) and not isinstance(valor_justo, bool) else 0.0
    tope_bruto = min(justo, valor * TOPE_SOBREPUJA) if justo > 0 else 0.0
    maxima = _paso(tope_bruto) if tope_bruto > 0 else None
    if maxima is not None and maxima <= 0:
        maxima = None

    saldo = None
    if isinstance(tu_saldo, (int, float)) and not isinstance(tu_saldo, bool):
        saldo = float(tu_saldo)

    interesados: list[float] = []
    puesto = posicion if isinstance(posicion, str) else ""
    for rival in rivales:
        if not isinstance(rival, dict):
            continue
        puestos = rival.get("posiciones")
        if not isinstance(puestos, (list, set, tuple)) or puesto not in puestos:
            continue
        caja = rival.get("saldo")
        if isinstance(caja, bool) or not isinstance(caja, (int, float)):
            continue
        if float(caja) > 0:
            interesados.append(float(caja))

    base = recomendada
    if maxima is not None:
        base = min(base, maxima)
    if saldo is not None and interesados and all(caja < saldo for caja in interesados):
        objetivo = max(interesados) + MARGEN_RIVAL_EUR
        smart = max(base, _paso(objetivo))
        if maxima is not None:
            smart = min(smart, maxima)
    else:
        smart = base
    if saldo is not None:
        smart = min(float(smart), saldo)
        smart = math.floor(smart / PASO_PRECIO) * PASO_PRECIO
    if smart <= 0:
        smart_out: int | None = None
    else:
        smart_out = int(smart)

    return {
        "puja_recomendada": recomendada if recomendada > 0 else None,
        "puja_maxima": maxima,
        "puja_smart": smart_out,
    }


def capitanes(xi: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """Capitán seguro (jornada, titularidad alta) y capitán de techo."""
    filas = [row for row in xi if isinstance(row, dict)]

    def ficha(row: dict[str, Any], criterio: str) -> dict[str, Any]:
        return {
            "player_id": row.get("player_id"),
            "nombre": row.get("nombre") or row.get("nickname") or row.get("name") or row.get("player_id"),
            "posicion": row.get("position"),
            "jornada": row.get("jornada"),
            "si_titular": row.get("si_titular"),
            "techo": row.get("techo"),
            "p_titular": row.get("p_titular"),
            "criterio": criterio,
        }

    seguros = [
        row
        for row in filas
        if isinstance(row.get("p_titular"), (int, float))
        and not isinstance(row.get("p_titular"), bool)
        and float(row["p_titular"]) >= TITULAR_SEGURO
        and isinstance(row.get("jornada"), (int, float))
        and not isinstance(row.get("jornada"), bool)
    ]
    seguro = max(seguros, key=lambda row: (float(row["jornada"]), float(row["p_titular"]), str(row.get("nombre") or ""))) if seguros else None
    techos = [
        row
        for row in filas
        if isinstance(row.get("techo"), (int, float))
        and not isinstance(row.get("techo"), bool)
        and float(row["techo"]) > 0
    ]
    remontada = max(techos, key=lambda row: (float(row["techo"]), float(row.get("jornada") or 0.0), str(row.get("nombre") or ""))) if techos else None
    return {
        "capitan_seguro": ficha(seguro, "jornada") if seguro is not None else None,
        "capitan_remontada": ficha(remontada, "techo") if remontada is not None else None,
    }


def nota_y_veredicto(mejora: float, acciones: list[dict[str, Any]]) -> tuple[int, str]:
    """Nota 0-10 y veredicto a partir de los puntos que gana el once.

    Por debajo de 0,4 es opcional. Desde 0,4, recomendable. A partir de 1,5
    —o de 0,8 si hay que actuar hoy— es para hacerlo ya. La nota sube unos
    4 puntos por cada punto esperado de mejora, con suelo según el veredicto.
    """
    if mejora <= 0 or not acciones:
        return 0, "Opcional"
    hay_hoy = any(accion.get("momento") == "hoy" for accion in acciones)
    if mejora >= 1.5 or (hay_hoy and mejora >= 0.8):
        veredicto = "Hazlo ya"
        suelo = 8
    elif mejora >= 0.4:
        veredicto = "Recomendable"
        suelo = 5
    else:
        veredicto = "Opcional"
        suelo = 0
    nota = int(round(mejora * 4))
    nota = max(suelo, min(10, nota))
    return nota, veredicto

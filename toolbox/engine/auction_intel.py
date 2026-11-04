"""Pujas, rivales obligados a vender y, si la liga lo tiene, los dos capitanes."""

from __future__ import annotations

import math
import zlib
from typing import Any

from toolbox.engine.market_predictor import PASO_PRECIO
from toolbox.engine.reglamento import CAPITAN_ACTIVO

# La Pizarra puja un 4,7 % por encima del valor.
# El techo ya no es un +25 % fijo: prima de oportunidad, previsión a 7 días
# y dificultad del partido, con un cap absoluto del +30 % para la liquidez.
PRIMA_PUJA = 1.047
MULTIPLICADOR_BASE = 1.15
PESO_REVALORIZACION = 0.55
BONO_PARTIDO_FACIL = 0.02
BONO_PARTIDO_DIFICIL = -0.01
CAP_LIQUIDEZ = 1.30
_DIFICULTAD_FACIL = {"facil", "muy_facil", "easy", "very_easy"}
_DIFICULTAD_DIFICIL = {"dificil", "muy_dificil", "hard", "very_hard"}
# Por encima del rival con más caja que necesita el puesto.
MARGEN_RIVAL_EUR = 100_000
# Una proyección de +5 % en siete días ya es una subida alta.
PREVISION_ALTA_PCT = 5.0
# Por encima de esto, vender al titular duele de verdad.
UMBRAL_WAR_OFERTA = 1.5
# Titularidad mínima del capitán seguro.
TITULAR_SEGURO = 0.80
# Anti-Pizarra: con demanda alta pujamos por encima del escalón redondo de La Pizarra.
PASO_PIZARRA_EUR = 100_000
UMBRAL_NOTA_DEMANDA = 8.0
UMBRAL_PREVISION_DEMANDA = 15.0
# Entre 140.000 y 220.000 €, en pasos de 10.000, sin múltiplos de 50.000.
DIFERENCIALES_EUR = tuple(v for v in range(140_000, 220_001, 10_000) if v % 50_000 != 0)


def _paso(valor: float, paso: int = PASO_PRECIO) -> int:
    if paso <= 0:
        return int(round(valor))
    return int(round(valor / paso)) * paso


def _clave_dificultad(dificultad: str | None) -> str:
    if not isinstance(dificultad, str):
        return ""
    return (
        dificultad.strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace(" ", "_")
        .replace("-", "_")
    )


def prevision_a_puntos(value: Any) -> float:
    """``+23,2%`` o ``23.2`` → 23.2. Sin dato, 0."""
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else 0.0
    if isinstance(value, str):
        text = value.strip().replace("%", "").replace(",", ".")
        if not text:
            return 0.0
        try:
            number = float(text)
        except ValueError:
            return 0.0
        return number if math.isfinite(number) else 0.0
    return 0.0


def prima_quemada_mercado(puja: Any, valor: Any, prevision_7d_pct: Any = None) -> float:
    """Euros que no vuelven al pujar por encima del valor de mercado.

    ``max(0, puja − valor − subida_7d)``. La subida prevista a 7 días descuenta
    el sobreprecio; una bajada lo agranda. Sin valor de mercado no se puede
    medir y la prima queda en cero, igual que en un clausulazo sin valor.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor <= 0:
        return 0.0
    if isinstance(puja, bool) or not isinstance(puja, (int, float)) or puja <= 0:
        return 0.0
    subida = float(valor) * (prevision_a_puntos(prevision_7d_pct) / 100.0)
    return max(0.0, float(puja) - float(valor) - subida)


def bono_dificultad(dificultad: str | None) -> float:
    """Fácil suma 2 puntos al multiplicador. Difícil resta 1. El resto, nada."""
    clave = _clave_dificultad(dificultad)
    if clave in _DIFICULTAD_FACIL:
        return BONO_PARTIDO_FACIL
    if clave in _DIFICULTAD_DIFICIL:
        return BONO_PARTIDO_DIFICIL
    return 0.0


def multiplicador_puja(prevision_7d_pct: Any = None, dificultad: str | None = None) -> float:
    """``1,15 + 0,55·(previsión/100) + bono de partido``, nunca por encima de 1,30.

    Una subida del +23,2 % a 7 días aporta ``0,55 × 0,232 ≈ 0,127``: el techo
    sube ~12,7 puntos porque el mercado devuelve esa prima solo.
    """
    bono_revalorizacion = PESO_REVALORIZACION * (prevision_a_puntos(prevision_7d_pct) / 100.0)
    crudo = MULTIPLICADOR_BASE + bono_revalorizacion + bono_dificultad(dificultad)
    if crudo < 0:
        return 0.0
    return min(CAP_LIQUIDEZ, crudo)


def techo_puja_dinamico(
    valor_mercado: int | float,
    prevision_7d_pct: Any = None,
    dificultad: str | None = None,
    *,
    paso: int = PASO_PRECIO,
) -> int:
    """``valor × multiplicador``, redondeado al paso de precio y capado al +30 %."""
    if isinstance(valor_mercado, bool) or not isinstance(valor_mercado, (int, float)) or valor_mercado <= 0:
        return 0
    return _paso(float(valor_mercado) * multiplicador_puja(prevision_7d_pct, dificultad), paso)


def calcular_pujas(
    valor_actual: int | float,
    delta_hoy: int | float,
    valor_justo: int | float,
    *,
    tu_saldo: int | float | None,
    rivales: list[dict[str, Any]],
    posicion: str | None,
    prevision_7d_pct: Any = None,
    dificultad: str | None = None,
) -> dict[str, int | None]:
    """Puja recomendada, techo dinámico y puja que deja atrás al rival.

    ``puja_recomendada`` es el valor por 1,047 más la subida de hoy, si la hay.
    ``puja_maxima`` es el techo dinámico (previsión a 7 días y dificultad),
    con cap absoluto del +30 %. ``valor_justo`` se conserva en la firma para
    quien ya lo calculaba; ya no recorta el techo.
    ``puja_smart`` suma 0,1 M€ al rival interesado con más saldo cuando todos
    los que necesitan el puesto tienen menos caja que tú, y nunca supera el techo.
    """
    del valor_justo
    vacio = {"puja_recomendada": None, "puja_maxima": None, "puja_smart": None}
    if isinstance(valor_actual, bool) or not isinstance(valor_actual, (int, float)) or valor_actual <= 0:
        return vacio
    valor = float(valor_actual)
    subida = float(delta_hoy) if isinstance(delta_hoy, (int, float)) and not isinstance(delta_hoy, bool) else 0.0
    if subida < 0:
        subida = 0.0
    recomendada = _paso(valor * PRIMA_PUJA + subida)
    maxima = techo_puja_dinamico(valor, prevision_7d_pct, dificultad)
    if maxima <= 0:
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


def puja_pizarra(valor_actual: Any, delta_hoy: Any = 0) -> int | None:
    """La cifra redonda que copia quien usa La Pizarra: valor × 1,047 + subida, a 0,1 M€."""
    if isinstance(valor_actual, bool) or not isinstance(valor_actual, (int, float)) or valor_actual <= 0:
        return None
    subida = float(delta_hoy) if isinstance(delta_hoy, (int, float)) and not isinstance(delta_hoy, bool) else 0.0
    base = float(valor_actual) * PRIMA_PUJA + max(0.0, subida)
    redondeada = int(round(base / PASO_PIZARRA_EUR)) * PASO_PIZARRA_EUR
    return redondeada if redondeada > 0 else None


def diferencial_asimetrico(clave: Any) -> int:
    """Entre 140.000 y 220.000 €, estable por jugador y nunca múltiplo de 50.000.

    Una cifra que acaba en ``…640.000`` o ``…650.000`` es la que teclean los demás;
    esta no. Con la misma clave sale lo mismo en cada refresco.
    """
    semilla = zlib.crc32(str(clave).encode("utf-8"))
    return DIFERENCIALES_EUR[semilla % len(DIFERENCIALES_EUR)]


def alta_demanda(nota_mercado: Any, prevision_7d_pct: Any) -> bool:
    nota = nota_mercado if isinstance(nota_mercado, (int, float)) and not isinstance(nota_mercado, bool) else None
    if nota is not None and float(nota) >= UMBRAL_NOTA_DEMANDA:
        return True
    return prevision_a_puntos(prevision_7d_pct) > UMBRAL_PREVISION_DEMANDA


def puja_anti_pizarra(
    valor_actual: Any,
    delta_hoy: Any = 0,
    *,
    nota_mercado: Any = None,
    prevision_7d_pct: Any = None,
    clave: Any = None,
    maxima: int | None = None,
    saldo: int | float | None = None,
) -> dict[str, Any]:
    """Escalón de La Pizarra y, si el jugador está caliente, nuestra puja por encima.

    Solo se activa con ``nota_mercado >= 8`` o previsión a 7 días > 15 %. El
    diferencial no redondo gana los empates a quien puja la cifra de La Pizarra.
    Nunca pasa del techo dinámico ni de la caja; si no cabe, no se activa.
    """
    pizarra = puja_pizarra(valor_actual, delta_hoy)
    salida: dict[str, Any] = {
        "puja_pizarra": pizarra,
        "puja_anti_pizarra": None,
        "diferencial_anti_pizarra_eur": 0,
        "alta_demanda": alta_demanda(nota_mercado, prevision_7d_pct),
    }
    if pizarra is None or not salida["alta_demanda"]:
        return salida
    diferencial = diferencial_asimetrico(clave if clave is not None else valor_actual)
    objetivo = pizarra + diferencial
    if isinstance(maxima, int) and not isinstance(maxima, bool) and maxima > 0:
        objetivo = min(objetivo, maxima)
    if isinstance(saldo, (int, float)) and not isinstance(saldo, bool):
        objetivo = min(objetivo, int(math.floor(float(saldo) / PASO_PRECIO)) * PASO_PRECIO)
    objetivo = int(math.floor(objetivo / PASO_PRECIO)) * PASO_PRECIO
    if objetivo <= pizarra:
        return salida
    salida["puja_anti_pizarra"] = objetivo
    salida["diferencial_anti_pizarra_eur"] = objetivo - pizarra
    return salida


def capitanes(
    xi: list[dict[str, Any]],
    *,
    activo: bool | None = None,
) -> dict[str, dict[str, Any] | None]:
    """Capitán seguro (jornada, titularidad alta) y capitán de techo.

    Con el capitán apagado no hay nadie que doblar: las dos fichas salen vacías
    y el once se valora por los puntos de cada titular, sin x2.
    """
    if not (CAPITAN_ACTIVO if activo is None else activo):
        return {"capitan_seguro": None, "capitan_remontada": None}
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

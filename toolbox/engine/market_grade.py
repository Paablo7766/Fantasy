"""Nota de fichaje 0-10 y veredicto de mercado.

La nota reparte cien puntos de peso en cuatro bloques cuantitativos:

* 35 % impacto neto sobre el peor titular de la misma posición.
* 30 % revalorización a 7 días. Por encima del +15 % el bloque vale 10.
* 20 % titularidad y media de puntos de las últimas cinco jornadas.
* 15 % dificultad del próximo partido.

El saldo no entra en la ponderación: solo dice si el precio cabe en caja
y, si no cabe, lo añade a la frase.
"""

from __future__ import annotations

import math
from typing import Any

_PESO_IMPACTO = 0.35
_PESO_REVAL = 0.30
_PESO_FORMA = 0.20
_PESO_PARTIDO = 0.15

# +2,5 xP sobre el peor titular llena el bloque de impacto.
_IMPACTO_XP_TECHO = 2.5
# +15 % a siete días llena el bloque de revalorización.
_REVAL_TECHO_PCT = 15.0
# 7 puntos de media en las últimas jornadas llenan la racha.
_RACHA_TECHO = 7.0
_PRECIO_PARCHE = 6_000_000

_LINEA = {
    "POR": "portería",
    "DEF": "defensa",
    "MC": "mediocampo",
    "DEL": "delantera",
}
_DIFICULTAD = {
    "muy_facil": 10.0,
    "very_easy": 10.0,
    "facil": 8.0,
    "easy": 8.0,
    "medio": 5.0,
    "neutral": 5.0,
    "dificil": 2.5,
    "hard": 2.5,
    "muy_dificil": 0.0,
    "very_hard": 0.0,
}
_PARTIDO_DURO = {"dificil", "muy_dificil", "hard", "very_hard"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _clave(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return (
        value.strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace(" ", "_")
        .replace("-", "_")
    )


def _puntos_pct(value: Any) -> float | None:
    number = _num(value)
    if number is not None:
        return number
    if not isinstance(value, str):
        return None
    text = value.strip().replace("%", "").replace(",", ".")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _titularidad(value: Any) -> float | None:
    number = _num(value)
    if number is None or number < 0:
        return None
    if number > 1:
        if number > 100:
            return None
        number /= 100.0
    return min(1.0, number)


def _racha(jugador: dict[str, Any]) -> list[float]:
    raw = jugador.get("week_points")
    if not isinstance(raw, list):
        raw = jugador.get("racha")
    if not isinstance(raw, list):
        raw = jugador.get("recientes")
    if not isinstance(raw, list):
        return []
    puntos: list[float] = []
    for item in raw:
        if isinstance(item, dict):
            number = _num(item.get("puntos", item.get("points")))
        else:
            number = _num(item)
        if number is not None:
            puntos.append(number)
    return puntos[-5:]


def _xp(jugador: dict[str, Any]) -> float | None:
    for key in ("xp", "jornada_ev", "jornada"):
        number = _num(jugador.get(key))
        if number is not None:
            return number
    return None


def _precio(jugador: dict[str, Any]) -> float | None:
    for key in ("precio", "sale_price", "market_value", "valor"):
        number = _num(jugador.get(key))
        if number is not None and number > 0:
            return number
    return None


def _dificultad(jugador: dict[str, Any]) -> str:
    for key in ("dificultad", "difficulty", "calendar_difficulty"):
        clave = _clave(jugador.get(key))
        if clave:
            return clave
    fixture = jugador.get("fixture")
    if isinstance(fixture, dict):
        clave = _clave(fixture.get("difficulty") or fixture.get("dificultad"))
        if clave:
            return clave
    return ""


def _peor_titular(plantilla: list[dict[str, Any]], posicion: str) -> float | None:
    peores: list[float] = []
    for fila in plantilla:
        if not isinstance(fila, dict):
            continue
        if fila.get("en_xi") is False or fila.get("in_xi") is False:
            continue
        puesto = fila.get("position") or fila.get("posicion")
        if isinstance(puesto, str) and puesto != posicion:
            continue
        if not isinstance(puesto, str) or not puesto:
            continue
        xp = _xp(fila)
        if xp is None:
            for key in ("jornada", "jornada_ev", "expected_points", "points"):
                xp = _num(fila.get(key))
                if xp is not None:
                    break
        if xp is not None:
            peores.append(xp)
    if not peores:
        return None
    return min(peores)


def _bloque(value: float) -> float:
    return max(0.0, min(10.0, value))


def _coma(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _frase(
    *,
    delta: float,
    posicion: str,
    pct: float | None,
    dificultad: str,
    precio: float | None,
    saldo: float | None,
    caja: float | None = None,
) -> str:
    linea = _LINEA.get(posicion, "once")
    if delta >= 0.05 and pct is not None and pct > 0:
        texto = f"Mejora +{_coma(delta)} pts tu {linea} y sube +{round(pct)}% esta semana"
    elif delta >= 0.05 and pct is not None and pct < 0:
        texto = f"Mejora +{_coma(delta)} pts tu {linea}, aunque el valor cede {round(abs(pct))}% esta semana"
    elif delta >= 0.05:
        texto = f"Mejora +{_coma(delta)} pts tu {linea}"
    elif dificultad in _PARTIDO_DURO:
        texto = "Sobreprecio: su partido es difícil y no mejora a tus titulares"
    elif pct is not None and pct > 12:
        texto = f"No mejora a tus titulares, pero sube +{round(pct)}% esta semana"
    elif pct is not None and pct < 0:
        texto = f"No mejora a tus titulares y el valor cede {round(abs(pct))}% esta semana"
    else:
        texto = "No mejora a tus titulares"
    # ``saldo`` es el poder de puja (caja + crédito del 20 %); ``caja``, lo que tienes hoy.
    if precio is not None and saldo is not None and precio > saldo:
        texto = f"{texto}. No te llega ni con crédito"
    elif precio is not None and caja is not None and precio > caja:
        texto = f"{texto}. Se paga con crédito: vende antes del saque"
    return texto


def _num_o_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def calcular_nota_mercado(
    jugador: dict[str, Any],
    mi_plantilla: list[dict[str, Any]],
    saldo_disponible: float | int | None,
    caja: float | int | None = None,
) -> dict[str, Any]:
    """Nota 0-10, veredicto y la frase de una línea para la tarjeta de mercado."""
    if not isinstance(jugador, dict):
        jugador = {}
    plantilla = [fila for fila in mi_plantilla if isinstance(fila, dict)] if isinstance(mi_plantilla, list) else []
    posicion = jugador.get("position") or jugador.get("posicion")
    posicion = posicion if isinstance(posicion, str) else ""
    xp = _xp(jugador)
    peor = _peor_titular(plantilla, posicion) if posicion else None
    if xp is None:
        delta = 0.0
    elif peor is None:
        delta = max(0.0, xp)
    else:
        delta = max(0.0, xp - peor)
    impacto = _bloque(delta / _IMPACTO_XP_TECHO * 10.0)

    pct = _puntos_pct(jugador.get("prevision_7d_pct"))
    if pct is None or pct <= 0:
        reval = 0.0
    elif pct > _REVAL_TECHO_PCT:
        reval = 10.0
    else:
        reval = _bloque(pct / _REVAL_TECHO_PCT * 10.0)

    titular = _titularidad(jugador.get("p_titular"))
    partidos = _racha(jugador)
    media = sum(partidos) / len(partidos) if partidos else None
    bloques_forma: list[float] = []
    if titular is not None:
        bloques_forma.append(titular * 10.0)
    if media is not None:
        bloques_forma.append(_bloque(media / _RACHA_TECHO * 10.0))
    forma = sum(bloques_forma) / len(bloques_forma) if bloques_forma else 0.0

    dificultad = _dificultad(jugador)
    partido = _DIFICULTAD.get(dificultad, 5.0)

    cruda = (
        _PESO_IMPACTO * impacto
        + _PESO_REVAL * reval
        + _PESO_FORMA * forma
        + _PESO_PARTIDO * partido
    )
    nota = round(max(0.0, min(10.0, cruda)), 1)
    precio = _precio(jugador)
    saldo = _num(saldo_disponible)
    if nota >= 8.0:
        veredicto, etiqueta = "TE CONVIENE (TITULAR)", "TE CONVIENE"
    elif nota >= 7.0 and pct is not None and pct > 12:
        veredicto, etiqueta = "CHOLLO (ESPECULAR)", "ESPECULAR"
    elif 6.0 <= nota <= 7.5 and precio is not None and precio < _PRECIO_PARCHE:
        veredicto, etiqueta = "PARCHE ÚTIL", "PARCHE"
    elif nota < 6.0:
        # La nota no mira el precio: «sobreprecio» lo dice la puja por valor del plan.
        veredicto, etiqueta = "DESCARTAR", "DESCARTAR"
    else:
        veredicto, etiqueta = "VIGILAR", "VIGILAR"

    return {
        "nota_mercado": nota,
        "veredicto_mercado": veredicto,
        "etiqueta_mercado": etiqueta,
        "frase_mercado": _frase(
            delta=delta,
            posicion=posicion,
            pct=pct,
            dificultad=dificultad,
            precio=precio,
            saldo=saldo,
            caja=_num_o_none(caja),
        ),
        "impacto_xp": round(delta, 2),
        "cabe_en_caja": None if precio is None or saldo is None else precio <= saldo,
    }

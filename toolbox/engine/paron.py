"""Contexto de parón de selecciones: cuántos días de previsión son fiables.

El motor mide todo en "días hasta el primer saque". En un ciclo normal son 7 o
menos. En un parón (12-13 días sin liga) ese reloj se alarga, pero la previsión
de precio de cada jugador (``pct``) es a **7 días**. Prolongarla en línea recta
a 12 días sería inventar datos, así que el horizonte útil se topa en 7.

Qué NO hace: no cambia umbrales de venta ni la regla de rivales. Esas reglas
dependen de una sola opinión experta y se auditarán con el histórico antes de
tocarlas.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

#: Días a los que está calibrada la previsión de precio por jugador.
HORIZONTE_PREVISION_DIAS = 7.0
#: Un ciclo normal nunca pasa de aquí entre el último partido y el siguiente saque.
UMBRAL_PARON_DIAS = 7.5
#: Se sale a vender un día antes del saque, no en el último minuto.
MARGEN_VENTA_DIAS = 1.0


def _dias(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    dias = float(value)
    return dias if math.isfinite(dias) else None


def es_paron(dias_al_saque: object) -> bool:
    """True si falta más de un ciclo semanal para el próximo partido."""
    dias = _dias(dias_al_saque)
    return dias is not None and dias > UMBRAL_PARON_DIAS


def dias_de_prevision(dias_al_saque: object, margen: float = MARGEN_VENTA_DIAS) -> float | None:
    """Días de previsión de precio que se pueden usar: hasta el margen de venta, topados en 7."""
    dias = _dias(dias_al_saque)
    if dias is None:
        return None
    return min(HORIZONTE_PREVISION_DIAS, max(0.0, dias - margen))


def contexto_paron(dias_al_saque: object) -> dict[str, object]:
    """Resumen para pintar y auditar: si hay parón y cuánto se extrapola."""
    dias = _dias(dias_al_saque)
    paron = es_paron(dias)
    return {
        "paron": paron,
        "dias_al_saque": None if dias is None else round(dias, 2),
        "dias_prevision_usados": None if dias is None else round(dias_de_prevision(dias) or 0.0, 2),
        "horizonte_prevision": HORIZONTE_PREVISION_DIAS,
        "nota": (
            "Parón: la previsión de precio es a 7 días y no se extrapola más allá."
            if paron
            else None
        ),
    }


#: Parones con cierre conocido: (primer día del parón, cierre = primer saque de la jornada que vuelve).
#: Es el respaldo cuando el feed de LaLiga no trae calendario: sin él el motor
#: apunta al "próximo viernes" y no se entera de que hay dos semanas sin liga.
#: Hay que añadir una línea por parón (el calendario oficial se publica en verano).
PARONES_CONOCIDOS: tuple[tuple[str, str], ...] = (
    ("2026-11-08", "2026-11-20T21:00:00+01:00"),
)


def paron_conocido(now: datetime) -> tuple[datetime, datetime] | None:
    """(inicio, cierre) del parón que contiene ``now``, si está en la tabla."""
    zona = ZoneInfo("Europe/Madrid")
    for inicio, cierre in PARONES_CONOCIDOS:
        ini = datetime.fromisoformat(inicio).replace(tzinfo=zona)
        fin = datetime.fromisoformat(cierre)
        if ini <= now < fin:
            return ini, fin
    return None

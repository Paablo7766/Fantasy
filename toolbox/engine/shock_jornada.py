"""Shock de puntos de jornada: el jugador barato que explota y aún no ha subido.

Un jugador de menos de 5 M€ que hace 8+ puntos tiene un ratio puntos/precio
que el valor de mercado no refleja. LaLiga empieza a subirle el precio unos
días después y las webs externas lo recogen todavía más tarde. Entre el
partido y esa subida hay una ventana en la que comprar o clausular es barato.

La función no lee caché ni sale a la red: recibe los puntos recientes, el
precio y las señales de subida ya conocidas.
"""

from __future__ import annotations

from typing import Any

SHOCK_PRECIO_MAX = 5_000_000
SHOCK_PUNTOS_MIN = 8.0
# Puntos de la última jornada por millón de precio.
SHOCK_RATIO_MIN = 2.0
# Si el precio ya se ha movido más de esto en el día, la ventana está cerrada.
SHOCK_SUBIDA_PREVIA_MAX = 0.015


def _numero(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def detectar_shock(
    recientes: list[Any] | None,
    precio: int | float | None,
    delta_hoy: int | float | None = None,
    *,
    externo_sube: bool = False,
) -> dict[str, Any] | None:
    """Devuelve el shock de la última jornada o ``None`` si no lo hay.

    ``ventana`` es ``abierta`` mientras ni el precio de LaLiga ni las señales
    externas (``externo_sube``) han reaccionado, y ``cerrada`` cuando ya lo
    hicieron: el shock existe pero el sobreprecio ya está en camino.
    """
    precio_num = _numero(precio)
    if precio_num is None or precio_num <= 0 or precio_num >= SHOCK_PRECIO_MAX:
        return None
    puntos = [n for n in (_numero(item.get("points", item.get("puntos"))) if isinstance(item, dict) else _numero(item) for item in (recientes or [])) if n is not None]
    if not puntos:
        return None
    ultima = puntos[-1]
    if ultima < SHOCK_PUNTOS_MIN:
        return None
    ratio = ultima / (precio_num / 1_000_000.0)
    if ratio < SHOCK_RATIO_MIN:
        return None
    delta = _numero(delta_hoy)
    ya_se_mueve = delta is not None and delta / precio_num > SHOCK_SUBIDA_PREVIA_MAX
    abierta = not ya_se_mueve and not externo_sube
    return {
        "puntos": ultima,
        "ratio_pts_por_millon": round(ratio, 2),
        "precio": int(precio_num),
        "ventana": "abierta" if abierta else "cerrada",
    }

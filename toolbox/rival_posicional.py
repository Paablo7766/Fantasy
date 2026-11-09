"""Rival posicional: cuánto regala o seca cada equipo a cada puesto.

Para cada equipo rival y puesto se mide, en los partidos de titular de las actas
guardadas, cuántos puntos de **valoración + acciones** hizo un jugador por encima
(o por debajo) de su propia media. Quitar su media evita confundir «el rival
concede» con «los jugadores de esta muestra son buenos». El resultado se
encoge por el tamaño de la muestra y se acota: es un ajuste suave, no una señal
fuerte. Sin actas o sin calendario en caché no hay ajuste (0).
"""

from __future__ import annotations

from typing import Any

#: Observaciones que valen lo mismo que la media (encogimiento hacia 0).
K_ENCOGIMIENTO = 12.0
#: Tope del ajuste, en puntos. Con muestra pequeña el encogimiento lo deja mucho más abajo.
AJUSTE_MAX = 0.60
#: Por debajo de esto el ajuste es ruido y no se aplica.
AJUSTE_MIN = 0.10
#: Titularidades propias mínimas para usar a un jugador (hace falta su media).
MIN_TITULARIDADES = 3
MINUTOS_TITULAR = 45

_SLOT = {"POR": "PT", "PT": "PT", "DEF": "DF", "DF": "DF", "MC": "MC", "DEL": "DL", "DL": "DL"}


def _slot(position: Any) -> str | None:
    return _SLOT.get(str(position or "").upper())


def _por_jornada(mapa: Any) -> dict[int, Any]:
    """Claves de jornada como entero: la caché trae enteros y el JSON del almacén, textos."""
    if not isinstance(mapa, dict):
        return {}
    return {int(k): v for k, v in mapa.items() if str(k).isdigit()}


def _valoracion_y_acciones(bloque: Any) -> float | None:
    puntos = bloque.get("puntos") if isinstance(bloque, dict) else None
    if not isinstance(puntos, dict):
        return None
    return float(puntos.get("rating", 0.0)) + float(puntos.get("act", 0.0))


def construir_tabla(
    actas: dict[str, dict[str, Any]],
    rivales: dict[tuple[str, int], str],
    clave_equipo: Any,
) -> dict[str, dict[str, dict[str, float]]]:
    """``{rival: {puesto: {"n": n, "delta": media de desviaciones}}}``.

    ``rivales`` mapea ``(equipo, jornada)`` al rival de ese partido y
    ``clave_equipo`` normaliza el nombre de club de las actas.
    """
    acumulado: dict[str, dict[str, list[float]]] = {}
    for entry in actas.values():
        slot = _slot(entry.get("position"))
        equipo = clave_equipo(str(entry.get("team") or ""))
        weeks = _por_jornada(entry.get("weeks"))
        desglose = _por_jornada(entry.get("desglose"))
        if slot is None or not equipo:
            continue
        partidos: list[tuple[int, float]] = []
        for jornada, valor in weeks.items():
            if not isinstance(valor, (list, tuple)) or len(valor) < 2 or float(valor[1]) < MINUTOS_TITULAR:
                continue
            medida = _valoracion_y_acciones(desglose.get(jornada))
            if medida is not None:
                partidos.append((jornada, medida))
        if len(partidos) < MIN_TITULARIDADES:
            continue
        media = sum(m for _j, m in partidos) / len(partidos)
        for jornada, medida in partidos:
            rival = rivales.get((equipo, jornada))
            if rival:
                acumulado.setdefault(rival, {}).setdefault(slot, []).append(medida - media)
    return {
        rival: {slot: {"n": float(len(vals)), "delta": sum(vals) / len(vals)} for slot, vals in por_slot.items()}
        for rival, por_slot in acumulado.items()
    }


def ajuste_de(tabla: dict[str, dict[str, dict[str, float]]], rival_clave: str | None, position: Any) -> float:
    """Puntos a sumar a valoración + acciones contra este rival. 0 si no hay muestra."""
    slot = _slot(position)
    if not rival_clave or slot is None:
        return 0.0
    celda = (tabla.get(rival_clave) or {}).get(slot)
    if not celda:
        return 0.0
    n = float(celda["n"])
    encogido = float(celda["delta"]) * n / (n + K_ENCOGIMIENTO)
    if abs(encogido) < AJUSTE_MIN:
        return 0.0
    return round(max(-AJUSTE_MAX, min(AJUSTE_MAX, encogido)), 3)


_CACHE: dict[str, Any] = {"firma": None, "tabla": {}}


def tabla_en_cache() -> dict[str, dict[str, dict[str, float]]]:
    """Tabla de la temporada, releída solo si cambian las actas o el calendario."""
    from toolbox.cache import cache_root
    from toolbox.player_history import actas_en_cache
    from toolbox.understat import normalize_club, parse_openfootball_matchdays

    ruta = cache_root() / "laliga_2026_27.txt"
    try:
        actas = actas_en_cache()
        firma = (len(actas), sum(len(e.get("weeks") or {}) for e in actas.values()), ruta.stat().st_mtime_ns)
    except (OSError, Exception):  # noqa: BLE001 — sin calendario o actas, sin ajuste
        return {}
    if _CACHE["firma"] == firma:
        return _CACHE["tabla"]
    rivales: dict[tuple[str, int], str] = {}
    for (local, visitante), jornada in parse_openfootball_matchdays(ruta.read_text(encoding="utf-8")).items():
        rivales[(local, jornada)] = visitante
        rivales[(visitante, jornada)] = local
    tabla = construir_tabla(actas, rivales, normalize_club)
    _CACHE["firma"] = firma
    _CACHE["tabla"] = tabla
    return tabla


def ajuste_rival_posicional(rival: Any, position: Any) -> float:
    """Ajuste en puntos para ``position`` contra el club ``rival`` (nombre libre)."""
    if not isinstance(rival, str) or not rival.strip():
        return 0.0
    try:
        from toolbox.understat import normalize_club

        return ajuste_de(tabla_en_cache(), normalize_club(rival), position)
    except Exception:  # noqa: BLE001 — el ajuste es un extra: nunca tumba el xP
        return 0.0

"""Avisos push por reloj, sin red.

Todo sale de la foto ya guardada (``board``) y de la hora. Cero llamadas a
LaLiga: el vigilante de ``foto_previa`` ya pasa cada 5 min con el tablero leído
de disco y le cuelga esta revisión.

Aviso 1a: a 24 h y a 3 h del cierre de la jornada (primer saque de la próxima
jornada editable), si el once guardado tiene menos de 11, un lesionado o
sancionado, o la caja está en negativo. Cada aviso sale una sola vez por cierre
y tramo: los enviados se guardan en ``.cache/avisos_enviados.json`` para que un
reinicio del servidor no los repita.

Los avisos 1b (cláusula de un titular) y 1c (cambio de once probable) cuelgan de
``revisar`` con la misma tabla de enviados.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from toolbox import cache as cache_module

logger = logging.getLogger("fantasy.avisos_reloj")

#: Tramos de aviso, de más lejano a más cercano al cierre (horas).
TRAMOS_HORAS = (("24h", 24.0), ("3h", 3.0))
#: Una foto más vieja que esto se avisa como tal: el aviso puede estar desfasado.
FOTO_VIEJA_HORAS = 6.0
_CONSERVAR_DIAS = 10


def _ruta():
    return cache_module.cache_root() / "avisos_enviados.json"


def _leer() -> dict[str, str]:
    try:
        datos = json.loads(_ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _escribir(datos: dict[str, str], ahora: datetime) -> None:
    corte = (ahora - timedelta(days=_CONSERVAR_DIAS)).isoformat()
    podado = {k: v for k, v in datos.items() if isinstance(v, str) and v >= corte}
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(podado, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ruta)


def tramo_actual(horas: float | None) -> str | None:
    """El tramo más cercano al cierre en el que ya estamos (``3h`` gana a ``24h``)."""
    if horas is None or horas <= 0:
        return None
    actual = None
    for nombre, limite in TRAMOS_HORAS:
        if horas <= limite:
            actual = nombre
    return actual


def _nombre(fila: dict[str, Any]) -> str:
    return str(fila.get("nickname") or fila.get("name") or fila.get("player_id") or "jugador")


def problemas_del_once(board: dict[str, Any]) -> list[str]:
    """Qué le pasa al once guardado. Lista vacía = todo en orden (o sin datos para decirlo)."""
    from toolbox.analyzer import index_trends, own_squad, unavailable_reason

    squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else None
    if squads is None or squads.get("ok") is not True:
        return []
    propio = own_squad(squads)
    if propio is None:
        return []
    problemas: list[str] = []

    caja = propio.get("cash")
    if isinstance(caja, int) and not isinstance(caja, bool) and caja < 0:
        problemas.append(f"saldo negativo ({caja / 1_000_000:.1f} M)".replace(".", ","))

    guardado = optimize.get("saved_lineup") if isinstance(optimize, dict) and isinstance(optimize.get("saved_lineup"), dict) else None
    if guardado is None:
        return problemas
    filas = [f for f in guardado.get("xi") or [] if isinstance(f, dict)]
    if len(filas) < 11:
        problemas.append(f"once con {len(filas)}/11")

    tendencias = index_trends(board.get("trends") if isinstance(board.get("trends"), dict) else None)
    plantilla = {
        p.get("player_id"): p for p in propio.get("players") or [] if isinstance(p, dict) and p.get("player_id")
    }
    for fila in filas:
        pid = fila.get("player_id")
        jugador = plantilla.get(pid, fila)
        try:
            motivo = unavailable_reason(jugador, tendencias.get(pid) if isinstance(pid, str) else None)
        except Exception:  # noqa: BLE001 — un jugador raro no tumba el aviso
            motivo = None
        if motivo:
            problemas.append(f"{_nombre(jugador)} {motivo}")
    return problemas


def _edad_foto_horas(board: dict[str, Any], ahora: datetime) -> float | None:
    guardado = board.get("photo_saved_unix")
    if isinstance(guardado, (int, float)) and not isinstance(guardado, bool):
        return max(0.0, (ahora.timestamp() - float(guardado)) / 3600.0)
    return None


def aviso_once(
    board: dict[str, Any],
    ahora: datetime,
    *,
    cierre: datetime | None = None,
) -> dict[str, Any] | None:
    """El aviso 1a que toca ahora, o ``None``. No mira si ya se envió."""
    from toolbox.jornada_plan import _parse_iso, next_lock

    if cierre is None:
        trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
        cierre = _parse_iso(next_lock(trends, now=ahora))
    if cierre is None:
        return None
    horas = (cierre - ahora).total_seconds() / 3600.0
    tramo = tramo_actual(horas)
    if tramo is None:
        return None
    problemas = problemas_del_once(board)
    if not problemas:
        return None
    resto = f"{max(1, round(horas))} h" if horas >= 1 else f"{max(1, round(horas * 60))} min"
    cuerpo = f"Cierra en {resto}: " + "; ".join(problemas[:4]) + "."
    edad = _edad_foto_horas(board, ahora)
    if edad is not None and edad >= FOTO_VIEJA_HORAS:
        cuerpo += f" (Foto de hace {round(edad)} h: pulsa Actualizar.)"
    return {
        "clave": f"once:{cierre.astimezone(timezone.utc).isoformat()}:{tramo}",
        "title": "Tu once no está listo" if tramo == "24h" else "Último aviso: tu once",
        "body": cuerpo,
        "tag": f"once-{tramo}",
        "url": "/",
    }


def revisar(
    board: dict[str, Any],
    ahora: datetime | None = None,
    *,
    enviar: Callable[..., int] | None = None,
) -> list[str]:
    """Envía los avisos que toquen y no se hayan enviado. Devuelve las claves enviadas."""
    from toolbox import web_push

    if enviar is None:
        if not web_push.enabled():
            return []
        enviar = web_push.send_to_all
    momento = ahora or datetime.now(timezone.utc)
    if not isinstance(board, dict):
        return []
    enviados = _leer()
    nuevos: list[str] = []
    for aviso in (aviso_once(board, momento),):
        if aviso is None or aviso["clave"] in enviados:
            continue
        if enviar(aviso["title"], aviso["body"], url=aviso["url"], tag=aviso["tag"]) > 0:
            enviados[aviso["clave"]] = momento.isoformat()
            nuevos.append(aviso["clave"])
    if nuevos:
        _escribir(enviados, momento)
        logger.info("Avisos enviados: %s", nuevos)
    return nuevos

"""Foto del Marcador antes del primer saque de cada jornada.

Hasta nov 2026 la previsión de jornada solo se guardaba al abrir Laboratorio
(``/api/calibration`` → ``matchday_auto.auto_track_from_board``) y una vez al
día. Si nadie abría esa pestaña antes del primer partido no había foto (la J11
se fotografió el lunes con medio fin de semana jugado y hubo que tirarla).

Este vigilante corre en un hilo del servidor:

* En las ``VENTANA_HORAS`` previas al primer saque guarda la previsión desde el
  tablero ya descargado (sin red). Repite si el tablero cambió desde la última
  foto, para que quede la más reciente antes del saque.
* Si dentro de esa ventana el tablero tiene más de ``TABLERO_VIEJO_HORAS``, pide
  una actualización completa (la misma del botón «Actualizar»), una sola vez
  por saque. ``FOTO_PREVIA_REFRESCO=0`` lo desactiva.

``persist_snapshot`` ya descarta los partidos empezados (``toolbox.marcador``):
una foto tardía nunca se cuela como previsión.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger("fantasy.foto_previa")

VENTANA_HORAS = 3.0
#: A menos de esto del saque ya no se pide red: no daría tiempo.
MARGEN_REFRESCO_MIN = 20.0
TABLERO_VIEJO_HORAS = 3.0
INTERVALO_SEGUNDOS = 300.0

_ESTADO: dict[str, Any] = {"fotos": {}, "refrescos": set(), "hilo": None}
_LOCK = threading.Lock()


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _edad_tablero_horas(board: dict[str, Any], now: datetime) -> float | None:
    saved = board.get("photo_saved_unix")
    if isinstance(saved, (int, float)) and not isinstance(saved, bool):
        return max(0.0, (now.timestamp() - float(saved)) / 3600.0)
    stamp = _parse(board.get("dashboard_at"))
    if stamp is None:
        return None
    return max(0.0, (now - stamp).total_seconds() / 3600.0)


def primer_saque(board: dict[str, Any], now: datetime) -> datetime | None:
    from toolbox.jornada_plan import earliest_kickoff

    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    return _parse(earliest_kickoff(trends, now=now))


def en_ventana(saque: datetime | None, now: datetime) -> bool:
    return saque is not None and saque - timedelta(hours=VENTANA_HORAS) <= now < saque


def foto_previa(board: dict[str, Any], *, now: datetime | None = None, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Guarda la previsión si estamos en la ventana previa al primer saque y el tablero es nuevo."""
    momento = now or datetime.now(timezone.utc)
    if not isinstance(board, dict):
        return {"ok": False, "motivo": "sin_tablero"}
    saque = primer_saque(board, momento)
    if not en_ventana(saque, momento):
        return {"ok": True, "hecho": False, "motivo": "fuera_de_ventana", "saque": saque.isoformat() if saque else None}
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    market = board.get("market") if isinstance(board.get("market"), dict) else None
    if squads is None or trends is None or squads.get("ok") is not True:
        return {"ok": False, "motivo": "tablero_incompleto"}
    firma = (saque.isoformat(), board.get("photo_saved_unix") or board.get("dashboard_at"))
    with _LOCK:
        if _ESTADO["fotos"].get(saque.isoformat()) == firma:
            return {"ok": True, "hecho": False, "motivo": "ya_fotografiado", "saque": saque.isoformat()}

    from toolbox.matchday_auto import _db_path, _load_track

    track = _load_track()
    propia = conn is None
    if propia:
        ruta = _db_path()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(ruta)
    try:
        track._ensure_schema(conn)
        from toolbox.marcador import reparar_historico

        # Antes de fotografiar: fuera puntos prematuros y previsiones tomadas tras un saque.
        reparar_historico(conn)
        league_id = trends.get("league_id") if isinstance(trends.get("league_id"), str) else None
        snap = track.run_snapshot(conn, league=league_id, jornada_id=None, fresh=False, squads=squads, trends=trends, market=market)
    finally:
        if propia:
            conn.close()
    with _LOCK:
        _ESTADO["fotos"][saque.isoformat()] = firma
    return {
        "ok": True,
        "hecho": True,
        "saque": saque.isoformat(),
        "jornada_id": snap.get("jornada_id"),
        "filas": snap.get("written"),
    }


def debe_refrescar(board: dict[str, Any], now: datetime) -> bool:
    """Tablero viejo dentro de la ventana, con tiempo de sobra y sin haberlo pedido ya para este saque."""
    if os.environ.get("FOTO_PREVIA_REFRESCO", "1").strip() == "0":
        return False
    saque = primer_saque(board, now)
    if not en_ventana(saque, now) or saque - now < timedelta(minutes=MARGEN_REFRESCO_MIN):
        return False
    edad = _edad_tablero_horas(board, now)
    if edad is None or edad < TABLERO_VIEJO_HORAS:
        return False
    with _LOCK:
        return saque.isoformat() not in _ESTADO["refrescos"]


def marcar_refresco(board: dict[str, Any], now: datetime) -> None:
    saque = primer_saque(board, now)
    if saque is not None:
        with _LOCK:
            _ESTADO["refrescos"].add(saque.isoformat())


def una_pasada(
    cargar_tablero: Callable[[], dict[str, Any] | None],
    refrescar: Callable[[], None] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    momento = now or datetime.now(timezone.utc)
    board = cargar_tablero()
    if not isinstance(board, dict):
        return {"ok": False, "motivo": "sin_tablero"}
    if refrescar is not None and debe_refrescar(board, momento):
        marcar_refresco(board, momento)
        refrescar()
        board = cargar_tablero() or board
    return foto_previa(board, now=momento)


def arrancar_vigilante(
    cargar_tablero: Callable[[], dict[str, Any] | None],
    refrescar: Callable[[], None] | None = None,
) -> bool:
    """Hilo demonio que hace ``una_pasada`` cada ``INTERVALO_SEGUNDOS``. Idempotente."""
    with _LOCK:
        if _ESTADO["hilo"] is not None and _ESTADO["hilo"].is_alive():
            return False

        def bucle() -> None:
            while True:
                try:
                    resultado = una_pasada(cargar_tablero, refrescar)
                    if resultado.get("hecho"):
                        logger.info("Foto previa guardada: %s", resultado)
                except Exception:  # noqa: BLE001 — el vigilante nunca tumba el servidor
                    logger.debug("Foto previa fallida", exc_info=True)
                time.sleep(INTERVALO_SEGUNDOS)

        hilo = threading.Thread(target=bucle, name="foto-previa", daemon=True)
        _ESTADO["hilo"] = hilo
        hilo.start()
        return True

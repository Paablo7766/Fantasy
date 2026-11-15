"""Foto del mercado unos minutos antes del cierre de las 14:08 (Madrid).

Tu puja, el número de pujas y el valor de cada anuncio solo los publica la API
mientras la subasta está abierta. Esta foto los guarda en el diario de subastas
de Supabase (``market_board``) para que, cuando el feed diga quién ganó, quede
la pareja «lo que pujaste / lo que pagó el ganador».

La llama un cron externo (Supabase ``pg_cron``, ver ``scripts/foto_cierre_cron.sql``)
porque Render gratuito duerme tras 15 min sin visitas: un reloj interno no se
despertaría. El cron llama a las 13:47 y el servidor espera un rato al azar
(hasta ``ESPERA_MAX_MIN``) para que la hora no sea siempre la misma. El retraso
cabe en los 15 min de Render y la foto sale antes de las 14:03.

Una sola petición a LaLiga (``LaligaClient.market_snapshot``), con las mismas
protecciones de ``net.py``: pausa humana, solo lectura y kill switch.
"""

from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger("fantasy.foto_cierre")

MADRID = ZoneInfo("Europe/Madrid")
#: Solo se acepta la llamada en esta franja (hora de Madrid). El cron de Supabase
#: va en UTC y se programa para invierno y para verano: la que cae fuera se ignora.
VENTANA_DESDE = time(13, 30)
VENTANA_HASTA = time(14, 3)
#: La foto nunca sale después de esta hora: el cierre es a las 14:08.
ULTIMA_FOTO = time(14, 3)
ESPERA_MAX_MIN = 13.0

_LOCK = threading.Lock()
_ESTADO: dict[str, Any] = {"dia": None, "programada": None, "hecha": None, "resultado": None}


def ahora_madrid(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(MADRID)


def en_ventana(now: datetime | None = None) -> bool:
    hora = ahora_madrid(now).time()
    return VENTANA_DESDE <= hora < VENTANA_HASTA


def espera_al_azar(now: datetime | None = None, rng: random.Random | None = None) -> float:
    """Segundos de espera: al azar, sin pasar de ``ESPERA_MAX_MIN`` ni de las 14:03."""
    local = ahora_madrid(now)
    tope = datetime.combine(local.date(), ULTIMA_FOTO, tzinfo=MADRID)
    margen = max(0.0, (tope - local).total_seconds())
    maximo = min(ESPERA_MAX_MIN * 60.0, margen)
    return (rng or random).uniform(0.0, maximo)


def estado() -> dict[str, Any]:
    with _LOCK:
        return dict(_ESTADO)


def reservar_dia(now: datetime | None = None) -> bool:
    """Una foto por día. ``False`` si hoy ya hay una programada o hecha."""
    dia = ahora_madrid(now).date().isoformat()
    with _LOCK:
        if _ESTADO["dia"] == dia:
            return False
        _ESTADO.update({"dia": dia, "programada": None, "hecha": None, "resultado": None})
        return True


def capturar(client: Any, league: str | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Baja el mercado (una petición) y lo guarda en el diario de subastas."""
    from toolbox.auction_journal import capture_live

    market = client.market_snapshot(league)
    own = market.get("own_team_id")
    squads = {
        "league_id": market.get("league_id"),
        "squads": [{"team_id": own, "is_self": True}] if isinstance(own, str) and own else [],
    }
    # Sin libros: con ``feed_latest`` vacío el diario no cierra ninguna subasta.
    # Se cierran después, en el siguiente refresco normal que traiga el feed.
    momento = now or datetime.now(timezone.utc)
    guardado = capture_live(market, squads, [], now=momento)
    listings = [row for row in market.get("listings") or [] if isinstance(row, dict)]
    return {
        "anuncios": len(listings),
        "con_tu_puja": sum(1 for row in listings if isinstance(row.get("own_bid"), int)),
        "guardadas": guardado.get("board", 0),
        "a": ahora_madrid(momento).isoformat(),
    }


def programar(
    lanzar: Callable[[], dict[str, Any]],
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
    dormir: Callable[[float], None] | None = None,
    al_fallar: Callable[[BaseException], None] | None = None,
) -> float:
    """Arranca un hilo que espera al azar y llama a ``lanzar``. Devuelve la espera."""
    import time as _time

    espera = espera_al_azar(now, rng)
    previsto = ahora_madrid(now) + timedelta(seconds=espera)
    with _LOCK:
        _ESTADO["programada"] = previsto.isoformat()

    def _trabajo() -> None:
        (dormir or _time.sleep)(espera)
        try:
            resultado = lanzar()
        except BaseException as exc:  # noqa: BLE001 — el hilo no muere en silencio
            with _LOCK:
                _ESTADO["resultado"] = {"ok": False, "error": repr(exc)}
            logger.exception("La foto antes del cierre falló")
            if al_fallar is not None:
                al_fallar(exc)
            return
        with _LOCK:
            _ESTADO["hecha"] = ahora_madrid().isoformat()
            _ESTADO["resultado"] = {"ok": True, **resultado}
        logger.info("Foto antes del cierre guardada: %s", resultado)

    threading.Thread(target=_trabajo, name="foto-cierre", daemon=True).start()
    return espera


def _reset_para_pruebas() -> None:
    with _LOCK:
        _ESTADO.update({"dia": None, "programada": None, "hecha": None, "resultado": None})

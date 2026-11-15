"""Fotos del mercado antes del cierre de las 14:08 (Madrid).

Tu puja, el número de pujas y el valor de cada anuncio solo los publica la API
mientras la subasta está abierta. Estas fotos los guardan en el diario de
subastas de Supabase (``market_board``) para que, cuando el feed diga quién
ganó, quede la pareja «lo que pujaste / lo que pagó el ganador».

Dos fotos al día, cada una con **una sola** petición a LaLiga
(``LaligaClient.market_snapshot``) y las protecciones de ``net.py``:

* **Temprana**, entre las 13:48 y las 14:01 al azar. Si la última falla, queda esta.
* **Última**, entre las 14:06:15 y las 14:07:10 al azar. Muchas pujas entran en
  los últimos minutos: esta las recoge. Una puja de los últimos ~50 s no se ve.

Las dispara un cron externo (Supabase ``pg_cron``, ``scripts/foto_cierre_cron.sql``)
porque Render gratuito duerme tras 15 min sin visitas: la llamada de las 13:47
programa la temprana y la de las 14:00 la última. La franja decide cuál es.
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
TEMPRANA = "temprana"
ULTIMA = "ultima"
#: Franja (Madrid) en la que se acepta cada llamada. El cron va en UTC y se
#: programa para invierno y para verano: la llamada que cae fuera se ignora.
FRANJAS = {
    TEMPRANA: (time(13, 30), time(14, 0)),
    ULTIMA: (time(14, 0), time(14, 5)),
}
ESPERA_MAX_MIN = 13.0
TOPE_TEMPRANA = time(14, 1)
#: La última foto sale al azar dentro de este tramo; el cierre es a las 14:08:00.
ULTIMA_DESDE = time(14, 6, 15)
ULTIMA_HASTA = time(14, 7, 10)

_LOCK = threading.Lock()


def _vacio() -> dict[str, Any]:
    return {"dia": None, "programada": None, "hecha": None, "resultado": None}


_ESTADO: dict[str, dict[str, Any]] = {TEMPRANA: _vacio(), ULTIMA: _vacio()}


def ahora_madrid(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(MADRID)


def fase_de(now: datetime | None = None) -> str | None:
    """Qué foto toca según la hora de Madrid. ``None`` fuera de las dos franjas."""
    hora = ahora_madrid(now).time()
    for fase, (desde, hasta) in FRANJAS.items():
        if desde <= hora < hasta:
            return fase
    return None


def en_ventana(now: datetime | None = None) -> bool:
    return fase_de(now) is not None


def espera_al_azar(now: datetime | None = None, rng: random.Random | None = None, fase: str | None = None) -> float:
    """Segundos hasta la foto. Temprana: hasta 13 min y nunca después de las 14:01.
    Última: un instante al azar entre las 14:06:15 y las 14:07:10."""
    local = ahora_madrid(now)
    tirada = rng or random
    fase = fase or fase_de(now) or TEMPRANA
    if fase == ULTIMA:
        desde = datetime.combine(local.date(), ULTIMA_DESDE, tzinfo=MADRID)
        hasta = datetime.combine(local.date(), ULTIMA_HASTA, tzinfo=MADRID)
        objetivo = desde + timedelta(seconds=tirada.uniform(0.0, (hasta - desde).total_seconds()))
        return max(0.0, (objetivo - local).total_seconds())
    tope = datetime.combine(local.date(), TOPE_TEMPRANA, tzinfo=MADRID)
    margen = max(0.0, (tope - local).total_seconds())
    return tirada.uniform(0.0, min(ESPERA_MAX_MIN * 60.0, margen))


def estado() -> dict[str, Any]:
    with _LOCK:
        return {fase: dict(valores) for fase, valores in _ESTADO.items()}


def reservar_dia(fase: str = TEMPRANA, now: datetime | None = None) -> bool:
    """Una foto de cada fase por día. ``False`` si hoy ya está programada o hecha."""
    dia = ahora_madrid(now).date().isoformat()
    with _LOCK:
        if _ESTADO[fase]["dia"] == dia:
            return False
        _ESTADO[fase] = {**_vacio(), "dia": dia}
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
    # La segunda foto del día pisa recuentos y valores; tu puja no se pierde si
    # ya no viene (``merge_own_bids``).
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
    fase: str = TEMPRANA,
    now: datetime | None = None,
    rng: random.Random | None = None,
    dormir: Callable[[float], None] | None = None,
    al_fallar: Callable[[BaseException], None] | None = None,
) -> float:
    """Arranca un hilo que espera al azar y llama a ``lanzar``. Devuelve la espera."""
    import time as _time

    espera = espera_al_azar(now, rng, fase)
    previsto = ahora_madrid(now) + timedelta(seconds=espera)
    with _LOCK:
        _ESTADO[fase]["programada"] = previsto.isoformat()

    def _trabajo() -> None:
        (dormir or _time.sleep)(espera)
        try:
            resultado = lanzar()
        except BaseException as exc:  # noqa: BLE001 — el hilo no muere en silencio
            with _LOCK:
                _ESTADO[fase]["resultado"] = {"ok": False, "error": repr(exc)}
            logger.exception("La foto %s antes del cierre falló", fase)
            if al_fallar is not None:
                al_fallar(exc)
            return
        with _LOCK:
            _ESTADO[fase]["hecha"] = ahora_madrid().isoformat()
            _ESTADO[fase]["resultado"] = {"ok": True, **resultado}
        logger.info("Foto %s antes del cierre guardada: %s", fase, resultado)

    threading.Thread(target=_trabajo, name=f"foto-cierre-{fase}", daemon=True).start()
    return espera


def _reset_para_pruebas() -> None:
    with _LOCK:
        for fase in _ESTADO:
            _ESTADO[fase] = _vacio()

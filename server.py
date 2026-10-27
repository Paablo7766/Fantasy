"""Tablero local de LALIGA Fantasy.

Sirve la interfaz de ``static/index.html`` y reutiliza la caja de herramientas.
El servidor solo lee: no envía pujas ni cláusulas.

    python run_dashboard.py
    uvicorn server:app --reload --port 8000

Abre http://127.0.0.1:8000
"""

from __future__ import annotations

import contextlib
import functools
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from toolbox import project_root
from toolbox import api_meter
from toolbox.analyzer import (
    clause_multiple,
    exposed_clause_rule,
    index_trends,
    is_at_risk,
    display_price_delta,
    lineup_points,
    official_price_delta,
    optimize_from_documents,
    own_squad,
    probability,
    projected_lineup_points,
    sell_signal,
)
from toolbox.auth import AuthError, login_with_browser
from toolbox.bidding import flip_from_documents, load_activity, needs_from_documents
from toolbox.cache import ResponseCache, cache_root
from toolbox.bid_war import rival_snapshots
from toolbox.clause_intel import build_clause_intel
from toolbox.clause_board import build_clause_board
from toolbox.cache import CashLedgerStore
from toolbox.portfolio import (
    build_portfolio,
    ledger_for_squad,
    ledger_index,
    league_activity_feed,
    merge_ledgers,
    player_name_index,
    team_activity_profile,
)
from toolbox.rival_intel import events_from_ledgers, get_financial_intel, madrid_day_of
from toolbox.jornada_plan import (
    attach_clause_window,
    experts_from_pages,
    plan_from_documents,
    read_expert_note,
    write_expert_note,
)
from toolbox.engine_calibration import build_calibration_report, persist_market_decisions
from toolbox.market_maker import get_market_recommendations
from toolbox.data_health import build_field_health
from toolbox.matchday_auto import auto_track_from_board
from toolbox.market_intel import decisions_from_board
from toolbox.quant_valuation import build_quant_radar
from toolbox.league_race import build_league_race, mode_from_squads, posture_from_squads
from toolbox.net import FantasyHttpError, LaligaClient, network_log_path, no_network
from toolbox.net import (
    HUMAN_PACER,
    HUMAN_REQUESTS_PER_REFRESH,
    LALIGA_ENV_VAR,
    PRODUCTION_ENV,
    close_official_session,
    environment,
    is_production,
    kill_switch_state,
    network_sealed,
    offline_mode,
    pace_stretch_for,
)
from toolbox.normalize import SCHEMA_VERSION, attach_image_urls, daily_market_is_past
from toolbox.scrapers import build_trends, refresh_squad_titularity_in_index

logger = logging.getLogger("fantasy.dashboard")

STATIC_DIR = project_root() / "static"
# **No hay TTL.** La foto en RAM y la de disco son la fuente de verdad hasta que
# el usuario pulsa «Actualizar». Abrir el panel 6 h después devuelve la misma
# foto al instante y sin una sola petición de red.
# A partir de aquí la foto se marca como vieja (solo etiqueta informativa).
# No dispara red: sirve para pintar «Actualizado hace 6 h» y avisar al usuario.
PHOTO_STALE_AFTER_SECONDS = 15 * 60.0
# Un refresco fresh (plantillas + scrapers) puede pasar de 3 min; los waiters
# deben aguantar al dueño del vuelo en lugar de devolver 504 mientras sigue vivo.
# Con la cadencia de ultra-baja frecuencia la foto completa (tier ``full``,
# ~60 GET a ~33 s de media) ronda los 32 min, así que 10 min se quedaban cortos
# y un segundo clic devolvía 504 con el dueño del vuelo aún trabajando. El
# margen cubre la pasada más lenta (todos los máximos: ~41 min) sin colgar una
# petición HTTP para siempre.
SNAPSHOT_WAIT_SECONDS = 45 * 60.0

_VOID_COPY = {
    "negative_cash": "El saldo es negativo y la jornada completa puntúa 0.",
    "empty_slot": "El once no tiene 11 jugadores válidos y la jornada completa puntúa 0.",
}
_STATUS_FOR_CODE = {
    "auth_required": 401,
    "unauthorized": 401,
    "league_required": 400,
    "league_not_found": 404,
    "not_found": 404,
    "rate_limited": 429,
    "login_timeout": 408,
    "login_cancelled": 400,
    "login_in_progress": 409,
    "browser_missing": 503,
    "league_lookup": 502,
    # Modo avión: no es un fallo del tablero, es que falta la copia en disco.
    "offline_miss": 503,
    "offline": 503,
}


class _Flight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: dict[str, Any] | None = None
        self.error: BaseException | None = None


_state_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_inflight: dict[str, _Flight] = {}

# ---------------------------------------------------------------------------
# Estado visible del refresco
# ---------------------------------------------------------------------------
# Un POST /api/plan/refresh puede tardar media hora (cadencia humana de 12–25 s
# por GET). Sin un sitio donde mirar, el usuario solo ve «Actualizando…» y no
# sabe si avanza o está colgado: exactamente la ceguera que este bloque evita.
# Es RAM y solo lo escribe ``refresh_board``; ningún GET lo modifica.
_refresh_status_lock = threading.Lock()
_refresh_status: dict[str, Any] = {}


def _refresh_status_start(tier: str, league: str | None) -> dict[str, Any]:
    started = time.time()
    status = {
        "running": True,
        "tier": tier,
        "league": league,
        "phase": "core" if tier == "core" else "full",
        "phase_label": "Foto rápida (mercado, plantillas, once)" if tier == "core" else "Foto completa (scrapers)",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "started_unix": started,
        "finished_at": None,
        "elapsed_seconds": 0.0,
        "calls": 0,
        "by_source": [],
        "current_source": None,
        "current_label": None,
        "in_flight": 0,
        # ``result_ok``, no ``ok``: ``ok`` es el del documento (la respuesta es
        # válida) y lo usan todos los endpoints. Mezclarlos hacía que un refresco
        # fallido se pintara como correcto, porque el snapshot reescribía ``ok``.
        "result_ok": None,
        "error": None,
    }
    with _refresh_status_lock:
        _refresh_status.clear()
        _refresh_status.update(status)
    return status


def _refresh_status_phase(phase: str, label: str) -> None:
    with _refresh_status_lock:
        if not _refresh_status.get("running"):
            return
        _refresh_status["phase"] = phase
        _refresh_status["phase_label"] = label


def _refresh_status_finish(*, ok: bool, error: Any = None) -> None:
    with _refresh_status_lock:
        if not _refresh_status:
            return
        _refresh_status["running"] = False
        _refresh_status["result_ok"] = ok
        _refresh_status["error"] = error
        _refresh_status["finished_at"] = datetime.now(timezone.utc).isoformat()
        if isinstance(_refresh_status.get("started_unix"), (int, float)):
            _refresh_status["elapsed_seconds"] = round(
                max(0.0, time.time() - float(_refresh_status["started_unix"])), 1
            )


def _refresh_elapsed(status: dict[str, Any]) -> float:
    """Duración de la pasada. Congelada al terminar, no «hace cuánto empezó».

    Antes se recalculaba en cada lectura, así que un refresco acabado hace tres
    horas seguía diciendo «10 035 s»: el panel no podía distinguir «lleva 10
    minutos descargando» de «terminó, y fue hace 10 minutos».
    """
    frozen = status.get("elapsed_seconds")
    if status.get("running") is False and isinstance(frozen, (int, float)) and not isinstance(frozen, bool):
        return float(frozen)
    started = status.get("started_unix")
    if isinstance(started, (int, float)) and not isinstance(started, bool):
        return round(max(0.0, time.time() - float(started)), 1)
    return 0.0


def refresh_status_snapshot() -> dict[str, Any]:
    """Estado del refresco en curso (o del último), con el ritmo ya medido.

    Devuelve siempre un documento ``ok``: que no haya refresco es información
    («nada en marcha»), no un error. Los contadores de llamadas se recalculan
    aquí contra ``started_unix`` para que el panel pueda decir «37 llamadas en
    4 min» sin que el hilo de descarga tenga que actualizar nada.
    """
    with _refresh_status_lock:
        status = dict(_refresh_status)
    if not status:
        return {
            "ok": True,
            "command": "refresh-status",
            "schema_version": SCHEMA_VERSION,
            "running": False,
            "phase": None,
            "phase_label": None,
            "started_at": None,
            "finished_at": None,
            "elapsed_seconds": 0.0,
            "calls": 0,
            "cache_hits": 0,
            "network": network_sealed() is False,
            "by_source": [],
            "current_source": None,
            "current_label": None,
            "in_flight": 0,
            "last_activity_seconds": None,
            "result_ok": None,
        }
    started = status.get("started_unix")
    live = api_meter.calls_since(float(started)) if isinstance(started, (int, float)) else {
        "calls": 0,
        "cache_hits": 0,
        "by_source": [],
        "current": None,
        "current_label": None,
        "in_flight": 0,
        "last_activity_seconds": None,
    }
    status.update(
        {
            "ok": True,
            "command": "refresh-status",
            "schema_version": SCHEMA_VERSION,
            "elapsed_seconds": _refresh_elapsed(status),
            "calls": live["calls"],
            "cache_hits": live.get("cache_hits", 0),
            # ``network`` explica por qué ``calls`` puede ser 0 con la descarga
            # viva: en air-gap no sale ni una petición y todo es caché. Sin este
            # campo el panel solo puede decir «0 llamadas», que se lee como
            # «colgado» cuando en realidad está leyendo de disco.
            "network": network_sealed() is False,
            "by_source": live["by_source"],
            "current_source": live["current"],
            "current_label": live["current_label"],
            "in_flight": live["in_flight"],
            "last_activity_seconds": live.get("last_activity_seconds"),
        }
    )
    status.pop("started_unix", None)
    return status


# Sin refresco en segundo plano: la única salida a red es ``refresh_board``,
# invocada exclusivamente desde ``POST /api/plan/refresh``.
_open_market_lock = threading.Lock()
_open_market_mem: dict[str, tuple[float, dict[str, Any]]] = {}
OPEN_MARKET_TTL_SECONDS = 90.0
_CALIBRATION_TTL_SECONDS = 300.0
_calibration_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_calibration_report_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _own_team_id(board: dict[str, Any]) -> str | None:
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    own = own_squad(squads)
    if isinstance(own, dict) and isinstance(own.get("team_id"), str):
        return own["team_id"]
    return None


def _board_league_id(board: dict[str, Any] | None, query_league: str | None = None) -> str | None:
    """Id canónico de liga del tablero (p. ej. 018668579), no el slug corto de la URL (?league=7)."""
    if isinstance(board, dict):
        trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
        if isinstance(trends.get("league_id"), str) and trends["league_id"].strip():
            return trends["league_id"].strip()
        squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
        if isinstance(squads.get("league_id"), str) and squads["league_id"].strip():
            return squads["league_id"].strip()
        market = board.get("market") if isinstance(board.get("market"), dict) else {}
        if isinstance(market.get("league_id"), str) and market["league_id"].strip():
            return market["league_id"].strip()
    return _league(query_league)


def _calibration_report(board: dict[str, Any]) -> dict[str, Any]:
    league_id = _board_league_id(board)
    team_id = _own_team_id(board)
    key = f"{league_id or '_'}:{team_id or '_'}"
    now = time.time()
    cached = _calibration_report_cache.get(key)
    if cached and now - cached[0] < _CALIBRATION_TTL_SECONDS:
        return cached[1]
    auto_meta: dict[str, Any] | None = None
    try:
        auto_meta = auto_track_from_board(board)
        if auto_meta.get("evaluated") or (auto_meta.get("snapshot") and not auto_meta.get("skipped")):
            _calibration_report_cache.pop(key, None)
            _calibration_cache.pop(key, None)
    except Exception as exc:
        logger.debug("matchday auto-track skipped: %s", exc)
    try:
        report = build_calibration_report(league_id=league_id, own_team_id=team_id)
        report["ok"] = True
        if auto_meta:
            report["matchday_auto"] = auto_meta
    except Exception as exc:
        logger.warning("engine calibration failed: %s", exc)
        report = {
            "ok": False,
            "error": {"code": "calibration_failed", "message": str(exc)},
            "coverage": {"price_snapshots": 0, "activity_buys": 0, "matchday_jornadas": 0},
        }
    _calibration_report_cache[key] = (now, report)
    if report.get("ok") is not False:
        confidence = report.get("engine_confidence")
        if isinstance(confidence, dict):
            _calibration_cache[key] = (now, confidence)
    return report


def _engine_confidence_snapshot(board: dict[str, Any]) -> dict[str, Any]:
    report = _calibration_report(board)
    if report.get("ok") is False:
        return {"score": None, "band": "unknown", "label": "Sin histórico", "notes": []}
    payload = report.get("engine_confidence") if isinstance(report.get("engine_confidence"), dict) else {}
    return payload


def _calibration_for_client(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("ok") is False:
        return report
    crest = report.get("sell_at_crest") if isinstance(report.get("sell_at_crest"), dict) else {}
    samples = crest.get("samples")
    if isinstance(samples, list) and len(samples) > 6:
        crest = {**crest, "samples": samples[:6]}
    return {
        "ok": True,
        "schema_version": report.get("schema_version"),
        "command": "calibration",
        "league_id": report.get("league_id"),
        "database": report.get("database"),
        "coverage": report.get("coverage"),
        "points": report.get("points"),
        "sell_at_crest": crest,
        "pujar": report.get("pujar"),
        "win_probability": report.get("win_probability"),
        "engine_confidence": report.get("engine_confidence"),
    }


def clear_ram_snapshot_cache() -> None:
    """Vacía solo la foto en memoria; el disco sigue siendo la fuente de verdad."""
    with _state_lock:
        _cache.clear()
        _inflight.clear()
    with _open_market_lock:
        _open_market_mem.clear()
    _calibration_cache.clear()
    _calibration_report_cache.clear()


def _apply_image_index(board: dict[str, Any], index: dict[str, str]) -> None:
    """Rellena ``image_url`` en todas las filas de jugador del tablero."""
    if not index:
        return
    market = board.get("market")
    if isinstance(market, dict):
        attach_image_urls(market.get("listings"), index)
    squads = board.get("squads")
    if isinstance(squads, dict):
        for squad in squads.get("squads") or []:
            if isinstance(squad, dict):
                attach_image_urls(squad.get("players"), index)
    trends = board.get("trends")
    if isinstance(trends, dict):
        for key in ("players", "rising", "falling", "undervalued", "availability"):
            attach_image_urls(trends.get(key), index)
    optimize = board.get("optimize")
    if isinstance(optimize, dict):
        for key in ("xi", "benched", "excluded"):
            attach_image_urls(optimize.get(key), index)
        for gap in list(optimize.get("gaps") or []) + list(optimize.get("market_fills") or []):
            if isinstance(gap, dict):
                attach_image_urls(gap.get("options"), index)
        saved = optimize.get("saved_lineup")
        if isinstance(saved, dict):
            attach_image_urls(saved.get("xi"), index)
            attach_image_urls(saved.get("bench"), index)
    flip = board.get("flip")
    if isinstance(flip, dict):
        attach_image_urls(flip.get("signings"), index)


def ensure_board_images(board: dict[str, Any], *, index: dict[str, str] | None = None) -> dict[str, Any]:
    """Garantiza fotos aunque la foto en RAM/disco sea anterior al catálogo CDN."""
    if not isinstance(board, dict):
        return board
    lookup = index
    if lookup is None:
        try:
            with LaligaClient() as client:
                lookup = client.image_index(fresh=False)
        except Exception:
            logger.exception("No se pudo cargar el catálogo de fotos de jugadores")
            return board
    _apply_image_index(board, lookup or {})
    return board


def clear_snapshot_cache() -> None:
    """Vacía la foto en memoria y en disco. Lo usan las pruebas."""
    clear_ram_snapshot_cache()
    _clear_disk_snapshots()


def _league_dir_key(league: str | None) -> str:
    raw = (league or "").strip() or "_default"
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)


def _disk_snapshot_path(kind: str, league: str | None, root: Path | None = None) -> Path:
    base = root or cache_root()
    return base / "dashboard" / _league_dir_key(league) / f"{kind}.json"


def _clear_disk_snapshots() -> None:
    root = cache_root() / "dashboard"
    if not root.is_dir():
        return
    for path in root.rglob("*.json"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("No se pudo borrar caché de tablero %s", path)


def _board_has_data(value: dict[str, Any] | None) -> bool:
    """``True`` si la foto trae mercado o plantillas con contenido.

    Sirve para no dejar que una foto vacía pise una real. No se exige
    ``trends``: la pasada rápida (``core``) aún no los tiene y es legítima.
    """
    if not isinstance(value, dict):
        return False
    market = value.get("market")
    if isinstance(market, dict) and (market.get("listings") or market.get("players")):
        return True
    squads = value.get("squads")
    if isinstance(squads, dict) and squads.get("squads"):
        return True
    return False


def _write_disk_snapshot(
    kind: str,
    league: str | None,
    value: dict[str, Any],
    *,
    root: Path | None = None,
) -> None:
    """Persiste la foto. Es la única fuente de verdad entre refrescos.

    Una foto sin mercado ni plantillas no sobrescribe otra con datos: eso es
    un tablero de juguete (el que dejó una prueba en ``.cache/`` el 25-10 a las
    13:30) y borrar la foto buena dejaba al panel sin once.
    """
    if not _board_has_data(value):
        logger.warning("Foto %s/%s descartada: no trae mercado ni plantillas.", kind, league)
        return
    path = _disk_snapshot_path(kind, league, root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(value)
        for key in ("stale", "is_stale", "photo_age_seconds"):
            payload.pop(key, None)
        envelope = {
            "saved_unix": time.time(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "league": (league or "").strip(),
            "value": payload,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.exception("No se pudo guardar la foto del tablero en disco")


def _disk_snapshot_envelope(kind: str, league: str | None) -> dict[str, Any] | None:
    """Sobre completo de la foto (``value`` + ``saved_unix``). Sin caducidad."""
    path = _disk_snapshot_path(kind, league)
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Foto de tablero ilegible en %s", path)
        return None
    if not isinstance(envelope, dict):
        return None
    value = envelope.get("value")
    if not isinstance(value, dict):
        return None
    return envelope


def _read_disk_snapshot(kind: str, league: str | None) -> dict[str, Any] | None:
    """Última foto guardada, sin importar su antigüedad.

    El TTL ya no existe: una foto de hace seis horas se sirve igual que una de
    hace un minuto. Quien decide si está vieja es la interfaz, con
    ``last_updated``/``photo_age_seconds``. Nunca toca la red.
    """
    envelope = _disk_snapshot_envelope(kind, league)
    if envelope is None:
        return None
    value = envelope.get("value")
    return value if isinstance(value, dict) else None


def _disk_saved_unix(kind: str, league: str | None) -> float | None:
    envelope = _disk_snapshot_envelope(kind, league)
    if envelope is None:
        return None
    saved = envelope.get("saved_unix")
    return float(saved) if isinstance(saved, (int, float)) and not isinstance(saved, bool) else None


def _photo_day(board: dict[str, Any] | None) -> str | None:
    """Día Europe/Madrid de la foto que se sirve. ``None`` si no hay marca."""
    if not isinstance(board, dict):
        return None
    stamp = board.get("last_updated") or board.get("dashboard_at")
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    return madrid_day_of(stamp)


def _photo_age(board: dict[str, Any] | None) -> float | None:
    """Segundos desde que se guardó la foto que se está sirviendo."""
    if not isinstance(board, dict):
        return None
    age = board.get("photo_age_seconds")
    if isinstance(age, (int, float)) and not isinstance(age, bool):
        return max(0.0, float(age))
    return None


def _stamp_photo(board: dict[str, Any], saved_unix: float | None) -> dict[str, Any]:
    """Anota de cuándo es la foto. Solo presentación: no cambia datos.

    ``stale``/``is_stale`` dicen si la foto tiene más de
    ``PHOTO_STALE_AFTER_SECONDS``; la edad exacta va en ``photo_age_seconds``
    para que la UI pueda escribir «hace 6 h» sin adivinar.
    """
    stamped = dict(board)
    now = time.time()
    if saved_unix is None:
        saved_unix = now
    age = max(0.0, now - float(saved_unix))
    saved_at = datetime.fromtimestamp(float(saved_unix), tz=timezone.utc).isoformat()
    stamped["last_updated"] = saved_at
    stamped["photo_age_seconds"] = round(age, 1)
    stamped["is_stale"] = age > PHOTO_STALE_AFTER_SECONDS
    stamped["stale"] = stamped["is_stale"]
    return stamped


# El refresco en segundo plano ya no existe: era la vía por la que un GET
# acababa gastando peticiones a LALIGA. Toda descarga pasa por
# ``refresh_board``, que solo se invoca desde ``POST /api/plan/refresh``.


def _empty_trends(*, league_id: Any = None, league_name: Any = None) -> dict[str, Any]:
    """Tendencias vacías para la foto rápida: el once no espera a los scrapers."""
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "trends",
        "league_id": league_id if isinstance(league_id, str) else None,
        "league_name": league_name if isinstance(league_name, str) else None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "partial": True,
        "catalog_count": 0,
        "form_note": None,
        "sources": {},
        "rising": [],
        "falling": [],
        "undervalued": [],
        "availability": [],
        "players": [],
        "matching": {"threshold": 0.85, "linked": 0, "manual": 0, "low_confidence": 0, "audits": []},
    }


def load_core_snapshot(league: str | None, fresh: bool) -> dict[str, Any]:
    """Foto rápida: mercado, plantillas, once y caja. Sin scrapers externos."""
    with LaligaClient() as client:
        _refresh_status_phase("mercado", "Mercado de LALIGA")
        market = client.market_document(league, fresh=fresh)
        _refresh_status_phase("plantillas", "Plantillas de la liga")
        squads = client.squads_document(league, fresh=fresh)
        trends = _empty_trends(league_id=squads.get("league_id"), league_name=squads.get("league_name"))
        store = ResponseCache()
        try:
            _refresh_status_phase("once", "Once óptimo y caja")
            optimized = optimize_from_documents(squads, None, cache=store, fresh=fresh, market=market)
            own = own_squad(squads)
            team_id = own.get("team_id") if isinstance(own, dict) else None
            if isinstance(team_id, str) and team_id:
                optimized["saved_lineup"] = client.saved_lineup(team_id, fresh=fresh)
            flipped = flip_from_documents(
                market,
                squads,
                trends,
                lineup=optimized,
                cache=store,
                fresh=fresh,
            )
            league_id = squads.get("league_id") if isinstance(squads.get("league_id"), str) else None
            # El historial de la temporada no se re-pagina en cada Actualizar:
            # 40 páginas en serie + 429 dejaban Caja pillada al 25 %.
            _refresh_status_phase("actividad", "Historial de pujas")
            activity = load_activity(client, league_id, fresh=fresh)
            _refresh_status_phase("caja", "Caja y necesidades")
            needs = needs_from_documents(
                market,
                squads,
                trends,
                activity,
                cache=store,
                fresh=fresh,
            )
        finally:
            store.close()
        board = {
            "dashboard_at": datetime.now(timezone.utc).isoformat(),
            "market": market,
            "squads": squads,
            "trends": trends,
            "optimize": optimized,
            "flip": flipped,
            "needs": needs,
            "tier": "core",
        }
        _refresh_status_phase("imagenes", "Fotos de jugador")
        return ensure_board_images(board, index=client.image_index(fresh=fresh))


def load_snapshot(league: str | None, fresh: bool) -> dict[str, Any]:
    """Foto completa: incluye scrapers de mercado, titularidad y valor."""
    with LaligaClient() as client:
        _refresh_status_phase("mercado", "Mercado de LALIGA")
        market = client.market_document(league, fresh=fresh)
        _refresh_status_phase("plantillas", "Plantillas de la liga")
        squads = client.squads_document(league, fresh=fresh)
        _refresh_status_phase("scrapers", "Scrapers: puntos, forma y valor")
        trends = build_trends(
            league=league,
            fresh=fresh,
            laliga=client,
            market=market,
            squads=squads,
        )
        store = ResponseCache()
        try:
            _refresh_status_phase("once", "Once óptimo y caja")
            optimized = optimize_from_documents(squads, trends, cache=store, fresh=fresh, market=market)
            own = own_squad(squads)
            team_id = own.get("team_id") if isinstance(own, dict) else None
            if isinstance(team_id, str) and team_id:
                optimized["saved_lineup"] = client.saved_lineup(team_id, fresh=fresh)
            flipped = flip_from_documents(
                market,
                squads,
                trends,
                lineup=optimized,
                cache=store,
                fresh=fresh,
            )
            league_id = squads.get("league_id") if isinstance(squads.get("league_id"), str) else None
            _refresh_status_phase("actividad", "Historial de pujas")
            activity = load_activity(client, league_id, fresh=fresh)
            _refresh_status_phase("caja", "Caja y necesidades")
            needs = needs_from_documents(
                market,
                squads,
                trends,
                activity,
                cache=store,
                fresh=fresh,
            )
        finally:
            store.close()
        board = {
            "dashboard_at": datetime.now(timezone.utc).isoformat(),
            "market": market,
            "squads": squads,
            "trends": trends,
            "optimize": optimized,
            "flip": flipped,
            "needs": needs,
            "tier": "full",
        }
        return ensure_board_images(board, index=client.image_index(fresh=fresh))


def _trends_hollow_doc(trends: dict[str, Any] | None) -> bool:
    """True si no hay catálogo enriquecido (p. ej. foto core sin scrapers)."""
    if not isinstance(trends, dict):
        return True
    players = trends.get("players")
    return not isinstance(players, list) or len(players) < 20


def _board_trends_hollow(board: dict[str, Any] | None) -> bool:
    if not isinstance(board, dict):
        return True
    trends = board.get("trends")
    return _trends_hollow_doc(trends if isinstance(trends, dict) else None)


def _full_warms_core(board: dict[str, Any]) -> bool:
    """Solo una foto full enriquecida puede sustituir la foto rápida core."""
    return not _board_market_past(board) and not _board_trends_hollow(board)


def _borrow_full_trends(league: str | None) -> dict[str, Any] | None:
    """Tendencias de la foto ``full`` en RAM o disco, sin volver a scrapear."""
    league_key = (league or "").strip()

    def _take(board: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(board, dict):
            return None
        trends = board.get("trends")
        if isinstance(trends, dict) and not _trends_hollow_doc(trends):
            return trends
        return None

    with _state_lock:
        for key, (_stamp, board) in _cache.items():
            if not key.startswith("full:") or not key.endswith(f":{league_key}"):
                continue
            hit = _take(board)
            if hit is not None:
                return hit
        holder = _inflight.get(f"refresh:full:{league_key}")
        if holder is not None and isinstance(holder.value, dict):
            hit = _take(holder.value)
            if hit is not None:
                return hit
    disk = _read_disk_snapshot("full", league)
    if isinstance(disk, dict):
        trends = disk.get("trends")
        if isinstance(trends, dict) and not _trends_hollow_doc(trends):
            return trends
    return None


def _enrich_board_trends(board: dict[str, Any], league: str | None) -> dict[str, Any]:
    """Inyecta tendencias completas cuando la foto core llegó sin scrapers."""
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    if not _trends_hollow_doc(trends):
        return board
    borrowed = _borrow_full_trends(league)
    if borrowed is None:
        return board
    enriched = dict(board)
    enriched["trends"] = borrowed
    return enriched


def _snapshot_day_deltas(league_id: str | None) -> dict[str, int]:
    try:
        from toolbox.cache import PriceSnapshotStore

        latest = PriceSnapshotStore().latest_prices(league_id)
    except Exception:
        logger.debug("Sin snapshots de precio para enriquecer plantillas", exc_info=True)
        return {}
    out: dict[str, int] = {}
    for player_id, snap in latest.items():
        if not isinstance(snap, dict):
            continue
        change = snap.get("market_value_change")
        if isinstance(change, int) and not isinstance(change, bool):
            out[player_id] = change
    return out


def _patch_optimize_titularity(
    optimize: dict[str, Any],
    squad: dict[str, Any],
    trends: dict[str, Any] | None,
    *,
    fresh: bool = False,
    posture: Any = None,
) -> dict[str, Any]:
    """Corrige titularidad en el once ya calculado sin repetir el solver."""
    from toolbox.analyzer import ObjectiveWeights, candidates_from_squad

    indexed = index_trends(trends)
    refresh_squad_titularity_in_index(squad, indexed, fresh=fresh)
    roster = {
        candidate.player_id: candidate
        for candidate in candidates_from_squad(squad, indexed, weights=ObjectiveWeights(), posture=posture)
        if candidate.player_id
    }
    patched = dict(optimize)
    for key in ("xi", "benched", "excluded"):
        rows = patched.get(key)
        if not isinstance(rows, list):
            continue
        updated_rows: list[Any] = []
        for row in rows:
            if not isinstance(row, dict):
                updated_rows.append(row)
                continue
            copy = dict(row)
            player_id = copy.get("player_id")
            if isinstance(player_id, str):
                candidate = roster.get(player_id)
                if candidate is not None:
                    copy["p_titular"] = candidate.p_titular
                    copy["p_titular_source"] = candidate.p_titular_source
                    copy["jornada_ev"] = candidate.jornada_ev
                    copy["expected_points"] = candidate.expected_points
                    copy["points_if_starts"] = candidate.points_if_starts
                    copy["objective"] = candidate.objective
                    if candidate.player_status is not None:
                        copy["player_status"] = candidate.player_status
            updated_rows.append(copy)
        patched[key] = updated_rows
    # Los puntos del once se recalculan con la titularidad ya corregida: si no,
    # el delta contra el once guardado se mediría con dos métricas distintas.
    patched["lineup_expected_points"] = lineup_points(patched.get("xi"))[0]
    return patched


def _enrich_board_optimize(
    board: dict[str, Any],
    league: str | None,
    *,
    fresh: bool = False,
) -> dict[str, Any]:
    """Enriquece titularidad del once; solo recalcula el solver con ``fresh``."""
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    if _trends_hollow_doc(trends):
        board = _enrich_board_trends(board, league)
        trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    if _trends_hollow_doc(trends):
        return board
    squads = board.get("squads")
    if not isinstance(squads, dict):
        return board
    squad = own_squad(squads)
    if squad is None:
        return board
    existing = board.get("optimize") if isinstance(board.get("optimize"), dict) else None
    market = board.get("market") if isinstance(board.get("market"), dict) else None
    posture = posture_from_squads(squads)
    enriched = dict(board)
    if fresh or existing is None or existing.get("ok") is False:
        store = ResponseCache()
        try:
            optimized = optimize_from_documents(
                squads,
                trends,
                cache=store,
                fresh=fresh,
                market=market,
                posture=posture,
            )
        finally:
            store.close()
        enriched["optimize"] = optimized
        return enriched
    enriched["optimize"] = _patch_optimize_titularity(existing, squad, trends, fresh=fresh, posture=posture)
    return enriched


def _board_market_past(board: dict[str, Any] | None) -> bool:
    if not isinstance(board, dict):
        return False
    market = board.get("market")
    return daily_market_is_past(market if isinstance(market, dict) else None)


def _remember_open_market(league: str | None, market: Any) -> None:
    if not isinstance(market, dict) or daily_market_is_past(market):
        return
    key = (league or "").strip()
    with _open_market_lock:
        _open_market_mem[key] = (time.monotonic(), market)


def _store_snapshot(
    kind: str,
    league: str | None,
    fresh: bool,
    value: dict[str, Any],
    *,
    cache_dir: Path | None = None,
) -> None:
    """Guarda la foto en RAM y en disco. Solo la llama ``refresh_board``."""
    now = time.monotonic()
    league_key = (league or "").strip()
    suffix = f"{'1' if fresh else '0'}:{league_key}"
    warm = f"0:{league_key}"
    clean = dict(value)
    for key in ("stale", "photo_age_seconds", "is_stale"):
        clean.pop(key, None)
    # La misma liga puede estar cacheada en RAM bajo otra clave (``_default``,
    # el id canónico, un slug corto). Sin invalidarla, el GET seguía sirviendo
    # la copia anterior aunque el disco ya tuviera la nueva: la descarga
    # terminaba bien y el panel no cambiaba. Se borra antes de escribir para no
    # tirar lo que se acaba de guardar.
    _drop_ram_for_league(clean, league)
    with _state_lock:
        _cache[f"{kind}:{suffix}"] = (now, clean)
        _cache[f"{kind}:{warm}"] = (now, clean)
        if kind == "full" and _full_warms_core(clean):
            # La foto completa enriquecida también vale como core: mismo mercado/once.
            _cache[f"core:{suffix}"] = (now, clean)
            _cache[f"core:{warm}"] = (now, clean)
    _write_disk_snapshot(kind, league, clean, root=cache_dir)
    if kind == "full" and _full_warms_core(clean):
        _write_disk_snapshot("core", league, clean, root=cache_dir)
    _remember_open_market(league, clean.get("market"))


def _drop_ram_for_league(board: dict[str, Any], league: str | None) -> None:
    """Olvida en RAM toda foto de esta liga, pida como se pida.

    ``_read_board`` casa primero en RAM y solo cae al disco si no hay nada. Con
    la misma liga guardada bajo varias claves (``_default``, id canónico, slug),
    un refresco escrito en una clave dejaba vivas las otras: el disco tenía la
    foto nueva y el panel seguía pintando la de antes. La liga se compara por el
    ``league_id`` de dentro porque la clave de carpeta no siempre lo es.
    """
    league_id = _snapshot_league_id(board)
    key_league = (league or "").strip()
    with _state_lock:
        for key in list(_cache):
            cached = _cache.get(key)
            if not cached or not isinstance(cached[1], dict):
                continue
            cached_value = cached[1]
            if league_id is not None and _snapshot_league_id(cached_value) == league_id:
                _cache.pop(key, None)
                continue
            if key.endswith(f":0:{key_league}") or key.endswith(f":1:{key_league}"):
                _cache.pop(key, None)


def _core_boards(league: str | None) -> list[dict[str, Any]]:
    suffix = (league or "").strip()
    found: list[dict[str, Any]] = []
    with _state_lock:
        for key, (_stamp, board) in list(_cache.items()):
            parts = key.split(":", 2)
            if len(parts) == 3 and parts[0] == "core" and parts[2] == suffix and isinstance(board, dict):
                found.append(board)
    disk = _read_disk_snapshot("core", league)
    if isinstance(disk, dict):
        found.append(disk)
    return found


def _best_open_core(league: str | None) -> dict[str, Any] | None:
    best: tuple[str, dict[str, Any]] | None = None
    for board in _core_boards(league):
        market = board.get("market")
        if not isinstance(market, dict) or daily_market_is_past(market):
            continue
        fetched = market.get("fetched_at") if isinstance(market.get("fetched_at"), str) else ""
        if best is None or fetched >= best[0]:
            best = (fetched, board)
    return None if best is None else best[1]


def _cached_open_market(league: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Devuelve (mercado abierto, foto core donante). El donante puede ser None.

    Solo mira RAM y disco: la lectura del tablero no descarga. Si ninguna foto
    trae el mercado abierto se devuelve ``(None, None)`` y la foto se sirve tal
    cual; el usuario decide si pulsa Actualizar.
    """
    key = (league or "").strip()
    with _open_market_lock:
        hit = _open_market_mem.get(key)
        if hit is not None and (time.monotonic() - hit[0]) < OPEN_MARKET_TTL_SECONDS:
            market = hit[1]
            if isinstance(market, dict) and not daily_market_is_past(market):
                return market, None
    donor = _best_open_core(league)
    if isinstance(donor, dict):
        market = donor.get("market")
        if isinstance(market, dict) and not daily_market_is_past(market):
            _remember_open_market(league, market)
            return market, donor
    return None, None


def _history_buys(board: dict[str, Any] | None) -> int:
    needs = board.get("needs") if isinstance(board, dict) else None
    history = needs.get("history") if isinstance(needs, dict) else None
    if not isinstance(history, dict):
        return 0
    for key in ("buy_count", "priced_count", "war_count"):
        value = history.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return 0


def _overlay_core_history(board: dict[str, Any], league: str | None) -> dict[str, Any]:
    """La foto full puede ser vieja. Si Caja ya trajo el historial, las pujas lo usan."""
    donor = None
    best_at = ""
    for candidate in _core_boards(league):
        stamp = candidate.get("dashboard_at") if isinstance(candidate.get("dashboard_at"), str) else ""
        if _history_buys(candidate) <= 0:
            continue
        if donor is None or stamp >= best_at:
            donor = candidate
            best_at = stamp
    if not isinstance(donor, dict):
        return board
    if _history_buys(donor) <= _history_buys(board):
        return board
    updated = dict(board)
    needs = donor.get("needs")
    if isinstance(needs, dict):
        updated["needs"] = needs
    return updated


def _overlay_open_market(board: dict[str, Any], league: str | None) -> dict[str, Any]:
    """Sustituye el mercado cerrado de una foto vieja por el que sigue abierto.

    La foto ``full`` puede tardar minutos (scrapers). Mientras tanto el
    mercado del día ya está en la foto ``core`` o en la API. Sin este cambio
    la mesa sigue pintando la oferta de la liga que ya cerró.
    """
    market = board.get("market") if isinstance(board.get("market"), dict) else None
    if not daily_market_is_past(market):
        _remember_open_market(league, market)
        return board
    current, donor = _cached_open_market(league)
    if not isinstance(current, dict):
        return board
    updated = dict(board)
    updated["market"] = current
    if isinstance(donor, dict):
        for key in ("squads", "optimize", "needs"):
            if isinstance(donor.get(key), dict):
                updated[key] = donor[key]
    squads = updated.get("squads") if isinstance(updated.get("squads"), dict) else {}
    trends = updated.get("trends") if isinstance(updated.get("trends"), dict) else None
    optimize = updated.get("optimize") if isinstance(updated.get("optimize"), dict) else None
    try:
        updated["flip"] = flip_from_documents(current, squads, trends, lineup=optimize, fresh=False)
    except Exception:
        logger.exception("No se pudo recalcular el flip del mercado vigente")
    return updated


def snapshot(league: str | None, *, tier: str = "full") -> dict[str, Any]:
    """Devuelve la última foto guardada. **Nunca toca la red.**

    Este es el camino de lectura: ``GET /api/...`` y el arranque del panel. Si
    hay foto en RAM o en disco se sirve tal cual, aunque tenga seis horas. Si no
    hay ninguna, se levanta ``offline_miss`` para que la interfaz pida pulsar
    Actualizar en lugar de descargar por su cuenta.

    No admite ``fresh``: la descarga vive en :func:`refresh_board`, que solo
    llama ``POST /api/plan/refresh``.

    ``core`` (once/plantillas/caja) y ``full`` (tendencias/scrapers) se sirven
    del mismo almacén; ``core`` prefiere la foto completa cuando existe porque
    trae las mismas plantillas con más señales.
    """
    kind = "core" if tier == "core" else "full"
    board = _read_board(kind, league)
    if board is None and kind == "core":
        # Sin foto rápida, la completa vale: mismo mercado y mismas plantillas.
        board = _read_board("full", league)
    if board is None:
        raise FantasyHttpError(
            "Todavía no hay ninguna foto guardada. Pulsa Actualizar para descargar la primera.",
            status=503,
            code="offline_miss",
        )
    return _present_board(board, league, kind=kind)


def _snapshot_league_id(value: dict[str, Any] | None) -> str | None:
    """Id canónico de liga que lleva dentro una foto guardada.

    Se lee de los documentos que lo traen (plantillas, mercado, tendencias) y
    nunca del nombre de la carpeta: la carpeta es solo la clave con la que el
    usuario pidió la foto, y esa clave puede ser un slug corto (``7``), el id
    canónico (``018668579``) o nada (``_default``).
    """
    if not isinstance(value, dict):
        return None
    for block in ("trends", "squads", "market"):
        document = value.get(block)
        if not isinstance(document, dict):
            continue
        league_id = document.get("league_id")
        if isinstance(league_id, str) and league_id.strip():
            return league_id.strip()
    return None


def _newest_same_league_snapshot(kind: str, league: str | None, *, root: Path | None = None) -> dict[str, Any] | None:
    """Foto más reciente de **la misma liga**, guardada bajo otra clave.

    El panel puede pedir ``?league=7`` (slug de la URL), ``?league=018668579``
    (id canónico) o no pedir nada (``_default``). Las tres rutas apuntaban a
    carpetas distintas, así que la misma liga convivía en tres fotos con edades
    diferentes: abrir un enlace con el id canónico servía datos de hace días
    mientras la portada mostraba los de hace un minuto. Eso es exactamente
    «veo información desactualizada» y no tenía nada que ver con el refresco.

    Solo se miran dos candidatas —la carpeta del id canónico y ``_default``— y
    se filtra por ``mtime`` antes de leer el JSON: escanear todas las carpetas
    en cada GET costaba 13 s con la foto completa en disco.
    """
    current = _disk_snapshot_envelope(kind, league)
    if current is None:
        # Sin foto bajo la clave pedida no se sabe a qué liga se refiere ese
        # ``?league=``: adivinar sirviendo otra liga sería peor que decir que
        # no hay foto. La búsqueda solo corrige fotos **de la misma liga**.
        return None
    current_id = _snapshot_league_id(current.get("value"))
    if current_id is None:
        return None
    current_saved = current.get("saved_unix")
    best_saved = (
        float(current_saved)
        if isinstance(current_saved, (int, float)) and not isinstance(current_saved, bool)
        else None
    )
    candidates = [candidate for candidate in (current_id, None) if _league_dir_key(candidate) != _league_dir_key(league)]
    if not candidates:
        return None
    best: dict[str, Any] | None = None
    for candidate in candidates:
        path = _disk_snapshot_path(kind, candidate, root)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0:
            continue
        saved = _disk_saved_unix(kind, candidate)
        if saved is None:
            continue
        if best_saved is not None and saved <= best_saved:
            continue
        envelope = _disk_snapshot_envelope(kind, candidate)
        value = (envelope or {}).get("value")
        if not isinstance(value, dict):
            continue
        # La liga manda sobre la antigüedad: una foto nueva de otra liga nunca
        # sustituye a la liga pedida.
        if _snapshot_league_id(value) != current_id:
            continue
        best_saved = saved
        best = {"value": value, "saved_unix": saved}
    return best


def _disk_snapshot_mtime(kind: str, league: str | None) -> float | None:
    """``mtime`` del fichero de foto. Solo un ``stat``: barato y sin parsear.

    Se usa para detectar que otro proceso (el VPS, o un refresco que terminó en
    otra pestaña) escribió una foto más nueva que la que hay en RAM.
    """
    path = _disk_snapshot_path(kind, league)
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _read_board(kind: str, league: str | None) -> dict[str, Any] | None:
    """Foto de RAM (si la hay) o de disco. Sin caducidad y sin red."""
    key = f"{kind}:0:{(league or '').strip()}"
    with _state_lock:
        hit = _cache.get(key)
    if hit is not None and isinstance(hit[1], dict):
        board = hit[1]
        if kind != "full" or not _board_trends_hollow(board):
            # La RAM gana solo si no hay disco más nuevo. Sin esta comprobación,
            # una foto escrita por otro proceso se quedaba invisible hasta
            # reiniciar: la descarga terminaba y el panel no cambiaba.
            cached_saved = board.get("photo_saved_unix")
            disk_mtime = _disk_snapshot_mtime(kind, league)
            stale_ram = (
                disk_mtime is not None
                and isinstance(cached_saved, (int, float))
                and not isinstance(cached_saved, bool)
                and disk_mtime > float(cached_saved) + 1.0
            )
            if not stale_ram:
                return board
            with _state_lock:
                _cache.pop(key, None)
    disk = _read_disk_snapshot(kind, league)
    saved = _disk_saved_unix(kind, league)
    # Misma liga, otra clave de carpeta: la más nueva gana. Sin esto, un
    # ``?league=<id canónico>`` servía una foto de hace días mientras la
    # portada (sin parámetro) mostraba la de hace un minuto.
    newer = _newest_same_league_snapshot(kind, league)
    if newer is not None:
        newer_saved = newer.get("saved_unix")
        if isinstance(newer_saved, (int, float)) and not isinstance(newer_saved, bool):
            if saved is None or float(newer_saved) > float(saved):
                disk = newer.get("value")
                saved = float(newer_saved)
    if kind == "full" and _board_trends_hollow(disk):
        # Una foto completa sin catálogo no vale para Mercado: la rápida, con
        # liga y plantillas reales, es mejor foto que una «full» a medias.
        fallback = _read_disk_snapshot("core", league)
        if fallback is not None:
            disk = fallback
            kind = "core"
            key = f"core:0:{(league or '').strip()}"
            saved = _disk_saved_unix(kind, league)
    if disk is None:
        return None
    board = _remember_photo(disk, saved)
    with _state_lock:
        _cache[key] = (time.monotonic(), board)
    return board


def _remember_photo(board: dict[str, Any], saved_unix: float | None) -> dict[str, Any]:
    """Adjunta la edad de la foto a la copia en RAM, sin reescribir el disco."""
    stamped = _stamp_photo(board, saved_unix)
    if saved_unix is not None:
        # ``_present_board`` vuelve a sellar; sin esta marca la edad de una foto
        # leída de disco se perdería y todo parecería recién descargado.
        stamped["photo_saved_unix"] = float(saved_unix)
    return stamped


def _present_board(board: dict[str, Any], league: str | None, *, kind: str) -> dict[str, Any]:
    """Aplica los overlays de solo lectura antes de servir la foto."""
    saved_unix = _board_saved_unix(board)
    served = _stamp_photo(board, saved_unix)
    if kind == "core":
        return _overlay_core_history(served, league)
    return _overlay_core_history(_overlay_open_market(served, league), league)


def _board_saved_unix(board: dict[str, Any]) -> float | None:
    """Instante de captura ya anotado en la foto, si lo trae."""
    for key in ("photo_saved_unix", "saved_unix"):
        value = board.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def refresh_board(league: str | None, *, tier: str = "full", track_status: bool = True) -> dict[str, Any]:
    """Descarga una foto nueva y sobrescribe la caché. **Única vía con red.**

    Solo se llama desde ``POST /api/plan/refresh``. Comparte un único vuelo por
    liga y tier: dos clics seguidos no duplican los scrapers.

    ``track_status=False`` deja el latido en manos de quien orquesta varias
    pasadas seguidas (``POST /api/plan/refresh`` encadena core y full): si cada
    tramo cerrara su propio estado, el panel vería un parpadeo de «terminado»
    entre la foto rápida y la completa y daría la descarga por acabada antes de
    que empezaran los scrapers.
    """
    kind = "core" if tier == "core" else "full"
    key = f"{kind}:0:{(league or '').strip()}"
    flight_key = f"refresh:{kind}:{(league or '').strip()}"
    # La descarga tarda minutos: fijamos el directorio al empezar para que un
    # cambio de entorno a mitad de vuelo no reparta la foto en dos cachés.
    root = cache_root()
    with _state_lock:
        holder = _inflight.get(flight_key)
        if holder is None:
            holder = _Flight()
            _inflight[flight_key] = holder
            owner = True
        else:
            owner = False
    if not owner:
        if not holder.event.wait(SNAPSHOT_WAIT_SECONDS):
            raise TimeoutError("La actualización del tablero superó el tiempo de espera.")
        if holder.error is not None:
            raise holder.error
        if holder.value is None:
            raise TimeoutError("La actualización del tablero no devolvió datos.")
        return holder.value
    if track_status:
        _refresh_status_start(tier, league)
    try:
        value = load_core_snapshot(league, True) if kind == "core" else load_snapshot(league, True)
    except Exception as exc:
        holder.error = exc
        if track_status:
            _refresh_status_finish(ok=False, error=error_payload("refresh", exc).get("error"))
        raise
    else:
        saved_unix = time.time()
        clean = dict(value)
        clean["photo_saved_unix"] = saved_unix
        _store_snapshot(kind, league, True, clean, cache_dir=root)
        served = _stamp_photo(clean, saved_unix)
        holder.value = served
        if track_status:
            _refresh_status_finish(ok=True)
        return served
    finally:
        with _state_lock:
            if _inflight.get(flight_key) is holder:
                _inflight.pop(flight_key, None)
        holder.event.set()


def _liquidity_projection(document: dict[str, Any]) -> float | None:
    projected = projected_lineup_points(document)
    if projected is not None:
        return projected
    raw = document.get("expected_points")
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None


def liquidity_from(optimize: dict[str, Any] | None) -> dict[str, Any]:
    """Estado de tu caja para el aviso de jornada."""
    document = optimize if isinstance(optimize, dict) else {}
    reasons = [item for item in (document.get("void_reasons") or []) if isinstance(item, str)]
    cash = document.get("cash_eur") if isinstance(document.get("cash_eur"), int) else None
    void = bool(document.get("matchday_void"))
    known = document.get("cash_known") is True and cash is not None
    eligible = document.get("eligible_count") if isinstance(document.get("eligible_count"), int) else None
    if document.get("ok") is False:
        message = (document.get("error") or {}).get("message")
        status = "unknown"
        headline = "Caja sin confirmar"
        detail = str(message or "No hay plantilla propia para calcular el saldo.")
    elif void:
        status = "penalty_risk"
        headline = "Riesgo de penalización"
        sentences = [_VOID_COPY.get(reason, reason) for reason in reasons]
        if "empty_slot" in reasons and eligible is not None:
            sentences.append(f"Hay {eligible} jugadores disponibles para un once de 11.")
        detail = " ".join(sentences) or "La jornada completa puntúa 0."
    elif not known:
        status = "unconfirmed"
        headline = "Saldo no observado"
        detail = "La API no trajo el saldo. Confirma la caja antes de pujar."
    else:
        status = "safe"
        headline = "Caja segura para la jornada"
        formation = document.get("formation") if isinstance(document.get("formation"), str) else "el once"
        detail = f"Saldo en positivo y formación {formation} con 11 jugadores."
    return {
        "status": status,
        "headline": headline,
        "detail": detail,
        "cash_eur": cash,
        "cash_known": known,
        "cash_negative": isinstance(cash, int) and cash < 0,
        "matchday_void": void,
        "void_reasons": reasons,
        "eligible_count": eligible,
        "formation": document.get("formation") if isinstance(document.get("formation"), str) else None,
        "expected_points": _liquidity_projection(document),
        "manager_name": document.get("manager_name") if isinstance(document.get("manager_name"), str) else None,
    }


def shape_trends(board: dict[str, Any]) -> dict[str, Any]:
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    flip = board.get("flip") if isinstance(board.get("flip"), dict) else {}
    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    signings = flip.get("signings") if flip.get("ok") and isinstance(flip.get("signings"), list) else []
    listings = market.get("listings") if isinstance(market.get("listings"), list) else []
    flips = _enrich_flip_deltas(signings, trends, listings)
    intel = decisions_from_board(board)
    raw_decisions = intel.get("decisions") if isinstance(intel.get("decisions"), list) else []
    decisions = [_normalize_market_decision(row) for row in raw_decisions if isinstance(row, dict)]
    summary = intel.get("summary") if isinstance(intel.get("summary"), dict) else {}
    league_for_track = trends.get("league_id") if isinstance(trends.get("league_id"), str) else None
    try:
        persist_market_decisions(decisions, league_id=league_for_track)
    except Exception as exc:
        logger.debug("market decision snapshot skipped: %s", exc)
    calibration_report = _calibration_report(board)
    engine_confidence = (
        calibration_report.get("engine_confidence")
        if isinstance(calibration_report.get("engine_confidence"), dict)
        else _engine_confidence_snapshot(board)
    )
    return {
        "ok": trends.get("ok", False) is not False and bool(trends),
        "schema_version": trends.get("schema_version") or SCHEMA_VERSION,
        "command": "trends",
        "league_id": trends.get("league_id") or market.get("league_id"),
        "league_name": trends.get("league_name") or market.get("league_name"),
        "fetched_at": trends.get("fetched_at"),
        "dashboard_at": board.get("dashboard_at"),
        "stale": board.get("stale") is True,
        "partial": bool(trends.get("partial")),
        "catalog_count": trends.get("catalog_count"),
        "form_note": trends.get("form_note"),
        "sources": trends.get("sources") if isinstance(trends.get("sources"), dict) else {},
        "rising": trends.get("rising") if isinstance(trends.get("rising"), list) else [],
        "falling": trends.get("falling") if isinstance(trends.get("falling"), list) else [],
        "undervalued": trends.get("undervalued") if isinstance(trends.get("undervalued"), list) else [],
        "availability": trends.get("availability") if isinstance(trends.get("availability"), list) else [],
        "af_prediction_rising": trends.get("af_prediction_rising")
        if isinstance(trends.get("af_prediction_rising"), list)
        else [],
        "af_prediction_falling": trends.get("af_prediction_falling")
        if isinstance(trends.get("af_prediction_falling"), list)
        else [],
        "af_oracle_points": trends.get("af_oracle_points") if isinstance(trends.get("af_oracle_points"), list) else [],
        "af_oracle_chollos": trends.get("af_oracle_chollos")
        if isinstance(trends.get("af_oracle_chollos"), list)
        else [],
        "af_in_form": trends.get("af_in_form") if isinstance(trends.get("af_in_form"), list) else [],
        "own_prediction_rising": trends.get("own_prediction_rising")
        if isinstance(trends.get("own_prediction_rising"), list)
        else [],
        "own_prediction_falling": trends.get("own_prediction_falling")
        if isinstance(trends.get("own_prediction_falling"), list)
        else [],
        "flips": flips,
        "flip_count": len(flips),
        "cash_eur": flip.get("cash_eur") if isinstance(flip.get("cash_eur"), int) else None,
        "market_decisions": decisions,
        "jornada_board": intel.get("jornada_board") if isinstance(intel.get("jornada_board"), list) else [],
        "market_decision_summary": {
            "pujar": summary.get("pujar") if isinstance(summary.get("pujar"), int) else 0,
            "esperar": summary.get("esperar") if isinstance(summary.get("esperar"), int) else 0,
            "no": summary.get("no") if isinstance(summary.get("no"), int) else 0,
            "cash_eur": summary.get("cash_eur") if isinstance(summary.get("cash_eur"), int) else (
                flip.get("cash_eur") if isinstance(flip.get("cash_eur"), int) else None
            ),
            "count": summary.get("count") if isinstance(summary.get("count"), int) else len(decisions),
            "liga": summary.get("liga") if isinstance(summary.get("liga"), int) else 0,
            "rival": summary.get("rival") if isinstance(summary.get("rival"), int) else 0,
            "propio": summary.get("propio") if isinstance(summary.get("propio"), int) else 0,
            "league_war_count": summary.get("league_war_count") if isinstance(summary.get("league_war_count"), int) else 0,
            "league_priced_count": summary.get("league_priced_count") if isinstance(summary.get("league_priced_count"), int) else 0,
            "league_buy_count": summary.get("league_buy_count") if isinstance(summary.get("league_buy_count"), int) else 0,
            "league_median_premium": summary.get("league_median_premium")
            if isinstance(summary.get("league_median_premium"), (int, float))
            and not isinstance(summary.get("league_median_premium"), bool)
            else None,
            "league_bomb_count": summary.get("league_bomb_count") if isinstance(summary.get("league_bomb_count"), int) else 0,
            "markets_left": summary.get("markets_left") if isinstance(summary.get("markets_left"), int) else None,
            "day_budget_eur": summary.get("day_budget_eur") if isinstance(summary.get("day_budget_eur"), int) else None,
            "plan_spend_eur": summary.get("plan_spend_eur") if isinstance(summary.get("plan_spend_eur"), int) else None,
            "plan_cash_after_eur": summary.get("plan_cash_after_eur")
            if isinstance(summary.get("plan_cash_after_eur"), int)
            else None,
        },
        "market": {
            "count": market.get("count") if isinstance(market.get("count"), int) else len(listings),
            "fetched_at": market.get("fetched_at"),
            "listings": [_slim_listing(row) for row in listings if isinstance(row, dict)],
        },
        "catalog": _catalog_rows(board),
        "engine_confidence": engine_confidence,
        "calibration": _calibration_for_client(calibration_report),
        "error": trends.get("error") if trends.get("ok") is False else None,
    }


def shape_squads(board: dict[str, Any]) -> dict[str, Any]:
    document = board.get("squads") if isinstance(board.get("squads"), dict) else board
    squads = document.get("squads") if isinstance(document.get("squads"), list) else []
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    trend_index = _trend_index(trends)
    league_id = document.get("league_id") if isinstance(document.get("league_id"), str) else None
    snapshot_deltas = _snapshot_day_deltas(league_id)
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    ledger_rows = [row for row in needs.get("ledgers") or [] if isinstance(row, dict)]
    try:
        store = CashLedgerStore()
        stored = store.list_ledgers(league_id) if league_id else store.list_ledgers(None)
        if league_id and not stored:
            stored = [row for row in store.list_ledgers(None) if row.get("league_id") == league_id]
    except Exception:
        logger.debug("Sin libros persistidos para cartera", exc_info=True)
        stored = []
    ledger_rows = merge_ledgers(ledger_rows, stored)
    ledgers = ledger_index(ledger_rows)
    activity_meta = needs.get("activity") if isinstance(needs.get("activity"), dict) else {}
    activity_event_count = activity_meta.get("event_count") if isinstance(activity_meta.get("event_count"), int) else 0
    activity_ok = activity_meta.get("ok") is True
    rivals: list[dict[str, Any]] = []
    own: dict[str, Any] | None = None
    clauses: list[dict[str, Any]] = []
    roster_raw = [squad for squad in squads if isinstance(squad, dict)]
    names = player_name_index(roster_raw)
    portfolio_doc: dict[str, Any] | None = None
    for squad in roster_raw:
        view = _squad_view(squad, trend_index, snapshot_deltas)
        ledger = ledger_for_squad(squad, ledgers)
        if view["cash_eur"] is None and isinstance(ledger, dict) and isinstance(ledger.get("reconstructed_cash_eur"), int):
            view["cash_eur"] = ledger["reconstructed_cash_eur"]
            view["cash_is_ceiling"] = ledger.get("cash_is_ceiling") is True
        profile = team_activity_profile(ledger, names)
        if profile is not None:
            view["activity_profile"] = profile
        port = build_portfolio(view.get("players") or [], ledger, names)
        view["players"] = port.get("players") or view.get("players")
        view["portfolio"] = port.get("summary")
        if squad.get("is_self") is True:
            portfolio_doc = {
                "summary": port.get("summary"),
                "recent_events": port.get("recent_events"),
            }
            own = view
            continue
        rivals.append(view)
        clauses.extend(_clause_rows(squad))
    rivals.sort(key=_squad_sort)
    clauses.sort(key=_clause_sort)
    own_players = own.get("players") if isinstance(own, dict) else []
    if not isinstance(own_players, list):
        own_players = []
    own_ledger = ledger_for_squad(own, ledgers) if isinstance(own, dict) else None
    own_ledger_events = (
        len(own_ledger.get("events"))
        if isinstance(own_ledger, dict) and isinstance(own_ledger.get("events"), list)
        else 0
    )
    activity_feed = league_activity_feed(ledger_rows, roster_raw, names, limit=28)
    return {
        "ok": document.get("ok", True) is not False,
        "schema_version": document.get("schema_version") or SCHEMA_VERSION,
        "command": "squads",
        "league_id": document.get("league_id"),
        "league_name": document.get("league_name"),
        "fetched_at": document.get("fetched_at"),
        "dashboard_at": board.get("dashboard_at"),
        "stale": board.get("stale") is True,
        "partial": bool(document.get("partial")),
        "clause_lock_timezone": document.get("clause_lock_timezone"),
        "clause_lock_note": document.get("clause_lock_note"),
        "self": own,
        "rival_count": len(rivals),
        "rivals": rivals,
        "clauses": clauses,
        "portfolio": portfolio_doc,
        "portfolio_meta": {
            "activity_ok": activity_ok,
            "activity_event_count": activity_event_count,
            "ledger_event_count": own_ledger_events,
            "history_ready": activity_event_count > 0 and own_ledger_events > 0,
        },
        "activity_feed": activity_feed,
        "shield": [player for player in own_players if player.get("is_at_risk") is True],
        "sell": [player for player in own_players if player.get("sell_signal") is True],
        "error": document.get("error") if document.get("ok") is False else None,
    }


def clause_intel_from_board(board: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else None
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else None
    rivals = needs.get("rivals") if isinstance(needs, dict) and isinstance(needs.get("rivals"), list) else None
    if not rivals:
        rivals = rival_snapshots(squads, trends)
    document = build_clause_intel(squads, trends, optimize, rivals or [], now=current)
    if document.get("ok") is False:
        return document
    document = attach_clause_window(document, trends=trends, squads=squads, now=current)
    document["league_id"] = squads.get("league_id")
    document["league_name"] = squads.get("league_name")
    return document


def shape_clause_intel(board: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    close = document.get("clause_market_close") if isinstance(document.get("clause_market_close"), dict) else None
    offers = []
    for row in document.get("offers") or []:
        if not isinstance(row, dict):
            continue
        offers.append(
            {
                "decision": row.get("decision"),
                "player_id": row.get("player_id"),
                "name": row.get("name"),
                "nickname": row.get("nickname"),
                "position": row.get("position"),
                "club": row.get("club"),
                "image_url": row.get("image_url"),
                "team_id": row.get("team_id"),
                "manager_name": row.get("manager_name"),
                "buyout_clause_eur": row.get("buyout_clause_eur"),
                "cash_after_eur": row.get("cash_after_eur"),
                "objective": row.get("objective"),
                "points_delta": row.get("points_delta"),
                "enters_xi": row.get("enters_xi"),
                "window_open": row.get("window_open"),
                "requires_confirmation": row.get("requires_confirmation"),
                "clause_lock": row.get("clause_lock"),
            }
        )
    protect = []
    for row in document.get("protect") or []:
        if not isinstance(row, dict):
            continue
        protect.append(
            {
                "player_id": row.get("player_id"),
                "name": row.get("name"),
                "nickname": row.get("nickname"),
                "position": row.get("position"),
                "buyout_clause_eur": row.get("buyout_clause_eur"),
                "threat_count": row.get("threat_count"),
                "top_rival": row.get("top_rival"),
                "options": row.get("options"),
            }
        )
    return {
        "ok": document.get("ok", False) is not False,
        "schema_version": document.get("schema_version") or SCHEMA_VERSION,
        "command": "clause-intel",
        "league_id": document.get("league_id") or board.get("league_id"),
        "league_name": document.get("league_name"),
        "dashboard_at": board.get("dashboard_at"),
        "stale": board.get("stale") is True,
        "fetched_at": document.get("fetched_at"),
        "cash_eur": document.get("cash_eur"),
        "baseline_points": document.get("baseline_points"),
        "clause_window_open": document.get("clause_window_open"),
        "clause_market_close": close,
        "offers": offers,
        "protect": protect,
        "sends": False,
        "error": document.get("error") if document.get("ok") is False else None,
    }


def rival_intel_from_board(    squads: dict[str, Any] | None,
    ledgers: list[Any] | None,
    *,
    now: datetime | None = None,
    observed_on: str | date | None = None,
) -> dict[str, Any]:
    """Auditoría de caja rival desde la foto ya cargada, sin red.

    Reutiliza los libros contables de ``needs`` cuando están, porque traen el
    historial completo (incluido el cobro de cláusulas al vendedor) sin volver
    a paginar 40 páginas. ``observed_on`` es el día de la foto: el diff de
    cláusulas se fecha contra ella, no contra el reloj.
    """
    if not isinstance(squads, dict) or not squads:
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "command": "rival-intel",
            "error": {"code": "squads_missing", "message": "Sin plantillas no hay caja rival."},
        }
    activity = events_from_ledgers(ledgers)
    document = get_financial_intel(
        squads, activity, now=now, observed_on=observed_on
    )
    document["activity"]["source"] = activity.get("source")
    document["activity"]["from_ledgers"] = True
    return document


def shape_needs(board: dict[str, Any]) -> dict[str, Any]:
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    rivals = needs.get("rivals") if isinstance(needs.get("rivals"), list) else []
    alerts = needs.get("clause_alerts") if isinstance(needs.get("clause_alerts"), list) else []
    return {
        "ok": needs.get("ok", False) is not False and bool(needs),
        "schema_version": needs.get("schema_version") or SCHEMA_VERSION,
        "command": "needs",
        "league_id": needs.get("league_id"),
        "dashboard_at": board.get("dashboard_at"),
        "stale": board.get("stale") is True,
        "from_cache": needs.get("from_cache"),
        "activity": needs.get("activity") if isinstance(needs.get("activity"), dict) else None,
        "history": _slim_history(needs.get("history") if isinstance(needs.get("history"), dict) else None),
        "ledger_note": needs.get("ledger_note"),
        "rival_count": needs.get("rival_count") if isinstance(needs.get("rival_count"), int) else len(rivals),
        "rivals": [_slim_rival(rival) for rival in rivals if isinstance(rival, dict)],
        "clause_alerts": alerts,
        "alert_count": len(alerts),
        "liquidity": liquidity_from(board.get("optimize") if isinstance(board.get("optimize"), dict) else None),
        "error": needs.get("error") if needs.get("ok") is False else None,
    }


def _trend_index(trends: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed = index_trends(trends)
    for key in ("rising", "falling", "undervalued", "availability"):
        rows = trends.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            player_id = row.get("player_id")
            if isinstance(player_id, str) and player_id and player_id not in indexed:
                indexed[player_id] = row
    return indexed


def _enrich_flip_deltas(
    signings: list[Any],
    trends: dict[str, Any],
    listings: list[Any],
) -> list[dict[str, Any]]:
    """Rellena ``price_delta`` del flip con la subida oficial del catálogo o del listing."""
    catalog = _trend_index(trends)
    by_listing: dict[str, dict[str, Any]] = {}
    for row in listings:
        if not isinstance(row, dict):
            continue
        player_id = row.get("player_id")
        if isinstance(player_id, str) and player_id:
            by_listing[player_id] = row
    enriched: list[dict[str, Any]] = []
    for signing in signings:
        if not isinstance(signing, dict):
            continue
        row = dict(signing)
        player_id = row.get("player_id") if isinstance(row.get("player_id"), str) else ""
        trend = catalog.get(player_id) or {} if player_id else {}
        listing = by_listing.get(player_id) or {} if player_id else {}
        if _signed(row.get("price_delta")) is None and player_id:
            day_delta = official_price_delta(
                {
                    "market_value_change": listing.get("market_value_change")
                    if _signed(listing.get("market_value_change")) is not None
                    else trend.get("market_value_change"),
                    "price_delta": trend.get("price_delta"),
                    "market_value": trend.get("fantasy_price")
                    if _signed(trend.get("fantasy_price")) is not None
                    else listing.get("market_value"),
                    "fantasy_price": trend.get("fantasy_price"),
                    "sale_price": listing.get("sale_price")
                    if _signed(listing.get("sale_price")) is not None
                    else trend.get("sale_price"),
                }
            )
            if day_delta is not None:
                row["price_delta"] = day_delta
        if not isinstance(row.get("image_url"), str):
            image = trend.get("image_url") if isinstance(trend.get("image_url"), str) else None
            if image is None and isinstance(listing.get("image_url"), str):
                image = listing["image_url"]
            if image is not None:
                row["image_url"] = image
        enriched.append(row)
    return enriched


def _catalog_rows(board: dict[str, Any]) -> list[dict[str, Any]]:
    """Universo de la liga: dueño, movimiento y serie. Sin 3 días no hay previsión."""
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    players = trends.get("players") if isinstance(trends.get("players"), list) else []
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    owners: dict[str, str] = {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        kind = "propio" if squad.get("is_self") is True else "rival"
        for player in squad.get("players") or []:
            if isinstance(player, dict) and isinstance(player.get("player_id"), str):
                owners[player["player_id"]] = kind
    history: dict[str, list[dict[str, Any]]] = {}
    try:
        from toolbox.cache import PriceSnapshotStore

        history = PriceSnapshotStore().list_history(days=14)
    except Exception:
        logger.debug("Sin histórico de precios para el catálogo", exc_info=True)
    rows: list[dict[str, Any]] = []
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else None
        if not player_id:
            continue
        points = []
        for snap in history.get(player_id) or []:
            if not isinstance(snap, dict):
                continue
            value = snap.get("market_value")
            day = snap.get("day")
            if isinstance(day, str) and isinstance(value, int) and not isinstance(value, bool):
                points.append({"day": day, "market_value": value})
        forecast = _signed(player.get("own_predicted_delta")) if len(points) >= 3 else None
        confidence = player.get("matching_confidence")
        af_delta = None
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and float(confidence) >= 0.85:
            af_delta = _signed(player.get("af_price_delta"))
        market_value = player.get("market_value") if isinstance(player.get("market_value"), int) else None
        if market_value is None and isinstance(player.get("fantasy_price"), int):
            market_value = player.get("fantasy_price")
        rows.append(
            {
                "player_id": player_id,
                "name": player.get("name"),
                "nickname": player.get("nickname"),
                "position": player.get("position"),
                "club": player.get("club"),
                "image_url": player.get("image_url") if isinstance(player.get("image_url"), str) else None,
                "market_value": market_value,
                "owner": owners.get(player_id, "libre"),
                "price_delta": _signed(player.get("price_delta")),
                # Mismos tramos que la app oficial: 1, 2 y 3 días. Sin ellos la
                # UI no podía explicar por qué LaLiga marcaba 519.675 € y el
                # panel 257.864 € para el mismo jugador.
                "ff_price_delta_2": _signed(player.get("ff_price_delta_2")),
                "ff_price_delta_3": _signed(player.get("ff_price_delta_3")),
                "own_predicted_delta": forecast,
                "af_price_delta": af_delta,
                "price_points": points,
            }
        )
    rows.sort(key=lambda row: (row.get("owner") != "propio", row.get("owner") != "rival", str(row.get("name") or "")))
    return rows


def _catalog_price_history() -> dict[str, list[dict[str, Any]]]:
    """Histórico diario por jugador, desde el almacén local. Nunca sale a red."""
    try:
        from toolbox.cache import PriceSnapshotStore

        store = PriceSnapshotStore()
        try:
            return store.list_history(days=14)
        finally:
            store.close()
    except Exception:
        logger.debug("Sin histórico de precios para el arbitraje", exc_info=True)
        return {}


def _catalog_players() -> list[dict[str, Any]]:
    """Catálogo normalizado desde la copia de disco. Sin red, sin refresco."""
    from toolbox.normalize import normalize_catalog
    from toolbox.quant_valuation import cached_catalog

    rows = cached_catalog()
    return normalize_catalog(rows) if rows else []


def catalog_report(board: dict[str, Any]) -> dict[str, Any]:
    """Análisis cuantitativo del catálogo contra la foto guardada.

    La foto aporta las plantillas (quién está fichado) y el catálogo aporta la
    serie de jornadas y el valor. El histórico de precios añade la caída diaria
    que alimenta el arbitraje de lesiones. Todo es local: si falta una pieza el
    módulo lo dice (``known: false``) en lugar de inventar escasez.
    """
    from toolbox.catalog_intel import MarketQuantAnalyzer

    squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
    players = _catalog_players()
    analyzer = MarketQuantAnalyzer(
        players,
        squads=squads,
        price_history=_catalog_price_history(),
    )
    return analyzer.report()


def _signed(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _average(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number:
        return None
    return number


def _squad_view(
    squad: dict[str, Any],
    trend_index: dict[str, dict[str, Any]] | None = None,
    snapshot_deltas: dict[str, int] | None = None,
) -> dict[str, Any]:
    players = [player for player in squad.get("players") or [] if isinstance(player, dict)]
    locked = 0
    for player in players:
        lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
        if lock.get("is_locked") is True:
            locked += 1
    slim = [_slim_player(player, trend_index, snapshot_deltas) for player in players]
    totals = _squad_totals(slim)
    return {
        "team_id": squad.get("team_id"),
        "is_self": squad.get("is_self") is True,
        "manager_name": squad.get("manager_name"),
        "fantasy_team_name": squad.get("fantasy_team_name"),
        "rank": squad.get("rank") if isinstance(squad.get("rank"), int) else None,
        "points": squad.get("points") if isinstance(squad.get("points"), int) else None,
        "cash_eur": squad.get("cash") if isinstance(squad.get("cash"), int) else None,
        "player_count": len(players),
        "locked_clauses": locked,
        "error": squad.get("error"),
        **totals,
        "players": slim,
    }


def _squad_totals(players: list[dict[str, Any]]) -> dict[str, int | None]:
    """Valor de mercado agregado y suma del Δ oficial del día por plantilla."""
    market_total = 0
    delta_day = 0
    delta_players = 0
    for player in players:
        market_value = player.get("market_value")
        if isinstance(market_value, int) and not isinstance(market_value, bool):
            market_total += market_value
        delta = player.get("price_delta")
        if isinstance(delta, int) and not isinstance(delta, bool):
            delta_day += delta
            delta_players += 1
    return {
        "market_value_total": market_total if market_total > 0 else None,
        "price_delta_day": delta_day if delta_players > 0 else None,
        "price_delta_players": delta_players if delta_players > 0 else None,
    }


def _player_price_delta(player: dict[str, Any], trend: dict[str, Any] | None) -> int | None:
    merged: dict[str, Any] = dict(player)
    if isinstance(trend, dict):
        for key in (
            "ff_price_delta",
            "market_value_change",
            "price_delta",
            "market_value",
            "fantasy_price",
            "sale_price",
        ):
            value = trend.get(key)
            if value is not None:
                merged[key] = value
    return display_price_delta(merged)


def _player_p_titular(player: dict[str, Any], trend: dict[str, Any] | None) -> float | None:
    if isinstance(trend, dict):
        scraped = probability(trend.get("p_titular"))
        if scraped is not None:
            return scraped
    return probability(player.get("p_titular"))


def _slim_player(
    player: dict[str, Any],
    trend_index: dict[str, dict[str, Any]] | None = None,
    snapshot_deltas: dict[str, int] | None = None,
) -> dict[str, Any]:
    lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
    player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else ""
    trend = (trend_index or {}).get(player_id)
    market_value = player.get("market_value") if isinstance(player.get("market_value"), int) else None
    clause = player.get("buyout_clause") if isinstance(player.get("buyout_clause"), int) else None
    view = {
        "player_id": player.get("player_id"),
        "name": player.get("name"),
        "nickname": player.get("nickname"),
        "position": player.get("position"),
        "club": player.get("club"),
        "image_url": player.get("image_url") if isinstance(player.get("image_url"), str) else None,
        "market_value": market_value,
        "average_points": _average(player.get("average_points")),
        "buyout_clause": clause,
        "clause_multiple": clause_multiple(player),
        "is_shielded": player.get("is_shielded") if isinstance(player.get("is_shielded"), bool) else None,
        "clause_lock": _lock_view(lock),
        "is_at_risk": is_at_risk(player),
        "sell_signal": sell_signal(trend if isinstance(trend, dict) else None),
        "price_delta": _player_price_delta(player, trend if isinstance(trend, dict) else None),
        "p_titular": _player_p_titular(player, trend if isinstance(trend, dict) else None),
    }
    if isinstance(trend, dict):
        view["acceleration"] = _signed(trend.get("acceleration"))
        view["own_predicted_delta"] = _signed(trend.get("own_predicted_delta"))
        view["own_expected_points"] = _average(trend.get("own_expected_points"))
        confidence = trend.get("matching_confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and float(confidence) >= 0.85:
            view["af_price_delta"] = _signed(trend.get("af_price_delta"))
        else:
            view["af_price_delta"] = None
    if view.get("price_delta") is None and player_id and snapshot_deltas:
        snap_delta = snapshot_deltas.get(player_id)
        if isinstance(snap_delta, int) and not isinstance(snap_delta, bool):
            view["price_delta"] = snap_delta
    return view


def _clause_rows(squad: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in squad.get("players") or []:
        if not isinstance(player, dict):
            continue
        lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
        if lock.get("present") is not True and lock.get("is_locked") is not True:
            continue
        if player.get("is_shielded") is True:
            continue
        rule = exposed_clause_rule(player)
        if rule is None:
            continue
        view = _lock_view(lock)
        locked = view["is_locked"] is True
        rows.append(
            {
                "team_id": squad.get("team_id"),
                "manager_name": squad.get("manager_name"),
                "fantasy_team_name": squad.get("fantasy_team_name"),
                "player_id": player.get("player_id"),
                "name": player.get("name"),
                "nickname": player.get("nickname"),
                "position": player.get("position"),
                "club": player.get("club"),
                "image_url": player.get("image_url") if isinstance(player.get("image_url"), str) else None,
                "buyout_clause_eur": player.get("buyout_clause") if isinstance(player.get("buyout_clause"), int) else None,
                "market_value": player.get("market_value") if isinstance(player.get("market_value"), int) else None,
                "average_points": _average(player.get("average_points")),
                "clause_multiple": clause_multiple(player),
                "clause_rule": rule,
                "is_shielded": False,
                "is_locked": locked,
                "at_risk": locked,
                "clause_lock": view,
            }
        )
    return rows


def _lock_view(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": lock.get("present") is True,
        "is_locked": lock.get("is_locked") if isinstance(lock.get("is_locked"), bool) else None,
        "local_date": lock.get("local_date") if isinstance(lock.get("local_date"), str) else None,
        "local_time": lock.get("local_time") if isinstance(lock.get("local_time"), str) else None,
        "local_clock": lock.get("local_clock") if isinstance(lock.get("local_clock"), str) else None,
        "expires_at": lock.get("expires_at") if isinstance(lock.get("expires_at"), str) else None,
        "timezone": lock.get("timezone") if isinstance(lock.get("timezone"), str) else None,
    }


def _normalize_market_decision(row: dict[str, Any]) -> dict[str, Any]:
    """Contrato JSON de market-intel: incluye metadatos de subasta v2.0."""
    item = dict(row)
    knockouts = item.get("rival_knockout_targets")
    if not isinstance(knockouts, list):
        item["rival_knockout_targets"] = []
    else:
        item["rival_knockout_targets"] = [str(name) for name in knockouts if isinstance(name, str) and name.strip()]
    intent = item.get("bid_intent")
    if not isinstance(intent, str) or not intent.strip():
        legacy = item.get("intent")
        intent = legacy if isinstance(legacy, str) and legacy.strip() else None
    item["bid_intent"] = intent
    if isinstance(intent, str) and intent.strip():
        item["intent"] = intent
    for key in (
        "optimal_bid_eur",
        "intrinsic_valuation_eur",
        "expected_surplus_eur",
    ):
        value = item.get(key)
        item[key] = value if isinstance(value, int) and not isinstance(value, bool) else None
    win = item.get("win_probability")
    if isinstance(win, bool) or not isinstance(win, (int, float)):
        item["win_probability"] = None
    else:
        item["win_probability"] = round(float(win), 4)
    return item


def _slim_listing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row.get("player_id"),
        "name": row.get("name"),
        "nickname": row.get("nickname"),
        "position": row.get("position"),
        "club": row.get("club"),
        "image_url": row.get("image_url") if isinstance(row.get("image_url"), str) else None,
        "sale_price": row.get("sale_price") if isinstance(row.get("sale_price"), int) else None,
        "leading_bid": row.get("leading_bid") if isinstance(row.get("leading_bid"), int) else None,
        "market_value": row.get("market_value") if isinstance(row.get("market_value"), int) else None,
        "listing_expires_at": row.get("listing_expires_at"),
        "listing_expires_local_time": row.get("listing_expires_local_time"),
    }


def _slim_history(history: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(history, dict) or not history:
        return None
    median = history.get("median_premium")
    return {
        "buy_count": history.get("buy_count") if isinstance(history.get("buy_count"), int) else 0,
        "priced_count": history.get("priced_count") if isinstance(history.get("priced_count"), int) else 0,
        "war_count": history.get("war_count") if isinstance(history.get("war_count"), int) else 0,
        "bomb_count": history.get("bomb_count") if isinstance(history.get("bomb_count"), int) else 0,
        "median_premium": median
        if isinstance(median, (int, float)) and not isinstance(median, bool)
        else None,
        "initial_source": history.get("initial_source") if isinstance(history.get("initial_source"), str) else None,
        "initial_budget_eur": history.get("initial_budget_eur")
        if isinstance(history.get("initial_budget_eur"), int)
        else None,
    }


def _slim_rival(rival: dict[str, Any]) -> dict[str, Any]:
    ledger = rival.get("ledger") if isinstance(rival.get("ledger"), dict) else None
    slim_ledger = None
    if ledger is not None:
        slim_ledger = {
            "observed_cash_eur": ledger.get("observed_cash_eur"),
            "reconstructed_cash_eur": ledger.get("reconstructed_cash_eur"),
            "balanced": ledger.get("balanced"),
            "gap_eur": ledger.get("gap_eur"),
            "initial_budget_eur": ledger.get("initial_budget_eur"),
            "cash_is_ceiling": ledger.get("cash_is_ceiling") is True,
            "premiums_eur": ledger.get("premiums_eur") if isinstance(ledger.get("premiums_eur"), int) else None,
            "purchases_eur": ledger.get("purchases_eur") if isinstance(ledger.get("purchases_eur"), int) else None,
            "clauses_eur": ledger.get("clauses_eur") if isinstance(ledger.get("clauses_eur"), int) else None,
            "sales_eur": ledger.get("sales_eur") if isinstance(ledger.get("sales_eur"), int) else None,
        }
    body = dict(rival)
    body["ledger"] = slim_ledger
    return body


def _squad_sort(squad: dict[str, Any]) -> tuple[bool, int, str]:
    rank = squad.get("rank")
    return (not isinstance(rank, int), rank if isinstance(rank, int) else 9999, str(squad.get("manager_name") or "").lower())


def _clause_sort(row: dict[str, Any]) -> tuple[int, int, str, str, str]:
    lock = row.get("clause_lock") if isinstance(row.get("clause_lock"), dict) else {}
    missing = 0 if lock.get("local_date") and lock.get("local_time") else 1
    return (
        0 if row.get("at_risk") else 1,
        missing,
        str(lock.get("local_date") or "9999-99-99"),
        str(lock.get("local_time") or "99:99"),
        str(row.get("nickname") or row.get("name") or ""),
    )


def error_payload(command: str, exc: Exception) -> dict[str, Any]:
    status: int | None = None
    details: dict[str, Any] | None = None
    if isinstance(exc, AuthError):
        code = exc.code
    elif isinstance(exc, FantasyHttpError):
        code = exc.code
        status = exc.status
        details = exc.details or None
    elif isinstance(exc, TimeoutError):
        code = "timeout"
    else:
        code = "unexpected"
    error: dict[str, Any] = {"code": code, "message": str(exc), "status": status}
    if details:
        error["details"] = details
    return {"ok": False, "schema_version": SCHEMA_VERSION, "command": command, "error": error}


def error_response(command: str, exc: Exception) -> JSONResponse:
    if isinstance(exc, (AuthError, FantasyHttpError, TimeoutError)):
        logger.warning("%s: %s", command, exc)
    else:
        logger.exception("Fallo en %s", command)
    payload = error_payload(command, exc)
    code = str(payload["error"]["code"])
    http_status = _STATUS_FOR_CODE.get(code)
    if http_status is None:
        if isinstance(exc, TimeoutError):
            http_status = 504
        elif isinstance(exc, FantasyHttpError):
            http_status = 502
        else:
            http_status = 500
    return JSONResponse(status_code=http_status, content=payload)


def _league(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _board_health_extra(board: dict[str, Any]) -> dict[str, Any]:
    """Mercado y plantillas de LALIGA no viven en ``trends.sources``.

    Sin esta traducción, dos fuentes críticas salían siempre ``no_leida`` y el
    panel avisaba de ceguera total con el tablero entero leído. Aquí solo se
    traduce el estado real del bloque; no se inventa una lectura.

    Ya no hay TTL: la foto vale hasta que el usuario pulse Actualizar. Por eso
    se informa la edad real (``photo_age_seconds``) y no una caducidad fingida.
    """
    extra: dict[str, Any] = {}
    age = _photo_age(board)
    fresh = board.get("is_stale") is not True

    market = board.get("market") if isinstance(board.get("market"), dict) else None
    if market is not None:
        extra["laliga_market"] = {
            "ok": market.get("ok") is not False,
            "count": market.get("count") if isinstance(market.get("count"), int) else None,
            "from_cache": True,
            "photo_age_seconds": age,
            # Sin TTL no hay caducidad que anunciar: se mantiene la clave para
            # que la UI vieja no pinte «caducada» en falso.
            "expires_in_seconds": None,
            "fresh_until_update": fresh,
        }

    squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
    if squads is not None:
        extra["laliga_squads"] = {
            "ok": squads.get("ok") is not False,
            "count": squads.get("count") if isinstance(squads.get("count"), int) else None,
            "from_cache": True,
            "photo_age_seconds": age,
            "expires_in_seconds": None,
            "fresh_until_update": fresh,
        }
    return extra


def _board(
    command: str,
    league: str | None,
    *,
    tier: str = "full",
) -> dict[str, Any] | JSONResponse:
    """Foto guardada para un GET. La lectura no descarga: no acepta ``fresh``.

    Ni siquiera existe la opción de pedir red por esta vía. Si algún día se
    añade un parámetro aquí, es que la lectura ha vuelto a tener dos caminos.
    """
    try:
        # Cinturón y tirantes: aunque un helper olvidado intente descargar, el
        # veto por hilo (que ahora también heredan los pools) lo corta en
        # ``net.py`` antes de gastar una petición.
        with no_network():
            return snapshot(_league(league), tier=tier)
    except Exception as exc:
        return error_response(command, exc)


def _refresh(command: str, league: str | None, *, tier: str = "full", track_status: bool = True) -> dict[str, Any] | JSONResponse:
    """Descarga real. Único camino con red; solo lo usa ``POST /api/plan/refresh``."""
    try:
        return refresh_board(_league(league), tier=tier, track_status=track_status)
    except Exception as exc:
        return error_response(command, exc)


def _photo_fields(board: dict[str, Any]) -> dict[str, Any]:
    """Metadatos de la foto para cualquier respuesta del tablero.

    ``last_updated`` dice de cuándo es el dato; ``photo_age_seconds`` cuánto
    hace; ``is_stale`` solo avisa de que ya pasó el umbral de frescura. Nada de
    esto dispara red: es información para que el usuario decida actualizar.
    """
    fields: dict[str, Any] = {
        "last_updated": board.get("last_updated"),
        "photo_age_seconds": board.get("photo_age_seconds"),
        "is_stale": board.get("is_stale") is True,
        "stale": board.get("stale") is True,
        # La edad de arriba mide cuánto hace que se **guardó** la foto. Con un
        # refresco core el panel se sella al escribir (~1 s) aunque LALIGA se
        # leyera dos minutos antes: «Actualizado 12:07 · hace 3 s» junto a un
        # mercado de las 12:05. Esto es cuánto hace que se **descargó** el dato.
        "data_age_seconds": _data_age(board),
    }
    return fields


def _data_age(board: dict[str, Any]) -> float | None:
    """Segundos desde el instante de descarga más reciente de la foto."""
    newest: float | None = None
    for block in ("market", "squads", "trends"):
        document = board.get(block)
        if not isinstance(document, dict):
            continue
        fetched = document.get("fetched_at")
        if not isinstance(fetched, str) or not fetched.strip():
            continue
        try:
            stamp = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        newest = max(newest, stamp.timestamp()) if newest is not None else stamp.timestamp()
    if newest is None:
        return None
    return round(max(0.0, time.time() - newest), 1)


def _read_only(view: Any) -> Any:
    """Envuelve un endpoint GET: dentro, cualquier salida a red está prohibida.

    El veto va por hilo y cubre todo el handler, incluidos los enriquecimientos
    que corren después de leer la foto (once, flip, ventana de cláusulas). Si
    alguno necesita una fuente que no está en disco, ``net.py`` sirve la copia
    antigua o marca la fuente caída; nunca descarga.
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with no_network():
            return view(*args, **kwargs)

    return wrapper


def _cors_origins() -> list[str]:
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    extra = os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
    if extra:
        origins.append(extra)
    for item in os.getenv("CORS_ORIGINS", "").split(","):
        cleaned = item.strip().rstrip("/")
        if cleaned and cleaned not in origins:
            origins.append(cleaned)
    return origins


app = FastAPI(
    title="LALIGA Fantasy",
    version="0.1.0",
    description="Tablero local de solo lectura sobre la caja de herramientas.",
)
# Orígenes explícitos + regex para previews de Vercel y URLs temporales de
# Cloudflare Tunnel (*.trycloudflare.com). FRONTEND_ORIGIN / CORS_ORIGINS
# cubren el dominio de producción en Vercel.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=(
        r"https://([a-z0-9-]+\.)*(vercel\.app|trycloudflare\.com)"
        r"|https?://(localhost|127\.0\.0\.1)(:\d+)?"
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.post("/api/auth/browser")
def api_auth_browser() -> Any:
    """Abre la ventana de login en esta máquina y guarda los tokens en ``.env``."""
    try:
        payload = login_with_browser()
    except Exception as exc:
        return error_response("auth", exc)
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def _day_price_delta(player: dict[str, Any]) -> int | None:
    """Subida o bajada del día. No usa valor menos precio de venta."""
    for key in ("market_value_change", "price_delta"):
        value = player.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _stamp_squad_price_delta(body: dict[str, Any], board: dict[str, Any]) -> None:
    """La variación de tus jugadores viaja con el once, no con el mercado.

    Se copian también ``measured_price_delta`` y ``price_delta_estimated``: el
    catálogo distingue el Δ medido entre dos capturas propias de LaLiga del
    estimado de FútbolFantasy, y sin propagarlos el campo enseñaba el estimado
    con el prefijo ``≈`` aunque el dato medido existiera. El once y el mercado
    deben contar la misma historia.
    """
    index: dict[str, int] = {}
    measured: dict[str, int] = {}
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    trend_index = _trend_index(trends)
    for player in trends.get("players") or []:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            continue
        trend = trend_index.get(player_id)
        delta = _player_price_delta(player, trend if isinstance(trend, dict) else None)
        if delta is not None:
            index[player_id] = delta
        own_delta = player.get("measured_price_delta")
        if isinstance(own_delta, int) and not isinstance(own_delta, bool):
            measured[player_id] = own_delta
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    own = own_squad(squads)
    if isinstance(own, dict):
        for player in own.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = player.get("player_id")
            if not isinstance(player_id, str) or not player_id:
                continue
            trend = trend_index.get(player_id)
            delta = _player_price_delta(player, trend if isinstance(trend, dict) else None)
            if delta is not None:
                index[player_id] = delta
    for key in ("xi", "benched", "excluded"):
        rows = body.get(key)
        if not isinstance(rows, list):
            continue
        for player in rows:
            if not isinstance(player, dict):
                continue
            player_id = player.get("player_id")
            if isinstance(player_id, str) and player_id in index:
                player["price_delta"] = index[player_id]
            if isinstance(player_id, str) and player_id in measured:
                player["measured_price_delta"] = measured[player_id]
                player["measured_price_delta_source"] = "capturas_propias"
                player["price_delta_estimated"] = index.get(player_id)
                player["price_delta_is_estimate"] = index.get(player_id) is not None


@app.get("/api/optimize")
@_read_only
def api_optimize(
    league: str | None = Query(default=None),
) -> Any:
    board = _board("optimize", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    board = _enrich_board_optimize(board, _league(league), fresh=False)
    optimize = board.get("optimize")
    if not isinstance(optimize, dict):
        # La foto puede no traer once (refresco a medias, liga sin plantilla
        # propia o un ``core`` escrito antes de calcularlo). Un KeyError aquí
        # devolvía 500 y el panel se quedaba con el once guardado en el
        # navegador: parecía «no ha cargado» mostrando datos de días atrás.
        # Sin once se dice, no se inventa ni se tumba el endpoint.
        logger.warning("Foto sin bloque optimize (liga=%s): no hay once que servir.", league)
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "schema_version": SCHEMA_VERSION,
                "command": "optimize",
                "league_id": _board_league_id(board, league),
                "error": {
                    "code": "optimize_missing",
                    "message": "La foto guardada no trae once. Pulsa Actualizar para calcularlo.",
                },
            },
        )
    body = dict(optimize)
    _stamp_squad_price_delta(body, board)
    body["dashboard_at"] = board.get("dashboard_at")
    body.update(_photo_fields(board))
    return body


@app.get("/api/trends")
@_read_only
def api_trends(
    league: str | None = Query(default=None),
) -> Any:
    board = _board("trends", league, tier="full")
    if isinstance(board, JSONResponse):
        return board
    payload = shape_trends(board)
    payload.update(_photo_fields(board))
    return payload


@app.get("/api/squads")
@_read_only
def api_squads(
    league: str | None = Query(default=None),
) -> Any:
    board = _board("squads", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    board = _overlay_core_history(board, _league(league))
    board = _enrich_board_trends(board, _league(league))
    payload = shape_squads(board)
    payload.update(_photo_fields(board))
    return payload


@app.get("/api/league-race")
@_read_only
def api_league_race(
    league: str | None = Query(default=None),
) -> Any:
    """Brecha, postura y proyección de rivales. Solo lectura."""
    board = _board("league-race", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    board = _enrich_board_optimize(board, _league(league), fresh=False)
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else None
    market = board.get("market") if isinstance(board.get("market"), dict) else None
    document = build_league_race(squads, trends, optimize, market=market)
    document["fetched_at"] = board.get("dashboard_at")
    document.update(_photo_fields(board))
    return document


@app.get("/api/data-health")
@_read_only
def api_data_health(
    league: str | None = Query(default=None),
) -> Any:
    """Salud por fuente y por campo. Solo lee caché local, sin red."""
    board = _board("data-health", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    board = _enrich_board_trends(board, _league(league))
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    sources = trends.get("sources") if isinstance(trends.get("sources"), dict) else {}
    document = build_field_health(
        sources,
        fetched_at=board.get("dashboard_at") if isinstance(board.get("dashboard_at"), str) else None,
        extra=_board_health_extra(board),
    )
    document.update(_photo_fields(board))
    document["partial"] = bool(trends.get("partial"))
    return document


@app.get("/api/market/quant-radar")
@_read_only
def api_quant_radar(
    league: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
) -> Any:
    """Value Investing puro: coste por punto, momentum global y blank rate.

    Solo lee la foto y el catálogo ya cacheados. Ninguna ruta de este handler
    puede salir a la red: el veto de ``_read_only`` lo corta en ``net.py``.
    """
    board = _board("quant-radar", league, tier="full")
    if isinstance(board, JSONResponse):
        return board
    board = _enrich_board_trends(board, _league(league))
    document = build_quant_radar(board, limit=limit)
    document.update(_photo_fields(board))
    return document


@app.get("/api/market-maker")
@_read_only
def api_market_maker(
    league: str | None = Query(default=None),
) -> Any:
    """Ofertas del Computer sobre mi plantilla: percentil, EV de mañana y veredicto.

    Solo lee la foto de plantillas y el log local de ofertas. La oferta del
    sistema es un punto de referencia (±10 % en el motor, ±5 % en la regla
    rápida de ``scripts/eval_ofertas_maquina.py``); el jugador puede editar la
    oferta real que recibe y volver a evaluarla desde la app.
    """
    board = _board("squads", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    own = squads.get("self") if isinstance(squads.get("self"), dict) else None
    players = own.get("players") if isinstance(own, dict) and isinstance(own.get("players"), list) else []
    document = get_market_recommendations(players)
    document.update(_photo_fields(board))
    document["league_id"] = document.get("league_id") or _board_league_id(board, league)
    return document


@app.get("/api/api-usage")
@_read_only
def api_api_usage() -> Any:
    """Ritmo real de llamadas salientes. Lee contadores en RAM: no toca la red."""
    document = api_meter.build_usage_report()
    document["schema_version"] = SCHEMA_VERSION
    return document


NETWORK_LOG_LIMIT = 200


def _read_network_log(path: Path, limit: int = NETWORK_LOG_LIMIT) -> tuple[list[dict[str, Any]], int]:
    """Últimas ``limit`` líneas válidas del JSONL, de la más nueva a la más vieja.

    Devuelve ``(filas, total_lineas)``. Si el fichero no existe todavía
    devuelve lista vacía: un reinicio limpio no es un error.
    """
    if not path.is_file():
        return [], 0
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            # 600 B por línea es de sobra para una entrada con URL; se lee el
            # final del fichero en lugar de cargarlo entero.
            chunk = min(size, max(64 * 1024, limit * 600))
            handle.seek(size - chunk)
            raw = handle.read()
    except OSError:
        return [], 0
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if chunk < size and lines:
        # La primera línea puede venir cortada por el seek.
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows, len(lines)


@app.get("/api/diagnostics/network")
@_read_only
def api_diagnostics_network() -> Any:
    """Bitácora persistente de llamadas HTTP reales. Sin red y sin tablero."""
    path = network_log_path()
    rows, scanned = _read_network_log(path)
    # Las filas se piden de la más reciente a la más antigua, sin fiarse del
    # orden de escritura (varios hilos apuntan a la vez).
    rows.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
    errores: dict[str, dict[str, Any]] = {}
    for row in rows:
        status = row.get("status")
        if not isinstance(status, int) or status < 400:
            continue
        source = str(row.get("fuente") or "otros")
        bucket = errores.setdefault(source, {"fuente": source, "total": 0, "por_status": {}, "ultimo": None})
        bucket["total"] += 1
        key = str(status)
        bucket["por_status"][key] = bucket["por_status"].get(key, 0) + 1
        if bucket["ultimo"] is None:
            bucket["ultimo"] = row.get("timestamp")
    return {
        "ok": True,
        "command": "network-diagnostics",
        "schema_version": SCHEMA_VERSION,
        "file": str(path),
        "file_exists": path.is_file(),
        "limit": NETWORK_LOG_LIMIT,
        "scanned": len(rows),
        "total_count": scanned,
        "count": len(rows),
        "calls": rows,
        "errors": sorted(errores.values(), key=lambda bucket: (-bucket["total"], bucket["fuente"])),
        "notes": [
            "Solo llamadas que salieron a la red: los aciertos de caché no se apuntan.",
            "Cada reintento es una línea aparte: es lo que pasó de verdad.",
            "La URL va sin query string: sirve para localizar la fuente, no lleva credenciales.",
        ],
    }


@app.get("/api/needs")
@_read_only
def api_needs(
    league: str | None = Query(default=None),
) -> Any:
    board = _board("needs", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    board = _enrich_board_optimize(board, _league(league), fresh=False)
    payload = shape_needs(board)
    payload.update(_photo_fields(board))
    return payload


@app.get("/api/clause-intel")
@_read_only
def api_clause_intel(
    league: str | None = Query(default=None),
) -> Any:
    board = _board("clause-intel", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    board = _enrich_board_trends(board, _league(league))
    board = _enrich_board_optimize(board, _league(league), fresh=False)
    document = clause_intel_from_board(board)
    payload = shape_clause_intel(board, document)
    payload.update(_photo_fields(board))
    return payload


@app.get("/api/clause-board")
@_read_only
def api_clause_board(
    league: str | None = Query(default=None),
) -> Any:
    """Todas las cláusulas rivales, con la subida de cada jugador ya fechada.

    ``/api/squads`` solo publica las que cumplen la regla de oro. Esta vista no
    filtra: una fila por jugador con cláusula, hora exacta de desbloqueo y el
    diff contra el último día guardado. No descarga: cruza la foto con el
    histórico de cláusulas que ya está en disco.
    """
    board = _board("squads", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    document = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    ledgers = needs.get("ledgers") if isinstance(needs.get("ledgers"), list) else []
    payload = build_clause_board(document, photo_day=_photo_day(board), ledgers=ledgers)
    payload["league_id"] = _board_league_id(board, league)
    payload["league_name"] = document.get("league_name") or board.get("league_name")
    payload.update(_photo_fields(board))
    return payload


@app.get("/api/rival-intel")
@_read_only
def api_rival_intel(
    league: str | None = Query(default=None),
) -> Any:
    """Caja rival con cota superior y gasto oculto. No descarga: usa la foto."""
    board = _board("needs", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    ledgers = needs.get("ledgers") if isinstance(needs.get("ledgers"), list) else []
    payload = rival_intel_from_board(squads, ledgers, observed_on=_photo_day(board))
    payload.update(_photo_fields(board))
    return payload


@app.get("/api/catalog/free-agents")
@_read_only
def api_catalog_free_agents(
    league: str | None = Query(default=None),
) -> Any:
    """Agentes libres y radar de inflación. Solo lectura de la foto y del caché."""
    board = _board("catalog-free-agents", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    try:
        report = catalog_report(board)
    except Exception as exc:
        return error_response("catalog-free-agents", exc)
    payload = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "catalog-free-agents",
        "league_id": _board_league_id(board, league),
        "league_name": board.get("league_name"),
        "count": len(report.get("free_agents") or []),
        "inflation": report.get("inflation"),
        "free_agents": report.get("free_agents") or [],
        "top_free": report.get("top_free") or [],
        "counts": report.get("counts"),
    }
    payload.update(_photo_fields(board))
    return payload


@app.get("/api/catalog/arbitrage")
@_read_only
def api_catalog_arbitrage(
    league: str | None = Query(default=None),
) -> Any:
    """Arbitraje de lesiones y perfil de volatilidad del catálogo."""
    board = _board("catalog-arbitrage", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    try:
        report = catalog_report(board)
    except Exception as exc:
        return error_response("catalog-arbitrage", exc)
    payload = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "catalog-arbitrage",
        "league_id": _board_league_id(board, league),
        "league_name": board.get("league_name"),
        "count": len(report.get("distressed") or []),
        "distressed": report.get("distressed") or [],
        "refuge": report.get("refuge") or [],
        "risk": report.get("risk") or [],
        "counts": report.get("counts"),
    }
    payload.update(_photo_fields(board))
    return payload


def _note_path() -> Path:
    return project_root() / "context" / "expert_notes.md"


def _memory_path() -> Path:
    return project_root() / "context" / "MEMORY.md"


@app.get("/api/calibration")
@_read_only
def api_calibration(
    league: str | None = Query(default=None),
) -> Any:
    board = _board("trends", league, tier="core")
    if isinstance(board, JSONResponse):
        team_id = None
        dashboard_at = None
    else:
        team_id = _own_team_id(board)
        dashboard_at = board.get("dashboard_at")
    if isinstance(board, dict):
        report = _calibration_report(board)
    else:
        resolved_league = _league(league)
        try:
            report = build_calibration_report(league_id=resolved_league, own_team_id=team_id)
            report["ok"] = True
        except Exception as exc:
            logger.exception("calibration report failed")
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "schema_version": SCHEMA_VERSION,
                    "command": "calibration",
                    "error": {"code": "calibration_failed", "message": str(exc)},
                },
            )
    payload = _calibration_for_client(report)
    payload["dashboard_at"] = dashboard_at
    payload["league_id"] = payload.get("league_id") or _board_league_id(board if isinstance(board, dict) else None, league)
    if isinstance(board, dict):
        payload.update(_photo_fields(board))
    return payload


@app.get("/api/plan")
@_read_only
def api_plan(
    league: str | None = Query(default=None),
) -> Any:
    """Foto del plan. **Cero red**: si no hay foto, pide pulsar Actualizar.

    Abrir la pestaña seis horas después devuelve la misma foto al instante.
    ``last_updated``/``photo_age_seconds`` dicen de cuándo es. No acepta
    ``?fresh=``: pedir red por aquí no es una opción, ni siquiera ignorada.
    """
    board = _board("plan", league, tier="core")
    if isinstance(board, JSONResponse):
        return board
    return _plan_document(board)


def _plan_document(board: dict[str, Any]) -> dict[str, Any]:
    note = read_expert_note(_note_path())
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    experts = experts_from_pages({"mentions": [], "lineups": [], "sources": {}}, trends, note_text=note)
    document = plan_from_documents(
        board.get("market") if isinstance(board.get("market"), dict) else {},
        board.get("squads") if isinstance(board.get("squads"), dict) else {},
        trends,
        board.get("optimize") if isinstance(board.get("optimize"), dict) else None,
        board.get("flip") if isinstance(board.get("flip"), dict) else None,
        board.get("needs") if isinstance(board.get("needs"), dict) else None,
        experts=experts,
        memory_path=_memory_path(),
    )
    document["dashboard_at"] = board.get("dashboard_at")
    document.update(_photo_fields(board))
    document["mode"] = mode_from_squads(board.get("squads") if isinstance(board.get("squads"), dict) else {})
    document["expert_note"] = note
    plan_decisions = document.get("decisions")
    if isinstance(plan_decisions, list):
        document["decisions"] = [_normalize_market_decision(row) for row in plan_decisions if isinstance(row, dict)]
    return document


# ---------------------------------------------------------------------------
# Gatillo remoto (VPS / móvil)
# ---------------------------------------------------------------------------
# El dashboard local lee la foto y nunca sale a la red. El refresco real vive
# en el VPS, que es el único proceso con ``LALIGA_ENV=production``. Este
# endpoint es la puerta: una petición corta desde el móvil (o un cron) pone en
# marcha la pasada humana y responde al instante.
#
# Por qué un hilo y no ``BackgroundTasks`` de FastAPI: las tareas de Starlette
# corren **después** de enviar la respuesta, pero dentro del mismo ciclo de
# request; un refresco de una hora dejaría la conexión del móvil abierta hasta
# que el cliente cortara. Un ``threading.Thread`` daemon desacopla el trabajo
# del ciclo HTTP: el 202 sale en milisegundos y la pasada sigue viva aunque el
# móvil se vaya a dormir.
REMOTE_TOKEN_HEADER = "X-Remote-Token"
# ¿Este proceso nació en producción? Se congela al importar, antes de que
# ninguna petición pueda abrir el ``production_window``. Es el dato correcto
# para decidir si el proceso está publicado en Internet (VPS) o si solo es un
# panel local al que alguien le dejó ``LALIGA_ENV=production`` en la consola.
STARTUP_PRODUCTION = is_production()


def startup_production() -> bool:
    """``True`` solo si el proceso arrancó en producción. No cambia en caliente."""
    return STARTUP_PRODUCTION


# Nombres admitidos para el secreto del gatillo. ``REMOTE_TRIGGER_TOKEN`` es el
# canónico (el que documenta el despliegue en el VPS); ``REMOTE_REFRESH_TOKEN``
# se mantiene como alias para no invalidar los ``.env`` y los tests ya escritos.
# Si están los dos, vale cualquiera de los dos: un despliegue no se queda fuera
# por haber renombrado la variable a medias.
REMOTE_TOKEN_ENV_VARS = ("REMOTE_TRIGGER_TOKEN", "REMOTE_REFRESH_TOKEN")
REMOTE_MIN_MINUTES = 1.0
REMOTE_MAX_MINUTES = 240.0
# Peticiones esperadas por tipo de foto. Es solo la base para repartir el
# presupuesto; no promete un número exacto.
_REMOTE_EXPECTED_REQUESTS = {"core": 25, "full": HUMAN_REQUESTS_PER_REFRESH}

_remote_lock = threading.Lock()
_remote_job: dict[str, Any] | None = None


def _remote_token() -> str:
    """Contraseña simple del gatillo. Sin token configurado, el endpoint no existe."""
    for name in REMOTE_TOKEN_ENV_VARS:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _remote_default_minutes() -> float:
    raw = os.getenv("REMOTE_REFRESH_DEFAULT_MINUTES", "").strip()
    try:
        return _clamp_minutes(float(raw))
    except (TypeError, ValueError):
        return 60.0


def _clamp_minutes(value: float) -> float:
    return max(REMOTE_MIN_MINUTES, min(REMOTE_MAX_MINUTES, float(value)))


def _remote_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "command": "remote-refresh",
            "error": {"code": code, "message": message},
        },
    )


def _remote_authorized(token: str | None) -> bool:
    """Compara en tiempo constante. Un token vacío en el servidor nunca autoriza."""
    expected = _remote_token()
    if not expected or not token:
        return False
    return hmac.compare_digest(token.strip(), expected)


def _kill_process_from_worker() -> None:
    """Cierra el proceso entero cuando el kill switch salta en un hilo.

    ``net.trip_kill_switch`` sale con ``sys.exit(1)``, pero un ``SystemExit``
    dentro de un hilo secundario solo termina ese hilo: uvicorn seguiría vivo
    sirviendo la foto vieja con la IP ya marcada, que es exactamente lo que el
    contrato del kill switch prohíbe. Aquí se manda SIGTERM al propio proceso
    para que el runtime (Docker ``restart: unless-stopped``) lo levante de
    nuevo, o se sale de inmediato si la señal no está disponible.
    """
    logger.critical("Kill switch disparado en el hilo de refresco: se cierra el proceso.")
    try:
        import signal

        os.kill(os.getpid(), signal.SIGTERM)
        # Margen para que uvicorn atienda la señal antes de forzar la salida.
        time.sleep(5.0)
    except Exception:  # noqa: BLE001 — cualquier fallo acaba en la salida dura
        logger.exception("No se pudo enviar SIGTERM; salida inmediata.")
    os._exit(1)


def _remote_worker(
    job_id: str,
    league: str | None,
    tier: str,
    target_minutes: float,
    expected_requests: int,
) -> None:
    """Corre la pasada real en un hilo. Nunca comparte el ciclo HTTP."""
    global _remote_job
    try:
        # El presupuesto remoto alarga la cadencia si sobra tiempo; nunca la
        # comprime por debajo del suelo anti-429 de ``HumanPacer``.
        HUMAN_PACER.stretch_to(target_minutes * 60.0, expected_requests=expected_requests)
        try:
            board = refresh_board(league, tier=tier)
        finally:
            HUMAN_PACER.reset_stretch()
        with _remote_lock:
            _remote_job = {
                **(_remote_job or {}),
                "job_id": job_id,
                "status": "done",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "ok": True,
                "last_updated": board.get("last_updated"),
                "photo_age_seconds": board.get("photo_age_seconds"),
                "error": None,
            }
        logger.info("Refresco remoto %s terminado (tier=%s).", job_id, tier)
    except SystemExit:
        with _remote_lock:
            _remote_job = {
                **(_remote_job or {}),
                "job_id": job_id,
                "status": "kill_switch",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "ok": False,
                "error": {"code": "kill_switch", "message": "Kill switch disparado."},
            }
        _kill_process_from_worker()
    except BaseException as exc:  # noqa: BLE001 — el hilo no puede morir en silencio
        payload = error_payload("remote-refresh", exc)
        with _remote_lock:
            _remote_job = {
                **(_remote_job or {}),
                "job_id": job_id,
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "ok": False,
                "error": payload.get("error"),
            }
        logger.exception("El refresco remoto %s falló.", job_id)


@app.post("/api/remote/refresh", status_code=202)
def api_remote_refresh(
    payload: dict[str, Any] = Body(default=None),
    x_remote_token: str | None = Header(default=None, alias=REMOTE_TOKEN_HEADER),
) -> Any:
    """Lanza el orquestador en segundo plano y responde 202 en el acto.

    Cuerpo: ``{"target_minutes": 60}``. ``target_minutes`` es el presupuesto de
    la pasada completa: si sobra respecto a la cadencia de fábrica, las esperas
    se estiran proporcionalmente; si falta, la cadencia no se acelera (el suelo
    de 12–25 s existe para no despertar al WAF) y el refresco tardará lo suyo.

    Opcionales: ``league`` (id o slug) y ``tier`` (``full`` por defecto, ``core``
    para la foto rápida sin scrapers externos).

    Autenticación: header ``X-Remote-Token``. El secreto se lee de
    ``REMOTE_TRIGGER_TOKEN`` (o de su alias ``REMOTE_REFRESH_TOKEN``). Sin
    ninguno de los dos configurado el endpoint queda desactivado (503), nunca
    abierto.
    """
    global _remote_job

    if not _remote_token():
        return _remote_error(
            503,
            "remote_disabled",
            "REMOTE_REFRESH_TOKEN no está configurado: el gatillo remoto está apagado.",
        )
    if not _remote_authorized(x_remote_token):
        logger.warning("Gatillo remoto rechazado: token inválido o ausente.")
        return _remote_error(401, "unauthorized", "Token remoto inválido.")

    # Un kill switch disparado deja el proceso vivo solo hasta que uvicorn
    # atienda el SIGTERM (o hasta que el runtime lo reinicie). Cualquier pasada
    # nueva volvería a golpear una IP ya marcada: se corta aquí, no en net.py.
    tripped = kill_switch_state()
    if tripped.get("tripped"):
        return _remote_error(
            423,
            "kill_switch",
            "El kill switch de LaLiga está disparado; no se lanza ningún refresco.",
        )

    body = payload if isinstance(payload, dict) else {}

    raw_minutes = body.get("target_minutes", None)
    if raw_minutes is None:
        target_minutes = _remote_default_minutes()
    else:
        try:
            if isinstance(raw_minutes, bool):
                raise ValueError("booleano")
            target_minutes = _clamp_minutes(float(raw_minutes))
        except (TypeError, ValueError):
            return _remote_error(
                400,
                "invalid_target_minutes",
                "target_minutes tiene que ser un número de minutos (1–240).",
            )

    tier = body.get("tier") if isinstance(body.get("tier"), str) else "full"
    tier = tier.strip().lower()
    if tier not in _REMOTE_EXPECTED_REQUESTS:
        return _remote_error(400, "invalid_tier", "tier tiene que ser 'full' o 'core'.")

    league_value = body.get("league")
    league = _league(league_value) if isinstance(league_value, str) else None

    if not is_production():
        # Sin red real la pasada moriría en el primer GET con `offline_miss`.
        # Mejor un 409 explícito que un 202 y un trabajo condenado.
        return _remote_error(
            409,
            "air_gapped",
            "El proceso está en air-gap (LALIGA_ENV != production): no puede refrescar.",
        )

    with _remote_lock:
        running = _remote_job if _remote_job and _remote_job.get("status") == "running" else None
        if running is not None:
            # Idempotente a propósito: el móvil puede reintentar sin miedo. No
            # se enciende una segunda pasada ni se paga otra vez el presupuesto.
            return JSONResponse(
                status_code=202,
                content={
                    "ok": True,
                    "schema_version": SCHEMA_VERSION,
                    "command": "remote-refresh",
                    "accepted": True,
                    "status": "already_running",
                    "job": running,
                },
            )
        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        expected_requests = _REMOTE_EXPECTED_REQUESTS[tier]
        _remote_job = {
            "job_id": job_id,
            "status": "running",
            "target_minutes": target_minutes,
            "expected_requests": expected_requests,
            "tier": tier,
            "league": league,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
        }
        thread = threading.Thread(
            target=_remote_worker,
            args=(job_id, league, tier, target_minutes, expected_requests),
            name=f"remote-refresh-{job_id}",
            # Daemon: un reinicio del contenedor no espera una hora a que acabe.
            daemon=True,
        )
        thread.start()
        stretch = pace_stretch_for(target_minutes * 60.0, expected_requests=expected_requests)
        job = dict(_remote_job)

    logger.info(
        "Refresco remoto %s aceptado (tier=%s, %.0f min, liga=%s).",
        job_id,
        tier,
        target_minutes,
        league or "única",
    )
    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "command": "remote-refresh",
            "accepted": True,
            "status": "started",
            # ``message`` y ``target_minutes`` en la raíz para que el cliente
            # móvil pueda confirmar el disparo sin bucear en ``job``.
            "message": "extracción iniciada",
            "target_minutes": target_minutes,
            "job": {**job, "pace_stretch": round(stretch, 3)},
            "poll": "/api/remote/refresh",
        },
    )


# ---------------------------------------------------------------------------
# Salto local del air-gap: ``POST /api/local/force-refresh``
# ---------------------------------------------------------------------------
# El dashboard de casa corre en air-gap (``LALIGA_ENV`` sin definir) y su
# botón Actualizar solo reordena la foto de disco. Para bajar datos nuevos hay
# que abrir la puerta a mano. Este endpoint es esa puerta, con tres reglas:
#
# 1. **Solo desde esta máquina.** El air-gap protege la cuenta de LaLiga; un
#    endpoint que lo salta no puede quedar expuesto en la LAN ni detrás de un
#    túnel. Se exige que el cliente sea loopback, sin excepciones y sin token
#    que lo pueda abrir desde fuera.
# 2. **Ventana temporal, no permanente.** ``LALIGA_ENV=production`` se inyecta
#    justo antes de descargar y se retira en el ``finally``. Al volver de la
#    función el proceso está otra vez sellado, haya ido bien o mal.
# 3. **Sin reentrada.** Dos clics no pueden encender dos pasadas: el refresco
#    tarda media hora y duplicarlo es justo el patrón que el kill switch evita.
#
# La restauración es del *valor anterior*, no un ``pop`` a ciegas: si el
# proceso arrancó ya en producción (VPS), borrar la variable lo dejaría en
# development al terminar, que es el error contrario y más peligroso.
LOCAL_FORCE_REFRESH_PATH = "/api/local/force-refresh"
LOCAL_FORCE_COMMAND = "local-force-refresh"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
# Cabeceras que solo existen cuando hay un túnel delante. Un proxy reescribe
# ``CF-Connecting-IP`` con la IP real del cliente; uvicorn, mientras tanto, ve
# ``127.0.0.1`` porque el proxy es local. Sin este veto, publicar el 8000 con
# Cloudflare convertiría el salto del air-gap en un botón abierto a Internet.
_TUNNEL_HEADERS = ("cf-connecting-ip", "cf-ray", "x-real-ip", "x-vercel-id", "forwarded")
_force_refresh_lock = threading.Lock()
_force_refresh_running = False


def _loopback_address(value: str) -> bool:
    """``True`` para ``127.x``, ``::1`` y sus formas ``::ffff:``."""
    candidate = value.strip().strip("[]").lower()
    if candidate.startswith("::ffff:"):
        candidate = candidate[len("::ffff:") :]
    if candidate in _LOOPBACK_HOSTS or candidate == "::":
        return True
    if candidate.startswith("127."):
        return True
    # ``host:port`` en la forma que usa ``Forwarded``.
    if candidate.rsplit(":", 1)[0] in {"127.0.0.1", "::1", "localhost"}:
        return True
    return False


def loopback_client(request: Request | None) -> bool:
    """``True`` solo si la petición nació en esta máquina, no en un proxy.

    Se acepta ``X-Forwarded-For`` únicamente si **todas** sus saltos son
    loopback: el proxy de Next del panel React llega por ahí (Next rellena la
    cabecera con ``::1``). Un túnel añade su IP pública al final de la cadena,
    así que la misma comprobación lo rechaza.

    ``TestClient`` se identifica como ``testclient``: es ASGI en proceso, no
    abre un socket, así que la suite puede ejercitar el endpoint.
    """
    if request is None:
        return False
    headers = getattr(request, "headers", None) or {}
    if any(headers.get(name) for name in _TUNNEL_HEADERS):
        return False
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        hops = [hop for hop in str(forwarded).split(",") if hop.strip()]
        if not hops or not all(_loopback_address(hop) for hop in hops):
            return False
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if not isinstance(host, str):
        return False
    return _loopback_address(host)


def _force_refresh_error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "command": LOCAL_FORCE_COMMAND,
            "error": error,
        },
    )


def _reset_force_refresh() -> None:
    """Suelta el candado de reentrada. Solo pruebas y diagnóstico."""
    global _force_refresh_running
    with _force_refresh_lock:
        _force_refresh_running = False


@contextlib.contextmanager
def production_window() -> Iterator[None]:
    """Abre ``LALIGA_ENV=production`` y **siempre** restaura el valor anterior.

    ``net.py`` lee el entorno en cada llamada (``environment()`` no cachea la
    variable de la shell), así que basta con tocar ``os.environ`` para que los
    clientes que se construyan dentro del bloque vean producción y los de
    después vuelvan a estar sellados.

    ``FANTASY_OFFLINE=1`` no se toca: es un interruptor más duro y explícito
    del usuario. Si está puesto, la pasada seguirá sin red y así se informa en
    la respuesta, en lugar de mentir con un «actualizado».
    """
    previous_marker = object()
    previous = os.environ.get(LALIGA_ENV_VAR, previous_marker)
    opened_here = not is_production()
    os.environ[LALIGA_ENV_VAR] = PRODUCTION_ENV
    try:
        yield
    finally:
        if previous is previous_marker:
            os.environ.pop(LALIGA_ENV_VAR, None)
        else:
            os.environ[LALIGA_ENV_VAR] = str(previous)
        # Solo si la sesión la construyó esta ventana. En un proceso que ya era
        # producción (VPS) cerrarla mataría la sesión que otro hilo está usando.
        if opened_here:
            close_official_session()


def force_refresh_document(league: str | None) -> dict[str, Any]:
    """Pasada real con la puerta abierta. Fuera del bloque, el aire vuelve."""
    with production_window():
        board = refresh_board(league, tier="full")
        document = _plan_document(board)
        document["refresh"] = {"ok": True, "core": True, "full": True, "error": None}
        return document


@app.post(LOCAL_FORCE_REFRESH_PATH)
def api_local_force_refresh(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
) -> Any:
    """Salta el air-gap durante una sola pasada y lo vuelve a cerrar.

    Pensado para el botón visual del panel local (Tauri/React) y para el
    ``Actualizar_Fantasy.bat``. Responde con el plan nuevo, igual que
    ``POST /api/plan/refresh``, pero sin exigir haber arrancado el backend en
    producción.

    Cuerpo opcional: ``{"league": "018668579"}``.

    Respuestas:

    * ``403 local_only``: la petición no viene de loopback.
    * ``409 already_running``: ya hay un salto en curso.
    * ``423 kill_switch``: el kill switch está disparado; no se reintenta.
    * ``503 offline_forced``: ``FANTASY_OFFLINE=1``; el modo avión manda.
    * ``200``: plan nuevo. ``environment`` confirma que la puerta se cerró.
    """
    if not loopback_client(request):
        logger.warning("Salto de air-gap rechazado: la petición no es local.")
        return _force_refresh_error(
            403,
            "local_only",
            "El salto del air-gap solo se permite desde esta máquina.",
        )

    tripped = kill_switch_state()
    if tripped.get("tripped"):
        return _force_refresh_error(
            423,
            "kill_switch",
            "El kill switch de LaLiga está disparado; no se lanza ningún refresco.",
            details=tripped,
        )

    if offline_mode():
        # ``FANTASY_OFFLINE=1`` es el interruptor duro del usuario: abrir
        # LALIGA_ENV no lo salta, y fingir un refresco sería peor que negarlo.
        return _force_refresh_error(
            503,
            "offline_forced",
            "FANTASY_OFFLINE=1 está activo: el modo avión no se salta.",
        )

    global _force_refresh_running
    with _force_refresh_lock:
        if _force_refresh_running:
            return _force_refresh_error(
                409,
                "already_running",
                "Ya hay un refresco en curso; espera a que termine.",
            )
        _force_refresh_running = True

    body = payload if isinstance(payload, dict) else {}
    league_value = body.get("league")
    league = _league(league_value) if isinstance(league_value, str) else None

    try:
        before = environment()
        logger.info("Salto de air-gap solicitado desde loopback (liga=%s).", league or "única")
        try:
            document = force_refresh_document(league)
        except SystemExit:
            # El kill switch sale con ``SystemExit`` dentro de ``net.py``. Aquí
            # se deja el marcador visible y se devuelve 423 en vez de matar el
            # proceso del panel: es la diferencia entre «hoy no hay datos» y
            # «se cae el dashboard de casa a mitad de clic».
            #
            # Desviación deliberada del contrato del kill switch (que sí manda
            # SIGTERM desde ``_remote_worker``): la propiedad que importa es
            # que **no se reintente**, y eso lo garantiza el marcador, que
            # persiste en ``.cache/kill_switch.json`` y hace que la siguiente
            # llamada —y cualquier refresco remoto— responda 423 sin tocar la
            # red. ``production_window`` ya restauró el entorno en su propio
            # ``finally`` antes de llegar aquí.
            #
            # ``SystemExit`` no es ``Exception``: ``refresh_board`` no lo marca,
            # así que el latido quedaría «running» para siempre sin esta línea.
            close_official_session()
            marker = kill_switch_state()
            _refresh_status_finish(
                ok=False,
                error={"code": "kill_switch", "message": marker.get("reason")},
            )
            logger.critical("Kill switch disparado durante el salto local del air-gap.")
            return _force_refresh_error(
                423,
                "kill_switch",
                "LaLiga devolvió una señal de bloqueo; no se reintenta.",
                details=marker,
            )
        except Exception as exc:  # noqa: BLE001 — la foto anterior sigue válida
            # ``refresh_board`` ya cerró el latido con su error; aquí solo se
            # traduce la excepción a una respuesta HTTP.
            logger.exception("El salto local del air-gap falló")
            return error_response(LOCAL_FORCE_COMMAND, exc)

        document["forced"] = True
        document["endpoint"] = LOCAL_FORCE_REFRESH_PATH
        # ``force_refresh_document`` ya salió de su ``production_window``, así
        # que este ``environment()`` es la prueba de que el escudo volvió a
        # subir. Se publica el valor de antes y el de ahora para que el panel
        # pueda afirmarlo sin adivinar.
        document["environment"] = environment()
        document["environment_before"] = before
        document["air_gap_restored"] = environment() == before
        return document
    finally:
        with _force_refresh_lock:
            _force_refresh_running = False


@app.get("/api/remote/refresh")
def api_remote_status(
    x_remote_token: str | None = Header(default=None, alias=REMOTE_TOKEN_HEADER),
) -> Any:
    """Estado del último trabajo remoto. El móvil lo consulta en vez de esperar."""
    if not _remote_token():
        return _remote_error(503, "remote_disabled", "REMOTE_REFRESH_TOKEN no está configurado.")
    if not _remote_authorized(x_remote_token):
        return _remote_error(401, "unauthorized", "Token remoto inválido.")
    with _remote_lock:
        job = dict(_remote_job) if _remote_job else None
    tripped = kill_switch_state()
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "remote-refresh",
        "environment": "production" if is_production() else "development",
        "kill_switch": tripped if tripped.get("tripped") else None,
        "job": job,
    }


# ---------------------------------------------------------------------------
# Modo actualización: el ÚNICO endpoint que descarga
# ---------------------------------------------------------------------------
@app.post("/api/plan/refresh")
def api_plan_refresh(
    league: str | None = Query(default=None),
    x_remote_token: str | None = Header(default=None, alias=REMOTE_TOKEN_HEADER),
) -> Any:
    """Baja todo, sobrescribe la caché y devuelve la foto nueva.

    Aquí y solo aquí se llama a LALIGA y a los scrapers (``fresh=True`` hacia
    ``net.py``). El GET de la portada nunca descarga.

    Orden: primero la foto rápida (mercado, plantillas, once, caja) y después la
    completa (tendencias y scrapers). Si la completa falla, se devuelve la rápida
    ya guardada: el usuario ve datos nuevos y el error de la parte lenta.

    El token remoto solo se exige al proceso de producción de verdad: el que
    publica el puerto en Internet (VPS con ``LALIGA_ENV=production`` en el
    entorno al arrancar). En local no pide nada.

    Ojo: **no** vale ``is_production()``. ``Actualizar_Fantasy.bat`` arranca el
    refresco con una ventana temporal de producción, pero el backend del panel
    puede estar corriendo con esa misma variable en su entorno; con la
    comprobación anterior el botón «Actualizar» se comía un ``401`` sin token
    y el panel se quedaba con la foto vieja. El air-gap ya lo respeta el
    ``production_window`` de dentro: sin él, la pasada no sale a la red.
    """
    if startup_production() and not _remote_authorized(x_remote_token):
        return _remote_error(401, "unauthorized", "Token remoto inválido.")
    # Un solo latido para las dos pasadas: el panel no debe ver «terminado»
    # entre la foto rápida y la completa, porque los scrapers aún no empezaron.
    _refresh_status_start("full", _league(league))
    try:
        with production_window():
            return _plan_refresh_download(league)
    except SystemExit:
        # El kill switch de ``net.py`` sale con ``SystemExit``: un 401/403/429
        # de LaLiga mata el proceso. Sin esta rama, el ``SystemExit`` escapaba
        # del handler y se llevaba por delante uvicorn, así que el panel moría
        # en vez de decir «bloqueado, no se reintenta».
        close_official_session()
        marker = kill_switch_state()
        _refresh_status_finish(
            ok=False,
            error={"code": "kill_switch", "message": marker.get("reason")},
        )
        logger.critical("Kill switch disparado durante el refresco manual.")
        return _remote_error(
            423,
            "kill_switch",
            "LaLiga devolvió una señal de bloqueo; no se reintenta.",
        )


def _plan_refresh_download(league: str | None) -> Any:
    """Las dos pasadas (rápida y completa) con la ventana de producción abierta.

    Vive aparte porque **tiene que** ejecutarse dentro de ``production_window``:
    el proceso del panel nace en air-gap (``LALIGA_ENV=development``) y sin la
    ventana ``net.py`` resuelve todo contra el disco. Era el fallo del botón
    Actualizar: respondía 200 con ``calls: 0`` y ``cache_hits: 122``, sirviendo
    la foto de ayer con la fecha de hoy. ``GET /api/plan`` no descarga nunca;
    la única puerta es este POST y, por tanto, la ventana se abre aquí.
    """
    core = _refresh("plan", league, tier="core", track_status=False)
    if isinstance(core, JSONResponse):
        _refresh_status_finish(ok=False, error=None)
        return core
    core_document = _plan_document(core)

    def _full_failed(error: Any) -> Any:
        """La foto rápida ya está guardada: se sirve con el aviso del fallo."""
        document = dict(core_document)
        document["refresh"] = {"ok": False, "core": True, "full": False, "error": error}
        return document

    _refresh_status_phase("scrapers", "Foto completa: scrapers")
    try:
        full = refresh_board(_league(league), tier="full", track_status=False)
    except Exception as exc:  # noqa: BLE001 — la foto rápida ya está guardada
        logger.exception("La foto completa falló tras la rápida")
        payload = error_payload("plan-refresh", exc).get("error")
        _refresh_status_finish(ok=False, error=payload)
        return _full_failed(payload)
    document = _plan_document(full)
    document["refresh"] = {"ok": True, "core": True, "full": True, "error": None}
    _refresh_status_finish(ok=True)
    return document


@app.get("/api/refresh-status")
def api_refresh_status() -> Any:
    """¿Sigue viva la descarga? ¿Cuántas llamadas lleva y en cuál está?

    Es RAM y no toca la red, así que el panel puede consultarlo cada pocos
    segundos mientras dura el POST sin gastar una sola petición a las fuentes.
    Existe porque una pasada completa tarda media hora con la cadencia humana:
    sin este latido, «Actualizando…» y «colgado» se ven igual.
    """
    return refresh_status_snapshot()


@app.post("/api/expert-note")
def api_expert_note(payload: dict[str, Any] = Body(default=None)) -> Any:
    body = payload if isinstance(payload, dict) else {}
    text = body.get("text") if isinstance(body.get("text"), str) else ""
    stored = write_expert_note(_note_path(), text)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "command": "expert-note", "chars": len(stored)}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

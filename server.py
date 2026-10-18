"""Tablero local de LALIGA Fantasy.

Sirve la interfaz de ``static/index.html`` y reutiliza la caja de herramientas.
El servidor solo lee: no envía pujas ni cláusulas.

    python run_dashboard.py
    uvicorn server:app --reload --port 8000

Abre http://127.0.0.1:8000
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from toolbox import project_root
from toolbox.analyzer import (
    clause_multiple,
    exposed_clause_rule,
    index_trends,
    is_at_risk,
    optimize_from_documents,
    own_squad,
    sell_signal,
)
from toolbox.auth import AuthError, login_with_browser
from toolbox.bidding import flip_from_documents, load_activity, needs_from_documents
from toolbox.cache import ResponseCache
from toolbox.net import FantasyHttpError, LaligaClient
from toolbox.normalize import SCHEMA_VERSION
from toolbox.scrapers import build_trends

logger = logging.getLogger("fantasy.dashboard")

STATIC_DIR = project_root() / "static"
SNAPSHOT_TTL_SECONDS = 30.0
SNAPSHOT_WAIT_SECONDS = 180.0

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
}


class _Flight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: dict[str, Any] | None = None
        self.error: BaseException | None = None


_state_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_inflight: dict[str, _Flight] = {}


def clear_snapshot_cache() -> None:
    """Vacía la foto en memoria. Lo usan las pruebas."""
    with _state_lock:
        _cache.clear()
        _inflight.clear()


def load_snapshot(league: str | None, fresh: bool) -> dict[str, Any]:
    """Una pasada de mercado, plantillas, tendencias, once, flips y caja."""
    with LaligaClient() as client:
        market = client.market_document(league, fresh=fresh)
        squads = client.squads_document(league, fresh=fresh)
        trends = build_trends(league=league, fresh=fresh, laliga=client)
        store = ResponseCache()
        try:
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
            activity = load_activity(client, league_id, fresh=fresh)
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
    return {
        "dashboard_at": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "squads": squads,
        "trends": trends,
        "optimize": optimized,
        "flip": flipped,
        "needs": needs,
    }


def snapshot(league: str | None, fresh: bool) -> dict[str, Any]:
    """Comparte una sola lectura entre las cuatro peticiones del tablero."""
    key = f"{'1' if fresh else '0'}:{(league or '').strip()}"
    with _state_lock:
        if not fresh:
            cached = _cache.get(key)
            if cached is not None and (time.monotonic() - cached[0]) < SNAPSHOT_TTL_SECONDS:
                return cached[1]
        holder = _inflight.get(key)
        if holder is None:
            holder = _Flight()
            _inflight[key] = holder
            owner = True
        else:
            owner = False
    if not owner:
        if not holder.event.wait(SNAPSHOT_WAIT_SECONDS):
            raise TimeoutError("La carga del tablero superó el tiempo de espera.")
        if holder.error is not None:
            raise holder.error
        if holder.value is None:
            raise TimeoutError("La carga del tablero no devolvió datos.")
        return holder.value
    try:
        value = load_snapshot(league, fresh)
    except Exception as exc:
        holder.error = exc
        raise
    else:
        holder.value = value
        if not fresh:
            with _state_lock:
                _cache[key] = (time.monotonic(), value)
        return value
    finally:
        with _state_lock:
            if _inflight.get(key) is holder:
                _inflight.pop(key, None)
        holder.event.set()


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
        "expected_points": document.get("expected_points") if isinstance(document.get("expected_points"), (int, float)) else None,
        "manager_name": document.get("manager_name") if isinstance(document.get("manager_name"), str) else None,
    }


def shape_trends(board: dict[str, Any]) -> dict[str, Any]:
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    flip = board.get("flip") if isinstance(board.get("flip"), dict) else {}
    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    signings = flip.get("signings") if flip.get("ok") and isinstance(flip.get("signings"), list) else []
    listings = market.get("listings") if isinstance(market.get("listings"), list) else []
    return {
        "ok": trends.get("ok", False) is not False and bool(trends),
        "schema_version": trends.get("schema_version") or SCHEMA_VERSION,
        "command": "trends",
        "league_id": trends.get("league_id") or market.get("league_id"),
        "league_name": trends.get("league_name") or market.get("league_name"),
        "fetched_at": trends.get("fetched_at"),
        "dashboard_at": board.get("dashboard_at"),
        "partial": bool(trends.get("partial")),
        "catalog_count": trends.get("catalog_count"),
        "form_note": trends.get("form_note"),
        "sources": trends.get("sources") if isinstance(trends.get("sources"), dict) else {},
        "rising": trends.get("rising") if isinstance(trends.get("rising"), list) else [],
        "falling": trends.get("falling") if isinstance(trends.get("falling"), list) else [],
        "undervalued": trends.get("undervalued") if isinstance(trends.get("undervalued"), list) else [],
        "availability": trends.get("availability") if isinstance(trends.get("availability"), list) else [],
        "flips": signings,
        "flip_count": len(signings),
        "cash_eur": flip.get("cash_eur") if isinstance(flip.get("cash_eur"), int) else None,
        "market": {
            "count": market.get("count") if isinstance(market.get("count"), int) else len(listings),
            "fetched_at": market.get("fetched_at"),
            "listings": [_slim_listing(row) for row in listings if isinstance(row, dict)],
        },
        "error": trends.get("error") if trends.get("ok") is False else None,
    }


def shape_squads(board: dict[str, Any]) -> dict[str, Any]:
    document = board.get("squads") if isinstance(board.get("squads"), dict) else board
    squads = document.get("squads") if isinstance(document.get("squads"), list) else []
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    trend_index = _trend_index(trends)
    rivals: list[dict[str, Any]] = []
    own: dict[str, Any] | None = None
    clauses: list[dict[str, Any]] = []
    for squad in squads:
        if not isinstance(squad, dict):
            continue
        view = _squad_view(squad, trend_index if squad.get("is_self") is True else None)
        if squad.get("is_self") is True:
            own = view
            continue
        rivals.append(view)
        clauses.extend(_clause_rows(squad))
    rivals.sort(key=_squad_sort)
    clauses.sort(key=_clause_sort)
    own_players = own.get("players") if isinstance(own, dict) else []
    if not isinstance(own_players, list):
        own_players = []
    return {
        "ok": document.get("ok", True) is not False,
        "schema_version": document.get("schema_version") or SCHEMA_VERSION,
        "command": "squads",
        "league_id": document.get("league_id"),
        "league_name": document.get("league_name"),
        "fetched_at": document.get("fetched_at"),
        "dashboard_at": board.get("dashboard_at"),
        "partial": bool(document.get("partial")),
        "clause_lock_timezone": document.get("clause_lock_timezone"),
        "clause_lock_note": document.get("clause_lock_note"),
        "self": own,
        "rival_count": len(rivals),
        "rivals": rivals,
        "clauses": clauses,
        "shield": [player for player in own_players if player.get("is_at_risk") is True],
        "sell": [player for player in own_players if player.get("sell_signal") is True],
        "error": document.get("error") if document.get("ok") is False else None,
    }


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
        "from_cache": needs.get("from_cache"),
        "activity": needs.get("activity") if isinstance(needs.get("activity"), dict) else None,
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


def _squad_view(squad: dict[str, Any], trend_index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    players = [player for player in squad.get("players") or [] if isinstance(player, dict)]
    locked = 0
    for player in players:
        lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
        if lock.get("is_locked") is True:
            locked += 1
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
        "players": [_slim_player(player, trend_index) for player in players],
    }


def _slim_player(player: dict[str, Any], trend_index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
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
        "market_value": market_value,
        "average_points": _average(player.get("average_points")),
        "buyout_clause": clause,
        "clause_multiple": clause_multiple(player),
        "is_shielded": player.get("is_shielded") if isinstance(player.get("is_shielded"), bool) else None,
        "clause_lock": _lock_view(lock),
        "is_at_risk": is_at_risk(player),
        "sell_signal": sell_signal(trend),
    }
    if isinstance(trend, dict):
        view["acceleration"] = _signed(trend.get("acceleration"))
        view["price_delta"] = _signed(trend.get("price_delta"))
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


def _slim_listing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row.get("player_id"),
        "name": row.get("name"),
        "nickname": row.get("nickname"),
        "position": row.get("position"),
        "club": row.get("club"),
        "sale_price": row.get("sale_price") if isinstance(row.get("sale_price"), int) else None,
        "leading_bid": row.get("leading_bid") if isinstance(row.get("leading_bid"), int) else None,
        "market_value": row.get("market_value") if isinstance(row.get("market_value"), int) else None,
        "listing_expires_at": row.get("listing_expires_at"),
        "listing_expires_local_time": row.get("listing_expires_local_time"),
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


def _board(command: str, league: str | None, fresh: bool) -> dict[str, Any] | JSONResponse:
    try:
        return snapshot(_league(league), fresh)
    except Exception as exc:
        return error_response(command, exc)


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


@app.get("/api/optimize")
def api_optimize(
    league: str | None = Query(default=None),
    fresh: bool = Query(default=False),
) -> Any:
    board = _board("optimize", league, fresh)
    if isinstance(board, JSONResponse):
        return board
    body = dict(board["optimize"])
    body["dashboard_at"] = board.get("dashboard_at")
    return body


@app.get("/api/trends")
def api_trends(
    league: str | None = Query(default=None),
    fresh: bool = Query(default=False),
) -> Any:
    board = _board("trends", league, fresh)
    if isinstance(board, JSONResponse):
        return board
    return shape_trends(board)


@app.get("/api/squads")
def api_squads(
    league: str | None = Query(default=None),
    fresh: bool = Query(default=False),
) -> Any:
    board = _board("squads", league, fresh)
    if isinstance(board, JSONResponse):
        return board
    return shape_squads(board)


@app.get("/api/needs")
def api_needs(
    league: str | None = Query(default=None),
    fresh: bool = Query(default=False),
) -> Any:
    board = _board("needs", league, fresh)
    if isinstance(board, JSONResponse):
        return board
    return shape_needs(board)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

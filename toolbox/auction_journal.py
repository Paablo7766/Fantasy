"""Diario de subastas en Supabase.

Cada refresco de verdad guarda la lista completa del mercado de ese cierre y,
cuando la actividad ya pasa de la hora de cierre, el resultado: comprador e
importe, o sin comprador. Si había puja propia, queda el importe y si ganó o
perdió.

No escribe en ``.cache``. Sin Supabase no hace nada y no tumba la caja.
Si las tablas de ``scripts/init_supabase.sql`` aún no están creadas, el mismo
diario queda en ``dashboard_snapshots`` (clave ``auction:journal``) y se pasa
a las tablas el día en que existan.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from toolbox.league_history import madrid_day

logger = logging.getLogger("fantasy.auction_journal")

TABLE_BOARD = "market_board"
TABLE_RESULTS = "auction_results"
# Una subasta abierta se resuelve en el refresco siguiente. Más atrás de esto
# no se relee el tablero entero en cada Actualizar.
LOOKBACK_DAYS = 40

_client: Any = None
_client_lock = threading.Lock()
_warned: set[str] = set()


def _warn_once(what: str, exc: BaseException) -> None:
    if what in _warned:
        logger.debug("%s", what, exc_info=True)
        return
    _warned.add(what)
    logger.warning("%s: %s (¿está aplicado scripts/init_supabase.sql?)", what, exc)


def _enabled() -> bool:
    from toolbox import snapshot_remote

    return snapshot_remote.enabled()


def _get_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            from toolbox import cache as cache_module

            _client = cache_module.create_client(
                os.environ["SUPABASE_URL"].strip(),
                os.environ["SUPABASE_KEY"].strip(),
            )
        return _client


def _reset_for_tests() -> None:
    global _client
    _client = None
    _warned.clear()


def _parse_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def is_league_auction(listing: dict[str, Any]) -> bool:
    """Subasta de LaLiga: sin vendedor y sin oferta directa."""
    seller = listing.get("seller_team_id")
    if isinstance(seller, str) and seller.strip():
        return False
    return listing.get("direct_offer") is not True


def board_row(listing: dict[str, Any], *, league_id: str, now: datetime) -> dict[str, Any] | None:
    """Una fila del tablero. El día es el del cierre, en hora de Madrid."""
    market_id = _text(listing.get("market_id"))
    if market_id is None or not league_id:
        return None
    expires = _text(listing.get("listing_expires_at"))
    day = madrid_day(expires) if expires else madrid_day(now.isoformat())
    if day is None:
        return None
    name = _text(listing.get("nickname")) or _text(listing.get("name"))
    return {
        "league_id": league_id,
        "day": day,
        "market_id": market_id,
        "player_id": _text(listing.get("player_id")),
        "player_name": name,
        "position": _text(listing.get("position")),
        "market_value": _int(listing.get("market_value")),
        "sale_price": _int(listing.get("sale_price")),
        "seller_team_id": _text(listing.get("seller_team_id")),
        "bid_count": _int(listing.get("bid_count")),
        "offer_count": _int(listing.get("offer_count")),
        "direct_offer": listing.get("direct_offer") if isinstance(listing.get("direct_offer"), bool) else None,
        "expires_at": expires,
        "own_bid_eur": _int(listing.get("own_bid")),
        "league_auction": is_league_auction(listing),
        "stored_at": time.time(),
    }


def merge_own_bids(incoming: list[dict[str, Any]], stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """La puja propia se queda si un refresco posterior ya no la trae."""
    previous: dict[tuple[str, str, str], int] = {}
    for row in stored:
        bid = _int(row.get("own_bid_eur"))
        key = (str(row.get("league_id")), str(row.get("day")), str(row.get("market_id")))
        if bid is not None:
            previous[key] = bid
    merged: list[dict[str, Any]] = []
    for row in incoming:
        item = dict(row)
        if item.get("own_bid_eur") is None:
            key = (str(item.get("league_id")), str(item.get("day")), str(item.get("market_id")))
            if key in previous:
                item["own_bid_eur"] = previous[key]
        merged.append(item)
    return merged


def buys_from_ledgers(ledgers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compras de mercado ya unidas al equipo, no al id de mánager."""
    found: list[dict[str, Any]] = []
    for ledger in ledgers:
        if not isinstance(ledger, dict):
            continue
        team_id = _text(ledger.get("team_id"))
        if team_id is None:
            continue
        for event in ledger.get("events") or []:
            if not isinstance(event, dict) or event.get("kind") != "buy":
                continue
            player_id = _text(event.get("player_id"))
            amount = _int(event.get("amount_eur"))
            at = _text(event.get("at"))
            day = madrid_day(at) if at else None
            if player_id is None or amount is None or day is None:
                continue
            found.append(
                {
                    "team_id": team_id,
                    "player_id": player_id,
                    "amount_eur": amount,
                    "at": at,
                    "day": day,
                }
            )
    return found


def latest_activity_at(ledgers: list[dict[str, Any]]) -> datetime | None:
    latest: datetime | None = None
    for ledger in ledgers:
        if not isinstance(ledger, dict):
            continue
        for event in ledger.get("events") or []:
            if not isinstance(event, dict):
                continue
            moment = _parse_at(event.get("at"))
            if moment is not None and (latest is None or moment > latest):
                latest = moment
    return latest


def _closer(buy: dict[str, Any], expiry: datetime | None) -> tuple[float, int]:
    moment = _parse_at(buy.get("at"))
    if expiry is None or moment is None:
        return (0.0, -int(buy.get("amount_eur") or 0))
    return (abs((moment - expiry).total_seconds()), -int(buy.get("amount_eur") or 0))


def resolve_auctions(
    board: list[dict[str, Any]],
    buys: list[dict[str, Any]],
    *,
    own_team_id: str | None,
    now: datetime,
    feed_latest: datetime | None,
    already: set[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Cierra las subastas de LaLiga cuyo cierre ya pasó y la actividad lo cubre."""
    done = already or set()
    results: list[dict[str, Any]] = []
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in board:
        league_id = _text(row.get("league_id"))
        day = _text(row.get("day"))
        market_id = _text(row.get("market_id"))
        if league_id is None or day is None or market_id is None:
            continue
        latest[(league_id, day, market_id)] = row
    for row in latest.values():
        if row.get("league_auction") is False:
            continue
        if not is_league_auction(row) and row.get("league_auction") is not True:
            continue
        league_id = str(row.get("league_id"))
        day = str(row.get("day"))
        market_id = str(row.get("market_id"))
        if (league_id, day, market_id) in done:
            continue
        expiry = _parse_at(row.get("expires_at"))
        if expiry is not None and expiry > now:
            continue
        if expiry is None and day >= (madrid_day(now.isoformat()) or ""):
            continue
        player_id = _text(row.get("player_id"))
        matches = [
            buy
            for buy in buys
            if buy.get("day") == day and player_id is not None and buy.get("player_id") == player_id
        ]
        if matches:
            winner = min(matches, key=lambda buy: _closer(buy, expiry))
            status = "vendida"
            winner_id = str(winner["team_id"])
            amount = int(winner["amount_eur"])
        elif feed_latest is not None and (expiry is None or feed_latest >= expiry):
            status = "sin_comprador"
            winner_id = None
            amount = None
        else:
            continue
        own_bid = _int(row.get("own_bid_eur"))
        if own_bid is None:
            own_result = "sin_puja"
        elif status == "vendida" and own_team_id is not None and winner_id == own_team_id:
            own_result = "ganada"
        else:
            own_result = "perdida"
        results.append(
            {
                "league_id": league_id,
                "day": day,
                "market_id": market_id,
                "player_id": player_id,
                "status": status,
                "winner_team_id": winner_id,
                "amount_eur": amount,
                "own_bid_eur": own_bid,
                "own_result": own_result,
                "resolved_at": time.time(),
            }
        )
    return results


def _missing_table(exc: BaseException) -> bool:
    text = str(exc)
    return "PGRST205" in text or "schema cache" in text


class BlobJournal:
    """Mismo diario dentro de ``dashboard_snapshots`` si las tablas aún no existen.

    La service role no puede crear tablas. Hasta que se aplique el SQL, el
    refresco no puede perder el día: queda en Supabase, en la fila
    ``auction:journal``, que ya sobrevive a los despliegues de Render.
    """

    def __init__(self, load: Any, save: Any) -> None:
        self._load = load
        self._save = save
        self._doc: dict[str, list[dict[str, Any]]] | None = None

    def _document(self) -> dict[str, list[dict[str, Any]]]:
        if self._doc is None:
            raw = self._load() or {}
            board = raw.get("board") if isinstance(raw, dict) else None
            results = raw.get("results") if isinstance(raw, dict) else None
            self._doc = {
                "board": [row for row in board if isinstance(row, dict)] if isinstance(board, list) else [],
                "results": [row for row in results if isinstance(row, dict)] if isinstance(results, list) else [],
            }
        return self._doc

    def _persist(self) -> None:
        doc = self._document()
        self._save({"board": doc["board"], "results": doc["results"]})

    def load_board(self, league_id: str, *, since_day: str) -> list[dict[str, Any]]:
        return [
            row
            for row in self._document()["board"]
            if row.get("league_id") == league_id and str(row.get("day")) >= since_day
        ]

    def load_result_keys(self, league_id: str, *, since_day: str) -> set[tuple[str, str, str]]:
        return {
            (str(row.get("league_id")), str(row.get("day")), str(row.get("market_id")))
            for row in self._document()["results"]
            if row.get("league_id") == league_id and str(row.get("day")) >= since_day
        }

    def upsert_board(self, rows: list[dict[str, Any]]) -> None:
        doc = self._document()
        keys = {(row.get("league_id"), row.get("day"), row.get("market_id")) for row in rows}
        doc["board"] = [
            row
            for row in doc["board"]
            if (row.get("league_id"), row.get("day"), row.get("market_id")) not in keys
        ]
        doc["board"].extend(rows)
        self._persist()

    def upsert_results(self, rows: list[dict[str, Any]]) -> None:
        doc = self._document()
        keys = {(row.get("league_id"), row.get("day"), row.get("market_id")) for row in rows}
        doc["results"] = [
            row
            for row in doc["results"]
            if (row.get("league_id"), row.get("day"), row.get("market_id")) not in keys
        ]
        doc["results"].extend(rows)
        self._persist()


class SupabaseJournal:
    """Lectura y upsert de las dos tablas. Un fallo se traga en ``capture_live``."""

    def load_board(self, league_id: str, *, since_day: str) -> list[dict[str, Any]]:
        response = (
            _get_client()
            .table(TABLE_BOARD)
            .select("*")
            .eq("league_id", league_id)
            .gte("day", since_day)
            .limit(5000)
            .execute()
        )
        data = getattr(response, "data", None)
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def load_results(self, league_id: str, *, since_day: str) -> list[dict[str, Any]]:
        response = (
            _get_client()
            .table(TABLE_RESULTS)
            .select("*")
            .eq("league_id", league_id)
            .gte("day", since_day)
            .limit(5000)
            .execute()
        )
        data = getattr(response, "data", None)
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def load_result_keys(self, league_id: str, *, since_day: str) -> set[tuple[str, str, str]]:
        response = (
            _get_client()
            .table(TABLE_RESULTS)
            .select("league_id,day,market_id")
            .eq("league_id", league_id)
            .gte("day", since_day)
            .limit(5000)
            .execute()
        )
        data = getattr(response, "data", None)
        keys: set[tuple[str, str, str]] = set()
        if not isinstance(data, list):
            return keys
        for row in data:
            if isinstance(row, dict):
                keys.add((str(row.get("league_id")), str(row.get("day")), str(row.get("market_id"))))
        return keys

    def upsert_board(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            _get_client().table(TABLE_BOARD).upsert(rows, on_conflict="league_id,day,market_id").execute()

    def upsert_results(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            _get_client().table(TABLE_RESULTS).upsert(rows, on_conflict="league_id,day,market_id").execute()


def _since(now: datetime) -> str:
    from datetime import timedelta

    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return (moment.date() - timedelta(days=LOOKBACK_DAYS)).isoformat()


def _own_team_id(squads: dict[str, Any]) -> str | None:
    for squad in squads.get("squads") or []:
        if isinstance(squad, dict) and squad.get("is_self") is True:
            team_id = squad.get("team_id")
            if isinstance(team_id, str) and team_id:
                return team_id
    return None


def capture_market_day(
    market: dict[str, Any],
    squads: dict[str, Any],
    ledgers: list[dict[str, Any]],
    *,
    now: datetime,
    journal: Any | None = None,
) -> dict[str, int]:
    """Guarda el tablero de hoy y cierra las subastas ya vencidas."""
    league_id = market.get("league_id") if isinstance(market.get("league_id"), str) else None
    if not league_id:
        league_id = squads.get("league_id") if isinstance(squads.get("league_id"), str) else None
    listings = [row for row in (market.get("listings") or []) if isinstance(row, dict)]
    if not league_id or not listings:
        return {"board": 0, "results": 0}
    incoming = [
        row
        for row in (board_row(item, league_id=league_id, now=now) for item in listings)
        if row is not None
    ]
    if not incoming:
        return {"board": 0, "results": 0}
    store = journal if journal is not None else SupabaseJournal()
    since = _since(now)
    stored = store.load_board(league_id, since_day=since)
    merged = merge_own_bids(incoming, stored)
    store.upsert_board(merged)
    buys = buys_from_ledgers(ledgers)
    results = resolve_auctions(
        stored + merged,
        buys,
        own_team_id=_own_team_id(squads),
        now=now,
        feed_latest=latest_activity_at(ledgers),
        already=store.load_result_keys(league_id, since_day=since),
    )
    store.upsert_results(results)
    return {"board": len(merged), "results": len(results)}


def _read_blob() -> dict[str, Any]:
    from toolbox import snapshot_remote

    rows = (
        _get_client()
        .table(snapshot_remote.TABLE)
        .select("payload")
        .eq("key", snapshot_remote.snapshot_key("auction", "journal"))
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return {}
    envelope = snapshot_remote._unpack(str(rows[0].get("payload") or ""))
    value = envelope.get("value") if isinstance(envelope, dict) else None
    return value if isinstance(value, dict) else {}


def _write_blob(document: dict[str, Any]) -> None:
    from toolbox import snapshot_remote

    snapshot_remote.save("auction", "journal", {"saved_unix": time.time(), "value": document})


def _flush_blob(journal: SupabaseJournal) -> None:
    """Pasa a las tablas lo que se guardó en el sobre mientras no existían."""
    try:
        document = _read_blob()
    except Exception:  # noqa: BLE001 — sin sobre no hay nada que pasar
        return
    board = [row for row in document.get("board") or [] if isinstance(row, dict)]
    results = [row for row in document.get("results") or [] if isinstance(row, dict)]
    if not board and not results:
        return
    journal.upsert_board(board)
    journal.upsert_results(results)
    _write_blob({"board": [], "results": []})


def ventas_cerradas(league_id: str | None) -> list[dict[str, Any]]:
    """Compras ya resueltas del diario, con el valor de mercado guardado ese día.

    Sirve para que los multiplicadores de puja se muevan con cada compra nueva.
    Sin Supabase, o si el diario aún no tiene filas, devuelve una lista vacía.
    """
    if not isinstance(league_id, str) or not league_id or not _enabled():
        return []
    board: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        board = SupabaseJournal().load_board(league_id, since_day="2020-01-01")
        results = SupabaseJournal().load_results(league_id, since_day="2020-01-01")
    except Exception as exc:  # noqa: BLE001 — sin tablas se lee el sobre
        if not _missing_table(exc):
            _warn_once("No se pudo leer el diario de subastas", exc)
        try:
            document = _read_blob()
        except Exception as blob_exc:  # noqa: BLE001
            _warn_once("No se pudo leer el diario de subastas", blob_exc)
            return []
        board = [row for row in document.get("board") or [] if isinstance(row, dict) and row.get("league_id") == league_id]
        results = [row for row in document.get("results") or [] if isinstance(row, dict) and row.get("league_id") == league_id]
    valor_de = {
        (str(row.get("day")), str(row.get("market_id"))): row.get("market_value")
        for row in board
        if row.get("day") and row.get("market_id")
    }
    ventas: list[dict[str, Any]] = []
    for row in results:
        if row.get("status") != "vendida":
            continue
        amount = row.get("amount_eur")
        winner = row.get("winner_team_id")
        player_id = row.get("player_id")
        day = row.get("day")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            continue
        if not isinstance(winner, str) or not isinstance(player_id, str) or not isinstance(day, str):
            continue
        reference = valor_de.get((day, str(row.get("market_id"))))
        if isinstance(reference, bool) or not isinstance(reference, int) or reference <= 0:
            continue
        ventas.append(
            {
                "team_id": winner,
                "player_id": player_id,
                "day": day,
                "amount_eur": amount,
                "reference_eur": reference,
            }
        )
    return ventas


def capture_live(
    market: dict[str, Any],
    squads: dict[str, Any],
    ledgers: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, int]:
    """Igual que ``capture_market_day``, solo con Supabase configurado. Nunca lanza."""
    if not _enabled():
        return {"board": 0, "results": 0}
    try:
        summary = capture_market_day(market, squads, ledgers, now=now)
    except Exception as exc:  # noqa: BLE001 — el diario no puede tumbar la caja
        if not _missing_table(exc):
            _warn_once("No se pudo guardar el diario de subastas en Supabase", exc)
            return {"board": 0, "results": 0}
        _warn_once(
            "market_board aún no existe; el diario queda en dashboard_snapshots (auction:journal) hasta aplicar scripts/init_supabase.sql",
            exc,
        )
        try:
            return capture_market_day(
                market,
                squads,
                ledgers,
                now=now,
                journal=BlobJournal(_read_blob, _write_blob),
            )
        except Exception as blob_exc:  # noqa: BLE001
            _warn_once("No se pudo guardar el diario de subastas en Supabase", blob_exc)
            return {"board": 0, "results": 0}
    try:
        _flush_blob(SupabaseJournal())
    except Exception as exc:  # noqa: BLE001 — las tablas ya tienen el día; el traspaso puede esperar
        _warn_once("No se pudo pasar el diario antiguo a las tablas", exc)
    return summary

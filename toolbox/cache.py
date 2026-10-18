"""Caché y persistencia sobre Supabase (PostgreSQL).

Sustituye SQLite. Con ``SUPABASE_URL`` y ``SUPABASE_KEY`` se usa el cliente
oficial ``supabase-py``. Sin credenciales, o cuando se pasa un ``root``
explícito (pruebas), un almacén JSON local imita la API de tablas.
Los cuerpos de scrapers viven en la fila: no hay ficheros sueltos ni bearer.
Una entrada caducada se trata como ausente.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from supabase import create_client

from toolbox import project_root

TABLE_SCRAPER_CACHE = "scraper_cache"
TABLE_PLAYER_LINKS = "player_links"
TABLE_MATCH_AUDITS = "match_audits"
TABLE_CASH_LEDGERS = "cash_ledgers"


def cache_root() -> Path:
    override = os.getenv("FANTASY_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return project_root() / ".cache"


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_KEY", "").strip())


def _use_remote(*, explicit_root: bool) -> bool:
    if explicit_root:
        return False
    if os.getenv("FANTASY_CACHE_DIR", "").strip():
        return False
    return supabase_configured()


def _open_backend(root: Path, *, explicit_root: bool) -> Any:
    if _use_remote(explicit_root=explicit_root):
        return create_client(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_KEY"].strip())
    root.mkdir(parents=True, exist_ok=True)
    return LocalSupabase(root)


class _ExecuteResult:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _Query:
    """Subconjunto de la API de tablas de supabase-py usado por este módulo."""

    def __init__(self, store: LocalSupabase, table: str) -> None:
        self._store = store
        self._table = table
        self._op = "select"
        self._payload: Any = None
        self._filters: list[tuple[str, str, Any]] = []
        self._orders: list[tuple[str, bool]] = []
        self._on_conflict = ""

    def select(self, _columns: str = "*") -> _Query:
        self._op = "select"
        return self

    def insert(self, payload: Any) -> _Query:
        self._op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload: Any, on_conflict: str = "") -> _Query:
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def delete(self) -> _Query:
        self._op = "delete"
        return self

    def eq(self, column: str, value: Any) -> _Query:
        self._filters.append(("eq", column, value))
        return self

    def lte(self, column: str, value: Any) -> _Query:
        self._filters.append(("lte", column, value))
        return self

    def order(self, column: str, desc: bool = False) -> _Query:
        self._orders.append((column, bool(desc)))
        return self

    def execute(self) -> _ExecuteResult:
        return self._store.execute(self)


class LocalSupabase:
    """Almacén JSON con la misma interfaz ``table().select().eq().execute()``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dir = root / "supabase-local"
        self.dir.mkdir(parents=True, exist_ok=True)

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def execute(self, query: _Query) -> _ExecuteResult:
        path = self.dir / f"{query._table}.json"
        lock = _file_lock(path)
        with lock:
            rows = _read_rows(path)
            if query._op == "select":
                matched = [_copy(row) for row in rows if _matches(row, query._filters)]
                for column, descending in reversed(query._orders):
                    matched.sort(key=lambda row, col=column: _sort_value(row.get(col)), reverse=descending)
                return _ExecuteResult(matched)
            if query._op == "delete":
                kept = [row for row in rows if not _matches(row, query._filters)]
                _write_rows(path, kept)
                return _ExecuteResult([])
            incoming = query._payload
            items = incoming if isinstance(incoming, list) else [incoming]
            if query._op == "insert":
                rows.extend(_copy(item) for item in items if isinstance(item, dict))
                _write_rows(path, rows)
                return _ExecuteResult([_copy(item) for item in items if isinstance(item, dict)])
            keys = [part.strip() for part in (query._on_conflict or "").split(",") if part.strip()]
            for item in items:
                if not isinstance(item, dict):
                    continue
                payload = _copy(item)
                index = _find_conflict(rows, payload, keys) if keys else None
                if index is None:
                    rows.append(payload)
                else:
                    rows[index] = payload
            _write_rows(path, rows)
            return _ExecuteResult([_copy(item) for item in items if isinstance(item, dict)])


_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _file_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[key] = lock
        return lock


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _copy(row: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(row, ensure_ascii=False))


def _matches(row: Mapping[str, Any], filters: list[tuple[str, str, Any]]) -> bool:
    for operation, column, expected in filters:
        actual = row.get(column)
        if operation == "eq" and actual != expected:
            return False
        if operation == "lte":
            if actual is None or expected is None:
                return False
            try:
                if float(actual) > float(expected):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _find_conflict(rows: list[dict[str, Any]], payload: Mapping[str, Any], keys: list[str]) -> int | None:
    for index, row in enumerate(rows):
        if all(row.get(key) == payload.get(key) for key in keys):
            return index
    return None


def _sort_value(value: Any) -> tuple[int, Any]:
    if value is None:
        return (1, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, float(value))
    return (0, str(value))


def _first_row(result: Any) -> dict[str, Any] | None:
    rows = getattr(result, "data", None)
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    return row if isinstance(row, dict) else None


def _rows(result: Any) -> list[dict[str, Any]]:
    rows = getattr(result, "data", None)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


class ResponseCache:
    def __init__(self, root: Path | None = None) -> None:
        explicit = root is not None
        self.root = root or cache_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.client = _open_backend(self.root, explicit_root=explicit)

    def close(self) -> None:
        return None

    def get_json(self, url: str) -> Any | None:
        body = self._read(url, kind="json")
        if body is None:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            self._delete(url)
            return None

    def put_json(self, url: str, payload: Any, ttl_seconds: float) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._write(url, kind="json", body=encoded, ttl_seconds=ttl_seconds)

    def get_page(self, url: str) -> str | None:
        return self._read(url, kind="page")

    def put_page(self, url: str, html: str, ttl_seconds: float) -> None:
        self._write(url, kind="page", body=html, ttl_seconds=ttl_seconds)

    def purge_expired(self) -> int:
        now = time.time()
        with self._lock:
            rows = _rows(
                self.client.table(TABLE_SCRAPER_CACHE).select("cache_key").lte("expires_at", now).execute()
            )
            self.client.table(TABLE_SCRAPER_CACHE).delete().lte("expires_at", now).execute()
        return len(rows)

    def _read(self, url: str, *, kind: str) -> str | None:
        key = cache_key(url)
        now = time.time()
        with self._lock:
            row = _first_row(
                self.client.table(TABLE_SCRAPER_CACHE).select("*").eq("cache_key", key).execute()
            )
            if row is None:
                return None
            stored_kind = str(row.get("kind") or "")
            try:
                expires_at = float(row.get("expires_at"))
            except (TypeError, ValueError):
                expires_at = 0.0
            if stored_kind != kind or expires_at <= now:
                self.client.table(TABLE_SCRAPER_CACHE).delete().eq("cache_key", key).execute()
                return None
            body = row.get("body")
            return body if isinstance(body, str) else None

    def _write(self, url: str, *, kind: str, body: str, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        key = cache_key(url)
        now = time.time()
        payload = {
            "cache_key": key,
            "url": url,
            "kind": kind,
            "status_code": 200,
            "stored_at": now,
            "expires_at": now + ttl_seconds,
            "body": body,
        }
        with self._lock:
            self.client.table(TABLE_SCRAPER_CACHE).upsert(payload, on_conflict="cache_key").execute()

    def _delete(self, url: str) -> None:
        key = cache_key(url)
        with self._lock:
            self.client.table(TABLE_SCRAPER_CACHE).delete().eq("cache_key", key).execute()


class EntityStore:
    """Equivalencias ``player_id`` de LALIGA Fantasy <-> fuente externa.

    Un mapeo manual no se pisa al volver a emparejar.
    """

    def __init__(self, root: Path | None = None) -> None:
        explicit = root is not None
        self.root = root or cache_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.client = _open_backend(self.root, explicit_root=explicit)

    def close(self) -> None:
        return None

    def get_link(self, player_id: str, source: str) -> dict[str, Any] | None:
        with self._lock:
            row = _first_row(
                self.client.table(TABLE_PLAYER_LINKS)
                .select("*")
                .eq("player_id", player_id)
                .eq("source", source)
                .execute()
            )
        return _link_dict(row) if row is not None else None

    def links_for(self, player_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = _rows(
                self.client.table(TABLE_PLAYER_LINKS)
                .select("*")
                .eq("player_id", player_id)
                .order("source")
                .execute()
            )
        return [_link_dict(row) for row in rows]

    def list_links(self, source: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            query = self.client.table(TABLE_PLAYER_LINKS).select("*")
            if source is not None:
                query = query.eq("source", source)
            rows = _rows(query.order("player_id").order("source").execute())
        return [_link_dict(row) for row in rows]

    def manual_links(self, source: str) -> list[dict[str, Any]]:
        return [link for link in self.list_links(source) if link["manual"]]

    def put_link(
        self,
        *,
        player_id: str,
        source: str,
        external_name: str,
        external_id: str | None,
        club: str | None,
        position: str | None,
        confidence: float,
        manual: bool,
    ) -> dict[str, Any]:
        current = self.get_link(player_id, source)
        if current is not None and current["manual"] and not manual:
            return current
        now = time.time()
        payload = {
            "player_id": player_id,
            "source": source,
            "external_id": external_id,
            "external_name": external_name,
            "club": club,
            "position": position,
            "confidence": confidence,
            "manual": bool(manual),
            "updated_at": now,
        }
        with self._lock:
            self.client.table(TABLE_PLAYER_LINKS).upsert(payload, on_conflict="player_id,source").execute()
            self.client.table(TABLE_MATCH_AUDITS).delete().eq("player_id", player_id).eq("source", source).execute()
        stored = self.get_link(player_id, source)
        if stored is None:
            raise RuntimeError("No se pudo leer el mapeo recién escrito.")
        return stored

    def clear_auto(self, source: str) -> None:
        with self._lock:
            autos = [
                row
                for row in _rows(
                    self.client.table(TABLE_PLAYER_LINKS).select("*").eq("source", source).execute()
                )
                if not bool(row.get("manual"))
            ]
            for row in autos:
                self.client.table(TABLE_PLAYER_LINKS).delete().eq("player_id", row["player_id"]).eq(
                    "source", source
                ).execute()

    def clear_audits(self, source: str) -> None:
        with self._lock:
            self.client.table(TABLE_MATCH_AUDITS).delete().eq("source", source).execute()

    def put_audit(
        self,
        *,
        player_id: str,
        source: str,
        external_name: str | None,
        candidate_name: str | None,
        confidence: float,
        reason: str,
    ) -> None:
        payload = {
            "player_id": player_id,
            "source": source,
            "external_name": external_name,
            "candidate_name": candidate_name,
            "confidence": confidence,
            "reason": reason,
            "created_at": time.time(),
        }
        with self._lock:
            self.client.table(TABLE_MATCH_AUDITS).upsert(payload, on_conflict="player_id,source").execute()

    def list_audits(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = _rows(
                self.client.table(TABLE_MATCH_AUDITS)
                .select("*")
                .order("confidence", desc=True)
                .order("player_id")
                .order("source")
                .execute()
            )
        return [_audit_dict(row) for row in rows]


class CashLedgerStore:
    """Libro mayor de caja reconstruido por liga y equipo rival."""

    def __init__(self, root: Path | None = None, *, client: Any | None = None) -> None:
        explicit = root is not None and client is None
        self.root = root or cache_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.client = client if client is not None else _open_backend(self.root, explicit_root=explicit)

    def close(self) -> None:
        return None

    def replace_league(
        self,
        league_id: str,
        ledgers: list[dict[str, Any]],
        *,
        fingerprint: str | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            self.client.table(TABLE_CASH_LEDGERS).delete().eq("league_id", league_id).execute()
            for ledger in ledgers:
                team_id = ledger.get("team_id")
                if not isinstance(team_id, str) or not team_id:
                    continue
                payload = {
                    "league_id": league_id,
                    "team_id": team_id,
                    "manager_name": ledger.get("manager_name") if isinstance(ledger.get("manager_name"), str) else None,
                    "initial_budget_eur": ledger.get("initial_budget_eur"),
                    "premiums_eur": ledger.get("premiums_eur") or 0,
                    "purchases_eur": ledger.get("purchases_eur") or 0,
                    "clauses_eur": ledger.get("clauses_eur") or 0,
                    "sales_eur": ledger.get("sales_eur") or 0,
                    "reconstructed_cash_eur": ledger.get("reconstructed_cash_eur"),
                    "observed_cash_eur": ledger.get("observed_cash_eur"),
                    "balanced": ledger.get("balanced"),
                    "gap_eur": ledger.get("gap_eur"),
                    "ignored_events": ledger.get("ignored_events") or 0,
                    "events": ledger.get("events") if isinstance(ledger.get("events"), list) else [],
                    "fingerprint": fingerprint,
                    "updated_at": now,
                }
                self.client.table(TABLE_CASH_LEDGERS).upsert(
                    payload, on_conflict="league_id,team_id"
                ).execute()

    def list_ledgers(self, league_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            query = self.client.table(TABLE_CASH_LEDGERS).select("*")
            if league_id is not None:
                query = query.eq("league_id", league_id)
            rows = _rows(query.order("league_id").order("team_id").execute())
        return [_ledger_dict(row) for row in rows]


def _link_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row["player_id"],
        "source": row["source"],
        "external_id": row["external_id"],
        "external_name": row["external_name"],
        "club": row["club"],
        "position": row["position"],
        "confidence": float(row["confidence"]),
        "manual": bool(row["manual"]),
        "updated_at": float(row["updated_at"]),
    }


def _audit_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row["player_id"],
        "source": row["source"],
        "external_name": row["external_name"],
        "candidate_name": row["candidate_name"],
        "confidence": float(row["confidence"]),
        "reason": row["reason"],
        "created_at": float(row["created_at"]),
    }


def _ledger_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    events = row.get("events")
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except json.JSONDecodeError:
            events = []
    return {
        "league_id": row.get("league_id"),
        "team_id": row.get("team_id"),
        "manager_name": row.get("manager_name"),
        "initial_budget_eur": row.get("initial_budget_eur"),
        "premiums_eur": row.get("premiums_eur"),
        "purchases_eur": row.get("purchases_eur"),
        "clauses_eur": row.get("clauses_eur"),
        "sales_eur": row.get("sales_eur"),
        "reconstructed_cash_eur": row.get("reconstructed_cash_eur"),
        "observed_cash_eur": row.get("observed_cash_eur"),
        "balanced": row.get("balanced") if isinstance(row.get("balanced"), bool) else None,
        "gap_eur": row.get("gap_eur"),
        "ignored_events": row.get("ignored_events"),
        "events": events if isinstance(events, list) else [],
        "fingerprint": row.get("fingerprint"),
        "updated_at": float(row["updated_at"]) if row.get("updated_at") is not None else None,
    }

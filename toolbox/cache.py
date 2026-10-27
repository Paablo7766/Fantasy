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
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from supabase import create_client

from toolbox import project_root

logger = logging.getLogger("fantasy.cache")

TABLE_SCRAPER_CACHE = "scraper_cache"
TABLE_PLAYER_LINKS = "player_links"
TABLE_MATCH_AUDITS = "match_audits"
TABLE_CASH_LEDGERS = "cash_ledgers"
TABLE_PRICE_SNAPSHOTS = "price_snapshots"

# Mínimo de jugadores en común para considerar que un lote repite el día
# anterior. El mercado de LaLiga se mueve todos los días: una coincidencia
# total sobre este número de precios no es casualidad, es una copia.
_FLAT_DAY_MIN_SHARED = 20


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

    def gte(self, column: str, value: Any) -> _Query:
        self._filters.append(("gte", column, value))
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


def _atomic_write_text(path: Path, payload: str) -> None:
    """Escritura atómica con reintento: en Windows ``replace`` falla si el
    antivirus u otro hilo aún tiene abierto el destino."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}.{threading.get_ident()}")
    temporary.write_text(payload, encoding="utf-8")
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    try:
        path.write_text(payload, encoding="utf-8")
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    if last_error is not None and not path.exists():
        raise last_error


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write_text(path, json.dumps(rows, ensure_ascii=False))


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
                # Comparación lexicográfica para días ISO (YYYY-MM-DD).
                if str(actual) > str(expected):
                    return False
        if operation == "gte":
            if actual is None or expected is None:
                return False
            try:
                if float(actual) < float(expected):
                    return False
            except (TypeError, ValueError):
                if str(actual) < str(expected):
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


_SCRAPER_BODIES = "scraper_bodies"
# Una migración del JSON monolítico por directorio de caché. Después, cada
# lectura que falla no vuelve a parsear el fichero histórico.
_LEGACY_MIGRATED: set[str] = set()
_LEGACY_GUARD = threading.Lock()


def _scraper_body_path(root: Path, key: str) -> Path:
    return root / _SCRAPER_BODIES / key


def _read_entry(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_entry(path: Path, row: Mapping[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(dict(row), ensure_ascii=False))


def _entry_body(row: Mapping[str, Any] | None, *, kind: str, now: float) -> str | None:
    if row is None or str(row.get("kind") or "") != kind:
        return None
    try:
        expires_at = float(row.get("expires_at"))
    except (TypeError, ValueError):
        return None
    if expires_at <= now:
        return None
    body = row.get("body")
    return body if isinstance(body, str) else None


def _entry_body_stale(row: Mapping[str, Any] | None, *, kind: str) -> str | None:
    if row is None or str(row.get("kind") or "") != kind:
        return None
    body = row.get("body")
    return body if isinstance(body, str) else None


def _migrate_legacy_scraper_cache(root: Path) -> dict[str, dict[str, Any]]:
    """Parte el ``scraper_cache.json`` histórico en un fichero por entrada.

    Ese JSON acumulaba el HTML de todas las fuentes (~50 MB). Cada acierto
    lo parseaba entero y cada escritura lo volvía a serializar, y el paso de
    mercado no llegaba a responder.
    """
    path = root / "supabase-local" / f"{TABLE_SCRAPER_CACHE}.json"
    token = str(path)
    with _LEGACY_GUARD:
        if token in _LEGACY_MIGRATED:
            return {}
        if not path.is_file() or path.stat().st_size < 10:
            _LEGACY_MIGRATED.add(token)
            return {}
        rows = _read_rows(path)
        now = time.time()
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = row.get("cache_key")
            body = row.get("body")
            if not isinstance(key, str) or not isinstance(body, str):
                continue
            try:
                expires_at = float(row.get("expires_at"))
            except (TypeError, ValueError):
                continue
            if expires_at <= now:
                continue
            entry = {"kind": str(row.get("kind") or ""), "expires_at": expires_at, "body": body}
            dest = _scraper_body_path(root, key)
            if not dest.exists():
                _write_entry(dest, entry)
            index[key] = entry
        _write_rows(path, [])
        _LEGACY_MIGRATED.add(token)
        return index


def _read_local_body(root: Path, url: str, *, kind: str) -> str | None:
    key = cache_key(url)
    path = _scraper_body_path(root, key)
    now = time.time()
    lock = _file_lock(path)
    with lock:
        row = _read_entry(path)
        body = _entry_body(row, kind=kind, now=now)
        if body is not None:
            return body
        if row is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    legacy = _migrate_legacy_scraper_cache(root)
    body = _entry_body(legacy.get(key), kind=kind, now=now)
    if body is not None:
        return body
    with lock:
        return _entry_body(_read_entry(path), kind=kind, now=time.time())


def _read_local_body_stale(root: Path, url: str, *, kind: str) -> str | None:
    key = cache_key(url)
    path = _scraper_body_path(root, key)
    lock = _file_lock(path)
    with lock:
        body = _entry_body_stale(_read_entry(path), kind=kind)
        if body is not None:
            return body
    legacy = _migrate_legacy_scraper_cache(root)
    return _entry_body_stale(legacy.get(key), kind=kind)


def _write_local_body(root: Path, url: str, *, kind: str, body: str, ttl_seconds: float) -> None:
    if ttl_seconds <= 0:
        return
    key = cache_key(url)
    path = _scraper_body_path(root, key)
    now = time.time()
    # ``stored_at`` es lo que permite medir la edad real de una copia (el
    # catálogo de LaLiga se refresca a mano y solo pasado su TTL de 6 h).
    entry = {"kind": kind, "stored_at": now, "expires_at": now + ttl_seconds, "body": body}
    lock = _file_lock(path)
    with lock:
        _write_entry(path, entry)


def _delete_local_body(root: Path, url: str) -> None:
    path = _scraper_body_path(root, cache_key(url))
    lock = _file_lock(path)
    with lock:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _purge_local_bodies(root: Path) -> int:
    folder = root / _SCRAPER_BODIES
    if not folder.is_dir():
        return 0
    now = time.time()
    removed = 0
    for path in folder.iterdir():
        if not path.is_file():
            continue
        lock = _file_lock(path)
        with lock:
            row = _read_entry(path)
            try:
                expires_at = float(row.get("expires_at")) if row else 0.0
            except (TypeError, ValueError):
                expires_at = 0.0
            if row is None or expires_at <= now:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
                removed += 1
    return removed


class ResponseCache:
    def __init__(self, root: Path | None = None) -> None:
        explicit = root is not None
        self.root = root or cache_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.client = _open_backend(self.root, explicit_root=explicit)
        self._local = isinstance(self.client, LocalSupabase)

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

    def get_json_stale(self, url: str) -> Any | None:
        body = self._read_stale(url, kind="json")
        if body is None:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def put_json(self, url: str, payload: Any, ttl_seconds: float) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._write(url, kind="json", body=encoded, ttl_seconds=ttl_seconds)

    def entry_meta(self, url: str, *, kind: str = "json") -> dict[str, Any] | None:
        """Sello temporal de la copia en disco, sin leer el cuerpo.

        ``stored_at`` puede faltar en entradas antiguas (anteriores a que se
        guardara): en ese caso se devuelve ``None`` y quien pregunte debe
        tratar la copia como de edad desconocida, no como recién escrita.
        """
        if self._local:
            path = _scraper_body_path(self.root, cache_key(url))
            row = _read_entry(path)
            if row is None or str(row.get("kind") or "") != kind:
                return None
            stored = row.get("stored_at")
            if not isinstance(stored, (int, float)):
                # Entradas escritas antes de que se guardara ``stored_at``. El
                # mtime del fichero es la edad real del cuerpo y evita que una
                # copia de hace días se selle con la hora del proceso.
                try:
                    stored = path.stat().st_mtime
                except OSError:
                    stored = None
            return {
                "stored_at": stored if isinstance(stored, (int, float)) else None,
                "expires_at": row.get("expires_at") if isinstance(row.get("expires_at"), (int, float)) else None,
            }
        key = cache_key(url)
        with self._lock:
            row = _first_row(
                self.client.table(TABLE_SCRAPER_CACHE).select("*").eq("cache_key", key).execute()
            )
        if row is None or str(row.get("kind") or "") != kind:
            return None
        stored = row.get("stored_at")
        expires = row.get("expires_at")
        return {
            "stored_at": float(stored) if isinstance(stored, (int, float)) else None,
            "expires_at": float(expires) if isinstance(expires, (int, float)) else None,
        }

    def age_seconds(self, url: str, *, kind: str = "json", now: float | None = None) -> float | None:
        """Edad de la copia en segundos. ``None`` si no hay copia o sello."""
        meta = self.entry_meta(url, kind=kind)
        if not meta or not isinstance(meta.get("stored_at"), (int, float)):
            return None
        return max(0.0, (time.time() if now is None else now) - float(meta["stored_at"]))

    def get_page(self, url: str) -> str | None:
        return self._read(url, kind="page")

    def get_page_stale(self, url: str) -> str | None:
        return self._read_stale(url, kind="page")

    def put_page(self, url: str, html: str, ttl_seconds: float) -> None:
        self._write(url, kind="page", body=html, ttl_seconds=ttl_seconds)

    def purge_expired(self) -> int:
        if self._local:
            return _purge_local_bodies(self.root)
        now = time.time()
        with self._lock:
            rows = _rows(
                self.client.table(TABLE_SCRAPER_CACHE).select("cache_key").lte("expires_at", now).execute()
            )
            self.client.table(TABLE_SCRAPER_CACHE).delete().lte("expires_at", now).execute()
        return len(rows)

    def _read(self, url: str, *, kind: str) -> str | None:
        if self._local:
            return _read_local_body(self.root, url, kind=kind)
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

    def _read_stale(self, url: str, *, kind: str) -> str | None:
        if self._local:
            return _read_local_body_stale(self.root, url, kind=kind)
        key = cache_key(url)
        with self._lock:
            row = _first_row(
                self.client.table(TABLE_SCRAPER_CACHE).select("*").eq("cache_key", key).execute()
            )
            if row is None:
                return None
            stored_kind = str(row.get("kind") or "")
            if stored_kind != kind:
                return None
            body = row.get("body")
            return body if isinstance(body, str) else None

    def _write(self, url: str, *, kind: str, body: str, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        if self._local:
            _write_local_body(self.root, url, kind=kind, body=body, ttl_seconds=ttl_seconds)
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
        if self._local:
            _delete_local_body(self.root, url)
            return
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
            # Lectura dentro del mismo lock: evita carrera con otro proceso/hilo
            # que reescribe player_links.json en Windows a mitad del get.
            row = _first_row(
                self.client.table(TABLE_PLAYER_LINKS)
                .select("*")
                .eq("player_id", player_id)
                .eq("source", source)
                .execute()
            )
        if row is not None:
            return _link_dict(row)
        # El upsert ya se hizo; no tumbar trends por un readback flaky.
        return _link_dict(payload)

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


class PriceSnapshotStore:
    """Histórico diario de valor de mercado LALIGA Fantasy (Europe/Madrid)."""

    def __init__(self, root: Path | None = None, *, client: Any | None = None) -> None:
        explicit = root is not None and client is None
        self.root = root or cache_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.client = client if client is not None else _open_backend(self.root, explicit_root=explicit)

    def close(self) -> None:
        return None

    def upsert_price_snapshots(self, rows: list[dict[str, Any]]) -> int:
        """Upsert idempotente por (player_id, day). Un solo write por lote."""
        now = time.time()
        payloads: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            player_id = row.get("player_id")
            day = row.get("day")
            if not isinstance(player_id, str) or not player_id:
                continue
            if not isinstance(day, str) or not day:
                continue
            key = (player_id, day)
            if key in seen:
                continue
            seen.add(key)
            value = row.get("market_value")
            change = row.get("market_value_change")
            payloads.append(
                {
                    "player_id": player_id,
                    "day": day,
                    "league_id": row.get("league_id") if isinstance(row.get("league_id"), str) else None,
                    "market_value": value if isinstance(value, int) and not isinstance(value, bool) else None,
                    "market_value_change": change
                    if isinstance(change, int) and not isinstance(change, bool)
                    else None,
                    "stored_at": float(row.get("stored_at") or now),
                }
            )
        if not payloads:
            return 0
        # Guarda contra el «día copia»: el mercado de LaLiga se mueve a diario,
        # así que un lote cuyos valores son idénticos al último día grabado no
        # es una captura nueva, es la foto de ayer con el sello de hoy. Se
        # grabó una vez (2026-10-25 con los 148 valores del 24) y envenenó la
        # cinemática con un delta de 0 € que ocultaba el movimiento real.
        payloads = self._drop_copy_of_previous_day(payloads)
        if not payloads:
            return 0
        # Lotes: el almacén local reescribe el JSON entero por execute();
        # uno por jugador congelaba /api/trends (~500 writes).
        chunk_size = 200
        with self._lock:
            for start in range(0, len(payloads), chunk_size):
                chunk = payloads[start : start + chunk_size]
                self.client.table(TABLE_PRICE_SNAPSHOTS).upsert(
                    chunk, on_conflict="player_id,day"
                ).execute()
        return len(payloads)

    def _drop_copy_of_previous_day(
        self, payloads: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Descarta el lote si repite integro el último día ya grabado.

        Solo se compara contra el día anterior (nunca contra el mismo día: un
        re-upsert del día en curso es legítimo y actualiza valores). Se exige
        una coincidencia total sobre un mínimo de jugadores para no confundir
        una casualidad de dos precios con una copia de la foto.
        """
        days = {str(row["day"]) for row in payloads}
        if len(days) != 1:
            return payloads
        day = next(iter(days))
        try:
            previous_day = self._previous_day_before(day)
        except Exception:  # noqa: BLE001 — la guarda no puede tumbar el motor
            return payloads
        if not previous_day:
            return payloads
        try:
            previous = {
                str(row.get("player_id")): _snapshot_dict(row).get("market_value")
                for row in self._rows_for_day(previous_day)
            }
        except Exception:  # noqa: BLE001
            return payloads
        if len(previous) < _FLAT_DAY_MIN_SHARED:
            return payloads
        shared = [row for row in payloads if row["player_id"] in previous]
        if len(shared) < _FLAT_DAY_MIN_SHARED:
            return payloads
        if any(row["market_value"] != previous[row["player_id"]] for row in shared):
            return payloads
        logger.warning(
            "Snapshot %s descartado: sus %d valores son idénticos a %s (copia, no captura).",
            day,
            len(shared),
            previous_day,
        )
        return []

    def _previous_day_before(self, day: str) -> str | None:
        """Día grabado inmediatamente anterior a ``day``.

        Se resuelve en memoria con un ``select`` completo de la columna ``day``
        en vez de añadir ``lt``/``limit`` al constructor de consultas: esos
        operadores no existen en el subconjunto que este módulo implementa y
        añadirlos solo para esta guarda ampliaba la superficie del backend.
        """
        rows = _rows(self.client.table(TABLE_PRICE_SNAPSHOTS).select("day").execute())
        candidates = [
            str(row["day"])
            for row in rows
            if isinstance(row.get("day"), str) and str(row["day"]) < day
        ]
        return max(candidates) if candidates else None

    def _rows_for_day(self, day: str) -> list[dict[str, Any]]:
        return _rows(
            self.client.table(TABLE_PRICE_SNAPSHOTS)
            .select("player_id,day,market_value")
            .eq("day", day)
            .execute()
        )

    def price_history(self, player_id: str, *, days: int = 14) -> list[dict[str, Any]]:
        since = _day_offset_madrid(-(max(1, days) - 1))
        with self._lock:
            rows = _rows(
                self.client.table(TABLE_PRICE_SNAPSHOTS)
                .select("*")
                .eq("player_id", player_id)
                .gte("day", since)
                .order("day")
                .execute()
            )
        return [_snapshot_dict(row) for row in rows]

    def list_history(
        self,
        *,
        league_id: str | None = None,
        days: int = 14,
    ) -> dict[str, list[dict[str, Any]]]:
        """Histórico por jugador desde ``days`` atrás (incluye hoy)."""
        since = _day_offset_madrid(-(max(1, days) - 1))
        with self._lock:
            query = self.client.table(TABLE_PRICE_SNAPSHOTS).select("*").gte("day", since)
            if league_id is not None:
                query = query.eq("league_id", league_id)
            rows = _rows(query.order("day").execute())
        out: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            snap = _snapshot_dict(row)
            pid = snap.get("player_id")
            if isinstance(pid, str):
                out.setdefault(pid, []).append(snap)
        return out

    def latest_prices(self, league_id: str | None = None) -> dict[str, dict[str, Any]]:
        with self._lock:
            query = self.client.table(TABLE_PRICE_SNAPSHOTS).select("*")
            if league_id is not None:
                query = query.eq("league_id", league_id)
            rows = _rows(query.order("day", desc=True).execute())
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            snap = _snapshot_dict(row)
            pid = snap.get("player_id")
            if isinstance(pid, str) and pid not in latest:
                latest[pid] = snap
        return latest

    def all_snapshots(self, league_id: str | None = None) -> list[dict[str, Any]]:
        """Export completo para auditoría offline (calibración SELL_AT_CREST)."""
        with self._lock:
            query = self.client.table(TABLE_PRICE_SNAPSHOTS).select("*").order("day")
            if league_id is not None:
                query = query.eq("league_id", league_id)
            rows = _rows(query.execute())
        return [_snapshot_dict(row) for row in rows]


def madrid_day(moment: float | None = None) -> str:
    """Fecha civil Europe/Madrid como YYYY-MM-DD."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    ts = moment if moment is not None else time.time()
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ZoneInfo("Europe/Madrid")).date().isoformat()


def _day_offset_madrid(offset_days: int) -> str:
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    today = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Madrid")).date()
    return (today + timedelta(days=offset_days)).isoformat()


def _snapshot_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("market_value")
    change = row.get("market_value_change")
    return {
        "player_id": row.get("player_id"),
        "day": row.get("day"),
        "league_id": row.get("league_id"),
        "market_value": value if isinstance(value, int) and not isinstance(value, bool) else None,
        "market_value_change": change if isinstance(change, int) and not isinstance(change, bool) else None,
        "stored_at": float(row["stored_at"]) if row.get("stored_at") is not None else None,
    }


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

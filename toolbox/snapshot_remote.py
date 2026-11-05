"""Copia de la foto del tablero en Supabase, para sobrevivir a los despliegues.

La foto vive en ``.cache/dashboard/<liga>/<tipo>.json``. En Render ese disco se
borra en cada despliegue y el panel se quedaba con «Todavía no hay ninguna
foto guardada» hasta terminar una descarga de varios minutos. Aquí se guarda
también una copia comprimida en la tabla ``dashboard_snapshots`` y se restaura
cuando el disco no la tiene.

Todo es opcional y a prueba de fallos: sin ``SUPABASE_URL``/``SUPABASE_KEY``, con
``FANTASY_CACHE_DIR`` (pruebas) o si la tabla no existe, no hace nada y el
comportamiento es el de siempre.

Tabla (se crea una vez en el editor SQL de Supabase):

    create table if not exists dashboard_snapshots (
        key text primary key,
        saved_unix double precision not null,
        payload text not null,
        updated_at timestamptz not null default now()
    );
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
import threading
import time
from typing import Any, Callable

from toolbox import cache as cache_module

logger = logging.getLogger("fantasy.snapshot_remote")

TABLE = "dashboard_snapshots"
# Tras un fallo de lectura no se vuelve a preguntar durante este tiempo: un GET
# sin foto no puede convertirse en una consulta a Supabase por cada petición.
RETRY_AFTER_SECONDS = 30.0

_client: Any = None
_client_lock = threading.Lock()
_last_miss: dict[str, float] = {}
_warned: set[str] = set()
# Las pruebas sustituyen la fábrica por un almacén local.
_client_factory: Callable[[], Any] | None = None


def enabled() -> bool:
    return _client_factory is not None or cache_module._use_remote(explicit_root=False)


def _get_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            if _client_factory is not None:
                _client = _client_factory()
            else:
                _client = cache_module.create_client(
                    os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_KEY"].strip()
                )
        return _client


def _reset_for_tests() -> None:
    global _client, _client_factory
    _client = None
    _client_factory = None
    _last_miss.clear()
    _warned.clear()


def snapshot_key(kind: str, league_dir: str) -> str:
    return f"{kind}:{league_dir}"


def _warn_once(what: str, exc: BaseException) -> None:
    if what in _warned:
        logger.debug("%s", what, exc_info=True)
        return
    _warned.add(what)
    logger.warning("%s: %s (¿existe la tabla %s en Supabase?)", what, exc, TABLE)


def _pack(envelope: dict[str, Any]) -> str:
    raw = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")


def _unpack(payload: str) -> dict[str, Any] | None:
    try:
        data = json.loads(gzip.decompress(base64.b64decode(payload)).decode("utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def save(kind: str, league_dir: str, envelope: dict[str, Any]) -> bool:
    """Sube la foto. ``False`` si no está activo o si falla (nunca lanza)."""
    if not enabled():
        return False
    saved = envelope.get("saved_unix")
    if not isinstance(saved, (int, float)) or isinstance(saved, bool):
        return False
    try:
        _get_client().table(TABLE).upsert(
            {
                "key": snapshot_key(kind, league_dir),
                "saved_unix": float(saved),
                "payload": _pack(envelope),
            },
            on_conflict="key",
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001 — la copia remota nunca tumba la descarga
        _warn_once("No se pudo copiar la foto a Supabase", exc)
        return False


def load(kind: str, league_dir: str) -> dict[str, Any] | None:
    """Sobre guardado (``value`` + ``saved_unix``) o ``None``. Nunca lanza."""
    if not enabled():
        return None
    key = snapshot_key(kind, league_dir)
    now = time.monotonic()
    if now - _last_miss.get(key, -RETRY_AFTER_SECONDS) < RETRY_AFTER_SECONDS:
        return None
    try:
        rows = _get_client().table(TABLE).select("payload").eq("key", key).execute().data or []
    except Exception as exc:  # noqa: BLE001
        _last_miss[key] = now
        _warn_once("No se pudo leer la foto de Supabase", exc)
        return None
    if not rows:
        _last_miss[key] = now
        return None
    envelope = _unpack(str(rows[0].get("payload") or ""))
    if envelope is None or not isinstance(envelope.get("value"), dict):
        _last_miss[key] = now
        return None
    return envelope

"""Copia en Supabase del histórico de medición (cuotas y xP por jornada).

Ese histórico vive en ``.cache/responses.sqlite``. Hay dos problemas:

* Render borra su disco en cada despliegue (y se despliega con cada commit).
* La foto del tablero se descarga en el PC con «Actualizar Fantasy», así que
  las cuotas se guardan en el SQLite del PC y Render nunca las ve.

Resultado: el informe del modelo en Render decía «0 partidos guardados» y
«sin cuotas» aunque el PC llevaba días guardándolas.

Aquí se sube una copia comprimida de esas tablas (reutiliza la tabla
``dashboard_snapshots`` de :mod:`toolbox.snapshot_remote`) y se fusiona fila a
fila al leer. La fusión nunca borra: une las dos copias y, para la misma
clave, se queda con la fila evaluada (``actual_points``) o, si no, la más
reciente (``stored_at``). Todo es a prueba de fallos: sin Supabase no hace nada.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from toolbox import snapshot_remote
from toolbox.cache import cache_root

logger = logging.getLogger("fantasy.history_remote")

KIND = "history"
KEY = "tables"
TABLES = (
    "odds_snapshots",
    "scorer_odds_snapshots",
    "matchday_snapshots",
    "matchday_snapshot_log",
    "previa_snapshots",
    # Foto previa al primer saque. La última captura anterior al cierre manda;
    # el que escribe ya no guarda nada después de ese saque.
    "pre_lock_snapshots",
)
# Ediciones congeladas: la primera guardada manda, nunca se reescribe.
KEEP_FIRST = {"previa_snapshots"}
# Una lectura remota por proceso cada este tiempo como mucho.
PULL_EVERY_SECONDS = 600.0

_lock = threading.Lock()
_last_pull = 0.0


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def _pk(conn: sqlite3.Connection, table: str) -> list[str]:
    cols = conn.execute(f"pragma table_info({table})").fetchall()
    return [row[1] for row in sorted((c for c in cols if c[5]), key=lambda c: c[5])]


def _dump(conn: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for table in TABLES:
        row = conn.execute("select sql from sqlite_master where type='table' and name=?", (table,)).fetchone()
        if not row:
            continue
        cur = conn.execute(f"select * from {table}")
        out[table] = {
            "schema": row[0],
            "columns": [d[0] for d in cur.description],
            "rows": [list(r) for r in cur.fetchall()],
        }
    return out


def _better(remote: dict[str, Any], local: dict[str, Any]) -> bool:
    """¿La fila remota debe sustituir a la local con la misma clave?"""
    if "actual_points" in remote:
        from toolbox.marcador import evaluacion_prematura

        if remote.get("actual_points") is not None and evaluacion_prematura(
            remote.get("kickoff"), remote.get("evaluated_at")
        ):
            # Puntos apuntados antes de ser definitivos (los 0 del Sevilla-Betis): no entran.
            return False
        r_eval = remote.get("actual_points") is not None
        l_eval = local.get("actual_points") is not None
        if r_eval != l_eval:
            return r_eval
    return float(remote.get("stored_at") or 0) > float(local.get("stored_at") or 0)


def merge_into(conn: sqlite3.Connection, dump: dict[str, Any]) -> int:
    """Fusiona una copia en ``conn``. Devuelve cuántas filas entraron o cambiaron."""
    changed = 0
    for table in TABLES:
        block = dump.get(table)
        if not isinstance(block, dict) or not block.get("rows"):
            continue
        conn.execute(str(block["schema"]).replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
        local_cols = [row[1] for row in conn.execute(f"pragma table_info({table})").fetchall()]
        remote_cols = list(block["columns"])
        cols = [c for c in remote_cols if c in local_cols]
        pk = _pk(conn, table)
        if not pk or not all(k in cols for k in pk):
            continue
        where = " and ".join(f"{k} = ?" for k in pk)
        placeholders = ",".join("?" for _ in cols)
        for values in block["rows"]:
            remote = dict(zip(remote_cols, values))
            current = conn.execute(
                f"select {','.join(cols)} from {table} where {where}", [remote[k] for k in pk]
            ).fetchone()
            if current is not None and (table in KEEP_FIRST or not _better(remote, dict(zip(cols, current)))):
                continue
            conn.execute(
                f"insert or replace into {table} ({','.join(cols)}) values ({placeholders})",
                [remote[c] for c in cols],
            )
            changed += 1
    conn.commit()
    return changed


def _remote_dump() -> dict[str, Any] | None:
    envelope = snapshot_remote.load(KIND, KEY)
    value = envelope.get("value") if envelope else None
    return value if isinstance(value, dict) else None


def pull(db: Path | None = None, *, force: bool = False) -> int:
    """Trae la copia remota y la fusiona en el SQLite local. Nunca lanza."""
    global _last_pull
    if not snapshot_remote.enabled():
        return 0
    with _lock:
        now = time.monotonic()
        if not force and _last_pull and now - _last_pull < PULL_EVERY_SECONDS:
            return 0
        _last_pull = now
        try:
            dump = _remote_dump()
            if not dump:
                return 0
            path = db or _db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            try:
                return merge_into(conn, dump)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 — sin copia remota el informe sigue
            logger.warning("No se pudo traer el histórico de Supabase: %s", exc)
            return 0


def push(db: Path | None = None) -> bool:
    """Fusiona lo remoto en local y sube la unión. Nunca lanza."""
    if not snapshot_remote.enabled():
        return False
    path = db or _db_path()
    if not path.is_file():
        return False
    try:
        with _lock:
            conn = sqlite3.connect(path)
            try:
                remote = _remote_dump()
                if remote:
                    merge_into(conn, remote)
                dump = _dump(conn)
            finally:
                conn.close()
        if not dump:
            return False
        return snapshot_remote.save(KIND, KEY, {"saved_unix": time.time(), "value": dump})
    except Exception as exc:  # noqa: BLE001 — la copia nunca tumba la descarga
        logger.warning("No se pudo subir el histórico a Supabase: %s", exc)
        return False

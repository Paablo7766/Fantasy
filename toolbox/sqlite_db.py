"""Una sola forma de abrir ``.cache/responses.sqlite``.

Quince módulos escriben en ese fichero, cada uno con su conexión y desde hilos
distintos (descarga, lecturas del panel, calibración, previa). En Render el
disco se borra en cada despliegue y la base nacía en el modo por defecto
(``journal_mode=delete``): mientras alguien escribe, nadie más lee ni escribe,
y a los 5 s de espera de ``sqlite3`` saltaba «database is locked» en la previa,
el informe del modelo, la memoria del plan y el registro del consejo. Con la
0,1 CPU del plan gratuito, una transacción larga dura fácilmente más de 5 s.

Aquí:

* **WAL**: los lectores no esperan a quien escribe y quien escribe no espera a
  los lectores. Es una propiedad del fichero: basta con fijarla una vez.
* **30 s de espera** si dos escriben a la vez, en vez de rendirse a los 5 s.
* ``synchronous=NORMAL``: con WAL es seguro ante un corte del proceso y ahorra
  un ``fsync`` por transacción.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

BUSY_TIMEOUT_SECONDS = 30.0

_wal_ready: set[str] = set()
_wal_lock = threading.Lock()


def _read_only(target: str, kwargs: dict[str, Any]) -> bool:
    return bool(kwargs.get("uri")) and "mode=ro" in target


def connect(path: str | Path, **kwargs: Any) -> sqlite3.Connection:
    """``sqlite3.connect`` con WAL y espera larga. Mismos argumentos."""
    timeout = kwargs.pop("timeout", None)
    kwargs["timeout"] = max(float(timeout or 0.0), BUSY_TIMEOUT_SECONDS)
    target = str(path)
    conn = sqlite3.connect(target, **kwargs)
    if target == ":memory:" or _read_only(target, kwargs):
        return conn
    if target not in _wal_ready:
        with _wal_lock:
            if target not in _wal_ready:
                try:
                    mode = conn.execute("pragma journal_mode=wal").fetchone()
                    if mode and str(mode[0]).lower() == "wal":
                        _wal_ready.add(target)
                except sqlite3.OperationalError:
                    # Base ocupada justo ahora: se intenta en la próxima conexión.
                    pass
    try:
        conn.execute("pragma synchronous=normal")
    except sqlite3.OperationalError:
        pass
    return conn

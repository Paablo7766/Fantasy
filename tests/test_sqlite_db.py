"""``responses.sqlite`` se abre en WAL y con espera larga: sin «database is locked»."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from toolbox import sqlite_db


def test_abre_en_wal_y_con_espera_larga(tmp_path: Path) -> None:
    db = tmp_path / "responses.sqlite"
    conn = sqlite_db.connect(db)
    try:
        assert conn.execute("pragma journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()
    # Un ``timeout`` menor que pida el que llama no recorta la espera.
    conn = sqlite_db.connect(db, timeout=2)
    conn.close()


def test_lector_no_espera_a_quien_escribe(tmp_path: Path) -> None:
    db = tmp_path / "responses.sqlite"
    writer = sqlite_db.connect(db)
    writer.execute("create table t (k integer primary key, v text)")
    writer.commit()
    writer.execute("insert into t values (1, 'a')")  # transacción abierta, sin commit
    reader = sqlite_db.connect(db)
    started = time.monotonic()
    assert reader.execute("select count(*) from t").fetchone()[0] == 0
    assert time.monotonic() - started < 1.0
    writer.commit()
    reader.close()
    writer.close()


def test_segundo_escritor_espera_en_vez_de_fallar(tmp_path: Path) -> None:
    db = tmp_path / "responses.sqlite"
    first = sqlite_db.connect(db)
    first.execute("create table t (k integer primary key)")
    first.commit()
    first.execute("insert into t values (1)")  # bloqueo de escritura tomado
    errors: list[Exception] = []

    def second_writer() -> None:
        conn = sqlite_db.connect(db)
        try:
            conn.execute("insert into t values (2)")
            conn.commit()
        except sqlite3.OperationalError as exc:  # pragma: no cover - es el fallo a evitar
            errors.append(exc)
        finally:
            conn.close()

    thread = threading.Thread(target=second_writer)
    thread.start()
    time.sleep(6)  # más que los 5 s por defecto de sqlite3
    first.commit()
    thread.join(timeout=10)
    first.close()
    assert not errors
    check = sqlite3.connect(db)
    assert check.execute("select count(*) from t").fetchone()[0] == 2
    check.close()

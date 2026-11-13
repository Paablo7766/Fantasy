"""La foto previa al saque se reescribe hasta el cierre y ahí se queda."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from toolbox.pre_lock import freeze_pre_lock, leer

KICKOFF = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)
ANTES = datetime(2026, 11, 11, 21, 0, tzinfo=timezone.utc)
DESPUES = datetime(2026, 11, 20, 20, 1, tzinfo=timezone.utc)


def _odds() -> dict:
    return {
        "athletic|espanyol": {
            "source": "oddspapi",
            "kickoff": "2026-11-20T20:00:00+00:00",
            "odds_1x2": (2.1, 3.3, 3.6),
            "anytime_scorers": [{"name": "Alex Berenguer", "price": 3.4, "suspended": True}],
        }
    }


def _players() -> list[dict]:
    return [{"player_id": "1", "name": "Uno", "p_titular": 0.7, "own_expected_points": 6.2, "price": 12}]


def test_rewrites_until_kickoff_and_then_refuses(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    lock = (13, KICKOFF)
    first = freeze_pre_lock(_players(), _odds(), now=ANTES, conn=conn, lock=lock)
    assert first["wrote"] and first["jornada"] == 13 and first["scorers"] == 1
    later = freeze_pre_lock(
        [{"player_id": "1", "p_titular": 0.4, "own_expected_points": 4.0}],
        _odds(),
        now=datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc),
        conn=conn,
        lock=lock,
    )
    assert later["wrote"]
    saved = leer(13, conn=conn)
    assert saved is not None
    assert saved["payload"]["players"][0]["p_titular"] == 0.4
    assert saved["payload"]["players"][0]["p_titular_prod"] is None
    assert saved["payload"]["players"][0]["p_titular_reajuste"] is None
    assert saved["payload"]["scorers"][0]["suspended"] is True
    closed = freeze_pre_lock(_players(), _odds(), now=DESPUES, conn=conn, lock=lock)
    assert closed["wrote"] is False
    assert leer(13, conn=conn)["payload"]["players"][0]["p_titular"] == 0.4

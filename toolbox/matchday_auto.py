"""Snapshot y evaluate automáticos de E[pts] usando el tablero ya cargado."""

from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root, madrid_day

_AUTO_STAMP: dict[str, float] = {}
_AUTO_COOLDOWN_SECONDS = 3600.0


def _load_track():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "track_matchday.py"
    spec = importlib.util.spec_from_file_location("track_matchday", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar scripts/track_matchday.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def _needs_snapshot(conn: sqlite3.Connection, jornada_id: str, day: str) -> bool:
    row = conn.execute(
        """
        select count(*) from matchday_snapshots
        where jornada_id = ? and snapshot_day = ?
        """,
        (jornada_id, day),
    ).fetchone()
    return int(row[0] if row else 0) == 0


def _pending_jornadas(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        select jornada_id
        from matchday_snapshots
        group by jornada_id
        having sum(case when actual_points is null then 1 else 0 end) > 0
        order by cast(jornada_id as integer), jornada_id
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def auto_track_from_board(board: dict[str, Any]) -> dict[str, Any]:
    """
    Sin red extra: usa squads/trends/market del tablero.
    - 1 snapshot / jornada / día (Europe/Madrid).
    - Evaluate de jornadas con puntos reales ya en plantilla/trends.
    """
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    market = board.get("market") if isinstance(board.get("market"), dict) else None
    if squads is None or trends is None or squads.get("ok") is not True:
        return {"ok": False, "reason": "tablero_incompleto"}

    league_id = trends.get("league_id") if isinstance(trends.get("league_id"), str) else None
    day = madrid_day()
    cache_key = f"{league_id or '_'}:{day}"
    last = _AUTO_STAMP.get(cache_key, 0.0)
    if time.time() - last < _AUTO_COOLDOWN_SECONDS:
        return {"ok": True, "skipped": True, "reason": "cooldown", "cooldown_sec": _AUTO_COOLDOWN_SECONDS}

    track = _load_track()
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    result: dict[str, Any] = {"ok": True, "skipped": False, "snapshot": None, "evaluated": []}
    try:
        track._ensure_schema(conn)
        jornada = track.infer_jornada_id(trends, squads)
        if _needs_snapshot(conn, jornada, day):
            snap = track.run_snapshot(
                conn,
                league=league_id,
                jornada_id=jornada,
                fresh=False,
                squads=squads,
                trends=trends,
                market=market if isinstance(market, dict) else None,
            )
            result["snapshot"] = {
                "jornada_id": snap.get("jornada_id"),
                "written": snap.get("written"),
                "snapshot_day": day,
            }

        for jornada_id in _pending_jornadas(conn):
            report = track.run_evaluate(
                conn,
                league=league_id,
                jornada_id=jornada_id,
                fresh=False,
                squads=squads,
                trends=trends,
                catalog=None,
            )
            if report.get("ok") and (report.get("scored") or 0) > 0:
                result["evaluated"].append(
                    {
                        "jornada_id": jornada_id,
                        "scored": report.get("scored"),
                        "mae": report.get("mae"),
                    }
                )
    finally:
        conn.close()

    _AUTO_STAMP[cache_key] = time.time()
    return result

"""Validación empírica E[Pts]: snapshot y evaluate, sin red."""

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _load_track():
    path = ROOT / "scripts" / "track_matchday.py"
    spec = importlib.util.spec_from_file_location("track_matchday", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


track = _load_track()


def _player(
    player_id: str,
    position: str,
    *,
    expected: float | None = 6.0,
    ceiling: float | None = 10.0,
    matchday: int = 9,
    name: str | None = None,
) -> dict:
    payload = {
        "player_id": player_id,
        "name": name or player_id,
        "nickname": name or player_id,
        "position": position,
        "club": "Club",
        "p_titular": 0.9,
        "form": {"xg": 1.0, "xa": 0.4, "minutes": 720, "starts": 8},
    }
    if expected is not None:
        payload["own_expected_points"] = expected
    if ceiling is not None:
        payload["own_ceiling_points"] = ceiling
    payload["own_calendar"] = [{"matchday": matchday, "opponent": "RIVAL"}]
    return payload


def _squad(players: list[dict], *, cash: int = 1_000_000) -> dict:
    return {
        "team_id": "1",
        "is_self": True,
        "manager_name": "Yo",
        "cash": cash,
        "players": players,
        "error": None,
    }


def _full_squad() -> list[dict]:
    players = [_player("por", "POR", expected=4.0, ceiling=7.0)]
    for index in range(1, 6):
        players.append(_player(f"def{index}", "DEF", expected=5.0 + index * 0.2, ceiling=9.0))
    for index in range(1, 6):
        players.append(_player(f"mc{index}", "MC", expected=6.0 + index * 0.1, ceiling=11.0))
    for index in range(1, 4):
        players.append(_player(f"del{index}", "DEL", expected=8.0 + index, ceiling=14.0))
    return players


def _docs(players: list[dict]) -> tuple[dict, dict]:
    squads = {"ok": True, "league_id": "7", "squads": [_squad(players)]}
    trends = {"ok": True, "players": [dict(row) for row in players]}
    return squads, trends


class TrackMatchdayTest(unittest.TestCase):
    def test_infers_jornada_from_own_calendar_mode(self) -> None:
        players = _full_squad()
        players[0]["own_calendar"] = [{"matchday": 10}]
        _squads, trends = _docs(players)
        self.assertEqual(track.infer_jornada_id(trends), "9")

    def test_snapshot_writes_expected_ceiling_and_xi_flag(self) -> None:
        squads, trends = _docs(_full_squad())
        jornada, rows, meta = track.snapshot_rows_from_documents(squads, trends, jornada_id="9")
        self.assertEqual(jornada, "9")
        self.assertEqual(len(rows), 14)
        self.assertEqual(meta["xi_count"], 11)
        xi = {row["player_id"] for row in rows if row["in_once_optimo"]}
        self.assertEqual(len(xi), 11)
        por = next(row for row in rows if row["player_id"] == "por")
        self.assertEqual(por["expected_points"], 4.0)
        self.assertEqual(por["ceiling_points"], 7.0)

    def test_evaluate_mae_ceiling_break_and_xi_total(self) -> None:
        squads, trends = _docs(_full_squad())
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "responses.sqlite"
            conn = sqlite3.connect(db)
            try:
                snap = track.run_snapshot(conn, jornada_id="9", squads=squads, trends=trends, market={})
                self.assertTrue(snap["ok"])
                xi_ids = {row["player_id"] for row in snap["rows"] if row["in_once_optimo"]}
                catalog = []
                for row in snap["rows"]:
                    # por techo=7 → 8 rompe P90; el resto queda bajo techo.
                    actual = 8.0 if row["player_id"] == "por" else 5.0
                    catalog.append(
                        {
                            "id": row["player_id"],
                            "playerMaster": {
                                "id": row["player_id"],
                                "lastStats": [{"weekNumber": 9, "totalPoints": actual}],
                            },
                        }
                    )
                report = track.run_evaluate(
                    conn,
                    jornada_id="9",
                    squads=squads,
                    trends=trends,
                    catalog=catalog,
                )
            finally:
                conn.close()
        self.assertTrue(report["ok"])
        self.assertEqual(report["scored"], 14)
        self.assertIsNotNone(report["mae"])
        self.assertGreater(report["mae"], 0)
        self.assertEqual(report["ceiling_breaks"], 1)
        self.assertAlmostEqual(report["ceiling_break_rate"], 1 / 14, places=4)
        self.assertEqual(report["xi_scored"], 11)
        self.assertIn("por", xi_ids)
        self.assertEqual(report["xi_actual_points"], 8.0 + 5.0 * 10)

    def test_week_points_map_reads_last_stats(self) -> None:
        mapping = track.week_points_by_round(
            {"playerMaster": {"lastStats": [{"weekNumber": 8, "totalPoints": 2}, {"weekNumber": 9, "weekPoints": 7}]}}
        )
        self.assertEqual(mapping, {"8": 2.0, "9": 7.0})

    def test_cli_requires_mode(self) -> None:
        with self.assertRaises(SystemExit):
            track.build_parser().parse_args([])

    def test_evaluate_without_snapshot_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "responses.sqlite"
            conn = sqlite3.connect(db)
            try:
                report = track.run_evaluate(conn, squads={}, trends={}, catalog=[])
            finally:
                conn.close()
        self.assertFalse(report["ok"])

    def test_cli_snapshot_uses_injected_runner(self) -> None:
        squads, trends = _docs(_full_squad())
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            buf = StringIO()
            with (
                patch.object(track, "_load_live_documents", return_value=(squads, {}, trends, [])),
                patch("sys.stdout", buf),
            ):
                code = track.main(["--snapshot", "--jornada", "9", "--db", str(db)])
            self.assertEqual(code, 0)
            conn = sqlite3.connect(db)
            try:
                count = conn.execute("select count(*) from matchday_snapshots").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 14)
            self.assertIn("Snapshot jornada 9", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

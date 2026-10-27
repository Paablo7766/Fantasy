"""Auto snapshot/evaluate desde tablero."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from toolbox.matchday_auto import auto_track_from_board


class MatchdayAutoTests(unittest.TestCase):
    def test_skips_without_squads(self) -> None:
        out = auto_track_from_board({"trends": {"ok": True, "players": []}})
        self.assertFalse(out.get("ok"))

    def test_snapshot_from_minimal_board(self) -> None:
        players = []
        for index in range(11):
            players.append(
                {
                    "player_id": f"p{index}",
                    "name": f"P{index}",
                    "nickname": f"P{index}",
                    "position": "MC" if index else "POR",
                    "own_expected_points": 5.0,
                    "own_ceiling_points": 9.0,
                    "own_calendar": [{"matchday": 12}],
                }
            )
        squads = {
            "ok": True,
            "league_id": "L1",
            "squads": [
                {
                    "team_id": "1",
                    "is_self": True,
                    "cash": 1_000_000,
                    "players": players,
                }
            ],
        }
        trends = {"ok": True, "league_id": "L1", "players": players}
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "responses.sqlite"
            # ``FANTASY_OFFLINE=1``: el tablero ya trae squads y tendencias, así
            # que la titularidad no debe salir a FútbolFantasy. El air-gap de
            # ``LALIGA_ENV`` solo cubre LaLiga; sin esto la prueba abría un
            # socket real y ``conftest._no_real_sockets`` la abortaba.
            with patch("toolbox.matchday_auto._db_path", return_value=db), patch(
                "toolbox.matchday_auto._AUTO_COOLDOWN_SECONDS", 0.0
            ), patch.dict(os.environ, {"FANTASY_OFFLINE": "1"}):
                first = auto_track_from_board({"squads": squads, "trends": trends, "market": {"ok": True}})
                self.assertTrue(first.get("ok"))
                self.assertIsNotNone(first.get("snapshot"))
                conn = sqlite3.connect(db)
                count = conn.execute("select count(*) from matchday_snapshots").fetchone()[0]
                conn.close()
                self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()

"""Registro diario de puntos y señales de precio."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from toolbox.signal_log import TABLE, record_signal_log


class SignalLogTests(unittest.TestCase):
    def test_one_row_per_player_and_day_is_rewritten(self) -> None:
        players = [
            {
                "player_id": "p1",
                "fantasy_price": 3_000_000,
                "market_value_change": 50_000,
                "week_points": [2, 12],
                "af_predicted_delta": 40_000,
                "own_expected_points": 4.2,
            },
            {"player_id": "p2", "market_value": 9_000_000},
            {"name": "sin id"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            self.assertEqual(record_signal_log(players, league_id="L", day="2026-11-02", path=path), 2)
            players[0]["week_points"] = [2, 12, 3]
            self.assertEqual(record_signal_log(players, league_id="L", day="2026-11-02", path=path), 2)
            conn = sqlite3.connect(path)
            rows = conn.execute(
                f"select player_id, price, last_points, af_predicted_delta from {TABLE} order by player_id"
            ).fetchall()
            conn.close()
        self.assertEqual(rows, [("p1", 3_000_000, 3.0, 40_000.0), ("p2", 9_000_000, None, None)])

    def test_no_day_or_no_players_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            self.assertEqual(record_signal_log([{"player_id": "p"}], league_id=None, day=None, path=path), 0)
            self.assertEqual(record_signal_log([], league_id=None, day="2026-11-02", path=path), 0)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

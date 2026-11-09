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

    def test_guarda_xp_de_af_y_del_modelo_y_migra_tablas_viejas(self) -> None:
        players = [{"player_id": "p1", "af_expected_points": 8.8, "own_xp_modelo": 4.1, "own_expected_points": 8.2}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            conn = sqlite3.connect(path)
            conn.execute(f"create table {TABLE} (player_id text not null, day text not null, league_id text, price integer, "
                         "market_value_change integer, last_points real, af_predicted_delta real, af_price_delta real, "
                         "own_predicted_delta real, own_expected_points real, stored_at real not null, primary key (player_id, day))")
            conn.commit()
            conn.close()
            self.assertEqual(record_signal_log(players, league_id="L", day="2026-11-03", path=path), 1)
            conn = sqlite3.connect(path)
            row = conn.execute(f"select af_expected_points, own_xp_modelo, own_expected_points from {TABLE}").fetchone()
            conn.close()
        self.assertEqual(row, (8.8, 4.1, 8.2))

    def test_guarda_la_titularidad_de_cada_fuente(self) -> None:
        players = [
            {"player_id": "ff", "p_titular": 0.85, "p_titular_source": "scraper", "af_p_titular": 70, "lineup_status": "titular"},
            {"player_id": "solo_af", "p_titular": 0.4, "p_titular_source": "analiticafantasy_market", "af_p_titular": 0.4},
            {"player_id": "crudo", "startProbability": 60, "p_titular": 0.1, "p_titular_source": "scraper", "lineupStatus": "duda"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            self.assertEqual(record_signal_log(players, league_id="L", day="2026-11-07", path=path), 3)
            conn = sqlite3.connect(path)
            rows = conn.execute(
                f"select player_id, p_titular_ff, p_titular_af, p_titular_final, p_titular_fuente, lineup_status "
                f"from {TABLE} order by player_id"
            ).fetchall()
            conn.close()
        self.assertEqual(
            rows,
            [
                ("crudo", 0.6, None, 0.1, "scraper", "duda"),
                ("ff", 0.85, 0.7, 0.85, "scraper", "titular"),
                ("solo_af", None, 0.4, 0.4, "analiticafantasy_market", None),
            ],
        )

    def test_guarda_el_parte_oficial_y_deriva_el_cambio_de_precio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            ayer = [
                {"player_id": "a", "fantasy_price": 10_000_000, "player_status": "ok"},
                {"player_id": "b", "fantasy_price": 5_000_000},
                {"player_id": "c", "fantasy_price": 2_000_000},
            ]
            hoy = [
                {"player_id": "a", "fantasy_price": 10_400_000, "player_status": "injured"},
                {"player_id": "b", "fantasy_price": 4_900_000},
                {"player_id": "d", "fantasy_price": 1_000_000},
            ]
            record_signal_log(ayer, league_id="L", day="2026-11-06", path=path)
            record_signal_log(hoy, league_id="L", day="2026-11-07", path=path)
            # Hueco de un día: el 9 no tiene el 8, así que no hay cambio derivado.
            record_signal_log(hoy, league_id="L", day="2026-11-09", path=path)
            conn = sqlite3.connect(path)
            rows = conn.execute(
                f"select player_id, day, player_status, price_change_derived from {TABLE} "
                "where day >= '2026-11-07' order by day, player_id"
            ).fetchall()
            conn.close()
        self.assertEqual(
            rows,
            [
                ("a", "2026-11-07", "injured", 400_000),
                ("b", "2026-11-07", None, -100_000),
                ("d", "2026-11-07", None, None),
                ("a", "2026-11-09", "injured", None),
                ("b", "2026-11-09", None, None),
                ("d", "2026-11-09", None, None),
            ],
        )

    def test_no_day_or_no_players_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            self.assertEqual(record_signal_log([{"player_id": "p"}], league_id=None, day=None, path=path), 0)
            self.assertEqual(record_signal_log([], league_id=None, day="2026-11-02", path=path), 0)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

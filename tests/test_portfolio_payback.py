"""Amortización de la cartera: puntos desde la compra y caja que generan."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from toolbox.portfolio import (
    attach_points,
    build_portfolio,
    current_round,
    points_while_owned,
    round_points,
    round_start,
)

# Miércoles: la última jornada con puntos es la del fin de semana pasado.
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class PaybackTests(unittest.TestCase):
    def test_round_start_is_friday_counting_back(self) -> None:
        self.assertEqual(round_start(10, 10, NOW), datetime(2026, 10, 30, tzinfo=timezone.utc))
        self.assertEqual(round_start(9, 10, NOW), datetime(2026, 10, 23, tzinfo=timezone.utc))

    def test_round_points_merges_and_first_wins(self) -> None:
        merged = round_points({"9": 4, "10": 6}, {"8": 2, "9": 99, "x": 1, "7": True})
        self.assertEqual(merged, {8: 2.0, 9: 4.0, 10: 6.0})
        self.assertEqual(current_round([merged, {11: 1.0}]), 11)

    def test_points_only_after_purchase(self) -> None:
        rounds = {8: 2.0, 9: 4.0, 10: 6.0}
        out = points_while_owned(rounds, "2026-10-20T09:00:00+00:00", 10, NOW)
        self.assertEqual(out["points_total"], 12.0)
        self.assertEqual(out["points_owned"], 10.0)
        self.assertEqual(out["rounds_owned"], 2)
        self.assertTrue(out["points_owned_estimated"])

    def test_initial_squad_owns_every_round(self) -> None:
        out = points_while_owned({1: 3.0, 2: 5.0}, None, 2, NOW)
        self.assertEqual(out["points_owned"], 8.0)
        self.assertFalse(out["points_owned_estimated"])

    def test_attach_points_uses_latest_round_of_all_players(self) -> None:
        players = [
            {"player_id": "a", "acquired_at": "2026-10-20T09:00:00Z"},
            {"player_id": "b", "acquired_at": None},
        ]
        attach_points(players, {"a": {9: 4.0, 10: 6.0}, "b": {1: 3.0}}, NOW)
        self.assertEqual(players[0]["points_owned"], 10.0)
        self.assertEqual(players[1]["points_owned"], 3.0)

    def test_build_portfolio_attaches_points(self) -> None:
        ledger = {"events": [{"kind": "buy", "amount_eur": 1_000_000, "player_id": "a", "at": "2026-10-20T09:00:00Z"}]}
        doc = build_portfolio([{"player_id": "a", "market_value": 1_200_000}], ledger, rounds_by_player={"a": {10: 7.0}})
        self.assertEqual(doc["players"][0]["points_total"], 7.0)
        self.assertIn("points_owned", doc["players"][0])


if __name__ == "__main__":
    unittest.main()

"""Contrato JSON de subasta v2 en el tablero."""

from __future__ import annotations

import unittest

from server import _normalize_market_decision


class ServerAuctionFieldsTests(unittest.TestCase):
    def test_normalize_preserves_auction_v2_keys(self) -> None:
        row = _normalize_market_decision(
            {
                "player_id": "p1",
                "optimal_bid_eur": 1_200_000,
                "win_probability": 0.6123,
                "intrinsic_valuation_eur": 1_450_000,
                "expected_surplus_eur": 95_000,
                "rival_knockout_targets": ["Ana", ""],
                "intent": "FLIP",
            }
        )
        self.assertEqual(row["optimal_bid_eur"], 1_200_000)
        self.assertEqual(row["win_probability"], 0.6123)
        self.assertEqual(row["intrinsic_valuation_eur"], 1_450_000)
        self.assertEqual(row["expected_surplus_eur"], 95_000)
        self.assertEqual(row["rival_knockout_targets"], ["Ana"])
        self.assertEqual(row["bid_intent"], "FLIP")
        self.assertEqual(row["intent"], "FLIP")


if __name__ == "__main__":
    unittest.main()

"""Rentabilidad y perfiles de actividad."""

from __future__ import annotations

import unittest

from toolbox.portfolio import (
    build_portfolio,
    holdings_from_events,
    ledger_for_squad,
    ledger_index,
    realized_from_events,
    team_activity_profile,
)


class PortfolioTests(unittest.TestCase):
    def test_holdings_replace_on_resell(self) -> None:
        events = [
            {"kind": "buy", "amount_eur": 1_000_000, "player_id": "p1", "at": "2026-01-01T10:00:00+00:00"},
            {"kind": "sell", "amount_eur": 1_200_000, "player_id": "p1", "at": "2026-02-01T10:00:00+00:00"},
            {"kind": "clause", "amount_eur": 2_500_000, "player_id": "p1", "at": "2026-03-01T10:00:00+00:00"},
        ]
        holdings = holdings_from_events(events)
        self.assertEqual(holdings["p1"]["cost_eur"], 2_500_000)
        self.assertEqual(holdings["p1"]["acquisition_kind"], "clausula")

    def test_build_portfolio_gain(self) -> None:
        ledger = {
            "events": [
                {"kind": "buy", "amount_eur": 1_000_000, "player_id": "a", "at": "2026-01-01T10:00:00+00:00", "signed_eur": -1_000_000},
            ]
        }
        players = [{"player_id": "a", "nickname": "Alpha", "market_value": 1_300_000}]
        doc = build_portfolio(players, ledger, {"a": "Alpha"})
        self.assertEqual(doc["summary"]["gain_eur"], 300_000)
        self.assertAlmostEqual(doc["summary"]["roi"], 0.3)
        self.assertEqual(doc["players"][0]["cost_eur"], 1_000_000)

    def test_unknown_cost_when_no_event(self) -> None:
        doc = build_portfolio([{"player_id": "x", "market_value": 500_000}], {"events": []}, {})
        self.assertIsNone(doc["players"][0]["cost_eur"])
        self.assertIsNone(doc["summary"]["gain_eur"])

    def test_ledger_lookup_by_manager_id(self) -> None:
        ledgers = ledger_index(
            [
                {
                    "team_id": "999",
                    "events": [{"kind": "buy", "amount_eur": 1, "player_id": "p", "at": "2026-01-01T10:00:00+00:00"}],
                }
            ]
        )
        squad = {"team_id": "44", "manager_id": "999"}
        found = ledger_for_squad(squad, ledgers)
        assert found is not None
        self.assertEqual(found["team_id"], "999")

    def test_team_activity_profile(self) -> None:
        ledger = {
            "initial_budget_eur": 100_000_000,
            "premiums_eur": 1_000_000,
            "purchases_eur": 5_000_000,
            "clauses_eur": 2_000_000,
            "sales_eur": 1_000_000,
            "events": [
                {"kind": "buy", "amount_eur": 500_000, "player_id": "p", "at": "2026-01-02T10:00:00+00:00", "signed_eur": -500_000},
            ],
        }
        profile = team_activity_profile(ledger, {"p": "Pepe"})
        assert profile is not None
        self.assertEqual(profile["net_outflow_eur"], 6_000_000)
        self.assertEqual(profile["recent_events"][0]["player_name"], "Pepe")
        self.assertIsNone(profile["realized_gain_eur"])

    def test_realized_gain_from_sale(self) -> None:
        events = [
            {"kind": "buy", "amount_eur": 1_000_000, "player_id": "p1", "at": "2026-01-01T10:00:00+00:00"},
            {"kind": "sell", "amount_eur": 1_400_000, "player_id": "p1", "at": "2026-02-01T10:00:00+00:00"},
        ]
        realized = realized_from_events(events)
        self.assertEqual(realized["realized_gain_eur"], 400_000)
        self.assertEqual(realized["priced_sales"], 1)
        self.assertEqual(realized["sale_count"], 1)


if __name__ == "__main__":
    unittest.main()

"""Motor propio: puja, Poisson, E[pts] y snapshots. Sin red."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from toolbox.cache import PriceSnapshotStore, madrid_day
from toolbox.market_intel import build_market_decisions
from toolbox.own_intel import (
    compute_bids,
    compute_market_signal,
    deltas_from_history,
    expected_opta_points,
    match_outcome_probs,
    markets_until_kickoff,
    persist_and_apply_own_intel,
    project_rate,
    recommendation_pct,
)
from toolbox.understat import FixtureInfo, TeamStrength


class ProjectRateTests(unittest.TestCase):
    def test_needs_min_history(self) -> None:
        self.assertIsNone(project_rate([1, 2]))

    def test_outlier_falls_back_to_mean(self) -> None:
        deltas = [100_000, 110_000, 90_000, 105_000, 2_000_000]
        rate = project_rate(deltas, today_delta=2_000_000)
        self.assertIsNotNone(rate)
        assert rate is not None
        self.assertLess(abs(rate), 500_000)


class BidTests(unittest.TestCase):
    def test_rising_ideal_below_max(self) -> None:
        ideal, maximum = compute_bids(price=10_000_000, rate=200_000, days=6)
        self.assertGreaterEqual(ideal, 10_000_000)
        self.assertGreaterEqual(maximum, ideal)

    def test_falling_ideal_is_price(self) -> None:
        ideal, maximum = compute_bids(price=10_000_000, rate=-150_000, days=4, falling=True)
        self.assertEqual(ideal, 10_000_000)
        self.assertGreaterEqual(maximum, ideal)

    def test_unavailable_both_equal_price(self) -> None:
        ideal, maximum = compute_bids(price=8_000_000, rate=300_000, days=5, unavailable=True)
        self.assertEqual(ideal, 8_000_000)
        self.assertEqual(maximum, 8_000_000)


class SignalTests(unittest.TestCase):
    def test_up_and_strength(self) -> None:
        direction, strength, predicted = compute_market_signal(
            rate=200_000,
            today_delta=250_000,
            universe_abs=[100_000, 200_000, 300_000],
        )
        self.assertEqual(direction, "up")
        self.assertGreater(strength, 0)
        self.assertGreater(predicted, 0)


class PoissonTests(unittest.TestCase):
    def test_favorite_wins_more(self) -> None:
        probs = match_outcome_probs(2.2, 0.8)
        self.assertGreater(probs["win"], probs["loss"])
        rec = recommendation_pct(probs["win"], probs["draw"], probs["expected_diff"])
        self.assertGreaterEqual(rec, 50)


class PointsTests(unittest.TestCase):
    def test_expected_points_present(self) -> None:
        result = expected_opta_points(
            position="DEL",
            p_titular=0.9,
            player_xg=8.0,
            player_xa=4.0,
            team_lambda=1.8,
            opp_lambda=1.0,
            team_avg_xg=1.6,
            home=True,
            fdr=4,
        )
        self.assertIsNotNone(result["expected_points"])
        self.assertIsNotNone(result["ceiling_points"])
        self.assertGreater(float(result["ceiling_points"] or 0), float(result["expected_points"] or 0))
        self.assertGreater(float(result["goal_probability"] or 0), 0)


class SnapshotStoreTests(unittest.TestCase):
    def test_upsert_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PriceSnapshotStore(root=Path(tmp))
            day = madrid_day()
            written = store.upsert_price_snapshots(
                [
                    {
                        "player_id": "p1",
                        "day": day,
                        "league_id": "L1",
                        "market_value": 5_000_000,
                        "market_value_change": 100_000,
                    }
                ]
            )
            self.assertEqual(written, 1)
            hist = store.price_history("p1", days=7)
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["market_value"], 5_000_000)
            # Idempotent same day
            store.upsert_price_snapshots(
                [
                    {
                        "player_id": "p1",
                        "day": day,
                        "league_id": "L1",
                        "market_value": 5_100_000,
                        "market_value_change": 100_000,
                    }
                ]
            )
            hist2 = store.price_history("p1", days=7)
            self.assertEqual(len(hist2), 1)
            self.assertEqual(hist2[0]["market_value"], 5_100_000)


class ApplyOwnIntelTests(unittest.TestCase):
    def test_snapshot_day_follows_capture_not_process_clock(self) -> None:
        """El día del snapshot es el de la captura, no el del proceso.

        En air-gap se sirve una copia del 24-oct mientras el proceso corre el 25.
        Sellar con hoy grababa dos días con el mismo valor y el motor leía una
        subida de 0 € que nunca ocurrió (Moleiro: 84.119.939 € dos días
        seguidos, cuando la app oficial marcaba +514.000 €).
        """
        from datetime import datetime, timezone

        from toolbox.own_intel import snapshot_rows_from_players
        from toolbox.scrapers import _snapshot_day

        captured = datetime(2026, 10, 24, 18, 38, tzinfo=timezone.utc).timestamp()
        market = {
            "source_stored_at": captured,
            "source_age_seconds": 60.0,
            "listings": [],
        }
        day = _snapshot_day(market)
        self.assertEqual(day, "2026-10-24")

        players = [
            {
                "player_id": "3086",
                "nickname": "Moleiro",
                "market_value": 84_119_939,
                "fantasy_price": 84_119_939,
            }
        ]
        rows = snapshot_rows_from_players(players, league_id="L1", day=day)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["day"], "2026-10-24")
        self.assertEqual(rows[0]["market_value"], 84_119_939)

    def test_snapshot_day_missing_stamp_falls_back_to_today(self) -> None:
        """Sin sello de captura se mantiene el comportamiento anterior."""
        from toolbox.own_intel import snapshot_rows_from_players
        from toolbox.scrapers import _snapshot_day

        self.assertIsNone(_snapshot_day(None))
        self.assertIsNone(_snapshot_day({"listings": []}))
        players = [
            {
                "player_id": "p1",
                "market_value": 1_000,
                "fantasy_price": 1_000,
            }
        ]
        rows = snapshot_rows_from_players(players, league_id="L1", day=None)
        self.assertEqual(rows[0]["day"], madrid_day())

    def test_applies_with_history_and_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = PriceSnapshotStore(root=root)
            today = datetime.now(timezone.utc).date()
            for i in range(5):
                day = (today - timedelta(days=4 - i)).isoformat()
                store.upsert_price_snapshots(
                    [
                        {
                            "player_id": "p1",
                            "day": day,
                            "league_id": "L1",
                            "market_value": 10_000_000 + i * 150_000,
                            "market_value_change": 150_000,
                        }
                    ]
                )
            kickoff = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
            fixtures = {
                "real madrid": FixtureInfo(
                    opponent="Sevilla",
                    opponent_id="2",
                    home=True,
                    kickoff=kickoff,
                    fdr=4,
                    opponent_xga=1.4,
                    opponent_xg=1.1,
                )
            }
            strengths = {
                "real madrid": TeamStrength("1", "Real Madrid", 1.9, 0.9, 10),
                "sevilla": TeamStrength("2", "Sevilla", 1.1, 1.4, 10),
            }
            players = [
                {
                    "player_id": "p1",
                    "name": "Test",
                    "club": "Real Madrid",
                    "position": "DEL",
                    "fantasy_price": 10_600_000,
                    "market_value_change": 150_000,
                    "p_titular": 0.85,
                    "form": {"xg": 6.0, "xa": 2.0},
                }
            ]
            summary = persist_and_apply_own_intel(
                players,
                league_id="L1",
                fixtures_by_club=fixtures,
                strengths=strengths,
                store=store,
            )
            self.assertTrue(summary["sources"]["own_intel_bids"]["ok"])
            self.assertIn("own_ideal_bid", players[0])
            self.assertIn("own_expected_points", players[0])
            self.assertIn("own_calendar", players[0])
            self.assertEqual(players[0]["own_market_signal"], "up")


class MarketIntelOwnCascadeTests(unittest.TestCase):
    def test_own_bid_preferred_over_af(self) -> None:
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        market = {
            "ok": True,
            "league_id": "L1",
            "listings": [
                {
                    "player_id": "p1",
                    "name": "P1",
                    "nickname": "P1",
                    "position": "MC",
                    "club": "Test",
                    "sale_price": 1_000_000,
                    "seller_team_id": "rival",
                }
            ],
        }
        trends = {
            "ok": True,
            "players": [
                {
                    "player_id": "p1",
                    "name": "P1",
                    "position": "MC",
                    "matching_confidence": 0.95,
                    "own_ideal_bid": 1_500_000,
                    "own_max_bid": 1_800_000,
                    "af_ideal_bid": 900_000,
                    "af_max_bid": 950_000,
                    "own_market_signal": "up",
                    "own_expected_points": 7.0,
                    "p_titular": 0.9,
                    "acceleration": 50_000,
                }
            ],
        }
        flip = {
            "ok": True,
            "cash_eur": 5_000_000,
            "matchday_void": False,
            "team_id": "self",
            "signings": [],
            "rejected": [],
        }
        doc = build_market_decisions(
            market,
            trends,
            flip,
            {"ok": True, "gaps": [], "market_fills": []},
            now=now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["price_band"], "bargain")
        self.assertEqual(row["own_ideal_bid"], 1_500_000)
        self.assertEqual(row["af_ideal_bid"], 900_000)
        self.assertEqual(row["ideal_bid"], 1_500_000)
        # El precio de venta ya supera el techo AF (950k). No se persigue.
        self.assertEqual(row["decision"], "ESPERAR")
        self.assertEqual(row["bid_limit"], "fuentes_no_coinciden")
        self.assertIsNone(row["suggested_bid"])

    def test_own_signal_works_with_low_matching(self) -> None:
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        market = {
            "ok": True,
            "listings": [
                {
                    "player_id": "p2",
                    "name": "P2",
                    "position": "MC",
                    "sale_price": 1_000_000,
                    "seller_team_id": "rival",
                }
            ],
        }
        trends = {
            "ok": True,
            "players": [
                {
                    "player_id": "p2",
                    "matching_confidence": 0.5,
                    "own_ideal_bid": 1_200_000,
                    "own_max_bid": 1_400_000,
                    "own_market_signal": "up",
                    "own_expected_points": 6.0,
                    "p_titular": 0.8,
                    "af_market_signal": "up",
                }
            ],
        }
        flip = {
            "ok": True,
            "cash_eur": 5_000_000,
            "matchday_void": False,
            "team_id": "self",
            "signings": [],
            "rejected": [],
        }
        doc = build_market_decisions(
            market,
            trends,
            flip,
            {"ok": True, "gaps": [], "market_fills": []},
            now=now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertIn("own_signal_up", row["motives"])
        self.assertNotIn("af_signal_up", row["motives"])


class MarketsUntilTests(unittest.TestCase):
    def test_days_until(self) -> None:
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        kickoff = (now + timedelta(days=3)).isoformat()
        self.assertEqual(markets_until_kickoff(kickoff, now=now), 3)


class DeltasTests(unittest.TestCase):
    def test_from_change_field(self) -> None:
        hist = [
            {"day": "2026-10-15", "market_value": 1_000_000, "market_value_change": 50_000},
            {"day": "2026-10-16", "market_value": 1_050_000, "market_value_change": 50_000},
            {"day": "2026-10-17", "market_value": 1_100_000, "market_value_change": 50_000},
        ]
        self.assertEqual(deltas_from_history(hist), [50_000, 50_000, 50_000])


if __name__ == "__main__":
    unittest.main()

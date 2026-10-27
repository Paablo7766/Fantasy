"""Subastas v2: perfilado Bayesiano y puja óptima."""

from __future__ import annotations

import unittest

from toolbox.bid_war import probability_of_winning_bid, solve_optimal_bid_v2
from toolbox.league_history import RivalProfile, fit_rival_profiles_eb


class FitRivalProfilesTests(unittest.TestCase):
    def test_shrinkage_pulls_sparse_manager_toward_league_prior(self) -> None:
        buys = []
        for index in range(6):
            buys.append(
                {
                    "team_id": "rich",
                    "amount_eur": 11_500_000,
                    "reference_value_eur": 10_000_000,
                    "cash_at_event_eur": 50_000_000,
                    "positional_urgency": 0.0,
                }
            )
        buys.append(
            {
                "team_id": "one-shot",
                "amount_eur": 20_000_000,
                "reference_value_eur": 10_000_000,
                "cash_at_event_eur": 30_000_000,
                "positional_urgency": 0.0,
            }
        )
        rivals_state = [
            {"team_id": "rich", "manager_name": "Rich", "cash_eur": 40_000_000, "thin_positions": ["MC"]},
            {"team_id": "one-shot", "manager_name": "One", "cash_eur": 25_000_000, "thin_positions": []},
            {"team_id": "cold", "manager_name": "Cold", "cash_eur": 5_000_000, "thin_positions": ["DEL"]},
        ]
        profiles = fit_rival_profiles_eb(buys, rivals_state, eb_shrinkage_k=3.0)
        self.assertIn("rich", profiles)
        self.assertIn("one-shot", profiles)
        self.assertIn("cold", profiles)
        # Perfil con muestras estables vs. manager con una sola puja extrema.
        self.assertLess(profiles["rich"].alpha_aggressiveness, profiles["one-shot"].alpha_aggressiveness)
        self.assertLess(profiles["one-shot"].alpha_aggressiveness, -1.0)
        self.assertLess(profiles["cold"].sigma_dispersion, 0.95)

    def test_no_samples_uses_global_prior(self) -> None:
        profiles = fit_rival_profiles_eb([], [{"team_id": "x", "manager_name": "X", "cash_eur": 1_000_000}])
        self.assertAlmostEqual(profiles["x"].alpha_aggressiveness, -2.465, places=2)

    def test_the_cash_uncertainty_floor_is_shared_with_the_thermometer(self) -> None:
        """``σ_cash`` usa el mismo suelo que la calibración de caja rival."""
        import os
        from unittest.mock import patch

        rivals = [{"team_id": "x", "manager_name": "X", "cash_eur": 1_000_000}]
        with patch.dict(os.environ, {"CASH_UNCERTAINTY_FLOOR_EUR": "400000"}):
            profiles = fit_rival_profiles_eb([], rivals)
        self.assertEqual(profiles["x"].cash_uncertainty_eur, 400_000)
        explicit = fit_rival_profiles_eb([], rivals, cash_uncertainty_floor_eur=900_000)
        self.assertEqual(explicit["x"].cash_uncertainty_eur, 900_000)

    def test_an_unbalanced_ledger_widens_the_floor(self) -> None:
        rivals = [
            {"team_id": "ok", "manager_name": "OK", "cash_eur": 1_000_000, "balanced": True},
            {"team_id": "off", "manager_name": "Off", "cash_eur": 1_000_000, "balanced": False},
        ]
        profiles = fit_rival_profiles_eb([], rivals, cash_uncertainty_floor_eur=100_000)
        self.assertEqual(profiles["ok"].cash_uncertainty_eur, 100_000)
        self.assertGreater(profiles["off"].cash_uncertainty_eur, profiles["ok"].cash_uncertainty_eur)


class OptimalBidTests(unittest.TestCase):
    def test_win_probability_zero_below_floor(self) -> None:
        rival = RivalProfile(
            team_id="r1",
            manager_name="R1",
            alpha_aggressiveness=-2.0,
            sigma_dispersion=0.4,
            cash_eur=5_000_000,
            cash_uncertainty_eur=200_000,
            thin_positions=["MC"],
            xi_gaps=[],
            lacks_replacements=False,
        )
        p_win = probability_of_winning_bid(900_000, 1_000_000, 1_000_000, "MC", 6.0, [rival])
        self.assertEqual(p_win, 0.0)

    def test_bidding_at_sale_price_does_not_collapse_win_probability(self) -> None:
        """Pujar al precio de venta (premium 0) no debe dar 0.0 por todos los rivales."""
        rival = RivalProfile(
            team_id="r1",
            manager_name="Ana",
            alpha_aggressiveness=-2.465,
            sigma_dispersion=0.4,
            cash_eur=5_000_000,
            cash_uncertainty_eur=200_000,
            thin_positions=["MC"],
            xi_gaps=[],
            lacks_replacements=False,
        )
        p_at_sale = probability_of_winning_bid(1_000_000, 1_000_000, 1_000_000, "MC", 6.0, [rival])
        self.assertGreater(p_at_sale, 0.0)
        # Sin rivales activos no hay incertidumbre rival que colapse.
        self.assertEqual(probability_of_winning_bid(1_000_000, 1_000_000, 1_000_000, "MC", 6.0, []), 1.0)
        # Monótona en la puja: por encima del suelo se gana más.
        p_above = probability_of_winning_bid(1_050_000, 1_000_000, 1_000_000, "MC", 6.0, [rival])
        self.assertGreater(p_above, p_at_sale)

    def test_cash_ceiling_knockout_raises_win_probability(self) -> None:
        rival = RivalProfile(
            team_id="r1",
            manager_name="Ana",
            alpha_aggressiveness=-1.5,
            sigma_dispersion=0.35,
            cash_eur=1_400_000,
            cash_uncertainty_eur=150_000,
            thin_positions=["MC"],
            xi_gaps=["MC"],
            lacks_replacements=True,
            already_bidding=True,
        )
        p_below = probability_of_winning_bid(1_100_000, 1_000_000, 1_000_000, "MC", 7.0, [rival])
        p_ko = probability_of_winning_bid(1_403_500, 1_000_000, 1_000_000, "MC", 7.0, [rival])
        self.assertGreater(p_ko, p_below)

    def test_solve_optimal_bid_respects_own_cash_cap(self) -> None:
        result = solve_optimal_bid_v2(
            market_value=1_000_000,
            sale_price=1_000_000,
            leading_bid=0,
            own_cash_eur=1_100_000,
            position="MC",
            expected_pts=6.0,
            points_delta_xi=0.0,
            populates_empty_slot=False,
            free_tier_peers_count=5,
            projected_daily_deltas=[20_000, 15_000],
            delta_volatility=10_000,
            rivals=[],
            value_ceiling=1_200_000,
        )
        self.assertLessEqual(result.optimal_bid_eur, 1_100_000)
        self.assertEqual(result.win_probability, 1.0)


if __name__ == "__main__":
    unittest.main()

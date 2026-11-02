"""Subastas v2: perfilado Bayesiano y puja óptima."""

from __future__ import annotations

import unittest
from dataclasses import replace

from toolbox.bid_war import calcular_puja_optima, probability_of_winning_bid, solve_optimal_bid_v2
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


class HurdleProfileTests(unittest.TestCase):
    @staticmethod
    def _buys(team: str, premiums: list[float]) -> list[dict]:
        return [
            {
                "team_id": team,
                "amount_eur": round(10_000_000 * (1.0 + premium)),
                "reference_value_eur": 10_000_000,
                "cash_at_event_eur": 30_000_000,
                "positional_urgency": 0.0,
            }
            for premium in premiums
        ]

    def _profiles(self):
        buys = (
            self._buys("naviis", [0.0, 0.0, 0.004, 0.0, 0.0, 0.0, 0.0, 0.18])
            + self._buys("pabs", [0.14, 0.16, 0.18, 0.15, 0.17, 0.0])
        )
        rivals = [
            {"team_id": "naviis", "manager_name": "Naviis10", "cash_eur": 40_000_000},
            {"team_id": "pabs", "manager_name": "PABS FC", "cash_eur": 40_000_000},
            {"team_id": "nuevo", "manager_name": "Nuevo", "cash_eur": 40_000_000},
        ]
        return fit_rival_profiles_eb(buys, rivals)

    def test_exact_bids_are_data_not_censored(self) -> None:
        profiles = self._profiles()
        self.assertGreater(profiles["naviis"].p_exact, 0.6)
        self.assertEqual(profiles["naviis"].style, "conservador")
        self.assertLess(profiles["pabs"].p_exact, 0.4)
        self.assertEqual(profiles["pabs"].style, "agresivo")
        self.assertAlmostEqual(profiles["pabs"].median_overbid, 0.16, places=2)
        self.assertEqual(profiles["nuevo"].style, "sin_datos")

    def test_a_conservative_rival_adds_no_risk_premium(self) -> None:
        profiles = self._profiles()
        kwargs = dict(v_ref=10_000_000, min_legal_bid=10_000_000, position="MC", expected_pts=5.0)
        # Con +3 % se gana casi siempre al que puja el valor exacto y casi nunca al agresivo.
        # ``already_bidding`` fuerza que el rival participe, para aislar la curva de puja.
        naviis = replace(profiles["naviis"], already_bidding=True)
        pabs = replace(profiles["pabs"], already_bidding=True)
        vs_naviis = probability_of_winning_bid(10_300_000, rivals=[naviis], **kwargs)
        vs_pabs = probability_of_winning_bid(10_300_000, rivals=[pabs], **kwargs)
        self.assertGreater(vs_naviis, 0.6)
        self.assertGreater(vs_naviis, vs_pabs + 0.25)

    def test_without_exact_mass_the_curve_is_unchanged(self) -> None:
        rival = RivalProfile("r", "R", -2.0, 0.4, 40_000_000, 500_000, [], [], False)
        self.assertEqual(rival.p_exact, 0.0)
        low = probability_of_winning_bid(10_100_000, 10_000_000, 10_000_000, "MC", 5.0, [rival])
        high = probability_of_winning_bid(12_000_000, 10_000_000, 10_000_000, "MC", 5.0, [rival])
        self.assertLess(low, high)


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


class SmartBidTests(unittest.TestCase):
    """Puja smart: +4,7 % de base, techo dinámico (suelo +15 %, cap +30 %) y knockout."""

    def _player(self) -> dict:
        return {"valor": 48_700_000, "posicion": "DEL"}

    def test_no_rival_bids_the_app_base(self) -> None:
        result = calcular_puja_optima(self._player(), [], 116_600_000)
        self.assertEqual(result["puja_base_app"], 51_000_000)
        self.assertEqual(result["puja_maxima"], 56_000_000)
        self.assertEqual(result["puja_smart"], 51_000_000)
        self.assertEqual(result["probabilidad_exito"], 95)
        self.assertEqual(result["rivales_peligrosos"], [])

    def test_knockout_stays_inside_the_financial_cap(self) -> None:
        rivals = [
            {"nombre": "Pobre", "dineroEstimado": -1_000_000, "posiciones_debiles": ["DEL"]},
            {"nombre": "Lleno", "dineroEstimado": 80_000_000, "posiciones_debiles": ["MC"]},
            {"nombre": "Ana", "dineroEstimado": 55_000_000, "posiciones_debiles": ["DEL"]},
            {"nombre": "Corto", "dineroEstimado": 40_000_000, "posiciones_debiles": ["DEL"]},
        ]
        result = calcular_puja_optima(self._player(), rivals, 116_600_000)
        self.assertEqual(result["rivales_peligrosos"], ["Ana"])
        self.assertEqual(result["puja_smart"], 55_100_000)
        self.assertEqual(result["probabilidad_exito"], 99)
        self.assertIn("Ana", result["analisis"])

    def test_rich_rival_stops_at_the_dynamic_cap(self) -> None:
        rivals = [{"nombre": "Rico", "dineroEstimado": 80_000_000, "posiciones_debiles": ["DEL"]}]
        result = calcular_puja_optima(self._player(), rivals, 116_600_000)
        self.assertEqual(result["puja_smart"], 56_000_000)
        self.assertEqual(result["probabilidad_exito"], 40)

    def test_forecast_and_easy_fixture_lift_the_ceiling_up_to_30_percent(self) -> None:
        # +23,2 % a 7 días aporta ~12,76 puntos. Partido fácil suma 2. 1,2976 < 1,30.
        player = {"valor": 48_700_000, "posicion": "DEL", "prevision_7d_pct": 23.2, "dificultad": "facil"}
        result = calcular_puja_optima(player, [], 116_600_000)
        self.assertEqual(result["puja_maxima"], 63_200_000)
        capped = {"valor": 10_000_000, "posicion": "MC", "prevision_7d_pct": "+80%", "dificultad": "muy_facil"}
        hard = calcular_puja_optima(capped, [], 50_000_000)
        self.assertEqual(hard["puja_maxima"], 13_000_000)
        tough = calcular_puja_optima({"valor": 10_000_000, "posicion": "MC", "dificultad": "dificil"}, [], 50_000_000)
        self.assertEqual(tough["puja_maxima"], 11_400_000)

    def test_poorer_manager_goes_all_in(self) -> None:
        rivals = [{"nombre": "Rico", "dineroEstimado": 200_000_000, "posiciones_debiles": ["DEL"]}]
        result = calcular_puja_optima(self._player(), rivals, 116_600_000)
        self.assertEqual(result["puja_smart"], 116_600_000)
        self.assertEqual(result["probabilidad_exito"], 20)

    def test_rounding_still_clears_the_rival_cash(self) -> None:
        rivals = [{"nombre": "Ana", "dineroEstimado": 12_340_000, "posiciones_debiles": ["MC"]}]
        # +20 % a 7 días sube el techo a 1,26×, por encima de la caja de Ana y por debajo del cap.
        result = calcular_puja_optima(
            {"valor": 10_000_000, "posicion": "MC", "prevision_7d_pct": 20},
            rivals,
            30_000_000,
        )
        self.assertGreater(result["puja_smart"], 12_340_000)
        self.assertLessEqual(result["puja_smart"], result["puja_maxima"])
        self.assertEqual(result["puja_maxima"], 12_600_000)


if __name__ == "__main__":
    unittest.main()

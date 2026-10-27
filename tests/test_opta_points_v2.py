"""Motor E[Pts] OPTA v2: escalón Poisson, Ordered Probit y Monte Carlo."""

from __future__ import annotations

import unittest

from toolbox.opta_points_v2 import (
    compute_expected_opta_points_v2,
    infer_opta_performance_bonus,
    poisson_step_expectation,
)


class PoissonStepTests(unittest.TestCase):
    def test_zero_mu(self) -> None:
        self.assertEqual(poisson_step_expectation(0.0, 2), 0.0)

    def test_positive_expectation(self) -> None:
        value = poisson_step_expectation(3.5, 2)
        self.assertGreater(value, 0.5)
        self.assertLess(value, 3.0)


class OrderedProbitTests(unittest.TestCase):
    def test_bonus_in_range(self) -> None:
        bonus = infer_opta_performance_bonus(
            avg_rating=7.2,
            lambda_own=1.5,
            lambda_opp=1.1,
            key_passes_90=1.5,
            duels_won_90=5.0,
            p_start_eff=0.85,
            p_sub_eff=0.05,
        )
        self.assertGreaterEqual(bonus, 0.0)
        self.assertLessEqual(bonus, 4.0)


class ExpectedPointsV2Tests(unittest.TestCase):
    def test_del_striker_ceiling_above_mean(self) -> None:
        player = {
            "player_id": "striker-1",
            "position": "DEL",
            "p_titular": 0.9,
            "form": {"xg": 8.0, "xa": 4.0, "minutes": 720, "starts": 8, "minutes_pct": 1.0, "duels_won": 18},
        }
        result = compute_expected_opta_points_v2(player, lambda_own=1.8, lambda_opp=1.0, n_sims=2000)
        self.assertGreater(result["expected_points"], 0.0)
        self.assertGreaterEqual(result["ceiling_points"], result["expected_points"])

    def test_portero_saves_component(self) -> None:
        player = {
            "player_id": "gk-1",
            "position": "POR",
            "p_titular": 0.95,
            "form": {"saves": 45.0, "minutes": 810, "starts": 9},
        }
        result = compute_expected_opta_points_v2(player, lambda_own=0.9, lambda_opp=1.6, n_sims=1500)
        self.assertGreater(result["expected_points"], 2.0)

    def test_on_verge_reduces_survival(self) -> None:
        base = {
            "player_id": "mc-1",
            "position": "MC",
            "p_titular": 0.8,
            "form": {"xg": 2.0, "xa": 1.0, "minutes": 600, "starts": 7},
        }
        ok = compute_expected_opta_points_v2(dict(base), n_sims=500, run_monte_carlo=False)
        warned = compute_expected_opta_points_v2(
            {**base, "sanction": {"on_verge": True}},
            n_sims=500,
            run_monte_carlo=False,
        )
        self.assertEqual(ok["next_match_survival"], 1.0)
        self.assertLess(warned["next_match_survival"], 1.0)

    def test_injured_zero_points(self) -> None:
        player = {
            "position": "DEL",
            "p_titular": 0.9,
            "fitness": "lesionado",
            "form": {"xg": 10.0},
        }
        result = compute_expected_opta_points_v2(player)
        self.assertEqual(result["expected_points"], 0.0)

    def test_season_xg_normalized_with_sparse_minutes(self) -> None:
        player = {
            "player_id": "mc-sparse",
            "position": "MC",
            "p_titular": 0.9,
            "average_points": 4.0,
            "form": {"xg": 8.0, "xa": 3.0, "minutes": 150, "starts": 2, "minutes_pct": 0.8},
        }
        result = compute_expected_opta_points_v2(player, run_monte_carlo=False)
        self.assertLess(result["expected_points"], 40.0)

    def test_season_xg_normalized_with_full_sample(self) -> None:
        player = {
            "player_id": "mc-full",
            "position": "MC",
            "p_titular": 0.85,
            "form": {"xg": 8.0, "xa": 3.0, "minutes": 720, "starts": 8, "minutes_pct": 1.0},
        }
        result = compute_expected_opta_points_v2(player, run_monte_carlo=False)
        self.assertLess(result["expected_points"], 16.0)


class TitularityTruthinessTests(unittest.TestCase):
    """Un ``p_titular`` de ``0.0`` es un cero real, no un dato ausente."""

    def _player(self, p_titular: object) -> dict:
        return {
            "player_id": "zero-titular",
            "position": "MC",
            "p_titular": p_titular,
            "form": {"xg": 4.0, "xa": 2.0, "minutes": 0, "starts": 0, "minutes_pct": 0.0},
        }

    def test_explicit_zero_is_respected(self) -> None:
        result = compute_expected_opta_points_v2(self._player(0.0), run_monte_carlo=False)
        self.assertEqual(result["p_start_eff"], 0.0)
        self.assertEqual(result["expected_minutes"], 0.0)
        self.assertEqual(result["expected_points"], 0.0)
        self.assertEqual(result["goal_probability"], 0.0)

    def test_zero_is_not_replaced_by_the_default(self) -> None:
        zero = compute_expected_opta_points_v2(self._player(0.0), run_monte_carlo=False)
        missing = compute_expected_opta_points_v2(self._player(None), run_monte_carlo=False)
        self.assertEqual(missing["p_start_eff"], 0.5)
        self.assertLess(zero["p_start_eff"], missing["p_start_eff"])

    def test_integer_zero_is_respected(self) -> None:
        result = compute_expected_opta_points_v2(self._player(0), run_monte_carlo=False)
        self.assertEqual(result["p_start_eff"], 0.0)

    def test_non_numeric_falls_back_to_default(self) -> None:
        result = compute_expected_opta_points_v2(self._player("0"), run_monte_carlo=False)
        self.assertEqual(result["p_start_eff"], 0.5)


if __name__ == "__main__":
    unittest.main()

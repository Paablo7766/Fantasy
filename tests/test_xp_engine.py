"""Puntuación esperada: titular contra revulsivo, no media de temporada × titularidad."""

from __future__ import annotations

import unittest

from toolbox.analyzer import ObjectiveWeights, candidate_from_player
from toolbox.engine.xp_calculator import (
    ContextoEquipo,
    FantasyXPEngine,
    PartidoHistorico,
    predecir_desde_jugador,
)
from toolbox.opta_points_v2 import compute_expected_opta_points_v2


def _neutral(local: bool = True) -> tuple[ContextoEquipo, ContextoEquipo]:
    propio = ContextoEquipo(xg_favor_90=1.25, xg_contra_90=1.25, es_local=local)
    rival = ContextoEquipo(xg_favor_90=1.25, xg_contra_90=1.25, es_local=not local)
    return propio, rival


def _titulares(puntos: list[float], minutos: int = 80) -> list[PartidoHistorico]:
    return [
        PartidoHistorico(puntos=puntos_jornada, minutos=minutos, jornada=index + 1)
        for index, puntos_jornada in enumerate(puntos)
    ]


class BayesianShrinkageTests(unittest.TestCase):
    def test_youth_without_starts_uses_the_position_prior(self) -> None:
        propio, rival = _neutral()
        result = FantasyXPEngine.calcular_prediccion_completa(
            "DEF",
            [],
            0.85,
            propio,
            rival,
            lambda_favor=1.35,
            lambda_contra=0.9,
        )
        # La media de temporada (1,8) × 85 % se quedaba por debajo de 2.
        # Sin partidos de titular la base es el prior de defensa, ~4,3.
        self.assertEqual(result["n_titular"], 0.0)
        self.assertGreater(result["base_titular"], 4.0)
        self.assertLess(result["base_titular"], 4.6)
        self.assertGreater(result["xp_condicional"], 4.0)
        self.assertGreater(result["xp_pizarra"], 3.2)
        self.assertLess(result["xp_pizarra"], result["xp_condicional"])

    def test_one_start_does_not_collapse_to_the_season_average(self) -> None:
        """Yoel Lago: un 5 en el único partido de titular no es un 1,8 de media."""
        historial = [
            PartidoHistorico(puntos=0, minutos=0, jornada=1),
            PartidoHistorico(puntos=0, minutos=0, jornada=2),
            PartidoHistorico(puntos=1, minutos=20, jornada=3),
            PartidoHistorico(puntos=5, minutos=78, jornada=4),
        ]
        result = predecir_desde_jugador(
            {"position": "DEF", "historial": historial},
            prob_titular=0.85,
            lambda_favor=1.35,
            lambda_contra=0.9,
        )
        self.assertEqual(result["n_titular"], 1.0)
        self.assertGreater(result["base_titular"], 4.0)
        self.assertGreater(result["xp_pizarra"], 3.0)

    def test_regular_mean_dominates_the_prior(self) -> None:
        propio, rival = _neutral()
        veteran = FantasyXPEngine.calcular_prediccion_completa(
            "MC",
            _titulares([6.8] * 10),
            0.70,
            propio,
            rival,
            7.25,
            lambda_favor=1.55,
            lambda_contra=1.05,
        )
        youth = FantasyXPEngine.calcular_prediccion_completa(
            "MC",
            [],
            0.70,
            propio,
            rival,
            lambda_favor=1.55,
            lambda_contra=1.05,
        )
        self.assertGreater(veteran["base_titular"], 6.5)
        self.assertGreater(veteran["xp_condicional"], youth["xp_condicional"])
        self.assertGreater(veteran["xp_condicional"], 7.0)
        self.assertLess(veteran["xp_condicional"], 10.0)
        self.assertGreater(veteran["xp_pizarra"], 4.5)
        self.assertLess(veteran["xp_pizarra"], veteran["xp_condicional"])
        self.assertGreater(veteran["techo"], veteran["xp_condicional"])
        volatile = FantasyXPEngine.calcular_prediccion_completa(
            "MC",
            _titulares([2, 4, 14, 3, 9, 6, 11, 5, 8, 7]),
            0.70,
            propio,
            rival,
            7.25,
            lambda_favor=1.55,
            lambda_contra=1.05,
        )
        self.assertGreater(volatile["techo"], 15.0)
        self.assertGreater(volatile["std_jugador"], 3.0)

    def test_recent_starts_weigh_more_than_old_ones(self) -> None:
        propio, rival = _neutral()
        hot = FantasyXPEngine.calcular_prediccion_completa(
            "MC",
            _titulares([2, 2, 2, 2, 2, 10]),
            1.0,
            propio,
            rival,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        cold = FantasyXPEngine.calcular_prediccion_completa(
            "MC",
            _titulares([10, 2, 2, 2, 2, 2]),
            1.0,
            propio,
            rival,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        self.assertGreater(hot["base_titular"], cold["base_titular"])

    def test_dnp_zeroes_stay_out_of_the_starter_mean(self) -> None:
        inferred = predecir_desde_jugador(
            {"position": "DEF", "week_points": [0, 0, 0, 0, 5]},
            prob_titular=0.8,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        self.assertEqual(inferred["n_titular"], 1.0)
        self.assertGreater(inferred["base_titular"], 4.0)


class MatchupTests(unittest.TestCase):
    def test_weak_attack_raises_a_defender_against_a_strong_one(self) -> None:
        propio, rival = _neutral()
        easy = FantasyXPEngine.calcular_prediccion_completa(
            "DEF",
            _titulares([4.3] * 6),
            0.9,
            propio,
            rival,
            lambda_favor=1.3,
            lambda_contra=0.8,
        )
        hard = FantasyXPEngine.calcular_prediccion_completa(
            "DEF",
            _titulares([4.3] * 6),
            0.9,
            propio,
            rival,
            lambda_favor=1.1,
            lambda_contra=2.4,
        )
        self.assertGreater(easy["prob_clean_sheet"], hard["prob_clean_sheet"])
        self.assertGreater(easy["xp_condicional"], hard["xp_condicional"])

    def test_soft_defense_raises_a_forward(self) -> None:
        propio, rival = _neutral()
        soft = FantasyXPEngine.calcular_prediccion_completa(
            "DEL",
            _titulares([5.5] * 6),
            0.8,
            propio,
            rival,
            lambda_favor=1.9,
            lambda_contra=1.1,
        )
        tight = FantasyXPEngine.calcular_prediccion_completa(
            "DEL",
            _titulares([5.5] * 6),
            0.8,
            propio,
            rival,
            lambda_favor=0.8,
            lambda_contra=1.4,
        )
        self.assertGreater(soft["factor_partido"], tight["factor_partido"])
        self.assertGreater(soft["xp_condicional"], tight["xp_condicional"])


class BimodalTests(unittest.TestCase):
    def test_zero_start_probability_is_a_zero_jornada(self) -> None:
        propio, rival = _neutral()
        result = FantasyXPEngine.calcular_prediccion_completa(
            "MC",
            _titulares([6, 7, 5]),
            0.0,
            propio,
            rival,
            lambda_favor=1.4,
            lambda_contra=1.1,
        )
        self.assertEqual(result["xp_pizarra"], 0.0)
        self.assertGreater(result["xp_condicional"], 4.0)

    def test_rotation_player_keeps_a_bench_slice(self) -> None:
        propio, rival = _neutral()
        result = FantasyXPEngine.calcular_prediccion_completa(
            "MC",
            _titulares([4.5] * 5),
            0.30,
            propio,
            rival,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        self.assertGreater(result["xp_pizarra"], 0.30 * result["xp_condicional"])
        self.assertLess(result["xp_pizarra"], result["xp_condicional"])

    def test_status_heuristic(self) -> None:
        historial = _titulares([4, 5, 6])
        self.assertEqual(
            FantasyXPEngine.prob_titular_heuristica(historial, player_status="injured"),
            0.0,
        )
        self.assertEqual(
            FantasyXPEngine.prob_titular_heuristica(historial, player_status="doubtful"),
            0.25,
        )
        available = FantasyXPEngine.prob_titular_heuristica(historial, player_status="ok")
        self.assertIsNotNone(available)
        assert available is not None
        self.assertGreaterEqual(available, 0.15)
        self.assertLessEqual(available, 0.90)


class PipelineTests(unittest.TestCase):
    def test_published_points_are_the_jornada_value(self) -> None:
        player = {
            "player_id": "cantera",
            "position": "DEF",
            "p_titular": 0.85,
            "average_points": 1.8,
            "week_points": [0, 0, 0, 1, 5],
            "form": {"minutes": 120, "starts": 1, "xg": 0.1, "xa": 0.05},
        }
        result = compute_expected_opta_points_v2(player, lambda_own=1.35, lambda_opp=0.9, run_monte_carlo=False)
        self.assertGreater(result["expected_points"], 3.0)
        self.assertGreater(result["xp_condicional"], result["expected_points"])
        self.assertGreater(result["ceiling_points"], result["xp_condicional"])
        self.assertEqual(result["n_titular"], 1.0)

    def test_candidate_splits_jornada_and_if_starts(self) -> None:
        player = {
            "player_id": "cantera",
            "name": "Cantera",
            "position": "DEF",
            "p_titular": 0.85,
            "average_points": 1.8,
            "week_points": [0, 0, 0, 1, 5],
            "form": {"minutes": 120, "starts": 1},
        }
        candidate = candidate_from_player(player, None, weights=ObjectiveWeights(), ordinal=0)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertGreater(candidate.jornada_ev, 3.0)
        self.assertIsNotNone(candidate.points_if_starts)
        assert candidate.points_if_starts is not None
        self.assertGreater(candidate.points_if_starts, candidate.jornada_ev)
        self.assertGreater(candidate.points_if_starts, 4.0)


if __name__ == "__main__":
    unittest.main()

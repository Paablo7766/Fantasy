"""Puntuación esperada: titular contra revulsivo, no media de temporada × titularidad."""

from __future__ import annotations

import unittest

from toolbox.analyzer import ObjectiveWeights, candidate_from_player
from toolbox.engine.xp_calculator import (
    K_PRIOR,
    K_PRIOR_RACHA,
    ContextoEquipo,
    FantasyXPEngine,
    PartidoHistorico,
    k_prior_efectivo,
    lambdas_de_fuerzas,
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


def _con_minutos(filas: list[tuple[float, int]]) -> list[PartidoHistorico]:
    return [
        PartidoHistorico(puntos=puntos, minutos=minutos, jornada=index + 1)
        for index, (puntos, minutos) in enumerate(filas)
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
        # Sin minutos, un 5 no demuestra titularidad: no entra en la media.
        self.assertEqual(inferred["n_titular"], 0.0)
        self.assertGreater(inferred["base_titular"], 4.0)

    def test_minutes_beat_the_score_when_they_disagree(self) -> None:
        titular_de_un_punto = predecir_desde_jugador(
            {"position": "DEF", "historial": [{"puntos": 1, "minutos": 80, "jornada": 1}]},
            prob_titular=0.8,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        suplente_de_tres = predecir_desde_jugador(
            {
                "position": "DEF",
                "historial": [
                    {"puntos": 3, "minutos": 12, "jornada": 1},
                    {"puntos": 4, "minutos": 20, "jornada": 2},
                ],
            },
            prob_titular=0.8,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        self.assertEqual(titular_de_un_punto["n_titular"], 1.0)
        self.assertEqual(suplente_de_tres["n_titular"], 0.0)

    def test_season_minutes_count_only_when_the_role_is_unambiguous(self) -> None:
        claro = predecir_desde_jugador(
            {"position": "DEF", "week_points": [0, 0, 5], "form": {"starts": 1, "minutes": 80}},
            prob_titular=0.8,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        mezclado = predecir_desde_jugador(
            {"position": "DEF", "week_points": [1, 5], "form": {"starts": 1, "minutes": 100}},
            prob_titular=0.8,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        self.assertEqual(claro["n_titular"], 1.0)
        self.assertEqual(mezclado["n_titular"], 0.0)

    def test_goalkeeper_prior_is_a_starter_score(self) -> None:
        propio, rival = _neutral()
        result = FantasyXPEngine.calcular_prediccion_completa(
            "POR",
            [],
            1.0,
            propio,
            rival,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        self.assertGreater(result["base_titular"], 7.5)
        self.assertLess(result["base_titular"], 8.5)

    def test_forward_prior_sits_on_the_prewindow_mean(self) -> None:
        propio, rival = _neutral()
        result = FantasyXPEngine.calcular_prediccion_completa(
            "DEL",
            [],
            1.0,
            propio,
            rival,
            lambda_favor=1.25,
            lambda_contra=1.25,
        )
        self.assertGreater(result["base_titular"], 5.5)
        self.assertLess(result["base_titular"], 6.2)

    def test_home_lambda_is_higher_than_away_for_the_same_rates(self) -> None:
        home, _ = lambdas_de_fuerzas(1.4, 1.1, 1.2, 1.3, es_local=True)
        away, _ = lambdas_de_fuerzas(1.4, 1.1, 1.2, 1.3, es_local=False)
        self.assertGreater(home, away)


class HotStreakTests(unittest.TestCase):
    def test_three_games_at_six_or_more_loosen_the_prior(self) -> None:
        """Pepelu: 7, 8 y 9 con 60' o más no se ancla al prior de un medio."""
        propio, rival = _neutral()
        en_racha = _con_minutos([(2, 20), (2, 20), (2, 20), (7, 80), (8, 80), (9, 80)])
        cortada = _con_minutos([(2, 20), (2, 20), (2, 20), (7, 80), (8, 80), (9, 50)])
        hot = FantasyXPEngine.calcular_prediccion_completa(
            "MC", en_racha, 0.9, propio, rival, lambda_favor=1.25, lambda_contra=1.25
        )
        cold = FantasyXPEngine.calcular_prediccion_completa(
            "MC", cortada, 0.9, propio, rival, lambda_favor=1.25, lambda_contra=1.25
        )
        self.assertEqual(hot["k_prior"], K_PRIOR_RACHA)
        self.assertEqual(hot["racha_partidos"], 3.0)
        self.assertGreaterEqual(hot["racha_media"], 6.0)
        self.assertEqual(cold["k_prior"], K_PRIOR)
        self.assertEqual(cold["racha_partidos"], 0.0)
        self.assertEqual(hot["n_titular"], cold["n_titular"])
        self.assertGreater(hot["base_titular"], cold["base_titular"])

    def test_two_games_and_a_low_mean_keep_the_strong_prior(self) -> None:
        self.assertEqual(k_prior_efectivo(_titulares([9, 9])), K_PRIOR)
        self.assertEqual(k_prior_efectivo(_titulares([5, 6, 6])), K_PRIOR)
        self.assertEqual(k_prior_efectivo(_titulares([6, 6, 6])), K_PRIOR_RACHA)

    def test_a_cameo_or_unknown_minutes_breaks_the_live_streak(self) -> None:
        self.assertEqual(k_prior_efectivo(_con_minutos([(8, 80), (8, 80), (8, 80), (1, 20)])), K_PRIOR)
        self.assertEqual(k_prior_efectivo(_con_minutos([(7, -1), (8, -1), (9, -1)])), K_PRIOR)
        self.assertEqual(k_prior_efectivo(_titulares([2, 2, 2, 2, 2, 10])), K_PRIOR)

    def test_sixty_minutes_counts_and_fifty_nine_does_not(self) -> None:
        self.assertEqual(k_prior_efectivo(_con_minutos([(7, 60), (8, 60), (9, 60)])), K_PRIOR_RACHA)
        self.assertEqual(k_prior_efectivo(_con_minutos([(7, 80), (8, 80), (9, 59)])), K_PRIOR)


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

    def test_titular_probability_separates_bench_from_absent(self) -> None:
        def historial(minutes: list[int]) -> list[PartidoHistorico]:
            return [PartidoHistorico(puntos=2.0, minutos=m, jornada=i + 1) for i, m in enumerate(minutes)]

        titular = FantasyXPEngine.prob_titular_heuristica(historial([90, 90, 90]))
        revulsivo = FantasyXPEngine.prob_titular_heuristica(historial([20, 25, 15]))
        ausente = FantasyXPEngine.prob_titular_heuristica(historial([0, 0, 0]))
        assert titular is not None and revulsivo is not None and ausente is not None
        self.assertGreater(titular, revulsivo)
        self.assertGreater(revulsivo, ausente)
        self.assertGreater(revulsivo, 0.25)


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
        # Un start y dos partidos con puntos: no se adivina cuál fue el titular.
        self.assertEqual(result["n_titular"], 0.0)

    def test_candidate_splits_jornada_and_if_starts(self) -> None:
        player = {
            "player_id": "cantera",
            "name": "Cantera",
            "position": "DEF",
            "p_titular": 0.85,
            "average_points": 1.8,
            "week_points": [0, 0, 0, 1, 5],
            "form": {"minutes": 120, "starts": 1},
            "own_expected_points": 3.6,
            "own_points_if_starts": 4.5,
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

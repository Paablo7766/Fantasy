"""Shock de puntos de jornada: baratos que explotan antes de que suba el precio."""

from __future__ import annotations

import unittest

from toolbox.engine.shock_jornada import detectar_shock


class DetectarShockTests(unittest.TestCase):
    def test_cheap_player_with_a_big_game_opens_the_window(self) -> None:
        shock = detectar_shock([2, 1, 12], 3_000_000, 0)
        assert shock is not None
        self.assertEqual(shock["ventana"], "abierta")
        self.assertEqual(shock["puntos"], 12.0)
        self.assertEqual(shock["ratio_pts_por_millon"], 4.0)

    def test_expensive_or_modest_games_are_not_a_shock(self) -> None:
        self.assertIsNone(detectar_shock([12], 6_000_000, 0))
        self.assertIsNone(detectar_shock([6], 2_000_000, 0))
        self.assertIsNone(detectar_shock([], 2_000_000, 0))
        self.assertIsNone(detectar_shock([12], None, 0))

    def test_ratio_floor_filters_a_borderline_price(self) -> None:
        self.assertIsNone(detectar_shock([8], 4_900_000, 0))

    def test_window_closes_once_the_price_or_the_external_signal_moves(self) -> None:
        moved = detectar_shock([12], 3_000_000, 150_000)
        assert moved is not None
        self.assertEqual(moved["ventana"], "cerrada")
        late = detectar_shock([12], 3_000_000, 0, externo_sube=True)
        assert late is not None
        self.assertEqual(late["ventana"], "cerrada")

    def test_dict_points_are_read(self) -> None:
        shock = detectar_shock([{"points": 10}], 2_000_000, None)
        assert shock is not None
        self.assertEqual(shock["puntos"], 10.0)


if __name__ == "__main__":
    unittest.main()

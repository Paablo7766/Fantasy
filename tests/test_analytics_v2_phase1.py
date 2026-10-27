"""Fase 1 arquitectura v2.0: de-vig, Dixon-Coles y cinemática de precios."""

from __future__ import annotations

import unittest

import numpy as np

from toolbox.own_intel import compute_price_kinematics_and_sell_signal
from toolbox.understat import devig_shin_3way, invert_market_to_dixon_coles


class DevigShinTests(unittest.TestCase):
    def test_probs_sum_to_one(self) -> None:
        probs, z = devig_shin_3way((2.10, 3.40, 3.50))
        self.assertAlmostEqual(float(np.sum(probs)), 1.0, places=6)
        self.assertGreaterEqual(z, 0.0)

    def test_rejects_invalid_odds(self) -> None:
        with self.assertRaises(ValueError):
            devig_shin_3way((1.0, 3.0, 4.0))


class DixonColesInvertTests(unittest.TestCase):
    def test_invert_returns_reasonable_lambdas(self) -> None:
        odds = (2.05, 3.55, 3.60)
        lh, la, rho = invert_market_to_dixon_coles(odds, (1.85, 2.05), (1.72, 2.15))
        self.assertGreater(lh, 0.15)
        self.assertGreater(la, 0.15)
        self.assertLess(rho, 0.15)
        self.assertGreater(rho, -0.25)


class PriceKinematicsTests(unittest.TestCase):
    def test_sell_at_crest_while_still_rising(self) -> None:
        """Sube hoy pero desacelera: cresta antes del cruce por cero.

        Serie de capturas propias: cada delta sale de restar dos
        ``market_value`` medidos por este proyecto, nunca de
        ``market_value_change`` (estimación de terceros).
        """
        snapshots = [
            {"day": "2026-10-14", "market_value": 10_600_000},
            {"day": "2026-10-15", "market_value": 11_100_000},
            {"day": "2026-10-16", "market_value": 11_500_000},
            {"day": "2026-10-17", "market_value": 11_800_000},
        ]
        kin = compute_price_kinematics_and_sell_signal(
            snapshots,
            current_market_value=12_000_000,
            official_today_delta=200_000,
        )
        self.assertEqual(kin.price_delta_1, 200_000)
        self.assertEqual(kin.price_delta_3, 900_000)
        self.assertLess(kin.acceleration, 0)
        self.assertEqual(kin.sell_signal_status, "SELL_AT_CREST")
        self.assertTrue(kin.sell_signal)
        self.assertLessEqual(kin.days_to_zero_crossing, 2.0)
        self.assertGreaterEqual(kin.relative_exhaustion_index, 0.38)

    def test_sell_signal_blocked_when_delta_comes_from_third_party_estimate(self) -> None:
        """Sin capturas propias, el delta es de terceros: no hay señal de venta."""
        snapshots = [
            {"day": "2026-10-14", "market_value_change": 500_000},
            {"day": "2026-10-15", "market_value_change": 400_000},
            {"day": "2026-10-16", "market_value_change": 300_000},
            {"day": "2026-10-17", "market_value_change": 200_000},
        ]
        kin = compute_price_kinematics_and_sell_signal(
            snapshots,
            current_market_value=12_000_000,
            official_today_delta=200_000,
        )
        self.assertFalse(kin.sell_signal)
        self.assertEqual(kin.sell_signal_status, "HOLD_RISING")


if __name__ == "__main__":
    unittest.main()

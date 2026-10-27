"""Explotador del market maker: percentil, EV de mañana y badge. Sin red."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from toolbox.market_maker import (
    DEFAULT_MEAN_PCT,
    LIQUIDATION_RATIO,
    MAX_OFFER_PCT,
    MIN_LOG_SAMPLES,
    MIN_OFFER_PCT,
    MarketMakerExploiter,
    evaluate_offer,
    get_market_recommendations,
    get_offer_percentile,
    log_offer,
)

VALUE = 10_000_000


class _LogFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "market_offers_log.json"
        self.mm = MarketMakerExploiter(self.path)

    def tearDown(self) -> None:
        self.folder.cleanup()


class PercentileTests(unittest.TestCase):
    def test_spec_example_008_is_p90(self) -> None:
        self.assertEqual(get_offer_percentile(0.08), 90.0)

    def test_band_edges(self) -> None:
        self.assertEqual(get_offer_percentile(MIN_OFFER_PCT), 0.0)
        self.assertEqual(get_offer_percentile(0.0), 50.0)
        self.assertEqual(get_offer_percentile(MAX_OFFER_PCT), 100.0)

    def test_liquidate_threshold_is_p80(self) -> None:
        self.assertAlmostEqual(LIQUIDATION_RATIO, 0.06, places=6)
        self.assertEqual(get_offer_percentile(LIQUIDATION_RATIO), 80.0)

    def test_out_of_band_saturates(self) -> None:
        self.assertEqual(get_offer_percentile(0.50), 100.0)
        self.assertEqual(get_offer_percentile(-0.40), 0.0)

    def test_instance_method_matches_module(self) -> None:
        self.assertEqual(MarketMakerExploiter.get_offer_percentile(0.02), 60.0)

    def test_rejects_non_numeric(self) -> None:
        with self.assertRaises(ValueError):
            get_offer_percentile(True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            get_offer_percentile(float("nan"))


class LogTests(_LogFixture):
    def test_log_offer_stores_ratio(self) -> None:
        entry = self.mm.log_offer("p1", VALUE, int(VALUE * 1.05))
        self.assertEqual(entry["ratio"], 0.05)
        self.assertEqual(entry["percentile"], 75.0)
        self.assertEqual(len(self.mm.load_log()), 1)

    def test_log_appends_and_is_readable(self) -> None:
        self.mm.log_offer("p1", VALUE, VALUE)
        self.mm.log_offer("p2", VALUE, VALUE * 1.10)
        rows = self.mm.load_log()
        self.assertEqual([row["jugador_id"] for row in rows], ["p1", "p2"])

    def test_module_helper_writes_the_same_file(self) -> None:
        entry = log_offer("p1", VALUE, VALUE * 0.95, path=self.path)
        self.assertEqual(entry["ratio"], -0.05)
        self.assertEqual(len(self.mm.load_log()), 1)

    def test_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            self.mm.log_offer("p1", 0, VALUE)
        with self.assertRaises(ValueError):
            self.mm.log_offer("", VALUE, VALUE)
        self.assertEqual(self.mm.load_log(), [])

    def test_corrupt_file_counts_as_empty(self) -> None:
        self.path.write_text("{no es json", encoding="utf-8")
        self.assertEqual(self.mm.load_log(), [])
        self.assertEqual(self.mm.historical_mean()["mean_source"], "default")

    def test_mean_uses_default_below_min_samples(self) -> None:
        for _ in range(MIN_LOG_SAMPLES - 1):
            self.mm.log_offer("p1", VALUE, VALUE * 1.05)
        mean = self.mm.historical_mean("p1")
        self.assertEqual(mean["mean_pct"], DEFAULT_MEAN_PCT)
        self.assertEqual(mean["mean_source"], "default")

    def test_mean_uses_player_log_when_enough_samples(self) -> None:
        for _ in range(MIN_LOG_SAMPLES):
            self.mm.log_offer("p1", VALUE, VALUE * 1.05)
        mean = self.mm.historical_mean("p1")
        self.assertAlmostEqual(mean["mean_pct"], 0.05, places=6)
        self.assertEqual(mean["mean_source"], "log_jugador")


class EvaluateOfferTests(_LogFixture):
    def test_strong_sell_at_p90(self) -> None:
        result = self.mm.evaluate_offer(VALUE * 1.08, VALUE, 0)
        self.assertEqual(result["recommendation"], "STRONG_SELL")
        self.assertEqual(result["percentile"], 90.0)
        self.assertEqual(result["action"], "SELL")
        self.assertEqual(result["badge"]["tone"], "green")

    def test_strong_sell_even_with_rising_trend(self) -> None:
        """El pico manda: el riesgo de rechazarlo es altísimo."""
        result = self.mm.evaluate_offer(VALUE * 1.08, VALUE, 900_000)
        self.assertEqual(result["recommendation"], "STRONG_SELL")

    def test_sell_when_offer_beats_tomorrow_ev(self) -> None:
        result = self.mm.evaluate_offer(VALUE * 1.02, VALUE, 100_000)
        self.assertEqual(result["recommendation"], "SELL")
        self.assertEqual(result["ev_tomorrow_eur"], _eur(VALUE * 1.01))
        self.assertGreater(result["edge_vs_ev_eur"], 0)

    def test_ev_uses_historical_mean(self) -> None:
        for _ in range(MIN_LOG_SAMPLES):
            self.mm.log_offer("p1", VALUE, VALUE * 1.05)
        result = self.mm.evaluate_offer(VALUE * 1.02, VALUE, 0, jugador_id="p1")
        self.assertEqual(result["mean_source"], "log_jugador")
        self.assertAlmostEqual(result["mean_pct"], 0.05, places=6)
        self.assertEqual(result["ev_tomorrow_eur"], _eur(VALUE * 1.05))
        self.assertEqual(result["recommendation"], "HOLD")

    def test_strong_hold_when_short_and_rising(self) -> None:
        result = self.mm.evaluate_offer(VALUE * 1.01, VALUE, 200_000)
        self.assertEqual(result["recommendation"], "STRONG_HOLD")
        self.assertEqual(result["action"], "HOLD")
        self.assertEqual(result["badge"]["tone"], "red")

    def test_liquidate_when_p80_tomorrow_still_loses(self) -> None:
        """Con caída, la oferta de hoy no llega ni al mínimo del sistema de mañana.

        El umbral del rechazo es independiente de la media histórica: es el
        percentil 0 de mañana (``1 + MIN_OFFER_PCT``). Si la oferta queda por
        debajo, esperar solo puede empeorar y se liquida ahora.
        """
        trend = -800_000
        offer = VALUE + trend * (1.0 + MIN_OFFER_PCT) * 0.95
        result = self.mm.evaluate_offer(offer, VALUE, trend, mean_pct=0.08)
        self.assertEqual(result["recommendation"], "LIQUIDATE_NOW")
        self.assertEqual(result["reason"], "escenario_limite")
        self.assertLess(result["offer_eur"], _eur(result["tomorrow_value_eur"] * (1.0 + MIN_OFFER_PCT)))
        self.assertGreater(result["ev_tomorrow_eur"], result["offer_eur"])

    def test_hold_when_p80_tomorrow_beats_today(self) -> None:
        """Cae, pero la oferta de hoy aún supera el suelo del sistema de mañana."""
        trend = -400_000
        result = self.mm.evaluate_offer(VALUE * 0.99, VALUE, trend, mean_pct=0.08)
        self.assertEqual(result["recommendation"], "HOLD")
        self.assertEqual(result["reason"], "esperar_oferta_mejor")
        self.assertGreater(result["offer_eur"], _eur(result["tomorrow_value_eur"] * (1.0 + MIN_OFFER_PCT)))

    def test_liquidation_window_does_not_need_the_historical_mean(self) -> None:
        trend = -900_000
        offer = VALUE + trend * (1.0 + MIN_OFFER_PCT) * 0.95
        result = self.mm.evaluate_offer(offer, VALUE, trend, mean_pct=0.0)
        self.assertEqual(result["recommendation"], "LIQUIDATE_NOW")
        self.assertEqual(result["reason"], "escenario_limite")

    def test_hold_when_tomorrow_floor_still_beats_today(self) -> None:
        trend = -900_000
        offer = VALUE - 500_000
        result = self.mm.evaluate_offer(offer, VALUE, trend, mean_pct=0.0)
        self.assertEqual(result["recommendation"], "HOLD")
        self.assertEqual(result["reason"], "esperar_oferta_mejor")

    def test_liquidation_boundary_is_strict(self) -> None:
        """Empate exacto: no se liquida. La regla pide ganar menos, no igual."""
        trend = -800_000
        tomorrow = VALUE + trend
        offer = tomorrow * (1.0 + MIN_OFFER_PCT)
        result = self.mm.evaluate_offer(offer, VALUE, trend, mean_pct=0.08)
        self.assertEqual(result["recommendation"], "HOLD")
        self.assertEqual(result["reason"], "esperar_oferta_mejor")

    def test_no_trend_never_liquidates(self) -> None:
        result = self.mm.evaluate_offer(VALUE * 0.90, VALUE, None)
        self.assertEqual(result["recommendation"], "HOLD")
        self.assertIsNone(result["trend_source"])

    def test_zero_trend_never_liquidates(self) -> None:
        result = self.mm.evaluate_offer(VALUE * 0.90, VALUE, 0)
        self.assertEqual(result["recommendation"], "HOLD")
        self.assertEqual(result["reason"], "sin_tendencia")

    def test_equal_to_ev_is_hold(self) -> None:
        result = self.mm.evaluate_offer(VALUE, VALUE, 0)
        self.assertEqual(result["recommendation"], "HOLD")
        self.assertEqual(result["edge_vs_ev_eur"], 0)

    def test_trend_cannot_make_tomorrow_value_negative(self) -> None:
        result = self.mm.evaluate_offer(VALUE * 0.99, VALUE, -VALUE * 5)
        self.assertEqual(result["tomorrow_value_eur"], 0)
        self.assertEqual(result["ev_tomorrow_eur"], 0)
        self.assertEqual(result["recommendation"], "SELL")

    def test_forced_mean_overrides_log(self) -> None:
        for _ in range(MIN_LOG_SAMPLES):
            self.mm.log_offer("p1", VALUE, VALUE * 1.05)
        result = self.mm.evaluate_offer(VALUE, VALUE, 0, jugador_id="p1", mean_pct=0.0)
        self.assertEqual(result["mean_source"], "forzada")
        self.assertEqual(result["ev_tomorrow_eur"], _eur(VALUE))

    def test_module_helper(self) -> None:
        result = evaluate_offer(VALUE * 1.08, VALUE, 0, path=self.path)
        self.assertEqual(result["recommendation"], "STRONG_SELL")

    def test_rejects_bad_inputs(self) -> None:
        with self.assertRaises(ValueError):
            self.mm.evaluate_offer(0, VALUE, 0)
        with self.assertRaises(ValueError):
            self.mm.evaluate_offer(VALUE, 0, 0)
        with self.assertRaises(ValueError):
            self.mm.evaluate_offer(VALUE, VALUE, float("inf"))


class RecommendationsTests(_LogFixture):
    def test_maps_flags_to_badge(self) -> None:
        document = self.mm.get_market_recommendations(
            [
                {"player_id": "a", "name": "A", "market_value": VALUE, "oferta_sistema": int(VALUE * 1.08)},
                {"player_id": "b", "name": "B", "market_value": VALUE, "oferta_sistema": int(VALUE * 0.99)},
            ]
        )
        self.assertTrue(document["ok"])
        self.assertFalse(document["sends"])
        by_id = {row["jugador_id"]: row for row in document["offers"]}
        self.assertEqual(by_id["a"]["badge"]["tone"], "green")
        self.assertEqual(by_id["b"]["badge"]["tone"], "red")
        for row in document["offers"]:
            self.assertIn("ev_tomorrow_eur", row)
            self.assertIn(row["recommendation"], {"STRONG_SELL", "SELL", "HOLD", "STRONG_HOLD", "LIQUIDATE_NOW"})

    def test_accepts_document_and_aliases(self) -> None:
        document = self.mm.get_market_recommendations(
            {
                "jugadores_en_venta": [
                    {
                        "player_id": "a",
                        "market_value": VALUE,
                        "offer_eur": int(VALUE * 1.02),
                        "own_predicted_delta": 100_000,
                    }
                ]
            }
        )
        self.assertEqual(document["count"], 1)
        self.assertEqual(document["offers"][0]["recommendation"], "SELL")

    def test_skips_rows_without_offer_or_id(self) -> None:
        document = self.mm.get_market_recommendations(
            [
                {"player_id": "a", "market_value": VALUE},
                {"market_value": VALUE, "oferta_sistema": VALUE},
                {"player_id": "c", "valor_mercado": 0, "oferta_sistema": VALUE},
            ]
        )
        self.assertEqual(document["count"], 0)
        reasons = sorted(item["reason"] for item in document["skipped"])
        self.assertEqual(reasons, ["sin_jugador_id", "sin_oferta", "sin_valor_mercado"])

    def test_summary_counts_and_cash(self) -> None:
        document = self.mm.get_market_recommendations(
            [
                {"player_id": "a", "market_value": VALUE, "oferta_sistema": int(VALUE * 1.08)},
                {"player_id": "b", "market_value": VALUE, "oferta_sistema": int(VALUE * 1.04)},
                {"player_id": "c", "market_value": VALUE, "oferta_sistema": int(VALUE * 0.99)},
            ]
        )
        self.assertEqual(document["summary"]["sell"], 2)
        self.assertEqual(document["summary"]["hold"], 1)
        self.assertEqual(document["summary"]["strong_sell"], 1)
        self.assertEqual(
            document["summary"]["cash_if_sell_eur"],
            int(VALUE * 1.08) + int(VALUE * 1.04),
        )

    def test_sorted_sell_first(self) -> None:
        document = self.mm.get_market_recommendations(
            [
                {"player_id": "hold", "market_value": VALUE, "oferta_sistema": int(VALUE * 0.99)},
                {"player_id": "sell", "market_value": VALUE, "oferta_sistema": int(VALUE * 1.08)},
            ]
        )
        self.assertEqual([row["jugador_id"] for row in document["offers"]], ["sell", "hold"])

    def test_module_endpoint(self) -> None:
        document = get_market_recommendations(
            [{"player_id": "a", "market_value": VALUE, "oferta_sistema": int(VALUE * 1.08)}],
            path=self.path,
        )
        self.assertEqual(document["command"], "market-maker")


def _eur(value: float) -> int:
    return int(round(value))


if __name__ == "__main__":
    unittest.main()

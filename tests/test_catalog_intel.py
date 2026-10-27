"""Catálogo global: normalización, motor cuantitativo y endpoints. Sin red.

El catálogo de verdad se leyó una vez y se guardó en ``.cache/``; estas
pruebas fijan las reglas que convierten esa foto en decisiones, que es donde
un cambio silencioso cuesta puntos: el descarte de ``out_of_league``, el cast
de ``marketValue``, la serie completa de jornadas, la clasificación de riesgo
y la detección de suelo en una lesión.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox.catalog_intel import (
    MarketQuantAnalyzer,
    blank_rate,
    classify_asset,
    owned_player_ids,
    price_deceleration,
    quant_profile,
)
from toolbox.normalize import LALIGA_CLUBS, normalize_catalog, normalize_catalog_player


def _row(**overrides: object) -> dict:
    base = {
        "id": "68",
        "positionId": "1",
        "nickname": "Unai Simón",
        "playerStatus": "ok",
        "marketValue": "38074199",
        "averagePoints": 7.22,
        "weekPoints": [
            {"weekNumber": 3, "points": 10},
            {"weekNumber": 1, "points": 10},
            {"weekNumber": 2, "points": 1},
        ],
        "image": "https://assets-fantasy.llt-services.com/players/t174/p68/256x256/p68.png",
        "teamId": "3",
    }
    base.update(overrides)
    return base


def _player(
    player_id: str,
    series: list[float],
    *,
    status: str = "ok",
    value: int = 10_000_000,
    name: str | None = None,
) -> dict:
    return {
        "player_id": player_id,
        "nickname": name or f"Jugador {player_id}",
        "name": None,
        "club": "Athletic Club",
        "club_short": "ATH",
        "position": "POR",
        "player_status": status,
        "market_value": value,
        "week_points": series,
    }


class NormalizeCatalogTests(unittest.TestCase):
    def test_static_map_has_the_twenty_clubs(self) -> None:
        self.assertEqual(len(LALIGA_CLUBS), 20)
        self.assertEqual(LALIGA_CLUBS["3"]["short"], "ATH")
        self.assertEqual(LALIGA_CLUBS["4"]["short"], "FCB")
        for entry in LALIGA_CLUBS.values():
            self.assertTrue(entry["name"])
            self.assertEqual(len(entry["short"]), 3)

    def test_out_of_league_is_discarded(self) -> None:
        self.assertIsNone(normalize_catalog_player(_row(playerStatus="out_of_league")))
        self.assertIsNotNone(normalize_catalog_player(_row(playerStatus="injured")))

    def test_market_value_is_an_integer(self) -> None:
        player = normalize_catalog_player(_row())
        self.assertIsInstance(player["market_value"], int)
        self.assertEqual(player["market_value"], 38074199)
        self.assertIsInstance(normalize_catalog_player(_row(marketValue="0"))["market_value"], int)

    def test_club_comes_from_the_static_map(self) -> None:
        player = normalize_catalog_player(_row())
        self.assertEqual(player["club"], "Athletic Club")
        self.assertEqual(player["club_short"], "ATH")
        # Un teamId que no está en el mapa no inventa club.
        self.assertIsNone(normalize_catalog_player(_row(teamId="999"))["club"])

    def test_week_series_is_complete_and_chronological(self) -> None:
        series = [{"weekNumber": week, "points": week * 2} for week in range(20, 0, -1)]
        player = normalize_catalog_player(_row(weekPoints=series))
        self.assertEqual(len(player["week_points"]), 20)
        self.assertEqual(player["week_points"], [float(week * 2) for week in range(1, 21)])

    def test_series_is_not_truncated_to_five(self) -> None:
        series = [{"weekNumber": week, "points": float(week)} for week in range(1, 15)]
        player = normalize_catalog_player(_row(weekPoints=series))
        self.assertEqual(len(player["week_points"]), 14)

    def test_normalize_catalog_skips_what_has_no_id(self) -> None:
        rows = [_row(), _row(id=""), _row(playerStatus="out_of_league")]
        players = normalize_catalog(rows)
        self.assertEqual([player["player_id"] for player in players], ["68"])

    def test_normalize_catalog_accepts_wrapped_payload(self) -> None:
        players = normalize_catalog({"players": [_row()]})
        self.assertEqual(len(players), 1)


class QuantProfileTests(unittest.TestCase):
    def test_median_stdev_and_blank_rate(self) -> None:
        profile = quant_profile([0, 10, 0, 10, 0])
        self.assertEqual(profile["median"], 0.0)
        self.assertEqual(profile["blank_rate"], 0.6)
        self.assertGreater(profile["stdev"], 0)
        self.assertEqual(profile["sample"], 5)

    def test_blank_rate_counts_zero_and_negative(self) -> None:
        self.assertEqual(blank_rate([0, 0, -1, 5]), 0.75)
        self.assertEqual(blank_rate([]), 0.0)

    def test_single_sample_has_no_stdev(self) -> None:
        profile = quant_profile([7])
        self.assertIsNone(profile["stdev"])
        self.assertIsNone(profile["consistency"])

    def test_refuge_needs_high_median_low_variance(self) -> None:
        profile = quant_profile([6, 7, 6, 7, 6, 7])
        self.assertEqual(classify_asset(profile), "refugio")

    def test_risk_needs_high_variance_and_blanks(self) -> None:
        profile = quant_profile([0, 0, 0, 20, 15])
        self.assertEqual(classify_asset(profile), "riesgo")

    def test_short_sample_is_not_classified(self) -> None:
        self.assertIsNone(classify_asset(quant_profile([10, 10])))


class PriceDecelerationTests(unittest.TestCase):
    def test_slower_second_drop_is_a_floor(self) -> None:
        history = [
            {"day": "2026-10-21", "market_value": 10_000_000},
            {"day": "2026-10-22", "market_value": 7_000_000},
            {"day": "2026-10-23", "market_value": 5_200_000},
        ]
        trend = price_deceleration(history)
        self.assertTrue(trend["falling"])
        self.assertTrue(trend["decelerating"])
        self.assertEqual(trend["first_delta"], -3_000_000)
        self.assertEqual(trend["last_delta"], -1_800_000)

    def test_accelerating_drop_is_not_a_floor(self) -> None:
        history = [
            {"day": "2026-10-21", "market_value": 10_000_000},
            {"day": "2026-10-22", "market_value": 9_000_000},
            {"day": "2026-10-23", "market_value": 6_000_000},
        ]
        self.assertFalse(price_deceleration(history)["decelerating"])

    def test_recovery_is_not_a_floor(self) -> None:
        history = [
            {"day": "2026-10-21", "market_value": 10_000_000},
            {"day": "2026-10-22", "market_value": 9_000_000},
            {"day": "2026-10-23", "market_value": 9_500_000},
        ]
        trend = price_deceleration(history)
        self.assertTrue(trend["recovery"])
        self.assertFalse(trend["decelerating"])

    def test_missing_history_is_unknown(self) -> None:
        self.assertIsNone(price_deceleration([]))
        self.assertIsNone(price_deceleration([{"day": "d1", "market_value": 1}]))


class OwnershipTests(unittest.TestCase):
    def test_owner_map_from_document(self) -> None:
        squads = {"squads": [{"team_id": "9", "players": [{"player_id": "1"}, {"player_id": "2"}]}]}
        self.assertEqual(owned_player_ids(squads), {"1": "9", "2": "9"})

    def test_owner_map_accepts_a_list(self) -> None:
        self.assertEqual(owned_player_ids([{"team_id": "4", "players": [{"player_id": "7"}]}]), {"7": "4"})

    def test_no_squads_means_nobody_is_free(self) -> None:
        analyzer = MarketQuantAnalyzer([_player("1", [5, 6, 7])])
        self.assertEqual(analyzer.free_agents(), [])
        radar = analyzer.inflation_radar()
        self.assertFalse(radar["known"])
        self.assertIsNone(radar["scarce"])
        self.assertIn("plantillas", radar["recommendation"])


class MarketQuantAnalyzerTests(unittest.TestCase):
    def _squads(self, *player_ids: str) -> dict:
        return {"squads": [{"team_id": "9", "players": [{"player_id": pid} for pid in player_ids]}]}

    def test_free_agents_are_catalog_minus_squads(self) -> None:
        players = [_player("1", [6, 6, 6]), _player("2", [6, 6, 6])]
        analyzer = MarketQuantAnalyzer(players, squads=self._squads("1"))
        free = analyzer.free_agents()
        self.assertEqual([row["player_id"] for row in free], ["2"])
        self.assertTrue(free[0]["is_free_agent"])

    def test_owned_players_are_not_free(self) -> None:
        players = [_player("1", [6, 6, 6]), _player("2", [6, 6, 6])]
        analyzer = MarketQuantAnalyzer(players, squads=self._squads("1", "2"))
        self.assertEqual(analyzer.free_agents(), [])

    def test_distressed_needs_status_and_deceleration(self) -> None:
        dropping = [
            {"day": "2026-10-21", "market_value": 10_000_000},
            {"day": "2026-10-22", "market_value": 7_000_000},
            {"day": "2026-10-23", "market_value": 5_200_000},
        ]
        crashing = [
            {"day": "2026-10-21", "market_value": 10_000_000},
            {"day": "2026-10-22", "market_value": 9_000_000},
            {"day": "2026-10-23", "market_value": 5_000_000},
        ]
        players = [
            _player("1", [6, 7, 8], status="injured"),
            _player("2", [6, 7, 8], status="injured"),
            _player("3", [6, 7, 8], status="ok"),
        ]
        analyzer = MarketQuantAnalyzer(
            players,
            squads=self._squads("9"),
            price_history={"1": dropping, "2": crashing, "3": dropping},
        )
        rows = analyzer.distressed_assets()
        self.assertEqual([row["player_id"] for row in rows], ["1"])
        self.assertEqual(rows[0]["distress_kind"], "injured")
        self.assertEqual(rows[0]["floor_signal"], "suelo")

    def test_distressed_without_history_is_not_claimed(self) -> None:
        analyzer = MarketQuantAnalyzer([_player("1", [6, 7, 8], status="injured")], squads=self._squads("9"))
        self.assertEqual(analyzer.distressed_assets(), [])

    def test_suspended_also_counts_as_distressed(self) -> None:
        dropping = [
            {"day": "2026-10-21", "market_value": 9_000_000},
            {"day": "2026-10-22", "market_value": 6_000_000},
            {"day": "2026-10-23", "market_value": 4_500_000},
        ]
        analyzer = MarketQuantAnalyzer(
            [_player("1", [6, 7, 8], status="suspended")],
            squads=self._squads("9"),
            price_history={"1": dropping},
        )
        self.assertEqual(len(analyzer.distressed_assets()), 1)

    def test_inflation_flags_scarcity(self) -> None:
        # Un único top libre de 1 M: no hay talento ni liquidez.
        players = [_player("1", [8, 8, 8], value=1_000_000), _player("2", [1, 0, 0], value=1_000_000)]
        analyzer = MarketQuantAnalyzer(players, squads=self._squads("2"))
        radar = analyzer.inflation_radar()
        self.assertTrue(radar["known"])
        self.assertTrue(radar["scarce"])
        self.assertEqual(radar["flag"], "Alta Inflación Esperada")
        self.assertIn("liquidez", radar["recommendation"])

    def test_inflation_is_contained_with_abundant_talent(self) -> None:
        players = [_player(str(i), [8, 8, 8], value=200_000_000) for i in range(12)]
        analyzer = MarketQuantAnalyzer(players, squads=self._squads("99"))
        radar = analyzer.inflation_radar()
        self.assertFalse(radar["scarce"])
        self.assertEqual(radar["level"], "normal")
        self.assertEqual(radar["top_free_count"], 12)

    def test_report_has_every_section(self) -> None:
        players = [_player("1", [8, 8, 8]), _player("2", [0, 12, 0])]
        report = MarketQuantAnalyzer(players, squads=self._squads("1")).report()
        for key in ("counts", "inflation", "refuge", "risk", "distressed", "free_agents", "top_free"):
            self.assertIn(key, report)
        self.assertEqual(report["counts"]["catalog"], 2)

    def test_volatility_table_is_sorted_by_median(self) -> None:
        players = [_player("1", [1, 1, 1]), _player("2", [9, 9, 9])]
        rows = MarketQuantAnalyzer(players, squads=self._squads("9")).volatility_table()
        self.assertEqual([row["player_id"] for row in rows], ["2", "1"])


class CatalogEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(server.app)

    def _board(self, squads: dict | None = None) -> dict:
        return {
            "league_name": "Mi liga",
            "dashboard_at": "2026-10-24T10:00:00+00:00",
            "photo_age_seconds": 60.0,
            "is_stale": False,
            "stale": False,
            "squads": squads
            or {
                "league_id": "018668579",
                "squads": [{"team_id": "9", "players": [{"player_id": "1"}]}],
            },
        }

    def _players(self) -> list[dict]:
        return [
            _player("1", [8, 8, 8], value=50_000_000),
            _player("2", [7, 6, 8], value=40_000_000),
            _player("3", [0, 14, 0], value=5_000_000),
        ]

    def test_free_agents_endpoint(self) -> None:
        with (
            patch.object(server, "_board", return_value=self._board()),
            patch.object(server, "_catalog_players", return_value=self._players()),
            patch.object(server, "_catalog_price_history", return_value={}),
        ):
            response = self.client.get("/api/catalog/free-agents")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "catalog-free-agents")
        self.assertEqual(payload["count"], 2)
        self.assertEqual({row["player_id"] for row in payload["free_agents"]}, {"2", "3"})
        self.assertIn("inflation", payload)
        self.assertEqual(payload["league_id"], "018668579")

    def test_arbitrage_endpoint(self) -> None:
        dropping = [
            {"day": "2026-10-21", "market_value": 10_000_000},
            {"day": "2026-10-22", "market_value": 7_000_000},
            {"day": "2026-10-23", "market_value": 5_200_000},
        ]
        players = self._players() + [_player("4", [6, 7, 8], status="injured")]
        with (
            patch.object(server, "_board", return_value=self._board()),
            patch.object(server, "_catalog_players", return_value=players),
            patch.object(server, "_catalog_price_history", return_value={"4": dropping}),
        ):
            response = self.client.get("/api/catalog/arbitrage")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "catalog-arbitrage")
        self.assertEqual([row["player_id"] for row in payload["distressed"]], ["4"])
        self.assertIn("refuge", payload)
        self.assertIn("risk", payload)

    def test_endpoints_degrade_without_catalog(self) -> None:
        with (
            patch.object(server, "_board", return_value=self._board()),
            patch.object(server, "_catalog_players", return_value=[]),
            patch.object(server, "_catalog_price_history", return_value={}),
        ):
            free = self.client.get("/api/catalog/free-agents").json()
            arbitrage = self.client.get("/api/catalog/arbitrage").json()
        self.assertTrue(free["ok"])
        self.assertEqual(free["count"], 0)
        self.assertFalse(free["inflation"]["known"])
        self.assertTrue(arbitrage["ok"])
        self.assertEqual(arbitrage["distressed"], [])


class CachedCatalogTests(unittest.TestCase):
    """``cached_catalog`` no debe abrir sockets ni con el catálogo vacío."""

    def test_catalog_report_survives_a_missing_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"FANTASY_CACHE_DIR": tmp}):
                report = server.catalog_report({"squads": {"squads": []}})
        self.assertEqual(report["counts"]["catalog"], 0)
        self.assertEqual(report["free_agents"], [])


if __name__ == "__main__":
    unittest.main()

"""Value Investing puro: coste por punto, momentum global y supervivencia.

Todas las pruebas construyen sus propios documentos. Ni una sola toca la red:
si el motor pidiera algo, ``no_network`` lo cortaría y la prueba fallaría.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from toolbox.net import no_network
from toolbox.quant_valuation import (
    BLANK_THRESHOLD,
    MIN_GAMES,
    NameMatcher,
    build_quant_radar,
    calculate_intrinsic_value,
    detect_global_momentum,
    point_stats,
    week_series,
)


def _player(
    player_id: str,
    *,
    position: str = "3",
    value: int = 2_000_000,
    points: list[float] | None = None,
    name: str | None = None,
    team: str = "3",
) -> dict:
    """Fila con la forma exacta del catálogo público (``/competition/1/players``)."""
    weeks = points if points is not None else [4, 5, 6, 5, 4, 6]
    return {
        "id": player_id,
        "nickname": name or f"Jugador {player_id}",
        "positionId": position,
        "teamId": team,
        "marketValue": str(value),
        "averagePoints": sum(weeks) / len(weeks) if weeks else 0,
        "weekPoints": [{"weekNumber": index + 1, "points": value} for index, value in enumerate(weeks)],
        "playerStatus": "ok",
    }


class PointStatsTests(unittest.TestCase):
    def test_median_and_blank_rate_use_the_whole_series(self) -> None:
        stats = point_stats([6, 6, 0, 4, 2, 8])
        self.assertEqual(stats["games"], 6)
        self.assertEqual(stats["median_points"], 5.0)
        # <= 2 puntos: el 0 y el 2. Dos de seis.
        self.assertAlmostEqual(stats["blank_rate"], 0.3333, places=4)
        self.assertAlmostEqual(stats["floor_rate"], 0.1667, places=4)
        # Un 8 ya es techo, no suelo.
        self.assertAlmostEqual(stats["boom_rate"], 0.1667, places=4)

    def test_empty_series_is_not_zero(self) -> None:
        """Sin muestra no hay 0 puntos: hay ``None``. Un 0 falsearía la mediana."""
        stats = point_stats([])
        self.assertEqual(stats["games"], 0)
        for key in ("median_points", "mean_points", "blank_rate", "stdev_points"):
            self.assertIsNone(stats[key])

    def test_week_series_sorts_by_week_number(self) -> None:
        row = {
            "weekPoints": [
                {"weekNumber": 3, "points": 9},
                {"weekNumber": 1, "points": 1},
                {"weekNumber": 2, "points": 5},
            ]
        }
        self.assertEqual(week_series(row), [1.0, 5.0, 9.0])
        # Sin ``weekNumber`` se respeta el orden de llegada.
        self.assertEqual(week_series({"weekPoints": [4, 2, 7]}), [4.0, 2.0, 7.0])

    def test_blank_threshold_is_the_documented_one(self) -> None:
        """El umbral vive en una constante: cambiarlo cambia el veredicto."""
        self.assertEqual(BLANK_THRESHOLD, 2.0)
        stats = point_stats([2, 3])
        self.assertAlmostEqual(stats["blank_rate"], 0.5)


class IntrinsicValueTests(unittest.TestCase):
    def test_cost_per_point_is_value_over_median(self) -> None:
        catalog = [_player("1", value=3_000_000, points=[6, 6, 6, 6])]
        document = calculate_intrinsic_value(catalog)
        row = document["players"][0]
        self.assertEqual(row["median_points"], 6.0)
        self.assertEqual(row["cost_per_point_eur"], 500_000.0)
        self.assertEqual(row["points_per_million"], 2.0)
        self.assertEqual(row["points_source"], "weekPoints")
        self.assertEqual(row["club"], "Athletic Club")

    def test_cheap_player_against_expensive_one_is_undervalued(self) -> None:
        """El caso del enunciado: 2 M que puntúa como uno de 6 M."""
        catalog = [
            _player("cheap", value=2_000_000, points=[5, 6, 5, 6]),
            _player("fair", value=4_000_000, points=[5, 6, 5, 6]),
            _player("rich", value=6_000_000, points=[5, 6, 5, 6]),
        ]
        document = calculate_intrinsic_value(catalog)
        rows = {row["player_id"]: row for row in document["players"]}
        self.assertTrue(rows["cheap"]["undervalued"])
        self.assertFalse(rows["rich"]["undervalued"])
        self.assertGreater(rows["cheap"]["discount_vs_position"], 0.30)
        # La referencia es la mediana de la posición, no la media de la liga.
        # Costes por punto: 363.636 · 727.273 · 1.090.909 → mediana 727.273.
        self.assertEqual(
            document["baselines"]["MC"]["median_cost_per_point_eur"],
            727_272.73,
        )

    def test_division_by_zero_never_reaches_the_client(self) -> None:
        catalog = [
            _player("zero", value=5_000_000, points=[0, 0, 0, 0]),
            _player("nominal", value=5_000_000, points=[]),
            _player("priceless", value=0, points=[5, 5, 5]),
        ]
        with no_network():
            document = calculate_intrinsic_value(catalog)
        for row in document["players"]:
            self.assertIsNone(row["cost_per_point_eur"])
            self.assertIsNone(row["points_per_million"])
            self.assertFalse(row["undervalued"])

    def test_small_sample_is_not_a_bargain(self) -> None:
        catalog = [
            _player(f"filler-{index}", value=4_000_000, points=[5, 6, 5, 6]) for index in range(6)
        ] + [_player("rookie", value=500_000, points=[9])]
        document = calculate_intrinsic_value(catalog)
        rookie = next(row for row in document["players"] if row["player_id"] == "rookie")
        self.assertLess(rookie["games"], MIN_GAMES)
        self.assertFalse(rookie["undervalued"])
        self.assertNotEqual(rookie["points_source"], "weekPoints")

    def test_average_points_fill_gaps_but_are_labelled(self) -> None:
        """Sin serie, la media oficial sirve de referencia y se marca como tal."""
        row = {"id": "7", "positionId": "4", "marketValue": "1000000", "averagePoints": 4.0}
        document = calculate_intrinsic_value([row])
        player = document["players"][0]
        self.assertEqual(player["median_points"], 4.0)
        self.assertEqual(player["points_source"], "averagePoints")
        self.assertFalse(player["undervalued"])


class MomentumTests(unittest.TestCase):
    def test_positive_acceleration_is_smart_money(self) -> None:
        market = {
            "players": [
                {"player_id": "1", "price_delta": 100_000, "acceleration": 25_000},
                {"player_id": "2", "price_delta": 100_000, "acceleration": -25_000},
                {"player_id": "3", "price_delta": -100_000, "acceleration": 25_000},
                {"player_id": "4"},
            ]
        }
        with no_network():
            momentum = detect_global_momentum(market)
        signals = {row["player_id"]: row for row in momentum["players"]}
        self.assertTrue(signals["1"]["smart_money"])
        self.assertFalse(signals["2"]["smart_money"])
        # Acelera, pero el precio baja: no es acumulación.
        self.assertFalse(signals["3"]["smart_money"])
        self.assertIsNone(signals["4"]["smart_money"])
        self.assertEqual([row["player_id"] for row in momentum["smart_money"]], ["1"])
        self.assertAlmostEqual(signals["1"]["relative_acceleration"], 0.25, places=4)

    def test_catalog_rows_extend_the_league_snapshot(self) -> None:
        market = {"players": [{"player_id": "1", "price_delta": 1_000, "acceleration": 500}]}
        global_rows = [
            {"player_id": "99", "price_delta": 900_000, "acceleration": 400_000},
            # Ruido: ni acelera ni sube.
            {"player_id": "98", "price_delta": 0, "acceleration": 0},
        ]
        momentum = detect_global_momentum(market, catalog=global_rows)
        smart = [row["player_id"] for row in momentum["smart_money"]]
        self.assertEqual(smart, ["99", "1"])
        self.assertEqual(momentum["counts"]["players"], 3)
        self.assertEqual(momentum["counts"]["smart_money"], 2)

    def test_league_signal_wins_over_global_duplicate(self) -> None:
        market = {"players": [{"player_id": "1", "price_delta": 5_000, "acceleration": 1_000}]}
        momentum = detect_global_momentum(
            market,
            catalog=[{"player_id": "1", "price_delta": 999_999, "acceleration": 888_888}],
        )
        row = momentum["players"][0]
        self.assertEqual(row["price_delta"], 5_000)
        self.assertEqual(row["origin"], "trends")

    def test_no_source_is_not_a_signal(self) -> None:
        momentum = detect_global_momentum(None)
        self.assertEqual(momentum["source"], "none")
        self.assertEqual(momentum["smart_money"], [])
        self.assertEqual(momentum["counts"]["players"], 0)


class NameMatcherTests(unittest.TestCase):
    def test_full_name_matches_short_nickname(self) -> None:
        catalog = [
            {"id": "680", "nickname": "Moi Gómez", "name": "Moisés Gómez", "positionId": "3"},
            {"id": "1", "nickname": "Sivera", "name": "Antonio Sivera", "positionId": "1"},
        ]
        matcher = NameMatcher(catalog)
        player, score = matcher.match("Antonio Sivera", "POR")
        self.assertIsNotNone(player)
        self.assertEqual(player["id"], "1")
        self.assertGreaterEqual(score, 0.9)

    def test_unknown_surname_returns_nothing(self) -> None:
        matcher = NameMatcher([{"id": "1", "nickname": "Sivera", "positionId": "1"}])
        player, score = matcher.match("Nombre Inexistente", "POR")
        self.assertIsNone(player)
        self.assertEqual(score, 0.0)


class QuantRadarTests(unittest.TestCase):
    def _board(self) -> dict:
        return {
            "market": {
                "listings": [
                    {
                        "player_id": "cheap",
                        "sale_price": 1_500_000,
                        "seller_team_id": "rival-1",
                        "seller_manager": "Rival",
                    }
                ]
            },
            "squads": {
                "squads": [
                    {
                        "team_id": "me",
                        "is_self": True,
                        "manager_name": "Yo",
                        "players": [{"player_id": "mine"}],
                    }
                ]
            },
            "trends": {
                "players": [
                    {"player_id": "cheap", "price_delta": 200_000, "acceleration": 50_000},
                    {"player_id": "steady", "price_delta": 5_000, "acceleration": -1_000},
                ]
            },
            "flip": {"cash_eur": 2_000_000},
        }

    def _catalog(self) -> list[dict]:
        return [
            _player("cheap", value=2_000_000, points=[5, 6, 5, 6]),
            _player("steady", value=4_000_000, points=[5, 6, 5, 6]),
            _player("rich", value=6_000_000, points=[5, 6, 5, 6]),
            _player("mine", value=1_500_000, points=[5, 6, 5, 6]),
            _player("toxic", value=800_000, points=[0, 1, 0, 9]),
            _player("unknown", value=1_000_000, points=[]),
        ]

    def test_radar_returns_a_prioritised_buy_list(self) -> None:
        with no_network():
            radar = build_quant_radar(self._board(), catalog=self._catalog(), limit=5)
        self.assertTrue(radar["ok"])
        self.assertEqual(radar["sources"]["network"], "none")
        self.assertEqual(radar["cash_eur"], 2_000_000)

        buys = radar["buys"]
        self.assertEqual([row["player_id"] for row in buys], ["cheap"])
        buy = buys[0]
        self.assertEqual(buy["verdict"], "COMPRAR")
        self.assertTrue(buy["smart_money"])
        self.assertTrue(buy["affordable"])
        self.assertTrue(buy["on_market"])
        self.assertIn("smart_money", buy["reasons"])
        self.assertIn("infravalorado", buy["reasons"])

        # El caro no está infravalorado; el tóxico cae por blank_rate.
        verdicts = {row["player_id"]: row["verdict"] for row in radar["candidates"]}
        self.assertNotEqual(verdicts.get("rich"), "COMPRAR")
        toxic = next(row for row in radar["toxic"] if row["player_id"] == "toxic")
        self.assertIn("blank_rate_alto", toxic["reasons"])
        self.assertGreater(toxic["blank_rate"], 0.4)

    def test_owned_player_is_never_a_signing(self) -> None:
        radar = build_quant_radar(self._board(), catalog=self._catalog(), limit=5)
        candidates = {row["player_id"]: row for row in radar["candidates"]}
        mine = candidates["mine"]
        self.assertEqual(mine["owner"], "propio")
        self.assertEqual(mine["verdict"], "NO_FICHABLE")
        self.assertIn("ya_en_plantilla", mine["reasons"])

    def test_listing_price_beats_market_value(self) -> None:
        radar = build_quant_radar(self._board(), catalog=self._catalog(), limit=5)
        cheap = radar["buys"][0]
        self.assertEqual(cheap["market_value"], 2_000_000)
        self.assertEqual(cheap["sale_price"], 1_500_000)
        # Lo que se paga es el anuncio, no la tasación.
        self.assertEqual(cheap["effective_price"], 1_500_000)

    def test_radar_never_touches_the_network(self) -> None:
        """El veto es la prueba: cualquier GET revienta dentro del bloque."""
        with no_network():
            radar = build_quant_radar(self._board(), catalog=self._catalog(), limit=5)
        self.assertEqual(radar["sources"]["network"], "none")

    def test_momentum_block_is_public_and_marked(self) -> None:
        radar = build_quant_radar(self._board(), catalog=self._catalog(), limit=5)
        smart = radar["momentum"]["smart_money"]
        self.assertEqual([row["player_id"] for row in smart], ["cheap"])
        self.assertTrue(smart[0]["smart_money"])
        self.assertEqual(smart[0]["verdict"], "COMPRAR")
        self.assertEqual(radar["summary"]["smart_money"], 1)

    def test_empty_board_degrades_without_inventing_players(self) -> None:
        radar = build_quant_radar({}, catalog=[], limit=5)
        self.assertTrue(radar["ok"])
        self.assertEqual(radar["buys"], [])
        self.assertEqual(radar["candidates"], [])
        self.assertEqual(radar["summary"]["scanned"], 0)
        self.assertIsNone(radar["cash_eur"])


class QuantRadarEndpointTests(unittest.TestCase):
    """/api/market/quant-radar sirve la foto: no descarga ni inventa datos."""

    def _catalog(self) -> list[dict]:
        return QuantRadarTests()._catalog()

    def test_endpoint_serves_the_cached_photo(self) -> None:
        from fastapi.testclient import TestClient

        import server

        board = QuantRadarTests()._board()
        request = TestClient(server.app)
        with patch.object(server, "_board", return_value=board):
            # El enriquecimiento de tendencias lee la foto completa de disco:
            # aquí no aplica, la foto de prueba ya trae sus señales.
            with patch.object(server, "_enrich_board_trends", side_effect=lambda value, _league: value):
                with patch("toolbox.quant_valuation.cached_catalog", return_value=self._catalog()):
                    response = request.get("/api/market/quant-radar?limit=5")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "quant-radar")
        self.assertEqual(payload["sources"]["network"], "none")
        self.assertEqual([row["player_id"] for row in payload["buys"]], ["cheap"])
        self.assertIn("baselines", payload)
        self.assertIn("momentum", payload)

    def test_endpoint_rejects_a_silly_limit(self) -> None:
        from fastapi.testclient import TestClient

        import server

        request = TestClient(server.app)
        # ``limit=0`` no es una lista vacía: es una petición mal formada.
        self.assertEqual(request.get("/api/market/quant-radar?limit=0").status_code, 422)
        self.assertEqual(request.get("/api/market/quant-radar?limit=99").status_code, 422)


if __name__ == "__main__":
    unittest.main()

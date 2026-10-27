"""Parsers de Analítica Fantasy. Sin red."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from toolbox.analitica_fantasy import (
    AfBidRow,
    AfBundle,
    AfMarketRow,
    AfPointsRow,
    AfPredictionRow,
    apply_analitica_fantasy,
    parse_calendar,
    parse_form_players,
    parse_ideal_bids,
    parse_market_players,
    parse_market_predictions,
    parse_points_predictions,
    parse_set_pieces,
    parse_status_players,
)
from toolbox.cache import EntityStore
from toolbox.matching import CanonicalPlayer, EntityResolver


MARKET_HTML = r"""
<script>
self.__next_f.push([1,"88:[\"$\",\"$L9c\",null,{\"initialPlayers\":[{\"nickname\":\"Diomande\",\"masterPlayerId\":513776,\"positionId\":4,\"marketValue\":78255651,\"subida\":2045493,\"teamName\":\"Real Madrid\",\"titularityPercent\":70},{\"nickname\":\"Koski\",\"masterPlayerId\":106759,\"positionId\":2,\"marketValue\":36516902,\"subida\":-500000,\"teamName\":\"Alaves\",\"titularityPercent\":70}]}]"])
</script>
"""

BID_HTML = r"""
<script>
\"initialPlayers\":[
  {\"name\":\"Diomande\",\"id\":513776,\"marketValue\":78255651,\"pujaIdeal\":78404383,\"pujaMaxima\":79000000,\"subida\":2045493,\"positionId\":4,\"chance\":70,\"club\":{\"id\":541,\"name\":\"Real Madrid\"},\"expectedPoints\":9.49}
]
</script>
"""

PREDICTION_HTML = """
<script type="application/ld+json">
[
  {
    "@type": "ItemList",
    "name": "Predicción de subidas — La Liga Fantasy DAZN",
    "itemListElement": [
      {
        "@type": "ListItem",
        "item": {
          "@type": "Person",
          "name": "Lamine Yamal",
          "additionalProperty": [
            {"@type": "PropertyValue", "name": "Valor de mercado", "value": 193923095},
            {"@type": "PropertyValue", "name": "Subida diaria", "value": 2114487},
            {"@type": "PropertyValue", "name": "Probabilidad", "value": 16}
          ]
        }
      }
    ]
  },
  {
    "@type": "ItemList",
    "name": "Predicción de bajadas — La Liga Fantasy DAZN",
    "itemListElement": [
      {
        "@type": "ListItem",
        "item": {
          "@type": "Person",
          "name": "Aubameyang",
          "additionalProperty": [
            {"@type": "PropertyValue", "name": "Valor de mercado", "value": 54874763},
            {"@type": "PropertyValue", "name": "Subida diaria", "value": -1329022},
            {"@type": "PropertyValue", "name": "Probabilidad", "value": 22}
          ]
        }
      }
    ]
  }
]
</script>
"""

POINTS_HTML = r"""
<script>
\"players\":[
  {\"playerId\":386828,\"playerName\":\"Lamine Yamal\",\"position\":\"Delantero\",\"positionId\":4,\"predictedPoints\":15.73,\"ceilingPoints\":24.34,\"playerTeamId\":529,\"homeTeamId\":543,\"homeTeamName\":\"Real Betis\",\"awayTeamId\":529,\"awayTeamName\":\"Barcelona\",\"chance\":80,\"goalProbability\":0.36,\"assistProbability\":0.29,\"pointsPerMillion\":0.08,\"marketValue\":193000000}
]
</script>
"""

STATUS_HTML = r"""
<script>
\"initialPlayers\":[
  {\"playerId\":50,\"playerName\":\"Koke\",\"teamName\":\"Atletico Madrid\",\"status\":\"injured\",\"statusInfo\":\"Lesión muscular\",\"report\":\"Baja para la jornada 10\",\"injuryStartDate\":\"2026-10-15\",\"expectedReturnDate\":null,\"isSanctioned\":false}
]
</script>
"""

FORM_HTML = """
<a class="af-link" href="/jugadores/lamine-yamal-386828/fantasy/la-liga-fantasy">
<article>
<h3>Lamine Yamal</h3>
<p>Media reciente <!-- -->15.8<!-- --> puntos</p>
<span>4<!-- --> señales</span>
<div title="6 jornadas seguidas con 10+ puntos"></div>
<div title="Media de 15.8 puntos"></div>
</article>
</a>
"""

SETPIECE_HTML = """
<span>Directas</span><span>Principal#15</span><span>Abde Rebbach</span>
<span>Penaltis</span><span>Principal#9</span><span>Toni Martínez</span>
"""

CALENDAR_HTML = r"""
{\"matchday\":1,\"round\":\"Regular Season - 10\",\"fixtureId\":100012040,\"fixtureDate\":\"2026-10-23T19:00:00+00:00\",\"opponentId\":4665,\"opponentName\":\"Racing Santander\",\"isHome\":true,\"predictedScore\":\"7-2\",\"predictedHome\":7,\"predictedAway\":2,\"winProb\":1,\"drawProb\":0,\"lossProb\":0,\"recommendationPct\":99,\"difficulty\":\"very_easy\",\"hasPrediction\":true},\"teamId\":529,\"teamName\":\"Barcelona\"
"""


class AnaliticaFantasyParsersTest(unittest.TestCase):
    def test_market(self) -> None:
        rows = {row.name: row for row in parse_market_players(MARKET_HTML)}
        self.assertIn("Diomande", rows)
        self.assertEqual(rows["Diomande"].price_delta, 2045493)
        self.assertEqual(rows["Diomande"].p_titular, 0.7)
        self.assertEqual(rows["Koski"].price_delta, -500000)

    def test_ideal_bid(self) -> None:
        rows = parse_ideal_bids(BID_HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ideal_bid, 78404383)
        self.assertEqual(rows[0].max_bid, 79000000)
        self.assertEqual(rows[0].club, "Real Madrid")

    def test_prediction_jsonld(self) -> None:
        rows = parse_market_predictions(PREDICTION_HTML)
        by_name = {row.name: row for row in rows}
        self.assertEqual(by_name["Lamine Yamal"].direction, "up")
        self.assertEqual(by_name["Lamine Yamal"].signal_strength, 0.16)
        self.assertEqual(by_name["Aubameyang"].direction, "down")
        self.assertEqual(by_name["Aubameyang"].predicted_delta, -1329022)

    def test_points(self) -> None:
        rows = parse_points_predictions(POINTS_HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].predicted_points, 15.73)
        self.assertEqual(rows[0].club, "Barcelona")

    def test_status(self) -> None:
        rows = parse_status_players(STATUS_HTML)
        self.assertEqual(rows[0].status, "injured")
        self.assertIn("muscular", rows[0].status_info or "")

    def test_form_html(self) -> None:
        rows = parse_form_players(FORM_HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].recent_average, 15.8)
        self.assertEqual(rows[0].signal_count, 4)
        self.assertEqual(rows[0].external_id, "386828")

    def test_set_pieces(self) -> None:
        rows = parse_set_pieces(SETPIECE_HTML)
        roles = {(row.name, row.role) for row in rows}
        self.assertIn(("Abde Rebbach", "direct"), roles)
        self.assertIn(("Toni Martínez", "penalties"), roles)

    def test_calendar(self) -> None:
        cells = parse_calendar(CALENDAR_HTML)
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].team_name, "Barcelona")
        self.assertEqual(cells[0].recommendation_pct, 99)

    def test_apply_enriches_players(self) -> None:
        catalog = [
            CanonicalPlayer(
                player_id="p1",
                name="Diomande",
                nickname="Diomande",
                club="Real Madrid",
                position="DEL",
                fantasy_price=70_000_000,
            ),
            CanonicalPlayer(
                player_id="p2",
                name="Lamine Yamal",
                nickname="Lamine Yamal",
                club="Barcelona",
                position="DEL",
                fantasy_price=190_000_000,
            ),
        ]
        players = [
            {
                "player_id": "p1",
                "name": "Diomande",
                "club": "Real Madrid",
                "sanction": {"yellow_cards": None, "on_verge": False, "suspended": False},
            },
            {
                "player_id": "p2",
                "name": "Lamine Yamal",
                "club": "Barcelona",
                "sanction": {"yellow_cards": None, "on_verge": False, "suspended": False},
            },
        ]
        bundle = AfBundle(
            market=[AfMarketRow(name="Diomande", club="Real Madrid", price_delta=100, external_id="513776")],
            bids=[AfBidRow(name="Diomande", club="Real Madrid", ideal_bid=50, max_bid=60, external_id="513776")],
            predictions=[
                AfPredictionRow(name="Lamine Yamal", direction="up", signal_strength=0.2, predicted_delta=1_000_000)
            ],
            points=[AfPointsRow(name="Lamine Yamal", predicted_points=12.5, points_per_million=0.1)],
        )
        with tempfile.TemporaryDirectory() as directory:
            store = EntityStore(Path(directory))
            try:
                resolver = EntityResolver(store)
                _decisions, summary = apply_analitica_fantasy(catalog, resolver, bundle, players)
            finally:
                store.close()
        by_id = {row["player_id"]: row for row in players}
        self.assertEqual(by_id["p1"].get("af_ideal_bid"), 50)
        self.assertEqual(by_id["p1"].get("af_price_delta"), 100)
        self.assertEqual(by_id["p2"].get("af_market_signal"), "up")
        self.assertEqual(by_id["p2"].get("af_expected_points"), 12.5)
        self.assertTrue(summary["prediction_rising"])
        self.assertTrue(summary["oracle_points"])


if __name__ == "__main__":
    unittest.main()

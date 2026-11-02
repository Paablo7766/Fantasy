"""Parsers y ajustes de Understat, Jornada Perfecta, minutos y FDR."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from toolbox.jornada_perfecta import parse_market_caching
from toolbox.matching import normalize_club
from toolbox.understat import (
    fdr_from_opponent_xga,
    next_fixtures,
    parse_openfootball_matchdays,
    parse_understat_payload,
    points_multiplier,
)


UNDERSTAT = {
    "teams": {
        "1": {
            "id": "1",
            "title": "Real Sociedad",
            "history": [{"xG": 1.0, "xGA": 0.5}, {"xG": 1.2, "xGA": 0.7}],
        },
        "2": {
            "id": "2",
            "title": "Celta Vigo",
            "history": [{"xG": 1.0, "xGA": 1.8}, {"xG": 0.8, "xGA": 1.6}],
        },
    },
    "players": [
        {
            "id": "9",
            "player_name": "Brais Méndez",
            "games": "10",
            "time": "450",
            "xG": "2.5",
            "xA": "1.0",
            "key_passes": "12",
            "position": "M",
            "team_title": "Real Sociedad",
        }
    ],
    "dates": [
        {
            "id": "m1",
            "isResult": False,
            "h": {"id": "1", "title": "Real Sociedad"},
            "a": {"id": "2", "title": "Celta Vigo"},
            "datetime": "2099-06-01 20:00:00",
        }
    ],
}

JP_PAGE = """
<script>
const marketCaching=[{"playerId":"7","name":"Aspas","real_name":"Iago Aspas","position":"delantero","team":"Celta","tip":"apuesta","racha":"2","injured":"0","doubt":"0","status":"check"}];
</script>
"""


class IntelSourcesTest(unittest.TestCase):
    def test_understat_players_and_fdr(self) -> None:
        players, strengths, dates = parse_understat_payload(UNDERSTAT)
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0]["xg"], 2.5)
        self.assertEqual(players[0]["xa"], 1.0)
        self.assertEqual(players[0]["minutes"], 450)
        self.assertAlmostEqual(players[0]["minutes_pct"], 0.5)
        fixtures = next_fixtures(dates, strengths, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertIn("real sociedad", fixtures)
        home = fixtures["real sociedad"]
        self.assertTrue(home.home)
        self.assertEqual(home.opponent, "Celta Vigo")
        self.assertGreaterEqual(home.fdr, 4)
        self.assertEqual(fdr_from_opponent_xga(1.7, 1.0), 5)
        self.assertEqual(points_multiplier(fdr=5, home=True), round(1.2 * 1.05, 4))

    def test_jornada_perfecta_tips(self) -> None:
        rows = parse_market_caching(JP_PAGE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Iago Aspas")
        self.assertEqual(rows[0]["jp_tip"], "apuesta")
        self.assertEqual(rows[0]["jp_projected_points"], 5.5)
        self.assertEqual(rows[0]["jp_multiplier"], 1.0)

    def test_openfootball_names_share_the_understat_key(self) -> None:
        self.assertEqual(normalize_club("CA Osasuna"), "osasuna")
        self.assertEqual(normalize_club("C.A. Osasuna"), "osasuna")
        self.assertEqual(normalize_club("R. Racing Club"), "racing")
        self.assertEqual(normalize_club("Real Racing Club de Santander"), "racing")
        self.assertEqual(normalize_club("RC Celta de Vigo"), "celta")
        self.assertEqual(normalize_club("Rayo Vallecano de Madrid"), "rayo")
        self.assertEqual(normalize_club("Real Sociedad de Fútbol"), "real sociedad")

    def test_split_matchday_keeps_the_official_number(self) -> None:
        text = """
Matchday 1
  Sat Aug 15 2026
    19:30  Deportivo Alavés v Getafe CF 3-0
Matchday 2
    21:00  Rayo Vallecano de Madrid v Deportivo Alavés 1-1
Matchday 1
    21:00  FC Barcelona v Athletic Club 2-0
"""
        table = parse_openfootball_matchdays(text)
        self.assertEqual(table[("alaves", "getafe")], 1)
        self.assertEqual(table[("rayo", "alaves")], 2)
        self.assertEqual(table[("barcelona", "athletic")], 1)


if __name__ == "__main__":
    unittest.main()

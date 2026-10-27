"""Parsers y ajustes de Understat, Jornada Perfecta, minutos y FDR."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from toolbox.analyzer import expected_opta_points
from toolbox.jornada_perfecta import parse_market_caching
from toolbox.understat import (
    fdr_from_opponent_xga,
    next_fixtures,
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

    def test_expected_points_applies_minutes_and_fdr(self) -> None:
        base, _ = expected_opta_points("MC", {"xg": 2.0, "xa": 1.0})
        low_minutes, components = expected_opta_points(
            "MC",
            {"xg": 2.0, "xa": 1.0, "minutes_pct": 0.3, "fdr": 5, "home": True, "jp_multiplier": 1.06},
        )
        self.assertGreater(base, 0)
        self.assertLess(low_minutes, base)
        self.assertIn("minutes_factor", components)
        self.assertIn("fixture_factor", components)
        self.assertIn("jp_factor", components)


if __name__ == "__main__":
    unittest.main()

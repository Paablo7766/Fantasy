"""Fase 2A: ingesta de cuotas y rolling xG → proyección híbrida."""

from __future__ import annotations

import unittest

from toolbox.scrapers import (
    MatchOddsBundle,
    build_simulated_match_odds_index,
    match_odds_key,
    parse_the_odds_api_payload,
)
from toolbox.own_intel import build_team_calendar_cell
from toolbox.understat import (
    FixtureInfo,
    TeamRollingWindow,
    TeamStrength,
    build_hybrid_match_projection,
    rolling_window_from_history,
    stat_lambdas_for_fixture,
    team_rolling_windows_from_payload,
)


UNDERSTAT_ROLLING = {
    "teams": {
        "1": {
            "title": "Real Sociedad",
            "history": [
                {"xG": 0.8, "xGA": 1.4},
                {"xG": 1.0, "xGA": 1.2},
                {"xG": 1.6, "xGA": 0.9},
                {"xG": 2.0, "xGA": 1.0},
                {"xG": 1.8, "xGA": 0.7},
            ],
        },
        "2": {
            "title": "Celta Vigo",
            "history": [
                {"xG": 1.1, "xGA": 1.5},
                {"xG": 0.9, "xGA": 1.6},
                {"xG": 1.0, "xGA": 1.3},
                {"xG": 1.2, "xGA": 1.1},
                {"xG": 0.7, "xGA": 1.8},
            ],
        },
    }
}


class RollingOddsPipelineTests(unittest.TestCase):
    def test_rolling_window_recent_first(self) -> None:
        windows = team_rolling_windows_from_payload(UNDERSTAT_ROLLING)
        sociedad = windows["real sociedad"]
        self.assertEqual(len(sociedad.last5_xg), 5)
        self.assertAlmostEqual(sociedad.last5_xg[0], 1.8)

    def test_simulated_odds_and_hybrid_projection(self) -> None:
        strengths = {
            "real sociedad": TeamStrength("1", "Real Sociedad", 1.4, 1.0, 5),
            "celta vigo": TeamStrength("2", "Celta Vigo", 1.0, 1.5, 5),
        }
        rolling = team_rolling_windows_from_payload(UNDERSTAT_ROLLING)
        fixtures = {
            "real sociedad": FixtureInfo(
                opponent="Celta Vigo",
                opponent_id="2",
                home=True,
                kickoff="2099-06-01T20:00:00+00:00",
                fdr=4,
                opponent_xga=1.5,
                opponent_xg=1.0,
            )
        }
        odds_index = build_simulated_match_odds_index(
            fixtures,
            strengths=strengths,
            team_rolling=rolling,
        )
        key = match_odds_key("Real Sociedad", "Celta Vigo")
        self.assertIn(key, odds_index)
        bundle = odds_index[key]
        self.assertEqual(len(bundle["odds_1x2"]), 3)

        home_roll = rolling["real sociedad"]
        away_roll = rolling["celta vigo"]
        lh, la = stat_lambdas_for_fixture(
            home_team=strengths["real sociedad"],
            away_team=strengths["celta vigo"],
            home_rolling=home_roll,
            away_rolling=away_roll,
            league_avg_xg=1.25,
        )
        self.assertEqual(home_roll.sample_size, 5)
        self.assertAlmostEqual(home_roll.last5_xg[0], 1.8)

        proj = build_hybrid_match_projection(
            lh,
            la,
            odds_1x2=tuple(bundle["odds_1x2"]),
            odds_ou25=tuple(bundle["odds_ou25"]) if bundle.get("odds_ou25") else None,
            odds_btts=tuple(bundle["odds_btts"]) if bundle.get("odds_btts") else None,
            hours_to_kickoff=36.0,
        )
        self.assertGreater(proj.lambda_home, 0.2)
        self.assertGreater(proj.p_home_win, 0.0)

        cell = build_team_calendar_cell(
            team_name="Real Sociedad",
            fixture=fixtures["real sociedad"],
            team=strengths["real sociedad"],
            opponent=strengths["celta vigo"],
            league_avg_xg=1.25,
            odds_1x2=tuple(bundle["odds_1x2"]),
            odds_ou25=tuple(bundle["odds_ou25"]),
            odds_btts=tuple(bundle["odds_btts"]),
            home_rolling=home_roll,
            away_rolling=away_roll,
            hours_to_kickoff=36.0,
        )
        self.assertIsNotNone(cell.get("market_weight"))
        self.assertGreater(cell["recommendation_pct"], 0)

    def test_parse_the_odds_api_payload(self) -> None:
        payload = [
            {
                "home_team": "Barcelona",
                "away_team": "Sevilla",
                "bookmakers": [
                    {
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Barcelona", "price": 1.55},
                                    {"name": "Sevilla", "price": 5.5},
                                    {"name": "Draw", "price": 4.2},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": 1.85, "point": 2.5},
                                    {"name": "Under", "price": 2.0, "point": 2.5},
                                ],
                            },
                            {
                                "key": "btts",
                                "outcomes": [
                                    {"name": "Yes", "price": 1.72},
                                    {"name": "No", "price": 2.1},
                                ],
                            },
                        ]
                    }
                ],
            }
        ]
        index = parse_the_odds_api_payload(payload)
        key = match_odds_key("Barcelona", "Sevilla")
        self.assertIn(key, index)
        row = index[key]
        self.assertEqual(row["source"], "the_odds_api")
        bundle = MatchOddsBundle(
            match_key=key,
            odds_1x2=tuple(row["odds_1x2"]),
            odds_ou25=tuple(row["odds_ou25"]) if row.get("odds_ou25") else None,
            odds_btts=tuple(row["odds_btts"]) if row.get("odds_btts") else None,
            source="the_odds_api",
        )
        proj = build_hybrid_match_projection(1.5, 1.1, odds_1x2=bundle.odds_1x2, hours_to_kickoff=24.0)
        self.assertGreater(proj.lambda_home, 0.2)


if __name__ == "__main__":
    unittest.main()

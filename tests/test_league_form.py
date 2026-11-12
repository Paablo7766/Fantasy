"""Forma por jornada: cruce de nombres, medias y tendencia."""

from __future__ import annotations

import unittest

from toolbox.league_form import build_league_form, load_rounds

SQUADS = {
    "squads": [
        {"team_id": "1", "manager_name": "paaabsnz", "fantasy_team_name": "Mi Equipo", "is_self": True, "error": None},
        {"team_id": "2", "manager_name": "Ana", "fantasy_team_name": "PABS FC", "error": None},
    ]
}


class LeagueFormTest(unittest.TestCase):
    def test_matches_by_manager_or_team_name_and_reports_unmatched(self) -> None:
        rounds = {9: {"paaabsnz": 28, "pabs fc": 47, "Fantasma": 5}, 10: {"paaabsnz": 43, "pabs fc": 47, "Fantasma": 1}}
        form = build_league_form(SQUADS, rounds)
        self.assertEqual(form["unmatched"], ["Fantasma"])
        by_id = {row["team_id"]: row for row in form["rows"]}
        self.assertEqual(by_id["1"]["total"], 71)
        self.assertTrue(by_id["1"]["is_self"])
        self.assertEqual(by_id["2"]["total"], 94)

    def test_recent_average_trend_and_tied_rank(self) -> None:
        rounds = {9: {"paaabsnz": 20, "Ana": 20}, 10: {"paaabsnz": 30, "Ana": 10}, 11: {"paaabsnz": 40, "Ana": 40}}
        rows = {row["team_id"]: row for row in build_league_form(SQUADS, rounds)["rows"]}
        self.assertEqual(rows["1"]["recent_avg"], 30.0)
        self.assertEqual(rows["1"]["trend"], 15.0)  # 40 frente a la media 25
        self.assertEqual([item["rank"] for item in rows["2"]["rounds"]], [1, 2, 1])
        self.assertEqual(rows["1"]["rounds"][0]["rank"], 1)  # empate en la J9
        self.assertEqual(rows["1"]["form_rank"], 1)

    def test_no_data_is_not_ok(self) -> None:
        self.assertFalse(build_league_form(SQUADS, {})["ok"])

    def test_shipped_file_has_complete_rounds(self) -> None:
        rounds = load_rounds()
        self.assertEqual(sorted(rounds), [9, 10, 11, 12])
        self.assertTrue(all(len(rows) == 10 for rows in rounds.values()))
        self.assertEqual(sum(rounds[11].values()), 454)
        self.assertEqual(sum(rounds[12].values()), 489)


if __name__ == "__main__":
    unittest.main()

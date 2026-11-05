"""La proyección de cada once lleva los 11 jugadores para el cara a cara."""

from __future__ import annotations

import unittest

from toolbox.league_race import build_league_race

_SHAPE = {"POR": 1, "DEF": 4, "MC": 4, "DEL": 2}


def _squad(team_id: str, rank: int, points: int, prefix: str, *, is_self: bool = False) -> dict:
    players = []
    for position, count in _SHAPE.items():
        for index in range(count + 1):
            players.append(
                {
                    "player_id": f"{prefix}{position}{index}",
                    "nickname": f"{prefix}-{position}-{index}",
                    "position": position,
                    "status": "ok",
                    "p_titular": 0.9,
                    "average_points": 4.0,
                    "week_points": [4, 5, 3, 6, 4],
                }
            )
    return {
        "team_id": team_id,
        "is_self": is_self,
        "manager_name": f"M{team_id}",
        "rank": rank,
        "points": points,
        "cash": 1_000_000,
        "players": players,
        "error": None,
    }


class LeagueRaceXiTest(unittest.TestCase):
    def test_projection_carries_the_eleven(self) -> None:
        document = {
            "league_id": "L",
            "squads": [_squad("1", 2, 100, "a", is_self=True), _squad("2", 1, 110, "b")],
        }
        race = build_league_race(document, None, None)
        for row in race["rivals"]:
            xi = row["projection"]["xi"]
            if row["projection"]["expected_points"] is None:
                continue
            self.assertEqual(len(xi), 11)
            self.assertTrue(all({"player_id", "name", "position", "expected_points"} <= set(item) for item in xi))

    def test_own_xi_comes_from_optimize_when_available(self) -> None:
        document = {"league_id": "L", "squads": [_squad("1", 1, 100, "a", is_self=True), _squad("2", 2, 90, "b")]}
        optimize = {
            "ok": True,
            "xi": [
                {"player_id": "x", "nickname": "Equis", "position": "DEL", "jornada_ev": 7.123, "club": "FCB"},
            ],
            "formation": "4-4-2",
            "lineup_expected_points": 7.12,
        }
        race = build_league_race(document, None, optimize)
        mine = race["my_projection"]
        if mine and mine.get("source") == "optimize":
            self.assertEqual(mine["xi"][0]["name"], "Equis")
            self.assertEqual(mine["xi"][0]["expected_points"], 7.12)


if __name__ == "__main__":
    unittest.main()

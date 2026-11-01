"""Evolución del valor de la plantilla para la pestaña Cartera."""

from __future__ import annotations

import unittest
from unittest import mock

import server
from toolbox.portfolio import squad_value_history


def _snap(day: str, value: int) -> dict:
    return {"day": day, "market_value": value}


class SquadValueHistoryTests(unittest.TestCase):
    def test_sums_current_holdings_per_day(self) -> None:
        players = [{"player_id": "a"}, {"player_id": "b"}]
        history = {
            "a": [_snap("2026-10-30", 1_000_000), _snap("2026-10-31", 1_100_000)],
            "b": [_snap("2026-10-30", 2_000_000), _snap("2026-10-31", 1_900_000)],
            "z": [_snap("2026-10-31", 9_000_000)],
        }
        rows = squad_value_history(players, history)
        self.assertEqual([row["day"] for row in rows], ["2026-10-30", "2026-10-31"])
        self.assertEqual([row["value_eur"] for row in rows], [3_000_000, 3_000_000])
        self.assertEqual(rows[-1]["coverage"], 1.0)

    def test_carries_last_known_value_forward(self) -> None:
        players = [{"player_id": "a"}, {"player_id": "b"}]
        history = {
            "a": [_snap("2026-10-29", 1_000_000), _snap("2026-10-31", 1_500_000)],
            "b": [_snap("2026-10-29", 2_000_000), _snap("2026-10-30", 2_200_000)],
        }
        rows = squad_value_history(players, history)
        by_day = {row["day"]: row["value_eur"] for row in rows}
        self.assertEqual(by_day["2026-10-30"], 3_200_000)
        self.assertEqual(by_day["2026-10-31"], 3_700_000)

    def test_skips_days_with_low_coverage(self) -> None:
        players = [{"player_id": pid} for pid in ("a", "b", "c")]
        history = {
            "a": [_snap("2026-10-28", 1_000_000), _snap("2026-10-29", 1_000_000)],
            "b": [_snap("2026-10-29", 1_000_000)],
            "c": [_snap("2026-10-29", 1_000_000)],
        }
        rows = squad_value_history(players, history)
        self.assertEqual([row["day"] for row in rows], ["2026-10-29"])

    def test_empty_inputs(self) -> None:
        self.assertEqual(squad_value_history([], {"a": [_snap("2026-10-29", 1)]}), [])
        self.assertEqual(squad_value_history([{"player_id": "a"}], None), [])
        self.assertEqual(squad_value_history([{"player_id": "a"}], {"a": [{"day": "x", "market_value": True}]}), [])

    def test_shape_squads_publishes_value_history(self) -> None:
        board = {
            "squads": {
                "ok": True,
                "league_id": "L1",
                "squads": [
                    {
                        "team_id": "t1",
                        "is_self": True,
                        "manager_name": "Yo",
                        "players": [{"player_id": "a", "nickname": "Alpha", "market_value": 1_200_000}],
                    }
                ],
            }
        }
        history = {"a": [_snap("2026-10-30", 1_000_000), _snap("2026-10-31", 1_200_000)]}
        store = mock.Mock()
        store.list_history.return_value = history
        with mock.patch("toolbox.cache.PriceSnapshotStore", return_value=store), mock.patch.object(
            server, "_snapshot_day_deltas", return_value={}
        ):
            payload = server.shape_squads(board)
        self.assertEqual([row["value_eur"] for row in payload["value_history"]], [1_000_000, 1_200_000])
        store.list_history.assert_called_once_with(league_id="L1", days=14)

    def test_shape_squads_without_snapshots(self) -> None:
        board = {"squads": {"ok": True, "squads": [{"team_id": "t1", "is_self": True, "players": [{"player_id": "a"}]}]}}
        with mock.patch("toolbox.cache.PriceSnapshotStore", side_effect=RuntimeError("sin almacén")), mock.patch.object(
            server, "_snapshot_day_deltas", return_value={}
        ):
            payload = server.shape_squads(board)
        self.assertEqual(payload["value_history"], [])


if __name__ == "__main__":
    unittest.main()

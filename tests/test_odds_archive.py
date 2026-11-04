"""Cuotas guardadas por día y goleadores de bet365 enlazados con el catálogo."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

from toolbox.odds_archive import (
    _scale_to_team_goals,
    apply_market_scorer_odds,
    archive_match_odds,
    display_name,
    scorer_prices,
)
from toolbox.scrapers import oddspapi_odds_url, parse_oddspapi_payload


def _scorer_line(name: str, price: float, *, active: bool = True) -> dict:
    return {"active": active, "playerName": name, "price": price}


def _fixture() -> dict:
    line = lambda price: {"players": {"0": {"active": True, "price": price}}}  # noqa: E731
    return {
        "participant1Name": "FC Barcelona",
        "participant2Name": "Atletico Madrid",
        "startTime": "2026-11-08T20:00:00.000Z",
        "statusId": 0,
        "bookmakerOdds": {
            "pinnacle": {
                "markets": {
                    "101": {"outcomes": {"101": line(1.8), "102": line(4.0), "103": line(4.3)}},
                    "1010": {"outcomes": {"1010": line(1.7), "1011": line(2.2)}},
                }
            },
            "bet365": {
                "markets": {
                    "10730": {
                        "outcomes": {
                            "107300": {
                                "players": {
                                    "1": _scorer_line("Yamal, Lamine", 2.3),
                                    "2": _scorer_line("Raphinha", 2.02),
                                    "3": _scorer_line("Alvarez, Julian", 2.8),
                                    "4": _scorer_line("Lesionado, Jugador", 3.0, active=False),
                                }
                            }
                        }
                    }
                }
            },
        },
    }


NOW = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)


def test_url_asks_for_pinnacle_and_bet365_in_one_call(monkeypatch) -> None:
    monkeypatch.setenv("ODDSPAPI_API_KEY", "x")
    assert "bookmakers=pinnacle%2Cbet365" in oddspapi_odds_url("id1")


def test_bet365_names_are_flipped_and_inactive_lines_dropped() -> None:
    assert display_name("Yamal, Lamine") == "Lamine Yamal"
    assert display_name("Raphinha") == "Raphinha"
    names = [row["name"] for row in scorer_prices(_fixture())]
    assert names == ["Lamine Yamal", "Raphinha", "Julian Alvarez"]


def test_payload_keeps_kickoff_and_scorers_next_to_the_1x2() -> None:
    index = parse_oddspapi_payload([_fixture()], now=NOW)
    (row,) = index.values()
    assert row["odds_1x2"] == (1.8, 4.0, 4.3)
    assert row["kickoff"].startswith("2026-11-08T20:00")
    assert len(row["anytime_scorers"]) == 3


def test_scaling_matches_the_team_goals_of_the_market() -> None:
    raw = [1 / 2.3, 1 / 2.02, 1 / 3.5, 1 / 4.0, 1 / 6.0]
    k = _scale_to_team_goals(raw, 1.9)
    total = sum(-math.log(1 - k * p) for p in raw)
    assert abs(total - 1.9 * 0.97) < 1e-6
    assert k < 1  # quitar el margen baja las probabilidades brutas


def test_an_incomplete_list_is_not_inflated_to_the_team_goals() -> None:
    # Solo dos goleadores enlazados no pueden repartirse 2,5 goles.
    assert _scale_to_team_goals([1 / 2.3, 1 / 2.02], 2.5) == 1 / 1.25


def test_scorer_probability_is_written_only_as_a_market_field() -> None:
    index = parse_oddspapi_payload([_fixture()], now=NOW)
    players = [
        {"player_id": "1", "name": "Lamine Yamal", "nickname": "Lamine Yamal", "club": "FC Barcelona",
         "own_goal_probability": 0.3, "own_expected_points": 7.0},
        {"player_id": "2", "name": "Raphael Dias Belloli", "nickname": "Raphinha", "club": "FC Barcelona"},
        {"player_id": "3", "name": "Julián Álvarez", "nickname": "Julián Alvarez", "club": "Atlético de Madrid"},
        {"player_id": "4", "name": "Otro", "nickname": "Otro", "club": "Sevilla FC"},
    ]
    status = apply_market_scorer_odds(players, index)
    assert status["ok"] and status["count"] == 3
    yamal, raphinha, julian, other = players
    assert 0 < yamal["market_goal_probability"] < 1 / 2.3
    assert raphinha["market_goal_price"] == 2.02
    assert julian["market_goal_source"] == "bet365"
    assert "market_goal_probability" not in other
    # No toca el modelo propio.
    assert yamal["own_goal_probability"] == 0.3 and yamal["own_expected_points"] == 7.0


def test_simulated_odds_are_neither_linked_nor_archived(tmp_path) -> None:
    index = parse_oddspapi_payload([_fixture()], now=NOW)
    for row in index.values():
        row["source"] = "simulated"
    assert apply_market_scorer_odds([{"player_id": "1", "name": "Lamine Yamal", "club": "FC Barcelona"}], index)["count"] == 0
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    try:
        assert archive_match_odds(index, day="2026-11-04", conn=conn) == 0
    finally:
        conn.close()


def test_archive_keeps_one_row_per_match_and_day(tmp_path) -> None:
    index = parse_oddspapi_payload([_fixture()], now=NOW)
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    try:
        assert archive_match_odds(index, day="2026-11-03", conn=conn) == 1
        assert archive_match_odds(index, day="2026-11-03", conn=conn) == 1
        assert archive_match_odds(index, day="2026-11-06", conn=conn) == 1
        days = conn.execute("select day from odds_snapshots order by day").fetchall()
        scorers = conn.execute("select count(*) from scorer_odds_snapshots").fetchone()[0]
    finally:
        conn.close()
    assert days == [("2026-11-03",), ("2026-11-06",)]
    assert scorers == 6

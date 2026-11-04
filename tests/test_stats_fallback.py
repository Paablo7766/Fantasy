"""Respaldo de Understat con FotMob + football-data, sin red."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from toolbox.net import EXTERNAL_HOSTS, ExternalHttpError
from toolbox.stats_fallback import (
    FOTMOB_LEAGUE_URL,
    FOTMOB_TO_UNDERSTAT,
    build_backup_payload,
    football_data_code,
    football_data_matches,
    fotmob_players,
    fotmob_season_id,
    load_understat_with_fallback,
)

CSV = (
    "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HxG,AxG\n"
    "SP1,25/10/2026,20:00,Barcelona,Real Madrid,1,2,1.19,1.94\n"
    "SP1,18/10/2026,20:00,Real Madrid,Sevilla,4,1,2.28,0.75\n"
    "SP1,31/10/2026,20:00,Ath Bilbao,Sociedad,2,1,3.08,1.15\n"
)


def _stat(name: str, team: str, value: float, minutes: int = 900, games: int = 10) -> dict:
    return {"ParticipantName": name, "TeamName": team, "StatValue": value, "MinutesPlayed": minutes,
            "MatchesPlayed": games, "ParticiantId": 7}


STATS = {
    "expected_goals": {"TopLists": [{"StatList": [_stat("Kylian Mbappé", "Real Madrid", 10.0)]}]},
    "expected_assists": {"TopLists": [{"StatList": [_stat("Kylian Mbappé", "Real Madrid", 2.0),
                                                   _stat("Pedri", "Barcelona", 3.0, minutes=800)]}]},
    "total_att_assist": {"TopLists": [{"StatList": [_stat("Pedri", "Barcelona", 25.0, minutes=800)]}]},
}

LEAGUE = {
    "stats": {"players": [{"fetchAllUrl": "https://data.fotmob.com/stats/87/season/38843/goals.json"}]},
    "fixtures": {
        "allMatches": [
            {"home": {"name": "Barcelona"}, "away": {"name": "Real Madrid"},
             "status": {"utcTime": "2026-10-25T19:00:00Z", "finished": True}},
            {"home": {"name": "Real Madrid"}, "away": {"name": "Athletic Club"},
             "status": {"utcTime": "2026-11-08T20:00:00Z", "finished": False, "started": False}},
            {"home": {"name": "Sevilla"}, "away": {"name": "Barcelona"},
             "status": {"utcTime": "2026-11-09T17:30:00Z", "finished": False, "started": False}},
        ]
    },
}
NOW = datetime(2026, 11, 4, 20, tzinfo=timezone.utc)


def test_season_codes_and_ids() -> None:
    assert football_data_code(datetime(2026, 11, 4)) == "2627"
    assert football_data_code(datetime(2027, 3, 1)) == "2627"
    assert fotmob_season_id(LEAGUE) == "38843"


def test_fotmob_players_are_merged_and_scaled_to_understat() -> None:
    rows = {row["player_name"]: row for row in fotmob_players(STATS)}
    assert rows["Kylian Mbappé"]["xG"] == round(10.0 * FOTMOB_TO_UNDERSTAT, 4)
    assert rows["Kylian Mbappé"]["xA"] == round(2.0 * FOTMOB_TO_UNDERSTAT, 4)
    assert rows["Pedri"]["xG"] == 0.0 and rows["Pedri"]["key_passes"] == 25.0
    assert rows["Pedri"]["time"] == 800


def test_football_data_names_map_to_fotmob_and_sort_by_date() -> None:
    matches = football_data_matches(CSV)
    assert [m["home"] for m in matches] == ["Real Madrid", "Barcelona", "Athletic Club"]
    assert matches[2]["away"] == "Real Sociedad"
    assert matches[0]["xg_home"] == round(2.28 * FOTMOB_TO_UNDERSTAT, 4)


def test_payload_has_understat_shape_without_double_counting_rolling() -> None:
    payload = build_backup_payload(LEAGUE, STATS, CSV)
    madrid = payload["teams"]["Real Madrid"]["history"]
    assert len(madrid) == 2  # un registro por partido jugado
    upcoming = [row for row in payload["dates"] if not row["isResult"]]
    assert len(upcoming) == 2  # el partido terminado de FotMob no se repite
    played = [row for row in payload["dates"] if row["isResult"]]
    # El xG va en ``xG`` (como Understat), no dentro de h/a: si no, la ventana lo contaría dos veces.
    assert all("xG" not in row["h"] for row in played)


class _FakeClient:
    def __init__(self, understat_body: str) -> None:
        self.understat_body = understat_body

    def get_text(self, url: str, *, ttl: float, fresh: bool):
        if "understat.com" in url:
            return self.understat_body, False
        if "football-data.co.uk" in url:
            return CSV, False
        raise ExternalHttpError("inesperado")

    def get_json(self, url: str, *, ttl: float, fresh: bool):
        if url == FOTMOB_LEAGUE_URL:
            return LEAGUE, False
        for stat, payload in STATS.items():
            if url.endswith(f"/{stat}.json"):
                return payload, False
        raise ExternalHttpError("inesperado")


def test_falls_back_when_understat_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    import toolbox.stats_fallback as module

    real_next = module.next_fixtures
    monkeypatch.setattr(module, "next_fixtures", lambda dates, strengths, now=None: real_next(dates, strengths, now=NOW))
    players, fixtures, strengths, rolling, status = load_understat_with_fallback(
        _FakeClient("<html>We will come back soon</html>"), ttl=0, fresh=True
    )
    assert status["ok"] is True and status["source"] == "fotmob+football-data"
    assert "Understat caído" in status["error"]
    assert {p["source"] for p in players} == {"fotmob"}
    assert fixtures["real madrid"].opponent == "Athletic Club"
    assert strengths["real madrid"].matches == 2
    assert rolling["barcelona"].sample_size == 1


def test_understat_is_used_when_it_works() -> None:
    body = json.dumps({
        "players": [{"player_name": "Pedri", "team_title": "Barcelona", "games": "10", "time": "800", "xG": "1.0", "xA": "2.0"}],
        "teams": {"1": {"title": "Barcelona", "history": [{"xG": 2.0, "xGA": 1.0}]}},
        "dates": [{"isResult": False, "h": {"id": "1", "title": "Barcelona"}, "a": {"id": "2", "title": "Sevilla"},
                   "datetime": "2099-01-01 20:00:00"}],
    })
    players, _fixtures, _strengths, _rolling, status = load_understat_with_fallback(_FakeClient(body), ttl=0, fresh=True)
    assert status["source"] == "understat" and players[0]["source"] == "understat"


def test_backup_hosts_are_allowed() -> None:
    assert {"www.fotmob.com", "data.fotmob.com", "football-data.co.uk"} <= EXTERNAL_HOSTS

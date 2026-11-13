"""OddsPapi v4 y SportsGameOdds: URLs, partidos empezados y casa de referencia."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from toolbox.matching import normalize_club
from toolbox.scrapers import (
    oddspapi_fixtures_url,
    oddspapi_odds_url,
    oddspapi_upcoming_fixtures,
    parse_oddspapi_payload,
    parse_sportsgameodds_payload,
    sportsgameodds_events_url,
)


@pytest.mark.parametrize(
    ("oddspapi_name", "expected"),
    [
        ("Espanyol Barcelona", "espanyol"),
        ("RC Deportivo de A Coruna", "deportivo"),
        ("Real Betis Seville", "betis"),
        ("Real Sociedad San Sebastian", "real sociedad"),
        ("Athletic Bilbao", "athletic"),
        ("Deportivo Alaves", "alaves"),
    ],
)
def test_oddspapi_club_names_match_the_calendar_keys(oddspapi_name: str, expected: str) -> None:
    assert normalize_club(oddspapi_name) == expected


def _line(price: float, *, active: bool = True) -> dict:
    return {"players": {"0": {"active": active, "price": price, "playerName": None}}}


def _book(home: float, draw: float, away: float, *, with_extras: bool = True, suspended: bool = False) -> dict:
    markets = {"101": {"marketActive": True, "outcomes": {"101": _line(home), "102": _line(draw), "103": _line(away)}}}
    if with_extras:
        markets["1010"] = {"marketActive": True, "outcomes": {"1010": _line(1.85), "1011": _line(2.0)}}
        markets["104"] = {"marketActive": True, "outcomes": {"104": _line(1.72), "105": _line(2.1)}}
    return {"suspended": suspended, "markets": markets}


def _fixture(
    home: str,
    away: str,
    kickoff: str,
    books: dict[str, dict],
    *,
    status_id: int = 0,
) -> dict:
    return {
        "participant1Name": home,
        "participant2Name": away,
        "startTime": kickoff,
        "statusId": status_id,
        "bookmakerOdds": books,
    }


NOW = datetime(2026, 11, 2, 22, 0, tzinfo=timezone.utc)
FUTURE = "2026-11-08T20:00:00.000Z"
PAST = "2026-11-02T20:00:00.000Z"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODDSPAPI_API_KEY", "clave-de-prueba")


def test_urls_use_v4_with_the_key_as_a_query_parameter() -> None:
    # Con la clave en una cabecera (y en v5) OddsPapi responde 401.
    fixtures = oddspapi_fixtures_url(NOW)
    odds = oddspapi_odds_url("id1000000872478700")
    assert fixtures.startswith("https://api.oddspapi.io/v4/fixtures?")
    assert "sportId=10" in fixtures and "tournamentId=8" in fixtures
    assert "from=2026-11-02" in fixtures and "to=2026-11-12" in fixtures
    assert "apiKey=clave-de-prueba" in fixtures
    assert odds.startswith("https://api.oddspapi.io/v4/odds?")
    assert "fixtureId=id1000000872478700" in odds and "bookmakers=pinnacle" in odds


def test_upcoming_fixtures_skip_finished_started_and_without_odds() -> None:
    rows = [
        {"fixtureId": "a", "hasOdds": False, "statusId": 0, "startTime": FUTURE},
        {"fixtureId": "b", "hasOdds": True, "statusId": 2, "startTime": PAST},
        {"fixtureId": "c", "hasOdds": True, "statusId": 0, "startTime": PAST},
        {"fixtureId": "d", "hasOdds": True, "statusId": 0, "startTime": "2026-11-09T20:00:00.000Z"},
        {"fixtureId": "e", "hasOdds": True, "statusId": 0, "startTime": FUTURE},
    ]
    assert [row["fixtureId"] for row in oddspapi_upcoming_fixtures(rows, NOW)] == ["e", "d"]


def test_parses_the_v4_odds_structure() -> None:
    payload = [_fixture("Getafe", "Elche", FUTURE, {"pinnacle": _book(2.0, 3.3, 3.8)})]
    row = parse_oddspapi_payload(payload, now=NOW)["getafe|elche"]
    assert row["odds_1x2"] == (2.0, 3.3, 3.8)
    assert row["odds_ou25"] == (1.85, 2.0)
    assert row["odds_btts"] == (1.72, 2.1)
    assert row["source"] == "oddspapi"


def test_started_matches_are_dropped() -> None:
    payload = [
        _fixture("Sevilla", "Alaves", PAST, {"pinnacle": _book(1.03, 10.0, 50.0)}),
        _fixture("Getafe", "Elche", FUTURE, {"pinnacle": _book(2.0, 3.3, 3.8)}),
        _fixture("Celta", "Betis", FUTURE, {"pinnacle": _book(2.0, 3.3, 3.8)}, status_id=2),
    ]
    assert list(parse_oddspapi_payload(payload, now=NOW)) == ["getafe|elche"]


def test_a_match_without_extra_markets_still_has_the_1x2() -> None:
    payload = [_fixture("Getafe", "Elche", FUTURE, {"pinnacle": _book(2.0, 3.3, 3.8, with_extras=False)})]
    row = parse_oddspapi_payload(payload, now=NOW)["getafe|elche"]
    assert row["odds_1x2"] == (2.0, 3.3, 3.8)
    assert row["odds_ou25"] is None and row["odds_btts"] is None


def test_inactive_lines_and_suspended_books_do_not_count() -> None:
    inactive = _book(2.0, 3.3, 3.8)
    inactive["markets"]["101"]["outcomes"]["102"] = _line(3.3, active=False)
    payload = [
        _fixture("Getafe", "Elche", FUTURE, {"pinnacle": inactive}),
        _fixture("Celta", "Betis", FUTURE, {"pinnacle": _book(2.0, 3.3, 3.8, suspended=True)}),
        _fixture("Rayo", "Osasuna", FUTURE, {"betclic": _book(2.0, 3.3, 3.8)}),
    ]
    assert parse_oddspapi_payload(payload, now=NOW) == {}


def test_prices_not_above_one_are_ignored() -> None:
    bad = _book(2.0, 3.3, 3.8)
    bad["markets"]["101"]["outcomes"]["101"] = _line(1.0)
    assert parse_oddspapi_payload([_fixture("Getafe", "Elche", FUTURE, {"pinnacle": bad})], now=NOW) == {}


def _sgo_odd(american: str, *, line: str | None = None, book: str = "pinnacle") -> dict:
    side = {"odds": american, "available": True}
    if line is not None:
        side["overUnder"] = line
    return {"byBookmaker": {book: side}, "bookOdds": "-999", "bookOverUnder": "9.5"}


def _sgo_event(home: str, away: str, kickoff: str, *, live: bool = False) -> dict:
    return {
        "teams": {"home": {"names": {"medium": home, "long": home}}, "away": {"names": {"medium": away}}},
        "status": {"started": live, "live": live, "ended": False, "completed": False, "startsAt": kickoff},
        "odds": {
            "points-home-reg-ml3way-home": _sgo_odd("+100"),
            "points-all-reg-ml3way-draw": _sgo_odd("+230"),
            "points-away-reg-ml3way-away": _sgo_odd("+280"),
            "points-all-reg-ou-over": _sgo_odd("-110", line="2.5"),
            "points-all-reg-ou-under": _sgo_odd("-110", line="2.5"),
            "bothTeamsScored-all-game-yn-yes": _sgo_odd("-140"),
            "bothTeamsScored-all-game-yn-no": _sgo_odd("+110"),
        },
    }


def test_sportsgameodds_url_is_laliga_without_the_key() -> None:
    url = sportsgameodds_events_url(NOW)
    assert url.startswith("https://api.sportsgameodds.com/v2/events?")
    assert "leagueID=LA_LIGA" in url
    assert "apiKey" not in url
    assert "points-home-reg-ml3way-home" in url
    assert "bothTeamsScored-all-game-yn-yes" in url


def test_sportsgameodds_converts_american_odds_and_keeps_the_two_and_a_half_line() -> None:
    payload = {"success": True, "data": [_sgo_event("Getafe", "Elche", "2026-11-08T20:00:00.000Z")]}
    index = parse_sportsgameodds_payload(payload, now=NOW)
    row = index["getafe|elche"]
    assert row["odds_1x2"] == (2.0, 3.3, 3.8)
    assert row["odds_ou25"] == (1 + 100 / 110, 1 + 100 / 110)
    assert row["source"] == "sportsgameodds"


def test_sportsgameodds_drops_a_total_that_is_not_two_and_a_half() -> None:
    event = _sgo_event("Getafe", "Elche", "2026-11-08T20:00:00.000Z")
    event["odds"]["points-all-reg-ou-over"] = _sgo_odd("-110", line="3.5")
    event["odds"]["points-all-reg-ou-under"] = _sgo_odd("-110", line="3.5")
    index = parse_sportsgameodds_payload({"data": [event]}, now=NOW)
    assert index["getafe|elche"]["odds_ou25"] is None


def test_sportsgameodds_drops_started_matches_and_prefers_pinnacle() -> None:
    started = _sgo_event("Sevilla", "Alaves", "2026-11-02T20:00:00.000Z", live=True)
    upcoming = _sgo_event("Getafe", "Elche", "2026-11-08T20:00:00.000Z")
    upcoming["odds"]["points-home-reg-ml3way-home"]["byBookmaker"]["bet365"] = {"odds": "+150", "available": True}
    index = parse_sportsgameodds_payload({"data": [started, upcoming]}, now=NOW)
    assert list(index) == ["getafe|elche"]
    assert index["getafe|elche"]["odds_1x2"][0] == 2.0

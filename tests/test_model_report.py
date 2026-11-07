"""Informe del modelo del Laboratorio: tablero + tablas guardadas → JSON y texto."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from toolbox.model_report import build_model_report, sources_summary
from toolbox.odds_archive import archive_match_odds, ensure_schema

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def _board() -> dict:
    cal_home = [{"opponent": "Sevilla", "is_home": True, "kickoff": "2026-11-08T20:00:00+00:00",
                 "lambda_for": 2.1, "lambda_against": 0.9, "p_cs_for": 0.41, "predicted_score": "2-0"}]
    cal_away = [{"opponent": "FC Barcelona", "is_home": False, "kickoff": "2026-11-08T20:00:00+00:00",
                 "lambda_for": 0.9, "lambda_against": 2.1, "p_cs_for": 0.12, "predicted_score": "0-2"}]
    players = [
        {"player_id": "1", "nickname": "Lamine Yamal", "club": "FC Barcelona", "position": "DEL",
         "own_calendar": cal_home, "own_goal_probability": 0.31},
        {"player_id": "2", "nickname": "Isaac", "club": "Sevilla FC", "position": "DEL",
         "own_calendar": cal_away, "own_goal_probability": 0.2},
    ]
    return {
        "dashboard_at": "2026-11-05T10:00:00+00:00",
        "trends": {
            "league_id": "7",
            "players": players,
            "sources": {
                "understat": {"ok": True, "count": 487, "error": "Understat caído (x): xG de fotmob+football-data", "source": "fotmob+football-data"},
                "laliga_odds": {"ok": False, "count": 10, "error": "Sin cuotas reales: se usan simuladas", "source": "simulated"},
            },
        },
        "squads": {"ok": True, "league_id": "7", "squads": [
            {"team_id": "9", "is_self": True, "players": [{"player_id": "1"}]},
        ]},
    }


def _db(tmp_path):
    path = tmp_path / "responses.sqlite"
    conn = sqlite3.connect(path)
    ensure_schema(conn)
    index = {
        "barcelona|sevilla": {
            "source": "oddspapi",
            "kickoff": "2026-11-08T20:00:00+00:00",
            "odds_1x2": (1.5, 4.5, 6.5),
            "odds_ou25": (1.6, 2.4),
            "odds_btts": None,
            "anytime_scorers": [
                {"name": "Lamine Yamal", "price": 2.3, "bookmaker": "bet365", "player_id": "1", "market_goal_probability": 0.36},
                {"name": "Desconocido", "price": 5.0, "bookmaker": "bet365"},
            ],
        }
    }
    archive_match_odds(index, day="2026-11-05", conn=conn)
    conn.execute(
        "create table matchday_snapshots (jornada_id text, player_id text, name text, expected_points real, "
        "ceiling_points real, in_once_optimo integer, league_id text, snapshot_day text, stored_at real, "
        "actual_points real, evaluated_at real, kickoff text, position text, team_id text)"
    )
    conn.executemany(
        "insert into matchday_snapshots (jornada_id, player_id, expected_points, in_once_optimo, actual_points, stored_at) values (?,?,?,?,?,0)",
        [("11", "1", 6.0, 1, 9.0), ("11", "2", 4.0, 0, 2.0), ("12", "1", 7.0, 1, None)],
    )
    conn.commit()
    conn.close()
    return path


def test_sources_mark_the_backup_and_the_simulated_odds() -> None:
    rows = {row["id"]: row for row in sources_summary(_board()["trends"])}
    assert rows["understat"]["state"] == "respaldo"
    assert rows["laliga_odds"]["state"] == "fallo"


def test_report_joins_model_market_scorers_and_history(tmp_path) -> None:
    report = build_model_report(_board(), db_path=_db(tmp_path), now=NOW)
    (match,) = report["matches"]
    assert match["home"]["club"] == "FC Barcelona" and match["away"]["club"] == "Sevilla FC"
    assert match["market"]["p_home"] > 0.6 and match["market"]["lambda_home"] > match["market"]["lambda_away"]
    assert 0.55 < match["market_weight"] < 0.82

    scorers = report["scorers"]
    assert scorers["listed"] == 2 and scorers["linked"] == 1
    yamal = scorers["rows"][0]
    assert yamal["mine"] is True and yamal["gap"] == round(0.36 - 0.31, 3)

    j11 = next(row for row in report["history"]["jornadas"] if row["jornada"] == "11")
    assert j11["evaluated"] == 2 and j11["mae"] == 2.5
    assert {item["id"] for item in report["shadow"]} >= {"scorer_odds", "match_odds_weight"}


def test_text_is_self_contained_for_pasting(tmp_path) -> None:
    report = build_model_report(_board(), db_path=_db(tmp_path), now=NOW)
    text = report["text"]
    for needle in ("# Informe del modelo", "## Fuentes", "respaldo", "FC Barcelona - Sevilla FC", "Lamine Yamal", "J11", "## En pruebas"):
        assert needle in text


def test_report_survives_without_database(tmp_path) -> None:
    report = build_model_report(_board(), db_path=tmp_path / "no-existe.sqlite", now=NOW)
    assert report["scorers"]["rows"] == [] and report["history"]["jornadas"] == []
    assert report["matches"][0]["market"] is None


def test_scoreboard_compares_model_with_constant_baseline() -> None:
    from toolbox.model_report import scoreboard

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "create table matchday_snapshots (jornada_id text, player_id text, name text, expected_points real, "
        "actual_points real)"
    )
    rows = [("1", str(i), "x", 5.0, float(a)) for i, a in enumerate([5, 5, 5, 6, 4] * 8)]
    conn.executemany("insert into matchday_snapshots values (?,?,?,?,?)", rows)
    by_id = {r["id"]: r for r in scoreboard(conn, None)}
    assert by_id["xp_modelo"]["n"] == 40 and by_id["xp_modelo"]["verdict"] in {"mejor", "peor"}
    assert by_id["mercado_goleador"]["verdict"] == "sin_medir" or "mercado_goleador" not in by_id


def test_scoreboard_few_cases_is_not_a_verdict() -> None:
    from toolbox.model_report import scoreboard

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "create table matchday_snapshots (jornada_id text, player_id text, name text, expected_points real, "
        "actual_points real)"
    )
    conn.execute("insert into matchday_snapshots values ('1','1','x',5,2)")
    assert {r["id"]: r for r in scoreboard(conn, None)}["xp_modelo"]["verdict"] == "pocos_datos"

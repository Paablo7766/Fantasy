"""Previa: regla validada, ediciones congeladas y evaluación, sin red."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from toolbox.previa import build_previa, edition_for, evaluate, freeze, frozen_editions, previa_report

TUESDAY = datetime(2026, 11, 3, 10, tzinfo=timezone.utc)
THURSDAY = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)


def _player(pid, name, club, pos, avg, rounds, *, status="ok"):
    return {"player_id": pid, "nickname": name, "club": club, "position": pos, "average_points": avg,
            "week_points_by_round": rounds, "player_status": status, "market_value": 5_000_000}


def _board(dashboard_at="2026-11-03T09:00:00+00:00", *, with_calendar=True):
    r = {"9": 4.0, "10": 5.0, "11": 6.0}
    barca = [
        _player("d1", "Delantero bueno", "FC Barcelona", "DEL", 8.0, r),
        _player("d2", "Delantero lesionado", "FC Barcelona", "DEL", 9.0, r, status="injured"),
        _player("m1", "Medio", "FC Barcelona", "MC", 5.0, r),
        _player("p1", "Portero", "FC Barcelona", "POR", 4.0, r),
        _player("x1", "Revulsivo", "FC Barcelona", "DEL", 3.0, {"10": 3.0, "11": 4.0}),
    ]
    sevilla = [
        _player("s1", "Estrella Sevilla", "Sevilla FC", "DEL", 7.0, r),
        _player("s2", "Central", "Sevilla FC", "DEF", 6.0, r),
        _player("s3", "Lateral", "Sevilla FC", "DEF", 3.0, r),
    ]
    cal_home = [{"opponent": "Sevilla", "is_home": True, "kickoff": "2026-11-08T20:00:00+00:00",
                 "lambda_for": 2.4, "lambda_against": 0.7, "p_cs_for": 0.5}]
    cal_away = [{"opponent": "FC Barcelona", "is_home": False, "kickoff": "2026-11-08T20:00:00+00:00",
                 "lambda_for": 0.7, "lambda_against": 2.4, "p_cs_for": 0.09}]
    trends = [{"player_id": p["player_id"], "club": p["club"], "own_calendar": cal_home if with_calendar else []} for p in barca]
    trends += [{"player_id": p["player_id"], "club": p["club"], "own_calendar": cal_away if with_calendar else []} for p in sevilla]
    trends[0]["p_titular"] = 0.95
    return {
        "dashboard_at": dashboard_at,
        "trends": {"players": trends},
        "squads": {"squads": [
            {"team_id": "1", "is_self": True, "manager_name": "Yo", "players": barca[:3]},
            {"team_id": "2", "is_self": False, "manager_name": "Rival", "players": barca[3:] + sevilla},
        ]},
        "market": {"listings": []},
    }


def test_editions_follow_the_madrid_week() -> None:
    assert edition_for(TUESDAY) == "martes"
    assert edition_for(THURSDAY) == "jueves"
    assert edition_for(datetime(2026, 11, 8, 10, tzinfo=timezone.utc)) == "jueves"  # domingo
    assert edition_for(datetime(2026, 11, 9, 10, tzinfo=timezone.utc)) == "martes"  # lunes


def test_rule_ranks_by_mean_availability_and_rival(tmp_path) -> None:
    previa = build_previa(_board(), now=TUESDAY)
    assert previa["jornada"] == "12" and previa["edition"] == "martes"
    (match,) = previa["matches"]
    top = [p["name"] for p in match["top"]]
    assert top[0] == "Delantero bueno"
    assert "Delantero lesionado" not in top
    assert [p["name"] for p in match["bajas"]] == ["Delantero lesionado"]
    assert "Delantero lesionado" not in [p["name"] for p in match["no_recomendable"]]
    # La regla ingenua (solo media) habría puesto al lesionado arriba.
    assert match["naive_top"][0]["name"] == "Delantero lesionado"
    # Contra un Barça que espera 2,4 goles, el delantero del Sevilla baja.
    sevilla = next(p for p in match["no_recomendable"] + match["top"] if p["name"] == "Estrella Sevilla")
    assert sevilla["score"] < 7.0
    assert match["mine"][0]["mine"] is True


def test_calendar_fallback_without_model_or_odds(tmp_path, monkeypatch) -> None:
    import toolbox.previa as module

    (tmp_path / "laliga_2026_27.txt").write_text("▪ Matchday 12\n  Sun Nov 8\n   FC Barcelona v Sevilla FC\n", encoding="utf-8")
    monkeypatch.setattr(module, "cache_root", lambda: tmp_path)
    previa = build_previa(_board(with_calendar=False), now=TUESDAY)
    (match,) = previa["matches"]
    assert match["source"] == "calendario" and match["top"]


def test_an_edition_is_frozen_once_and_evaluated_later(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    try:
        first = build_previa(_board(), now=TUESDAY)
        assert freeze(conn, first) is True
        again = build_previa(_board(), now=TUESDAY)
        again["matches"][0]["top"] = []
        assert freeze(conn, again) is False  # no se reescribe
        (stored,) = frozen_editions(conn, "12")
        assert stored["matches"][0]["top"]

        played = _board()
        for team in played["squads"]["squads"]:
            for p in team["players"]:
                if p["player_id"] != "d2":  # el lesionado no juega
                    p["week_points_by_round"] = {**p["week_points_by_round"], "12": 10.0 if p["player_id"] == "d1" else 1.0}
        (row,) = evaluate(conn, played)
    finally:
        conn.close()
    assert row["jornada"] == "12" and row["top"]["mean"] > row["naive_top"]["mean"]


def test_stale_photo_is_shown_but_not_frozen(tmp_path) -> None:
    report = previa_report(_board(dashboard_at="2026-11-01T09:00:00+00:00"), db_path=tmp_path / "db.sqlite", now=TUESDAY)
    assert report["live"]["matches"] and report["frozen_now"] is False and report["editions"] == []
    fresh = previa_report(_board(), db_path=tmp_path / "db.sqlite", now=TUESDAY)
    assert fresh["frozen_now"] is True and len(fresh["editions"]) == 1


def test_a_round_published_with_zeros_is_not_evaluated_yet(tmp_path) -> None:
    """LALIGA abre la jornada con 0 a todos antes de jugarla: eso no es un resultado."""
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    try:
        assert freeze(conn, build_previa(_board(), now=TUESDAY)) is True
        pending = _board()
        for team in pending["squads"]["squads"]:
            for p in team["players"]:
                p["week_points_by_round"] = {**p["week_points_by_round"], "12": 0.0}
        assert evaluate(conn, pending) == []
    finally:
        conn.close()

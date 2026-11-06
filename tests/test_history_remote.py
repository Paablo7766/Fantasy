import sqlite3
from datetime import datetime, timezone

from toolbox import history_remote
from toolbox.matching import normalize_club
from toolbox.model_report import upcoming_matches


def _matchday(conn: sqlite3.Connection) -> None:
    conn.execute(
        "create table matchday_snapshots (jornada_id text not null, player_id text not null,"
        " expected_points real, stored_at real not null, actual_points real,"
        " primary key (jornada_id, player_id))"
    )
    conn.execute(
        "create table previa_snapshots (jornada text not null, edition text not null,"
        " payload text not null, stored_at real not null, primary key (jornada, edition))"
    )


def test_merge_keeps_evaluated_rows_and_first_frozen_previa() -> None:
    remote = sqlite3.connect(":memory:")
    _matchday(remote)
    remote.execute("insert into matchday_snapshots values ('12','a',5,10,null)")
    remote.execute("insert into matchday_snapshots values ('12','b',4,10,7)")
    remote.execute("insert into previa_snapshots values ('12','jueves','nueva',99)")
    dump = history_remote._dump(remote)

    local = sqlite3.connect(":memory:")
    _matchday(local)
    local.execute("insert into matchday_snapshots values ('12','a',5,5,3)")  # evaluada, más vieja
    local.execute("insert into matchday_snapshots values ('12','b',4,20,null)")  # sin evaluar, más nueva
    local.execute("insert into previa_snapshots values ('12','jueves','vieja',1)")
    history_remote.merge_into(local, dump)

    rows = dict(local.execute("select player_id, actual_points from matchday_snapshots").fetchall())
    assert rows == {"a": 3, "b": 7}
    assert local.execute("select payload from previa_snapshots").fetchone()[0] == "vieja"


def test_merge_creates_missing_tables() -> None:
    remote = sqlite3.connect(":memory:")
    _matchday(remote)
    remote.execute("insert into matchday_snapshots values ('12','a',5,10,null)")
    local = sqlite3.connect(":memory:")
    assert history_remote.merge_into(local, history_remote._dump(remote)) == 1


def test_deportivo_variants_share_one_key() -> None:
    names = ["deportivo a coruna", "RC Deportivo", "Deportivo de La Coruña", "RC Deportivo de A Coruña"]
    assert {normalize_club(n) for n in names} == {"deportivo"}
    assert normalize_club("Deportivo Alavés") == "alaves"


def test_upcoming_matches_drop_the_following_jornada() -> None:
    def player(club: str, opp: str, kickoff: str, home: bool) -> dict:
        return {"club": club, "own_calendar": [{"opponent": opp, "kickoff": kickoff, "is_home": home}]}

    trends = {
        "players": [
            player("Celta", "Levante UD", "2026-11-08T17:30:00+00:00", True),
            player("Levante UD", "Celta", "2026-11-08T17:30:00+00:00", False),
            player("Sevilla FC", "Getafe", "2026-11-21T17:30:00+00:00", True),
        ]
    }
    now = datetime(2026, 11, 6, 22, tzinfo=timezone.utc)
    keys = [m["match_key"] for m in upcoming_matches(trends, None, now=now)]
    assert keys == ["celta|levante"]

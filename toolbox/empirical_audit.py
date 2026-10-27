"""Auditoría empírica reutilizable: snapshots de precio y SELL_AT_CREST."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from toolbox.cache import CashLedgerStore, PriceSnapshotStore, cache_root
from toolbox.league_history import collect_activity_buys
from toolbox.own_intel import compute_price_kinematics_and_sell_signal


def default_audit_db() -> Path:
    return cache_root() / "responses.sqlite"


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in payload if isinstance(row, dict)]


def ensure_audit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists price_snapshots (
            player_id text not null,
            day text not null,
            league_id text,
            market_value integer,
            market_value_change integer,
            stored_at real not null,
            primary key (player_id, day)
        );
        create table if not exists activity_buys (
            id integer primary key autoincrement,
            league_id text,
            team_id text not null,
            player_id text not null,
            amount_eur integer not null,
            reference_value_eur integer,
            cash_at_event_eur integer,
            positional_urgency real,
            at text
        );
        create index if not exists activity_buys_team_idx on activity_buys (team_id);
        create index if not exists price_snapshots_day_idx on price_snapshots (day);
        """
    )
    conn.commit()


def hydrate_audit_from_app_stores(
    conn: sqlite3.Connection,
    *,
    league_id: str | None = None,
) -> dict[str, int]:
    """Copia snapshots y compras del almacén del tablero a ``responses.sqlite``."""
    ensure_audit_schema(conn)
    imported_snaps = 0
    imported_buys = 0
    try:
        rows = PriceSnapshotStore().all_snapshots(league_id)
        if league_id is not None and not rows:
            rows = PriceSnapshotStore().all_snapshots(None)
    except Exception:
        rows = []
    if rows:
        sqlite_n = conn.execute("select count(*) from price_snapshots").fetchone()[0]
        if len(rows) > sqlite_n:
            conn.executemany(
                """
                insert or replace into price_snapshots
                (player_id, day, league_id, market_value, market_value_change, stored_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.get("player_id"),
                        row.get("day"),
                        row.get("league_id"),
                        row.get("market_value"),
                        row.get("market_value_change"),
                        float(row.get("stored_at") or 0.0),
                    )
                    for row in rows
                    if isinstance(row.get("player_id"), str) and isinstance(row.get("day"), str)
                ],
            )
            imported_snaps = len(rows)

    try:
        ledgers = CashLedgerStore().list_ledgers(league_id)
        if league_id is not None and not ledgers:
            ledgers = CashLedgerStore().list_ledgers(None)
    except Exception:
        ledgers = []
    buy_n = conn.execute("select count(*) from activity_buys").fetchone()[0]
    if ledgers and buy_n < 3:
        index: dict[tuple[str, str], int] = {}
        for player_id, day, value in conn.execute(
            "select player_id, day, market_value from price_snapshots where market_value is not null"
        ):
            if isinstance(player_id, str) and isinstance(day, str) and isinstance(value, int):
                index[(player_id, day)] = value
        events: list[dict[str, Any]] = []
        for ledger in ledgers:
            team_id = ledger.get("team_id")
            league = ledger.get("league_id")
            if not isinstance(team_id, str):
                continue
            for ev in ledger.get("events") or []:
                if not isinstance(ev, dict) or ev.get("kind") != "buy":
                    continue
                events.append(
                    {
                        "activity_type_id": 31,
                        "team_id": team_id,
                        "league_id": league,
                        "player_id": ev.get("player_id"),
                        "amount_eur": ev.get("amount_eur"),
                        "at": ev.get("at"),
                    }
                )
        buys = collect_activity_buys(events, index, ledgers)
        if buys:
            if league_id is not None:
                conn.execute("delete from activity_buys where league_id = ? or league_id is null", (league_id,))
            else:
                conn.execute("delete from activity_buys")
            conn.executemany(
                """
                insert into activity_buys
                (league_id, team_id, player_id, amount_eur, reference_value_eur,
                 cash_at_event_eur, positional_urgency, at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        ev.get("league_id"),
                        ev.get("team_id"),
                        ev.get("player_id"),
                        ev.get("amount_eur"),
                        ev.get("reference_value_eur"),
                        ev.get("cash_at_event_eur"),
                        ev.get("positional_urgency"),
                        ev.get("at"),
                    )
                    for ev in buys
                ],
            )
            imported_buys = len(buys)

    conn.commit()
    return {"snapshots_imported": imported_snaps, "buys_imported": imported_buys}


def sync_audit_from_local_store(conn: sqlite3.Connection, cache: Path | None = None) -> tuple[int, int]:
    root = cache or cache_root()
    snap_n = conn.execute("select count(*) from price_snapshots").fetchone()[0]
    buy_n = conn.execute("select count(*) from activity_buys").fetchone()[0]
    if snap_n > 0 and buy_n > 0:
        return snap_n, buy_n

    local = root / "supabase-local"
    snapshots = _load_json_rows(local / "price_snapshots.json")
    ledgers = _load_json_rows(local / "cash_ledgers.json")

    if snap_n == 0 and snapshots:
        conn.executemany(
            """
            insert or replace into price_snapshots
            (player_id, day, league_id, market_value, market_value_change, stored_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("player_id"),
                    row.get("day"),
                    row.get("league_id"),
                    row.get("market_value"),
                    row.get("market_value_change"),
                    float(row.get("stored_at") or 0.0),
                )
                for row in snapshots
                if isinstance(row.get("player_id"), str) and isinstance(row.get("day"), str)
            ],
        )

    if buy_n == 0 and ledgers:
        index: dict[tuple[str, str], int] = {}
        for row in snapshots:
            player_id = row.get("player_id")
            day = row.get("day")
            value = row.get("market_value")
            if isinstance(player_id, str) and isinstance(day, str) and isinstance(value, int):
                index[(player_id, day)] = value

        events: list[dict[str, Any]] = []
        for ledger in ledgers:
            team_id = ledger.get("team_id")
            league_id = ledger.get("league_id")
            if not isinstance(team_id, str):
                continue
            for ev in ledger.get("events") or []:
                if not isinstance(ev, dict) or ev.get("kind") != "buy":
                    continue
                events.append(
                    {
                        "activity_type_id": 31,
                        "team_id": team_id,
                        "league_id": league_id,
                        "player_id": ev.get("player_id"),
                        "amount_eur": ev.get("amount_eur"),
                        "at": ev.get("at"),
                    }
                )

        buys = collect_activity_buys(events, index, ledgers)
        conn.executemany(
            """
            insert into activity_buys
            (league_id, team_id, player_id, amount_eur, reference_value_eur,
             cash_at_event_eur, positional_urgency, at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    ev.get("league_id"),
                    ev.get("team_id"),
                    ev.get("player_id"),
                    ev.get("amount_eur"),
                    ev.get("reference_value_eur"),
                    ev.get("cash_at_event_eur"),
                    ev.get("positional_urgency"),
                    ev.get("at"),
                )
                for ev in buys
            ],
        )

    conn.commit()
    return (
        conn.execute("select count(*) from price_snapshots").fetchone()[0],
        conn.execute("select count(*) from activity_buys").fetchone()[0],
    )


def read_price_snapshots_grouped(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    rows = conn.execute(
        """
        select player_id, day, league_id, market_value, market_value_change
        from price_snapshots
        order by player_id, day
        """
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player_id, day, league_id, market_value, market_value_change in rows:
        grouped[str(player_id)].append(
            {
                "player_id": player_id,
                "day": day,
                "league_id": league_id,
                "market_value": market_value,
                "market_value_change": market_value_change,
            }
        )
    return grouped


def _delta_for_row(row: dict[str, Any], prev_mv: int | None) -> int | None:
    change = row.get("market_value_change")
    if isinstance(change, int) and not isinstance(change, bool):
        return change
    mv = row.get("market_value")
    if isinstance(mv, int) and isinstance(prev_mv, int):
        return mv - prev_mv
    return None


@dataclass
class CrestAuditRow:
    player_id: str
    day: str
    market_value: int
    delta_t: int
    rei: float
    tau_zero: float
    hit_48h: bool
    peak_within_1d: bool
    regret_2d_eur: int


def audit_sell_at_crest(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    signals: list[CrestAuditRow] = []
    horizon = 2

    for player_id, series in grouped.items():
        if len(series) < 4:
            continue
        by_day = {str(row["day"]): row for row in series if isinstance(row.get("day"), str)}
        days = sorted(by_day)
        prev_mv: int | None = None
        deltas_by_day: dict[str, int] = {}
        values_by_day: dict[str, int] = {}
        for day in days:
            row = by_day[day]
            mv = row.get("market_value")
            if isinstance(mv, int) and not isinstance(mv, bool):
                values_by_day[day] = mv
            delta = _delta_for_row(row, prev_mv)
            if delta is not None:
                deltas_by_day[day] = delta
            if isinstance(mv, int):
                prev_mv = mv

        for idx in range(3, len(days)):
            day = days[idx]
            window = [by_day[d] for d in days[: idx + 1]]
            current_mv = values_by_day.get(day)
            if not isinstance(current_mv, int):
                continue
            delta_t = deltas_by_day.get(day)
            kin = compute_price_kinematics_and_sell_signal(
                window[-14:],
                current_market_value=current_mv,
                official_today_delta=delta_t,
            )
            if kin.sell_signal_status != "SELL_AT_CREST":
                continue

            future_days = days[idx + 1 : idx + 1 + horizon]
            future_deltas = [deltas_by_day[d] for d in future_days if d in deltas_by_day]
            hit_48h = any(delta <= 0 for delta in future_deltas)

            local_window = days[max(0, idx - 1) : min(len(days), idx + 3)]
            peak_day = max(local_window, key=lambda d: values_by_day.get(d, 0))
            peak_within_1d = abs(days.index(peak_day) - idx) <= 1

            horizon_values = [values_by_day[d] for d in days[idx : idx + 1 + horizon] if d in values_by_day]
            max_future = max(horizon_values) if horizon_values else current_mv
            regret_2d = max(0, int(max_future - current_mv))

            signals.append(
                CrestAuditRow(
                    player_id=player_id,
                    day=day,
                    market_value=current_mv,
                    delta_t=int(delta_t or 0),
                    rei=float(kin.relative_exhaustion_index),
                    tau_zero=float(kin.days_to_zero_crossing),
                    hit_48h=hit_48h,
                    peak_within_1d=peak_within_1d,
                    regret_2d_eur=regret_2d,
                )
            )

    if not signals:
        return {
            "signals": 0,
            "accuracy_pct": None,
            "hit_48h_rate": None,
            "peak_within_1d_rate": None,
            "mean_regret_2d_eur": None,
            "samples": [],
        }

    hit_rate = sum(1 for s in signals if s.hit_48h) / len(signals)
    return {
        "signals": len(signals),
        "accuracy_pct": round(hit_rate * 100.0, 2),
        "hit_48h_rate": round(hit_rate, 4),
        "peak_within_1d_rate": round(sum(1 for s in signals if s.peak_within_1d) / len(signals), 4),
        "mean_regret_2d_eur": round(sum(s.regret_2d_eur for s in signals) / len(signals)),
        "samples": [
            {
                "player_id": s.player_id,
                "day": s.day,
                "delta_t": s.delta_t,
                "rei": s.rei,
                "tau_zero": s.tau_zero,
                "hit_48h": s.hit_48h,
                "peak_within_1d": s.peak_within_1d,
                "regret_2d_eur": s.regret_2d_eur,
            }
            for s in sorted(signals, key=lambda row: (-row.regret_2d_eur, row.day))[:12]
        ],
    }

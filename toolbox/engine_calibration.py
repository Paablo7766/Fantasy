"""Dashboard de precisión del motor: E[pts], PUJAR, SELL_AT_CREST y P(ganar)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from toolbox.bid_war import probability_of_winning_bid
from toolbox.cache import cache_root, madrid_day
from toolbox.empirical_audit import (
    audit_sell_at_crest,
    default_audit_db,
    ensure_audit_schema,
    hydrate_audit_from_app_stores,
    read_price_snapshots_grouped,
    sync_audit_from_local_store,
)
from toolbox.cache import CashLedgerStore
from toolbox.league_history import RivalProfile, fit_rival_profiles_eb

# Proyección neutra solo cuando el jugador no tiene ninguna jornada puntuada.
# El Brier usa la proyección real guardada en ``matchday_snapshots``.
DEFAULT_EXPECTED_PTS = 4.5


def calibration_db_path() -> Path:
    return default_audit_db()


def _ensure_predicted_win_column(conn: sqlite3.Connection) -> None:
    """Migración idempotente: ``predicted_win`` (REAL, nullable) para el MAE.

    Bases antiguas ya creadas por versiones previas no tienen la columna; se
    añade aquí antes de insertar para que la puja congelada quede persistida.
    """
    have = {
        str(row[1])
        for row in conn.execute("pragma table_info(market_decision_snapshots)").fetchall()
    }
    if "predicted_win" not in have:
        conn.execute("alter table market_decision_snapshots add column predicted_win real")
        conn.commit()


def _ensure_tracking_schema(conn: sqlite3.Connection) -> None:
    ensure_audit_schema(conn)
    conn.execute(
        """
        create table if not exists market_decision_snapshots (
            snapshot_day text not null,
            league_id text,
            player_id text not null,
            decision text not null,
            suggested_bid integer,
            win_probability real,
            primary_motive text,
            stored_at real not null,
            outcome text,
            outcome_at real,
            primary key (snapshot_day, player_id)
        )
        """
    )
    _ensure_predicted_win_column(conn)
    conn.execute(
        """
        create table if not exists matchday_snapshots (
            jornada_id text not null,
            player_id text not null,
            name text,
            expected_points real,
            ceiling_points real,
            in_once_optimo integer not null default 0,
            league_id text,
            snapshot_day text,
            stored_at real not null,
            actual_points real,
            evaluated_at real,
            primary key (jornada_id, player_id)
        )
        """
    )
    conn.commit()


def _predicted_win(row: dict[str, Any]) -> float | None:
    """Puja congelada que el motor daba para ganar la subasta (MAE)."""
    for key in ("predicted_win", "optimal_bid_eur", "suggested_bid"):
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            return round(float(value), 2)
    return None


def persist_market_decisions(
    decisions: list[dict[str, Any]],
    *,
    league_id: str | None = None,
    snapshot_day: str | None = None,
    db_path: Path | None = None,
) -> int:
    """Guarda veredictos del día para medir hit rate de PUJAR más adelante."""
    if not decisions:
        return 0
    day = snapshot_day or madrid_day()
    path = db_path or calibration_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _ensure_tracking_schema(conn)
        stamp = time.time()
        rows = [
            (
                day,
                league_id,
                str(row["player_id"]),
                str(row.get("decision") or ""),
                row.get("suggested_bid") if isinstance(row.get("suggested_bid"), int) else None,
                float(row["win_probability"]) if isinstance(row.get("win_probability"), (int, float)) else None,
                row.get("primary_motive") if isinstance(row.get("primary_motive"), str) else None,
                stamp,
                None,
                None,
                _predicted_win(row),
            )
            for row in decisions
            if isinstance(row, dict) and isinstance(row.get("player_id"), str) and row.get("player_id")
        ]
        if not rows:
            return 0
        conn.executemany(
            """
            insert into market_decision_snapshots (
                snapshot_day, league_id, player_id, decision, suggested_bid,
                win_probability, primary_motive, stored_at, outcome, outcome_at,
                predicted_win
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(snapshot_day, player_id) do update set
                decision=excluded.decision,
                suggested_bid=excluded.suggested_bid,
                win_probability=excluded.win_probability,
                primary_motive=excluded.primary_motive,
                stored_at=excluded.stored_at,
                predicted_win=coalesce(excluded.predicted_win, market_decision_snapshots.predicted_win)
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _resolve_pujar_outcomes(conn: sqlite3.Connection, own_team_id: str | None) -> None:
    if not isinstance(own_team_id, str) or not own_team_id:
        return
    pending = conn.execute(
        """
        select snapshot_day, player_id, suggested_bid, win_probability
        from market_decision_snapshots
        where decision = 'PUJAR' and outcome is null and snapshot_day < ?
        order by snapshot_day
        """,
        (madrid_day(),),
    ).fetchall()
    if not pending:
        return
    buys = conn.execute(
        """
        select team_id, player_id, amount_eur, at
        from activity_buys
        where amount_eur > 0
        order by at
        """
    ).fetchall()
    by_player: dict[str, list[tuple[str, int, str | None]]] = {}
    for team_id, player_id, amount, at in buys:
        by_player.setdefault(str(player_id), []).append((str(team_id), int(amount), at))

    stamp = time.time()
    updates: list[tuple[str, float, str, str]] = []
    for snap_day, player_id, suggested, _p_win in pending:
        events = by_player.get(str(player_id)) or []
        outcome = "unknown"
        for team_id, amount, at in events:
            if at and isinstance(at, str) and at[:10] < snap_day:
                continue
            if team_id == own_team_id:
                # El éxito se mide contra el importe realmente pagado, no contra
                # la sugerencia congelada: la puja se ajusta durante el día y la
                # sugerencia del snapshot ya no es la que se ejecutó.
                outcome = "hit"
            else:
                outcome = "lost"
            break
        updates.append((outcome, stamp, snap_day, str(player_id)))

    conn.executemany(
        """
        update market_decision_snapshots
        set outcome = ?, outcome_at = ?
        where snapshot_day = ? and player_id = ?
        """,
        updates,
    )
    conn.commit()


def matchday_points_trend(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        select jornada_id,
               avg(abs(expected_points - actual_points)) as mae,
               count(*) as scored,
               sum(case when actual_points is not null and ceiling_points is not null
                        and actual_points > ceiling_points then 1 else 0 end) as ceiling_breaks,
               sum(case when ceiling_points is not null and actual_points is not null
                        then 1 else 0 end) as ceiling_checked,
               max(evaluated_at) as evaluated_at
        from matchday_snapshots
        where actual_points is not null and expected_points is not null
        group by jornada_id
        order by cast(jornada_id as integer), jornada_id
        """
    ).fetchall()

    series: list[dict[str, Any]] = []
    for jornada_id, mae, scored, breaks, checked, evaluated_at in rows:
        rate = round(int(breaks) / int(checked), 4) if checked else None
        series.append(
            {
                "jornada_id": str(jornada_id),
                "mae": round(float(mae), 4) if mae is not None else None,
                "scored": int(scored),
                "ceiling_break_rate": rate,
                "evaluated_at": evaluated_at,
            }
        )

    overall_mae = None
    if series:
        weights = [row["scored"] for row in series]
        total = sum(weights)
        if total:
            overall_mae = round(
                sum((row["mae"] or 0.0) * row["scored"] for row in series) / total,
                4,
            )

    trend = "insufficient"
    delta_mae = None
    if len(series) >= 4:
        recent = series[-3:]
        prior = series[-6:-3] if len(series) >= 6 else series[:3]
        recent_avg = sum(row["mae"] or 0.0 for row in recent) / len(recent)
        prior_avg = sum(row["mae"] or 0.0 for row in prior) / len(prior)
        delta_mae = round(recent_avg - prior_avg, 4)
        if delta_mae < -0.15:
            trend = "improving"
        elif delta_mae > 0.15:
            trend = "worsening"
        else:
            trend = "stable"

    return {
        "jornadas": series,
        "overall_mae": overall_mae,
        "trend": trend,
        "delta_mae_recent": delta_mae,
        "sample_jornadas": len(series),
    }


def pujar_hit_metrics(conn: sqlite3.Connection, own_team_id: str | None) -> dict[str, Any]:
    _resolve_pujar_outcomes(conn, own_team_id)
    rows = conn.execute(
        """
        select outcome, count(*) as n
        from market_decision_snapshots
        where decision = 'PUJAR' and outcome is not null and outcome != 'unknown'
        group by outcome
        """
    ).fetchall()
    counts = {str(outcome): int(n) for outcome, n in rows}
    hits = counts.get("hit", 0)
    lost = counts.get("lost", 0)
    overbid = counts.get("overbid", 0)
    resolved = hits + lost + overbid
    rate = round(hits / resolved, 4) if resolved else None
    pending = conn.execute(
        "select count(*) from market_decision_snapshots where decision = 'PUJAR' and outcome is null"
    ).fetchone()[0]
    return {
        "resolved": resolved,
        "hits": hits,
        "lost": lost,
        "overbid": overbid,
        "hit_rate": rate,
        "hit_rate_pct": round(rate * 100.0, 1) if rate is not None else None,
        "pending": int(pending),
    }


def _ledgers_from_cache(league_id: str | None = None) -> list[dict[str, Any]]:
    try:
        ledgers = CashLedgerStore().list_ledgers(league_id)
        if ledgers:
            return ledgers
    except Exception:
        pass
    path = cache_root() / "supabase-local" / "cash_ledgers.json"
    if not path.is_file():
        return []
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _rival_profiles(conn: sqlite3.Connection) -> dict[str, RivalProfile]:
    buys_raw = conn.execute(
        """
        select team_id, amount_eur, reference_value_eur, cash_at_event_eur, positional_urgency
        from activity_buys
        where amount_eur > 0 and reference_value_eur > 0
        """
    ).fetchall()
    buys = [
        {
            "team_id": team_id,
            "amount_eur": amount,
            "reference_value_eur": ref,
            "cash_at_event_eur": cash,
            "positional_urgency": urgency,
        }
        for team_id, amount, ref, cash, urgency in buys_raw
    ]
    rivals_state: list[dict[str, Any]] = []
    for ledger in _ledgers_from_cache(None):
        team_id = ledger.get("team_id")
        if not isinstance(team_id, str):
            continue
        cash = ledger.get("observed_cash_eur")
        if not isinstance(cash, int):
            cash = ledger.get("reconstructed_cash_eur")
        rivals_state.append(
            {
                "team_id": team_id,
                "manager_name": ledger.get("manager_name") or team_id,
                "cash_eur": cash if isinstance(cash, int) else 0,
                "thin_positions": [],
            }
        )
    if not buys or not rivals_state:
        return {}
    return fit_rival_profiles_eb(buys, rivals_state)


def _expected_points_seed(conn: sqlite3.Connection, player_id: str) -> float:
    """Proyección real del jugador (última jornada guardada). Fallback neutro si no hay dato."""
    try:
        row = conn.execute(
            """
            select expected_points from matchday_snapshots
            where player_id = ? and expected_points is not null
            order by cast(jornada_id as integer) desc
            limit 1
            """,
            (player_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row and isinstance(row[0], (int, float)) and not isinstance(row[0], bool):
        return float(row[0])
    return DEFAULT_EXPECTED_PTS


def win_probability_calibration(conn: sqlite3.Connection, *, limit: int = 120) -> dict[str, Any]:
    profiles = _rival_profiles(conn)
    if not profiles:
        return {"samples": 0, "brier": None, "bins": [], "mean_predicted": None}

    rows = conn.execute(
        """
        select team_id, player_id, amount_eur, reference_value_eur
        from activity_buys
        where amount_eur > 0 and reference_value_eur > 0
        order by at desc
        limit ?
        """,
        (limit,),
    ).fetchall()

    samples: list[tuple[float, float]] = []
    for winner_id, _player_id, amount, ref in rows:
        if not isinstance(ref, int) or ref <= 0 or not isinstance(amount, int):
            continue
        winner_id = str(winner_id)
        for subject_id in profiles:
            rivals = [profile for tid, profile in profiles.items() if tid != subject_id]
            if not rivals:
                continue
            # Cada compra se contrasta con la proyección real del jugador: usar
            # una constante (6.0) metía el mismo sesgo en todas las muestras y
            # el Brier medía la constante, no al motor.
            expected_pts = _expected_points_seed(conn, str(_player_id))
            predicted = probability_of_winning_bid(float(amount), float(ref), float(ref), "MC", expected_pts, rivals)
            outcome = 1.0 if subject_id == winner_id else 0.0
            samples.append((predicted, outcome))

    if not samples:
        return {"samples": 0, "brier": None, "bins": [], "mean_predicted": None}

    brier = sum((pred - outcome) ** 2 for pred, outcome in samples) / len(samples)
    mean_pred = sum(pred for pred, _ in samples) / len(samples)

    bins: list[dict[str, Any]] = []
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
    for lo, hi in zip(edges[:-1], edges[1:]):
        bucket = [(pred, out) for pred, out in samples if lo <= pred < hi]
        if not bucket:
            continue
        bins.append(
            {
                "lo": lo,
                "hi": min(hi, 1.0),
                "count": len(bucket),
                "mean_predicted": round(sum(p for p, _ in bucket) / len(bucket), 4),
                "observed_rate": round(sum(o for _, o in bucket) / len(bucket), 4),
            }
        )

    return {
        "samples": len(samples),
        "brier": round(brier, 4),
        "mean_predicted": round(mean_pred, 4),
        "bins": bins,
    }


def compute_engine_confidence(report: dict[str, Any]) -> dict[str, Any]:
    score = 50.0
    notes: list[str] = []

    points = report.get("points") if isinstance(report.get("points"), dict) else {}
    mae = points.get("overall_mae")
    if isinstance(mae, (int, float)):
        if mae <= 2.5:
            score += 12
            notes.append("MAE de puntos bajo")
        elif mae >= 4.0:
            score -= 12
            notes.append("MAE de puntos alto")
    else:
        score -= 5
        notes.append("Sin MAE por jornada evaluada")

    if points.get("trend") == "improving":
        score += 8
        notes.append("El MAE reciente mejora")
    elif points.get("trend") == "worsening":
        score -= 8
        notes.append("El MAE reciente empeora")

    crest = report.get("sell_at_crest") if isinstance(report.get("sell_at_crest"), dict) else {}
    acc = crest.get("hit_48h_rate")
    if isinstance(acc, (int, float)):
        if acc >= 0.6:
            score += 10
        elif acc < 0.4:
            score -= 10
    elif crest.get("signals", 0) == 0:
        score -= 3

    pujar = report.get("pujar") if isinstance(report.get("pujar"), dict) else {}
    hit = pujar.get("hit_rate")
    if isinstance(hit, (int, float)):
        if hit >= 0.55:
            score += 8
        elif hit < 0.35:
            score -= 8

    sample_j = points.get("sample_jornadas") if isinstance(points.get("sample_jornadas"), int) else 0
    if sample_j >= 3:
        score += 6
    elif sample_j >= 1:
        score += 2

    win = report.get("win_probability") if isinstance(report.get("win_probability"), dict) else {}
    brier = win.get("brier")
    if isinstance(brier, (int, float)):
        if brier <= 0.18:
            score += 6
        elif brier >= 0.28:
            score -= 6

    score = int(max(0, min(100, round(score))))
    if score >= 70:
        band = "alta"
        label = "Confianza alta"
    elif score >= 45:
        band = "media"
        label = "Confianza media"
    else:
        band = "baja"
        label = "Confianza baja"

    return {
        "score": score,
        "band": band,
        "label": label,
        "notes": notes[:4],
    }


def build_calibration_report(
    *,
    db_path: Path | None = None,
    own_team_id: str | None = None,
    league_id: str | None = None,
) -> dict[str, Any]:
    path = db_path or calibration_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _ensure_tracking_schema(conn)
        sync_audit_from_local_store(conn, path.parent)
        hydrate = hydrate_audit_from_app_stores(conn, league_id=league_id)
        sync_audit_from_local_store(conn, path.parent)
        grouped = read_price_snapshots_grouped(conn)
        crest = audit_sell_at_crest(grouped)
        points = matchday_points_trend(conn)
        pujar = pujar_hit_metrics(conn, own_team_id)
        win = win_probability_calibration(conn)
        snap_rows, buy_rows = sync_audit_from_local_store(conn, path.parent)
        report: dict[str, Any] = {
            "ok": True,
            "schema_version": 1,
            "command": "calibration",
            "league_id": league_id,
            "database": str(path),
            "coverage": {
                "price_snapshots": snap_rows,
                "activity_buys": buy_rows,
                "matchday_jornadas": points.get("sample_jornadas"),
                "hydrated_from_store": hydrate,
                "cache_root": str(cache_root()),
            },
            "points": points,
            "sell_at_crest": crest,
            "pujar": pujar,
            "win_probability": win,
            "generated_at": time.time(),
        }
        report["engine_confidence"] = compute_engine_confidence(report)
        return report
    finally:
        conn.close()

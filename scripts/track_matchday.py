"""Validación empírica del motor E[Pts] por jornada.

Modos:

  python scripts/track_matchday.py --snapshot   # guarda E[pts], techo y once ILP
  python scripts/track_matchday.py --evaluate   # cruza el snapshot con puntos reales

Lee plantilla, mercado y trends desde la caja de herramientas (caché local
si no se pasa ``--fresh``). Persiste en ``.cache/responses.sqlite``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.analyzer import index_trends, optimize_from_documents, own_squad  # noqa: E402
from toolbox.cache import cache_root, madrid_day  # noqa: E402

DEFAULT_DB = cache_root() / "responses.sqlite"

_CALENDAR_KEYS = ("own_calendar", "af_calendar")
_EXPECTED_KEYS = ("own_expected_points", "af_expected_points")
_CEILING_KEYS = ("own_ceiling_points", "af_ceiling_points")


def _ensure_schema(conn: sqlite3.Connection) -> None:
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
    conn.execute(
        "create index if not exists matchday_snapshots_stored_idx on matchday_snapshots (stored_at)"
    )
    conn.commit()


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number:
            return None
        return number
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _first_number(row: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        number = _as_float(row.get(key))
        if number is not None:
            return number
    return None


def infer_jornada_id(
    trends: dict[str, Any] | None,
    squads: dict[str, Any] | None = None,
    *,
    fallback: str | None = None,
) -> str:
    """Jornada vigente: moda de la primera celda de calendario; si no hay, el día Madrid."""
    counts: Counter[int] = Counter()
    sources: list[dict[str, Any]] = []
    if isinstance(trends, dict):
        players = trends.get("players")
        if isinstance(players, list):
            sources.extend(row for row in players if isinstance(row, dict))
    squad = own_squad(squads) if isinstance(squads, dict) else None
    if squad is not None:
        players = squad.get("players")
        if isinstance(players, list):
            sources.extend(row for row in players if isinstance(row, dict))
    for player in sources:
        for key in _CALENDAR_KEYS:
            calendar = player.get(key)
            if not isinstance(calendar, list) or not calendar:
                continue
            cell = calendar[0]
            if not isinstance(cell, dict):
                continue
            matchday = _as_int(cell.get("matchday"))
            if matchday is not None and matchday > 0:
                counts[matchday] += 1
                break
    if counts:
        return str(counts.most_common(1)[0][0])
    return fallback or madrid_day()


def week_points_by_round(player: dict[str, Any]) -> dict[str, float]:
    """Mapa jornada → puntos oficiales desde ``lastStats`` / series numeradas."""
    mapping: dict[str, float] = {}
    sources: list[dict[str, Any]] = [player]
    master = player.get("playerMaster")
    if not isinstance(master, dict):
        master = player.get("player_master")
    if isinstance(master, dict):
        sources.append(master)
    for source in sources:
        for key in ("lastStats", "last_stats", "weekPoints", "week_points"):
            raw = source.get(key)
            if not isinstance(raw, list):
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                week = _as_int(item.get("weekNumber", item.get("week", item.get("matchday"))))
                points = _as_float(
                    item.get("weekPoints", item.get("totalPoints", item.get("points")))
                )
                if week is None or points is None:
                    continue
                mapping[str(week)] = points
    return mapping


def _index_week_points(documents: Iterable[dict[str, Any] | list[Any] | None]) -> dict[str, dict[str, float]]:
    indexed: dict[str, dict[str, float]] = {}
    for document in documents:
        rows: list[Any]
        if isinstance(document, list):
            rows = document
        elif isinstance(document, dict):
            if isinstance(document.get("players"), list):
                rows = document["players"]
            elif isinstance(document.get("squads"), list):
                rows = []
                for squad in document["squads"]:
                    if isinstance(squad, dict) and isinstance(squad.get("players"), list):
                        rows.extend(squad["players"])
            else:
                rows = []
        else:
            rows = []
        for player in rows:
            if not isinstance(player, dict):
                continue
            player_id = player.get("player_id") or player.get("id") or player.get("playerId")
            if player_id is None:
                master = player.get("playerMaster")
                if isinstance(master, dict):
                    player_id = master.get("id") or master.get("playerId")
            if player_id is None:
                continue
            key = str(player_id)
            mapping = week_points_by_round(player)
            if mapping:
                indexed.setdefault(key, {}).update(mapping)
    return indexed


def _xi_ids(optimized: dict[str, Any]) -> set[str]:
    xi = optimized.get("xi") if isinstance(optimized, dict) else None
    if not isinstance(xi, list):
        return set()
    ids: set[str] = set()
    for row in xi:
        if isinstance(row, dict) and isinstance(row.get("player_id"), str) and row["player_id"]:
            ids.add(row["player_id"])
    return ids


def snapshot_rows_from_documents(
    squads: dict[str, Any],
    trends: dict[str, Any] | None,
    *,
    market: dict[str, Any] | None = None,
    jornada_id: str | None = None,
    snapshot_day: str | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    squad = own_squad(squads)
    if squad is None:
        raise ValueError("La plantilla propia no está en squads. Sin ella no hay snapshot.")
    optimized = optimize_from_documents(squads, trends, cache=None, fresh=True, market=market)
    jornada = str(jornada_id or infer_jornada_id(trends, squads))
    day = snapshot_day or madrid_day()
    league_id = squads.get("league_id") if isinstance(squads.get("league_id"), str) else None
    trends_index = index_trends(trends)
    xi_ids = _xi_ids(optimized)
    rows: list[dict[str, Any]] = []
    players = squad.get("players") if isinstance(squad.get("players"), list) else []
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            continue
        trend = trends_index.get(player_id) or {}
        expected = _first_number(trend, _EXPECTED_KEYS)
        if expected is None:
            expected = _first_number(player, _EXPECTED_KEYS)
        ceiling = _first_number(trend, _CEILING_KEYS)
        if ceiling is None:
            ceiling = _first_number(player, _CEILING_KEYS)
        name = player.get("nickname") or player.get("name") or trend.get("nickname") or trend.get("name")
        rows.append(
            {
                "jornada_id": jornada,
                "player_id": player_id,
                "name": name if isinstance(name, str) else None,
                "expected_points": expected,
                "ceiling_points": ceiling,
                "in_once_optimo": 1 if player_id in xi_ids else 0,
                "league_id": league_id,
                "snapshot_day": day,
            }
        )
    meta = {
        "ok": bool(optimized.get("ok")),
        "formation": optimized.get("formation"),
        "matchday_void": bool(optimized.get("matchday_void")),
        "xi_count": len(xi_ids),
        "squad_count": len(rows),
        "league_id": league_id,
        "team_id": squad.get("team_id"),
    }
    return jornada, rows, meta


def persist_snapshot(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stamp = time.time()
    conn.executemany(
        """
        insert or replace into matchday_snapshots (
            jornada_id, player_id, name, expected_points, ceiling_points,
            in_once_optimo, league_id, snapshot_day, stored_at,
            actual_points, evaluated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, null, null)
        """,
        [
            (
                row["jornada_id"],
                row["player_id"],
                row.get("name"),
                row.get("expected_points"),
                row.get("ceiling_points"),
                int(row.get("in_once_optimo") or 0),
                row.get("league_id"),
                row.get("snapshot_day"),
                stamp,
            )
            for row in rows
        ],
    )
    conn.commit()
    return len(rows)


def latest_jornada_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "select jornada_id from matchday_snapshots order by stored_at desc, jornada_id desc limit 1"
    ).fetchone()
    return str(row[0]) if row else None


def load_snapshot_rows(conn: sqlite3.Connection, jornada_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select jornada_id, player_id, name, expected_points, ceiling_points,
               in_once_optimo, league_id, snapshot_day, stored_at
        from matchday_snapshots
        where jornada_id = ?
        order by in_once_optimo desc, name collate nocase
        """,
        (jornada_id,),
    ).fetchall()
    return [
        {
            "jornada_id": jornada_id,
            "player_id": str(player_id),
            "name": name,
            "expected_points": expected,
            "ceiling_points": ceiling,
            "in_once_optimo": bool(in_xi),
            "league_id": league_id,
            "snapshot_day": snapshot_day,
            "stored_at": stored_at,
        }
        for jornada_id, player_id, name, expected, ceiling, in_xi, league_id, snapshot_day, stored_at in rows
    ]


def evaluate_rows(
    snapshot: list[dict[str, Any]],
    actual_by_player: dict[str, dict[str, float]],
    *,
    jornada_id: str,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    abs_errors: list[float] = []
    ceiling_checked = 0
    ceiling_breaks = 0
    xi_actual: list[float] = []
    xi_missing = 0

    for row in snapshot:
        player_id = str(row["player_id"])
        mapping = actual_by_player.get(player_id) or {}
        actual = mapping.get(str(jornada_id))
        expected = _as_float(row.get("expected_points"))
        ceiling = _as_float(row.get("ceiling_points"))
        in_xi = bool(row.get("in_once_optimo"))
        if actual is not None and expected is not None:
            abs_errors.append(abs(expected - actual))
        if actual is not None and ceiling is not None:
            ceiling_checked += 1
            if actual > ceiling:
                ceiling_breaks += 1
        if in_xi:
            if actual is None:
                xi_missing += 1
            else:
                xi_actual.append(actual)
        samples.append(
            {
                "player_id": player_id,
                "name": row.get("name"),
                "expected_points": expected,
                "ceiling_points": ceiling,
                "actual_points": actual,
                "in_once_optimo": in_xi,
                "abs_error": round(abs(expected - actual), 4)
                if actual is not None and expected is not None
                else None,
                "broke_ceiling": bool(actual is not None and ceiling is not None and actual > ceiling),
            }
        )

    mae = round(sum(abs_errors) / len(abs_errors), 4) if abs_errors else None
    break_rate = round(ceiling_breaks / ceiling_checked, 4) if ceiling_checked else None
    return {
        "jornada_id": jornada_id,
        "players": len(snapshot),
        "scored": len(abs_errors),
        "mae": mae,
        "ceiling_checked": ceiling_checked,
        "ceiling_breaks": ceiling_breaks,
        "ceiling_break_rate": break_rate,
        "xi_actual_points": round(sum(xi_actual), 4) if xi_actual else None,
        "xi_scored": len(xi_actual),
        "xi_missing": xi_missing,
        "samples": samples,
    }


def _league_dir_key(league: str | None) -> str:
    raw = (league or "").strip() or "_default"
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)


def _dashboard_snapshot_path(kind: str, league: str | None) -> Path:
    return cache_root() / "dashboard" / _league_dir_key(league) / f"{kind}.json"


def _trends_document_usable(trends: Any) -> bool:
    if not isinstance(trends, dict) or trends.get("ok") is not True:
        return False
    players = trends.get("players")
    return isinstance(players, list) and len(players) > 0


def _read_cached_dashboard_board(league: str | None) -> dict[str, Any] | None:
    """Foto del tablero en ``.cache/dashboard`` (full o core), sin recalcular scrapers."""
    for kind in ("full", "core"):
        path = _dashboard_snapshot_path(kind, league)
        if not path.is_file():
            continue
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        value = envelope.get("value")
        if not isinstance(value, dict):
            continue
        trends = value.get("trends")
        if _trends_document_usable(trends):
            return value
    return None


def persist_actuals(conn: sqlite3.Connection, jornada_id: str, samples: list[dict[str, Any]]) -> None:
    stamp = time.time()
    conn.executemany(
        """
        update matchday_snapshots
        set actual_points = ?, evaluated_at = ?
        where jornada_id = ? and player_id = ?
        """,
        [
            (sample.get("actual_points"), stamp, jornada_id, sample["player_id"])
            for sample in samples
        ],
    )
    conn.commit()


def _load_live_documents(
    league: str | None,
    *,
    fresh: bool,
    include_catalog: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[Any]]:
    from toolbox.net import LaligaClient
    from toolbox.scrapers import build_trends

    squads: dict[str, Any] | None = None
    market: dict[str, Any] | None = None
    trends: dict[str, Any] | None = None

    if not fresh:
        board = _read_cached_dashboard_board(league)
        if board is not None:
            cached_squads = board.get("squads")
            cached_market = board.get("market")
            cached_trends = board.get("trends")
            if isinstance(cached_squads, dict) and cached_squads.get("ok") is True:
                squads = cached_squads
            if isinstance(cached_market, dict) and cached_market.get("ok") is True:
                market = cached_market
            if _trends_document_usable(cached_trends):
                trends = cached_trends

    catalog: list[Any] = []
    if squads is not None and market is not None and trends is not None and not include_catalog and not fresh:
        return squads, market, trends, catalog

    with LaligaClient() as client:
        if squads is None:
            squads = client.squads_document(league, fresh=fresh)
        if market is None:
            market = client.market_document(league, fresh=fresh)
        if trends is None:
            # E[Pts] no depende de Transfermarkt; omitir evita rate-limit y bloqueos.
            tm_limit = None if fresh else 0
            trends = build_trends(
                league=league,
                fresh=fresh,
                laliga=client,
                market=market,
                squads=squads,
                transfermarkt_limit=tm_limit,
            )
        if include_catalog:
            try:
                raw = client.players_document(fresh=fresh)
                catalog = raw if isinstance(raw, list) else []
            except Exception:
                catalog = []
    assert squads is not None and market is not None and trends is not None
    return squads, market, trends, catalog


def run_snapshot(
    conn: sqlite3.Connection,
    *,
    league: str | None = None,
    jornada_id: str | None = None,
    fresh: bool = False,
    squads: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_schema(conn)
    if squads is None or trends is None:
        squads, market, trends, _catalog = _load_live_documents(league, fresh=fresh, include_catalog=False)
    assert squads is not None
    jornada, rows, meta = snapshot_rows_from_documents(
        squads,
        trends,
        market=market,
        jornada_id=jornada_id,
    )
    written = persist_snapshot(conn, rows)
    return {
        "ok": True,
        "mode": "snapshot",
        "jornada_id": jornada,
        "written": written,
        **meta,
        "rows": rows,
    }


def run_evaluate(
    conn: sqlite3.Connection,
    *,
    league: str | None = None,
    jornada_id: str | None = None,
    fresh: bool = False,
    squads: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    catalog: list[Any] | None = None,
) -> dict[str, Any]:
    _ensure_schema(conn)
    jornada = jornada_id or latest_jornada_id(conn)
    if jornada is None:
        return {
            "ok": False,
            "mode": "evaluate",
            "error": "No hay snapshot previo. Ejecuta --snapshot antes de --evaluate.",
        }
    snapshot = load_snapshot_rows(conn, jornada)
    if not snapshot:
        return {
            "ok": False,
            "mode": "evaluate",
            "jornada_id": jornada,
            "error": f"No hay filas en matchday_snapshots para jornada {jornada}.",
        }
    if squads is None and trends is None and catalog is None:
        squads, _market, trends, catalog = _load_live_documents(league, fresh=fresh)
    actuals = _index_week_points((trends, squads, catalog))
    report = evaluate_rows(snapshot, actuals, jornada_id=jornada)
    persist_actuals(conn, jornada, report["samples"])
    report.update({"ok": True, "mode": "evaluate"})
    return report


def _print_snapshot(report: dict[str, Any]) -> None:
    print(f"Snapshot jornada {report['jornada_id']}")
    print(
        f"  Plantilla {report.get('squad_count', 0)} · "
        f"once ILP {report.get('xi_count', 0)} "
        f"({report.get('formation') or 'sin formación'})"
        + (" · jornada a 0" if report.get("matchday_void") else "")
    )
    print(f"  Filas escritas: {report.get('written', 0)}")
    for row in report.get("rows") or []:
        flag = "XI" if row.get("in_once_optimo") else "  "
        expected = row.get("expected_points")
        ceiling = row.get("ceiling_points")
        exp_txt = f"{expected:.2f}" if isinstance(expected, (int, float)) else "—"
        ceil_txt = f"{ceiling:.2f}" if isinstance(ceiling, (int, float)) else "—"
        label = row.get("name") or row.get("player_id")
        print(f"  [{flag}] {label}: E[pts]={exp_txt}  techo P90={ceil_txt}")


def _print_evaluate(report: dict[str, Any]) -> None:
    if not report.get("ok"):
        print(report.get("error") or "evaluate falló", file=sys.stderr)
        return
    print(f"Evaluate jornada {report['jornada_id']}")
    print(f"  Jugadores en snapshot: {report['players']}  con puntos reales: {report['scored']}")
    mae = report.get("mae")
    print(f"  MAE: {mae:.3f}" if mae is not None else "  MAE: — (sin cruces expected/real)")
    rate = report.get("ceiling_break_rate")
    checked = report.get("ceiling_checked") or 0
    breaks = report.get("ceiling_breaks") or 0
    if rate is None:
        print("  Rotura de techo (P90): —")
    else:
        print(
            f"  Rotura de techo (Monte Carlo P90): {rate:.1%}  "
            f"({breaks}/{checked}; calibración ideal ~10%)"
        )
    xi_pts = report.get("xi_actual_points")
    missing = report.get("xi_missing") or 0
    scored = report.get("xi_scored") or 0
    if xi_pts is None:
        print("  Rendimiento once ILP: — (sin puntos reales del XI)")
    else:
        extra = f"  ({missing} titulares sin puntos aún)" if missing else ""
        print(f"  Rendimiento once ILP: {xi_pts:.1f} pts reales ({scored} jugadores){extra}")
    print("  Detalle:")
    for sample in report.get("samples") or []:
        flag = "XI" if sample.get("in_once_optimo") else "  "
        actual = sample.get("actual_points")
        expected = sample.get("expected_points")
        act_txt = f"{actual:.1f}" if isinstance(actual, (int, float)) else "—"
        exp_txt = f"{expected:.2f}" if isinstance(expected, (int, float)) else "—"
        err = sample.get("abs_error")
        err_txt = f"  |e|={err:.2f}" if isinstance(err, (int, float)) else ""
        broke = "  TECHO" if sample.get("broke_ceiling") else ""
        label = sample.get("name") or sample.get("player_id")
        print(f"    [{flag}] {label}: real={act_txt}  E[pts]={exp_txt}{err_txt}{broke}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Snapshot y evaluación empírica de E[Pts] por jornada.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", action="store_true", help="Guarda E[pts], techo P90 y once ILP de la plantilla.")
    mode.add_argument("--evaluate", action="store_true", help="Cruza el snapshot con los puntos reales de la jornada.")
    parser.add_argument("--jornada", default=None, help="Id de jornada (por defecto, calendario o el último snapshot).")
    parser.add_argument("--league", default=None, help="Id de liga. Por defecto, LEAGUE_ID.")
    parser.add_argument("--fresh", action="store_true", help="Ignora la caché de lectura de LaLiga / trends.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="Ruta a responses.sqlite (por defecto .cache/responses.sqlite)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        if args.snapshot:
            report = run_snapshot(
                conn,
                league=args.league,
                jornada_id=str(args.jornada) if args.jornada is not None else None,
                fresh=bool(args.fresh),
            )
            _print_snapshot(report)
            return 0
        report = run_evaluate(
            conn,
            league=args.league,
            jornada_id=str(args.jornada) if args.jornada is not None else None,
            fresh=bool(args.fresh),
        )
        _print_evaluate(report)
        return 0 if report.get("ok") else 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

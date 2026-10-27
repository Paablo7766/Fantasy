"""Auditoría offline: precisión de SELL_AT_CREST y techos de caja rival.

Lee ``price_snapshots`` y ``activity_buys`` en ``.cache/responses.sqlite``.
Si esas tablas están vacías, las rellena desde ``.cache/supabase-local/`` y
reconstruye compras con la misma lógica que ``toolbox.league_history``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.cache import cache_root  # noqa: E402
from toolbox.empirical_audit import (  # noqa: E402
    audit_sell_at_crest,
    ensure_audit_schema,
    read_price_snapshots_grouped,
    sync_audit_from_local_store,
)

DEFAULT_DB = cache_root() / "responses.sqlite"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    ensure_audit_schema(conn)


def _sync_from_local_store(conn: sqlite3.Connection, cache: Path) -> tuple[int, int]:
    return sync_audit_from_local_store(conn, cache)


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _read_snapshots(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    return read_price_snapshots_grouped(conn)


def _replay_rival_cash(
    conn: sqlite3.Connection,
    cache: Path,
) -> dict[str, Any]:
    ledgers = _load_json_rows(cache / "supabase-local" / "cash_ledgers.json")
    if not ledgers:
        return {"teams": 0, "violations": [], "summary": {}}

    own_ids = {
        ledger.get("team_id")
        for ledger in ledgers
        if isinstance(ledger.get("observed_cash_eur"), int) and ledger.get("balanced") is True
    }
    own_ids = {team_id for team_id in own_ids if isinstance(team_id, str)}

    buys = conn.execute(
        """
        select team_id, player_id, amount_eur, reference_value_eur, cash_at_event_eur, at
        from activity_buys
        order by at
        """
    ).fetchall()

    violations: list[dict[str, Any]] = []
    ceiling_checks = 0
    ceiling_failures = 0

    for ledger in ledgers:
        team_id = ledger.get("team_id")
        if not isinstance(team_id, str) or team_id in own_ids:
            continue
        initial = ledger.get("initial_budget_eur")
        if not isinstance(initial, int):
            continue
        events = [ev for ev in (ledger.get("events") or []) if isinstance(ev, dict)]
        events.sort(key=lambda ev: (ev.get("at") or "", ev.get("kind") or ""))

        running = int(initial)
        for ev in events:
            kind = ev.get("kind")
            amount = ev.get("amount_eur")
            signed = ev.get("signed_eur")
            if not isinstance(amount, int) or isinstance(amount, bool):
                continue
            if kind == "buy":
                if amount > running:
                    violations.append(
                        {
                            "team_id": team_id,
                            "manager_name": ledger.get("manager_name"),
                            "player_id": ev.get("player_id"),
                            "amount_eur": amount,
                            "running_cash_eur": running,
                            "excess_eur": amount - running,
                            "at": ev.get("at"),
                        }
                    )
                running -= amount
            elif isinstance(signed, int):
                running += signed
            elif kind in {"sell", "premium", "clause"}:
                running += amount
            elif kind == "initial":
                running = amount

    for team_id, player_id, amount, ref, cash_at, at in buys:
        if not isinstance(team_id, str) or team_id in own_ids:
            continue
        if not isinstance(amount, int) or not isinstance(cash_at, int):
            continue
        ceiling_checks += 1
        if amount > cash_at:
            ceiling_failures += 1
            violations.append(
                {
                    "team_id": team_id,
                    "player_id": player_id,
                    "amount_eur": amount,
                    "cash_at_event_eur": cash_at,
                    "excess_eur": amount - cash_at,
                    "at": at,
                    "source": "static_ledger_ceiling",
                }
            )

    return {
        "rival_teams": len([ledger for ledger in ledgers if ledger.get("team_id") not in own_ids]),
        "replay_violations": len([v for v in violations if "running_cash_eur" in v]),
        "static_ceiling_violations": ceiling_failures,
        "static_ceiling_checks": ceiling_checks,
        "static_ceiling_valid_rate": round(1 - ceiling_failures / ceiling_checks, 4) if ceiling_checks else None,
        "violations": sorted(violations, key=lambda row: -int(row.get("excess_eur") or 0))[:15],
    }


def _snapshot_coverage(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not grouped:
        return {"players": 0, "days_min": 0, "days_max": 0, "day_span": []}
    lengths = [len(rows) for rows in grouped.values()]
    all_days = sorted({row["day"] for rows in grouped.values() for row in rows if isinstance(row.get("day"), str)})
    return {
        "players": len(grouped),
        "days_min": min(lengths),
        "days_max": max(lengths),
        "day_span": [all_days[0], all_days[-1]] if all_days else [],
    }


def run(db_path: Path) -> dict[str, Any]:
    cache = db_path.parent
    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema(conn)
        snap_n, buy_n = _sync_from_local_store(conn, cache)
        grouped = _read_snapshots(conn)
        return {
            "database": str(db_path),
            "rows": {"price_snapshots": snap_n, "activity_buys": buy_n},
            "coverage": _snapshot_coverage(grouped),
            "sell_at_crest": audit_sell_at_crest(grouped),
            "rival_cash_ceilings": _replay_rival_cash(conn, cache),
        }
    finally:
        conn.close()


def _print_report(report: dict[str, Any]) -> None:
    rows = report["rows"]
    print(f"Base: {report['database']}")
    print(f"Filas: price_snapshots={rows['price_snapshots']}  activity_buys={rows['activity_buys']}")
    cov = report["coverage"]
    print(
        f"Cobertura snapshots: {cov['players']} jugadores, "
        f"{cov['days_min']}-{cov['days_max']} dias/jugador, ventana {cov['day_span']}"
    )
    print()
    crest = report["sell_at_crest"]
    print("=== SELL_AT_CREST (backtest con histórico) ===")
    print(f"Señales detectadas: {crest['signals']}")
    if crest["signals"]:
        print(f"  Cruce delta<=0 en <=48h (1-2 dias):     {crest['hit_48h_rate']:.1%}")
        print(f"  Pico de valor a +/-1 dia del aviso:     {crest['peak_within_1d_rate']:.1%}")
        print(f"  Arrepentimiento medio a 2 dias (EUR):   {crest['mean_regret_2d_eur']:,.0f}")
        print("  Muestra (mayor regret):")
        for sample in crest["samples"][:8]:
            flags = []
            if sample["hit_48h"]:
                flags.append("hit48h")
            if sample["peak_within_1d"]:
                flags.append("pico±1d")
            print(
                f"    jugador {sample['player_id']} @ {sample['day']} "
                f"d={sample['delta_t']:,} REI={sample['rei']:.2f} "
                f"tau={sample['tau_zero']:.1f} regret={sample['regret_2d_eur']:,} "
                f"[{', '.join(flags) or '-'}]"
            )
    else:
        print("  (Sin señales en la ventana disponible; hacen falta ≥4 días por jugador.)")
    print()
    cash = report["rival_cash_ceilings"]
    print("=== Techos de caja rival ===")
    print(f"Equipos rivales: {cash['rival_teams']}")
    print(f"Compras que superan caja reconstruida (replay cronológico): {cash['replay_violations']}")
    rate = cash["static_ceiling_valid_rate"]
    checks = cash["static_ceiling_checks"]
    print(
        f"Compras vs techo estático cash_at_event (activity_buys): "
        f"{cash['static_ceiling_violations']}/{checks} violaciones"
        + (f"  (validez {rate:.1%})" if rate is not None else "")
    )
    if cash["violations"]:
        print("  Top violaciones:")
        for row in cash["violations"][:8]:
            mgr = row.get("manager_name") or row.get("team_id")
            src = row.get("source") or "replay"
            print(
                f"    {mgr} jugador {row.get('player_id')} "
                f"puja {row.get('amount_eur'):,} EUR  exceso {row.get('excess_eur'):,} EUR  ({src})"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría SELL_AT_CREST y techos de caja.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="Ruta a responses.sqlite (por defecto .cache/responses.sqlite)",
    )
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"No existe la base: {args.db}", file=sys.stderr)
        return 1
    report = run(args.db)
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Sonda de qué hay guardado, con hora, antes de medir titularidad.

No toca producción. Solo imprime inventarios.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
DB = CACHE / "responses.sqlite"


def main() -> None:
    conn = sqlite3.connect(DB)
    print("=== TABLAS ===")
    tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table' order by 1")]
    for name in tables:
        n = conn.execute(f"select count(*) from {name}").fetchone()[0]
        cols = [r[1] for r in conn.execute(f"pragma table_info({name})")]
        print(f"\n{name}: {n}")
        print("  cols:", ", ".join(cols))

    print("\n=== player_signal_log ===")
    if "player_signal_log" in tables:
        rows = conn.execute(
            """
            select day, count(*),
                   sum(p_titular_ff is not null),
                   sum(p_titular_af is not null),
                   sum(p_titular_final is not null),
                   sum(own_expected_points is not null),
                   min(stored_at), max(stored_at)
            from player_signal_log
            group by day order by day
            """
        ).fetchall()
        for r in rows:
            print(
                f"  {r[0]} n={r[1]} ff={r[2]} af={r[3]} final={r[4]} xp={r[5]} "
                f"stored {r[6]:.0f}..{r[7]:.0f}"
            )
        fuentes = conn.execute(
            "select p_titular_fuente, count(*) from player_signal_log group by 1 order by 2 desc"
        ).fetchall()
        print("  fuentes:", fuentes)
        status = conn.execute(
            "select lineup_status, count(*) from player_signal_log group by 1 order by 2 desc limit 15"
        ).fetchall()
        print("  lineup_status:", status)

    print("\n=== pre_lock ===")
    if "pre_lock_snapshots" in tables:
        for r in conn.execute("select season, jornada, kickoff, stored_at, length(payload) from pre_lock_snapshots"):
            print(" ", r)

    print("\n=== matchday_snapshots ===")
    if "matchday_snapshots" in tables:
        for r in conn.execute(
            """
            select jornada_id, count(*), sum(actual_points is not null),
                   sum(expected_points is not null), min(stored_at), max(stored_at),
                   min(kickoff), max(kickoff)
            from matchday_snapshots group by jornada_id order by 1
            """
        ):
            print(" ", r)
    if "matchday_snapshot_log" in tables:
        print(" log:")
        for r in conn.execute(
            """
            select jornada_id, snapshot_day, count(*), min(stored_at), max(kickoff)
            from matchday_snapshot_log group by 1, 2 order by 1, 2
            """
        ):
            print(" ", r)

    print("\n=== odds ===")
    for name in ("odds_snapshots", "scorer_odds_snapshots"):
        if name not in tables:
            continue
        print(name)
        cols = [r[1] for r in conn.execute(f"pragma table_info({name})")]
        print("  ", cols)
        try:
            for r in conn.execute(f"select count(*), min(stored_at), max(stored_at) from {name}"):
                print("  ", r)
        except sqlite3.OperationalError as exc:
            print("  ", exc)

    # Actas
    actas = json.loads((CACHE / "actas_jugadores.json").read_text(encoding="utf-8"))
    weeks = Counter()
    mins_pos = Counter()
    n_des = 0
    sample_des = None
    for pid, entry in actas.items():
        for w, pair in (entry.get("weeks") or {}).items():
            weeks[int(w)] += 1
        if entry.get("desglose"):
            n_des += 1
            if sample_des is None:
                sample_des = next(iter(entry["desglose"].values()))
    print("\n=== ACTAS ===")
    print("jugadores", len(actas), "con desglose", n_des)
    print("por jornada", dict(sorted(weeks.items())))
    print("desglose sample keys", list(sample_des)[:12] if isinstance(sample_des, dict) else type(sample_des))
    if isinstance(sample_des, dict):
        for k, v in list(sample_des.items())[:4]:
            if isinstance(v, dict):
                print(" ", k, list(v)[:20])

    hist = json.loads((CACHE / "historico_temporadas.json").read_text(encoding="utf-8"))
    temps = Counter()
    n_filas = 0
    sample = None
    for entrada in hist.values():
        if sample is None:
            sample = entrada
        for nombre, temp in (entrada.get("temporadas") or {}).items():
            temps[nombre] += 1
            n_filas += len(temp.get("filas") or [])
    print("\n=== HISTORICO ===")
    print("jugadores", len(hist), "filas", n_filas, "temps", dict(temps))
    if sample:
        print("keys", list(sample)[:12])
        t0 = next(iter((sample.get("temporadas") or {}).values()), None)
        if t0:
            print("temp keys", list(t0)[:12])
            filas = t0.get("filas") or []
            print("fila0", filas[0] if filas else None)

    # football-data columns
    import csv

    for name in ("SP1_2425.csv", "SP1_2526.csv", "SP1_2627.csv"):
        folder = "football_data_raw_2627" if "2627" in name else "football_data_raw"
        path = CACHE / folder / name
        if not path.is_file():
            print("missing", path)
            continue
        with path.open(encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        print(f"\n=== {name} n={len(rows)} cols={len(reader.fieldnames or [])} ===")
        interesting = [c for c in (reader.fieldnames or []) if any(s in c.lower() for s in ("date", "time", "home", "away", "fthg", "hs", "hthg"))]
        print(" ", interesting[:30])
        if rows:
            print("  row0 date/time", rows[0].get("Date"), rows[0].get("Time"), rows[0].get("HomeTeam"), rows[0].get("AwayTeam"))


if __name__ == "__main__":
    main()

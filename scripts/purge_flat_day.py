"""Borra el dia plano inventado de price_snapshots.

El 2026-10-25 se grabo con los MISMOS 148 valores del 2026-10-24: no hubo
captura real. Ese dia falso mete un delta de 0 EUR en la cinematica y esconde
el movimiento verdadero del mercado.

Uso:
    python scripts/purge_flat_day.py            # solo informa
    python scripts/purge_flat_day.py --apply    # borra de verdad
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _connect() -> sqlite3.Connection:
    db = ROOT / ".cache" / "responses.sqlite"
    if not db.is_file():
        raise SystemExit(f"No existe {db}")
    return sqlite3.connect(db)


def _days(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("select distinct day from price_snapshots order by day").fetchall()
    return [str(row[0]) for row in rows]


def _values(conn: sqlite3.Connection, day: str) -> dict[str, int | None]:
    rows = conn.execute(
        "select player_id, market_value from price_snapshots where day = ?", (day,)
    ).fetchall()
    return {str(r[0]): r[1] for r in rows}


def flat_days(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """Dias cuyo valor coincide con el dia anterior en TODOS los jugadores.

    Un dia asi no es una captura: es una copia. La app nunca graba dos dias
    iguales si ha leido el mercado de verdad, porque el mercado se mueve a
    diario. Devuelve ``(dia_plano, dia_previo, filas)``.
    """
    days = _days(conn)
    out: list[tuple[str, str, int]] = []
    for previous, current in zip(days, days[1:]):
        before, after = _values(conn, previous), _values(conn, current)
        common = set(before) & set(after)
        if len(common) < 20:
            continue
        identical = sum(1 for pid in common if before[pid] == after[pid])
        if identical == len(common):
            out.append((current, previous, len(after)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Borra dias planos inventados del historico de precios.")
    parser.add_argument("--apply", action="store_true", help="Borra de verdad (sin esto solo informa).")
    args = parser.parse_args(argv)

    conn = _connect()
    try:
        found = flat_days(conn)
        if not found:
            print("No hay dias planos: el historico esta limpio.")
            return 0
        print("Dias planos detectados (valor identico al dia anterior en todos los jugadores):")
        for day, previous, count in found:
            print(f"  {day}  == {previous}  ({count} filas)")
        if not args.apply:
            print("\nSin cambios. Repite con --apply para borrarlos.")
            return 0
        with conn:
            for day, _previous, _count in found:
                conn.execute("delete from price_snapshots where day = ?", (day,))
        print(f"\nBorrados {len(found)} dia(s). Historico limpio.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

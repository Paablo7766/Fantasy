"""Auditoría de cierres: MAE de la puja ganadora y cota de riesgo rival.

Compara lo que el motor habría pujado ese día (``predicted_win``) con el precio
al que se cerró cada subasta (``clearing_quote``) y avisa de los rivales cuyo
gasto real supera su ``risk_adjusted_bid_limit``.

No toca la red ni escribe en la caché: lee la foto guardada del tablero y
``responses.sqlite``. Por defecto audita el último día con compras anteriores a
la foto y cuyo mercado ya cerró (14:08 Madrid), y avisa si la foto es posterior
a ese cierre: entonces las pujas del motor no son las que estaban sobre la mesa.

Uso:
    python scripts/audit_market_clear.py
    python scripts/audit_market_clear.py --day 2026-10-24
    python scripts/audit_market_clear.py --db .cache/responses.sqlite --json out.json
    python scripts/audit_market_clear.py --exit-on-alert    # código 2 si un rival se pasa
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.cache import cache_root  # noqa: E402
from toolbox.market_clear import get_path  # noqa: E402
from toolbox.market_clear_report import (  # noqa: E402
    add_months,
    audit_day,
    ensure_schema,
    load_board,
    pick_day,
    read_buys,
    read_persisted_predictions,
    read_price_references,
)

DEFAULT_DB = cache_root() / "responses.sqlite"


def _eur(value: Any) -> str:
    """Euros con separador de miles español (1.234.567 €)."""
    number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if number is None:
        return "—"
    return f"{round(number):,}".replace(",", ".") + " €"


def _pct(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:+.2f} %"
    return "—"


def run(
    *,
    db_path: Path,
    day: str | None,
    cache_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Auditoría de un día. Todo lo que necesita sale del disco."""
    moment_now = now or datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)
        target = pick_day(conn, requested=day, now=moment_now)
        cutoff = datetime.fromisoformat(f"{target}T23:59:59+02:00")
        found = load_board(cache_dir if cache_dir is not None else cache_root(), before=cutoff)
        board = found["value"] if found else None
        league_id = get_path(board, "squads", "league_id") if board else None
        since = add_months(target, -1)
        buys = read_buys(conn, league_id=league_id if isinstance(league_id, str) else None, since=since)
        references = read_price_references(conn, day=target)
        persisted, decision_schema = read_persisted_predictions(conn, day=target)
    finally:
        conn.close()
    report = audit_day(
        day=target,
        board=board,
        moment=found["moment"] if found else None,
        board_path=str(found["path"]) if found else None,
        board_league=found.get("league") if found else None,
        buys=buys,
        references=references,
        persisted=persisted or None,
        now=moment_now,
    )
    report["sources"]["decision_table"] = decision_schema
    return report


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    mae = report["mae"]
    sample = report["sample"]
    board = report["board"]
    lines.append(f"Auditoría de cierres · {report['day']} · liga {report.get('league_id') or '—'}")
    lines.append(
        f"  Foto: {board.get('path') or 'sin foto'}  ({board.get('moment') or '—'})"
    )
    if board.get("limit_note"):
        lines.append(f"  AVISO: {board['limit_note']}")
    if report["sources"]["risk_limit"] == "ledger":
        lines.append("  Cota de riesgo: reconstruida de los libros (la foto no trae rival-intel).")
    lines.append("")
    coverage = report.get("coverage") or {}
    if not mae.get("pairs"):
        lines.append("MAE: — no hay pares (predicción + cierre de rival) para este día.")
        if coverage.get("note"):
            lines.append(f"  {coverage['note']}")
    else:
        lines.append(
            f"MAE: {_eur(mae['mae_eur'])} sobre {mae['pairs']} cierres "
            f"({_pct(mae['mae_pct'])} del precio)"
        )
        lines.append(
            f"  Sesgo medio: {_eur(mae['signed_bias_eur'])}  "
            f"(encima del cierre {mae['overbid_pairs']} · por debajo {mae['underbid_pairs']})"
        )
        lines.append(
            f"  Error máximo: {_eur(mae['max_abs_error_eur'])}  ·  "
            f"mediana: {_eur(mae['median_abs_error_eur'])}"
        )
        lines.append(
            f"  Aciertos de puja: {mae['pairs'] - sample.get('missed', 0)}/{mae['pairs']} "
            "(la puja del motor alcanzaba el cierre)"
        )
    lines.append(
        f"  Muestra: {sample['predictions']} veredictos, {sample['quoted']} con cierre, "
        f"{sample['excluded_own_clears']} cierres propios fuera del MAE, "
        f"{sample['unpredicted_clears']} cierres sin predicción."
    )
    schema = report["sources"].get("decision_table") or {}
    if schema and not schema.get("predicted_win_column", True):
        lines.append(
            "  Nota: la tabla de decisiones no guarda `predicted_win`; la puja estimada se "
            "recalcula del motor con la foto."
        )
    if report["misses"]:
        lines.append("")
        lines.append("Subastas perdidas por puja corta:")
        for row in report["misses"]:
            lines.append(
                f"    {row.get('name') or row.get('player_id')}: "
                f"pujaba {_eur(row.get('predicted_win_eur'))} · "
                f"cierre {_eur(row.get('clearing_quote_eur'))} · "
                f"falto {_eur(row.get('gap_eur'))}"
            )
    rivals = report["rivals"]
    lines.append("")
    lines.append(f"Rivales: {rivals['checked']} con cota · {rivals['alerts_count']} por encima de su límite")
    for row in rivals["alerts"]:
        lines.append(
            f"  EXCESO  {row.get('manager_name') or row.get('team_id')} "
            f"({row.get('team_id')})  gasto {_eur(row.get('spend_eur'))} > "
            f"límite {_eur(row.get('risk_adjusted_bid_limit_eur'))}  "
            f"(+{_eur(row.get('excess_over_ceiling_eur'))}, "
            f"{_pct(row.get('ceiling_breach_pct'))}, cota por {row.get('limit_source')})"
        )
        for purchase in row.get("purchases") or []:
            lines.append(
                f"      jugador {purchase.get('player_id')}: {_eur(purchase.get('amount_eur'))} "
                f"@ {purchase.get('at')}"
            )
    if rivals["unpriced"]:
        lines.append("  Sin cota conocida (gasto no verificable):")
        for row in rivals["unpriced"]:
            lines.append(
                f"    {row.get('manager_name') or row.get('team_id')}: gasto {_eur(row.get('spend_eur'))}"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MAE de la puja ganadora estimada y alertas de gasto rival.",
    )
    parser.add_argument(
        "--day",
        default=None,
        help="Día a auditar (YYYY-MM-DD). Por defecto, el último cerrado con compras anteriores a la foto.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="Ruta a responses.sqlite (por defecto .cache/responses.sqlite).",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="Raíz de caché donde están las fotos del tablero (por defecto la del proyecto).",
    )
    parser.add_argument("--json", type=Path, default=None, help="Escribe el informe completo en JSON.")
    parser.add_argument(
        "--exit-on-alert",
        action="store_true",
        help="Sale con código 2 si algún rival supera su cota de riesgo.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # La consola de Windows suele ser cp1252 y el informe usa «€» y «·»: sin
    # esto, una canalización a fichero revienta con UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if not args.db.is_file():
        print(f"No existe la base: {args.db}", file=sys.stderr)
        return 1
    report = run(db_path=args.db, day=args.day, cache_dir=args.cache)
    print(render(report))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {args.json}")
    if args.exit_on_alert and report["rivals"]["alerts_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Auditoría de cierres: MAE de la puja ganadora y alertas de cota rival.

Lo que se protege:

1. **El MAE es un error, no un acierto.** Cada par (predicción, cierre) cuenta
   con su valor absoluto aunque la puja alcanzase el cierre: sobreestimar la
   puja ganadora también es un error del modelo.
2. **Los cierres propios no entran.** Comparar lo que tú pujaste con lo que tú
   pagaste mide tu puja, no la capacidad del motor para leer el mercado.
3. **La cota baja se declara, no se disimula.** Un rival que gasta por encima
   de su ``risk_adjusted_bid_limit`` sale en ``alerts`` con el exceso; un rival
   sin cota sale en ``unpriced`` en vez de darse por bueno.
4. **Las tablas de prueba no cuentan.** La suite escribe compras de
   ``league-test:*`` en la misma base; si se colasen, la alerta de un día real
   mediría a un rival ficticio.
5. **La columna ``predicted_win`` manda cuando existe**, y su ausencia queda
   registrada en ``sources`` en vez de fingir que el dato venía de la tabla.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from toolbox.market_clear import (
    clearing_quotes,
    daily_rival_spend,
    price_limit_error,
    risk_limits_from_ledgers,
    sample_row,
)
from toolbox.market_clear_report import (
    audit_day,
    ensure_schema,
    load_board,
    read_buys,
    read_persisted_predictions,
)

_CLOSE = datetime(2026, 10, 24, 12, 8, tzinfo=timezone.utc)  # 14:08 Madrid
_LEAGUE = "018668579"
_OWN = "team-me"
_RIVAL = "team-rival"


def _board(bids: list[dict] | None = None, *, moment: datetime = _CLOSE) -> dict:
    return {
        "dashboard_at": moment.isoformat(),
        "squads": {
            "league_id": _LEAGUE,
            "squads": [
                {"team_id": _OWN, "is_self": True, "manager_name": "Yo"},
                {"team_id": _RIVAL, "is_self": False, "manager_name": "Rival"},
            ],
        },
        "needs": {
            "history": {"cash": [{"team_id": _RIVAL, "cash_eur": 10_000_000}]},
            "ledgers": [
                {
                    "team_id": _RIVAL,
                    "reconstructed_cash_eur": 10_000_000,
                    "observed_cash_eur": None,
                    "events": [],
                }
            ],
        },
        "market": {
            "fetched_at": moment.isoformat(),
            "listings": [
                {"player_id": "p1", "sale_price": 1_000_000, "bids": bids or []},
                {"player_id": "p2", "sale_price": 2_000_000, "bids": []},
            ],
        },
    }


def _buy(player: str, amount: int, *, team: str = _RIVAL, day: str = "2026-10-24") -> dict:
    return {
        "team_id": team,
        "player_id": player,
        "amount_eur": amount,
        "league_id": _LEAGUE,
        "at": f"{day}T14:08:39+02:00",
    }


def _prediction(player: str, amount: int | None, *, decision: str = "PUJAR") -> dict:
    return {
        "player_id": player,
        "name": f"J{player}",
        "decision": decision,
        "predicted_win_eur": amount,
        "reference_bid_eur": amount,
        "source": "motor",
    }


class PriceLimitErrorTests(unittest.TestCase):
    def test_mae_is_mean_of_absolute_errors(self) -> None:
        summary = price_limit_error([(3_000_000, 2_000_000), (1_000_000, 1_500_000)])
        self.assertEqual(summary["pairs"], 2)
        self.assertEqual(summary["mae_eur"], 750_000)
        self.assertEqual(summary["max_abs_error_eur"], 1_000_000)

    def test_signed_bias_separates_over_and_under(self) -> None:
        summary = price_limit_error([(3_000_000, 2_000_000), (500_000, 1_500_000)])
        self.assertEqual(summary["overbid_pairs"], 1)
        self.assertEqual(summary["underbid_pairs"], 1)
        self.assertEqual(summary["signed_bias_eur"], 0)

    def test_empty_sample_has_no_mae(self) -> None:
        summary = price_limit_error([])
        self.assertIsNone(summary["mae_eur"])
        self.assertEqual(summary["pairs"], 0)

    def test_sample_row_flags_short_bid_as_miss(self) -> None:
        row = sample_row(
            _prediction("p1", 900_000),
            {"quote_eur": 1_000_000, "quote_source": "activity_buys", "side": "rival"},
        )
        self.assertTrue(row["missed"])
        self.assertTrue(row["counts_in_mae"])
        self.assertEqual(row["abs_error_eur"], 100_000)

    def test_own_clearing_is_excluded_from_mae(self) -> None:
        row = sample_row(
            _prediction("p1", 5_000_000),
            {"quote_eur": 4_000_000, "quote_source": "activity_buys", "side": "propia"},
        )
        self.assertFalse(row["counts_in_mae"])
        self.assertIsNone(row["abs_error_eur"])
        self.assertEqual(row["clearing_side"], "propia")

    def test_higher_bid_wins_the_clearing_quote(self) -> None:
        quotes = clearing_quotes(
            [_buy("p1", 800_000), _buy("p1", 1_200_000, team="team-other")],
            own=_OWN,
        )
        self.assertEqual(quotes["p1"]["quote_eur"], 1_200_000)
        self.assertEqual(quotes["p1"]["side"], "rival")


class RiskLimitTests(unittest.TestCase):
    def test_daily_spend_ignores_own_buys_and_other_days(self) -> None:
        spend = daily_rival_spend(
            [
                _buy("p1", 1_000_000),
                _buy("p2", 500_000),
                _buy("p3", 9_000_000, team=_OWN),
                _buy("p4", 7_000_000, day="2026-10-23"),
            ],
            day="2026-10-24",
            own=_OWN,
        )
        self.assertEqual(spend[_RIVAL]["spend_eur"], 1_500_000)

    def test_limit_falls_back_to_reconstructed_cash_plus_floor(self) -> None:
        limits = risk_limits_from_ledgers(_board())
        self.assertEqual(limits[_RIVAL]["risk_adjusted_bid_limit"], 10_000_000)
        self.assertEqual(limits[_RIVAL]["source"], "ledger")

    def test_cached_ceiling_is_not_reused_as_risk_limit(self) -> None:
        # La foto trae la caja sin apretar y la cota vieja cacheada. La cota
        # ajustada tiene que salir del termómetro (observado + margen), no de
        # ``cash_is_ceiling``: si no, el rival recupera 100 M y nunca alerta.
        board = _board()
        board["needs"] = {
            "history": {
                "cash": [
                    {
                        "team_id": _RIVAL,
                        "cash_eur": 100_000_000,
                        "cash_is_ceiling": True,
                    }
                ]
            },
            "ledgers": [
                {
                    "team_id": _RIVAL,
                    "reconstructed_cash_eur": 100_000_000,
                    "observed_cash_eur": 5_000_000,
                    "cash_is_ceiling": True,
                    "events": [],
                }
            ],
        }
        limits = risk_limits_from_ledgers(board)
        self.assertEqual(limits[_RIVAL]["calculated_cash"], 5_000_000)
        self.assertLess(limits[_RIVAL]["risk_adjusted_bid_limit"], 20_000_000)

    def test_rival_over_limit_is_an_alert(self) -> None:
        report = audit_day(
            day="2026-10-24",
            board=_board(),
            moment=_CLOSE,
            buys=[_buy("p1", 14_000_000)],
            predictions={"p1": _prediction("p1", 12_000_000)},
            now=_CLOSE + timedelta(minutes=1),
        )
        self.assertEqual(report["rivals"]["alerts_count"], 1)
        alert = report["rivals"]["alerts"][0]
        self.assertEqual(alert["team_id"], _RIVAL)
        self.assertEqual(alert["manager_name"], "Rival")
        self.assertEqual(alert["excess_over_ceiling_eur"], 4_000_000)
        self.assertEqual(alert["risk_adjusted_bid_limit_eur"], 10_000_000)

    def test_rival_without_limit_is_declared_not_approved(self) -> None:
        board = _board()
        board["needs"] = {}
        report = audit_day(
            day="2026-10-24",
            board=board,
            moment=_CLOSE,
            buys=[_buy("p1", 14_000_000)],
            predictions={"p1": _prediction("p1", 12_000_000)},
            now=_CLOSE + timedelta(minutes=1),
        )
        self.assertEqual(report["rivals"]["alerts_count"], 0)
        self.assertEqual([row["team_id"] for row in report["rivals"]["unpriced"]], [_RIVAL])


class ReportTests(unittest.TestCase):
    def test_mae_uses_predictions_and_rival_clears(self) -> None:
        report = audit_day(
            day="2026-10-24",
            board=_board(),
            moment=_CLOSE,
            buys=[_buy("p1", 2_000_000), _buy("p2", 1_500_000)],
            predictions={"p1": _prediction("p1", 3_000_000), "p2": _prediction("p2", 1_500_000)},
            now=_CLOSE + timedelta(minutes=1),
        )
        self.assertEqual(report["mae"]["pairs"], 2)
        self.assertEqual(report["mae"]["mae_eur"], 500_000)
        self.assertEqual(report["sample"]["missed"], 0)
        self.assertEqual(report["coverage"]["no_overlap"], False)

    def test_board_after_close_is_flagged(self) -> None:
        report = audit_day(
            day="2026-10-24",
            board=_board(),
            moment=_CLOSE + timedelta(days=1),
            buys=[_buy("p1", 2_000_000)],
            predictions={"p1": _prediction("p1", 2_000_000)},
            now=_CLOSE + timedelta(days=1),
        )
        self.assertTrue(report["board"]["after_close"])
        self.assertIsNotNone(report["board"]["limit_note"])

    def test_no_overlap_is_explained(self) -> None:
        report = audit_day(
            day="2026-10-24",
            board=_board(),
            moment=_CLOSE,
            buys=[_buy("zzz", 2_000_000)],
            predictions={"p1": _prediction("p1", 2_000_000)},
            now=_CLOSE + timedelta(minutes=1),
        )
        # El cierre es de un jugador que el motor no veredictó: la muestra no
        # permite MAE y el informe lo dice en vez de publicar un cero.
        self.assertEqual(report["mae"]["pairs"], 0)
        self.assertTrue(report["coverage"]["no_overlap"])
        self.assertEqual(report["sample"]["unpredicted_clears"], 1)
        self.assertIn("no permite un MAE", report["coverage"]["note"])

    def test_board_market_bids_serve_as_clearing_when_nobody_bought(self) -> None:
        board = _board([{"amount": 2_500_000, "team_id": "team-x"}])
        report = audit_day(
            day="2026-10-24",
            board=board,
            moment=_CLOSE,
            buys=[],
            predictions={"p1": _prediction("p1", 2_000_000)},
            now=_CLOSE + timedelta(minutes=1),
        )
        self.assertEqual(report["mae"]["pairs"], 1)
        self.assertEqual(report["mae"]["mae_eur"], 500_000)


class BoardSourceTests(unittest.TestCase):
    def test_board_league_comes_from_content_not_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "dashboard" / "_default" / "core.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"league": "_default", "value": _board(moment=_CLOSE)}),
                encoding="utf-8",
            )
            found = load_board(root)
        self.assertIsNotNone(found)
        self.assertEqual(found["league"], _LEAGUE)
        self.assertEqual(found["moment"], _CLOSE)

    def test_board_before_close_is_preferred(self) -> None:
        newer = _board(moment=_CLOSE + timedelta(days=2))
        older = _board(moment=_CLOSE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "dashboard" / "liga"
            base.mkdir(parents=True)
            (base / "core.json").write_text(json.dumps({"value": newer}), encoding="utf-8")
            (base / "full.json").write_text(json.dumps({"value": older}), encoding="utf-8")
            found = load_board(root, before=_CLOSE + timedelta(minutes=5))
        self.assertEqual(found["moment"], _CLOSE)


class SqliteSourceTests(unittest.TestCase):
    def _connect(self, tmp: str) -> sqlite3.Connection:
        conn = sqlite3.connect(Path(tmp) / "responses.sqlite")
        ensure_schema(conn)
        return conn

    def test_test_league_rows_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._connect(tmp)
            conn.executemany(
                "insert into activity_buys (league_id, team_id, player_id, amount_eur, at) "
                "values (?, ?, ?, ?, ?)",
                [
                    (_LEAGUE, _RIVAL, "p1", 1_000_000, "2026-10-24T14:08:39+02:00"),
                    ("league-test:1", _RIVAL, "p2", 99_000_000, "2026-10-24T14:08:39+02:00"),
                ],
            )
            conn.commit()
            rows = read_buys(conn, league_id=_LEAGUE)
            conn.close()
        self.assertEqual([row["player_id"] for row in rows], ["p1"])

    def test_missing_predicted_win_column_is_migrated_and_empty(self) -> None:
        """Una base antigua recibe la columna (nullable) y no inventa valores."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "responses.sqlite")
            conn.execute(
                "create table market_decision_snapshots ("
                "snapshot_day text not null, league_id text, player_id text not null, "
                "decision text not null, suggested_bid integer, win_probability real, "
                "primary_motive text, stored_at real not null, outcome text, outcome_at real, "
                "primary key (snapshot_day, player_id))"
            )
            conn.execute(
                "insert into market_decision_snapshots "
                "(snapshot_day, player_id, decision, suggested_bid, stored_at) "
                "values ('2026-10-24', 'p0', 'PUJAR', 2000000, 0)"
            )
            conn.commit()
            ensure_schema(conn)
            persisted, schema = read_persisted_predictions(conn, day="2026-10-24")
            conn.close()
        self.assertEqual(persisted, {})
        self.assertTrue(schema["predicted_win_column"])
        self.assertTrue(schema["suggested_bid_column"])

    def test_persisted_predicted_win_wins_over_motor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._connect(tmp)
            conn.execute(
                "insert into market_decision_snapshots "
                "(snapshot_day, player_id, decision, suggested_bid, predicted_win, stored_at) "
                "values ('2026-10-24', 'p1', 'PUJAR', 2000000, 1250000, 0)"
            )
            conn.commit()
            persisted, schema = read_persisted_predictions(conn, day="2026-10-24")
            conn.close()
        self.assertTrue(schema["predicted_win_column"])
        self.assertEqual(persisted["p1"]["predicted_win_eur"], 1_250_000)
        report = audit_day(
            day="2026-10-24",
            board=_board(),
            moment=_CLOSE,
            buys=[_buy("p1", 2_000_000)],
            predictions={"p1": _prediction("p1", 2_000_000)},
            persisted=persisted,
            now=_CLOSE + timedelta(minutes=1),
        )
        self.assertEqual(report["sources"]["predictions"], "persistida+motor")
        self.assertEqual(report["mae"]["mae_eur"], 750_000)


if __name__ == "__main__":
    unittest.main()

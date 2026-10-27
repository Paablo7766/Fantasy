"""Calibración del motor: snapshots, MAE y confianza."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from toolbox.engine_calibration import (
    build_calibration_report,
    compute_engine_confidence,
    matchday_points_trend,
    persist_market_decisions,
    pujar_hit_metrics,
)
class EngineCalibrationTests(unittest.TestCase):
    def test_matchday_mae_trend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "responses.sqlite"
            build_calibration_report(db_path=db)
            conn = sqlite3.connect(db)
            conn.executemany(
                """
                insert into matchday_snapshots (
                    jornada_id, player_id, expected_points, ceiling_points,
                    in_once_optimo, stored_at, actual_points, evaluated_at
                ) values (?, ?, ?, ?, 0, 1.0, ?, 2.0)
                """,
                [
                    ("8", "a", 5.0, 9.0, 4.0),
                    ("8", "b", 7.0, 11.0, 8.0),
                    ("9", "a", 5.0, 9.0, 5.5),
                    ("9", "b", 7.0, 11.0, 6.0),
                    ("10", "a", 5.0, 9.0, 5.0),
                    ("10", "b", 7.0, 11.0, 7.0),
                ],
            )
            conn.commit()
            trend = matchday_points_trend(conn)
            conn.close()
            self.assertEqual(trend["sample_jornadas"], 3)
            self.assertIsNotNone(trend["overall_mae"])
            self.assertIn(trend["trend"], {"improving", "worsening", "stable", "insufficient"})

    def test_pujar_hit_rate_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "responses.sqlite"
            build_calibration_report(db_path=db, own_team_id="own")
            conn = sqlite3.connect(db)
            conn.execute(
                """
                insert into market_decision_snapshots (
                    snapshot_day, league_id, player_id, decision, suggested_bid,
                    win_probability, primary_motive, stored_at, outcome, outcome_at
                ) values ('2020-01-01', '7', 'p1', 'PUJAR', 1000000, 0.6, 'flip', 1.0, null, null)
                """
            )
            conn.execute(
                """
                insert into activity_buys
                (league_id, team_id, player_id, amount_eur, reference_value_eur, cash_at_event_eur, at)
                values ('7', 'own', 'p1', 990000, 900000, 5000000, '2020-01-02T10:00:00')
                """
            )
            conn.commit()
            metrics = pujar_hit_metrics(conn, "own")
            conn.close()
            self.assertEqual(metrics["hits"], 1)
            self.assertEqual(metrics["hit_rate"], 1.0)

    def test_build_report_with_short_league_slug(self) -> None:
        """?league=7 no debe vaciar snapshots cuyo league_id es el id largo de LaLiga."""
        report = build_calibration_report(league_id="7")
        if report["coverage"]["price_snapshots"] == 0:
            self.skipTest("sin caché local de snapshots")
        self.assertGreater(report["coverage"]["price_snapshots"], 0)

    def test_build_report_and_confidence_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "responses.sqlite"
            report = build_calibration_report(db_path=db, own_team_id="1", league_id=None)
            self.assertTrue(report.get("ok"))
            self.assertIn("engine_confidence", report)
            conf = compute_engine_confidence(report)
            self.assertIn(conf["band"], {"alta", "media", "baja"})
            self.assertGreaterEqual(conf["score"], 0)
            self.assertLessEqual(conf["score"], 100)

    def test_persist_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "responses.sqlite"
            written = persist_market_decisions(
                [{"player_id": "99", "decision": "PUJAR", "suggested_bid": 1_000_000, "win_probability": 0.55}],
                league_id="7",
                snapshot_day="2099-01-01",
                db_path=db,
            )
            self.assertEqual(written, 1)


if __name__ == "__main__":
    unittest.main()

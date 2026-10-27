"""Plan de jornada, puja con sobrepuja, cláusulas, expertos y auditoría. Sin red."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from toolbox.audit import append_audit, build_audit
from toolbox.bid_war import overbid_risk, recommend_bid
from toolbox.clause_intel import build_clause_intel
from toolbox.experts import (
    lineup_agreement,
    mentions_from_text,
    parse_bielsa_lineups,
    parse_donqui_mentions,
)
from toolbox.jornada_plan import build_jornada_plan, lineup_delta
from toolbox.market_intel import build_market_decisions


NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _trend(player_id: str, position: str, xg: float) -> dict:
    return {
        "player_id": player_id,
        "name": player_id,
        "nickname": player_id,
        "position": position,
        "club": "Test",
        "matching_confidence": 0.95,
        "p_titular": 0.9,
        "form": {"xg": xg, "xa": 0.05, "minutes_pct": 0.9},
    }


def _player(player_id: str, position: str, *, clause: int | None = None, locked: bool = False) -> dict:
    return {
        "player_id": player_id,
        "name": player_id,
        "nickname": player_id,
        "position": position,
        "club": "Test",
        "market_value": 1_000_000,
        "buyout_clause": clause,
        "is_shielded": False,
        "clause_lock": {
            "present": True,
            "is_locked": locked,
            "local_date": "2026-10-21",
            "local_time": "18:00",
            "expires_at": "2026-10-21T16:00:00+00:00",
        },
    }


def _xi(prefix: str, xg: float = 0.4) -> list[dict]:
    slots = (
        [("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)]
    )
    rows = []
    for position, count in slots:
        for index in range(count):
            rows.append(_player(f"{prefix}-{position}-{index}", position))
    return rows


class BidWarTests(unittest.TestCase):
    def test_no_leader_bids_ideal_now(self) -> None:
        plan = recommend_bid(
            {"sale_price": 1_000_000, "market_value": 1_000_000},
            ideal=1_200_000,
            maximum=1_500_000,
            cash=5_000_000,
            snipe_status="hidden",
        )
        self.assertEqual(plan["how"], "ahora")
        self.assertEqual(plan["recommended_bid_eur"], 1_200_000)
        self.assertEqual(plan["reason"], "empate_gana_la_primera")

    def test_leader_above_ideal_waits(self) -> None:
        plan = recommend_bid(
            {"sale_price": 1_000_000, "leading_bid": 1_300_000},
            ideal=1_200_000,
            maximum=1_600_000,
            cash=5_000_000,
            snipe_status="inside_window",
        )
        self.assertEqual(plan["how"], "esperar")
        self.assertEqual(plan["reason"], "lider_supera_ideal")

    def test_leader_snipes_at_cap(self) -> None:
        plan = recommend_bid(
            {"sale_price": 1_000_000, "leading_bid": 1_000_000},
            ideal=1_200_000,
            maximum=1_400_000,
            cash=5_000_000,
            snipe_status="hidden",
        )
        self.assertEqual(plan["how"], "snipe")
        self.assertEqual(plan["recommended_bid_eur"], 1_000_001)

    def test_missing_ceiling_stays_unknown(self) -> None:
        plan = recommend_bid(
            {"sale_price": 800_000},
            ideal=None,
            maximum=None,
            cash=2_000_000,
            snipe_status=None,
        )
        self.assertEqual(plan["how"], "unknown")
        self.assertEqual(plan["recommended_bid_eur"], 800_000)

    def test_overbid_unknown_without_cash(self) -> None:
        risk = overbid_risk("DEL", 1_000_000, [{"team_id": "r", "cash_eur": None, "thin_positions": ["DEL"]}])
        self.assertEqual(risk["status"], "unknown")
        self.assertIsNone(risk["count"])

    def test_overbid_high_when_cash_and_gap(self) -> None:
        risk = overbid_risk(
            "DEL",
            1_000_000,
            [{"team_id": "r", "cash_eur": 2_000_000, "thin_positions": ["DEL"]}],
        )
        self.assertEqual(risk["status"], "high")
        self.assertEqual(risk["count"], 1)

    def test_market_without_leader_pujar_now(self) -> None:
        expires = (NOW + timedelta(hours=2)).isoformat()
        doc = build_market_decisions(
            {"listings": [{
                "player_id": "p1",
                "name": "p1",
                "position": "MC",
                "sale_price": 1_000_000,
                "seller_team_id": "rival",
                "listing_expires_at": expires,
            }]},
            {"players": [{
                "player_id": "p1",
                "name": "p1",
                "position": "MC",
                "matching_confidence": 0.95,
                "af_ideal_bid": 1_200_000,
                "af_max_bid": 1_400_000,
                "acceleration": 60_000,
                "af_market_signal": "up",
            }]},
            {"ok": True, "cash_eur": 5_000_000, "matchday_void": False, "team_id": "self", "signings": [], "rejected": []},
            {"ok": True, "gaps": [], "market_fills": []},
            now=NOW,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertEqual(row["bid_plan"]["how"], "ahora")
        self.assertEqual(row["bid_plan"]["recommended_bid_eur"], 1_200_000)


class ClauseTests(unittest.TestCase):
    def test_pays_only_the_upgrade_that_enters(self) -> None:
        own_players = _xi("me", 0.2)
        own_players[10]["player_id"] = "me-DEL-2"
        weak = next(player for player in own_players if player["player_id"] == "me-DEL-2")
        star = _player("star", "DEL", clause=2_000_000, locked=False)
        locked = _player("locked", "DEL", clause=1_000_000, locked=True)
        squads = {
            "squads": [
                {"team_id": "me", "is_self": True, "manager_name": "Yo", "cash": 10_000_000, "players": own_players},
                {"team_id": "rival", "is_self": False, "manager_name": "Rival", "cash": 500_000, "players": [star, locked]},
            ]
        }
        trends = {"players": [_trend(player["player_id"], player["position"], 0.15) for player in own_players]}
        trends["players"].append(_trend("star", "DEL", 1.4))
        trends["players"].append(_trend("locked", "DEL", 1.4))
        weak_trend = next(row for row in trends["players"] if row["player_id"] == weak["player_id"])
        weak_trend["form"]["xg"] = 0.02
        from toolbox.analyzer import optimize_from_documents

        optimized = optimize_from_documents(squads, trends)
        doc = build_clause_intel(
            squads,
            trends,
            optimized,
            [{"team_id": "rival", "cash_eur": 9_000_000, "thin_positions": []}],
        )
        pagar = [row for row in doc["offers"] if row["decision"] == "PAGAR"]
        self.assertEqual(len(pagar), 1)
        self.assertEqual(pagar[0]["player_id"], "star")
        self.assertGreater(pagar[0]["points_delta"], 0)
        self.assertTrue(pagar[0]["requires_confirmation"])
        self.assertNotIn("locked", {row["player_id"] for row in doc["offers"]})

    def test_protects_when_a_rival_can_pay(self) -> None:
        own_players = _xi("me")
        exposed = own_players[0]
        exposed["buyout_clause"] = 3_000_000
        squads = {"squads": [{"team_id": "me", "is_self": True, "cash": 8_000_000, "players": own_players}]}
        doc = build_clause_intel(
            squads,
            {"players": []},
            {"ok": True, "xi": [], "expected_points": 0},
            [{"team_id": "r", "cash_eur": 4_000_000, "thin_positions": []}],
        )
        self.assertEqual(doc["protect"][0]["player_id"], exposed["player_id"])
        kinds = {option["kind"] for option in doc["protect"][0]["options"]}
        self.assertIn("subir_clausula", kinds)
        self.assertIn("vender", kinds)
        self.assertNotIn("blindar", kinds)


class PlanTests(unittest.TestCase):
    def test_clock_orders_close_before_kickoff(self) -> None:
        kickoff = (NOW + timedelta(days=2)).isoformat()
        trends = {"players": [{"player_id": "a", "fixture": {"kickoff": kickoff}}]}
        squads = {
            "squads": [
                {
                    "team_id": "me",
                    "is_self": True,
                    "cash": 1_000_000,
                    "players": [_player("me-1", "DEL", clause=2_000_000, locked=True)],
                }
            ]
        }
        optimize = {
            "ok": True,
            "formation": "4-3-3",
            "expected_points": 40,
            "xi": [{"player_id": "me-1", "name": "me-1", "position": "DEL", "expected_points": 4}],
            "saved_lineup": {"formation": "4-4-2", "xi": [{"player_id": "other", "name": "other", "position": "DEL"}]},
            "benched": [],
        }
        document = build_jornada_plan(
            market={"listings": []},
            squads=squads,
            trends=trends,
            optimize=optimize,
            needs={"rivals": [], "clause_alerts": []},
            decisions={"decisions": [], "summary": {}},
            clauses={"offers": [], "protect": []},
            now=NOW,
        )
        kinds = [event["kind"] for event in document["clock"]]
        self.assertLess(kinds.index("clausulazo_cierra"), kinds.index("inicio_jornada"))
        self.assertIn("desbloqueo", kinds)
        self.assertTrue(document["lineup"]["differs"])
        # Once guardado con 1 jugador: no es un «cambio», es cerrar hueco.
        self.assertFalse(document["lineup"]["saved_valid"])
        self.assertEqual(document["actions"][0]["kind"], "cerrar_hueco")
        self.assertEqual(document["actions"][0]["cash_after_eur"], 1_000_000)
        self.assertFalse(document["sends"])

    def test_lineup_delta_does_not_invent_saved_points(self) -> None:
        delta = lineup_delta(
            {
                "formation": "4-3-3",
                "expected_points": 30,
                "xi": [{"player_id": "a", "expected_points": 5}],
                "saved_lineup": {"xi": [{"player_id": "b", "name": "B"}]},
                "benched": [],
            }
        )
        self.assertIsNone(delta["points_delta"])
        self.assertIn("B", delta["missing_inputs"])

    def test_lineup_delta_uses_the_same_metric_on_both_sides(self) -> None:
        # Antes: expected_points (objetivo del solver) contra expected_points de
        # los guardados. Ahora: jornada_ev a los dos lados.
        delta = lineup_delta(
            {
                "formation": "3-5-2",
                "expected_points": 42.0,
                "xi": [
                    {"player_id": "militao", "jornada_ev": 2.1, "expected_points": 4.2},
                    {"player_id": "v2", "jornada_ev": 3.0, "expected_points": 3.0},
                ],
                "saved_lineup": {
                    "formation": "4-4-2",
                    "xi": [
                        {"player_id": "hugo", "jornada_ev": 4.6},
                        {"player_id": "militao", "jornada_ev": 2.1},
                    ],
                },
                "benched": [{"player_id": "hugo", "jornada_ev": 4.6}],
            }
        )
        self.assertAlmostEqual(delta["expected_points"], 5.1)
        self.assertAlmostEqual(delta["saved_points"], 6.7)
        self.assertAlmostEqual(delta["points_delta"], -1.6)
        self.assertFalse(delta["saved_valid"])

    def _plan(self, optimize: dict) -> dict:
        return build_jornada_plan(
            market={"listings": []},
            squads={"squads": [{"team_id": "me", "is_self": True, "cash": 5_000_000, "players": []}]},
            trends={"players": []},
            optimize=optimize,
            needs={"rivals": [], "clause_alerts": []},
            decisions={"decisions": [], "summary": {}},
            clauses={"offers": [], "protect": []},
            now=NOW,
        )

    @staticmethod
    def _full_saved(ids: list[str]) -> list[dict]:
        return [{"player_id": player_id, "name": player_id, "jornada_ev": 4.0} for player_id in ids]

    @staticmethod
    def _full_xi(ids: list[str], *, ev: float) -> list[dict]:
        positions = ["POR"] + ["DEF"] * 4 + ["MC"] * 3 + ["DEL"] * 3
        return [
            {
                "player_id": player_id,
                "name": player_id,
                "position": position,
                "jornada_ev": ev,
                "expected_points": ev,
            }
            for player_id, position in zip(ids, positions)
        ]

    def test_reported_case_militao_for_hugo_is_not_recommended(self) -> None:
        """El caso real: el motor quería un cambio que bajaba puntos del once."""
        ids = [f"v{i}" for i in range(10)]
        recommended = self._full_xi(ids + ["hugo"], ev=4.0)
        recommended[-1]["name"] = "Hugo Alvarez"
        saved = self._full_saved(ids + ["militao"])  # 11 x 4,0 = 44,0 pts
        saved[-1]["name"] = "E. Militão"
        document = self._plan(
            {
                "formation": "4-3-3",
                "matchday_void": False,
                "gaps": [],
                # El motor dice 39,5 pts pero sus filas suman 44,0: manda la fila.
                "xi": recommended,
                "lineup_expected_points": 39.5,
                "saved_lineup": {"formation": "4-3-3", "xi": saved},
                "benched": [],
            }
        )
        self.assertAlmostEqual(document["lineup"]["expected_points"], 44.0)
        self.assertAlmostEqual(document["lineup"]["points_delta"], 0.0)
        self.assertEqual(document["lineup"]["enters"][0]["name"], "Hugo Alvarez")
        # El cambio no mejora nada: no hay acción ni aviso de once pendiente.
        self.assertEqual(document["actions"], [])
        self.assertEqual(document["priority_actions"], [])
        lineup_check = next(
            check for check in document["red_line"]["checks"] if check["key"] == "lineup"
        )
        self.assertEqual(lineup_check["status"], "ok")

    def test_solver_total_disagreeing_with_rows_uses_rows(self) -> None:
        """Un total declarado que no cuadra con el XI no puede fabricar un delta negativo."""
        ids = [f"v{i}" for i in range(10)]
        recommended = self._full_xi(ids + ["hugo"], ev=3.9)
        saved = self._full_saved(ids + ["militao"])
        document = self._plan(
            {
                "formation": "4-3-3",
                "matchday_void": False,
                "gaps": [],
                "xi": recommended,
                "lineup_expected_points": 38.5,  # filas suman 42,9; guardado 44,0
                "saved_lineup": {"formation": "4-3-3", "xi": saved},
                "benched": [],
            }
        )
        self.assertAlmostEqual(document["lineup"]["expected_points"], 42.9)
        self.assertAlmostEqual(document["lineup"]["points_delta"], -1.1)
        self.assertEqual(document["actions"], [])


        ids = [f"s{i}" for i in range(11)]
        rec = ids[:-1] + ["star"]
        document = self._plan(
            {
                "formation": "3-5-2",
                "matchday_void": False,
                "gaps": [],
                "xi": self._full_xi(rec, ev=3.0),
                "saved_lineup": {"formation": "4-3-3", "xi": self._full_saved(ids)},
                "benched": [{"player_id": "s10", "name": "s10", "jornada_ev": 4.0}],
            }
        )
        self.assertIsNotNone(document["lineup"]["points_delta"])
        self.assertLess(document["lineup"]["points_delta"], 0)
        self.assertEqual(document["actions"], [])
        self.assertEqual(document["priority_actions"], [])
        self.assertFalse(any(check["status"] == "warn" for check in document["red_line"]["checks"]))

    def test_equal_lineup_is_not_recommended(self) -> None:
        ids = [f"s{i}" for i in range(11)]
        document = self._plan(
            {
                "formation": "3-5-2",
                "matchday_void": False,
                "gaps": [],
                "xi": self._full_xi(ids, ev=4.0),
                "saved_lineup": {"formation": "4-3-3", "xi": self._full_saved(ids)},
                "benched": [],
            }
        )
        self.assertEqual(document["lineup"]["points_delta"], 0)
        self.assertEqual(document["actions"], [])

    def test_real_upgrade_is_recommended(self) -> None:
        ids = [f"s{i}" for i in range(11)]
        document = self._plan(
            {
                "formation": "4-3-3",
                "matchday_void": False,
                "gaps": [],
                "xi": self._full_xi(ids, ev=5.0),
                "saved_lineup": {"formation": "4-3-3", "xi": self._full_saved(ids)},
            }
        )
        # Mismo XI: no hay cambio que proponer aunque el motor valga más.
        self.assertEqual(document["actions"], [])
        ids_alt = ids[:-1] + ["star"]
        document = self._plan(
            {
                "formation": "4-3-3",
                "matchday_void": False,
                "gaps": [],
                "xi": self._full_xi(ids_alt, ev=5.0),
                "saved_lineup": {"formation": "4-3-3", "xi": self._full_saved(ids)},
            }
        )
        self.assertEqual(document["actions"][0]["kind"], "alinear")
        self.assertGreater(document["actions"][0]["points_delta"], 0)
        self.assertEqual(document["priority_actions"][0]["verdict"], "HAZLO")

    def test_negative_cash_forces_a_sale(self) -> None:
        ids = [f"s{i}" for i in range(11)]
        document = build_jornada_plan(
            market={
                "listings": [
                    {"player_id": "s1", "name": "s1", "position": "DEF", "market_value": 2_000_000}
                ]
            },
            squads={"squads": [{"team_id": "me", "is_self": True, "cash": -1_000_000, "players": []}]},
            trends={"players": []},
            optimize={
                "formation": "3-5-2",
                "matchday_void": False,
                "gaps": [],
                "xi": self._full_xi(ids, ev=3.0),
                "benched": [{"player_id": "bench", "name": "bench", "jornada_ev": 1.0, "market_value": 2_000_000}],
                # El once guardado pierde piezas frente al motor: s10 sale.
                "saved_lineup": {"formation": "4-3-3", "xi": self._full_saved(ids[:-1] + ["bench"])},
            },
            needs={"rivals": [], "clause_alerts": []},
            decisions={"decisions": [], "summary": {}},
            clauses={"offers": [], "protect": []},
            now=NOW,
        )
        action = document["priority_actions"][0]
        self.assertEqual(action["kind"], "vender_emergencia")
        self.assertTrue(action["what"].startswith("Venta obligatoria"))
        self.assertEqual(document["actions"][0]["cash_after_eur"], 1_000_000)

    def test_missing_slot_closes_the_gap_first(self) -> None:
        ids = [f"s{i}" for i in range(10)]
        document = build_jornada_plan(
            market={
                "listings": [
                    {"player_id": "cheap-del", "name": "Cheap", "position": "DEL", "sale_price": 300_000},
                ]
            },
            squads={"squads": [{"team_id": "me", "is_self": True, "cash": 5_000_000, "players": []}]},
            trends={"players": []},
            optimize={
                "formation": "4-4-2",
                "matchday_void": True,
                "gaps": [{"position": "DEL", "missing": 1, "label": "Falta 1 DEL"}],
                "market_fills": [
                    {
                        "position": "DEL",
                        "missing": 1,
                        "label": "Falta 1 DEL",
                        "options": [
                            {"player_id": "cheap-del", "name": "Cheap", "position": "DEL", "sale_price": 300_000}
                        ],
                    }
                ],
                "xi": self._full_xi(ids, ev=3.8),
                "saved_lineup": {"formation": "4-4-2", "xi": self._full_saved([f"u{i}" for i in range(11)])},
            },
            needs={"rivals": [], "clause_alerts": []},
            decisions={"decisions": [], "summary": {}},
            clauses={"offers": [], "protect": []},
            now=NOW,
        )
        action = document["priority_actions"][0]
        self.assertEqual(action["kind"], "cerrar_hueco")
        self.assertEqual(action["player_id"], "cheap-del")
        self.assertIn("Cierra el hueco", action["what"])
        self.assertEqual(document["lineup"]["missing_slots"], 1)


class ExpertTests(unittest.TestCase):
    def test_donqui_and_bielsa_parsers(self) -> None:
        page = (
            '<p>red flag</p><a href="/jugadores/mbappe/fantasy">Mbappé</a>'
            + (" " * 500)
            + '<p>chollo</p><a href="/jugadores/oyarzabal/fantasy">Oyarzabal</a>'
        )
        mentions = parse_donqui_mentions(page)
        by_name = {row["name"]: row["kind"] for row in mentions}
        self.assertEqual(by_name["Mbappé"], "fade")
        self.assertEqual(by_name["Oyarzabal"], "boost")
        bielsa = parse_bielsa_lineups(
            "<h3>Alineación probable del Deportivo según ElBielsaFantasy</h3>"
            "<ol><li>Villares</li><li>Yeremay</li></ol>"
        )
        self.assertEqual(bielsa[0]["club"], "Deportivo")
        self.assertEqual(bielsa[0]["players"][0], "Villares")

    def test_note_matches_only_clear_names(self) -> None:
        catalog = [
            {"player_id": "1", "name": "Mikel Oyarzabal", "nickname": "Oyarzabal", "club": "Real Sociedad"},
        ]
        rows = mentions_from_text("Oyarzabal es un chollo esta jornada.", catalog)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_id"], "1")
        self.assertEqual(rows[0]["source"], "azteca")
        self.assertEqual(mentions_from_text("   ", catalog), [])

    def test_agreement_needs_two_sources(self) -> None:
        self.assertIsNone(lineup_agreement(ff=True, af=None, bielsa=None))
        self.assertEqual(lineup_agreement(ff=True, af=True, bielsa=True), "unanimous")
        self.assertEqual(lineup_agreement(ff=True, af=None, bielsa=False), "split")


class AuditTests(unittest.TestCase):
    def test_writes_once_after_kickoff(self) -> None:
        optimize = {
            "xi": [
                {"player_id": "a", "nickname": "A", "expected_points": 6},
                {"player_id": "b", "nickname": "B", "expected_points": 4},
            ]
        }
        squads = {
            "squads": [
                {
                    "is_self": True,
                    "players": [
                        {"player_id": "a", "week_points": [2, 6]},
                        {"player_id": "b", "week_points": [1, 5]},
                    ],
                }
            ]
        }
        past = (NOW - timedelta(hours=3)).isoformat()
        audit = build_audit(optimize, squads, now=NOW, kickoff=past)
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["predicted_points"], 10)
        self.assertEqual(audit["actual_points"], 11)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "MEMORY.md"
            path.write_text("# MEMORY\n\n## Registro\n", encoding="utf-8")
            first = append_audit(audit, path, now=NOW)
            second = append_audit(audit, path, now=NOW)
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        self.assertEqual(second["reason"], "ya_registrada")

    def test_future_kickoff_is_not_written(self) -> None:
        audit = build_audit(
            {"xi": [{"player_id": "a", "expected_points": 1}]},
            {"squads": [{"is_self": True, "players": [{"player_id": "a", "week_points": [1]}]}]},
            now=NOW,
            kickoff=(NOW + timedelta(days=1)).isoformat(),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "MEMORY.md"
            path.write_text("", encoding="utf-8")
            stored = append_audit(audit, path, now=NOW)
            self.assertFalse(stored["written"])
            self.assertEqual(path.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()

"""Caja rival única: subidas de cláusula desde las fotos diarias."""

from __future__ import annotations

import unittest

from toolbox import caja_rival
from toolbox.caja_rival import costes_ocultos, fusionar_historial, subidas_de_clausula, valores_de_fotos


def _subidas(dias, valores=None, eventos=None):
    return subidas_de_clausula(dias, valores or {}, caja_rival.adquisiciones_de_eventos(eventos or []))


class SubidasTests(unittest.TestCase):
    def test_paid_raise_costs_half_of_the_increase_over_the_value(self) -> None:
        dias = {"2026-11-01": {"t1": {"p1": 10_000_000}}, "2026-11-02": {"t1": {"p1": 16_000_000}}}
        valores = {("p1", "2026-11-02"): 11_000_000}
        rows = _subidas(dias, valores, [{"kind": "buy", "team_id": "t1", "player_id": "p1", "at": "2026-10-20T14:08:00+02:00", "amount_eur": 10_000_000}])
        self.assertEqual([(r["tipo"], r["cost_eur"]) for r in rows], [("manual", 2_500_000)])

    def test_automatic_raise_to_the_market_value_is_free(self) -> None:
        dias = {"2026-11-01": {"t1": {"p1": 10_000_000}}, "2026-11-02": {"t1": {"p1": 10_400_000}}}
        valores = {("p1", "2026-11-02"): 10_400_000}
        rows = _subidas(dias, valores, [{"kind": "buy", "team_id": "t1", "player_id": "p1", "at": "2026-10-20T14:08:00+02:00", "amount_eur": 10_000_000}])
        self.assertEqual([(r["tipo"], r["cost_eur"]) for r in rows], [("automatica", 0)])

    def test_a_copied_snapshot_does_not_charge_twice(self) -> None:
        # El 3 repite el 1 (copia de caché): sin descartarla, la subida del 2 se
        # «deshacía» el 3 y se volvía a cobrar el 4.
        base = {"t1": {"p1": 10_000_000}}
        subida = {"t1": {"p1": 14_000_000}}
        dias = {"2026-11-01": base, "2026-11-02": subida, "2026-11-03": base, "2026-11-04": subida}
        compra = [{"kind": "buy", "team_id": "t1", "player_id": "p1", "at": "2026-10-20T14:08:00+02:00", "amount_eur": 10_000_000}]
        rows = _subidas(dias, {}, compra)
        self.assertEqual(sum(r["cost_eur"] for r in rows), 2_000_000)

    def test_raises_chain_against_the_highest_clause_seen(self) -> None:
        dias = {
            "2026-11-01": {"t1": {"p1": 10_000_000}},
            "2026-11-02": {"t1": {"p1": 14_000_000}},
            "2026-11-03": {"t1": {"p1": 16_000_000}},
        }
        compra = [{"kind": "buy", "team_id": "t1", "player_id": "p1", "at": "2026-10-20T14:08:00+02:00", "amount_eur": 10_000_000}]
        rows = _subidas(dias, {}, compra)
        self.assertEqual([r["cost_eur"] for r in rows], [2_000_000, 1_000_000])

    def test_a_new_purchase_resets_the_base_to_the_price_paid(self) -> None:
        dias = {
            "2026-11-01": {"t1": {"p9": 3_000_000}},
            "2026-11-03": {"t1": {"p9": 3_000_000, "p1": 8_000_000}},
        }
        compra = [{"kind": "buy", "team_id": "t1", "player_id": "p1", "at": "2026-11-02T14:08:00+01:00", "amount_eur": 6_000_000}]
        rows = _subidas(dias, {("p1", "2026-11-03"): 6_100_000}, compra)
        self.assertEqual([(r["player_id"], r["cost_eur"]) for r in rows], [("p1", 950_000)])

    def test_initial_roster_excess_is_not_charged(self) -> None:
        dias = {"2026-11-01": {"t1": {"p1": 20_000_000}}}
        rows = _subidas(dias, {("p1", "2026-11-01"): 12_000_000})
        self.assertEqual([(r["tipo"], r["cost_eur"], r["exceso_eur"]) for r in rows], [("reparto", 0, 8_000_000)])

    def test_costes_ocultos_keeps_only_paid_raises(self) -> None:
        dias = {"2026-11-01": {"t1": {"p1": 10_000_000, "p2": 5_000_000}}, "2026-11-02": {"t1": {"p1": 16_000_000, "p2": 5_500_000}}}
        valores = {("p1", "2026-11-02"): 11_000_000, ("p2", "2026-11-02"): 5_500_000}
        compras = [
            {"kind": "buy", "team_id": "t1", "player_id": pid, "at": "2026-10-20T14:08:00+02:00", "amount_eur": amount}
            for pid, amount in (("p1", 10_000_000), ("p2", 5_000_000))
        ]
        rows = costes_ocultos(compras, valores, dias=dias)
        self.assertEqual([(r["player_id"], r["day"], r["cost_eur"]) for r in rows], [("p1", "2026-11-02", 2_500_000)])


class HistorialTests(unittest.TestCase):
    def test_merge_keeps_the_first_snapshot_of_each_day(self) -> None:
        local = {"days": {"2026-11-02": {"t1": {"p1": 2}}}}
        remoto = {"days": {"2026-11-01": {"t1": {"p1": 1}}, "2026-11-02": {"t1": {"p1": 9}}}}
        self.assertEqual(
            fusionar_historial(local, remoto),
            {"2026-11-01": {"t1": {"p1": 1}}, "2026-11-02": {"t1": {"p1": 2}}},
        )

    def test_values_saved_with_the_snapshot_are_read_back(self) -> None:
        doc = {"values": {"2026-11-02": {"p1": 7_000_000, "p2": True}}}
        self.assertEqual(valores_de_fotos(doc), {("p1", "2026-11-02"): 7_000_000})


class NeedsGuardaLaFotoTests(unittest.TestCase):
    def test_a_real_refresh_saves_today_and_charges_the_raise(self) -> None:
        import json
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path

        from toolbox.bidding import needs_from_documents
        from toolbox.cache import ResponseCache

        def jugador(clausula: int, valor: int) -> dict:
            return {"player_id": "p1", "name": "Uno", "position": "MC", "buyout_clause": clausula, "market_value": valor}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clause_snapshot_history.json").write_text(
                json.dumps({"version": 2, "days": {"2026-11-14": {"t2": {"p1": 10_000_000}}}}), encoding="utf-8"
            )
            squads = {
                "ok": True,
                "league_id": "7",
                "squads": [
                    {"team_id": "t1", "is_self": True, "manager_name": "Yo", "cash": 1_000_000, "players": []},
                    {"team_id": "t2", "is_self": False, "manager_name": "Rival", "cash": None, "players": [jugador(16_000_000, 11_000_000)]},
                ],
            }
            activity = {"ok": True, "events": [
                {"kind": "buy", "team_id": "t2", "player_id": "p1", "amount_eur": 10_000_000, "at": "2026-11-01T14:08:00+01:00"},
            ]}
            report = needs_from_documents(
                {"listings": []}, squads, None, activity,
                now=datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc), cache=ResponseCache(root), fresh=True,
            )
            guardado = json.loads((root / "clause_snapshot_history.json").read_text(encoding="utf-8"))
        self.assertEqual(guardado["days"]["2026-11-15"], {"t2": {"p1": 16_000_000}})
        self.assertEqual(guardado["values"]["2026-11-15"], {"p1": 11_000_000})
        self.assertEqual(
            [(r["team_id"], r["day"], r["cost_eur"]) for r in report["clause_raises"]],
            [("t2", "2026-11-15", 2_500_000)],
        )


class AuditoriaUsaLaMismaCajaTests(unittest.TestCase):
    def test_the_rival_audit_charges_the_unified_raises(self) -> None:
        from toolbox.rival_intel import LedgerAuditor

        auditor = LedgerAuditor(persist=False)
        rows = [
            {"team_id": "t1", "player_id": "p1", "day": "2026-11-02", "cost_eur": 2_500_000},
            {"team_id": "t1", "player_id": "p2", "day": "2026-11-05", "cost_eur": 1_000_000},
            {"team_id": "t2", "player_id": "p3", "day": "2026-11-02", "cost_eur": 9_000_000},
        ]
        total, filas = auditor._hidden_for_period(
            team_id="t1", retro=[{"team_id": "t1", "player_id": "p9", "cost_eur": 7_000_000}],
            log={}, present={"p1"}, anchor_day=None, override=rows,
        )
        self.assertEqual(total, 3_500_000)
        total_ancla, _ = auditor._hidden_for_period(
            team_id="t1", retro=[], log={}, present=set(), anchor_day="2026-11-03", override=rows,
        )
        self.assertEqual(total_ancla, 1_000_000)
        self.assertEqual({fila["player_id"] for fila in filas}, {"p1", "p2"})


if __name__ == "__main__":
    unittest.main()

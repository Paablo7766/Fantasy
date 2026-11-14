"""Auditoría 14-nov, fallo 4: con once incompleto Mercado vetaba todas las compras.

«xi_invalido» solo debe frenar la compra que no acerca a un once legal; la que
tapa un hueco es justo la que arregla la jornada. Y con 10 jugadores no hay
«10 fuera del once»: el once es el de los huecos a 0.
"""

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.bidding import assess_purchase, compra_cubre_hueco, huecos_para_once
from toolbox.engine.liquidacion import plan_liquidacion
from toolbox.market_intel import _elegibles_por_puesto, build_market_decisions

# 1 POR, 4 DEF, 3 MC, 2 DEL: falta uno de campo (4-4-2, 4-3-3 o 5-3-2).
DIEZ = {"POR": 1, "DEF": 4, "MC": 3, "DEL": 2}


class CompraQueCompletaElOnce(unittest.TestCase):
    def test_huecos(self):
        self.assertEqual(huecos_para_once(DIEZ), 1)
        self.assertEqual(huecos_para_once({**DIEZ, "DEL": 3}), 0)

    def test_cualquier_jugador_de_campo_tapa_el_hueco_y_un_portero_no(self):
        for pos in ("DEF", "MC", "DEL"):
            self.assertTrue(compra_cubre_hueco(DIEZ, pos), pos)
        self.assertFalse(compra_cubre_hueco(DIEZ, "POR"))

    def test_compra_que_completa_no_se_veta(self):
        r = assess_purchase(cash=10_000_000, cost=4_000_000, lineup_void=True, fills_gap=True)
        self.assertTrue(r["eligible"])
        self.assertNotIn("xi_invalido", r["reasons"])

    def test_compra_que_no_completa_sigue_vetada(self):
        r = assess_purchase(cash=10_000_000, cost=4_000_000, lineup_void=True, fills_gap=False)
        self.assertFalse(r["eligible"])
        self.assertIn("xi_invalido", r["reasons"])

    def test_elegibles_por_puesto_solo_si_el_nulo_es_por_huecos(self):
        xi = [{"position": "POR"}] + [{"position": "DEF"}] * 4 + [{"position": "MC"}] * 3 + [{"position": "DEL"}] * 2
        doc = {"matchday_void": True, "void_reasons": ["empty_slot"], "xi": xi, "benched": []}
        self.assertEqual(_elegibles_por_puesto(doc), DIEZ)
        self.assertIsNone(_elegibles_por_puesto({**doc, "void_reasons": ["empty_slot", "negative_cash"]}))
        self.assertIsNone(_elegibles_por_puesto({**doc, "matchday_void": False}))


class MercadoConOnceNulo(unittest.TestCase):
    def test_solo_el_portero_sobrante_queda_vetado_por_once(self):
        now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        expira = (now + timedelta(days=1)).isoformat()
        xi = [{"position": pos} for pos, n in DIEZ.items() for _ in range(n)]
        optimize = {"ok": True, "matchday_void": True, "void_reasons": ["empty_slot"], "xi": xi, "benched": [], "gaps": [], "market_fills": []}
        flip = {"ok": True, "cash_eur": 20_000_000, "matchday_void": True, "team_id": "yo", "signings": [], "rejected": []}
        listings = [
            {"player_id": pid, "name": pid, "position": pos, "sale_price": 1_000_000, "seller_team_id": None, "listing_expires_at": expira}
            for pid, pos in (("del", "DEL"), ("por", "POR"))
        ]
        trends = {"ok": True, "players": [{"player_id": pid, "name": pid, "position": pos, "matching_confidence": 0.95}
                                          for pid, pos in (("del", "DEL"), ("por", "POR"))]}
        doc = build_market_decisions({"ok": True, "listings": listings}, trends, flip, optimize, now=now)
        rows = {r["player_id"]: r for r in doc["decisions"]}
        self.assertNotIn("xi_invalido", rows["del"]["reasons"])
        self.assertIn("xi_invalido", rows["por"]["reasons"])


class SobrantesConDiez(unittest.TestCase):
    def test_con_diez_jugadores_ninguno_sobra(self):
        owned = []
        for pos, n in DIEZ.items():
            owned += [
                {"player_id": f"{pos}{i}", "nombre": f"{pos}{i}", "position": pos, "jornada": 4.0, "valor": 1_000_000}
                for i in range(n)
            ]
        out = plan_liquidacion(owned, saldo=1_000_000, dias_para_jornada=4.0)
        self.assertTrue(out["activo"])
        self.assertEqual(out["sobrantes"], [])
        self.assertEqual(len(out["once_ids"]), 10)


if __name__ == "__main__":
    unittest.main()

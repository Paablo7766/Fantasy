"""Escudo (te roban la cláusula) y francotirador (rojo seguro con cláusula baja)."""

from __future__ import annotations

import unittest

from toolbox.engine.trading_desk import alertas_escudo_francotirador
from toolbox.market_intel import alertas_escudo_francotirador as alertas_desde_mercado
from toolbox.rival_intel import bid_limit_por_puesto


class EscudoFrancotiradorTest(unittest.TestCase):
    def test_escudo_cuando_el_rival_cojea_y_tiene_credito(self) -> None:
        alertas = alertas_escudo_francotirador(
            [{"player_id": "n", "nombre": "Nico", "position": "DEL", "clausula": 10_000_000, "valor": 10_000_000, "en_xi": True}],
            [{"manager": "Sausor10", "poder": 9_000_000, "huecos": [], "flojas": ["DEL"], "saldo": 1_000_000, "debt_limit_eur": 12_000_000}],
        )
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["tono"], "rojo")
        self.assertEqual(
            alertas[0]["mensaje"],
            "Sausor10 necesita un DEL y la cláusula de Nico está a su alcance",
        )

    def test_escudo_no_salta_si_la_clausula_esta_alta_o_el_rival_no_llega(self) -> None:
        titular = {"player_id": "n", "nombre": "Nico", "position": "DEL", "clausula": 13_000_000, "valor": 10_000_000, "en_xi": True}
        rival = {"manager": "Sausor10", "poder": 20_000_000, "flojas": ["DEL"]}
        self.assertEqual(alertas_escudo_francotirador([titular], [rival]), [])
        barato = {**titular, "clausula": 10_000_000}
        sin_caja = {**rival, "poder": 4_000_000, "saldo": 4_000_000}
        self.assertEqual(alertas_escudo_francotirador([barato], [sin_caja]), [])
        otro_puesto = {**rival, "flojas": ["POR"], "huecos": []}
        self.assertEqual(alertas_escudo_francotirador([barato], [otro_puesto]), [])

    def test_francotirador_solo_en_rojo_seguro_con_clausula_baja_y_subida(self) -> None:
        jugadores = [
            {
                "player_id": "g1",
                "nombre": "Gol",
                "manager": "gerardo_vp",
                "team_id": "g",
                "position": "DEL",
                "clausula": 5_000_000,
                "valor": 5_000_000,
                "prevision_7d_pct": 4.2,
            },
            {
                "player_id": "caro",
                "nombre": "Caro",
                "manager": "gerardo_vp",
                "team_id": "g",
                "clausula": 8_000_000,
                "valor": 5_000_000,
                "prevision_7d_pct": 6,
            },
            {
                "player_id": "baja",
                "nombre": "Baja",
                "manager": "Naviis10",
                "team_id": "n",
                "clausula": 4_000_000,
                "valor": 4_000_000,
                "prevision_7d_pct": -1,
            },
        ]
        rivales = [
            {"team_id": "g", "manager": "gerardo_vp", "en_rojo_seguro": True, "saldo": -1},
            {"team_id": "n", "manager": "Naviis10", "en_rojo": "seguro", "saldo": -2},
            {"team_id": "s", "manager": "Sano", "en_rojo": None, "saldo": 5_000_000},
        ]
        alertas = alertas_desde_mercado([], rivales, jugadores)
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["tono"], "verde")
        self.assertIn("Gol", alertas[0]["mensaje"])
        self.assertIn("gerardo_vp", alertas[0]["mensaje"])
        self.assertTrue(alertas[0]["mensaje"].endswith("Clausúlalo antes del viernes para revenderlo"))

    def test_el_rojo_solo_recupera_el_tope_en_el_puesto_vacio(self) -> None:
        limites = bid_limit_por_puesto(
            {
                "players": [
                    {"position": "POR", "player_status": "injured"},
                    {"position": "DEF", "player_status": "ok"},
                    {"position": "DEF", "player_status": "ok"},
                ]
            },
            en_rojo=True,
            legal=5_000_000,
        )
        self.assertEqual(limites["POR"], 5_000_000)
        self.assertEqual(limites["DEF"], 0)
        self.assertEqual(limites["MC"], 5_000_000)
        self.assertEqual(limites["DEL"], 5_000_000)


if __name__ == "__main__":
    unittest.main()

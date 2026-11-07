"""Parón de selecciones: la previsión de precio no se extrapola más allá de 7 días."""

from __future__ import annotations

import unittest

from toolbox.engine.paron import contexto_paron, dias_de_prevision, es_paron
from toolbox.engine.sales_audit import evaluar_ventas_y_ofertas
from toolbox.engine.trading_desk import build_trading_desk, ganancia_esperada

VALOR = 10_000_000


class ParonTest(unittest.TestCase):
    def test_detecta_paron_solo_si_pasa_de_un_ciclo(self) -> None:
        self.assertFalse(es_paron(4.0))
        self.assertFalse(es_paron(7.5))
        self.assertTrue(es_paron(12.5))
        self.assertFalse(es_paron(None))
        self.assertFalse(es_paron(True))

    def test_dias_de_prevision_topa_en_siete(self) -> None:
        self.assertEqual(dias_de_prevision(12.5), 7.0)
        self.assertEqual(dias_de_prevision(4.0), 3.0)
        self.assertEqual(dias_de_prevision(0.5), 0.0)
        self.assertIsNone(dias_de_prevision(None))

    def test_contexto_avisa_solo_en_paron(self) -> None:
        self.assertIsNotNone(contexto_paron(12.0)["nota"])
        self.assertIsNone(contexto_paron(3.0)["nota"])

    def test_auditor_no_extrapola_a_doce_dias(self) -> None:
        jugador = {
            "player_id": "DEL-0",
            "nombre": "Delantero",
            "position": "DEL",
            "valor": VALOR,
            "valor_justo": VALOR,
            "jornada": 5.0,
            "pct": 7.0,
            "elegible": True,
            "en_mercado": True,
            "ofertas": [{"comprador": "LaLiga", "importe": VALOR}],
        }
        resultado = evaluar_ventas_y_ofertas([jugador], plan=None, saldo=0, dias_al_cierre=12.5)
        fila = resultado["filas"][0]
        # 7 % a 7 días, 7 días de previsión usados: +7 %, no +7 % * 11,5 / 7.
        self.assertEqual(fila["ganancia_esperar_jueves"]["pct"], 7.0)
        self.assertTrue(resultado["paron"]["paron"])

    def test_trading_en_paron_usa_siete_dias_no_cuatro(self) -> None:
        cand = {"player_id": "a", "nombre": "A", "origen": "bid", "euros": VALOR, "valor": VALOR, "pct": 7.0}
        ciclo = build_trading_desk([cand], saldo_sobrante=20_000_000, valor_equipo=0, dias_para_jornada=4)
        paron = build_trading_desk([cand], saldo_sobrante=20_000_000, valor_equipo=0, dias_para_jornada=12.5)
        self.assertEqual(ciclo["ganancia_esperada"], ganancia_esperada(VALOR, VALOR, 7.0, 4.0))
        self.assertEqual(paron["ganancia_esperada"], ganancia_esperada(VALOR, VALOR, 7.0, 7.0))


if __name__ == "__main__":
    unittest.main()

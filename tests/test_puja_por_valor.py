"""Auditoría 14-nov, fallo 1: la puja de un objetivo del plan sale de P(ganar) × valor para el once.

El techo fijo del +10 % dejaba a Carreras (mejora +2,4 xP) en 4,39 M€ con un
~47 % de ganar según la curva de la liga, cuando pagar +30 % sigue saliendo a cuenta.
"""

import unittest

from toolbox.engine.auction_intel import (
    CURVA_PRIMAS_PRIOR,
    MIN_MUESTRA_CURVA,
    curva_primas,
    prob_ganar_prima,
    puja_por_valor,
)
from toolbox.engine.strategy_layer import _sellar_pujas_plan
from toolbox.top4_levers import _prob_ganar

VALOR = 3_989_044
RATIO = 3_796_601


class Curva(unittest.TestCase):
    def test_interpola_y_es_monotona(self):
        self.assertAlmostEqual(prob_ganar_prima(0.10), 0.47)
        self.assertAlmostEqual(prob_ganar_prima(0.125), 0.535)
        ps = [prob_ganar_prima(x / 100) for x in range(0, 121)]
        self.assertEqual(ps, sorted(ps))

    def test_curva_empirica_necesita_muestra(self):
        self.assertIsNone(curva_primas([0.1] * (MIN_MUESTRA_CURVA - 1)))
        curva = curva_primas([0.0] * 15 + [0.2] * 15)
        self.assertEqual(len(curva), len(CURVA_PRIMAS_PRIOR))
        self.assertEqual(dict(curva)[0.10], 0.5)
        self.assertEqual(dict(curva)[0.20], 1.0)


class PujaPorValor(unittest.TestCase):
    def test_carreras_sube_por_encima_del_diez(self):
        r = puja_por_valor(VALOR, 2.42 * RATIO, tope_eur=40_000_000, clave="2533")
        self.assertGreater(r["prima"], 0.10)
        self.assertGreater(r["puja"], VALOR * 1.10)
        self.assertGreater(r["p_ganar"], 0.47)
        # Mejor que quedarse en el +10 %.
        en_techo = 0.47 * (2.42 * RATIO - 0.10 * VALOR)
        self.assertGreater(r["valor_esperado_eur"], en_techo)

    def test_sin_mejora_no_hay_cifra(self):
        self.assertIsNone(puja_por_valor(VALOR, 0.0))

    def test_poca_mejora_no_paga_prima(self):
        r = puja_por_valor(VALOR, 300_000, tope_eur=40_000_000)
        self.assertLessEqual(r["prima"], 0.05)

    def test_respeta_el_tope_del_plan(self):
        tope = int(VALOR * 1.05)
        r = puja_por_valor(VALOR, 2.42 * RATIO, tope_eur=tope)
        self.assertLessEqual(r["puja"], tope)


class SelladoDelPlan(unittest.TestCase):
    def _plan(self, holgura):
        plan = {
            "ratio_mercado": RATIO,
            "presupuesto": {"holgura": holgura},
            "acciones": [
                {"tipo": "PUJA", "player_id": "2533", "nombre": "Carreras", "euros": 4_188_685,
                 "mejora_neta": 2.42, "momento": "hoy"},
            ],
        }
        pujas = {"2533": {"valor_mercado": VALOR, "puja_maxima": 4_450_000, "puja_recomendada": 4_188_685,
                          "techo_sobrepuja": int(VALOR * 1.10)}}
        _sellar_pujas_plan(plan, pujas, None)
        return plan

    def test_con_holgura_la_puja_final_pasa_del_techo_fijo(self):
        plan = self._plan(30_000_000)
        accion = plan["acciones"][0]
        self.assertGreater(accion["puja_final"], VALOR * 1.10)
        self.assertEqual(accion["puja_final"], accion["puja_por_valor"])
        self.assertEqual(plan["cifras"]["inversion_eur"], accion["puja_final"] - 4_188_685)

    def test_sin_holgura_no_pasa_de_lo_que_el_plan_puede_poner(self):
        accion = self._plan(0)["acciones"][0]
        self.assertLessEqual(accion["puja_final"], 4_188_685)

    def test_el_top4_usa_la_probabilidad_de_la_cifra_que_se_escribe(self):
        plan = self._plan(30_000_000)
        doc = {"decisions": [{"player_id": "2533", "win_probability": 0.098}], "plan_fichajes": plan}
        self.assertEqual(_prob_ganar(doc)["2533"], plan["acciones"][0]["p_ganar_por_valor"])


if __name__ == "__main__":
    unittest.main()

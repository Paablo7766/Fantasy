"""Auditoría 14-nov, fallo 5: pujas, cláusulas y recambios comparten una sola caja.

El asesor de cláusulas partía de la caja inicial aunque el plan ya la hubiera
comprometido en pujas, y pedía un recambio por puesto que el plan ya fichaba.
"""

import unittest

from toolbox.engine.strategy_layer import _caja_para_clausulas, _caja_unica


def _plan(saldo_final, pujas=()):
    return {
        "cifras": {"saldo_final_eur": saldo_final},
        "acciones": [
            {"tipo": "PUJA", "momento": "hoy", "player_id": pid, "nombre": nombre, "posicion": pos,
             "puja_final": euros, "valor_esperado_puja_eur": ev}
            for pid, nombre, pos, euros, ev in pujas
        ],
    }


class CajaParaClausulas(unittest.TestCase):
    def test_descuenta_lo_que_el_plan_compromete(self):
        self.assertEqual(_caja_para_clausulas(46_000_000, _plan(26_000_000)), 26_000_000)

    def test_el_credito_de_las_pujas_no_paga_clausulas(self):
        # Pujas financiadas con crédito: no queda caja real para subir cláusulas.
        self.assertEqual(_caja_para_clausulas(10_000_000, _plan(-3_000_000)), 0)

    def test_sin_plan_es_la_caja(self):
        self.assertEqual(_caja_para_clausulas(10_000_000, None), 10_000_000)


class CompiteConElPlan(unittest.TestCase):
    def _clausulas(self, coste, exposicion):
        return {
            "resumen": {},
            "proteger": [
                {"player_id": "isco", "nombre": "Isco", "posicion": "MC", "veredicto_codigo": "SIN_CAJA",
                 "exposicion_eur": exposicion, "motivo_detallado": "Sin caja.",
                 "clausula_perfecta": {"coste_eur": coste, "viable": False}},
            ],
            "preparar": [],
        }

    def test_si_vale_mas_que_la_puja_mas_floja_se_dice_cual_soltar(self):
        clausulas = self._clausulas(11_000_000, 30_000_000)
        plan = _plan(5_000_000, [("a", "Revivo", "DEF", 10_800_000, 3_700_000), ("b", "Carreras", "DEF", 5_200_000, 6_000_000)])
        _caja_unica(clausulas, plan, saldo_inicial=46_000_000, caja_clausulas=5_000_000)
        fila = clausulas["proteger"][0]
        self.assertEqual(fila["compite_con_plan"]["soltar"], "Revivo")
        self.assertIn("Revivo", fila["motivo_detallado"])
        self.assertEqual(clausulas["resumen"]["caja_para_clausulas_eur"], 5_000_000)
        self.assertEqual(clausulas["resumen"]["comprometido_en_pujas_eur"], 41_000_000)

    def test_si_vale_menos_que_las_pujas_no_se_suelta_nada(self):
        clausulas = self._clausulas(11_000_000, 2_000_000)
        plan = _plan(5_000_000, [("a", "Revivo", "DEF", 10_800_000, 3_700_000)])
        _caja_unica(clausulas, plan, saldo_inicial=46_000_000, caja_clausulas=5_000_000)
        self.assertIsNone(clausulas["proteger"][0]["compite_con_plan"]["soltar"])

    def test_las_subidas_recomendadas_se_descuentan_entre_si(self):
        clausulas = {
            "resumen": {},
            "proteger": [],
            "preparar": [
                {"player_id": pid, "nombre": pid, "posicion": "MC", "veredicto_codigo": "PROTEGER_YA",
                 "exposicion_eur": 1_000_000, "motivo_detallado": "",
                 "subida_recomendada": {"coste_eur": 4_000_000, "viable": True}}
                for pid in ("uno", "dos")
            ],
        }
        _caja_unica(clausulas, _plan(5_000_000), saldo_inicial=20_000_000, caja_clausulas=5_000_000)
        self.assertNotIn("compite_con_plan", clausulas["preparar"][0])
        self.assertEqual(clausulas["preparar"][1]["compite_con_plan"]["falta_eur"], 3_000_000)


class RecambioDelPlan(unittest.TestCase):
    def test_el_recambio_es_la_puja_del_plan_en_ese_puesto(self):
        clausulas = {
            "resumen": {"alertas_prioritarias": [
                {"player_id": "radu", "nombre": "Radu", "posicion": "POR", "accion": "Es tu único POR. Ficha antes del 15-nov un POR de recambio (Eder Aller, 0,7M).",
                 "recambio_sugerido": {"nombre": "Eder Aller", "posicion": "POR"}},
            ]},
            "proteger": [{"player_id": "radu", "nombre": "Radu", "posicion": "POR", "veredicto_codigo": "SIN_RECAMBIO",
                          "recambio_sugerido": {"nombre": "Eder Aller", "posicion": "POR"}}],
            "preparar": [],
        }
        plan = _plan(5_000_000, [("f", "Fortuño", "POR", 4_360_000, 7_000_000)])
        _caja_unica(clausulas, plan, saldo_inicial=46_000_000, caja_clausulas=5_000_000)
        alerta = clausulas["resumen"]["alertas_prioritarias"][0]
        self.assertEqual(alerta["recambio_en_plan"], "Fortuño")
        self.assertIn("Fortuño", alerta["accion"])
        self.assertNotIn("Ficha antes", alerta["accion"])
        self.assertIn("Si la pierdes, ficha a Eder Aller", alerta["accion"])
        self.assertEqual(clausulas["proteger"][0]["recambio_en_plan"], "Fortuño")


if __name__ == "__main__":
    unittest.main()

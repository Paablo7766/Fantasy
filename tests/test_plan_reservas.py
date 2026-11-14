"""Auditoría 14-nov, fallo 2 (punto 2): una puja de reserva por cada puja dudosa.

Solo si sale a cuenta: vale la mejora de la reserva cuando se pierde la
principal, menos revender una si se ganan las dos; tiene que caber en la caja
que deja el plan (las pujas vivas reservan saldo).
"""

import unittest

from toolbox.engine.strategy_layer import _anadir_reservas
from toolbox.top4 import Top4Model
from toolbox.top4_levers import escenarios_pujas


def _plan(p_principal, saldo=10_000_000, valor_reserva=2_000_000):
    return {
        "ratio_mercado": 3_800_000,
        "calibracion_xp": {"factor": 1.0},
        "cifras": {"inversion_eur": 4_000_000, "saldo_final_eur": saldo},
        "acciones": [
            {"tipo": "PUJA", "momento": "hoy", "player_id": "main", "nombre": "Principal", "posicion": "DEF",
             "puja_final": 4_000_000, "p_ganar_por_valor": p_principal, "mejora_neta": 3.0},
        ],
        "candidatos_puja": [
            {"player_id": "res", "nombre": "Reserva", "posicion": "DEF", "euros": valor_reserva, "mejora_neta": 2.5},
            {"player_id": "otro", "nombre": "Otro", "posicion": "MC", "euros": 1_000_000, "mejora_neta": 4.0},
        ],
    }


PUJAS = {"res": {"valor_mercado": 2_000_000}, "otro": {"valor_mercado": 1_000_000}}


class Reservas(unittest.TestCase):
    def test_puja_dudosa_lleva_reserva_de_su_puesto(self):
        plan = _plan(0.4)
        _anadir_reservas(plan, PUJAS, None)
        reserva = next(a for a in plan["acciones"] if a.get("reserva_de"))
        self.assertEqual(reserva["player_id"], "res")
        self.assertEqual(reserva["reserva_de_nombre"], "Principal")
        self.assertEqual(plan["cifras"]["saldo_final_eur"], 10_000_000 - reserva["puja_final"])
        self.assertEqual(plan["cifras"]["inversion_eur"], 4_000_000 + reserva["puja_final"])
        self.assertGreaterEqual(reserva["puja_final"], 2_000_000)

    def test_puja_probable_no_lleva_reserva(self):
        plan = _plan(0.8)
        _anadir_reservas(plan, PUJAS, None)
        self.assertFalse(any(a.get("reserva_de") for a in plan["acciones"]))

    def test_sin_caja_para_la_reserva_no_hay_reserva(self):
        plan = _plan(0.4, saldo=1_500_000)
        _anadir_reservas(plan, PUJAS, None)
        self.assertFalse(any(a.get("reserva_de") for a in plan["acciones"]))
        self.assertEqual(plan["cifras"]["saldo_final_eur"], 1_500_000)


class EscenariosConReserva(unittest.TestCase):
    def test_la_reserva_devuelve_la_mejora_si_se_pierde_la_principal(self):
        model = Top4Model([50.0] * 9, 8.0)
        principal = {"id": "main", "nombre": "P", "mejora": 4.0, "prob": 0.4}
        reserva = {"id": "res", "reserva_de": "main", "nombre": "R", "mejora": 3.0, "prob": 0.6}
        sin = escenarios_pujas(model, [principal], 54.0, 4.0, 12)
        con = escenarios_pujas(model, [principal, reserva], 54.0, 4.0, 12)
        self.assertGreater(con["p_esperado"], sin["p_esperado"])
        # Ganar todas y no ganar ninguna se cuentan solo con las principales.
        self.assertEqual(con["prob_ganar_todas"], 0.4)
        self.assertEqual(con["prob_ganar_ninguna"], 0.6)


if __name__ == "__main__":
    unittest.main()

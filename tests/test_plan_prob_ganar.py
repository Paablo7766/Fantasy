"""Auditoría 14-nov, fallo 2 (punto 1): el plan cuenta cada puja por lo que espera sacar.

Antes elegía como si fuera a ganar todas (Antony, 40,9 M€, con un 36-46 % de ganar).
"""

import unittest

from toolbox.engine.signing_plan import build_plan_fichajes, peso_esperado


def fila(pid, pos, jornada=4.0, **extra):
    row = {"player_id": pid, "nombre": pid, "position": pos, "jornada": jornada, "elegible": True,
           "valor": 3_000_000, "venta_eur": 2_850_000}
    row.update(extra)
    return row


ONCE = [fila("POR0", "POR"), *[fila(f"DEF{i}", "DEF") for i in range(4)],
        *[fila(f"MC{i}", "MC") for i in range(4)], *[fila(f"DEL{i}", "DEL") for i in range(2)]]
MERCADO = [fila("dificil", "DEL", 10.0, euros=6_000_000), fila("seguro", "DEL", 8.0, euros=6_000_000)]
PROB = {"dificil": 0.15, "seguro": 0.9}


def _plan(prob_ganar=None):
    return build_plan_fichajes(
        cash=7_000_000, owned=ONCE, mercado=MERCADO, clausulas=[], ratio=3_000_000,
        dias_para_jornada=3.0, baseline_puntos=44.0, prob_ganar=prob_ganar,
    )


def _pujas(plan):
    return [a["player_id"] for a in plan["acciones"] if a.get("tipo") == "PUJA" and a.get("momento") == "hoy"]


class PesoEsperado(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(peso_esperado(None, 6.0, 10.0), 1.0)
        self.assertAlmostEqual(peso_esperado(0.5, 6.0, 10.0), 0.7)
        self.assertEqual(peso_esperado(1.0, 6.0, 10.0), 1.0)


class PlanConProbabilidad(unittest.TestCase):
    def test_sin_probabilidad_elige_el_de_mas_xp(self):
        self.assertEqual(_pujas(_plan()), ["dificil"])

    def test_con_probabilidad_elige_el_que_se_espera_ganar(self):
        plan = _plan(lambda row, mejora: PROB[row["player_id"]])
        self.assertEqual(_pujas(plan), ["seguro"])
        accion = next(a for a in plan["acciones"] if a.get("player_id") == "seguro")
        self.assertEqual(accion["p_ganar_estimada"], 0.9)

    def test_un_fallo_de_la_probabilidad_no_rompe_el_plan(self):
        def roto(row, mejora):
            raise RuntimeError("sin curva")

        self.assertEqual(_pujas(_plan(roto)), ["dificil"])


if __name__ == "__main__":
    unittest.main()

"""Auditoría 14-nov, fallo 2 (punto 4): Mercado habla como el plan.

* «DESCARTAR / SOBREPRECIO» salía de una nota que no mira el precio: ahora es «DESCARTAR».
* Un objetivo del plan lleva el veredicto del plan, no «Imprescindible» en un sitio
  y «Descartar» en otro.
* Cada puja dice qué pasa si se pierde.
"""

import unittest

from toolbox.engine.market_grade import calcular_nota_mercado
from toolbox.engine.strategy_layer import _si_pierdes, _unificar_fila_mercado, plan_compras


def _plan(con_reserva: bool):
    acciones = [
        {"tipo": "PUJA", "momento": "hoy", "player_id": "car", "nombre": "Carreras", "posicion": "DEF",
         "euros": 4_000_000, "puja_final": 6_000_000, "mejora_neta": 2.4, "p_ganar_por_valor": 0.54,
         "detalle": "Mejora el once."},
    ]
    if con_reserva:
        acciones.append({"tipo": "PUJA", "momento": "hoy", "player_id": "res", "nombre": "Reserva", "posicion": "DEF",
                         "euros": 2_000_000, "puja_final": 2_100_000, "mejora_neta": 1.5, "reserva_de": "car",
                         "reserva_de_nombre": "Carreras", "detalle": "Reserva."})
    return {"acciones": acciones}


class SiPierdes(unittest.TestCase):
    def test_sin_reserva_sigue_tu_once(self):
        plan = _plan(False)
        _si_pierdes(plan)
        texto = plan["acciones"][0]["si_pierdes"]
        self.assertIn("juega quien ya tienes", texto)
        self.assertIn("+2.4 xP", texto)
        self.assertIn(texto, plan["acciones"][0]["detalle"])

    def test_con_reserva_entra_la_reserva(self):
        plan = _plan(True)
        _si_pierdes(plan)
        self.assertEqual(plan["acciones"][0]["si_pierdes"], "Si la pierdes, entra Reserva, la puja de reserva.")
        self.assertNotIn("si_pierdes", plan["acciones"][1])


class VeredictoUnico(unittest.TestCase):
    def test_un_objetivo_del_plan_lleva_el_veredicto_del_plan(self):
        plan = _plan(False)
        _si_pierdes(plan)
        row = {"player_id": "car", "action": "NO", "is_vetoed": True, "reasons": ["xi_invalido"],
               "veredicto_mercado": "DESCARTAR", "etiqueta_mercado": "DESCARTAR"}
        _unificar_fila_mercado(row, {"compras_plan": plan_compras(plan), "pujas": {}})
        self.assertEqual(row["veredicto_mercado"], "OBJETIVO DEL PLAN")
        self.assertEqual(row["etiqueta_mercado"], "PLAN")
        self.assertEqual(row["action"], "PUJAR")
        self.assertIn("Si la pierdes", row["action_reason"])
        self.assertIn("Si la pierdes", row["si_pierdes"])

    def test_esperar_al_cierre_lo_dice_con_la_hora(self):
        plan = _plan(False)
        _si_pierdes(plan)
        row = {"player_id": "car", "action": "ESPERAR", "reasons": ["esperar_snipe"],
               "action_reason": "Hay señal, pero el precio o la caja todavía no acompañan.",
               "snipe": {"fire_local_time": "14:07"}}
        _unificar_fila_mercado(row, {"compras_plan": plan_compras(plan), "pujas": {}})
        self.assertIn("Puja a las 14:07", row["action_reason"])
        self.assertNotIn("no acompañan", row["action_reason"])

    def test_la_reserva_se_presenta_como_reserva(self):
        plan = _plan(True)
        _si_pierdes(plan)
        row = {"player_id": "res", "action": "ESPERAR", "reasons": []}
        _unificar_fila_mercado(row, {"compras_plan": plan_compras(plan), "pujas": {}})
        self.assertIn("Reserva de Carreras", row["action_reason"])

    def test_la_nota_baja_ya_no_dice_sobreprecio(self):
        nota = calcular_nota_mercado(
            {"position": "MC", "xp": 1.0, "prevision_7d_pct": -4, "p_titular": 0.2, "week_points": [0, 0, 1],
             "dificultad": "dificil", "precio": 1_000_000},
            [{"position": "MC", "xp": 6.0}] * 4,
            20_000_000,
        )
        self.assertEqual(nota["veredicto_mercado"], "DESCARTAR")


if __name__ == "__main__":
    unittest.main()

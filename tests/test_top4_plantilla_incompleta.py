"""Auditoría 14-nov, fallo 3: «Con el plan de hoy» con plantilla de 10.

Con menos de 11 el once actual vale 0 y ``mejora_puntos_jornada`` es el once
entero. Escalar las pujas perdidas con ella las multiplicaba por ~3.
"""

import unittest

from toolbox.engine.signing_plan import build_plan_fichajes
from toolbox.top4 import Top4Model, model_from_race
from toolbox.top4_levers import apply_overlay, escenarios_pujas


def fila(pid, pos, jornada=4.0, **extra):
    row = {"player_id": pid, "nombre": pid, "position": pos, "jornada": jornada, "elegible": True}
    row.update(extra)
    return row


DIEZ = [fila("POR-0", "POR"), *[fila(f"DEF-{i}", "DEF") for i in range(4)],
        *[fila(f"MC-{i}", "MC") for i in range(3)], *[fila(f"DEL-{i}", "DEL") for i in range(2)]]


class ReferenciaDelPlan(unittest.TestCase):
    def test_con_diez_la_referencia_es_el_once_con_hueco_a_cero(self):
        mercado = [fila("del-nuevo", "DEL", 6.0, euros=1_000_000)]
        plan = build_plan_fichajes(
            cash=5_000_000, owned=DIEZ, mercado=mercado, clausulas=[], ratio=2_000_000,
            dias_para_jornada=6.0, baseline_puntos=0.0,
        )
        self.assertEqual(plan["puntos_once_actual"], 0.0)
        # 10 jugadores x 4 xP con el hueco del DEL a 0.
        self.assertAlmostEqual(plan["puntos_once_referencia"], 40.0, places=2)
        puja = next(a for a in plan["acciones"] if a.get("player_id") == "del-nuevo")
        self.assertAlmostEqual(plan["puntos_once"] - plan["puntos_once_referencia"], puja["mejora_neta"], places=2)


class EscenariosConDiez(unittest.TestCase):
    ROSTER = [{"position": r["position"]} for r in DIEZ]

    def _doc(self):
        table = [
            {"team_id": str(i), "manager_name": f"m{i}", "is_self": i == 0, "player_count": 10 if i == 0 else 14,
             "projection": {"expected_points": 40 + 2 * i, "xi": []}}
            for i in range(10)
        ]
        race = {"table": table, "my_projection": {"expected_points": 40.0, "xi": [{"expected_points": 4.0}] * 10}}
        return {
            "league_race": race,
            "decisions": [
                {"player_id": "seguro", "win_probability": 0.9},
                {"player_id": "dificil", "win_probability": 0.15},
            ],
            "plan_fichajes": {
                # Caso de la foto: once actual 0, once del plan 60, mejoras que suman 20.
                "puntos_once": 60.0, "puntos_once_actual": 0.0, "mejora_puntos_jornada": 60.0,
                "puntos_once_referencia": 40.0,
                "acciones": [
                    {"tipo": "PUJA", "player_id": "seguro", "nombre": "Seguro", "posicion": "DEL", "mejora_neta": 8.0, "euros": 1},
                    {"tipo": "PUJA", "player_id": "dificil", "nombre": "Dificil", "posicion": "MC", "mejora_neta": 12.0, "euros": 1},
                ],
            },
        }

    def test_ganar_solo_la_segura_resta_la_mejora_perdida_una_vez(self):
        out = apply_overlay(self._doc(), {}, self.ROSTER)
        plan = out["plan"]
        model = model_from_race(self._doc()["league_race"], {})["model"]
        # Ganar solo «Seguro»: 60 − 12 = 48 xP, no 60 − 3 × 12 = 24.
        self.assertAlmostEqual(plan["solo_mas_probable"]["p_top4"], round(model.p(48.0), 4), places=3)
        self.assertGreater(plan["solo_mas_probable"]["p_top4"], 0.3)
        # El esperado no puede quedar por debajo de 0,9 × «solo la segura».
        self.assertGreater(plan["p_despues"], 0.9 * 0.85 * plan["solo_mas_probable"]["p_top4"])

    def test_sin_referencia_y_once_nulo_no_escala(self):
        doc = self._doc()
        del doc["plan_fichajes"]["puntos_once_referencia"]
        plan = apply_overlay(doc, {}, self.ROSTER)["plan"]
        model = model_from_race(doc["league_race"], {})["model"]
        self.assertAlmostEqual(plan["solo_mas_probable"]["p_top4"], round(model.p(48.0), 4), places=3)

    def test_escala_uno_cuando_las_mejoras_suman_la_mejora_total(self):
        model = Top4Model([40.0] * 9, 10.0)
        r = escenarios_pujas(model, [{"nombre": "a", "mejora": 5.0, "prob": 1.0}, {"nombre": "b", "mejora": 5.0, "prob": 0.0}], 60.0, 10.0, 10)
        self.assertAlmostEqual(r["p_esperado"], round(model.p(55.0), 4), places=4)


if __name__ == "__main__":
    unittest.main()

"""Regla dura: ninguna venta deja menos de 11 jugadores ni una línea sin titular."""

import unittest

from toolbox.analyzer import Candidate
from toolbox.engine.signing_plan import build_plan_fichajes
from toolbox.strategy_search import OwnedAsset, can_field, keep_legal_sales
from toolbox.top4_levers import apply_overlay, completa_once, escenarios_pujas
from toolbox.top4 import Top4Model


def cand(pid, pos, ev=5.0):
    return Candidate(
        key=pid, player_id=pid, name=pid, nickname=None, position=pos, club=None, p_titular=0.9,
        expected_points=ev, jornada_ev=ev, points_if_starts=ev, relevo_bonus=None, objective=ev,
        components={}, player_status=None, excluded_reason=None,
    )


def squad(layout):
    out = []
    for pos, n in layout:
        out += [OwnedAsset(cand(f"{pos}{i}", pos), 1_000_000) for i in range(n)]
    return out


def fila(pid, pos, jornada=5.0, **extra):
    row = {"player_id": pid, "nombre": pid, "position": pos, "jornada": jornada, "elegible": True}
    row.update(extra)
    return row


class VentasEstrategias(unittest.TestCase):
    def test_no_vende_al_unico_portero(self):
        owned = squad([("POR", 1), ("DEF", 4), ("MC", 4), ("DEL", 3)])
        radu = next(a for a in owned if a.candidate.position == "POR")
        self.assertEqual(keep_legal_sales(owned, [radu]), [])

    def test_con_dos_porteros_si_puede_vender_uno(self):
        owned = squad([("POR", 2), ("DEF", 4), ("MC", 4), ("DEL", 3)])
        por = next(a for a in owned if a.candidate.position == "POR")
        self.assertEqual(keep_legal_sales(owned, [por]), [por])

    def test_con_diez_jugadores_no_se_vende_a_nadie(self):
        owned = squad([("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 2)])
        self.assertFalse(can_field(owned))
        self.assertEqual(keep_legal_sales(owned, list(owned)), [])

    def test_ventas_acumuladas_no_rompen_el_once(self):
        owned = squad([("POR", 1), ("DEF", 5), ("MC", 4), ("DEL", 3), ("DEF", 0)])
        defs = [a for a in owned if a.candidate.position == "DEF"]
        kept = keep_legal_sales(owned, defs)
        remaining = [a for a in owned if a not in kept]
        self.assertTrue(can_field(remaining))


class VentasPlan(unittest.TestCase):
    def _plan(self, n_mc):
        owned = [fila("POR-0", "POR"), *[fila(f"DEF-{i}", "DEF") for i in range(4)],
                 *[fila(f"MC-{i}", "MC") for i in range(n_mc)],
                 *[fila(f"DEL-{i}", "DEL", 1.0, venta_eur=9_000_000, pct=-8.0) for i in range(3)]]
        mercado = [fila("estrella", "DEL", 12.0, euros=10_000_000)]
        plan = build_plan_fichajes(
            cash=2_000_000, owned=owned, mercado=mercado, clausulas=[], ratio=2_000_000,
            dias_para_jornada=1.5, baseline_puntos=40.0,
        )
        return len(owned), [a for a in plan["acciones"] if a.get("tipo") in {"VENDE", "VENDER HOY"}]

    def test_con_once_legal_el_plan_si_vende_para_financiar(self):
        # Control: sin esto el test de abajo no demostraría nada.
        n, ventas = self._plan(3)
        self.assertEqual(n, 11)
        self.assertTrue(ventas)

    def test_plan_con_diez_jugadores_no_vende(self):
        n, ventas = self._plan(2)
        self.assertEqual(n, 10)
        self.assertEqual(ventas, [])


class Primerpaso(unittest.TestCase):
    def _doc(self):
        table = [
            {"team_id": str(i), "manager_name": f"m{i}", "is_self": i == 0, "player_count": 10 if i == 0 else 14,
             "projection": {"expected_points": 40 + i, "xi": []}}
            for i in range(10)
        ]
        race = {"table": table, "my_projection": {"expected_points": 45.0, "xi": [{"expected_points": 3.0}] * 10}}
        return {
            "league_race": race,
            "decisions": [
                {"player_id": "caro", "win_probability": 0.30},
                {"player_id": "seguro", "win_probability": 0.90},
            ],
            "plan_fichajes": {
                "puntos_once": 58.0, "mejora_puntos_jornada": 8.0,
                "acciones": [
                    {"tipo": "PUJA", "player_id": "caro", "nombre": "Caro", "posicion": "DEL", "mejora_neta": 6.0, "euros": 1},
                    {"tipo": "PUJA", "player_id": "seguro", "nombre": "Seguro", "posicion": "DEL", "mejora_neta": 3.0, "euros": 1},
                ],
            },
        }

    ROSTER = [{"position": p} for p, n in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 2)) for _ in range(n)]

    def test_primer_paso_es_la_puja_mas_probable(self):
        doc = self._doc()
        out = apply_overlay(doc, {}, self.ROSTER)
        self.assertEqual(out["paso_1"]["nombre"], "Seguro")
        self.assertEqual(doc["plan_fichajes"]["acciones"][0]["player_id"], "seguro")
        self.assertTrue(doc["plan_fichajes"]["acciones"][0]["asegura_jugador_11"])

    def test_plan_ponderado_es_menor_que_dando_las_pujas_por_ganadas(self):
        out = apply_overlay(self._doc(), {}, self.ROSTER)
        plan = out["plan"]
        self.assertLess(plan["p_despues"], plan["p_si_ganas_todas"])
        self.assertEqual(plan["solo_mas_probable"]["nombre"], "Seguro")
        self.assertAlmostEqual(plan["prob_ganar_todas"], 0.27, places=2)
        caro = next(a for a in out["acciones"] if a["player_id"] == "caro")
        self.assertAlmostEqual(caro["delta_p_ponderado"], 0.3 * caro["delta_p_si_ganas"], places=3)

    def test_sin_ninguna_ganada_con_diez_jugadores_vale_cero(self):
        model = Top4Model([40.0] * 9, 10.0)
        r = escenarios_pujas(model, [{"nombre": "a", "mejora": 5.0, "prob": 0.0}], 60.0, 5.0, 10)
        self.assertEqual(r["p_esperado"], 0.0)

    def test_completa_once(self):
        self.assertTrue(completa_once(self.ROSTER, "DEL"))
        self.assertFalse(completa_once(self.ROSTER, "POR"))


if __name__ == "__main__":
    unittest.main()

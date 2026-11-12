import unittest

from toolbox.engine.signing_plan import COLCHON_SIN_PEAJE_EUR, escasez_de_caja
from toolbox.top4 import Top4Model
from toolbox.top4_levers import apply_overlay, plantilla_minima, postura


def squad(n_por=2, n_def=4, n_mc=4, n_del=3, p=0.8):
    out = []
    for pos, n in (("POR", n_por), ("DEF", n_def), ("MC", n_mc), ("DEL", n_del)):
        out += [{"position": pos, "p_titular": p} for _ in range(n)]
    return out


class Minima(unittest.TestCase):
    def test_full_squad_complies(self):
        self.assertTrue(plantilla_minima(squad())["cumple"])

    def test_ten_players_fails(self):
        r = plantilla_minima(squad(1, 3, 3, 3)[:10])
        self.assertFalse(r["cumple"])
        self.assertTrue(any("jugadores" in f for f in r["faltan"]))

    def test_two_reliable_strikers_needed(self):
        r = plantilla_minima(squad(n_del=1, p=0.8) + [{"position": "DEL", "p_titular": 0.3}] * 2)
        self.assertEqual(r["delanteros_titulares"], 1)
        self.assertFalse(r["cumple"])

    def test_planned_buys_count(self):
        base = squad(2, 4, 4, 1)
        r = plantilla_minima(base, [{"posicion": "DEL"}, {"posicion": "DEL"}])
        self.assertEqual(r["delanteros_titulares"], 3)


class Posture(unittest.TestCase):
    def test_three_modes(self):
        self.assertEqual(postura(60, 48, 10)["nombre"], "seguro")
        self.assertEqual(postura(40, 48, 10)["nombre"], "techo")
        self.assertEqual(postura(48.5, 48, 10)["nombre"], "neutro")


class Model(unittest.TestCase):
    def test_monotone_and_void(self):
        m = Top4Model([45, 44, 43, 42, 41, 40, 39, 38, 37], 10)
        self.assertLess(m.p(40), m.p(50))
        self.assertGreater(m.p(50) - m.p(40), 0.05)
        self.assertEqual(m.p(80, void=True), 0.0)


class Peaje(unittest.TestCase):
    def test_cash_surplus_switches_toll_off(self):
        self.assertEqual(escasez_de_caja(50_000_000, 20_000_000), 0.0)
        self.assertEqual(escasez_de_caja(8_000_000, 8_000_000), 1.0)
        mid = escasez_de_caja(8_000_000 + COLCHON_SIN_PEAJE_EUR / 2, 8_000_000)
        self.assertAlmostEqual(mid, 0.5)


class Overlay(unittest.TestCase):
    def test_short_squad_blocks_resale(self):
        table = [
            {"team_id": str(i), "manager_name": f"m{i}", "is_self": i == 0, "player_count": 10 if i == 0 else 14,
             "projection": {"expected_points": 40 + i, "xi": []}}
            for i in range(10)
        ]
        race = {"table": table, "my_projection": {"expected_points": 45.0, "xi": [{"expected_points": 3.0}] * 10}}
        doc = {
            "league_race": race,
            "plan_fichajes": {
                "acciones": [], "trading": {"operaciones": [{"x": 1}]}, "paron": {"especular": [{"y": 1}]},
            },
        }
        out = apply_overlay(doc, {}, squad(1, 3, 3, 3)[:10])
        self.assertFalse(out["plantilla_minima"]["cumple"])
        self.assertEqual(doc["plan_fichajes"]["trading"]["operaciones"], [])
        self.assertEqual(doc["plan_fichajes"]["paron"]["especular"], [])
        self.assertEqual(out["reventa_bloqueada"], 2)
        self.assertTrue(out["void"])
        self.assertEqual(out["p_real"], 0.0)


if __name__ == "__main__":
    unittest.main()

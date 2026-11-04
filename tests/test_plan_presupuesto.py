import unittest

from toolbox.engine.signing_plan import build_plan_fichajes


def _plantilla():
    filas = []
    pos = ["POR"] + ["DEF"] * 4 + ["MC"] * 4 + ["DEL"] * 2
    for i, p in enumerate(pos):
        filas.append({"player_id": f"o{i}", "nombre": f"O{i}", "position": p, "jornada": 3.0,
                      "elegible": True, "venta_eur": 9_500_000, "valor": 10_000_000})
    filas.append({"player_id": "s1", "nombre": "Suplente", "position": "DEF", "jornada": 1.0,
                  "elegible": True, "venta_eur": 9_500_000, "valor": 10_000_000, "tiene_oferta_laliga": True})
    return filas


class PresupuestoTest(unittest.TestCase):
    def _plan(self, **extra):
        return build_plan_fichajes(
            cash=5_000_000, owned=_plantilla(),
            mercado=[{"player_id": "m1", "nombre": "Crack", "position": "DEL", "jornada": 9.0, "euros": 12_000_000, "valor": 11_000_000}],
            clausulas=[], ratio=1_000_000.0, dias_para_jornada=None, baseline_puntos=33.0, **extra)

    def test_etiqueta_y_presupuesto(self):
        plan = self._plan()
        puja = next(a for a in plan["acciones"] if a["tipo"] == "PUJA")
        self.assertEqual(puja["etiqueta"], "PUJAR")
        pres = plan["presupuesto"]
        self.assertTrue(pres["cumple"])
        self.assertLessEqual(pres["gasto_pujas"], pres["disponible_pujas"])

    def test_prudente_no_usa_ventas_condicionales(self):
        plan = self._plan(permitir_condicionales=False)
        self.assertFalse(any(a["momento"] == "condicional" for a in plan["acciones"]))


if __name__ == "__main__":
    unittest.main()

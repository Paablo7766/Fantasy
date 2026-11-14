"""Lo que vale un fichaje se descuenta por lo que el xP exagera las diferencias.

Pendiente de los puntos reales sobre el xP previsto: backtest J8–J12 (0,93 ± 0,08)
combinado por varianza inversa con la medida en vivo. Nunca infla.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from toolbox.engine.auction_intel import PENDIENTE_XP_BACKTEST, factor_calibracion_xp
from toolbox.engine.strategy_layer import _sellar_pujas_plan
from toolbox.engine_calibration import pendiente_xp_en_vivo


class Factor(unittest.TestCase):
    def test_sin_vivo_es_el_backtest(self):
        self.assertEqual(factor_calibracion_xp(None)["factor"], PENDIENTE_XP_BACKTEST)

    def test_combina_por_varianza_inversa(self):
        f = factor_calibracion_xp({"pendiente": 0.64, "se": 0.19, "n": 113})["factor"]
        esperado = (0.93 / 0.08**2 + 0.64 / 0.19**2) / (1 / 0.08**2 + 1 / 0.19**2)
        self.assertAlmostEqual(f, round(esperado, 3))

    def test_nunca_infla(self):
        self.assertEqual(factor_calibracion_xp({"pendiente": 1.8, "se": 0.01, "n": 500})["factor"], 1.0)


class PendienteEnVivo(unittest.TestCase):
    def test_lee_las_predicciones_evaluadas(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "r.sqlite"
            conn = sqlite3.connect(ruta)
            conn.execute("create table matchday_snapshots (expected_points real, actual_points real)")
            # Reales = 0,5 × xP + 1, más jugadores por debajo de 2 xP que no cuentan.
            filas = [(x / 4, 0.5 * x / 4 + 1) for x in range(8, 48)] + [(1.0, 9.0)] * 10
            conn.executemany("insert into matchday_snapshots values (?, ?)", filas)
            conn.commit()
            conn.close()
            r = pendiente_xp_en_vivo(ruta)
        self.assertEqual(r["n"], 40)
        self.assertAlmostEqual(r["pendiente"], 0.5, places=3)

    def test_poca_muestra_es_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "r.sqlite"
            conn = sqlite3.connect(ruta)
            conn.execute("create table matchday_snapshots (expected_points real, actual_points real)")
            conn.executemany("insert into matchday_snapshots values (?, ?)", [(3.0, 2.0)] * 10)
            conn.commit()
            conn.close()
            self.assertIsNone(pendiente_xp_en_vivo(ruta))


class GananciaDescontada(unittest.TestCase):
    def _accion(self, factor):
        plan = {
            "ratio_mercado": 3_800_000,
            "presupuesto": {"holgura": 30_000_000},
            "acciones": [{"tipo": "PUJA", "player_id": "x", "nombre": "x", "posicion": "DEF",
                          "euros": 4_000_000, "mejora_neta": 2.5, "momento": "hoy"}],
        }
        _sellar_pujas_plan(plan, {"x": {"valor_mercado": 4_000_000}}, None,
                           factor_xp={"factor": factor, "pendiente_vivo": None, "muestra_vivo": None})
        return plan, plan["acciones"][0]

    def test_la_ganancia_lleva_el_factor(self):
        plan, accion = self._accion(0.8)
        self.assertEqual(accion["ganancia_once_eur"], int(round(2.5 * 3_800_000 * 0.8)))
        self.assertEqual(accion["factor_xp"], 0.8)
        self.assertEqual(plan["calibracion_xp"]["factor"], 0.8)

    def test_menos_factor_no_sube_la_puja(self):
        _, alto = self._accion(1.0)
        _, bajo = self._accion(0.5)
        self.assertLessEqual(bajo["puja_final"], alto["puja_final"])


if __name__ == "__main__":
    unittest.main()

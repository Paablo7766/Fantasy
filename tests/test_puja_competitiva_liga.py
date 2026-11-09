"""Puja competitiva de liga: el escalón que cubre lo que paga quien nos gana las subastas."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from toolbox.engine import strategy_layer
from toolbox.engine.auction_intel import (
    cola_anti_picos,
    SOBREPUJA_MAX,
    estimar_sobrepuja_liga,
    puja_competitiva_liga,
)
from toolbox.engine_calibration import sobrepuja_de_liga

# Las seis pujas recomendadas que perdimos a 7 de noviembre de 2026: (nuestra cifra, lo que pagó el ganador).
PERDIDAS_REALES = [
    (600_350, 599_596),
    (612_366, 598_769),
    (754_426, 829_000),
    (2_124_493, 3_150_000),
    (12_877_871, 12_736_988),
    (12_736_988, 12_736_988),
]


class EstimadorTests(unittest.TestCase):
    def test_solo_cuentan_las_derrotas_en_las_que_el_ganador_pago_mas(self) -> None:
        resumen = estimar_sobrepuja_liga(PERDIDAS_REALES)
        self.assertEqual(resumen["perdidas"], 6)
        self.assertEqual(resumen["con_sobrepuja"], 2)
        # La media bruta de esas dos (+29 %) la mueve un solo rival; la estimación se encoge hacia el prior.
        self.assertAlmostEqual(resumen["media_exceso"], 0.2908, places=3)
        self.assertAlmostEqual(resumen["estimada"], 0.1303, places=3)

    def test_sin_perdidas_con_sobrepuja_no_hay_estimacion(self) -> None:
        self.assertIsNone(estimar_sobrepuja_liga([(1_000_000, 900_000), (2_000_000, 2_000_000)])["estimada"])
        self.assertIsNone(estimar_sobrepuja_liga([])["estimada"])

    def test_nunca_pasa_del_tope(self) -> None:
        resumen = estimar_sobrepuja_liga([(1_000_000, 3_000_000)] * 30)
        self.assertEqual(resumen["estimada"], SOBREPUJA_MAX)

    def test_ignora_datos_que_no_son_importes(self) -> None:
        resumen = estimar_sobrepuja_liga([(None, 5), (5, None), (True, 9), (0, 9), ("x", 1)])  # type: ignore[list-item]
        self.assertEqual(resumen["perdidas"], 0)


class EscalonTests(unittest.TestCase):
    def test_sube_la_estimacion_sobre_nuestra_cifra(self) -> None:
        cifra = puja_competitiva_liga(10_000_000, 14_000_000, 0.13, clave="7")
        self.assertEqual(cifra, 11_300_000 + cola_anti_picos("7"))
        self.assertNotEqual(cifra % 10, 0)

    def test_nunca_pasa_del_techo_de_rentabilidad(self) -> None:
        self.assertEqual(puja_competitiva_liga(10_000_000, 10_500_000, 0.13), 10_500_000)

    def test_techo_pegado_a_la_base_no_deja_escalon(self) -> None:
        self.assertIsNone(puja_competitiva_liga(10_000_000, 10_000_000, 0.13))
        self.assertIsNone(puja_competitiva_liga(10_000_000, 9_000_000, 0.13))

    def test_respeta_el_margen_de_caja(self) -> None:
        self.assertEqual(puja_competitiva_liga(10_000_000, 14_000_000, 0.13, margen=500_000), 10_500_000)
        self.assertIsNone(puja_competitiva_liga(10_000_000, 14_000_000, 0.13, margen=0))
        self.assertIsNone(puja_competitiva_liga(10_000_000, 14_000_000, 0.13, margen=-1))

    def test_sin_evidencia_o_sin_techo_no_hay_cifra(self) -> None:
        self.assertIsNone(puja_competitiva_liga(10_000_000, 14_000_000, None))
        self.assertIsNone(puja_competitiva_liga(10_000_000, None, 0.13))
        self.assertIsNone(puja_competitiva_liga(None, 14_000_000, 0.13))
        self.assertIsNone(puja_competitiva_liga(10_000_000, 14_000_000, 0))


class HistorialTests(unittest.TestCase):
    def _base(self, filas: list[tuple]) -> Path:
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        ruta = Path(directorio.name) / "responses.sqlite"
        conn = sqlite3.connect(ruta)
        conn.execute(
            "create table market_decision_snapshots (snapshot_day text, player_id text, decision text, "
            "suggested_bid integer, predicted_win real, outcome text, paid_eur integer)"
        )
        conn.executemany("insert into market_decision_snapshots values (?,?,?,?,?,?,?)", filas)
        conn.commit()
        conn.close()
        return ruta

    def test_lee_las_pujar_perdidas_y_usa_la_congelada_si_falta_la_sugerida(self) -> None:
        ruta = self._base(
            [
                ("2026-11-01", "873", "PUJAR", None, 754_426.0, "lost", 829_000),
                ("2026-11-04", "2949", "PUJAR", 2_124_493, 2_164_767.0, "lost", 3_150_000),
                ("2026-11-04", "x", "PUJAR", 1_000_000, None, "hit", 1_000_000),
                ("2026-11-04", "y", "NO_PUJAR", 1_000_000, None, "lost", 9_000_000),
            ]
        )
        resumen = sobrepuja_de_liga(ruta)
        assert resumen is not None
        self.assertEqual((resumen["perdidas"], resumen["con_sobrepuja"]), (2, 2))

    def test_sin_base_o_sin_evidencia_devuelve_none(self) -> None:
        self.assertIsNone(sobrepuja_de_liga(Path("no-existe.sqlite")))
        self.assertIsNone(sobrepuja_de_liga(self._base([("2026-11-01", "1", "PUJAR", 5, None, "hit", 5)])))


class PlanTests(unittest.TestCase):
    def test_el_objetivo_del_plan_lleva_la_competitiva_dentro_del_techo_y_del_presupuesto(self) -> None:
        plan = {
            "presupuesto": {"holgura": 2_000_000, "credito_20pct": 0, "credito_paron": 0},
            "acciones": [{"tipo": "PUJA", "player_id": "7", "euros": 10_000_000}],
        }
        pujas = {"7": {"puja_maxima": 14_000_000, "puja_pizarra": 10_300_000}}
        strategy_layer._sellar_pujas_plan(plan, pujas, {"estimada": 0.13, "perdidas": 6, "con_sobrepuja": 2})
        accion = plan["acciones"][0]
        self.assertEqual(accion["puja_competitiva_liga"], 11_300_000 + cola_anti_picos("7"))
        self.assertEqual(accion["sobrepuja_liga_pct"], 13.0)
        self.assertEqual(pujas["7"]["puja_competitiva_liga"], 11_300_000 + cola_anti_picos("7"))

    def test_sin_holgura_en_el_presupuesto_no_ofrece_escalon(self) -> None:
        plan = {
            "presupuesto": {"holgura": 0, "credito_20pct": 0, "credito_paron": 0},
            "acciones": [{"tipo": "PUJA", "player_id": "7", "euros": 10_000_000}],
        }
        pujas = {"7": {"puja_maxima": 14_000_000}}
        strategy_layer._sellar_pujas_plan(plan, pujas, {"estimada": 0.13})
        self.assertIsNone(plan["acciones"][0]["puja_competitiva_liga"])

    def test_la_puja_con_credito_usa_lo_que_queda_del_20_por_ciento(self) -> None:
        plan = {
            "presupuesto": {"holgura": 0, "credito_20pct": 40_000_000, "credito_paron": 38_800_000},
            "acciones": [{"tipo": "PUJA", "player_id": "7", "euros": 10_000_000, "financia_con_credito": True}],
        }
        pujas = {"7": {"puja_maxima": 14_000_000}}
        strategy_layer._sellar_pujas_plan(plan, pujas, {"estimada": 0.13})
        self.assertEqual(plan["acciones"][0]["puja_competitiva_liga"], 11_200_000)

    def test_sin_historial_el_plan_sigue_igual(self) -> None:
        plan = {"presupuesto": {"holgura": 5_000_000}, "acciones": [{"tipo": "PUJA", "player_id": "7", "euros": 10_000_000}]}
        strategy_layer._sellar_pujas_plan(plan, {"7": {"puja_maxima": 14_000_000}}, None)
        self.assertIsNone(plan["acciones"][0]["puja_competitiva_liga"])
        self.assertIsNone(plan["acciones"][0]["sobrepuja_liga_pct"])

    def test_si_la_base_de_datos_falla_no_tumba_el_plan(self) -> None:
        with patch("toolbox.engine_calibration.sobrepuja_de_liga", side_effect=RuntimeError("boom")):
            self.assertIsNone(strategy_layer._sobrepuja_liga())


if __name__ == "__main__":
    unittest.main()


class VentaDeRivalFueraDelPlanTests(unittest.TestCase):
    def test_la_sobrepuja_ignora_las_subastas_de_rivales(self) -> None:
        import sqlite3
        import tempfile
        from pathlib import Path

        from toolbox.engine_calibration import _ensure_tracking_schema

        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "c.sqlite"
            conn = sqlite3.connect(ruta)
            _ensure_tracking_schema(conn)
            filas = [("2026-11-0%d" % i, str(i), "PUJAR", 1_000_000, "lost", 1_500_000, fuente) for i, fuente in
                     enumerate(["rival", "rival", "rival", "liga"], start=1)]
            for dia, pid, dec, sug, out, pag, fuente in filas:
                conn.execute(
                    "insert into market_decision_snapshots (snapshot_day, player_id, decision, suggested_bid, stored_at, outcome, paid_eur, offer_source) values (?,?,?,?,0,?,?,?)",
                    (dia, pid, dec, sug, out, pag, fuente),
                )
            conn.commit()
            conn.close()
            resumen = sobrepuja_de_liga(ruta)
            self.assertEqual(resumen["perdidas"], 1)

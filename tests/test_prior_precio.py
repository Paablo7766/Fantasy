"""Prior por valor de mercado y consenso de titularidad baja."""

from __future__ import annotations

import unittest

from toolbox.analitica_fantasy import _consenso_titularidad_baja
from toolbox.engine.xp_calculator import (
    AJUSTE_PRIOR_MAX,
    AJUSTE_PRIOR_MIN,
    ajuste_prior_por_precio,
    percentil_precio,
    predecir_desde_jugador,
)


class PriorPorPrecioTests(unittest.TestCase):
    def test_percentil_crece_con_el_precio_y_se_acota(self) -> None:
        bajo = percentil_precio("DL", 600_000)
        medio = percentil_precio("DL", 3_000_000)
        alto = percentil_precio("DL", 40_000_000)
        self.assertLess(bajo, medio)
        self.assertLess(medio, alto)
        self.assertEqual(percentil_precio("DL", 500_000_000), 1.0)
        self.assertIsNone(percentil_precio("DL", None))
        self.assertIsNone(percentil_precio("XX", 1_000_000))

    def test_ajuste_dentro_de_los_limites(self) -> None:
        self.assertAlmostEqual(ajuste_prior_por_precio("MC", 100), AJUSTE_PRIOR_MIN)
        self.assertAlmostEqual(ajuste_prior_por_precio("MC", 500_000_000), AJUSTE_PRIOR_MAX)
        self.assertEqual(ajuste_prior_por_precio("MC", None), 0.0)

    def test_el_caro_parte_de_un_xp_mayor_que_el_barato_sin_historial(self) -> None:
        def xp(precio: int) -> float:
            return predecir_desde_jugador(
                {"position": "DEL", "market_value": precio, "week_points": [6.0, 6.0]}, prob_titular=0.9
            )["xp_pizarra"]

        self.assertGreater(xp(40_000_000), xp(700_000))


class ActasTests(unittest.TestCase):
    def test_inyecta_el_historial_con_minutos_y_lo_quita_al_acabar(self) -> None:
        from unittest import mock

        from toolbox import own_intel

        actas = {"7": {"weeks": {2: (9.0, 90.0), 1: (3.0, 20.0)}}}
        jugadores = [{"player_id": "7"}, {"player_id": "8"}, {"player_id": "7", "historial": [{"puntos": 1}]}]
        with mock.patch.object(own_intel, "_actas_en_cache", return_value=actas):
            puestos = own_intel._inyectar_actas(jugadores)
        self.assertEqual(len(puestos), 1)
        self.assertEqual(jugadores[0]["historial"][0], {"puntos": 3.0, "minutos": 20, "jornada": 1})
        self.assertEqual(jugadores[0]["historial"][1]["minutos"], 90)
        self.assertNotIn("historial", jugadores[1])
        self.assertEqual(jugadores[2]["historial"], [{"puntos": 1}])

    def test_con_actas_el_xp_depende_del_jugador_y_no_solo_del_puesto(self) -> None:
        def xp(puntos: float) -> float:
            historial = [{"puntos": puntos, "minutos": 90, "jornada": j} for j in range(1, 7)]
            return predecir_desde_jugador({"position": "DEL", "historial": historial}, prob_titular=1.0)["xp_condicional"]

        self.assertGreater(xp(10.0), xp(2.0) + 1.0)


class ConsensoTitularidadTests(unittest.TestCase):
    def test_las_dos_fuentes_bajas_marcan_consenso(self) -> None:
        player = {"p_titular": 0.15, "p_titular_source": "scraper", "af_p_titular": 0.1}
        _consenso_titularidad_baja(player)
        self.assertEqual(player["p_titular_consenso"], "bajo")
        self.assertEqual(player["p_titular"], 0.1)

    def test_una_sola_fuente_baja_no_basta(self) -> None:
        player = {"p_titular": 0.15, "p_titular_source": "scraper", "af_p_titular": 0.7}
        _consenso_titularidad_baja(player)
        self.assertNotIn("p_titular_consenso", player)
        self.assertEqual(player["p_titular"], 0.15)

    def test_sin_fuente_ff_no_hay_consenso(self) -> None:
        player = {"p_titular": 0.1, "p_titular_source": "week_points", "af_p_titular": 0.1}
        _consenso_titularidad_baja(player)
        self.assertNotIn("p_titular_consenso", player)


if __name__ == "__main__":
    unittest.main()

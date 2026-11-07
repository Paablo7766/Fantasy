"""Calibración de nov 2026: ajuste de precio de las estrellas y tope de picos."""

from __future__ import annotations

import unittest

from toolbox.engine.xp_calculator import (
    AJUSTE_PRIOR_MAX,
    AJUSTE_PRIOR_MAX_ESTRELLA,
    TOPE_PICO_PUNTOS,
    FantasyXPEngine,
    PartidoHistorico,
    ContextoEquipo,
    ajuste_prior_jugador,
    ajuste_prior_por_precio,
)


class EstrellasTests(unittest.TestCase):
    def test_estrella_puede_subir_por_encima_del_tope_normal(self) -> None:
        self.assertAlmostEqual(ajuste_prior_jugador("DF", 200_000_000), AJUSTE_PRIOR_MAX_ESTRELLA)
        self.assertGreater(AJUSTE_PRIOR_MAX_ESTRELLA, AJUSTE_PRIOR_MAX)

    def test_jugador_normal_no_cambia(self) -> None:
        for precio in (600_000, 3_000_000, 12_000_000):
            self.assertAlmostEqual(ajuste_prior_jugador("MC", precio), ajuste_prior_por_precio("MC", precio))


class TopePicoTests(unittest.TestCase):
    def _xp(self, puntos: list[float]) -> float:
        historial = [PartidoHistorico(puntos=p, minutos=90, jornada=i) for i, p in enumerate(puntos, start=1)]
        neutro = ContextoEquipo(xg_favor_90=1.25, xg_contra_90=1.25, es_local=True)
        return FantasyXPEngine.calcular_prediccion_completa("DL", historial, 1.0, neutro, neutro)["xp_condicional"]

    def test_un_20_aislado_cuenta_como_el_tope(self) -> None:
        self.assertAlmostEqual(self._xp([3, 3, 6, 20, 7]), self._xp([3, 3, 6, TOPE_PICO_PUNTOS, 7]))

    def test_por_debajo_del_tope_no_cambia_nada(self) -> None:
        self.assertLess(self._xp([3, 3, 6, 9, 7]), self._xp([3, 3, 6, 12, 7]))


if __name__ == "__main__":
    unittest.main()

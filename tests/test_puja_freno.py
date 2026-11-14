"""Freno a la prima por poca muestra: la cifra óptima tiene que aguantar el remuestreo.

Se rehace la curva con las compras remuestreadas y se toma el percentil 25 de las
primas óptimas: si la cifra depende de tres o cuatro compras sueltas, baja.
"""

import unittest

from toolbox.engine.auction_intel import muestras_prior, prima_frenada, puja_por_valor


class Freno(unittest.TestCase):
    def _estable(self):
        # 60 compras a +5 % y 40 a +20 %: la curva no depende de nadie en concreto.
        return [{"prima": 0.05, "valor": 8_000_000} for _ in range(60)] + [
            {"prima": 0.20, "valor": 8_000_000} for _ in range(40)
        ]

    def _fragil(self):
        # 37 compras a +5 % y solo 3 a +90 %: la subida de la curva arriba son 3 compras.
        return [{"prima": 0.05, "valor": 8_000_000} for _ in range(37)] + [
            {"prima": 0.90, "valor": 8_000_000} for _ in range(3)
        ]

    def test_con_muestra_firme_el_freno_no_cambia_la_cifra(self):
        f = prima_frenada(self._estable(), valor=8_000_000, ganancia=6_000_000, clave="x")
        self.assertEqual(f["prima_max"], f["mediana"])

    def test_con_la_cola_en_tres_compras_el_freno_baja_la_prima(self):
        muestras = self._fragil()
        f = prima_frenada(muestras, valor=8_000_000, ganancia=40_000_000, clave="x")
        self.assertLess(f["prima_max"], 0.90)
        r = puja_por_valor(8_000_000, 40_000_000, prima_max=f["prima_max"])
        self.assertLessEqual(r["prima"], f["prima_max"])

    def test_la_misma_clave_da_la_misma_cifra(self):
        a = prima_frenada(self._fragil(), valor=8_000_000, ganancia=40_000_000, clave="2565")
        b = prima_frenada(self._fragil(), valor=8_000_000, ganancia=40_000_000, clave="2565")
        self.assertEqual(a, b)

    def test_sin_base_remuestrea_las_curvas_medidas(self):
        self.assertEqual(len(muestras_prior()), 19 + 21 + 43)
        f = prima_frenada(None, valor=3_000_000, ganancia=9_000_000, clave="x")
        self.assertIsNotNone(f["prima_max"])


if __name__ == "__main__":
    unittest.main()

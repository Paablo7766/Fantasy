"""Inercia, aceleración y valor justo del precio de mercado.

La serie de siete días sale de la fórmula documentada. Ninguna prueba toca
la red ni el caché.
"""

from __future__ import annotations

import unittest

from toolbox.engine.market_predictor import (
    AMORTIGUACION,
    EUROS_POR_PUNTO,
    FACTOR_RETORNO,
    HORIZONTE_DIAS,
    PESO_ACELERACION,
    PESO_ACELERACION_FRENADA,
    PESO_INERCIA,
    predecir_precio,
)


# Un punto esperado y el precio clavado en el valor justo: la fuerza de
# retorno es cero y solo se ve la inercia.
PRECIO_JUSTO = EUROS_POR_PUNTO
XP_UN_PUNTO = 1.0


def _proyeccion(delta_manana: int) -> int:
    """Suma geométrica que el módulo acumula en el bucle de siete días."""
    delta = float(delta_manana)
    acumulado = 0.0
    for _dia in range(HORIZONTE_DIAS):
        acumulado += delta
        delta *= AMORTIGUACION
    return int(round((PRECIO_JUSTO + acumulado) / 10_000)) * 10_000


class InerciaTests(unittest.TestCase):
    def test_subida_que_acelera_arrastra_el_delta_de_hoy(self) -> None:
        # 0,9 * 200.000 + 0,35 * 120.000 = 222.000, pero el tope es el movimiento de hoy: 200.000 €.
        resultado = predecir_precio(PRECIO_JUSTO, 200_000, 80_000, XP_UN_PUNTO)
        self.assertEqual(resultado["delta_manana"], 200_000)
        self.assertEqual(resultado["valor_en_7_dias"], _proyeccion(200_000))
        cambio = (resultado["valor_en_7_dias"] - PRECIO_JUSTO) / PRECIO_JUSTO * 100
        self.assertEqual(resultado["pct_cambio"], round(cambio, 2))
        self.assertGreater(resultado["valor_en_7_dias"], PRECIO_JUSTO)

    def test_frenada_pesa_menos_la_aceleracion_negativa(self) -> None:
        """Hoy sigue en positivo, pero ayer subió más: no se deja caer de golpe."""
        # Con peso 0,15: 90.000 − 9.000 = 81.000 → 80.000.
        # Con el peso pleno (0,35) serían 69.000 → 70.000.
        frenando = predecir_precio(PRECIO_JUSTO, 100_000, 160_000, XP_UN_PUNTO)
        self.assertLess(PESO_ACELERACION_FRENADA, PESO_ACELERACION)
        self.assertEqual(frenando["delta_manana"], 80_000)

        pleno = (PESO_INERCIA * 100_000) + (PESO_ACELERACION * (100_000 - 160_000))
        self.assertEqual(int(round(pleno / 10_000)) * 10_000, 70_000)
        self.assertGreater(frenando["delta_manana"], 70_000)

    def test_caida_que_se_acelera_conserva_el_peso_pleno(self) -> None:
        # Hoy −40.000, ayer −10.000. Aceleración −30.000, y hoy no es subida.
        # 0,9 * (−40.000) + 0,35 * (−30.000) = −46.500, con tope en el movimiento de hoy: −40.000.
        resultado = predecir_precio(PRECIO_JUSTO, -40_000, -10_000, XP_UN_PUNTO)
        self.assertEqual(resultado["delta_manana"], -40_000)
        self.assertLess(resultado["valor_en_7_dias"], PRECIO_JUSTO)


class ValorJustoTests(unittest.TestCase):
    def test_chollo_empuja_el_precio_hacia_arriba(self) -> None:
        # Justo 16,4 M, precio 10 M. Hueco 6,4 M * 0,02 = 128.000 → 130.000.
        self.assertEqual(FACTOR_RETORNO, 0.02)
        resultado = predecir_precio(10_000_000, 0, 0, XP_UN_PUNTO)
        self.assertEqual(resultado["delta_manana"], 130_000)
        self.assertGreater(resultado["pct_cambio"], 0)

    def test_sobrevalorado_empuja_el_precio_hacia_abajo(self) -> None:
        # Justo 16,4 M, precio 20 M. Hueco −3,6 M * 0,02 = −72.000 → −70.000.
        resultado = predecir_precio(20_000_000, 0, 0, XP_UN_PUNTO)
        self.assertEqual(resultado["delta_manana"], -70_000)
        self.assertLess(resultado["valor_en_7_dias"], 20_000_000)
        self.assertLess(resultado["pct_cambio"], 0)

    def test_sin_puntos_el_valor_justo_es_cero(self) -> None:
        resultado = predecir_precio(5_000_000, 0, 0, 0)
        # (0 − 5.000.000) * 0,02 = −100.000, ya en el escalón.
        self.assertEqual(resultado["delta_manana"], -100_000)

    def test_un_punto_esperado_vale_16_4_millones(self) -> None:
        self.assertEqual(EUROS_POR_PUNTO, 16_400_000)
        # 2,5 puntos → 41 M. Precio ya en 41 M: retorno nulo, delta 0.
        resultado = predecir_precio(41_000_000, 0, 0, 2.5)
        self.assertEqual(resultado["delta_manana"], 0)
        self.assertEqual(resultado["valor_en_7_dias"], 41_000_000)
        self.assertEqual(resultado["pct_cambio"], 0.0)


class ProyeccionTests(unittest.TestCase):
    def test_siete_dias_amortiguan_el_impulso(self) -> None:
        resultado = predecir_precio(PRECIO_JUSTO, 200_000, 80_000, XP_UN_PUNTO)
        delta = 200_000.0
        acumulado = 0.0
        for _dia in range(7):
            acumulado += delta
            delta *= 0.95
        # El factor 0,95 deja el día 7 en una fracción del primero, no en cero
        # ni en una copia del delta de mañana.
        self.assertLess(delta / 0.95, 200_000)
        self.assertGreater(acumulado, 200_000)
        self.assertLess(acumulado, 200_000 * 7)
        self.assertEqual(resultado["valor_en_7_dias"], int(round((PRECIO_JUSTO + acumulado) / 10_000)) * 10_000)

    def test_las_claves_del_contrato(self) -> None:
        resultado = predecir_precio(PRECIO_JUSTO, 10_000, 10_000, XP_UN_PUNTO)
        self.assertEqual(set(resultado), {"delta_manana", "valor_en_7_dias", "pct_cambio"})
        self.assertEqual(resultado["delta_manana"] % 10_000, 0)
        self.assertEqual(resultado["valor_en_7_dias"] % 10_000, 0)


class EntradaTests(unittest.TestCase):
    def test_precio_no_positivo_no_tiene_porcentaje(self) -> None:
        with self.assertRaises(ValueError):
            predecir_precio(0, 10_000, 0, 1)
        with self.assertRaises(ValueError):
            predecir_precio(-1_000_000, 10_000, 0, 1)

    def test_rechaza_valores_no_numericos(self) -> None:
        with self.assertRaises(TypeError):
            predecir_precio(True, 0, 0, 1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            predecir_precio(float("nan"), 0, 0, 1)


if __name__ == "__main__":
    unittest.main()

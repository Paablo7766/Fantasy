"""Nota de fichaje: impacto, revalorización, racha y dificultad."""

from __future__ import annotations

import unittest

from toolbox.engine.market_grade import calcular_nota_mercado


def _titulares() -> list[dict]:
    return [
        {"position": "MC", "xp": 4.0, "en_xi": True},
        {"position": "MC", "xp": 7.5, "en_xi": True},
        {"position": "DEL", "xp": 6.0, "en_xi": True},
    ]


class NotaMercadoTests(unittest.TestCase):
    def test_el_impacto_se_mide_contra_el_peor_titular(self) -> None:
        # 6 − 4 = +2,0 xP. No contra el 7,5.
        nota = calcular_nota_mercado(
            {"position": "MC", "xp": 6.0, "prevision_7d_pct": 0, "p_titular": 0, "dificultad": "medio", "precio": 8_000_000},
            _titulares(),
            20_000_000,
        )
        self.assertEqual(nota["impacto_xp"], 2.0)

    def test_titular_claro_con_subida_y_partido_facil_conviene(self) -> None:
        nota = calcular_nota_mercado(
            {
                "position": "MC",
                "xp": 7.0,
                "prevision_7d_pct": 23.2,
                "p_titular": 0.9,
                "week_points": [8, 7, 9, 6, 8],
                "dificultad": "facil",
                "precio": 12_000_000,
            },
            _titulares(),
            20_000_000,
        )
        self.assertGreaterEqual(nota["nota_mercado"], 8.0)
        self.assertEqual(nota["veredicto_mercado"], "TE CONVIENE (TITULAR)")
        self.assertEqual(nota["etiqueta_mercado"], "TE CONVIENE")
        self.assertIn("Mejora +3,0 pts tu mediocampo", nota["frase_mercado"])
        self.assertIn("+23% esta semana", nota["frase_mercado"])

    def test_subida_fuerte_sin_llegar_a_ocho_es_especular(self) -> None:
        nota = calcular_nota_mercado(
            {
                "position": "MC",
                "xp": 6.0,
                "prevision_7d_pct": 13,
                "p_titular": 0.8,
                "week_points": [5, 5, 5, 5, 5],
                "dificultad": "medio",
                "precio": 8_000_000,
            },
            _titulares(),
            20_000_000,
        )
        self.assertGreaterEqual(nota["nota_mercado"], 7.0)
        self.assertLess(nota["nota_mercado"], 8.0)
        self.assertEqual(nota["etiqueta_mercado"], "ESPECULAR")

    def test_mas_de_quince_por_ciento_llena_el_bloque_de_revalorizacion(self) -> None:
        base = {
            "position": "DEL",
            "xp": 6.0,
            "p_titular": 0.5,
            "week_points": [4, 4, 4],
            "dificultad": "medio",
            "precio": 9_000_000,
        }
        justo = calcular_nota_mercado({**base, "prevision_7d_pct": 15}, _titulares(), 20_000_000)
        alto = calcular_nota_mercado({**base, "prevision_7d_pct": 40}, _titulares(), 20_000_000)
        self.assertEqual(justo["nota_mercado"], alto["nota_mercado"])

    def test_parche_barato_y_descarte(self) -> None:
        parche = calcular_nota_mercado(
            {
                "position": "MC",
                "xp": 6.0,
                "prevision_7d_pct": 10,
                "p_titular": 0.4,
                "week_points": [4, 4, 4, 4],
                "dificultad": "medio",
                "precio": 4_000_000,
            },
            _titulares(),
            10_000_000,
        )
        self.assertGreaterEqual(parche["nota_mercado"], 6.0)
        self.assertLessEqual(parche["nota_mercado"], 7.5)
        self.assertEqual(parche["veredicto_mercado"], "PARCHE ÚTIL")
        self.assertEqual(parche["etiqueta_mercado"], "PARCHE")

        descarte = calcular_nota_mercado(
            {
                "position": "MC",
                "xp": 3.0,
                "prevision_7d_pct": -4,
                "p_titular": 0.2,
                "week_points": [1, 0, 2],
                "dificultad": "dificil",
                "precio": 10_000_000,
            },
            _titulares(),
            20_000_000,
        )
        self.assertLess(descarte["nota_mercado"], 6.0)
        self.assertEqual(descarte["etiqueta_mercado"], "DESCARTAR")
        self.assertIn("partido es difícil", descarte["frase_mercado"])

    def test_el_partido_facil_sube_la_nota_respecto_al_dificil(self) -> None:
        cuerpo = {
            "position": "DEL",
            "xp": 6.5,
            "prevision_7d_pct": 4,
            "p_titular": 0.7,
            "week_points": [5, 5, 5],
            "precio": 8_000_000,
        }
        facil = calcular_nota_mercado({**cuerpo, "dificultad": "facil"}, _titulares(), 20_000_000)
        dificil = calcular_nota_mercado({**cuerpo, "dificultad": "dificil"}, _titulares(), 20_000_000)
        self.assertGreater(facil["nota_mercado"], dificil["nota_mercado"])

    def test_sin_caja_la_frase_lo_dice_y_no_cambia_el_veredicto_deportivo(self) -> None:
        holgado = calcular_nota_mercado(
            {
                "position": "MC",
                "xp": 7.0,
                "prevision_7d_pct": 20,
                "p_titular": 0.95,
                "week_points": [8, 8, 8, 8, 8],
                "dificultad": "muy_facil",
                "precio": 9_000_000,
            },
            _titulares(),
            1_000_000,
        )
        self.assertEqual(holgado["cabe_en_caja"], False)
        # El saldo pasado es el poder de puja (caja + crédito): por encima, ni con crédito.
        self.assertIn("No te llega ni con crédito", holgado["frase_mercado"])
        self.assertEqual(holgado["etiqueta_mercado"], "TE CONVIENE")

    def test_con_credito_la_frase_dice_que_se_paga_con_credito(self) -> None:
        jugador = {"position": "MC", "xp": 7.0, "prevision_7d_pct": 20, "p_titular": 0.95, "precio": 9_000_000}
        nota = calcular_nota_mercado(jugador, _titulares(), 30_000_000, caja=250_000)
        self.assertIn("Se paga con crédito", nota["frase_mercado"])
        self.assertNotIn("No te llega", nota["frase_mercado"])


if __name__ == "__main__":
    unittest.main()

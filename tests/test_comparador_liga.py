"""Coste real de liga: oferta, puja smart y cláusula, no el valor genérico."""

from __future__ import annotations

import unittest

from toolbox.engine.comparador_liga import comparar_fichas, comparar_jugadores_liga


def _actual(**extra: object) -> dict:
    base = {
        "player_id": "a",
        "nickname": "Aitor",
        "position": "DEL",
        "is_self": True,
        "en_plantilla": True,
        "valor": 25_600_000,
        "xp_j1": 3.8,
        "p_titular": 0.70,
        "techo": 8.0,
        "prevision_7d_pct": 7.5,
    }
    base.update(extra)
    return base


def _objetivo(**extra: object) -> dict:
    base = {
        "player_id": "b",
        "nickname": "Pepelu",
        "position": "DEL",
        "valor": 36_000_000,
        "xp_j1": 4.7,
        "p_titular": 0.90,
        "techo": 12.0,
        "prevision_7d_pct": 23.3,
    }
    base.update(extra)
    return base


class CompararFichasTests(unittest.TestCase):
    def test_la_oferta_de_hoy_es_el_ingreso_y_si_no_hay_se_espera(self) -> None:
        con_oferta = comparar_fichas(
            _actual(oferta_laliga=25_600_000, valor=20_000_000),
            _objetivo(en_mercado=True, vendedor="LaLiga", puja_smart=37_500_000, puja_maxima=42_000_000),
            saldo=50_000_000,
        )
        self.assertEqual(con_oferta["ingreso_venta_a"], 25_600_000)
        self.assertEqual(con_oferta["ingreso_fuente"], "oferta_laliga")
        self.assertFalse(con_oferta["esperar_oferta_24h"])

        sin_oferta = comparar_fichas(
            _actual(),
            _objetivo(en_mercado=True, vendedor="LaLiga", puja_smart=37_500_000),
            saldo=50_000_000,
        )
        self.assertEqual(sin_oferta["ingreso_venta_a"], 25_600_000)
        self.assertTrue(sin_oferta["esperar_oferta_24h"])
        self.assertIn("24 h", sin_oferta["nota_ejecucion"])

    def test_el_mercado_de_laliga_usa_la_puja_smart_y_no_el_valor(self) -> None:
        comparado = comparar_fichas(
            _actual(oferta_laliga=25_600_000),
            _objetivo(
                en_mercado=True,
                vendedor="LaLiga",
                valor=36_000_000,
                puja_smart=37_500_000,
                puja_maxima=42_000_000,
            ),
            saldo=80_000_000,
        )
        self.assertEqual(comparado["coste_adquisicion_b"], 37_500_000)
        self.assertEqual(comparado["coste_fuente"], "puja_smart")
        self.assertEqual(comparado["coste_etiqueta"], "Puja Smart: 37,5M")
        self.assertEqual(comparado["puja_maxima"], 42_000_000)
        self.assertEqual(comparado["delta_caja"], 37_500_000 - 25_600_000)
        self.assertEqual(comparado["saldo_final_tras_cambio"], 80_000_000 - (37_500_000 - 25_600_000))
        self.assertEqual(comparado["saldo_escenario_maxima"], 80_000_000 - (42_000_000 - 25_600_000))

    def test_la_clausula_del_rival_manda_sobre_el_valor(self) -> None:
        comparado = comparar_fichas(
            _actual(oferta_laliga=25_600_000),
            _objetivo(
                propietario="PABS FC",
                posicion_liga=2,
                valor=25_000_000,
                clausula=60_000_000,
                clausula_abierta=False,
                clausulaAbre="jueves 10:15",
                prevision_7d_pct=4,
            ),
            saldo=70_000_000,
        )
        self.assertEqual(comparado["coste_adquisicion_b"], 60_000_000)
        self.assertNotEqual(comparado["coste_adquisicion_b"], 25_000_000)
        self.assertEqual(comparado["coste_fuente"], "clausula")
        self.assertEqual(comparado["coste_etiqueta"], "Cláusula de PABS FC: 60,0M")
        self.assertFalse(comparado["clausula_abierta"])
        self.assertEqual(comparado["clausula_abre"], "jueves 10:15")
        self.assertIn("jueves 10:15", comparado["nota_ejecucion"])
        self.assertEqual(comparado["veredicto_etiqueta"], "NO COMPENSA (CLÁUSULA INFLADA)")
        self.assertEqual(comparado["ganador"], "A")
        self.assertEqual(comparado["pill"], "CLÁUSULA CARA")
        aviso = comparado["impacto_rival"]["aviso"]
        self.assertEqual(aviso, "Cuidado: le inyectas +60,0M de caja a PABS FC")
        self.assertEqual(comparado["impacto_rival"]["posicion_liga"], 2)
        self.assertAlmostEqual(comparado["delta_xp_4j"], 0.9)

    def test_la_venta_de_un_rival_cuesta_el_minimo_entre_precio_y_clausula(self) -> None:
        comparado = comparar_fichas(
            _actual(oferta_laliga=10_000_000),
            _objetivo(
                en_mercado=True,
                vendedor="PABS FC",
                propietario="PABS FC",
                precio_venta_rival=30_000_000,
                clausula=58_000_000,
                valor=28_000_000,
                posicion_liga=4,
            ),
            saldo=40_000_000,
        )
        self.assertEqual(comparado["coste_adquisicion_b"], 30_000_000)
        self.assertEqual(comparado["coste_fuente"], "venta_rival")
        self.assertIn("PABS FC", comparado["impacto_rival"]["aviso"])
        self.assertIn("30,0M", comparado["impacto_rival"]["aviso"])

    def test_el_horizonte_pondera_los_cuatro_rivales(self) -> None:
        comparado = comparar_fichas(
            _actual(
                oferta_laliga=10_000_000,
                xp_j1=4.0,
                calendario=["dificil", "dificil", "dificil", "dificil"],
            ),
            _objetivo(
                en_mercado=True,
                vendedor="LaLiga",
                puja_smart=12_000_000,
                xp_j1=4.0,
                calendario=["dificil", "muy_facil", "muy_facil", "muy_facil"],
            ),
            saldo=20_000_000,
        )
        self.assertEqual(comparado["jugador_a"]["xp_4j"], 4.0)
        # 4,0 y tres veces 4,0 × 1,12 / 0,92.
        self.assertAlmostEqual(comparado["jugador_b"]["xp_4j"], (4.0 + 3 * 4.0 * 1.12 / 0.92) / 4, places=2)
        self.assertGreater(comparado["delta_xp_4j"], 0)
        self.assertAlmostEqual(comparado["delta_titularidad"], 0.2)
        self.assertAlmostEqual(comparado["delta_techo"], 4.0)

    def test_siete_dias_amortizan_la_caja_si_b_sube_mas_rapido(self) -> None:
        comparado = comparar_fichas(
            _actual(oferta_laliga=10_000_000, valor=10_000_000, prevision_7d_pct=0, xp_j1=4.0),
            _objetivo(
                en_mercado=True,
                vendedor="LaLiga",
                valor=20_000_000,
                puja_smart=15_000_000,
                puja_maxima=18_000_000,
                prevision_7d_pct=30,
                xp_j1=5.6,
                p_titular=0.95,
            ),
            saldo=30_000_000,
        )
        # Subida: 20M × 30 % = 6M. Caja: 5M. Neto a 7 días: −1M.
        self.assertEqual(comparado["delta_subida_7d_euros"], 6_000_000)
        self.assertEqual(comparado["coste_neto_a_7_dias"], -1_000_000)
        self.assertEqual(comparado["delta_caja"], 5_000_000)
        self.assertAlmostEqual(comparado["dias_amortizacion"], 5_000_000 / (6_000_000 / 7), places=1)
        self.assertEqual(comparado["coste_por_punto_extra"], 0)
        self.assertEqual(comparado["pill"], "RENTABLE EN 7D")
        self.assertEqual(comparado["veredicto_etiqueta"], "CAMBIO OBLIGATORIO")
        self.assertEqual(comparado["ganador"], "B")

    def test_un_cambio_claro_y_barato_es_obligatorio(self) -> None:
        comparado = comparar_fichas(
            _actual(oferta_laliga=20_000_000, valor=20_000_000, prevision_7d_pct=20, xp_j1=4.0, p_titular=0.8, techo=9),
            _objetivo(
                en_mercado=True,
                vendedor="LaLiga",
                valor=22_000_000,
                puja_smart=21_000_000,
                prevision_7d_pct=25,
                xp_j1=6.2,
                p_titular=0.92,
                techo=14,
            ),
            saldo=40_000_000,
        )
        # Caja: 1M. Subida neta: 22M×25% − 20M×20% = 1,5M. El neto a 7 días es negativo.
        self.assertLess(comparado["coste_neto_a_7_dias"], 0)
        self.assertEqual(comparado["veredicto_etiqueta"], "CAMBIO OBLIGATORIO")
        self.assertEqual(comparado["ganador_nombre"], "Pepelu")
        self.assertEqual(comparado["pill"], "RENTABLE EN 7D")

    def test_sin_mejora_deportiva_te_quedas_con_a(self) -> None:
        comparado = comparar_fichas(
            _actual(oferta_laliga=10_000_000, xp_j1=6.0),
            _objetivo(en_mercado=True, vendedor="LaLiga", puja_smart=12_000_000, xp_j1=4.5, p_titular=0.4, techo=6),
            saldo=20_000_000,
        )
        self.assertEqual(comparado["veredicto_etiqueta"], "MEJOR QUEDARSE A Aitor")
        self.assertEqual(comparado["ganador"], "A")


class CompararDesdeTableroTests(unittest.TestCase):
    def test_resuelve_ids_y_paga_la_clausula_real(self) -> None:
        board = {
            "squads": {
                "squads": [
                    {
                        "team_id": "me",
                        "is_self": True,
                        "manager_name": "Yo",
                        "cash": 70_000_000,
                        "rank": 5,
                        "players": [
                            {
                                "player_id": "a",
                                "nickname": "Aitor",
                                "position": "DEL",
                                "market_value": 25_600_000,
                                "jornada_ev": 3.8,
                                "p_titular": 0.7,
                                "own_ceiling_points": 8,
                                "oferta_sistema": 25_600_000,
                            }
                        ],
                    },
                    {
                        "team_id": "rival",
                        "is_self": False,
                        "manager_name": "Pablo",
                        "fantasy_team_name": "PABS FC",
                        "rank": 1,
                        "players": [
                            {
                                "player_id": "b",
                                "nickname": "Pepelu",
                                "position": "DEL",
                                "market_value": 25_000_000,
                                "buyout_clause": 60_000_000,
                                "jornada_ev": 4.7,
                                "p_titular": 0.9,
                                "own_ceiling_points": 12,
                                "clause_lock": {"is_locked": False},
                            }
                        ],
                    },
                ]
            },
            "market": {"listings": []},
            "trends": {"players": []},
            "optimize": {"xi": [], "benched": [], "excluded": []},
        }
        comparado = comparar_jugadores_liga("a", "b", board)
        self.assertTrue(comparado["ok"])
        self.assertEqual(comparado["ingreso_venta_a"], 25_600_000)
        self.assertFalse(comparado["esperar_oferta_24h"])
        self.assertEqual(comparado["coste_adquisicion_b"], 60_000_000)
        self.assertEqual(comparado["saldo_final_tras_cambio"], 70_000_000 - (60_000_000 - 25_600_000))
        self.assertEqual(comparado["veredicto_etiqueta"], "NO COMPENSA (CLÁUSULA INFLADA)")
        self.assertIn("PABS FC", comparado["impacto_rival"]["aviso"])
        self.assertEqual(comparado["impacto_rival"]["posicion_liga"], 1)
        self.assertTrue(comparado["clausula_abierta"])

    def test_id_desconocido(self) -> None:
        comparado = comparar_jugadores_liga("a", "z", {"squads": {"squads": []}, "market": {}, "trends": {}, "optimize": {}})
        self.assertFalse(comparado["ok"])
        self.assertEqual(comparado["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()

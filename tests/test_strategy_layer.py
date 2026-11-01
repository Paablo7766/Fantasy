"""Ratio de liga, precio a 7 días, WAR, pujas, rivales en negativo y plan.

No toca la red ni el caché. El plan de fichajes es el único que llama al solver.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.engine.auction_intel import calcular_pujas, capitanes, nota_y_veredicto
from toolbox.engine.lineup_math import war_del_once
from toolbox.engine.market_predictor import (
    EUROS_POR_PUNTO,
    formatear_pct,
    proyectar_7d,
    ratio_mercado_liga,
    valor_justo_jugador,
)
from toolbox.engine.signing_plan import BUSCA_PUNTOS, build_plan_fichajes
from toolbox.engine.strategy_layer import build_strategy


def _jugador(player_id: str, position: str, jornada: float, **extra: object) -> dict:
    row = {
        "player_id": player_id,
        "nombre": player_id,
        "position": position,
        "jornada": jornada,
        "elegible": True,
    }
    row.update(extra)
    return row


def _once(puntos: float = 5.0) -> list[dict]:
    plantilla = []
    for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
        for index in range(count):
            plantilla.append(_jugador(f"{position}-{index}", position, puntos))
    return plantilla


class RatioYPrecioTests(unittest.TestCase):
    def test_sin_muestra_usa_la_referencia(self) -> None:
        ratio = ratio_mercado_liga([(8_000_000, 4.0)] * 3)
        self.assertTrue(ratio["usa_referencia"])
        self.assertEqual(ratio["ratio_mercado"], float(EUROS_POR_PUNTO))

    def test_el_titular_medio_vale_lo_que_paga_el_mercado(self) -> None:
        ratio = ratio_mercado_liga([(8_000_000, 4.0)] * 8)
        self.assertFalse(ratio["usa_referencia"])
        self.assertEqual(ratio["ratio_mercado"], 2_000_000)
        self.assertEqual(valor_justo_jugador(4.0, 2_000_000), 8_000_000)
        self.assertEqual(valor_justo_jugador(1.0, EUROS_POR_PUNTO), EUROS_POR_PUNTO)

    def test_chollo_en_forma_sube_y_sin_forma_no(self) -> None:
        en_forma = proyectar_7d(4_000_000, 0, 0, 4.0, 2_000_000, en_forma=True)
        frio = proyectar_7d(4_000_000, 0, 0, 4.0, 2_000_000, en_forma=False)
        self.assertGreater(en_forma["valor_en_7d"], 4_000_000)
        self.assertTrue(str(en_forma["prevision_7d_pct"]).startswith("+"))
        self.assertEqual(frio["valor_en_7d"], 4_000_000)
        self.assertEqual(frio["prevision_7d_pct"], "0.0%")

    def test_sobrevalorado_corrige_aunque_no_venga_de_puntuar(self) -> None:
        caro = proyectar_7d(12_000_000, 0, 0, 4.0, 2_000_000, en_forma=False)
        self.assertLess(caro["valor_en_7d"], 12_000_000)
        self.assertTrue(str(caro["prevision_7d_pct"]).startswith("-"))

    def test_el_porcentaje_lleva_signo_y_un_decimal(self) -> None:
        self.assertEqual(formatear_pct(10.94), "+10.9%")
        self.assertEqual(formatear_pct(-2.14), "-2.1%")
        self.assertEqual(formatear_pct(0.0), "0.0%")


class WarYCapitanTests(unittest.TestCase):
    def test_sin_suplente_se_pierde_el_once_entero(self) -> None:
        xi = _once(5.0)
        perdidas = war_del_once(xi, [])
        self.assertEqual(perdidas["POR-0"], 55.0)
        self.assertEqual(perdidas["DEL-2"], 55.0)

    def test_el_suplente_del_puesto_recorta_la_perdida(self) -> None:
        xi = _once(5.0)
        xi[1]["jornada"] = 6.0  # DEF-0
        banquillo = [_jugador("DEF-sup", "DEF", 3.0)]
        perdidas = war_del_once(xi, banquillo)
        self.assertEqual(perdidas["DEF-0"], 3.0)
        self.assertEqual(perdidas["DEF-1"], 2.0)

    def test_capitan_seguro_exige_titularidad_y_el_de_techo_no(self) -> None:
        xi = _once(4.0)
        xi[10]["jornada"] = 8.0
        xi[10]["p_titular"] = 0.91
        xi[10]["techo"] = 11.0
        xi[10]["nombre"] = "Seguro"
        xi[9]["jornada"] = 5.0
        xi[9]["p_titular"] = 0.5
        xi[9]["techo"] = 18.0
        xi[9]["nombre"] = "Techo"
        caps = capitanes(xi)
        self.assertEqual(caps["capitan_seguro"]["player_id"], "DEL-2")
        self.assertEqual(caps["capitan_remontada"]["player_id"], "DEL-1")

    def test_nota_y_veredicto(self) -> None:
        self.assertEqual(nota_y_veredicto(0.2, [{"momento": "luego"}]), (1, "Opcional"))
        self.assertEqual(nota_y_veredicto(0.5, [{"momento": "luego"}]), (5, "Recomendable"))
        self.assertEqual(nota_y_veredicto(0.9, [{"momento": "hoy"}]), (8, "Hazlo ya"))
        self.assertEqual(nota_y_veredicto(0.0, []), (0, "Opcional"))


class PujaYForzadaTests(unittest.TestCase):
    def test_recomendada_suma_la_subida_de_hoy_y_el_tope_es_el_minimo(self) -> None:
        pujas = calcular_pujas(10_000_000, 200_000, 8_000_000, tu_saldo=20_000_000, rivales=[], posicion="MC")
        self.assertEqual(pujas["puja_recomendada"], 10_670_000)
        self.assertEqual(pujas["puja_maxima"], 8_000_000)

    def test_smart_supera_en_un_decimo_al_rival_con_menos_caja(self) -> None:
        pujas = calcular_pujas(
            1_000_000,
            0,
            5_000_000,
            tu_saldo=3_000_000,
            rivales=[{"saldo": 1_000_000, "posiciones": ["MC"]}, {"saldo": 9_000_000, "posiciones": ["DEL"]}],
            posicion="MC",
        )
        self.assertEqual(pujas["puja_smart"], 1_100_000)

    def test_smart_no_persigue_al_rival_mas_rico(self) -> None:
        pujas = calcular_pujas(
            1_000_000,
            0,
            5_000_000,
            tu_saldo=3_000_000,
            rivales=[{"saldo": 4_000_000, "posiciones": ["MC"]}],
            posicion="MC",
        )
        self.assertEqual(pujas["puja_smart"], 1_050_000)
        self.assertLessEqual(pujas["puja_smart"], pujas["puja_maxima"])


class PlanFichajesTests(unittest.TestCase):
    def test_puja_que_caduca_hoy_y_venta_van_en_hoy(self) -> None:
        owned = _once(5.0)
        owned[10]["jornada"] = 1.0
        owned[10]["venta_eur"] = 5_000_000
        mercado = [
            _jugador("estrella", "DEL", 7.0, euros=3_000_000, caduca_hoy=True),
        ]
        plan = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=mercado,
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=1,
            baseline_puntos=5.0 * 10 + 1.0,
        )
        tipos = {(accion["tipo"], accion["momento"]) for accion in plan["acciones"]}
        self.assertIn(("VENDE", "hoy"), tipos)
        self.assertIn(("PUJA", "hoy"), tipos)
        self.assertGreater(plan["mejora_puntos_jornada"], 1.5)
        self.assertEqual(plan["veredicto"], "Hazlo ya")
        self.assertGreaterEqual(plan["nota"], 8)
        self.assertGreaterEqual(plan["saldo_al_final"], 0)

    def test_clausulazo_rentable_queda_para_luego(self) -> None:
        owned = _once(5.0)
        owned[10]["jornada"] = 2.0
        plan = build_plan_fichajes(
            cash=4_000_000,
            owned=owned,
            mercado=[],
            clausulas=[_jugador("clausula", "DEL", 8.0, euros=4_000_000)],
            ratio=2_000_000,
            dias_para_jornada=1,
            baseline_puntos=5.0 * 10 + 2.0,
        )
        self.assertEqual([accion["tipo"] for accion in plan["acciones"]], ["CLAUSULAZO"])
        self.assertEqual(plan["acciones"][0]["momento"], "luego")
        self.assertEqual(plan["mejora_puntos_jornada"], 6.0)

    def test_busca_solo_si_faltan_dos_dias_y_hay_un_hueco(self) -> None:
        owned = []
        for position, count in (("POR", 1), ("DEF", 4), ("MC", 4), ("DEL", 1)):
            for index in range(count):
                owned.append(_jugador(f"{position}-{index}", position, 4.0))
        ratio = 1_000_000
        con_tiempo = build_plan_fichajes(
            cash=5_000_000,
            owned=owned,
            mercado=[],
            clausulas=[],
            ratio=ratio,
            dias_para_jornada=3,
            baseline_puntos=0.0,
        )
        self.assertEqual(con_tiempo["acciones"][0]["tipo"], "BUSCA")
        self.assertEqual(con_tiempo["acciones"][0]["momento"], "luego")
        self.assertIn("BUSCA un ", con_tiempo["acciones"][0]["nombre"])
        self.assertIn(str(BUSCA_PUNTOS), con_tiempo["acciones"][0]["nombre"])
        self.assertEqual(con_tiempo["acciones"][0]["euros"], int(round(BUSCA_PUNTOS * ratio)))
        self.assertEqual(len([accion for accion in con_tiempo["acciones"] if accion["tipo"] == "BUSCA"]), 1)

        sin_tiempo = build_plan_fichajes(
            cash=5_000_000,
            owned=owned,
            mercado=[],
            clausulas=[],
            ratio=ratio,
            dias_para_jornada=1,
            baseline_puntos=0.0,
        )
        self.assertEqual(sin_tiempo["acciones"], [])
        self.assertEqual(sin_tiempo["veredicto"], "Opcional")


class CapaIntegradaTests(unittest.TestCase):
    def test_oferta_war_alta_no_se_acepta_y_el_rival_en_rojo_se_marca(self) -> None:
        ahora = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        xi = []
        for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
            for index in range(count):
                xi.append(
                    {
                        "player_id": f"{position}-{index}",
                        "nickname": f"{position}{index}",
                        "position": position,
                        "jornada_ev": 6.0 if position == "DEL" and index == 0 else 4.0,
                        "points_if_starts": 7.0,
                        "ceiling_points": 14.0 if position == "DEL" and index == 0 else 8.0,
                        "p_titular": 0.9,
                        "market_value": 8_000_000,
                    }
                )
        board = {
            "squads": {
                "squads": [
                    {
                        "team_id": "own",
                        "is_self": True,
                        "manager_name": "Yo",
                        "cash": 2_000_000,
                        "players": [
                            {
                                "player_id": "DEL-0",
                                "nickname": "Nueve",
                                "position": "DEL",
                                "market_value": 8_000_000,
                                "week_points": [8, 7, 9],
                            }
                        ],
                    },
                    {
                        "team_id": "rival",
                        "is_self": False,
                        "manager_name": "Rival Rojo",
                        "cash": -500_000,
                        "players": [
                            {
                                "player_id": "forzado",
                                "nickname": "Forzado",
                                "position": "MC",
                                "market_value": 6_000_000,
                                "jornada_ev": 5.0,
                                "p_titular": 0.8,
                                "price_delta": 400_000,
                                "week_points": [6, 7, 8],
                            }
                        ],
                    },
                ]
            },
            "market": {
                "listings": [
                    {
                        "player_id": "DEL-0",
                        "position": "DEL",
                        "sale_price": 8_000_000,
                        "seller_team_id": "own",
                        "market_value": 8_000_000,
                    }
                ]
            },
            "trends": {"players": []},
            "optimize": {"xi": xi, "benched": [], "excluded": []},
        }
        report = build_strategy(board, now=ahora)
        consejo = report["consejos"]["DEL-0"]
        self.assertFalse(consejo["acepta"])
        self.assertIn("No aceptes", consejo["explicacion"])
        self.assertGreater(report["war"]["DEL-0"], 1.5)
        self.assertIn("forzado", report["forzadas"])
        self.assertTrue(report["ventas_forzadas"][0]["venta_forzada_rival"])
        self.assertEqual(report["capitan_seguro"]["player_id"], "DEL-0")
        self.assertTrue(str(report["previsiones"]["DEL-0"]["prevision_7d_pct"]).endswith("%"))


if __name__ == "__main__":
    unittest.main()

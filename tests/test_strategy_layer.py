"""Ratio de liga, precio a 7 días, WAR, pujas, rivales en negativo y plan.

No toca la red ni el caché. El plan de fichajes es el único que llama al solver.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.engine.auction_intel import calcular_pujas, capitanes, nota_y_veredicto, prima_quemada_mercado
from toolbox.engine.lineup_math import war_del_once
from toolbox.engine.market_predictor import (
    EUROS_POR_PUNTO,
    formatear_pct,
    proyectar_7d,
    ratio_mercado_liga,
    valor_justo_jugador,
)
from toolbox.engine.signing_plan import (
    BUSCA_PUNTOS,
    MAX_VENTAS_TITULARES_SANOS,
    build_plan_fichajes,
    conserva_esqueleto,
    evaluar_patrimonio_clausula,
    factor_peaje,
    penalizacion_por_millon,
)
from toolbox.engine.strategy_layer import _collect, _days_to_kickoff, build_strategy


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

    def test_un_millon_diario_dos_dias_seguidos_se_mantiene_la_semana(self) -> None:
        # El valor justo por puntos está muy por debajo. No puede convertir
        # una racha de ~1 M€/día en 390.000 € al día siguiente.
        precio = 38_865_975
        hoy = 969_556
        ayer = 1_023_041
        previsto = proyectar_7d(precio, hoy, ayer, 5.7, 3_760_000, en_forma=True)
        ritmo = (hoy + ayer) / 2
        esperado = int(round((precio + ritmo * 7) / 10_000)) * 10_000
        self.assertEqual(previsto["valor_en_7d"], esperado)
        self.assertGreater(previsto["valor_en_7d"], 45_000_000)
        self.assertGreater(float(previsto["pct"]), 15)

    def test_un_pico_de_un_dia_no_se_repite_siete_veces(self) -> None:
        precio = 10_000_000
        pico = proyectar_7d(precio, 1_000_000, 50_000, 4.0, 2_000_000, en_forma=True)
        self.assertLess(pico["valor_en_7d"], precio + 1_000_000 * 7)

    def test_ayer_sale_de_la_suma_de_dos_dias_no_de_la_aceleracion(self) -> None:
        board = {
            "trends": {
                "players": [
                    {
                        "player_id": "3077",
                        "position": "MC",
                        "fantasy_price": 38_865_975,
                        "price_delta": 969_556,
                        "ff_price_delta_2": 1_992_597,
                        "acceleration": 20_559,
                        "own_expected_points": 5.7,
                        "p_titular": 0.7,
                        "week_points": [8, 11, 6],
                    }
                ]
            },
            "squads": {"squads": []},
            "market": {"listings": []},
            "optimize": {},
        }
        records = _collect(board, datetime(2026, 11, 3, tzinfo=timezone.utc))
        self.assertEqual(records["3077"]["delta_ayer"], 1_992_597 - 969_556)

    def test_la_actividad_manda_sobre_una_plantilla_atrasada(self) -> None:
        """9 nov: Correia seguía con su dueño y su candado tras ficharlo otro."""
        def jugador(pid: str, clausula: int) -> dict:
            return {"player_id": pid, "position": "DEL", "buyout_clause": clausula, "market_value": clausula,
                    "clause_lock": {"is_locked": True, "local_date": "2026-11-09", "local_time": "14:08"}}

        board = {
            "trends": {"players": []},
            "squads": {"squads": [
                {"team_id": "gon", "manager_name": "Gon", "is_self": False, "players": [jugador("3262", 9_000_000), jugador("1", 5_000_000)]},
                {"team_id": "yo", "manager_name": "Yo", "is_self": True, "players": [jugador("2", 4_000_000)]},
            ]},
            "needs": {"ledgers": [
                {"team_id": "gon", "manager_name": "Gon", "events": [{"kind": "buy", "player_id": "3262", "amount_eur": 6_250_000, "at": "2026-10-26T14:08:31+01:00"}]},
                {"team_id": "pablo", "manager_name": "Pablo", "events": [{"kind": "clause", "player_id": "3262", "amount_eur": 12_500_000, "at": "2026-11-09T11:03:32+01:00"}]},
                {"team_id": "yo", "manager_name": "Yo", "events": [{"kind": "clause", "player_id": "1", "amount_eur": 5_000_000, "at": "2026-11-09T12:00:00+01:00"}]},
            ]},
            "market": {"listings": []},
            "optimize": {},
        }
        records = _collect(board, datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
        self.assertEqual(records["3262"]["team_id"], "pablo")
        self.assertEqual(records["3262"]["manager"], "Pablo")
        self.assertIsNone(records["3262"]["clause"])
        self.assertIsNone(records["3262"]["clause_lock"])
        self.assertTrue(records["1"]["is_self"])
        self.assertIsNone(records["1"]["clause"])
        self.assertEqual(records["2"]["clause"], 4_000_000)

    def test_el_porcentaje_lleva_signo_y_un_decimal(self) -> None:
        self.assertEqual(formatear_pct(10.94), "+10.9%")
        self.assertEqual(formatear_pct(-2.14), "-2.1%")
        self.assertEqual(formatear_pct(0.0), "0.0%")


class WarYCapitanTests(unittest.TestCase):
    def test_sin_suplente_se_pierden_sus_puntos_no_el_once_entero(self) -> None:
        xi = _once(5.0)
        perdidas = war_del_once(xi, [])
        self.assertEqual(perdidas["POR-0"], 5.0)
        self.assertEqual(perdidas["DEL-2"], 5.0)

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
        caps = capitanes(xi, activo=True)
        self.assertEqual(caps["capitan_seguro"]["player_id"], "DEL-2")
        self.assertEqual(caps["capitan_remontada"]["player_id"], "DEL-1")
        apagado = capitanes(xi)
        self.assertIsNone(apagado["capitan_seguro"])
        self.assertIsNone(apagado["capitan_remontada"])

    def test_nota_y_veredicto(self) -> None:
        self.assertEqual(nota_y_veredicto(0.2, [{"momento": "luego"}]), (1, "Opcional"))
        self.assertEqual(nota_y_veredicto(0.5, [{"momento": "luego"}]), (5, "Recomendable"))
        self.assertEqual(nota_y_veredicto(0.9, [{"momento": "hoy"}]), (8, "Hazlo ya"))
        self.assertEqual(nota_y_veredicto(0.0, []), (0, "Opcional"))


class PujaYForzadaTests(unittest.TestCase):
    def test_recomendada_suma_la_subida_de_hoy_y_el_techo_es_dinamico(self) -> None:
        pujas = calcular_pujas(10_000_000, 200_000, 8_000_000, tu_saldo=20_000_000, rivales=[], posicion="MC")
        self.assertEqual(pujas["puja_recomendada"], 10_670_000)
        # Sin previsión ni dificultad: prima base del +15 %, no el valor justo.
        self.assertEqual(pujas["puja_maxima"], 11_500_000)
        con_revalorizacion = calcular_pujas(
            10_000_000,
            0,
            8_000_000,
            tu_saldo=20_000_000,
            rivales=[],
            posicion="MC",
            prevision_7d_pct=23.2,
            dificultad="facil",
        )
        # 1,15 + 0,55·0,232 + 0,02 = 1,2976 → 12.980.000, por debajo del cap +30 %.
        self.assertEqual(con_revalorizacion["puja_maxima"], 12_980_000)

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
        self.assertIn(("PUJA", "hoy"), tipos)
        self.assertIn(("ESCAPARATE", "hoy"), tipos)
        self.assertIn(("VENDE", "condicional"), tipos)
        self.assertNotIn("VENDER HOY", [accion["tipo"] for accion in plan["acciones"]])
        self.assertTrue(any(accion["detalle"].startswith("PUJAR POR estrella") for accion in plan["acciones"] if accion["tipo"] == "PUJA"))
        self.assertTrue(any("PONER EN ESCAPARATE a DEL-2" in accion["detalle"] for accion in plan["acciones"]))
        self.assertTrue(any("SOLO SI GANAS LA PUJA DE estrella" in accion["detalle"] for accion in plan["acciones"]))
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
        self.assertEqual(plan["acciones"][0]["mejora_neta"], 6.0)
        # «Después» no entra en el encabezado: el once de hoy no cambia.
        self.assertEqual(plan["mejora_puntos_jornada"], 0.0)

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


class LiquidezTests(unittest.TestCase):
    def _plan(self, *, dias: float, cash: int, mercado: list[dict], owned: list[dict] | None = None, baseline: float | None = None):
        plantilla = owned if owned is not None else _once(5.0)
        base = 5.0 * 11 if baseline is None else baseline
        return build_plan_fichajes(
            cash=cash,
            owned=plantilla,
            mercado=mercado,
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=dias,
            baseline_puntos=base,
        )

    def test_el_lunes_cada_millon_exige_0_2_puntos_y_el_viernes_cero(self) -> None:
        self.assertAlmostEqual(penalizacion_por_millon(4), 0.2, places=6)
        self.assertAlmostEqual(penalizacion_por_millon(7), 0.35, places=6)
        self.assertAlmostEqual(penalizacion_por_millon(2), 0.1, places=6)
        self.assertEqual(penalizacion_por_millon(1), 0.0)
        self.assertEqual(penalizacion_por_millon(0), 0.0)
        self.assertEqual(penalizacion_por_millon(None), 0.0)

    def test_mejora_marginal_y_cara_se_queda_en_el_radar_si_quedan_dias(self) -> None:
        mercado = [_jugador("lateral", "DEL", 5.5, euros=3_000_000)]
        lunes = self._plan(dias=4, cash=3_000_000, mercado=mercado)
        self.assertEqual(lunes["acciones"], [])
        self.assertEqual(lunes["saldo_al_final"], 3_000_000)
        self.assertEqual(lunes["modo_liquidez"], "VENTANA")
        self.assertAlmostEqual(lunes["penalizacion_liquidez"], 0.2, places=4)
        self.assertEqual(lunes["en_radar"][0]["impulso"], "HOLD")
        self.assertIn("En el radar - No pujar hoy", lunes["en_radar"][0]["detalle"])

        viernes = self._plan(dias=0, cash=3_000_000, mercado=mercado)
        self.assertEqual(viernes["modo_liquidez"], "ALL-IN")
        self.assertEqual([accion["tipo"] for accion in viernes["acciones"]], ["PUJA"])
        self.assertEqual(viernes["acciones"][0]["impulso"], "ALL-IN")
        self.assertEqual(viernes["acciones"][0]["momento"], "luego")
        self.assertEqual(viernes["acciones"][0]["mejora_neta"], 0.5)
        self.assertEqual(viernes["en_radar"], [])
        self.assertEqual(viernes["mejora_puntos_jornada"], 0.0)

    def test_un_millon_que_no_rinde_el_peaje_se_queda_en_caja(self) -> None:
        # +1,0 xP por 8 M€. El lunes el peaje es 1,6 puntos: no se gasta.
        mercado = [_jugador("medio", "DEL", 6.0, euros=8_000_000)]
        lunes = self._plan(dias=4, cash=8_000_000, mercado=mercado)
        self.assertEqual(lunes["acciones"], [])
        self.assertEqual(lunes["en_radar"], [])
        self.assertEqual(lunes["saldo_al_final"], 8_000_000)

        viernes = self._plan(dias=0, cash=8_000_000, mercado=mercado)
        self.assertEqual(viernes["acciones"][0]["tipo"], "PUJA")
        self.assertEqual(viernes["acciones"][0]["momento"], "luego")
        self.assertEqual(viernes["acciones"][0]["mejora_neta"], 1.0)
        self.assertEqual(viernes["mejora_puntos_jornada"], 0.0)
        self.assertEqual(viernes["saldo_al_final"], 0)

    def test_must_buy_se_ejecuta_el_lunes_aunque_el_peaje_se_lo_comeria(self) -> None:
        # +2,1 xP por 15 M€. Sin exención el peaje (3,0) lo descartaría.
        mercado = [_jugador("nueve", "DEL", 7.1, euros=15_000_000)]
        plan = self._plan(dias=4, cash=15_000_000, mercado=mercado)
        self.assertEqual(plan["acciones"][0]["tipo"], "PUJA")
        self.assertEqual(plan["acciones"][0]["impulso"], "MUST-BUY")
        self.assertEqual(plan["acciones"][0]["momento"], "hoy")
        self.assertEqual(plan["mejora_puntos_jornada"], 2.1)
        self.assertEqual(plan["veredicto"], "Hazlo ya")
        self.assertEqual(plan["saldo_al_final"], 0)

    def test_no_vende_a_principios_de_semana_para_un_fichaje_normal(self) -> None:
        owned = _once(5.0)
        owned[10]["jornada"] = 4.0
        owned[10]["venta_eur"] = 6_000_000
        owned[10]["pct"] = 1.0
        mercado = [_jugador("repuesto", "DEL", 5.5, euros=4_000_000)]
        plan = self._plan(dias=4, cash=0, mercado=mercado, owned=owned, baseline=5.0 * 10 + 4.0)
        self.assertEqual([accion["tipo"] for accion in plan["acciones"]], ["ESCAPARATE"])
        self.assertIn("no aceptes hasta el jueves/viernes mientras sube", plan["acciones"][0]["detalle"])
        self.assertNotIn("VENDER HOY", [accion["tipo"] for accion in plan["acciones"]])
        self.assertEqual(plan["saldo_al_final"], 0)

    def test_vende_si_el_precio_se_desploma_o_si_financia_un_must_buy(self) -> None:
        owned = _once(5.0)
        owned[10]["jornada"] = 4.0
        owned[10]["venta_eur"] = 6_000_000
        owned[10]["pct"] = -4.0
        owned[10]["tiene_oferta_laliga"] = True
        caida = self._plan(
            dias=4,
            cash=0,
            mercado=[_jugador("repuesto", "DEL", 5.5, euros=4_000_000)],
            owned=owned,
            baseline=5.0 * 10 + 4.0,
        )
        tipos = {(accion["tipo"], accion["momento"]) for accion in caida["acciones"]}
        self.assertNotIn(("VENDER HOY", "hoy"), tipos)
        self.assertIn(("VENDE", "condicional"), tipos)
        self.assertIn(("ESCAPARATE", "hoy"), tipos)
        self.assertIn(("PUJA", "hoy"), tipos)
        self.assertTrue(any("SOLO SI GANAS LA PUJA" in accion["detalle"] for accion in caida["acciones"]))
        self.assertGreater(caida["saldo_al_final"], 0)

        rico = _once(5.0)
        rico[10]["venta_eur"] = 8_000_000
        rico[10]["pct"] = 0.0
        rico[10]["tiene_oferta_laliga"] = True
        must = self._plan(
            dias=4,
            cash=1_000_000,
            mercado=[_jugador("estrella", "DEL", 8.0, euros=6_000_000)],
            owned=rico,
            baseline=5.0 * 11,
        )
        self.assertNotIn("VENDER HOY", [accion["tipo"] for accion in must["acciones"]])
        self.assertIn("VENDE", [accion["tipo"] for accion in must["acciones"]])
        puja = next(accion for accion in must["acciones"] if accion["tipo"] == "PUJA")
        self.assertEqual(puja["impulso"], "MUST-BUY")
        self.assertEqual(puja["momento"], "hoy")
        self.assertTrue(puja["detalle"].startswith("PUJAR POR estrella"))
        self.assertTrue(any("Must-buy" in accion["detalle"] for accion in must["acciones"] if accion["tipo"] == "PUJA"))
        self.assertTrue(any("SOLO SI GANAS LA PUJA DE estrella" in accion["detalle"] for accion in must["acciones"]))

        sin_oferta = _once(5.0)
        sin_oferta[10]["venta_eur"] = 8_000_000
        sin_oferta[10]["pct"] = 0.0
        espera = self._plan(
            dias=4,
            cash=1_000_000,
            mercado=[_jugador("estrella", "DEL", 8.0, euros=6_000_000)],
            owned=sin_oferta,
            baseline=5.0 * 11,
        )
        self.assertEqual([accion["tipo"] for accion in espera["acciones"]], ["ESCAPARATE"])
        self.assertNotIn("PUJA", [accion["tipo"] for accion in espera["acciones"]])
        self.assertEqual(espera["saldo_al_final"], 1_000_000)

        cabe = self._plan(
            dias=4,
            cash=6_000_000,
            mercado=[_jugador("estrella", "DEL", 8.0, euros=6_000_000)],
            owned=rico,
        )
        self.assertEqual([accion["tipo"] for accion in cabe["acciones"]], ["PUJA"])
        self.assertEqual(cabe["saldo_al_final"], 0)

    def test_chollo_de_banquillo_va_al_trading_desk_no_al_once(self) -> None:
        mercado = [_jugador("billete", "DEL", 3.0, euros=1_000_000, pct=16.0)]
        plan = self._plan(dias=4, cash=4_000_000, mercado=mercado)
        self.assertEqual(plan["acciones"], [])
        self.assertEqual(plan["mejora_puntos_jornada"], 0.0)
        self.assertEqual(plan["saldo_al_final"], 4_000_000)
        self.assertNotEqual(plan["veredicto"], "Hazlo ya")
        self.assertNotIn("billete", {fila.get("player_id") for fila in plan["once"]})
        operaciones = plan["trading"]["operaciones"]
        self.assertEqual([op["player_id"] for op in operaciones], ["billete"])
        self.assertEqual(operaciones[0]["etiqueta"], "COMPRAR PARA TRADING")
        self.assertGreater(operaciones[0]["ganancia_esperada"], 0)

        tarde = self._plan(dias=1, cash=4_000_000, mercado=mercado)
        self.assertEqual(tarde["acciones"], [])
        self.assertEqual(tarde["saldo_al_final"], 4_000_000)
        self.assertEqual(tarde["trading"]["operaciones"], [])

    def test_alerta_bajada_queda_fuera_del_trading_aunque_suba(self) -> None:
        mercado = [_jugador("nino", "DEL", 3.0, euros=1_000_000, pct=16.0, af_alerta_bajada=True)]
        plan = self._plan(dias=4, cash=4_000_000, mercado=mercado)
        self.assertEqual(plan["acciones"], [])
        self.assertEqual(plan["trading"]["operaciones"], [])

    def test_la_alerta_de_bajada_viaja_desde_trends(self) -> None:
        records = _collect(
            {
                "trends": {
                    "players": [
                        {
                            "player_id": "nino",
                            "name": "Fer Niño",
                            "position": "DEL",
                            "af_alerta_bajada": True,
                        }
                    ]
                }
            },
            datetime(2026, 11, 3, tzinfo=timezone.utc),
        )
        self.assertIs(records["nino"]["af_alerta_bajada"], True)

    def test_el_factor_de_peaje_es_continuo_y_decrece_con_la_mejora(self) -> None:
        self.assertAlmostEqual(factor_peaje(0.4), 0.985, places=3)
        self.assertAlmostEqual(factor_peaje(1.6), 0.5, places=6)
        self.assertAlmostEqual(factor_peaje(2.5), 0.04, places=2)
        # Sin salto en el antiguo umbral de 2,0 xP: 0,06 xP de ruido mueve el peaje un 5 %, no un 100 %.
        self.assertLess(abs(factor_peaje(1.95) - factor_peaje(2.01)), 0.06)
        self.assertEqual(factor_peaje(None), 1.0)
        self.assertEqual(factor_peaje(float("nan")), 1.0)

    def test_la_revalorizacion_y_la_rotacion_bajan_el_peaje(self) -> None:
        # +1,2 xP por 7,7 M€. Con psi(1,2)=0,80 el lunes pide 1,23 pts y lo descarta.
        # Con un +8 % a 7 días, hasta el viernes solo se bloquean 7,35 M€ (1,18 pts) y entra.
        caro = [_jugador("nueve", "DEL", 6.2, euros=7_700_000)]
        sin_subida = self._plan(dias=4, cash=7_700_000, mercado=caro)
        self.assertEqual(sin_subida["acciones"], [])
        self.assertEqual(sin_subida["saldo_al_final"], 7_700_000)

        con_subida = [_jugador("nueve", "DEL", 6.2, euros=7_700_000, valor=7_700_000, pct=8.0)]
        plan = self._plan(dias=4, cash=7_700_000, mercado=con_subida)
        self.assertEqual(plan["acciones"][0]["tipo"], "PUJA")
        self.assertEqual(plan["acciones"][0]["momento"], "luego")
        self.assertEqual(plan["acciones"][0]["mejora_neta"], 1.2)
        self.assertEqual(plan["mejora_puntos_jornada"], 0.0)
        self.assertEqual(plan["saldo_al_final"], 0)

        # La misma mejora de +1,0 por 8 M€ no pasa el peaje en bruto (1,6 pts).
        # Pagada con una venta que ya tiene oferta, el drenaje neto es cero.
        owned = _once(5.0)
        owned[10]["venta_eur"] = 8_000_000
        owned[10]["pct"] = -4.0
        owned[10]["tiene_oferta_laliga"] = True
        rotacion = self._plan(
            dias=4,
            cash=0,
            mercado=[_jugador("relevo", "DEL", 6.0, euros=8_000_000)],
            owned=owned,
            baseline=55.0,
        )
        tipos = [accion["tipo"] for accion in rotacion["acciones"]]
        self.assertNotIn("VENDER HOY", tipos)
        self.assertIn("VENDE", tipos)
        self.assertIn("PUJA", tipos)
        self.assertIn("ESCAPARATE", tipos)
        self.assertTrue(any(accion["momento"] == "condicional" for accion in rotacion["acciones"] if accion["tipo"] == "VENDE"))
        puja_rotacion = next(accion for accion in rotacion["acciones"] if accion["tipo"] == "PUJA")
        self.assertEqual(puja_rotacion["momento"], "hoy")
        self.assertEqual(puja_rotacion["mejora_neta"], 1.0)
        self.assertEqual(rotacion["mejora_puntos_jornada"], 1.0)
        self.assertEqual(rotacion["saldo_al_final"], 0)

    def test_el_chollo_de_banquillo_no_se_come_la_caja_del_once(self) -> None:
        owned = []
        for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 2)):
            for index in range(count):
                owned.append(_jugador(f"{position}-{index}", position, 4.0))
        chollo = [_jugador("suplente", "POR", 1.0, euros=1_000_000, pct=20.0)]
        justo = build_plan_fichajes(
            cash=4_700_000,
            owned=owned,
            mercado=chollo,
            clausulas=[],
            ratio=1_000_000,
            dias_para_jornada=4,
            baseline_puntos=0.0,
        )
        self.assertTrue(any(accion["tipo"] == "BUSCA" for accion in justo["acciones"]))
        self.assertFalse(any(accion.get("impulso") == "CHOLLO" for accion in justo["acciones"]))
        self.assertEqual(justo["saldo_al_final"], 0)

        holgado = build_plan_fichajes(
            cash=5_700_000,
            owned=owned,
            mercado=chollo,
            clausulas=[],
            ratio=1_000_000,
            dias_para_jornada=4,
            baseline_puntos=0.0,
        )
        # El once no gasta en el chollo: la caja sobrante se la queda el trading desk.
        self.assertFalse(any(accion.get("impulso") == "CHOLLO" for accion in holgado["acciones"]))
        self.assertEqual(holgado["saldo_al_final"], 1_000_000)
        self.assertEqual([op["player_id"] for op in holgado["trading"]["operaciones"]], ["suplente"])
        self.assertEqual(holgado["trading"]["usa_deuda"], 0)


def _reales_tras_ventas_de_hoy(plan: dict, owned: list[dict]) -> int:
    """Cuerpos con nombre si se ejecutan solo las ventas de hoy y los clausulazos."""
    ventas = {
        accion["player_id"]
        for accion in plan["acciones"]
        if accion.get("tipo") in {"VENDE", "VENDER HOY"} and accion.get("momento") == "hoy" and accion.get("player_id")
    }
    clausulas = {
        accion["player_id"]
        for accion in plan["acciones"]
        if accion.get("tipo") == "CLAUSULAZO" and accion.get("player_id")
    }
    return len(owned) - len(ventas) + len(clausulas)


class ProteccionPatrimonioTests(unittest.TestCase):
    def test_la_formula_de_prima_quemada(self) -> None:
        caro = evaluar_patrimonio_clausula({"euros": 8_000_000, "valor": 4_000_000, "pct": 0})
        self.assertEqual(caro["sobreprecio_bruto"], 4_000_000)
        self.assertEqual(caro["ratio_clausula"], 2.0)
        self.assertEqual(caro["subida_7d_euros"], 0)
        self.assertEqual(caro["prima_quemada_neta"], 4_000_000)
        self.assertTrue(caro["descartar"])

        cubierto = evaluar_patrimonio_clausula({"euros": 8_000_000, "valor": 4_000_000, "pct": 60})
        self.assertEqual(cubierto["subida_7d_euros"], 2_400_000)
        self.assertEqual(cubierto["prima_quemada_neta"], 1_600_000)
        self.assertFalse(cubierto["descartar"])

        justo = evaluar_patrimonio_clausula({"euros": 13_500_000, "valor": 10_000_000, "pct": 0})
        self.assertEqual(justo["ratio_clausula"], 1.35)
        self.assertEqual(justo["prima_quemada_neta"], 3_500_000)
        self.assertFalse(justo["descartar"])

    def test_no_paga_8m_por_un_jugador_de_4m(self) -> None:
        owned = _once(5.0)
        plan = build_plan_fichajes(
            cash=8_000_000,
            owned=owned,
            mercado=[],
            clausulas=[_jugador("caro", "DEL", 12.0, euros=8_000_000, valor=4_000_000, pct=0)],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual(plan["acciones"], [])
        self.assertEqual(plan["saldo_al_final"], 8_000_000)

        # La subida a 7 días cubre el 60 % del sobreprecio: el clausulazo puede entrar.
        con_subida = build_plan_fichajes(
            cash=8_000_000,
            owned=owned,
            mercado=[],
            clausulas=[_jugador("caro", "DEL", 12.0, euros=8_000_000, valor=4_000_000, pct=70)],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual([accion["tipo"] for accion in con_subida["acciones"]], ["CLAUSULAZO"])
        self.assertIn("Prima quemada", con_subida["acciones"][0]["detalle"])

    def test_prima_de_mas_de_3_5m_en_valor_medio_se_descarta_y_en_una_estrella_no(self) -> None:
        # 12 M€ de valor, cláusula a +35 % exacto: prima 4,2 M€ y valor por debajo de 15 M€.
        medio = evaluar_patrimonio_clausula({"euros": 16_200_000, "valor": 12_000_000, "pct": 0})
        self.assertGreater(medio["prima_quemada_neta"], 3_500_000)
        self.assertTrue(medio["descartar"])
        owned = _once(5.0)
        plan = build_plan_fichajes(
            cash=16_200_000,
            owned=owned,
            mercado=[],
            clausulas=[_jugador("medio", "DEL", 12.0, euros=16_200_000, valor=12_000_000)],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual(plan["acciones"], [])

        # Misma prima, pero el jugador ya vale 20 M€: el filtro de 3,5 M€ no le aplica.
        estrella = evaluar_patrimonio_clausula({"euros": 27_000_000, "valor": 20_000_000, "pct": 0})
        self.assertGreater(estrella["prima_quemada_neta"], 3_500_000)
        self.assertFalse(estrella["descartar"])
        paga = build_plan_fichajes(
            cash=27_000_000,
            owned=owned,
            mercado=[],
            clausulas=[_jugador("estrella", "DEL", 12.0, euros=27_000_000, valor=20_000_000)],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual(paga["acciones"][0]["tipo"], "CLAUSULAZO")

    def test_la_prima_quemada_pesa_en_el_solver(self) -> None:
        # +1,0 xP por una prima de 3 M€. El castigo es 1,35 puntos y el clausulazo no entra.
        owned = _once(5.0)
        plan = build_plan_fichajes(
            cash=13_000_000,
            owned=owned,
            mercado=[],
            clausulas=[_jugador("caro", "DEL", 6.0, euros=13_000_000, valor=10_000_000, pct=0)],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual(plan["acciones"], [])
        self.assertEqual(plan["saldo_al_final"], 13_000_000)

        justo = build_plan_fichajes(
            cash=10_000_000,
            owned=owned,
            mercado=[],
            clausulas=[_jugador("justo", "DEL", 6.0, euros=10_000_000, valor=10_000_000)],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual(justo["acciones"][0]["tipo"], "CLAUSULAZO")
        self.assertNotIn("Prima quemada", justo["acciones"][0]["detalle"])

    def test_no_busca_un_def_si_eso_obliga_a_vender_a_un_titular(self) -> None:
        owned = _once(4.0)
        owned[10]["jornada"] = 1.0
        owned[10]["venta_eur"] = 8_000_000
        owned[10]["tiene_oferta_laliga"] = True
        owned[10]["pct"] = -5.0
        plan = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=[],
            clausulas=[],
            ratio=1_000_000,
            dias_para_jornada=4,
            baseline_puntos=41.0,
        )
        self.assertFalse(any(accion["tipo"] == "BUSCA" for accion in plan["acciones"]))
        self.assertGreaterEqual(_reales_tras_ventas_de_hoy(plan, owned), 11)

    def test_vender_hoy_solo_si_es_suplente_o_paga_un_clausulazo_o_hay_deuda(self) -> None:
        owned = _once(5.0)
        owned.append(_jugador("suplente", "DEL", 1.0, venta_eur=5_000_000, pct=-4.0, tiene_oferta_laliga=True))
        suplente = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=[_jugador("repuesto", "DEL", 6.5, euros=4_000_000)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=4,
            baseline_puntos=55.0,
        )
        venta = next(accion for accion in suplente["acciones"] if accion["player_id"] == "suplente")
        self.assertEqual((venta["tipo"], venta["momento"]), ("VENDER HOY", "hoy"))
        self.assertIn("3 %", venta["detalle"])
        self.assertGreaterEqual(_reales_tras_ventas_de_hoy(suplente, owned), 11)

        plantilla = _once(5.0)
        plantilla[10]["jornada"] = 2.0
        plantilla[10]["venta_eur"] = 6_000_000
        plantilla[10]["pct"] = 0.0
        plantilla[10]["tiene_oferta_laliga"] = True
        clausula = build_plan_fichajes(
            cash=1_000_000,
            owned=plantilla,
            mercado=[],
            clausulas=[_jugador("fijo", "DEL", 8.0, euros=6_000_000, valor=6_000_000)],
            ratio=2_000_000,
            dias_para_jornada=4,
            baseline_puntos=52.0,
        )
        self.assertIn(("VENDER HOY", "hoy"), {(accion["tipo"], accion["momento"]) for accion in clausula["acciones"]})
        self.assertTrue(any("clausulazo" in accion["detalle"] for accion in clausula["acciones"] if accion["tipo"] == "VENDER HOY"))
        self.assertGreaterEqual(_reales_tras_ventas_de_hoy(clausula, plantilla), 11)

        deuda_owned = _once(5.0)
        deuda_owned.append(_jugador("banco", "MC", 1.0, venta_eur=1_000_000, pct=2.0))
        deuda = build_plan_fichajes(
            cash=-500_000,
            owned=deuda_owned,
            mercado=[],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=4,
            baseline_puntos=55.0,
        )
        self.assertTrue(any(accion["tipo"] == "VENDER HOY" and accion["player_id"] == "banco" for accion in deuda["acciones"]))
        self.assertTrue(any("negativo" in accion["detalle"] for accion in deuda["acciones"] if accion["tipo"] == "VENDER HOY"))
        self.assertGreaterEqual(deuda["saldo_al_final"], 0)
        self.assertGreaterEqual(_reales_tras_ventas_de_hoy(deuda, deuda_owned), 11)

    def test_como_maximo_dos_titulares_sanos_y_las_bajas_no_cuentan(self) -> None:
        owned = _once(5.0)
        for row in owned:
            row["venta_eur"] = 2_000_000
            row["p_titular"] = 0.9
            row["tiene_oferta_laliga"] = True
        for index, position in enumerate(("DEF", "MC", "DEL")):
            owned.append(
                _jugador(
                    f"baja-{index}",
                    position,
                    1.0,
                    venta_eur=2_000_000,
                    p_titular=0.1,
                    tiene_oferta_laliga=True,
                    pct=0.0,
                )
            )
        mercado = [
            _jugador(f"nuevo-{position}-{index}", position, 9.0, euros=2_000_000)
            for position, count in (("DEF", 2), ("MC", 2), ("DEL", 1))
            for index in range(count)
        ]
        plan = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=mercado,
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=4,
            baseline_puntos=55.0,
        )
        ventas = [accion["player_id"] for accion in plan["acciones"] if accion["tipo"] in {"VENDE", "VENDER HOY"}]
        sanos = [player_id for player_id in ventas if player_id and not str(player_id).startswith("baja-")]
        bajas = [player_id for player_id in ventas if str(player_id).startswith("baja-")]
        self.assertEqual(len(sanos), MAX_VENTAS_TITULARES_SANOS)
        self.assertEqual(len(bajas), 3)
        self.assertGreater(plan["mejora_puntos_jornada"], 10)
        self.assertFalse(any(accion["tipo"] == "BUSCA" for accion in plan["acciones"]))
        self.assertGreaterEqual(_reales_tras_ventas_de_hoy(plan, owned), 11)


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
        self.assertIsNone(report["capitan_seguro"])
        self.assertIsNone(report["capitan_remontada"])
        self.assertTrue(str(report["previsiones"]["DEL-0"]["prevision_7d_pct"]).endswith("%"))

    def test_sin_kickoff_el_reloj_cae_en_el_viernes_a_las_21(self) -> None:
        # Miércoles 4 nov 2026, 19:00 en Madrid (18:00 UTC). El viernes 6 a las 21:00
        # son 50 horas después. No puede salir None: eso apagaba el peaje.
        ahora = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)
        dias = _days_to_kickoff(None, ahora)
        self.assertIsNotNone(dias)
        self.assertAlmostEqual(dias, 50 / 24, places=4)
        self.assertGreater(dias, 2.0)
        # Un silbato real no se sustituye por el viernes.
        con_partido = _days_to_kickoff(
            {"players": [{"player_id": "1", "club": "A", "fixture": {"kickoff": "2026-11-08T15:00:00+00:00"}}]},
            ahora,
        )
        self.assertAlmostEqual(con_partido, 4.0 - 3 / 24, places=3)


class PrimaMercadoYEsqueletoTests(unittest.TestCase):
    def test_la_prima_de_mercado_crece_si_el_precio_va_a_bajar(self) -> None:
        # Kike: 20,86 sobre 19,03 y una subida del 30,9 % cubre el sobreprecio.
        self.assertEqual(prima_quemada_mercado(20_860_000, 19_027_871, 30.91), 0.0)
        # 2 M€ de más y el valor baja un 10 %: se castigan 3 M€.
        self.assertEqual(prima_quemada_mercado(12_000_000, 10_000_000, -10), 3_000_000)
        self.assertEqual(prima_quemada_mercado(12_000_000, None, 0), 0.0)

    def test_el_solver_rechaza_quemar_2m_por_un_punto_si_el_jugador_baja(self) -> None:
        owned = _once(5.0)
        plan = build_plan_fichajes(
            cash=12_000_000,
            owned=owned,
            mercado=[_jugador("caro", "DEL", 6.0, euros=12_000_000, valor=10_000_000, pct=-10)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual(plan["acciones"], [])
        self.assertEqual(plan["saldo_al_final"], 12_000_000)

        cubierto = build_plan_fichajes(
            cash=12_000_000,
            owned=owned,
            mercado=[_jugador("justo", "DEL", 6.0, euros=12_000_000, valor=10_000_000, pct=30)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=55.0,
        )
        self.assertEqual(cubierto["acciones"][0]["tipo"], "PUJA")
        self.assertNotIn("Prima quemada", cubierto["acciones"][0]["detalle"])

    def test_el_plan_prudente_no_vende_el_ultimo_defensa(self) -> None:
        # 3 defensas y un medio de más: la caja solo llega vendiendo, y el
        # único cuerpo que sobra es un medio. Vender un defensa dejaría el
        # once pendiente de ganar la puja.
        owned = []
        for position, count in (("POR", 1), ("DEF", 3), ("MC", 6), ("DEL", 2)):
            for index in range(count):
                owned.append(
                    _jugador(
                        f"{position}-{index}",
                        position,
                        4.0,
                        venta_eur=8_000_000,
                        valor=8_000_000,
                        tiene_oferta_laliga=True,
                        pct=-5.0,
                    )
                )
        self.assertFalse(conserva_esqueleto(owned, {"DEF-0", "DEF-1", "DEF-2"}))
        plan = build_plan_fichajes(
            cash=1_000_000,
            owned=owned,
            mercado=[_jugador("lateral", "DEF", 9.0, euros=8_000_000, valor=8_000_000)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=4,
            baseline_puntos=48.0,
            permitir_condicionales=False,
        )
        vendidos = {
            accion["player_id"]
            for accion in plan["acciones"]
            if accion.get("tipo") in {"VENDE", "VENDER HOY"}
        }
        self.assertTrue(conserva_esqueleto(owned, vendidos))
        self.assertFalse(any(str(player_id).startswith("DEF-") for player_id in vendidos))
        self.assertTrue(any(accion["tipo"] == "PUJA" and accion["player_id"] == "lateral" for accion in plan["acciones"]))


if __name__ == "__main__":
    unittest.main()

"""Coherencia del plan (nov 2026): freno a vender titulares, jugador #12, Mercado
con la voz del plan, cláusulas que no blindan ventas y reglas del Marcador."""

from __future__ import annotations

import sqlite3
import time
import unittest

from toolbox.engine.liquidacion import ACCION_MANTENER, PARCHE_VALOR_MAX, plan_liquidacion
from toolbox.engine.signing_plan import UMBRAL_VENTA_TITULAR_XP, build_plan_fichajes
from toolbox.engine.strategy_layer import (
    _no_blindar_ventas_del_plan,
    _unificar_fila_mercado,
    plan_compras,
    plan_ventas,
    puja_unica,
)
from toolbox.marcador import evaluacion_prematura, puntos_definitivos, reparar_historico


def _jugador(player_id: str, position: str, jornada: float, **extra: object) -> dict:
    return {"player_id": player_id, "nombre": player_id, "position": position, "jornada": jornada, "elegible": True, **extra}


def _once(puntos: float = 5.0, **extra: object) -> list[dict]:
    plantilla = []
    for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
        for index in range(count):
            plantilla.append(_jugador(f"{position}-{index}", position, puntos, **extra))
    return plantilla


class FrenoVentaTitularTests(unittest.TestCase):
    def _plan(self, mejora: float) -> dict:
        # Sin caja: para fichar al DEL nuevo hay que vender a un titular consolidado.
        owned = _once(5.0, p_titular=0.85, venta_eur=5_000_000, oferta_laliga=5_000_000, valor=5_000_000)
        mercado = [_jugador("nuevo", "DEL", 5.0 + mejora, euros=5_000_000, futuro=3 * (5.0 + mejora))]
        return build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=mercado,
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=5.0 * 11,
        )

    def _vende(self, plan: dict) -> bool:
        return any(a["tipo"] in {"VENDE", "VENDER HOY"} for a in plan.get("acciones") or [])

    def test_mejora_pequena_no_vende_a_un_titular(self) -> None:
        self.assertFalse(self._vende(self._plan(1.0)))

    def test_mejora_grande_si(self) -> None:
        self.assertTrue(self._vende(self._plan(UMBRAL_VENTA_TITULAR_XP + 1.0)))


class PujaYClausulaALaVezTests(unittest.TestCase):
    def test_no_repite_nombres_de_variables(self) -> None:
        """Una puja y un clausulazo candidatos a la vez: antes ``_c0`` se repetía y CBC fallaba."""
        plan = build_plan_fichajes(
            cash=20_000_000,
            owned=_once(5.0),
            mercado=[_jugador("puja", "DEL", 8.0, euros=5_000_000, futuro=24.0)],
            clausulas=[_jugador("clau", "MC", 8.0, euros=6_000_000, futuro=24.0, valor=5_500_000)],
            ratio=2_000_000,
            dias_para_jornada=0,
            baseline_puntos=5.0 * 11,
        )
        self.assertTrue(plan["ok"])
        self.assertTrue(any(a["tipo"] in {"PUJA", "CLAUSULAZO"} for a in plan["acciones"]))


class ParcheTests(unittest.TestCase):
    def _owned(self) -> list[dict]:
        once = [{**row, "valor": 5_000_000} for row in _once(4.0)]
        return [
            *once,
            {"player_id": "barato", "position": "DEF", "jornada": 1.0, "elegible": True, "valor": 600_000},
            {"player_id": "caro", "position": "MC", "jornada": 1.5, "elegible": True, "valor": 6_000_000},
        ]

    def test_guarda_el_12_barato_si_la_caja_aguanta(self) -> None:
        plan = plan_liquidacion(self._owned(), saldo=100_000, dias_para_jornada=1.0)
        self.assertEqual(plan["parche_id"], "barato")
        acciones = {row["player_id"]: row["accion"] for row in plan["sobrantes"]}
        self.assertEqual(acciones["barato"], ACCION_MANTENER)
        self.assertNotEqual(acciones["caro"], ACCION_MANTENER)

    def test_sin_caja_no_hay_parche(self) -> None:
        plan = plan_liquidacion(self._owned(), saldo=-6_000_000, dias_para_jornada=1.0)
        self.assertIsNone(plan["parche_id"])

    def test_nada_por_debajo_del_tope(self) -> None:
        owned = [{**row, "valor": 5_000_000} for row in _once(4.0)]
        owned.append({"player_id": "medio", "position": "DEF", "jornada": 1.0, "elegible": True, "valor": PARCHE_VALOR_MAX})
        self.assertIsNone(plan_liquidacion(owned, saldo=0, dias_para_jornada=1.0)["parche_id"])


PLAN = {
    "acciones": [
        {"tipo": "PUJA", "momento": "hoy", "player_id": "927", "nombre": "Berenguer", "euros": 27_000_000, "mejora_neta": 1.2},
        {"tipo": "ESCAPARATE", "momento": "hoy", "player_id": "3090", "nombre": "Isco", "euros": 68_000_000},
        {"tipo": "VENDE", "momento": "condicional", "player_id": "3090", "nombre": "Isco", "euros": 68_000_000},
        {"tipo": "PUJA", "momento": "radar", "player_id": "1", "nombre": "Radar", "euros": 1_000_000},
    ],
    "cobertura_pujas": {"pujas": [{"player_id": "927", "euros": 27_000_000, "ventas": [{"player_id": "3090", "euros": 68_000_000}]}]},
}


class MercadoConLaVozDelPlanTests(unittest.TestCase):
    def test_compras_y_ventas_del_plan(self) -> None:
        self.assertEqual(plan_ventas(PLAN), {"3090": "Isco"})
        compras = plan_compras(PLAN)
        self.assertEqual(set(compras), {"927"})
        self.assertEqual(compras["927"]["ventas"], ["Isco"])

    def test_veto_de_caja_pasa_a_pujar_con_la_cifra_del_plan(self) -> None:
        row = {"player_id": "927", "action": "NO", "is_vetoed": True, "reasons": ["negative_cash"], "smart_bid_eur": None}
        _unificar_fila_mercado(row, {"compras_plan": plan_compras(PLAN), "pujas": {}})
        self.assertEqual(row["action"], "PUJAR")
        self.assertEqual(row["puja_unica_eur"], 27_000_000)
        self.assertEqual(row["smart_bid_eur"], 27_000_000)
        self.assertIn("vendiendo a Isco", row["action_reason"])

    def test_veto_por_lesion_se_respeta(self) -> None:
        row = {"player_id": "927", "action": "NO", "is_vetoed": True, "reasons": ["lesionado"]}
        _unificar_fila_mercado(row, {"compras_plan": plan_compras(PLAN), "pujas": {}})
        self.assertEqual(row["action"], "NO")

    def test_fuera_del_plan_la_misma_formula(self) -> None:
        puja = {"puja_recomendada": 5_000_000, "puja_maxima": 6_000_000}
        self.assertEqual(puja_unica(puja, {"sale_price": 4_000_000, "leading_bid": 5_200_000}), 5_200_000)
        self.assertIsNone(puja_unica(puja, {"sale_price": 7_000_000}))
        row = {"player_id": "x", "action": "PUJAR", "smart_bid_eur": 5_500_000, "sale_price": 4_000_000}
        _unificar_fila_mercado(row, {"compras_plan": {}, "pujas": {"x": puja}})
        self.assertEqual(row["smart_bid_eur"], 5_000_000)

    def test_no_blinda_a_quien_el_plan_vende(self) -> None:
        clausulas = {
            "proteger": [
                {"player_id": "3090", "veredicto_codigo": "PROTEGER_YA", "subida_recomendada": {"coste_eur": 4_000_000}, "motivos": []},
                {"player_id": "77", "veredicto_codigo": "PROTEGER_YA", "subida_recomendada": {"coste_eur": 1_000_000}, "motivos": []},
            ],
            "preparar": [{"player_id": "3090"}],
            "radar_anti_robo": [{"player_id": "3090"}],
            "alertas_clausulas": [{"tipo": "escudo", "player_id": "3090"}],
            "resumen": {"coste_proteger_eur": 5_000_000},
        }
        _no_blindar_ventas_del_plan(clausulas, plan_ventas(PLAN), {})
        self.assertEqual(clausulas["proteger"][0]["veredicto_codigo"], "VENDER_ANTES")
        self.assertEqual(clausulas["resumen"]["coste_proteger_eur"], 1_000_000)
        self.assertEqual(clausulas["preparar"], [])
        self.assertEqual(clausulas["radar_anti_robo"], [])
        self.assertEqual(clausulas["alertas_clausulas"], [])


SAQUE = "2026-11-06T20:00:00+00:00"
SAQUE_EPOCH = 1793995200.0


class MarcadorTests(unittest.TestCase):
    def test_puntos_definitivos_a_las_24_horas(self) -> None:
        self.assertFalse(puntos_definitivos(SAQUE, ahora=SAQUE_EPOCH + 2 * 3600))
        self.assertTrue(puntos_definitivos(SAQUE, ahora=SAQUE_EPOCH + 25 * 3600))
        self.assertFalse(puntos_definitivos(None, ahora=time.time()))

    def test_reparar_vacia_prematuros_y_anula_previas_tardias(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """create table matchday_snapshots (jornada_id text, player_id text, kickoff text, stored_at real,
               evaluated_at real, actual_points real, expected_points real, ceiling_points real,
               primary key (jornada_id, player_id))"""
        )
        conn.execute(
            """create table matchday_snapshot_log (jornada_id text, player_id text, snapshot_day text,
               expected_points real, ceiling_points real, stored_at real)"""
        )
        conn.executemany(
            "insert into matchday_snapshots values (?,?,?,?,?,?,?,?)",
            [
                ("12", "kike", SAQUE, SAQUE_EPOCH - 3600, SAQUE_EPOCH + 7200, 0.0, 6.1, 15.0),
                ("12", "sin_saque", None, SAQUE_EPOCH - 3600, SAQUE_EPOCH + 7200, 0.0, 6.8, 13.0),
                ("11", "tarde", SAQUE, SAQUE_EPOCH + 86400, SAQUE_EPOCH + 90000, 9.0, 0.0, 0.0),
                ("11", "con_log", SAQUE, SAQUE_EPOCH + 86400, SAQUE_EPOCH + 90000, 8.0, 0.0, 0.0),
                ("10", "bueno", SAQUE, SAQUE_EPOCH - 3600, SAQUE_EPOCH + 30 * 3600, 7.0, 5.0, 9.0),
            ],
        )
        conn.execute(
            "insert into matchday_snapshot_log values ('11','con_log','2026-11-05',5.5,10.0,?)", (SAQUE_EPOCH - 3600,)
        )
        resumen = reparar_historico(conn)
        filas = {
            pid: (actual, expected)
            for pid, actual, expected in conn.execute("select player_id, actual_points, expected_points from matchday_snapshots")
        }
        self.assertEqual(resumen["prematuras"], 2)
        self.assertIsNone(filas["kike"][0])
        self.assertIsNone(filas["sin_saque"][0])
        self.assertIsNone(filas["tarde"][1])
        self.assertEqual(filas["con_log"][1], 5.5)
        self.assertEqual(filas["bueno"], (7.0, 5.0))
        self.assertEqual(reparar_historico(conn), {"prematuras": 0, "previas_recuperadas": 0, "previas_anuladas": 0})

    def test_evaluacion_prematura(self) -> None:
        self.assertTrue(evaluacion_prematura(SAQUE, SAQUE_EPOCH + 3600))
        self.assertFalse(evaluacion_prematura(SAQUE, SAQUE_EPOCH + 30 * 3600))


class ApercibidoTests(unittest.TestCase):
    def test_apercibido_baja_la_jornada_siguiente(self) -> None:
        from toolbox.matching import normalize_club
        from toolbox.own_intel import apply_own_intel
        from toolbox.understat import FixtureInfo

        def partido(rival: str, casa: bool, siguientes: tuple = ()) -> FixtureInfo:
            return FixtureInfo(rival, None, casa, None, 3, None, None, siguientes)

        def jugador(apercibido: bool) -> dict:
            return {
                "player_id": "2206",
                "position": "DEF",
                "club": "Celta",
                "p_titular": 0.9,
                "sanction": {"on_verge": apercibido},
                "historial": [{"puntos": 6, "minutos": 90, "jornada": j} for j in range(6, 11)],
            }

        fixture = partido("Levante", True, tuple(partido("Getafe", False) for _ in range(3)))
        limpio, aviso = jugador(False), jugador(True)
        for row in (limpio, aviso):
            apply_own_intel([row], histories={}, fixtures_by_club={normalize_club("Celta"): fixture})
        self.assertLess(aviso["own_xp_siguientes"][0], limpio["own_xp_siguientes"][0])
        self.assertEqual(aviso["own_xp_siguientes"][1:], limpio["own_xp_siguientes"][1:])


class BloqueoViernesTests(unittest.TestCase):
    """La alineación se bloquea en el primer partido: con la jornada empezada, el cierre es la siguiente."""

    def _trends(self) -> dict:
        def jugador(pid: str, saque: str, siguientes: list[str]) -> dict:
            return {
                "player_id": pid,
                "club": pid,
                "fixture": {"kickoff": saque},
                "own_calendar": [{"kickoff": saque}, *[{"kickoff": k} for k in siguientes]],
            }

        return {
            "players": [
                jugador("sevilla", "2026-11-21T13:00:00+00:00", ["2026-11-29T14:00:00+00:00"]),
                jugador("alaves", "2026-11-21T13:00:00+00:00", ["2026-11-29T16:00:00+00:00"]),
                jugador("domingo", "2026-11-07T19:00:00+00:00", ["2026-11-21T15:15:00+00:00"]),
                jugador("rival_domingo", "2026-11-07T19:00:00+00:00", ["2026-11-22T15:15:00+00:00"]),
            ]
        }

    def _antes(self) -> dict:
        """Jueves: todos los clubes tienen su próximo partido en la jornada que viene."""
        trends = self._trends()
        for player in trends["players"]:
            if player["club"] in {"sevilla", "alaves"}:
                player["fixture"] = {"kickoff": "2026-11-06T20:00:00+00:00"}
                player["own_calendar"] = [{"kickoff": "2026-11-06T20:00:00+00:00"}, *player["own_calendar"]]
        return trends

    def test_con_la_jornada_en_curso_el_cierre_es_la_siguiente(self) -> None:
        from datetime import datetime, timezone

        from toolbox.engine.strategy_layer import proximo_cierre

        sabado = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(proximo_cierre(self._trends(), sabado).isoformat(), "2026-11-21T13:00:00+00:00")
        jueves = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(proximo_cierre(self._antes(), jueves).isoformat(), "2026-11-06T20:00:00+00:00")
        domingo = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(proximo_cierre(self._trends(), domingo).isoformat(), "2026-11-21T13:00:00+00:00")

    def test_el_partido_bloqueado_cede_su_sitio_a_la_siguiente(self) -> None:
        from datetime import datetime, timezone

        from toolbox.engine.strategy_layer import _saltar_jornada_bloqueada

        records = {
            "a": {"jornada": 4.0, "kickoff": "2026-11-08T15:15:00+00:00", "xp_siguientes": [6.0, 5.0, 5.5]},
            "b": {"jornada": 7.0, "kickoff": "2026-11-21T13:00:00+00:00", "xp_siguientes": [6.0, 6.0, 6.0]},
        }
        _saltar_jornada_bloqueada(records, datetime(2026, 11, 20, 20, tzinfo=timezone.utc))
        self.assertEqual(records["a"]["jornada"], 6.0)
        self.assertEqual(records["a"]["xp_siguientes"], [5.0, 5.5])
        self.assertEqual(records["b"]["jornada"], 7.0)


if __name__ == "__main__":
    unittest.main()

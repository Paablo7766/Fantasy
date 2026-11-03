"""Salida ordenada del #12 en adelante por fases de la semana."""

from __future__ import annotations

import unittest

from toolbox.engine.liquidacion import (
    ACCION_ESCAPARATE,
    ACCION_ESPERAR,
    ACCION_MANTENER,
    ACCION_SIN_OFERTA,
    ACCION_VENDER,
    ETIQUETA_LIQUIDAR,
    FASE_APALANCAMIENTO,
    FASE_ESCAPARATE,
    FASE_LIQUIDACION,
    fase_semana,
    plan_liquidacion,
)


def _once() -> list[dict]:
    """Un 4-4-2 completo: 11 titulares."""
    rows = [{"player_id": "por", "position": "POR", "jornada": 5.0}]
    rows += [{"player_id": f"def{i}", "position": "DEF", "jornada": 4.0} for i in range(4)]
    rows += [{"player_id": f"mc{i}", "position": "MC", "jornada": 4.0} for i in range(4)]
    rows += [{"player_id": f"del{i}", "position": "DEL", "jornada": 4.0} for i in range(2)]
    return [{**row, "elegible": True, "valor": 5_000_000} for row in rows]


def _sobrante(player_id: str, **extra) -> dict:
    return {"player_id": player_id, "position": "MC", "jornada": 1.0, "elegible": True, "valor": 3_000_000, **extra}


class FaseTest(unittest.TestCase):
    def test_fases_por_dias(self) -> None:
        self.assertEqual(fase_semana(4.0), FASE_APALANCAMIENTO)
        self.assertEqual(fase_semana(3.0), FASE_APALANCAMIENTO)
        self.assertEqual(fase_semana(2.5), FASE_ESCAPARATE)
        self.assertEqual(fase_semana(1.5), FASE_ESCAPARATE)
        self.assertEqual(fase_semana(1.0), FASE_LIQUIDACION)
        self.assertIsNone(fase_semana(None))


class PlanLiquidacionTest(unittest.TestCase):
    def test_solo_salen_los_que_no_entran_en_el_once(self) -> None:
        plan = plan_liquidacion([*_once(), _sobrante("extra")], saldo=1_000_000, dias_para_jornada=4.0)
        self.assertEqual([item["player_id"] for item in plan["sobrantes"]], ["extra"])
        self.assertEqual(len(plan["once_ids"]), 11)

    def test_apalancamiento_mantiene_salvo_oferta_que_paga_valor(self) -> None:
        owned = [*_once(), _sobrante("a"), _sobrante("b")]
        plan = plan_liquidacion(owned, saldo=0, dias_para_jornada=4.0, ofertas={"b": 3_100_000})
        acciones = {item["player_id"]: item["accion"] for item in plan["sobrantes"]}
        self.assertEqual(acciones, {"a": ACCION_MANTENER, "b": ACCION_VENDER})

    def test_escaparate_pone_a_la_venta_y_espera(self) -> None:
        owned = [*_once(), _sobrante("fuera"), _sobrante("dentro", en_venta=True)]
        plan = plan_liquidacion(owned, saldo=0, dias_para_jornada=2.0, ofertas={"dentro": 2_900_000})
        acciones = {item["player_id"]: item["accion"] for item in plan["sobrantes"]}
        self.assertEqual(acciones, {"fuera": ACCION_ESCAPARATE, "dentro": ACCION_ESPERAR})

    def test_liquidacion_acepta_la_oferta_que_haya(self) -> None:
        owned = [*_once(), _sobrante("con", en_venta=True), _sobrante("sin", en_venta=True)]
        plan = plan_liquidacion(owned, saldo=-1_000_000, dias_para_jornada=1.0, ofertas={"con": 2_700_000})
        por_id = {item["player_id"]: item for item in plan["sobrantes"]}
        self.assertEqual(por_id["con"]["accion"], ACCION_VENDER)
        self.assertEqual(por_id["con"]["etiqueta"], ETIQUETA_LIQUIDAR)
        self.assertEqual(por_id["sin"]["accion"], ACCION_SIN_OFERTA)
        # Con oferta se cuenta la oferta; sin ella, el valor (o el 90 % en el peor caso).
        self.assertEqual(plan["saldo_tras_liquidar"], -1_000_000 + 2_700_000 + 3_000_000)
        self.assertEqual(plan["saldo_peor_caso"], -1_000_000 + 2_700_000 + 2_700_000)
        self.assertEqual(plan["deficit_eur"], 0)

    def test_deficit_si_ni_vendiendo_todo_llega(self) -> None:
        owned = [*_once(), _sobrante("x")]
        plan = plan_liquidacion(owned, saldo=-10_000_000, dias_para_jornada=1.0)
        self.assertEqual(plan["deficit_eur"], 10_000_000 - 2_700_000)

    def test_cobertura_no_se_vende(self) -> None:
        owned = [*_once(), _sobrante("seguro")]
        plan = plan_liquidacion(owned, saldo=0, dias_para_jornada=1.0, conservar={"seguro"})
        self.assertEqual(plan["sobrantes"][0]["accion"], ACCION_MANTENER)
        self.assertEqual(plan["saldo_tras_liquidar"], 0)

    def test_lesionado_fuera_del_once_sale_primero(self) -> None:
        owned = [*_once(), _sobrante("sube", pct=5.0), _sobrante("roto", elegible=False, pct=5.0), _sobrante("baja", pct=-3.0)]
        plan = plan_liquidacion(owned, saldo=0, dias_para_jornada=1.0)
        self.assertEqual([item["player_id"] for item in plan["sobrantes"]], ["roto", "baja", "sube"])

    def test_sin_reloj_no_hay_plan(self) -> None:
        plan = plan_liquidacion([*_once(), _sobrante("x")], saldo=0, dias_para_jornada=None)
        self.assertFalse(plan["activo"])


if __name__ == "__main__":
    unittest.main()

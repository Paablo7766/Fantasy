"""Parón de selecciones: el crédito del 20 % se usa para pujar hoy, sin vender titulares.

A más de 4,5 días del cierre el saldo puede estar en negativo sin sanción
hasta el saque. El plan lo aprovecha solo para pujas que suben mucho (≥ 12 %
a 7 días) o mejoran el once de verdad (≥ +2,0 xP y sin previsión de bajada),
nunca para cláusulas, y deja dicho cuándo decidir las ventas.
"""

from __future__ import annotations

import unittest

from toolbox.engine.signing_plan import (
    CREDITO_PARON_MEJORA,
    CREDITO_PARON_PCT,
    build_plan_fichajes,
    merece_credito_paron,
)
from toolbox.engine.trading_desk import DEUDA_PCT_EQUIPO

DIAS_PARON = 13.0
VALOR = 10_000_000


def _jugador(player_id: str, position: str, jornada: float, **extra: object) -> dict:
    row = {"player_id": player_id, "nombre": player_id, "position": position, "jornada": jornada, "elegible": True}
    row.update(extra)
    return row


def _plantilla(puntos: float = 3.0) -> list[dict]:
    """Once de 11 con valor conocido (el tope del 20 % lo necesita) y sin oferta de LaLiga."""
    filas = []
    for position, cantidad in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
        for index in range(cantidad):
            filas.append(
                _jugador(
                    f"{position}-{index}",
                    position,
                    puntos,
                    valor=VALOR,
                    venta_eur=VALOR,
                    futuro=3 * puntos,
                    pct=0.0,
                    p_titular=0.9,
                )
            )
    return filas


def _mercado(player_id: str, position: str, jornada: float, euros: int, pct: float | None) -> dict:
    return _jugador(player_id, position, jornada, euros=euros, valor=euros, pct=pct, futuro=3 * jornada)


def _plan(mercado: list[dict], *, dias: float = DIAS_PARON, cash: int = 200_000, clausulas: list[dict] | None = None):
    owned = _plantilla()
    return build_plan_fichajes(
        cash=cash,
        owned=owned,
        mercado=mercado,
        clausulas=clausulas or [],
        ratio=2_000_000,
        dias_para_jornada=dias,
        baseline_puntos=33.0,
    )


class ReglaDelCreditoTests(unittest.TestCase):
    def test_sube_mucho_o_mejora_claro_sin_bajada(self) -> None:
        self.assertTrue(merece_credito_paron(origen="bid", pct=CREDITO_PARON_PCT, mejora=0.0))
        self.assertTrue(merece_credito_paron(origen="bid", pct=0.0, mejora=CREDITO_PARON_MEJORA))
        self.assertTrue(merece_credito_paron(origen="bid", pct=None, mejora=CREDITO_PARON_MEJORA))
        self.assertFalse(merece_credito_paron(origen="bid", pct=11.9, mejora=1.9))
        # Mejora el once, pero se prevé que baje: se espera.
        self.assertFalse(merece_credito_paron(origen="bid", pct=-3.0, mejora=4.0))
        # Una cláusula se paga siempre con caja.
        self.assertFalse(merece_credito_paron(origen="clause", pct=30.0, mejora=6.0))
        # Dip: aunque la semana pinte bien, hoy sigue cayendo y el crédito no entra.
        self.assertFalse(
            merece_credito_paron(origen="bid", pct=30.0, mejora=4.0, cambio_hoy_pct=-0.8)
        )
        self.assertTrue(
            merece_credito_paron(origen="bid", pct=30.0, mejora=0.0, cambio_hoy_pct=0.4)
        )


class PujarConCreditoTests(unittest.TestCase):
    def test_en_el_paron_puja_hoy_con_deuda_y_no_vende_a_nadie(self) -> None:
        plan = _plan([_mercado("felix", "DEL", 7.0, 9_000_000, 28.0)])
        pujas = [a for a in plan["acciones"] if a["tipo"] == "PUJA"]
        self.assertEqual([a["player_id"] for a in pujas], ["felix"])
        self.assertEqual(pujas[0]["momento"], "hoy")
        self.assertTrue(pujas[0]["financia_con_credito"])
        self.assertIn("No vendas hoy", pujas[0]["detalle"])
        self.assertFalse([a for a in plan["acciones"] if a["tipo"] in {"VENDER HOY", "VENDE"}])
        self.assertLess(plan["saldo_al_final"], 0)
        presupuesto = plan["presupuesto"]
        self.assertTrue(presupuesto["cumple"])
        self.assertEqual(presupuesto["credito_paron"], 9_000_000 - 200_000)

    def test_publica_la_deuda_y_cuando_decidir_las_ventas(self) -> None:
        plan = _plan([_mercado("felix", "DEL", 7.0, 9_000_000, 28.0)])
        deuda = plan["deuda_paron"]
        self.assertEqual(deuda["eur"], 8_800_000)
        self.assertAlmostEqual(deuda["saldar_antes_de_dias"], DIAS_PARON, places=1)
        self.assertAlmostEqual(deuda["decidir_ventas_en_dias"], DIAS_PARON - 3.0, places=1)

    def test_la_deuda_nunca_pasa_del_20_por_ciento_del_equipo(self) -> None:
        tope = DEUDA_PCT_EQUIPO * 11 * VALOR
        plan = _plan([_mercado("caro", "DEL", 9.0, int(tope) + 5_000_000, 30.0)])
        self.assertFalse([a for a in plan["acciones"] if a["tipo"] == "PUJA"])

    def test_antes_del_paron_el_credito_pide_venta_preparada(self) -> None:
        # Auditoría 14-nov, fallo 2: las pujas vivas reservan saldo y LaLiga deja
        # pujar hasta caja + 20 %. Con 2 días o más se puede, si el banquillo lo cubre.
        plan = _plan([_mercado("felix", "DEL", 7.0, 9_000_000, 28.0)], dias=4.0)
        puja = next(a for a in plan["acciones"] if a["tipo"] == "PUJA")
        self.assertTrue(puja["financia_con_credito"])
        self.assertTrue(puja["venta_si_ganas"])
        self.assertIn("Si la ganas, pon a la venta", puja["detalle"])
        self.assertTrue(plan["venta_preparada"])

    def test_a_menos_de_dos_dias_no_hay_credito(self) -> None:
        # Sin tiempo para vender después: si puja, la paga una venta atada a ganarla.
        plan = _plan([_mercado("felix", "DEL", 7.0, 9_000_000, 28.0)], dias=1.5)
        self.assertFalse([a for a in plan["acciones"] if a.get("financia_con_credito")])
        self.assertIsNone(plan.get("deuda_paron"))
        self.assertEqual(plan["venta_preparada"], [])

    def test_sin_banquillo_que_vender_no_hay_credito(self) -> None:
        owned = _plantilla()
        for row in owned:
            row.pop("venta_eur")
        plan = build_plan_fichajes(
            cash=200_000, owned=owned, mercado=[_mercado("felix", "DEL", 7.0, 9_000_000, 28.0)], clausulas=[],
            ratio=3_000_000, dias_para_jornada=4.0, baseline_puntos=33.0,
        )
        self.assertFalse([a for a in plan["acciones"] if a["tipo"] == "PUJA" and a.get("momento") == "hoy"])

    def test_no_compra_hoy_a_quien_mejora_el_once_pero_baja(self) -> None:
        plan = _plan([_mercado("cae", "DEL", 7.0, 9_000_000, -6.0)])
        self.assertFalse([a for a in plan["acciones"] if a["tipo"] == "PUJA"])

    def test_una_clausula_no_se_paga_con_credito(self) -> None:
        plan = _plan([], clausulas=[_mercado("raid", "DEL", 9.0, 5_000_000, 30.0)])
        self.assertFalse([a for a in plan["acciones"] if a["tipo"] == "CLAUSULAZO"])

    def test_alta_subida_sin_mejora_va_al_trading_y_no_al_once(self) -> None:
        # Mejora el once +0,3: no es un fichaje del once, es especulación.
        plan = _plan([_mercado("sube", "DEL", 3.3, 6_000_000, 20.0)])
        self.assertFalse([a for a in plan["acciones"] if a["tipo"] == "PUJA"])
        operaciones = plan["trading"]["operaciones"]
        self.assertEqual([o["player_id"] for o in operaciones], ["sube"])


if __name__ == "__main__":
    unittest.main()

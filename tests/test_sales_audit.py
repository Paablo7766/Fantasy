"""Auditor de ventas: ofertas de LaLiga y rivales, timing y los cinco veredictos."""

from __future__ import annotations

import unittest

from toolbox.engine.sales_audit import calidad_oferta, evaluar_ventas_y_ofertas
from toolbox.engine.strategy_layer import _ofertas_propias

VALOR = 10_000_000


def _once(puntos: float = 5.0) -> list[dict]:
    plantilla = []
    for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
        for index in range(count):
            plantilla.append(
                {
                    "player_id": f"{position}-{index}",
                    "nombre": f"{position}{index}",
                    "position": position,
                    "valor": VALOR,
                    "valor_justo": VALOR,
                    "jornada": puntos,
                    "elegible": True,
                    "ofertas": [],
                }
            )
    # Un suplente flojo por línea: sin banquillo, cualquier baja deja el once ilegal.
    for position in ("POR", "DEF", "MC", "DEL"):
        plantilla.append(
            {
                "player_id": f"{position}-banq",
                "nombre": f"Suplente {position}",
                "position": position,
                "valor": 2_000_000,
                "valor_justo": 2_000_000,
                "jornada": 0.5,
                "elegible": True,
                "ofertas": [],
            }
        )
    return plantilla


def _con(plantilla: list[dict], player_id: str, **cambios: object) -> list[dict]:
    for fila in plantilla:
        if fila["player_id"] == player_id:
            fila.update(cambios)
    return plantilla


def _oferta(comprador: str, factor: float) -> list[dict]:
    return [{"comprador": comprador, "importe": int(VALOR * factor)}]


def _fila(resultado: dict, player_id: str) -> dict:
    return next(fila for fila in resultado["filas"] if fila["player_id"] == player_id)


def _plan(*acciones: dict) -> dict:
    return {"acciones": list(acciones)}


class CalidadTests(unittest.TestCase):
    def test_umbrales(self) -> None:
        self.assertEqual(calidad_oferta(2.5), "Excelente")
        self.assertEqual(calidad_oferta(2.49), "Justa")
        self.assertEqual(calidad_oferta(-1.0), "Justa")
        self.assertEqual(calidad_oferta(-1.01), "Baja")
        self.assertIsNone(calidad_oferta(None))


class VeredictosTests(unittest.TestCase):
    def test_aceptar_ya_oferta_justa_de_laliga_si_el_plan_manda_vender(self) -> None:
        plantilla = _con(_once(), "DEF-0", ofertas=_oferta("LaLiga", 1.03), jornada=1.0, pct=-2.4, en_mercado=True)
        plantilla.append({"player_id": "DEF-9", "nombre": "Castrín", "position": "DEF", "valor": VALOR, "jornada": 4.8, "elegible": True, "ofertas": []})
        plan = _plan({"tipo": "VENDER HOY", "momento": "hoy", "player_id": "DEF-0"})
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=plan, saldo=5_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "DEF-0")
        self.assertEqual(fila["veredicto_codigo"], "ACEPTAR_YA")
        self.assertEqual(fila["veredicto_titulo"], "ACEPTA YA")
        self.assertEqual(fila["oferta_activa"]["calidad_oferta"], "Excelente")
        self.assertAlmostEqual(fila["oferta_activa"]["spread_pct"], 3.0, places=1)
        self.assertIn("10,3M", fila["motivo_detallado"])

    def test_aceptar_ya_si_cae_mas_de_un_3_por_ciento(self) -> None:
        plantilla = _con(_once(), "MC-0", ofertas=_oferta("LaLiga", 1.0), pct=-4.0, jornada=1.0, en_mercado=True)
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=_plan(), saldo=3_000_000, dias_al_cierre=4.0)
        self.assertEqual(_fila(resultado, "MC-0")["veredicto_codigo"], "ACEPTAR_YA")

    def test_aceptar_ya_obligada_si_la_caja_esta_en_negativo(self) -> None:
        plantilla = _con(_once(), "DEL-0", ofertas=_oferta("LaLiga", 0.97), jornada=3.0, en_mercado=True)
        plan = _plan({"tipo": "VENDE", "momento": "hoy", "player_id": "DEL-0"})
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=plan, saldo=-1_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "DEL-0")
        self.assertEqual(fila["veredicto_codigo"], "ACEPTAR_YA")
        self.assertIn("negativo", fila["motivo_detallado"])

    def test_aceptar_ya_obligada_si_financia_un_must_buy(self) -> None:
        plantilla = _con(_once(), "DEL-1", ofertas=_oferta("LaLiga", 0.99), jornada=3.0, en_mercado=True)
        plan = _plan(
            {"tipo": "VENDE", "momento": "hoy", "player_id": "DEL-1"},
            {"tipo": "PUJA", "momento": "hoy", "player_id": "X", "impulso": "MUST-BUY", "euros": 12_000_000},
        )
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=plan, saldo=4_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "DEL-1")
        self.assertEqual(fila["veredicto_codigo"], "ACEPTAR_YA")
        self.assertTrue(fila["financia_must_buy_hoy"])

    def test_rechazar_esperar_si_la_oferta_es_mala_y_sube_fuerte(self) -> None:
        plantilla = _con(_once(), "MC-1", ofertas=_oferta("LaLiga", 0.968), pct=9.4, jornada=1.0, en_mercado=True)
        plan = _plan({"tipo": "VENDE", "momento": "hoy", "player_id": "MC-1"})
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=plan, saldo=4_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "MC-1")
        self.assertEqual(fila["veredicto_codigo"], "RECHAZAR_ESPERAR")
        self.assertEqual(fila["oferta_activa"]["calidad_oferta"], "Baja")
        self.assertIn("jueves", fila["motivo_detallado"])

    def test_no_espera_si_quedan_menos_de_dos_dias(self) -> None:
        plantilla = _con(_once(), "MC-1", ofertas=_oferta("LaLiga", 0.97), pct=9.4, jornada=1.0, en_mercado=True)
        plan = _plan({"tipo": "VENDE", "momento": "hoy", "player_id": "MC-1"})
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=plan, saldo=4_000_000, dias_al_cierre=1.0)
        self.assertNotEqual(_fila(resultado, "MC-1")["veredicto_codigo"], "RECHAZAR_ESPERAR")

    def test_rechazar_rival_sin_sobreprecio_y_alerta_de_refuerzo(self) -> None:
        plantilla = _con(_once(), "DEL-2", ofertas=_oferta("Luis", 1.05), jornada=4.2, en_mercado=True)
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=_plan(), saldo=4_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "DEL-2")
        self.assertEqual(fila["veredicto_codigo"], "RECHAZAR_RIVAL")
        self.assertTrue(fila["alerta_refuerzo_rival"])
        self.assertEqual(fila["oferta_activa"]["comprador"], "Luis")

    def test_rival_con_sobreprecio_suficiente_no_se_rechaza(self) -> None:
        plantilla = _con(_once(), "DEL-2", ofertas=_oferta("Luis", 1.15), jornada=4.2, en_mercado=True)
        plan = _plan({"tipo": "VENDE", "momento": "hoy", "player_id": "DEL-2"})
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=plan, saldo=4_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "DEL-2")
        self.assertNotEqual(fila["veredicto_codigo"], "RECHAZAR_RIVAL")
        self.assertFalse(fila["alerta_refuerzo_rival"])

    def test_poner_escaparate_si_el_plan_lo_vende_y_no_hay_oferta(self) -> None:
        plantilla = _con(_once(), "DEF-1", jornada=1.0)
        plan = _plan({"tipo": "ESCAPARATE", "momento": "hoy", "player_id": "DEF-1"})
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=plan, saldo=4_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "DEF-1")
        self.assertEqual(fila["veredicto_codigo"], "PONER_ESCAPARATE")
        self.assertIsNone(fila["oferta_activa"]["importe_oferta"])
        self.assertEqual(fila["prioridad"], 1)

    def test_poner_escaparate_si_esta_sobrevalorado(self) -> None:
        plantilla = _con(_once(), "DEF-2", valor=14_000_000, valor_justo=10_000_000, jornada=1.0)
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=_plan(), saldo=4_000_000, dias_al_cierre=4.0)
        self.assertEqual(_fila(resultado, "DEF-2")["veredicto_codigo"], "PONER_ESCAPARATE")

    def test_mantener_intocable_si_el_once_se_hunde_sin_el(self) -> None:
        plantilla = _once(4.0)
        plantilla = _con(plantilla, "POR-0", ofertas=_oferta("LaLiga", 1.05), jornada=9.0, tu_once_pierde_sin_el=2.4, en_mercado=True)
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=_plan(), saldo=4_000_000, dias_al_cierre=4.0)
        fila = _fila(resultado, "POR-0")
        self.assertEqual(fila["veredicto_codigo"], "MANTENER_INTOCABLE")
        self.assertEqual(fila["prioridad"], 2)

    def test_jugador_sin_motivo_para_vender_no_aparece(self) -> None:
        resultado = evaluar_ventas_y_ofertas(_once(), plan=_plan(), saldo=4_000_000, dias_al_cierre=4.0)
        self.assertEqual(resultado["filas"], [])


class ProyeccionYResumenTests(unittest.TestCase):
    def test_ganancia_hasta_el_jueves_sale_del_ritmo_semanal(self) -> None:
        plantilla = _con(_once(), "MC-2", ofertas=_oferta("LaLiga", 1.0), pct=7.0, jornada=1.0, en_mercado=True)
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=_plan(), saldo=1_000_000, dias_al_cierre=4.0)
        jueves = _fila(resultado, "MC-2")["ganancia_esperar_jueves"]
        # 7 % a la semana = 1 % al día; faltan 3 días hasta el jueves.
        self.assertAlmostEqual(jueves["pct"], 3.0, places=2)
        self.assertEqual(jueves["valor_proyectado_jueves"], int(VALOR * 1.03))

    def test_resumen_y_orden_por_prioridad(self) -> None:
        plantilla = _once()
        _con(plantilla, "DEF-0", ofertas=_oferta("LaLiga", 1.04), pct=-3.5, jornada=1.0, en_mercado=True)
        _con(plantilla, "DEF-1", ofertas=_oferta("LaLiga", 1.0), pct=-4.0, jornada=1.0, en_mercado=True)
        _con(plantilla, "MC-0", valor=15_000_000, valor_justo=10_000_000, jornada=1.0)
        resultado = evaluar_ventas_y_ofertas(plantilla, plan=_plan(), saldo=2_000_000, dias_al_cierre=4.0)
        resumen = resultado["resumen"]
        self.assertEqual(resumen["ofertas_activas"], 2)
        self.assertEqual(resumen["total_ofertas_eur"], int(VALOR * 1.04) + VALOR)
        self.assertAlmostEqual(resumen["spread_medio_laliga_pct"], 2.0, places=1)
        self.assertEqual(resumen["ventas_recomendadas_hoy"], 2)
        orden = [fila["player_id"] for fila in resultado["filas"]]
        self.assertEqual(orden[:2], ["DEF-0", "DEF-1"])
        self.assertEqual(orden[-1], "MC-0")


class OfertasPropiasTests(unittest.TestCase):
    def test_puja_sin_equipo_es_de_laliga_y_la_de_un_rival_lleva_su_nombre(self) -> None:
        fila = {
            "is_self": True,
            "on_market": True,
            "seller_team_id": "yo",
            "bids": [{"amount": 9_000_000, "team_id": None}, {"amount": 9_500_000, "team_id": "t2"}, {"amount": 8_000_000, "team_id": "yo"}],
        }
        ofertas = _ofertas_propias(fila, "yo", {"t2": "Luis"})
        self.assertEqual(
            sorted((oferta["comprador"], oferta["importe"]) for oferta in ofertas),
            [("LaLiga", 9_000_000), ("Luis", 9_500_000)],
        )

    def test_marca_de_laliga_sin_importe_deja_la_oferta_sin_cifra(self) -> None:
        ofertas = _ofertas_propias({"is_self": True, "tiene_oferta_laliga": True}, "yo", {})
        self.assertEqual(ofertas, [{"comprador": "LaLiga", "importe": None}])

    def test_importe_directo_del_sistema(self) -> None:
        fila = {"is_self": True, "ofertas_directas": [{"comprador": "LaLiga", "importe": 7_000_000}], "tiene_oferta_laliga": True}
        self.assertEqual(_ofertas_propias(fila, "yo", {}), [{"comprador": "LaLiga", "importe": 7_000_000}])


if __name__ == "__main__":
    unittest.main()

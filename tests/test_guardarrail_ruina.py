"""Guardarraíl de ruina: saldo en el peor caso, colchón por caída de valor y estados."""

from __future__ import annotations

import math
import unittest

from toolbox.engine.guardarrail_ruina import (
    AVISO,
    K_COLA,
    OK,
    PELIGRO,
    SIN_ACTUALIZAR,
    evaluar,
    evaluar_plan,
    plan_cobertura,
    sigma_cartera,
    sigma_diaria,
    valor_estresado,
)

M = 1_000_000
FRESCO = 3600.0
VIEJO = 30 * 3600.0


def _sigma(rel: float = 0.01, valor: int = 100 * M) -> dict:
    return {"sigma_rel": rel, "sigma_eur": int(rel * valor), "observaciones": 10, "valor_actual": valor}


def _eval(caja: int, pujas: list[int], *, rel: float = 0.01, dias: float = 5.0, **extra):
    base = dict(
        caja=caja,
        pujas_vivas=[{"player_id": f"p{i}", "nombre": f"p{i}", "euros": e} for i, e in enumerate(pujas)],
        valor_equipo=100 * M,
        sigma=_sigma(rel),
        dias_al_cierre=dias,
        edad_caja_s=FRESCO,
        edad_precios_s=FRESCO,
    )
    base.update(extra)
    return evaluar(**base)


class SigmaTest(unittest.TestCase):
    def test_sigma_de_cambios_relativos(self) -> None:
        valores = [100, 101, 99, 100, 102, 101, 100]
        historia = [{"day": f"2026-11-{i + 1:02d}", "value_eur": v * M} for i, v in enumerate(valores)]
        resultado = sigma_diaria(historia)
        assert resultado is not None
        cambios = [valores[i + 1] / valores[i] - 1 for i in range(len(valores) - 1)]
        media = sum(cambios) / len(cambios)
        esperado = math.sqrt(sum((c - media) ** 2 for c in cambios) / (len(cambios) - 1))
        self.assertAlmostEqual(resultado["sigma_rel"], esperado, places=9)
        self.assertEqual(resultado["valor_actual"], 100 * M)

    def test_pocas_observaciones_no_dan_sigma(self) -> None:
        historia = [{"day": f"2026-11-0{i + 1}", "value_eur": (100 + i) * M} for i in range(3)]
        self.assertIsNone(sigma_diaria(historia))

    def test_hueco_de_dias_se_reparte(self) -> None:
        historia = [
            {"day": "2026-11-01", "value_eur": 100 * M},
            {"day": "2026-11-02", "value_eur": 101 * M},
            {"day": "2026-11-03", "value_eur": 100 * M},
            {"day": "2026-11-04", "value_eur": 101 * M},
            {"day": "2026-11-09", "value_eur": 101 * M + 50_000},
        ]
        con_hueco = sigma_diaria(historia, min_obs=4)
        assert con_hueco is not None
        self.assertLess(con_hueco["sigma_rel"], 0.02)


class SigmaCarteraTest(unittest.TestCase):
    def test_un_jugador_que_entra_al_historico_no_mete_un_salto(self) -> None:
        def serie(valores: list[int], desde: int) -> list[dict]:
            return [{"day": f"2026-11-{desde + i:02d}", "market_value": v} for i, v in enumerate(valores)]

        historia = {
            "a": serie([10 * M, 10_100_000, 10_000_000, 10_100_000, 10_000_000, 10_100_000], 1),
            # «b» solo aparece en el histórico desde el día 4: sumar valores metería un salto de 40 M.
            "b": serie([40 * M, 40_400_000, 40_000_000], 4),
        }
        resultado = sigma_cartera(historia, ["a", "b"], min_cobertura=0.4)
        assert resultado is not None
        self.assertLess(resultado["sigma_rel"], 0.02)

    def test_sin_cobertura_suficiente_no_hay_sigma(self) -> None:
        historia = {"a": [{"day": f"2026-11-0{i}", "market_value": (10 + i) * M} for i in range(1, 7)]}
        self.assertIsNone(sigma_cartera(historia, ["a", "b", "c", "d"]))


class ValorEstresadoTest(unittest.TestCase):
    def test_formula(self) -> None:
        self.assertEqual(valor_estresado(100 * M, 0.01, 4.0), int(round(100 * M * (1 - K_COLA * 0.01 * 2))))

    def test_sin_sigma_no_inventa(self) -> None:
        self.assertEqual(valor_estresado(100 * M, None, 4.0), 100 * M)


class EstadosTest(unittest.TestCase):
    def test_sin_pujas_y_caja_positiva_es_ok(self) -> None:
        r = _eval(10 * M, [])
        self.assertEqual(r["estado"], OK)
        self.assertEqual(r["saldo_peor"], 10 * M)
        self.assertGreater(r["margen_eur"], 10 * M)

    def test_una_puja_dentro_del_limite_es_aviso(self) -> None:
        r = _eval(5 * M, [15 * M])
        self.assertEqual(r["saldo_peor"], -10 * M)
        self.assertEqual(r["estado"], AVISO)
        self.assertEqual(r["falta_eur"], 10 * M)
        self.assertGreater(r["margen_eur"], 0)

    def test_varias_pujas_que_juntas_rompen_el_limite_son_peligro(self) -> None:
        # Cada una sola cabe; juntas (27 M) superan el 20 % estresado (≈ 18,96 M).
        self.assertEqual(_eval(5 * M, [15 * M])["estado"], AVISO)
        self.assertEqual(_eval(5 * M, [12 * M])["estado"], AVISO)
        junto = _eval(5 * M, [15 * M, 12 * M])
        self.assertEqual(junto["saldo_peor"], -22 * M)
        self.assertEqual(junto["estado"], PELIGRO)
        self.assertLess(junto["margen_eur"], 0)

    def test_caida_de_valor_rompe_el_limite_sin_pujas(self) -> None:
        # Deuda real de 17 M: con σ 1 % cabe en el límite estresado (18,96 M), con σ 3 % no (16,88 M).
        tranquilo = _eval(-17 * M, [], rel=0.01)
        self.assertEqual(tranquilo["estado"], AVISO)
        volatil = _eval(-17 * M, [], rel=0.03)
        self.assertEqual(volatil["estado"], PELIGRO)
        self.assertLess(volatil["limite_deuda_estresado"], tranquilo["limite_deuda_estresado"])

    def test_saldo_real_negativo_a_menos_de_24h_es_peligro(self) -> None:
        r = _eval(-1 * M, [], dias=0.5)
        self.assertEqual(r["estado"], PELIGRO)
        lejos = _eval(-1 * M, [], dias=3.0)
        self.assertEqual(lejos["estado"], AVISO)

    def test_pujas_que_dejan_negativo_a_menos_de_24h_no_es_aviso(self) -> None:
        self.assertEqual(_eval(5 * M, [8 * M], dias=0.5)["estado"], PELIGRO)

    def test_datos_caducados_nunca_son_ok(self) -> None:
        for kwargs in ({"edad_caja_s": VIEJO}, {"edad_precios_s": VIEJO}, {"edad_caja_s": None}):
            r = _eval(10 * M, [], **kwargs)
            self.assertEqual(r["estado"], SIN_ACTUALIZAR, kwargs)
            self.assertTrue(r["datos_caducados"])

    def test_datos_caducados_no_tapan_un_peligro(self) -> None:
        r = _eval(5 * M, [15 * M, 12 * M], edad_caja_s=VIEJO)
        self.assertEqual(r["estado"], PELIGRO)
        self.assertTrue(r["datos_caducados"])

    def test_sin_mercado_en_la_foto_no_es_ok(self) -> None:
        self.assertEqual(_eval(10 * M, [], pujas_conocidas=False)["estado"], SIN_ACTUALIZAR)

    def test_sin_sigma_no_es_ok(self) -> None:
        self.assertEqual(_eval(10 * M, [], sigma=None)["estado"], SIN_ACTUALIZAR)

    def test_ofertas_de_compra_pendientes_restan(self) -> None:
        r = _eval(10 * M, [4 * M], ofertas_compra_pendientes=7 * M)
        self.assertEqual(r["saldo_peor"], -1 * M)

    def test_sin_caja_no_calcula(self) -> None:
        r = _eval(None, [])  # type: ignore[arg-type]
        self.assertEqual(r["estado"], SIN_ACTUALIZAR)
        self.assertIsNone(r["saldo_peor"])


def _fila(pid: str, pos: str, xp: float, venta: int | None = None) -> dict:
    fila = {"player_id": pid, "nombre": pid, "position": pos, "jornada": xp, "p_titular": 1.0}
    if venta is not None:
        fila["venta_eur"] = venta
    return fila


def _plantilla() -> list[dict]:
    posiciones = ["POR", "POR"] + ["DEF"] * 5 + ["MC"] * 5 + ["DEL"] * 3
    xps = [5, 1, 6, 5, 5, 4, 1.2, 6, 5, 5, 4, 1.1, 7, 6, 1.3]
    return [_fila(f"j{i}", pos, xp, venta=2 * M) for i, (pos, xp) in enumerate(zip(posiciones, xps))]


class CoberturaTest(unittest.TestCase):
    def test_vende_al_suplente_antes_que_retirar_la_puja_del_titular(self) -> None:
        pujas = [{"player_id": "nuevo", "nombre": "nuevo", "position": "DEL", "jornada": 9.0, "euros": 3 * M}]
        r = plan_cobertura(falta_eur=2 * M, pujas=pujas, plantilla=_plantilla())
        self.assertTrue(r["cubre"])
        self.assertEqual(r["coste_xp"], 0.0)
        self.assertEqual([a["tipo"] for a in r["acciones"]], ["VENDER"])

    def test_retira_la_puja_si_vender_cuesta_mas(self) -> None:
        # La puja es de un suplente (xP 0,5): retirarla no cuesta nada y cubre los 3 M.
        pujas = [{"player_id": "nuevo", "nombre": "nuevo", "position": "DEL", "jornada": 0.5, "euros": 3 * M}]
        r = plan_cobertura(falta_eur=3 * M, pujas=pujas, plantilla=_plantilla())
        self.assertTrue(r["cubre"])
        self.assertEqual(r["coste_xp"], 0.0)

    def test_usa_el_precio_realizable_no_el_de_mercado(self) -> None:
        plantilla = _plantilla()
        for fila in plantilla:
            fila["venta_eur"] = 1 * M
        r = plan_cobertura(falta_eur=2 * M, pujas=[], plantilla=plantilla)
        self.assertEqual(r["euros_cubiertos"] >= 2 * M, True)
        self.assertGreaterEqual(len(r["acciones"]), 2)

    def test_falta_mas_de_lo_que_se_puede_cubrir(self) -> None:
        r = plan_cobertura(falta_eur=500 * M, pujas=[], plantilla=_plantilla())
        self.assertFalse(r["cubre"])

    def test_sin_falta_no_hay_acciones(self) -> None:
        self.assertEqual(plan_cobertura(falta_eur=0, pujas=[], plantilla=_plantilla())["acciones"], [])


class PlanTest(unittest.TestCase):
    def test_plan_que_deja_peligro_se_marca_para_descartar(self) -> None:
        base = _eval(5 * M, [])
        plan = evaluar_plan(
            base,
            [
                {"tipo": "PUJA", "player_id": "a", "euros": 20 * M},
                {"tipo": "CLAUSULAZO", "player_id": "b", "euros": 6 * M},
            ],
        )
        assert plan is not None
        self.assertEqual(plan["saldo_peor"], -21 * M)
        self.assertEqual(plan["estado"], PELIGRO)
        self.assertTrue(plan["descartar"])

    def test_plan_dentro_del_limite_es_aviso(self) -> None:
        plan = evaluar_plan(_eval(5 * M, []), [{"tipo": "PUJA", "player_id": "a", "euros": 12 * M}])
        assert plan is not None
        self.assertEqual(plan["estado"], AVISO)
        self.assertFalse(plan["descartar"])

    def test_puja_del_plan_sobre_una_viva_no_se_suma_dos_veces(self) -> None:
        base = _eval(5 * M, [10 * M])  # pujas_vivas[0].player_id == "p0"
        plan = evaluar_plan(base, [{"tipo": "PUJA", "player_id": "p0", "euros": 12 * M}])
        assert plan is not None
        self.assertEqual(plan["gasto_plan_adicional"], 2 * M)


if __name__ == "__main__":
    unittest.main()

"""Bloques de la fase 3: ley de inercia 0,944, venta en pico y suelo legal de la caja."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from toolbox.engine.market_predictor import (
    impulso_post_jornada_pct,
    proyectar_inercia,
    vender_en_pico_prohibido,
)
from toolbox.engine.paron_plan import valor_proyectado, venta_prematura
from toolbox.league_history import anchor_legal_floor, friday_locks
from toolbox.own_intel import catalog_snapshot_rows

MADRID = ZoneInfo("Europe/Madrid")


class LeyInerciaTests(unittest.TestCase):
    def test_un_dia_aplica_la_ley_exacta(self) -> None:
        # lunes 9 nov -> martes 10: 0,041 + 0,944 * 2 = 1,929 %
        res = proyectar_inercia(10_000_000, 2.0, 1, desde=date(2026, 11, 9))
        self.assertAlmostEqual(res["serie_pct"][0], 1.929, places=3)

    def test_el_domingo_no_se_mueve_ni_gasta_inercia(self) -> None:
        # sábado 7 nov: el domingo 8 es plano, el lunes 9 sigue desde el sábado.
        res = proyectar_inercia(10_000_000, 2.0, 2, desde=date(2026, 11, 7))
        self.assertEqual(res["serie_pct"][0], 0.0)
        self.assertAlmostEqual(res["serie_pct"][1], 1.929, places=3)

    def test_impulso_solo_en_tramo_y_con_puntos(self) -> None:
        self.assertEqual(impulso_post_jornada_pct(8_000_000, 5), 0.0)
        self.assertGreater(impulso_post_jornada_pct(8_000_000, 6), 0.0)
        # En >20 M no hay impulso medido: el umbral existe, el impulso es 0.
        self.assertEqual(impulso_post_jornada_pct(30_000_000, 9), 0.0)
        base = proyectar_inercia(8_000_000, 0.0, 3, desde=date(2026, 11, 9))
        con = proyectar_inercia(
            8_000_000, 0.0, 3, desde=date(2026, 11, 9), puntos_jornada=8, post_jornada=True
        )
        self.assertGreater(con["valor"], base["valor"])

    def test_no_se_vende_en_el_pico_salvo_dia_limite(self) -> None:
        self.assertTrue(vender_en_pico_prohibido(1.5))
        self.assertFalse(vender_en_pico_prohibido(1.5, dia_limite_caja=True))
        self.assertFalse(vender_en_pico_prohibido(0.1))
        fila = {"valor": 10_000_000, "delta_hoy": 300_000}
        self.assertTrue(venta_prematura(fila, dia_limite_caja=False))
        self.assertFalse(venta_prematura(fila, dia_limite_caja=True))

    def test_valor_proyectado_usa_la_ley_con_delta_y_lineal_sin_ella(self) -> None:
        con = valor_proyectado({"valor": 10_000_000, "delta_hoy": 200_000, "pct": 0.0}, 3, hoy=date(2026, 11, 9))
        self.assertGreater(con, 10_200_000)
        lineal = valor_proyectado({"valor": 10_000_000, "pct": 7.0}, 7)
        self.assertEqual(lineal, 10_700_000)


class SueloLegalTests(unittest.TestCase):
    def _ledger(self, initial: int, lines: list[dict]) -> dict:
        return {
            "team_id": "t1",
            "initial_budget_eur": initial,
            "reconstructed_cash_eur": initial + sum(item["signed_eur"] for item in lines),
            "observed_cash_eur": None,
            "events": lines,
        }

    def test_viernes_21h(self) -> None:
        locks = friday_locks(
            datetime(2026, 11, 2, 12, tzinfo=MADRID), datetime(2026, 11, 9, 12, tzinfo=MADRID)
        )
        self.assertEqual([lock.isoformat() for lock in locks], ["2026-11-06T21:00:00+01:00"])

    def test_clausulazo_exige_caja_previa(self) -> None:
        lines = [
            {"kind": "clause", "amount_eur": 12_500_000, "signed_eur": -12_500_000, "at": "2026-11-09T11:03:32+01:00"},
        ]
        ledger = self._ledger(3_850_000, lines)
        anchor_legal_floor([ledger], now=datetime(2026, 11, 9, 18, tzinfo=MADRID))
        self.assertEqual(ledger["reconstructed_cash_eur"], 0)
        self.assertEqual(ledger["anchored"]["lifted_eur"], 8_650_000)
        self.assertEqual(ledger["raw_reconstructed_cash_eur"], -8_650_000)

    def test_viernes_puntuado_levanta_a_cero_y_sin_premio_no(self) -> None:
        gasto = {"kind": "buy", "amount_eur": 5_000_000, "signed_eur": -5_000_000, "at": "2026-11-02T10:00:00+01:00"}
        premio = {"kind": "premium", "amount_eur": 4_000_000, "signed_eur": 4_000_000, "at": "2026-11-09T04:57:47+01:00"}
        puntuo = self._ledger(1_000_000, [gasto, premio])
        no_puntuo = self._ledger(1_000_000, [gasto])
        anchor_legal_floor([puntuo, no_puntuo], now=datetime(2026, 11, 9, 18, tzinfo=MADRID))
        self.assertEqual(puntuo["reconstructed_cash_eur"], 4_000_000)
        self.assertEqual(no_puntuo["reconstructed_cash_eur"], -4_000_000)

    def test_subida_de_clausula_resta_el_coste_1_a_2(self) -> None:
        ledger = self._ledger(10_000_000, [])
        ledger["events"] = [
            {"kind": "buy", "amount_eur": 1, "signed_eur": -1, "at": "2026-11-01T10:00:00+01:00"}
        ]
        coste = {"team_id": "t1", "day": "2026-11-08", "cost_eur": 7_421_102}
        anchor_legal_floor([ledger], [coste], now=datetime(2026, 11, 9, 18, tzinfo=MADRID))
        self.assertEqual(ledger["anchored"]["clause_raise_cost_eur"], 7_421_102)
        self.assertEqual(ledger["reconstructed_cash_eur"], 10_000_000 - 1 - 7_421_102)

    def test_caja_observada_no_se_toca(self) -> None:
        ledger = self._ledger(1_000_000, [])
        ledger["observed_cash_eur"] = 5
        anchor_legal_floor([ledger], now=datetime(2026, 11, 9, 18, tzinfo=MADRID))
        self.assertNotIn("anchored", ledger)


class CatalogoTests(unittest.TestCase):
    def test_solo_los_que_no_tienen_fila_y_estan_en_liga(self) -> None:
        catalogo = [
            {"player_id": "a", "market_value": 5_000_000, "market_value_change": 10_000},
            {"player_id": "b", "market_value": 6_000_000},
            {"player_id": "c", "market_value": 7_000_000, "player_status": "out_of_league"},
            {"player_id": "d", "market_value": 0},
        ]
        filas = catalog_snapshot_rows(catalogo, already={"a"}, league_id="L1", day="2026-11-09")
        self.assertEqual([fila["player_id"] for fila in filas], ["b"])
        self.assertEqual(filas[0]["market_value"], 6_000_000)


if __name__ == "__main__":
    unittest.main()


class ColaAntiPicosTests(unittest.TestCase):
    def test_cola_no_redonda_estable_y_acotada(self) -> None:
        from toolbox.engine.auction_intel import COLA_MAX_EUR, COLA_MIN_EUR, cola_anti_picos, con_cola_anti_picos

        for clave in ("1", "abc", 12345, None):
            cola = cola_anti_picos(clave)
            self.assertGreaterEqual(cola, COLA_MIN_EUR)
            self.assertLessEqual(cola, COLA_MAX_EUR)
            self.assertNotEqual(cola % 10, 0)
            self.assertEqual(cola, cola_anti_picos(clave))
        # Barre un +1 / +10 EUR sobre el redondo.
        puja = con_cola_anti_picos(10_000_000, clave="p")
        self.assertGreater(puja, 10_000_000 + 10)

    def test_nunca_pasa_del_techo_ni_del_presupuesto(self) -> None:
        from toolbox.engine.auction_intel import con_cola_anti_picos

        self.assertEqual(con_cola_anti_picos(10_000_000, clave="p", techo=10_000_500), 10_000_500)
        self.assertEqual(con_cola_anti_picos(10_000_000, clave="p", saldo=10_000_000), 10_000_000)
        self.assertEqual(con_cola_anti_picos(10_000_000, clave="p", techo=10_000_000), 10_000_000)
        # Una cifra que ya trae cola no se toca.
        self.assertEqual(con_cola_anti_picos(10_003_719, clave="p"), 10_003_719)

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from toolbox.dinero_caliente import PROB_GASTO_PCT, aviso_dinero_caliente, victimas_recientes

AHORA = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)  # 17:00 Madrid
SQUADS = [{"team_id": "T1", "manager_id": "M1"}, {"team_id": "T2", "manager_id": "M2"}]


def _clausula(at: str, importe: int, jugador: str, victima: str) -> dict:
    return {
        "kind": "clause",
        "team_id": "T9",
        "amount_eur": importe,
        "at": at,
        "player_id": jugador,
        "counterparty_manager_id": victima,
    }


class DineroCalienteTest(unittest.TestCase):
    def test_marca_a_la_victima_dentro_de_36_horas(self) -> None:
        ledgers = [{"team_id": "T9", "events": [_clausula("2026-11-09T11:03:00+01:00", 12_500_000, "FC", "M1")]}]
        hot = victimas_recientes(ledgers, SQUADS, {"FC": "Félix Correia"}, now=AHORA)
        self.assertEqual(set(hot), {"T1"})
        self.assertEqual(hot["T1"]["importe_eur"], 12_500_000)
        self.assertEqual(hot["T1"]["hace_horas"], 6.0)
        self.assertIn("🔥 Dinero caliente: acaba de cobrar +12,5 M€ por cláusula de Félix Correia hace 6 h", hot["T1"]["aviso"])
        self.assertIn(f"{PROB_GASTO_PCT}% prob.", hot["T1"]["aviso"])

    def test_fuera_de_ventana_o_futuro_no_marca(self) -> None:
        ledgers = [
            {"events": [_clausula("2026-11-07T10:00:00+01:00", 5_000_000, "A", "M1")]},
            {"events": [_clausula("2026-11-09T20:00:00+01:00", 5_000_000, "B", "M2")]},
        ]
        self.assertEqual(victimas_recientes(ledgers, SQUADS, {}, now=AHORA), {})

    def test_mismo_cobro_en_dos_libros_cuenta_una_vez_y_se_suman_cobros(self) -> None:
        a = _clausula("2026-11-09T09:00:00+01:00", 4_000_000, "A", "M2")
        b = _clausula("2026-11-09T12:00:00+01:00", 6_000_000, "B", "M2")
        ledgers = [{"events": [a, b]}, {"events": [dict(a)]}]
        hot = victimas_recientes(ledgers, SQUADS, {"B": "Beta"}, now=AHORA)
        self.assertEqual(hot["T2"]["importe_eur"], 10_000_000)
        self.assertEqual(hot["T2"]["n_cobros"], 2)
        self.assertEqual(hot["T2"]["jugador"], "Beta")

    def test_aviso_de_menos_de_una_hora(self) -> None:
        self.assertIn("hace menos de 1 h", aviso_dinero_caliente(1_000_000, "X", 0.4))


if __name__ == "__main__":
    unittest.main()


class LibroSinContraparteTest(unittest.TestCase):
    """El libro real no trae ``counterparty_manager_id``: la víctima es quien cobra lo mismo en el mismo instante."""

    def test_la_victima_es_el_libro_que_cobra_el_mismo_asiento(self) -> None:
        at = "2026-11-09T11:03:32+01:00"
        ledgers = [
            {"team_id": "40960858", "events": [{"kind": "clause", "team_id": "40960858", "amount_eur": 12_500_000, "at": at, "player_id": "3262"}]},
            {"team_id": "40960836", "events": [{"kind": "sell", "team_id": "40960836", "amount_eur": 12_500_000, "at": at, "player_id": "3262"}]},
            # Una venta normal sin cláusula a la vez no marca a nadie.
            {"team_id": "40960918", "events": [{"kind": "sell", "team_id": "40960918", "amount_eur": 30_219_429, "at": "2026-11-09T12:25:06+01:00", "player_id": "2384"}]},
        ]
        hot = victimas_recientes(ledgers, [], {"3262": "Félix Correia"}, now=AHORA)
        self.assertEqual(set(hot), {"40960836"})
        self.assertEqual(hot["40960836"]["jugador"], "Félix Correia")

    def test_cobro_ambiguo_no_se_adivina(self) -> None:
        at = "2026-11-09T11:03:32+01:00"
        ledgers = [
            {"team_id": "A", "events": [{"kind": "clause", "team_id": "A", "amount_eur": 5_000_000, "at": at, "player_id": "9"}]},
            {"team_id": "B", "events": [{"kind": "sell", "team_id": "B", "amount_eur": 5_000_000, "at": at, "player_id": "9"}]},
            {"team_id": "C", "events": [{"kind": "sell", "team_id": "C", "amount_eur": 5_000_000, "at": at, "player_id": "9"}]},
        ]
        self.assertEqual(victimas_recientes(ledgers, [], {}, now=AHORA), {})

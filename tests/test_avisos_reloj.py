"""Avisos push por reloj: una sola vez, solo en los tramos y solo con problema."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from toolbox import avisos_reloj as ar

AHORA = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def tablero(*, xi: int = 11, caja: int = 5_000_000, lesionado: bool = False, saved: bool = True) -> dict:
    jugadores = [{"player_id": f"p{i}", "name": f"J{i}", "player_status": "ok"} for i in range(11)]
    if lesionado:
        jugadores[3]["player_status"] = "injured"
    optimize = {"saved_lineup": {"xi": [{"player_id": f"p{i}"} for i in range(xi)]}} if saved else {}
    return {
        "squads": {"ok": True, "squads": [{"is_self": True, "cash": caja, "players": jugadores}]},
        "optimize": optimize,
        "trends": {"players": []},
        "photo_saved_unix": (AHORA - timedelta(hours=1)).timestamp(),
    }


class AvisosRelojTests(unittest.TestCase):
    def test_tramos(self) -> None:
        self.assertIsNone(ar.tramo_actual(30))
        self.assertEqual(ar.tramo_actual(20), "24h")
        self.assertEqual(ar.tramo_actual(2), "3h")
        self.assertIsNone(ar.tramo_actual(-1))

    def test_once_en_orden_no_avisa(self) -> None:
        self.assertIsNone(ar.aviso_once(tablero(), AHORA, cierre=AHORA + timedelta(hours=20)))

    def test_once_incompleto_avisa(self) -> None:
        aviso = ar.aviso_once(tablero(xi=9), AHORA, cierre=AHORA + timedelta(hours=20))
        self.assertIn("9/11", aviso["body"])
        self.assertTrue(aviso["clave"].endswith(":24h"))

    def test_lesionado_y_saldo_negativo(self) -> None:
        aviso = ar.aviso_once(tablero(lesionado=True, caja=-1_500_000), AHORA, cierre=AHORA + timedelta(hours=2))
        self.assertIn("saldo negativo", aviso["body"])
        self.assertIn("lesionado", aviso["body"])
        self.assertTrue(aviso["clave"].endswith(":3h"))

    def test_fuera_de_tramo_no_avisa(self) -> None:
        self.assertIsNone(ar.aviso_once(tablero(xi=9), AHORA, cierre=AHORA + timedelta(hours=40)))

    def test_cada_aviso_sale_una_sola_vez(self) -> None:
        enviar = mock.Mock(return_value=1)
        memoria: dict[str, str] = {}
        with mock.patch.object(ar, "_leer", side_effect=lambda: memoria), mock.patch.object(
            ar, "_escribir", side_effect=lambda datos, _ahora: memoria.update(datos)
        ), mock.patch(
            "toolbox.jornada_plan.next_lock", return_value=(AHORA + timedelta(hours=20)).isoformat()
        ):
            primera = ar.revisar(tablero(xi=9), AHORA, enviar=enviar)
            segunda = ar.revisar(tablero(xi=9), AHORA + timedelta(minutes=5), enviar=enviar)
        self.assertEqual(len(primera), 1)
        self.assertEqual(segunda, [])
        enviar.assert_called_once()


if __name__ == "__main__":
    unittest.main()

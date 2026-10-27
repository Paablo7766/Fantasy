"""Latido del refresco: ``GET /api/refresh-status``.

El problema que resuelve: una pasada completa tarda ~30 min con la cadencia
humana y el proxy de Next corta el POST a los 5. Sin un estado legible, «está
descargando» y «se ha colgado» se pintan igual, y el usuario pulsa Actualizar
otra vez. Estas pruebas fijan las tres cosas que el panel necesita ver:
que corre, en qué fase, y cuántas llamadas lleva **esta** pasada.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox import api_meter


class RefreshStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        api_meter.reset()
        with server._refresh_status_lock:
            server._refresh_status.clear()
        self.client = TestClient(server.app)

    def tearDown(self) -> None:
        api_meter.reset()
        with server._refresh_status_lock:
            server._refresh_status.clear()

    def test_without_refresh_it_answers_ok_not_running(self) -> None:
        response = self.client.get("/api/refresh-status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "refresh-status")
        self.assertFalse(payload["running"])
        self.assertEqual(payload["calls"], 0)

    def test_running_refresh_reports_phase_calls_and_current_source(self) -> None:
        server._refresh_status_start("full", None)
        api_meter.record_call(url="https://fantasy-api.llt-services.com/api/v1/x", status=200)
        api_meter.record_call(url="https://www.futbolfantasy.com/x", status=200)
        # Un acierto de caché no es una petición: no infla ``calls``, pero sí
        # demuestra avance, así que se informa aparte en ``cache_hits``.
        api_meter.record_cache_hit(url="https://understat.com/y")
        server._refresh_status_phase("plantillas", "Plantillas de la liga")

        payload = self.client.get("/api/refresh-status").json()
        self.assertTrue(payload["running"])
        self.assertEqual(payload["phase"], "plantillas")
        self.assertEqual(payload["phase_label"], "Plantillas de la liga")
        self.assertEqual(payload["calls"], 2)
        self.assertEqual(payload["cache_hits"], 1)
        # El desglose sí lista la fuente que solo sirvió caché: en air-gap
        # todas las filas tienen ``calls == 0`` y aun así hay trabajo.
        rows = {row["id"]: row for row in payload["by_source"]}
        self.assertEqual(set(rows), {"laliga", "futbolfantasy", "understat"})
        self.assertEqual(rows["understat"]["calls"], 0)
        self.assertEqual(rows["understat"]["cache_hits"], 1)
        # ``current_label`` es la última actividad, sea red o caché: en air-gap
        # la única actividad posible es leer de disco, y ocultarla dejaría al
        # panel sin decir «en qué está».
        self.assertEqual(payload["current_label"], "Understat")
        self.assertNotIn("started_unix", payload)

    def test_air_gapped_pass_reports_zero_network_but_real_progress(self) -> None:
        """En air-gap no hay llamadas: el panel necesita otra prueba de avance.

        Es el modo por defecto (``LALIGA_ENV`` sin definir). Sin ``cache_hits``
        el panel solo podía decir «0 llamadas» durante toda la pasada, que se
        lee como «colgado» aunque esté leyendo el disco entero.
        """
        server._refresh_status_start("full", None)
        for url in (
            "https://fantasy-api.llt-services.com/api/v4/leagues/7/market",
            "https://www.futbolfantasy.com/jugadores",
            "https://www.analiticafantasy.com/x",
        ):
            api_meter.record_cache_hit(url=url)

        payload = self.client.get("/api/refresh-status").json()
        self.assertTrue(payload["running"])
        self.assertEqual(payload["calls"], 0)
        self.assertEqual(payload["cache_hits"], 3)
        # ``network`` explica por qué ``calls`` es 0: sin este campo el 0 es
        # indistinguible de una descarga colgada.
        self.assertFalse(payload["network"])
        self.assertGreater(len(payload["by_source"]), 0)

    def test_finished_refresh_tells_ok_and_error(self) -> None:
        server._refresh_status_start("core", None)
        server._refresh_status_finish(ok=True)
        payload = self.client.get("/api/refresh-status").json()
        # ``ok`` es el del documento; el resultado de la pasada va aparte para
        # que un refresco fallido no se pinte como correcto.
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["running"])
        self.assertTrue(payload["result_ok"])
        self.assertIsNone(payload["error"])

        server._refresh_status_start("core", None)
        server._refresh_status_finish(ok=False, error={"code": "rate_limited", "message": "429"})
        payload = self.client.get("/api/refresh-status").json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["running"])
        self.assertFalse(payload["result_ok"])
        self.assertEqual(payload["error"]["code"], "rate_limited")

    def test_calls_are_counted_only_since_this_pass(self) -> None:
        """Una llamada anterior al refresco no debe aparecer en su contador."""
        api_meter.record_call(url="https://fantasy-api.llt-services.com/api/v1/old", status=200)
        time.sleep(0.01)
        server._refresh_status_start("full", None)
        api_meter.record_call(url="https://fantasy-api.llt-services.com/api/v1/new", status=200)

        payload = self.client.get("/api/refresh-status").json()
        self.assertEqual(payload["calls"], 1)

    def test_status_endpoint_never_downloads(self) -> None:
        """Es RAM: ningún camino de este endpoint puede construir una foto."""
        server._refresh_status_start("full", None)
        with patch.object(server, "snapshot", side_effect=AssertionError("no debe leer el tablero")):
            with patch.object(server, "refresh_board", side_effect=AssertionError("no debe descargar")):
                response = self.client.get("/api/refresh-status")
        self.assertEqual(response.status_code, 200)

    def test_refresh_board_marks_the_pass_finished(self) -> None:
        """El latido lo enciende y lo apaga ``refresh_board``, no el endpoint."""

        def fake_load(league: str | None, fresh: bool) -> dict:
            # Dentro de la descarga el latido ya está en marcha.
            live = server.refresh_status_snapshot()
            self.assertTrue(live["running"])
            return {"dashboard_at": "2026-10-25T08:00:00+00:00", "market": {}, "squads": {}}

        with patch.object(server, "load_core_snapshot", side_effect=fake_load):
            server.refresh_board(None, tier="core")

        payload = server.refresh_status_snapshot()
        self.assertFalse(payload["running"])
        self.assertTrue(payload["result_ok"])

    def test_refresh_board_marks_the_error(self) -> None:
        with patch.object(server, "load_core_snapshot", side_effect=RuntimeError("fuente caída")):
            with self.assertRaises(RuntimeError):
                server.refresh_board(None, tier="core")

        payload = server.refresh_status_snapshot()
        self.assertFalse(payload["running"])
        self.assertFalse(payload["result_ok"])
        self.assertIn("fuente caída", payload["error"]["message"])

    def test_plan_refresh_keeps_one_beat_across_core_and_full(self) -> None:
        """Sin ``track_status=False`` el panel vería «terminado» entre las dos fotos."""
        seen: list[bool] = []

        def fake_core(league: str | None, fresh: bool) -> dict:
            seen.append(server.refresh_status_snapshot()["running"])
            return {"dashboard_at": "2026-10-25T08:00:00+00:00", "market": {}, "squads": {}}

        def fake_full(league: str | None, *, tier: str = "full", track_status: bool = True) -> dict:
            seen.append(server.refresh_status_snapshot()["running"])
            return {"dashboard_at": "2026-10-25T08:05:00+00:00", "market": {}, "squads": {}, "trends": {}}

        with patch.object(server, "load_core_snapshot", side_effect=fake_core):
            with patch.object(server, "refresh_board", side_effect=fake_full):
                response = self.client.post("/api/plan/refresh")

        self.assertEqual(response.status_code, 200)
        # En las dos pasadas el latido seguía encendido.
        self.assertEqual(seen, [True, True])
        self.assertFalse(server.refresh_status_snapshot()["running"])


if __name__ == "__main__":
    unittest.main()

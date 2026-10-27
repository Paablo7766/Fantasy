"""Salto controlado del air-gap: ``POST /api/local/force-refresh``.

Tres propiedades, en orden de importancia:

1. **El escudo vuelve a subir.** Siempre, también cuando la descarga falla o
   cuando el kill switch sale con ``SystemExit``. Un fallo que dejara
   ``LALIGA_ENV=production`` en ``os.environ`` convertiría el dashboard en un
   cliente permanente de LaLiga: el error exacto que el air-gap evita.
2. **Solo desde loopback.** Un túnel (Cloudflare, ngrok) llega como
   ``127.0.0.1``; las cabeceras de proxy lo delatan y se rechaza.
3. **Sin reentrada.** Dos clics no encienden dos pasadas de media hora.

Ninguna prueba abre un socket: ``refresh_board`` está parcheado y el
``conftest`` bloquea cualquier conexión que no sea loopback.
"""

from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox import net

FORCE_PATH = "/api/local/force-refresh"


class _ForceRefreshBase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(server.app)
        # El air-gap de partida: sin variable, ``net.environment()`` es
        # development. ``patch.dict`` vacía también el valor heredado de la
        # shell para que el ``finally`` tenga algo real que restaurar.
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("LALIGA_ENV", None)
        self.addCleanup(self._env.stop)
        reset = getattr(server, "_reset_force_refresh", None)
        if reset is not None:
            reset()
        with server._refresh_status_lock:  # noqa: SLF001 — estado de proceso
            server._refresh_status.clear()  # noqa: SLF001
        self.board = {
            "dashboard_at": "2026-10-25T09:00:00+00:00",
            "last_updated": "2026-10-25T09:00:00+00:00",
            "market": {"ok": True, "listings": []},
            "squads": {"ok": True, "squads": []},
            "trends": {"players": []},
        }
        # ``_plan_document`` arrastra medio motor; se sustituye por un
        # documento mínimo para que la prueba mida el air-gap, no el plan.
        self._plan = patch.object(
            server,
            "_plan_document",
            side_effect=lambda board: {"ok": True, "market": board.get("market")},
        )
        self._plan.start()
        self.addCleanup(self._plan.stop)

    def tearDown(self) -> None:
        os.environ.pop("LALIGA_ENV", None)
        net.reset_kill_switch()


class AirGapRestoreTests(_ForceRefreshBase):
    def test_success_leaves_the_process_out_of_production(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board) as refresh:
            response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 200)
        refresh.assert_called_once_with(None, tier="full")
        # La prueba que importa: fuera del endpoint el proceso está sellado.
        self.assertNotIn("LALIGA_ENV", os.environ)
        self.assertTrue(net.air_gapped())
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["endpoint"], FORCE_PATH)
        self.assertTrue(body["forced"])
        self.assertEqual(body["environment"], "development")
        self.assertTrue(body["air_gap_restored"])

    def test_environment_is_open_while_the_download_runs(self) -> None:
        seen: list[str] = []

        def spy(league, *, tier="full", track_status=True):
            seen.append(net.environment())
            return self.board

        with patch.object(server, "refresh_board", side_effect=spy):
            response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 200)
        # Dentro del vuelo la puerta está abierta: si no, el refresco moriría
        # en el primer GET con ``offline_miss``.
        self.assertEqual(seen, ["production"])

    def test_a_failed_download_still_restores_the_shield(self) -> None:
        with patch.object(server, "refresh_board", side_effect=RuntimeError("sin red")):
            response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "unexpected")
        self.assertNotIn("LALIGA_ENV", os.environ)
        self.assertTrue(net.air_gapped())

    def test_a_previous_production_value_is_restored_not_deleted(self) -> None:
        """En el VPS el proceso ya era producción: el salto no debe degradarlo."""
        with patch.dict(os.environ, {"LALIGA_ENV": "production"}):
            with patch.object(server, "refresh_board", return_value=self.board):
                with patch.object(net, "_ENV_FILE_LALIGA_ENV", ""):
                    response = self.client.post(FORCE_PATH)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(os.environ.get("LALIGA_ENV"), "production")

    def test_a_kill_switch_signal_does_not_take_the_dashboard_down(self) -> None:
        """Un ``SystemExit`` de ``net.py`` devuelve 423, no tumba uvicorn."""
        clean = {"tripped": False, "status": None, "reason": None}
        tripped = {"tripped": True, "status": 429, "reason": "bloqueo"}
        with patch.object(server, "refresh_board", side_effect=SystemExit(1)):
            with patch.object(server, "kill_switch_state", side_effect=[clean, tripped, tripped]):
                response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["error"]["code"], "kill_switch")
        self.assertNotIn("LALIGA_ENV", os.environ)

    def test_the_window_restores_even_if_the_caller_raises(self) -> None:
        """``production_window`` es un ``finally``, no un par de set/pop."""
        self.assertNotIn("LALIGA_ENV", os.environ)
        with self.assertRaises(RuntimeError):
            with server.production_window():
                self.assertEqual(net.environment(), "production")
                raise RuntimeError("boom")
        self.assertNotIn("LALIGA_ENV", os.environ)
        self.assertTrue(net.air_gapped())


class LocalOnlyTests(_ForceRefreshBase):
    def test_a_proxied_request_is_rejected_even_from_loopback(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board) as refresh:
            response = self.client.post(
                FORCE_PATH,
                headers={"cf-connecting-ip": "203.0.113.7"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "local_only")
        refresh.assert_not_called()
        self.assertNotIn("LALIGA_ENV", os.environ)

    def test_a_tunnel_header_always_wins(self) -> None:
        for header in ("cf-ray", "x-real-ip", "x-vercel-id", "forwarded"):
            with self.subTest(header=header):
                response = self.client.post(FORCE_PATH, headers={header: "203.0.113.7"})
                self.assertEqual(response.status_code, 403)

    def test_a_public_hop_in_x_forwarded_for_is_rejected(self) -> None:
        response = self.client.post(
            FORCE_PATH,
            headers={"x-forwarded-for": "203.0.113.7"},
        )
        self.assertEqual(response.status_code, 403)
        # Cadena mixta: el proxy local delante de un cliente remoto tampoco vale.
        response = self.client.post(
            FORCE_PATH,
            headers={"x-forwarded-for": "203.0.113.7, ::1"},
        )
        self.assertEqual(response.status_code, 403)

    def test_the_next_proxy_of_the_react_panel_is_accepted(self) -> None:
        """Next rellena ``x-forwarded-for`` con ``::1``: mañana el botón pasa."""
        with patch.object(server, "refresh_board", return_value=self.board):
            response = self.client.post(
                FORCE_PATH,
                headers={"x-forwarded-for": "::1"},
            )
        self.assertEqual(response.status_code, 200)

    def test_a_remote_client_is_rejected(self) -> None:
        with patch.object(server, "loopback_client", return_value=False):
            response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "local_only")

    def test_loopback_helper_accepts_testclient_and_localhost(self) -> None:
        class _Client:
            host = "127.0.0.1"

        class _Request:
            client = _Client()
            headers: dict[str, str] = {}

        self.assertTrue(server.loopback_client(_Request()))
        _Client.host = "203.0.113.9"
        self.assertFalse(server.loopback_client(_Request()))
        _Client.host = "::ffff:127.0.0.1"
        self.assertTrue(server.loopback_client(_Request()))


class ForceRefreshGuardTests(_ForceRefreshBase):
    def test_a_tripped_kill_switch_blocks_the_pass(self) -> None:
        with patch.object(
            server,
            "kill_switch_state",
            return_value={"tripped": True, "status": 401, "reason": "401"},
        ):
            with patch.object(server, "refresh_board", return_value=self.board) as refresh:
                response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 423)
        refresh.assert_not_called()

    def test_a_second_click_does_not_start_another_pass(self) -> None:
        release = threading.Event()

        def slow(league, *, tier="full", track_status=True):
            release.wait(10.0)
            return self.board

        with patch.object(server, "refresh_board", side_effect=slow) as refresh:
            outcome: dict[str, int] = {}

            def first() -> None:
                outcome["first"] = self.client.post(FORCE_PATH).status_code

            worker = threading.Thread(target=first)
            worker.start()
            # Una espera corta y acotada: no se duerme la suite, se deja que el
            # primer hilo marque ``_force_refresh_running``.
            for _ in range(200):
                if server._force_refresh_running:  # noqa: SLF001
                    break
                threading.Event().wait(0.005)
            second = self.client.post(FORCE_PATH)
            release.set()
            worker.join(10.0)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "already_running")
        self.assertEqual(outcome.get("first"), 200)
        self.assertEqual(refresh.call_count, 1)
        # El candado se suelta al terminar, no al responder.
        self.assertFalse(server._force_refresh_running)  # noqa: SLF001

    def test_offline_mode_is_not_bypassed(self) -> None:
        """``FANTASY_OFFLINE=1`` es más duro que ``LALIGA_ENV``: no se toca."""
        with patch.object(server, "offline_mode", return_value=True):
            with patch.object(server, "refresh_board", return_value=self.board) as refresh:
                response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "offline_forced")
        refresh.assert_not_called()

    def test_the_league_in_the_body_is_forwarded(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board) as refresh:
            response = self.client.post(FORCE_PATH, json={"league": " 018668579 "})
        self.assertEqual(response.status_code, 200)
        refresh.assert_called_once_with("018668579", tier="full")

    def test_the_heartbeat_is_left_to_the_refresh_itself(self) -> None:
        """El latido no se duplica: lo enciende y lo apaga ``refresh_board``.

        El endpoint no lo toca. Si lo abriera él, un fallo dentro del refresco
        dejaría el panel en «Actualizando…» para siempre y el botón bloqueado
        por ``already_running`` sin trabajo vivo detrás.
        """
        with patch.object(server, "refresh_board", return_value=self.board):
            response = self.client.post(FORCE_PATH)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(server.refresh_status_snapshot()["running"])

    def test_the_route_is_registered_on_the_app(self) -> None:
        paths = {getattr(route, "path", None) for route in server.app.routes}
        self.assertIn(FORCE_PATH, paths)


if __name__ == "__main__":
    unittest.main()

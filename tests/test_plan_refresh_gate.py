"""Candado del refresco manual cuando el backend es público.

El VPS publica el 8080 en Internet. ``POST /api/plan/refresh`` dispara la
misma pasada humana que el gatillo remoto, así que en el proceso publicado
tiene que pedir el mismo token; en local (air-gap) sigue abierto para no
romper el botón Actualizar del dashboard.

La puerta mira ``startup_production()`` —el valor congelado al importar— y no
``is_production()``, que cambia en caliente cuando ``production_window`` abre
la red: si mirase la variable viva, el primer POST convertiría el panel local
en «publicado» y el segundo se comería un 401 sin token.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox import net

TOKEN = "token-de-prueba"
REFRESH_PATH = "/api/plan/refresh"


class PlanRefreshGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(server.app)
        self.board = {
            "dashboard_at": "2026-10-24T18:00:00+00:00",
            "last_updated": "2026-10-24T18:00:00+00:00",
            "market": {"ok": True, "listings": []},
            "squads": {"ok": True, "squads": []},
            "trends": {"players": []},
        }

    def _post(self, **kwargs):
        with patch.object(server, "refresh_board", return_value=self.board):
            return self.client.post(REFRESH_PATH, **kwargs)

    def test_local_development_does_not_ask_for_a_token(self) -> None:
        with patch.dict(os.environ, {"REMOTE_REFRESH_TOKEN": TOKEN}):
            with patch.object(server, "startup_production", return_value=False):
                response = self._post()
        self.assertEqual(response.status_code, 200)

    def test_production_requires_the_token(self) -> None:
        with patch.dict(os.environ, {"REMOTE_REFRESH_TOKEN": TOKEN}):
            with patch.object(server, "startup_production", return_value=True):
                response = self._post()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_production_accepts_the_token(self) -> None:
        with patch.dict(os.environ, {"REMOTE_REFRESH_TOKEN": TOKEN}):
            with patch.object(server, "startup_production", return_value=True):
                response = self._post(headers={"X-Remote-Token": TOKEN})
        self.assertEqual(response.status_code, 200)

    def test_production_without_a_configured_token_refuses_everything(self) -> None:
        """Sin token configurado no hay «modo abierto»: 401, nunca 200."""
        with patch.dict(os.environ, {"REMOTE_REFRESH_TOKEN": ""}):
            with patch.object(server, "startup_production", return_value=True):
                response = self._post()
        self.assertEqual(response.status_code, 401)


class PlanRefreshOpensTheGateTests(unittest.TestCase):
    """El botón Actualizar es la única puerta: tiene que abrir la red de verdad.

    Sin ``production_window`` la pasada se resolvía entera contra el disco
    (``calls: 0``, ``cache_hits: 122``) y el panel servía la foto de ayer con
    la fecha de hoy. Es el fallo que hacía que «Actualizar» no cambiara nada.
    """

    def setUp(self) -> None:
        self.client = TestClient(server.app)
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("LALIGA_ENV", None)
        self.addCleanup(self._env.stop)
        self.addCleanup(net.reset_kill_switch)
        with server._refresh_status_lock:  # noqa: SLF001 — estado de proceso
            server._refresh_status.clear()  # noqa: SLF001
        self.board = {
            "dashboard_at": "2026-10-25T09:00:00+00:00",
            "market": {"ok": True, "listings": []},
            "squads": {"ok": True, "squads": []},
            "trends": {"players": []},
        }

    def test_the_download_runs_inside_the_production_window(self) -> None:
        seen: list[str] = []

        def spy(league, *, tier="full", track_status=True):
            seen.append(net.environment())
            return self.board

        with patch.object(server, "refresh_board", side_effect=spy):
            response = self.client.post(REFRESH_PATH)

        self.assertEqual(response.status_code, 200)
        # Rápida y completa, las dos con la puerta abierta.
        self.assertEqual(seen, ["production", "production"])

    def test_the_shield_goes_back_up_when_the_refresh_ends(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board):
            response = self.client.post(REFRESH_PATH)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("LALIGA_ENV", os.environ)
        self.assertTrue(net.air_gapped())

    def test_a_kill_switch_signal_does_not_take_the_backend_down(self) -> None:
        """Un ``SystemExit`` de ``net.py`` responde 423, no mata uvicorn."""
        tripped = {"tripped": True, "status": 429, "reason": "bloqueo"}
        with patch.object(server, "refresh_board", side_effect=SystemExit(1)):
            with patch.object(server, "kill_switch_state", return_value=tripped):
                response = self.client.post(REFRESH_PATH)
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["error"]["code"], "kill_switch")
        self.assertNotIn("LALIGA_ENV", os.environ)
        self.assertTrue(net.air_gapped())
        self.assertFalse(server.refresh_status_snapshot()["running"])


if __name__ == "__main__":
    unittest.main()

"""El token remoto solo lo exige el proceso que nació en producción.

Lo que se protege: ``Actualizar_Fantasy.bat`` deja ``LALIGA_ENV=production`` en
su consola y desde ahí arranca el panel. Si la puerta del refresco mirase la
variable *viva*, el botón «Actualizar» respondería ``401`` en el portátil y el
panel se quedaría con la foto vieja sin explicar por qué. El air-gap ya lo
respeta el ``production_window``: sin él, la pasada no sale a la red.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server

REFRESH_PATH = "/api/plan/refresh"


class RefreshGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(server.app)
        self._token = patch.dict(os.environ, {"REMOTE_REFRESH_TOKEN": "secreto"})
        self._token.start()
        self.addCleanup(self._token.stop)
        self._plan = patch.object(
            server,
            "_refresh",
            return_value={"dashboard_at": "2026-10-25T09:00:00+00:00"},
        )
        self._plan.start()
        self.addCleanup(self._plan.stop)
        self._document = patch.object(server, "_plan_document", return_value={"ok": True})
        self._document.start()
        self.addCleanup(self._document.stop)
        self._board = patch.object(server, "refresh_board", return_value={"market": {}})
        self._board.start()
        self.addCleanup(self._board.stop)
        self._status = patch.object(server, "_refresh_status_finish", return_value=None)
        self._status.start()
        self.addCleanup(self._status.stop)

    def test_a_local_process_with_a_production_shell_is_not_401(self) -> None:
        with patch.object(server, "startup_production", return_value=False):
            with patch.dict(os.environ, {"LALIGA_ENV": "production"}):
                response = self.client.post(REFRESH_PATH)
        self.assertEqual(response.status_code, 200)

    def test_the_published_process_still_requires_the_token(self) -> None:
        with patch.object(server, "startup_production", return_value=True):
            response = self.client.post(REFRESH_PATH)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_the_published_process_accepts_the_header(self) -> None:
        with patch.object(server, "startup_production", return_value=True):
            response = self.client.post(REFRESH_PATH, headers={"X-Remote-Token": "secreto"})
        self.assertEqual(response.status_code, 200)

    def test_startup_production_does_not_change_when_the_window_opens(self) -> None:
        """El dato se congela al importar: una petición no puede convertir el
        proceso local en el publicado a ojos de la siguiente."""
        before = server.startup_production()
        with server.production_window():
            self.assertEqual(server.startup_production(), before)
        self.assertEqual(server.startup_production(), before)


if __name__ == "__main__":
    unittest.main()

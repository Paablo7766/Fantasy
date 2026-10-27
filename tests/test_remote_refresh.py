"""Gatillo remoto del orquestador (``POST /api/remote/refresh``).

La regla que estas pruebas protegen: el móvil recibe un 202 en milisegundos y
la pasada humana sigue en un hilo aparte. Ninguna prueba abre un socket ni
espera la cadencia real.
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox import net

TOKEN = "token-de-prueba"


class _RemoteBase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(server.app)
        self._env = patch.dict(
            "os.environ",
            {"REMOTE_REFRESH_TOKEN": TOKEN, "LALIGA_ENV": "production"},
        )
        self._env.start()
        self._reset_job()
        # La foto de mentira que devolvería un refresco terminado.
        self.board = {
            "dashboard_at": "2026-10-24T18:00:00+00:00",
            "last_updated": "2026-10-24T18:00:00+00:00",
            "photo_age_seconds": 0.0,
            "market": {"ok": True, "listings": []},
            "squads": {"ok": True, "squads": []},
            "trends": {"players": []},
        }

    def tearDown(self) -> None:
        self._env.stop()
        net.reset_human_pacer()
        self._reset_job()

    @staticmethod
    def _reset_job() -> None:
        with server._remote_lock:  # noqa: SLF001 — la prueba monta el estado
            server._remote_job = None  # noqa: SLF001

    def _wait_for_status(self, status: str, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with server._remote_lock:  # noqa: SLF001
                job = dict(server._remote_job) if server._remote_job else None  # noqa: SLF001
            if job is not None and job.get("status") == status:
                return job
            time.sleep(0.01)
        self.fail(f"El trabajo no llegó a {status}: {job}")


class RemoteRefreshAuthTests(_RemoteBase):
    def test_without_configured_token_the_trigger_is_disabled(self) -> None:
        with patch.dict("os.environ", {"REMOTE_REFRESH_TOKEN": ""}):
            response = self.client.post("/api/remote/refresh", json={"target_minutes": 60})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "remote_disabled")

    def test_missing_header_is_rejected(self) -> None:
        response = self.client.post("/api/remote/refresh", json={"target_minutes": 60})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_wrong_header_is_rejected(self) -> None:
        response = self.client.post(
            "/api/remote/refresh",
            json={"target_minutes": 60},
            headers={"X-Remote-Token": "otro"},
        )
        self.assertEqual(response.status_code, 401)

    def test_status_endpoint_also_requires_the_token(self) -> None:
        self.assertEqual(self.client.get("/api/remote/refresh").status_code, 401)
        response = self.client.get("/api/remote/refresh", headers={"X-Remote-Token": TOKEN})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["job"])


class RemoteRefreshValidationTests(_RemoteBase):
    def test_non_numeric_target_minutes_is_rejected(self) -> None:
        response = self.client.post(
            "/api/remote/refresh",
            json={"target_minutes": "una hora"},
            headers={"X-Remote-Token": TOKEN},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_target_minutes")

    def test_boolean_target_minutes_is_rejected(self) -> None:
        response = self.client.post(
            "/api/remote/refresh",
            json={"target_minutes": True},
            headers={"X-Remote-Token": TOKEN},
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_tier_is_rejected(self) -> None:
        response = self.client.post(
            "/api/remote/refresh",
            json={"target_minutes": 60, "tier": "todo"},
            headers={"X-Remote-Token": TOKEN},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_tier")

    def test_air_gapped_process_refuses_instead_of_queueing_a_doomed_job(self) -> None:
        with patch.object(server, "is_production", return_value=False):
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "air_gapped")

    def test_a_tripped_kill_switch_blocks_new_passes(self) -> None:
        """Reintentar contra una IP ya marcada es lo que convierte sospecha en baneo."""
        with patch.object(
            server,
            "kill_switch_state",
            return_value={"tripped": True, "status": 429, "reason": "bloqueo"},
        ):
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["error"]["code"], "kill_switch")


class RemoteRefreshBackgroundTests(_RemoteBase):
    def test_accepted_returns_202_without_waiting_for_the_refresh(self) -> None:
        release = threading.Event()

        def slow_refresh(league, *, tier="full"):
            release.wait(10.0)
            return self.board

        with patch.object(server, "refresh_board", side_effect=slow_refresh):
            started = time.monotonic()
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
            elapsed = time.monotonic() - started
            self.assertEqual(response.status_code, 202)
            body = response.json()
            self.assertTrue(body["accepted"])
            self.assertEqual(body["status"], "started")
            self.assertEqual(body["job"]["status"], "running")
            # El refresco sigue bloqueado en el evento: si el endpoint esperase,
            # esta prueba no terminaría nunca.
            self.assertLess(elapsed, 2.0)
            release.set()
        job = self._wait_for_status("done")
        self.assertTrue(job["ok"])

    def test_target_minutes_stretches_the_pacer_instead_of_rushing_it(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board) as refresh:
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(response.status_code, 202)
            # El factor se calcula, no se deja al azar: 60 min frente a la
            # cadencia de fábrica para ~60 GET.
            self.assertGreater(response.json()["job"]["pace_stretch"], 1.0)
            self._wait_for_status("done")
        refresh.assert_called_once()
        # Terminado el trabajo, el pacer vuelve a la cadencia de fábrica: el
        # siguiente refresco no hereda un presupuesto ajeno.
        self.assertEqual(net.HUMAN_PACER.stretch_factor, 1.0)

    def test_a_short_budget_never_compresses_the_anti_waf_floor(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board):
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 5},
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["job"]["pace_stretch"], 1.0)
            self._wait_for_status("done")

    def test_second_trigger_while_running_does_not_start_another_pass(self) -> None:
        release = threading.Event()

        def slow_refresh(league, *, tier="full"):
            release.wait(10.0)
            return self.board

        with patch.object(server, "refresh_board", side_effect=slow_refresh) as refresh:
            first = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
            second = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(first.status_code, 202)
            self.assertEqual(second.status_code, 202)
            self.assertEqual(second.json()["status"], "already_running")
            self.assertEqual(first.json()["job"]["job_id"], second.json()["job"]["job_id"])
            release.set()
        self._wait_for_status("done")
        # Un solo vuelo: el segundo gatillo no encendió otra pasada.
        self.assertEqual(refresh.call_count, 1)

    def test_a_failed_refresh_is_reported_and_frees_the_trigger(self) -> None:
        with patch.object(server, "refresh_board", side_effect=RuntimeError("sin red")):
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(response.status_code, 202)
            job = self._wait_for_status("failed")
        self.assertFalse(job["ok"])
        self.assertEqual(job["error"]["code"], "unexpected")
        # Un fallo no deja el gatillo bloqueado para siempre.
        with patch.object(server, "refresh_board", return_value=self.board):
            again = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 60},
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(again.json()["status"], "started")
            self._wait_for_status("done")

    def test_core_tier_and_league_are_forwarded(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board) as refresh:
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 30, "tier": "core", "league": " 018668579 "},
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(response.status_code, 202)
            self._wait_for_status("done")
        refresh.assert_called_once_with("018668579", tier="core")

    def test_missing_payload_uses_the_default_budget(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board):
            response = self.client.post(
                "/api/remote/refresh",
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["job"]["target_minutes"], 60.0)
            self._wait_for_status("done")

    def test_huge_budget_is_clamped(self) -> None:
        with patch.object(server, "refresh_board", return_value=self.board):
            response = self.client.post(
                "/api/remote/refresh",
                json={"target_minutes": 9999},
                headers={"X-Remote-Token": TOKEN},
            )
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["job"]["target_minutes"], server.REMOTE_MAX_MINUTES)
            self._wait_for_status("done")

    def test_a_kill_switch_in_the_worker_takes_the_process_down(self) -> None:
        """``sys.exit`` en un hilo solo mata el hilo: hay que cerrar el proceso.

        Sin esto, el VPS seguiría sirviendo la foto vieja con la IP ya marcada,
        que es justo lo que el contrato del kill switch prohíbe.
        """
        killed = threading.Event()

        def fake_kill() -> None:
            killed.set()

        with patch.object(server, "refresh_board", side_effect=SystemExit(1)):
            with patch.object(server, "_kill_process_from_worker", side_effect=fake_kill):
                response = self.client.post(
                    "/api/remote/refresh",
                    json={"target_minutes": 60},
                    headers={"X-Remote-Token": TOKEN},
                )
                self.assertEqual(response.status_code, 202)
                job = self._wait_for_status("kill_switch")
                self.assertTrue(killed.wait(5.0), "el proceso no se habría cerrado")
        self.assertFalse(job["ok"])
        self.assertEqual(job["error"]["code"], "kill_switch")


class PaceStretchTests(unittest.TestCase):
    """El presupuesto alarga la cadencia; nunca la acorta."""

    def test_no_budget_means_factory_cadence(self) -> None:
        self.assertEqual(net.pace_stretch_for(0.0, expected_requests=60), 1.0)

    def test_generous_budget_stretches_the_pauses(self) -> None:
        """El factor lleva la pasada al presupuesto, pausas de actividad incluidas."""
        factor = net.pace_stretch_for(60 * 60.0, expected_requests=60)
        self.assertGreater(factor, 1.5)
        # La propiedad que importa: 60 min de presupuesto dan 60 min de pasada.
        stretched = net.expected_pass_seconds(60) * factor
        self.assertAlmostEqual(stretched / 60.0, 60.0, delta=2.0)

    def test_tight_budget_does_not_compress_below_the_floor(self) -> None:
        self.assertEqual(net.pace_stretch_for(60.0, expected_requests=60), 1.0)

    def test_pacer_applies_and_resets_the_factor(self) -> None:
        pacer = net.HumanPacer(rng=__import__("random").Random(7))
        base, _ = pacer.next_delay()
        pacer.reset()
        pacer.stretch_to(60 * 60.0, expected_requests=60)
        stretched, _ = pacer.next_delay()
        self.assertGreater(stretched, base)
        pacer.reset_stretch()
        self.assertEqual(pacer.stretch_factor, 1.0)


if __name__ == "__main__":
    unittest.main()

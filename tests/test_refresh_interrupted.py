"""Una descarga cortada por un reinicio de Render se dice y se avisa al móvil.

Antes el hilo moría con el proceso, el nuevo decía «nada en marcha» y el panel
recargaba la foto vieja sin error ni push.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import server
from toolbox import snapshot_remote
from toolbox.cache import LocalSupabase


def _flush_marks() -> None:
    server._refresh_mark_pool.submit(lambda: None).result(timeout=5)


def _put_mark(**fields) -> None:
    mark = {
        "running": True,
        "tier": "full",
        "league": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "started_unix": time.time() - 60,
        "finished_at": None,
        "result_ok": None,
        "error": None,
        "boot_id": "proceso-anterior",
    }
    mark.update(fields)
    snapshot_remote.save(
        server.REFRESH_MARK_KIND,
        server.REFRESH_MARK_LEAGUE,
        {"saved_unix": time.time(), "value": mark},
    )


class RefreshInterruptedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"FANTASY_CACHE_DIR": str(Path(self.tmp.name) / "disk")})
        env.start()
        self.addCleanup(env.stop)
        snapshot_remote._reset_for_tests()
        remote_root = Path(self.tmp.name) / "remote"
        snapshot_remote._client_factory = lambda: LocalSupabase(remote_root)
        self.addCleanup(snapshot_remote._reset_for_tests)
        with server._refresh_status_lock:
            server._refresh_status.clear()
        self.addCleanup(server._refresh_status.clear)
        notify = mock.patch.object(server.web_push, "notify_refresh_done")
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def test_inicio_y_fin_dejan_marca(self) -> None:
        server._refresh_status_start("full", None)
        _flush_marks()
        mark = server._refresh_mark_load()
        self.assertTrue(mark["running"])
        self.assertEqual(mark["boot_id"], server._BOOT_ID)
        server._refresh_status_finish(ok=True)
        _flush_marks()
        snapshot_remote._last_miss.clear()
        mark = server._refresh_mark_load()
        self.assertFalse(mark["running"])
        self.assertTrue(mark["result_ok"])

    def test_pasada_cortada_se_dice_y_avisa(self) -> None:
        _put_mark()
        verdict = server.check_interrupted_refresh(wait_seconds=0)
        self.assertEqual(verdict, "interrupted")
        status = server.refresh_status_snapshot()
        self.assertIs(status["running"], False)
        self.assertIs(status["result_ok"], False)
        self.assertEqual(status["error"]["code"], "interrupted")
        self.notify.assert_called_once()
        self.assertIs(self.notify.call_args.kwargs["ok"], False)
        _flush_marks()
        snapshot_remote._last_miss.clear()
        self.assertFalse(server._refresh_mark_load()["running"], "la marca queda cerrada: no avisa dos veces")
        self.assertIsNone(server.check_interrupted_refresh(wait_seconds=0))
        self.notify.assert_called_once()

    def test_mientras_comprueba_el_latido_sigue_en_marcha(self) -> None:
        _put_mark()
        seen: dict = {}

        def fake_sleep(_seconds: float) -> None:
            seen.update(server.refresh_status_snapshot())

        with mock.patch.object(server.time, "sleep", fake_sleep):
            server.check_interrupted_refresh(wait_seconds=1)
        self.assertIs(seen["running"], True, "el panel no debe dar por buena la foto vieja")
        self.assertEqual(seen["phase"], "reinicio")

    def test_el_proceso_viejo_termino_a_tiempo(self) -> None:
        _put_mark()

        def old_process_finishes(_seconds: float) -> None:
            _put_mark(
                running=False,
                result_ok=True,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )

        with mock.patch.object(server.time, "sleep", old_process_finishes), mock.patch.object(
            server, "clear_snapshot_cache"
        ) as clear:
            verdict = server.check_interrupted_refresh(wait_seconds=1)
        self.assertEqual(verdict, "finished_elsewhere")
        self.assertIs(server.refresh_status_snapshot()["result_ok"], True)
        clear.assert_called_once()
        self.notify.assert_not_called()

    def test_marca_propia_o_cerrada_no_hace_nada(self) -> None:
        _put_mark(boot_id=server._BOOT_ID)
        self.assertIsNone(server.check_interrupted_refresh(wait_seconds=0))
        _put_mark(running=False, result_ok=True)
        snapshot_remote._last_miss.clear()
        self.assertIsNone(server.check_interrupted_refresh(wait_seconds=0))
        self.notify.assert_not_called()

    def test_marca_de_hace_horas_no_manda_aviso(self) -> None:
        _put_mark(started_unix=time.time() - 10 * 3600)
        self.assertEqual(server.check_interrupted_refresh(wait_seconds=0), "interrupted")
        self.notify.assert_not_called()

    def test_sin_supabase_no_hace_nada(self) -> None:
        snapshot_remote._client_factory = None
        server._refresh_status_start("full", None)
        self.assertIsNone(server.check_interrupted_refresh(wait_seconds=0))


if __name__ == "__main__":
    unittest.main()

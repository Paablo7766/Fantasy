"""Redespliegues de Render: la descarga en curso termina, o se dice que se cortó.

Antes el hilo moría con el proceso, el nuevo decía «nada en marcha» y el panel
recargaba la foto vieja sin error ni push.
"""

from __future__ import annotations

import os
import tempfile
import threading
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

    def tearDown(self) -> None:
        server._draining.clear()

    def test_inicio_y_fin_dejan_marca(self) -> None:
        server._refresh_status_start("full", None)
        _flush_marks()
        mark = server._refresh_mark_load()
        self.assertTrue(mark["running"])
        self.assertEqual(mark["boot_id"], server._BOOT_ID)
        self.assertIsInstance(mark["alive_unix"], float)
        server._refresh_status_finish(ok=True)
        _flush_marks()
        mark = server._refresh_mark_load()
        self.assertFalse(mark["running"])
        self.assertTrue(mark["result_ok"])

    def test_fin_correcto_suelta_las_vistas_de_la_foto_vieja(self) -> None:
        with server._PHOTO_MEMO_LOCK:
            server._PHOTO_MEMO[("top4", None, "foto-vieja")] = {"ok": True}
        with mock.patch.object(server, "release_memory") as release:
            server._refresh_status_start("full", None)
            server._refresh_status_finish(ok=True)
        _flush_marks()
        self.assertEqual(server._PHOTO_MEMO, {})
        self.assertGreaterEqual(release.call_count, 2)

    def test_fin_fallido_conserva_las_vistas(self) -> None:
        key = ("top4", None, "foto-buena")
        with server._PHOTO_MEMO_LOCK:
            server._PHOTO_MEMO[key] = {"ok": True}
        self.addCleanup(server._PHOTO_MEMO.pop, key, None)
        server._refresh_status_start("full", None)
        server._refresh_status_finish(ok=False, error={"code": "x"})
        _flush_marks()
        self.assertIn(key, server._PHOTO_MEMO)

    def test_el_latido_dice_sigo_vivo_con_la_fase(self) -> None:
        with mock.patch.object(server.snapshot_remote, "enabled", return_value=False):
            started = server._refresh_status_start("full", None)["started_unix"]
        server._refresh_status_phase("plantillas", "Plantillas de la liga")
        calls = {"n": 0}

        def fake_sleep(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                server._refresh_status_finish(ok=True)

        with mock.patch.object(server.time, "sleep", fake_sleep):
            server._refresh_heartbeat_loop(started)
        _flush_marks()
        self.assertEqual(calls["n"], 2, "el latido para en cuanto la pasada termina")

    def test_proceso_muerto_se_dice_y_avisa(self) -> None:
        _put_mark(alive_unix=time.time() - 120)
        verdict = server.check_interrupted_refresh(poll_seconds=0)
        self.assertEqual(verdict, "interrupted")
        status = server.refresh_status_snapshot()
        self.assertIs(status["running"], False)
        self.assertIs(status["result_ok"], False)
        self.assertEqual(status["error"]["code"], "interrupted")
        self.notify.assert_called_once()
        self.assertIs(self.notify.call_args.kwargs["ok"], False)
        _flush_marks()
        self.assertFalse(server._refresh_mark_load()["running"], "la marca queda cerrada: no avisa dos veces")
        self.assertIsNone(server.check_interrupted_refresh(poll_seconds=0))
        self.notify.assert_called_once()

    def test_el_corte_guarda_fase_memoria_y_fuente(self) -> None:
        memory = {"rss_mb": 480, "container_mb": 505, "limit_mb": 512}
        _put_mark(
            alive_unix=time.time() - 120, phase="scrapers", memory=memory, current_source="sofascore"
        )
        server.check_interrupted_refresh(poll_seconds=0)
        status = server.refresh_status_snapshot()
        self.assertEqual(status["cut_phase"], "scrapers")
        self.assertEqual(status["cut_memory"], memory)
        self.assertEqual(status["cut_source"], "sofascore")
        _flush_marks()
        mark = server._refresh_mark_load()
        self.assertEqual(mark["cut_phase"], "scrapers")
        self.assertEqual(mark["cut_source"], "sofascore")

    def test_proceso_viejo_vivo_se_espera_y_su_foto_se_sirve(self) -> None:
        _put_mark(alive_unix=time.time(), phase="mercado", phase_label="Mercado de LALIGA")
        seen: list[dict] = []
        calls = {"n": 0}

        def old_process(_seconds: float) -> None:
            calls["n"] += 1
            seen.append(server.refresh_status_snapshot())
            if calls["n"] == 1:
                _put_mark(alive_unix=time.time(), phase="plantillas", phase_label="Plantillas de la liga")
            else:
                _put_mark(running=False, result_ok=True, finished_at=datetime.now(timezone.utc).isoformat())

        with mock.patch.object(server.time, "sleep", old_process), mock.patch.object(
            server, "clear_snapshot_cache"
        ) as clear:
            verdict = server.check_interrupted_refresh(poll_seconds=1)
        self.assertEqual(verdict, "finished_elsewhere")
        self.assertTrue(all(s["running"] is True for s in seen), "el panel sigue esperando mientras late")
        self.assertEqual(seen[0]["phase"], "mercado")
        self.assertEqual(seen[1]["phase"], "plantillas")
        self.assertIs(server.refresh_status_snapshot()["result_ok"], True)
        clear.assert_called_once()
        self.notify.assert_not_called()

    def test_proceso_viejo_deja_de_latir(self) -> None:
        _put_mark(alive_unix=time.time())

        def killed(_seconds: float) -> None:
            _put_mark(alive_unix=time.time() - 100)

        with mock.patch.object(server.time, "sleep", killed):
            verdict = server.check_interrupted_refresh(poll_seconds=1)
        self.assertEqual(verdict, "interrupted")
        self.notify.assert_called_once()

    def test_techo_de_espera(self) -> None:
        _put_mark(alive_unix=time.time())
        self.assertEqual(server.check_interrupted_refresh(poll_seconds=0, max_wait_seconds=0), "interrupted")

    def test_marca_propia_o_cerrada_no_hace_nada(self) -> None:
        _put_mark(boot_id=server._BOOT_ID)
        self.assertIsNone(server.check_interrupted_refresh(poll_seconds=0))
        _put_mark(running=False, result_ok=True)
        self.assertIsNone(server.check_interrupted_refresh(poll_seconds=0))
        self.notify.assert_not_called()

    def test_marca_de_hace_horas_no_manda_aviso(self) -> None:
        _put_mark(started_unix=time.time() - 10 * 3600, alive_unix=time.time() - 10 * 3600)
        self.assertEqual(server.check_interrupted_refresh(poll_seconds=0), "interrupted")
        self.notify.assert_not_called()

    def test_sin_supabase_no_hace_nada(self) -> None:
        snapshot_remote._client_factory = None
        server._refresh_status_start("full", None)
        self.assertIsNone(server.check_interrupted_refresh(poll_seconds=0))

    def test_apagado_espera_a_que_termine_la_descarga(self) -> None:
        snapshot_remote._client_factory = None
        server._refresh_status_start("full", None)
        finisher = threading.Timer(0.3, lambda: server._refresh_status_finish(ok=True))
        finisher.start()
        self.addCleanup(finisher.cancel)
        self.assertTrue(server.drain_refresh_on_shutdown(5.0))
        self.assertIs(server.refresh_status_snapshot()["result_ok"], True)
        self.notify.assert_called_once_with(ok=True)

    def test_apagado_con_techo_no_se_cuelga(self) -> None:
        snapshot_remote._client_factory = None
        server._refresh_status_start("full", None)
        t0 = time.monotonic()
        self.assertFalse(server.drain_refresh_on_shutdown(0.2))
        self.assertLess(time.monotonic() - t0, 5.0)

    def test_apagandose_no_calienta_antes_del_aviso(self) -> None:
        snapshot_remote._client_factory = None
        server._refresh_status_start("full", None)
        server._draining.set()
        with mock.patch.object(server.web_push, "enabled", return_value=True), mock.patch.object(
            server, "_prewarm_then_notify"
        ) as prewarm:
            server._refresh_status_finish(ok=True)
        prewarm.assert_not_called()
        self.notify.assert_called_once_with(ok=True)

    def test_en_local_el_apagado_no_espera(self) -> None:
        with mock.patch.dict(os.environ, {"SHUTDOWN_DRAIN_SECONDS": ""}), mock.patch.object(
            server, "startup_production", return_value=False
        ):
            self.assertEqual(server._shutdown_drain_seconds(), 0.0)
        with mock.patch.dict(os.environ, {"SHUTDOWN_DRAIN_SECONDS": ""}), mock.patch.object(
            server, "startup_production", return_value=True
        ):
            self.assertEqual(server._shutdown_drain_seconds(), server.SHUTDOWN_DRAIN_DEFAULT_SECONDS)


if __name__ == "__main__":
    unittest.main()

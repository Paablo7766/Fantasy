"""La foto del tablero sobrevive a un despliegue que vacía el disco."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server
from toolbox import snapshot_remote
from toolbox.cache import LocalSupabase

BOARD = {
    "market": {"listings": [{"player_id": "1"}]},
    "squads": {"squads": [{"team_id": "t", "players": []}]},
}


class SnapshotRemoteTests(unittest.TestCase):
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

    def test_sobrevive_a_un_disco_vacio(self) -> None:
        server._write_disk_snapshot("core", "7", BOARD)
        path = server._disk_snapshot_path("core", "7")
        self.assertTrue(path.is_file())
        path.unlink()  # despliegue nuevo: el disco vuelve vacío
        restored = server._read_disk_snapshot("core", "7")
        self.assertEqual(restored, BOARD)
        self.assertTrue(path.is_file(), "la foto restaurada vuelve a estar en disco")

    def test_sin_copia_remota_no_inventa_nada(self) -> None:
        self.assertIsNone(server._read_disk_snapshot("core", "7"))

    def test_fallo_remoto_no_rompe_la_descarga(self) -> None:
        def boom() -> None:
            raise RuntimeError("sin red")

        snapshot_remote._client_factory = boom
        server._write_disk_snapshot("core", "7", BOARD)
        self.assertEqual(server._read_disk_snapshot("core", "7"), BOARD)
        server._disk_snapshot_path("core", "7").unlink()
        self.assertIsNone(server._read_disk_snapshot("core", "7"))

    def test_foto_vacia_no_se_copia(self) -> None:
        server._write_disk_snapshot("core", "7", {"market": {}, "squads": {}})
        self.assertIsNone(snapshot_remote.load("core", "7"))

    def test_desactivado_sin_supabase(self) -> None:
        snapshot_remote._client_factory = None
        self.assertFalse(snapshot_remote.enabled())
        self.assertFalse(snapshot_remote.save("core", "7", {"saved_unix": 1.0, "value": BOARD}))


if __name__ == "__main__":
    unittest.main()

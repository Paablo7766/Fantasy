"""Escritura de vínculos en bloque: misma semántica que ``put_link`` uno a uno."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from toolbox.cache import EntityStore


def _link(player_id: str, name: str) -> dict:
    return {
        "player_id": player_id,
        "external_name": name,
        "external_id": None,
        "club": "Betis",
        "position": "MC",
        "confidence": 0.95,
    }


class EntityStoreBulkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = EntityStore(Path(self._dir.name))

    def test_no_pisa_un_vinculo_manual(self) -> None:
        self.store.put_link(
            player_id="1",
            source="fuente",
            external_name="Manual",
            external_id=None,
            club=None,
            position=None,
            confidence=1.0,
            manual=True,
        )
        self.store.put_auto_links("fuente", [_link("1", "Auto"), _link("2", "Otro")])
        self.assertEqual(self.store.get_link("1", "fuente")["external_name"], "Manual")
        self.assertTrue(self.store.get_link("1", "fuente")["manual"])
        self.assertEqual(self.store.get_link("2", "fuente")["external_name"], "Otro")

    def test_borra_la_auditoria_del_jugador_vinculado(self) -> None:
        self.store.put_audits(
            "fuente",
            [
                {"player_id": "2", "external_name": "X", "candidate_name": "Y", "confidence": 0.5, "reason": "low_confidence"},
                {"player_id": "3", "external_name": "Z", "candidate_name": "W", "confidence": 0.5, "reason": "low_confidence"},
            ],
        )
        self.store.put_auto_links("fuente", [_link("2", "Otro")])
        self.assertEqual([row["player_id"] for row in self.store.list_audits()], ["3"])

    def test_clear_auto_conserva_manuales_y_otras_fuentes(self) -> None:
        self.store.put_link(
            player_id="1",
            source="fuente",
            external_name="Manual",
            external_id=None,
            club=None,
            position=None,
            confidence=1.0,
            manual=True,
        )
        self.store.put_auto_links("fuente", [_link("2", "Auto")])
        self.store.put_auto_links("otra", [_link("2", "Auto")])
        self.store.clear_auto("fuente")
        self.assertIsNotNone(self.store.get_link("1", "fuente"))
        self.assertIsNone(self.store.get_link("2", "fuente"))
        self.assertIsNotNone(self.store.get_link("2", "otra"))


if __name__ == "__main__":
    unittest.main()

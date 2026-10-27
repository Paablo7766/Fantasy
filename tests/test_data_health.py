"""Salud por campo: TTL, caducidad y severidad. Sin red."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from toolbox.data_health import SOURCE_CATALOG, build_field_health
from toolbox.scrapers import FF_MARKET_URL


def _sources(**overrides: dict) -> dict:
    """Catálogo completo en OK; el test solo cambia la fuente que le importa."""
    base = {str(spec["id"]): {"ok": True, "count": 1} for spec in SOURCE_CATALOG}
    base["fbref"] = {"ok": False, "error": "403"}
    base.update(overrides)
    return base


class FieldHealthTests(unittest.TestCase):
    def test_sources_missing_are_not_invented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = build_field_health(_sources(), root=Path(tmp))
        by_id = {row["id"]: row for row in document["fields"]}
        self.assertEqual(by_id["futbolfantasy_market"]["status"], "ok")
        self.assertEqual(by_id["fbref"]["status"], "error")
        document = build_field_health({}, root=Path(tmp))
        by_id = {row["id"]: row for row in document["fields"]}
        self.assertEqual(by_id["understat"]["status"], "no_leida")

    def test_optional_failure_is_warn_not_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = build_field_health(_sources(), root=Path(tmp))
        self.assertEqual(document["status"], "warn")
        self.assertEqual(document["critical_broken"], [])
        self.assertEqual(document["broken"], ["fbref"])

    def test_critical_error_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = build_field_health(
                _sources(analiticafantasy_points={"ok": False, "error": "timeout"}),
                root=Path(tmp),
            )
        self.assertEqual(document["status"], "fail")
        self.assertIn("analiticafantasy_points", document["critical_broken"])

    def test_critical_expired_is_warn_not_blindness(self) -> None:
        """Caducada no es ceguera: el dato existe y solo pide refresco."""
        sources = _sources()
        sources.pop("analiticafantasy_points")
        with tempfile.TemporaryDirectory() as tmp:
            document = build_field_health(
                sources,
                root=Path(tmp),
                extra={"analiticafantasy_points": {"ok": True, "ttl_seconds": 60, "expires_in_seconds": -5}},
            )
        self.assertEqual(document["status"], "warn")
        self.assertIn("analiticafantasy_points", document["stale_critical"])
        self.assertEqual(document["critical_broken"], [])

    def test_extra_supplies_ttl_without_cache_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = build_field_health(
                {},
                root=Path(tmp),
                extra={"laliga_market": {"ok": True, "count": 34, "ttl_seconds": 300, "expires_in_seconds": 271}},
            )
        by_id = {row["id"]: row for row in document["fields"]}
        self.assertEqual(by_id["laliga_market"]["status"], "ok")
        self.assertEqual(by_id["laliga_market"]["ttl_label"], "5 min")
        self.assertEqual(by_id["laliga_market"]["expires_label"], "caduca en 4 min")

    def test_cache_body_marks_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bodies = root / "scraper_bodies"
            bodies.mkdir()
            (bodies / hashlib.sha256(FF_MARKET_URL.encode("utf-8")).hexdigest()).write_text(
                json.dumps({"body": "<html/>", "expires_at": time.time() - 30}),
                encoding="utf-8",
            )
            document = build_field_health(_sources(), root=root)
        by_id = {row["id"]: row for row in document["fields"]}
        self.assertEqual(by_id["futbolfantasy_market"]["status"], "caducada")
        self.assertEqual(by_id["futbolfantasy_market"]["expires_label"], "caducada")


if __name__ == "__main__":
    unittest.main()

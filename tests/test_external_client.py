from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from toolbox.cache import ResponseCache, cache_key
from toolbox.net import ExternalClient, ExternalHttpError


class ExternalClientStaleFallbackTests(unittest.TestCase):
    def test_serves_expired_cache_when_upstream_forbidden(self) -> None:
        url = "https://fbref.com/en/comps/12/shooting/La-Liga-Stats"
        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            cache.put_page(url, "<html>cached stats</html>", 1.0)
            path = cache.root / "scraper_bodies" / cache_key(url)
            import json
            import time

            row = json.loads(path.read_text(encoding="utf-8"))
            row["expires_at"] = time.time() - 60
            path.write_text(json.dumps(row), encoding="utf-8")

            def handler(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(403, text="denied")

            transport = httpx.MockTransport(handler)
            with ExternalClient(cache=cache, http=httpx.Client(transport=transport)) as client:
                body, from_cache = client.get_text(url, ttl=3600.0, fresh=True)
            cache.close()

        self.assertEqual(body, "<html>cached stats</html>")
        self.assertTrue(from_cache)

    def test_optional_sources_do_not_mark_trends_partial(self) -> None:
        from toolbox.scrapers import _optional_sources_degraded, _trends_partial

        sources = {
            "understat": {"ok": True},
            "fbref": {"ok": False},
            "sofascore": {"ok": False},
            "transfermarkt": {"ok": False},
        }
        self.assertFalse(_trends_partial(sources))
        self.assertTrue(_optional_sources_degraded(sources))
        sources["futbolfantasy_market"] = {"ok": False}
        self.assertTrue(_trends_partial(sources))

    def test_fetch_json_uses_browser_on_forbidden(self) -> None:
        from unittest.mock import patch

        from toolbox.scrapers import _fetch_json

        url = "https://api.sofascore.com/api/v1/unique-tournament/8/season/77559/top-players/overall"
        payload = {"topPlayers": {"rating": [{"player": {"name": "Test"}, "statistics": {"rating": 7.1}}]}}
        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            transport = httpx.MockTransport(lambda _r: httpx.Response(403, text="denied"))
            with ExternalClient(cache=cache, http=httpx.Client(transport=transport)) as client:
                with patch(
                    "toolbox.browser_scrape.fetch_json_with_browser",
                    return_value=(payload, "{}"),
                ):
                    got, cached, err = _fetch_json(client, url, ttl=3600.0, fresh=True)
            cache.close()
        self.assertIsNone(err)
        self.assertFalse(cached)
        self.assertEqual(got, payload)


if __name__ == "__main__":
    unittest.main()

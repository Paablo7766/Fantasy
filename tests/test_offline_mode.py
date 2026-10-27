"""Modo avión: con ``FANTASY_OFFLINE=1`` no sale ni una petición a la red.

El transporte de ``httpx`` es un ``MockTransport`` que falla el test si se le
llama: así se demuestra tráfico cero, no solo que la respuesta venga de caché.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from toolbox import net
from toolbox.cache import ResponseCache, cache_key
from toolbox.net import (
    OFFLINE_MISS_CODE,
    ExternalClient,
    ExternalHttpError,
    FantasyHttpError,
    LaligaClient,
)

LALIGA_URL = "https://fantasy-api.llt-services.com/api/v4/leagues/7/market?x-lang=es"
LALIGA_ALT_URL = "https://api-fantasy.llt-services.com/api/v4/leagues/7/market?x-lang=es"
FBREF_URL = "https://fbref.com/en/comps/12/shooting/La-Liga-Stats"


class _Tokens:
    def authorization_value(self) -> str:
        return "Bearer test-token"

    def force_refresh(self) -> str:
        return "Bearer fresh-token"


def _expire(cache: ResponseCache, url: str) -> None:
    """Deja la entrada en disco con la fecha caducada, sin borrarla."""
    path = cache.root / "scraper_bodies" / cache_key(url)
    row = json.loads(path.read_text(encoding="utf-8"))
    row["expires_at"] = time.time() - 60.0
    path.write_text(json.dumps(row), encoding="utf-8")


class _OfflineFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._offline = patch.dict("os.environ", {"FANTASY_OFFLINE": "1"})
        self._offline.start()
        self.addCleanup(self._offline.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = ResponseCache(Path(directory.name))
        self.addCleanup(self.cache.close)
        self.calls = 0

    def _transport(self, request: httpx.Request) -> httpx.Response:
        # Cualquier petición que llegue aquí es un fallo del modo avión.
        self.calls += 1
        raise AssertionError(f"Modo avión: no debería salir {request.method} {request.url}")

    def _laliga(self) -> LaligaClient:
        http = httpx.Client(transport=httpx.MockTransport(self._transport))
        self.addCleanup(http.close)
        return LaligaClient(tokens=_Tokens(), cache=self.cache, http=http, jitter=False)

    def _external(self) -> ExternalClient:
        http = httpx.Client(transport=httpx.MockTransport(self._transport))
        self.addCleanup(http.close)
        return ExternalClient(cache=self.cache, http=http)


class OfflineModeFlagTests(unittest.TestCase):
    def _neutral(self) -> None:
        """Aísla la bandera del ``.env`` real del proyecto."""
        for name, value in (("_ENV_FILE_OFFLINE", False), ("OFFLINE_MODE", False)):
            patcher = patch.object(net, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _uncached(self) -> None:
        """Deja la bandera del ``.env`` sin resolver para que se lea el fichero."""
        for name, value in (("_ENV_FILE_OFFLINE", None), ("OFFLINE_MODE", False)):
            patcher = patch.object(net, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_constant_reads_the_environment(self) -> None:
        self._neutral()
        with patch.dict("os.environ", {"FANTASY_OFFLINE": "1"}):
            self.assertTrue(net.offline_mode())
        with patch.dict("os.environ", {"FANTASY_OFFLINE": "0"}):
            self.assertFalse(net.offline_mode())
        with patch.dict("os.environ", {"FANTASY_OFFLINE": ""}):
            self.assertFalse(net.offline_mode())

    def test_constant_exists_at_import_time(self) -> None:
        self.assertIsInstance(net.OFFLINE_MODE, bool)

    def test_the_env_file_is_read_when_the_process_env_has_no_flag(self) -> None:
        self._uncached()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("LEAGUE_ID=7\nFANTASY_OFFLINE=1\n", encoding="utf-8")
            with patch.dict("os.environ", {"FANTASY_OFFLINE": ""}):
                with patch("toolbox.project_root", return_value=root):
                    self.assertTrue(net.offline_mode())

    def test_a_quoted_value_in_the_env_file_also_counts(self) -> None:
        self._uncached()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text('FANTASY_OFFLINE="1"\n', encoding="utf-8")
            with patch.dict("os.environ", {"FANTASY_OFFLINE": ""}):
                with patch("toolbox.project_root", return_value=root):
                    self.assertTrue(net.offline_mode())

    def test_an_env_file_without_the_flag_keeps_the_network_on(self) -> None:
        self._uncached()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("LEAGUE_ID=7\n", encoding="utf-8")
            with patch.dict("os.environ", {"FANTASY_OFFLINE": ""}):
                with patch("toolbox.project_root", return_value=root):
                    self.assertFalse(net.offline_mode())

    def test_an_explicit_zero_in_the_environment_beats_the_env_file(self) -> None:
        """El contenedor declara FANTASY_OFFLINE=0 y el .env montado puede decir 1.

        Si el fichero mandara, el VPS arrancaría sellado y el gatillo remoto no
        tendría red: ningún refresco funcionaría y el fallo sería silencioso.
        """
        self._uncached()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("FANTASY_OFFLINE=1\n", encoding="utf-8")
            with patch.dict("os.environ", {"FANTASY_OFFLINE": "0"}):
                with patch("toolbox.project_root", return_value=root):
                    self.assertFalse(net.offline_mode())


class LaligaOfflineTests(_OfflineFixture):
    def test_serves_the_expired_copy_even_with_fresh_true(self) -> None:
        payload = {"elements": [{"id": "m1", "salePrice": 13000000}]}
        self.cache.put_json(LALIGA_URL, payload, 60)
        _expire(self.cache, LALIGA_URL)

        client = self._laliga()
        self.assertEqual(client.get_json(LALIGA_URL, ttl=1, fresh=True), payload)
        self.assertEqual(self.calls, 0)

    def test_a_zero_ttl_request_still_hits_the_disk_copy(self) -> None:
        self.cache.put_json(LALIGA_URL, {"elements": [{"id": "m1"}]}, 60)
        _expire(self.cache, LALIGA_URL)

        client = self._laliga()
        self.assertEqual(client.get_json(LALIGA_URL, ttl=0, fresh=True), {"elements": [{"id": "m1"}]})
        self.assertEqual(self.calls, 0)

    def test_a_missing_cache_entry_raises_503_without_touching_the_network(self) -> None:
        client = self._laliga()
        with self.assertRaises(FantasyHttpError) as raised:
            client.get_json(LALIGA_URL, ttl=60, fresh=False)

        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(raised.exception.code, OFFLINE_MISS_CODE)
        self.assertIn("Offline mode", str(raised.exception))
        self.assertEqual(self.calls, 0)

    def test_first_matching_falls_through_to_the_cached_host(self) -> None:
        self.cache.put_json(LALIGA_ALT_URL, {"elements": [{"id": "viejo"}]}, 60)
        _expire(self.cache, LALIGA_ALT_URL)

        client = self._laliga()
        source, payload = client._first_matching(
            [LALIGA_URL, LALIGA_ALT_URL],
            ttl=0,
            fresh=True,
            accept=lambda body: bool(body.get("elements")),
        )

        self.assertEqual(source, LALIGA_ALT_URL)
        self.assertEqual(payload["elements"][0]["id"], "viejo")
        self.assertEqual(self.calls, 0)

    def test_first_matching_without_any_copy_still_raises_503(self) -> None:
        client = self._laliga()
        with self.assertRaises(FantasyHttpError) as raised:
            client._first_matching(
                [LALIGA_URL, LALIGA_ALT_URL],
                ttl=0,
                fresh=True,
                accept=lambda body: bool(body.get("elements")),
            )
        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(self.calls, 0)

    def test_send_itself_refuses_to_leave(self) -> None:
        client = self._laliga()
        with self.assertRaises(FantasyHttpError) as raised:
            client._send(LALIGA_URL)
        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(self.calls, 0)

    def test_market_document_works_only_from_cache(self) -> None:
        leagues = [{"id": "7", "name": "Mi liga", "team": {"id": "3"}}]
        market = {"elements": [{"id": "m1", "playerMaster": {"id": 8, "nickname": "Courtois"}, "salePrice": 1}]}
        self.cache.put_json(net.league_list_urls()[0], leagues, 60)
        self.cache.put_json(net.market_urls("7")[0], market, 60)
        _expire(self.cache, net.league_list_urls()[0])
        _expire(self.cache, net.market_urls("7")[0])

        with patch.object(net.LaligaClient, "image_index", return_value={}):
            document = self._laliga().market_document("7", fresh=True)

        self.assertEqual(document["league_id"], "7")
        self.assertEqual(len(document["listings"]), 1)
        self.assertEqual(self.calls, 0)


class ExternalOfflineTests(_OfflineFixture):
    def test_get_text_serves_the_expired_page(self) -> None:
        self.cache.put_page(FBREF_URL, "<html>cached stats</html>", 60)
        _expire(self.cache, FBREF_URL)

        with self._external() as client:
            body, from_cache = client.get_text(FBREF_URL, ttl=1, fresh=True)

        self.assertEqual(body, "<html>cached stats</html>")
        self.assertTrue(from_cache)
        self.assertEqual(self.calls, 0)

    def test_get_json_serves_the_expired_payload(self) -> None:
        payload = {"topPlayers": {"rating": [{"player": {"name": "Test"}}]}}
        self.cache.put_json(FBREF_URL, payload, 60)
        _expire(self.cache, FBREF_URL)

        with self._external() as client:
            got, from_cache = client.get_json(FBREF_URL, ttl=1, fresh=True)

        self.assertEqual(got, payload)
        self.assertTrue(from_cache)
        self.assertEqual(self.calls, 0)

    def test_get_text_without_cache_raises_503(self) -> None:
        with self._external() as client:
            with self.assertRaises(ExternalHttpError) as raised:
                client.get_text(FBREF_URL, ttl=60, fresh=True)

        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(raised.exception.code, OFFLINE_MISS_CODE)
        self.assertEqual(self.calls, 0)

    def test_browser_scrape_is_disabled_too(self) -> None:
        from toolbox import browser_scrape

        with patch.dict("os.environ", {"FANTASY_SCRAPER_BROWSER": "1"}):
            self.assertIsNone(browser_scrape.render_with_browser(FBREF_URL))
            self.assertEqual(browser_scrape.fetch_json_with_browser(FBREF_URL), (None, None))

    def test_optional_sources_degrade_instead_of_raising(self) -> None:
        from toolbox.scrapers import _fetch_json, _fetch_text

        with self._external() as client:
            body, cached, error = _fetch_text(client, FBREF_URL, ttl=60.0, fresh=True)
            payload, json_cached, json_error = _fetch_json(client, FBREF_URL, ttl=60.0, fresh=True)

        self.assertIsNone(body)
        self.assertFalse(cached)
        self.assertIn("Offline mode", error or "")
        self.assertIsNone(payload)
        self.assertFalse(json_cached)
        self.assertIn("Offline mode", json_error or "")
        self.assertEqual(self.calls, 0)


class NetworkVetoThreadTests(unittest.TestCase):
    """El veto de lectura tiene que sobrevivir al salto de hilo de un pool.

    ``contextvars`` no viaja solo a los workers de ``ThreadPoolExecutor``: cada
    uno arranca con el contexto por defecto. Sin ``inherited()`` un ``GET``
    vetado recuperaba el permiso de red en cuanto delegaba en un pool, que es
    justo lo que hacía el enriquecimiento del once en lectura.
    """

    def test_a_pool_worker_inherits_the_veto(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        seen: list[bool] = []

        def probe() -> bool:
            seen.append(net.network_forbidden())
            return net.network_forbidden()

        with net.no_network():
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertTrue(pool.submit(net.inherited(probe)).result(timeout=5))

        self.assertEqual(seen, [True])

    def test_a_pool_worker_without_the_veto_keeps_the_network(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertFalse(pool.submit(net.inherited(net.network_forbidden)).result(timeout=5))

    def test_the_veto_does_not_leak_out_of_the_task(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            with net.no_network():
                pool.submit(net.inherited(net.network_forbidden)).result(timeout=5)
            # El worker queda limpio: la misma tarea, ya sin veto, puede salir.
            self.assertFalse(pool.submit(net.inherited(net.network_forbidden)).result(timeout=5))

    def test_a_vetoed_pool_request_never_reaches_the_transport(self) -> None:
        """La prueba de fuego: lectura vetada + pool = cero peticiones."""
        calls = 0

        def transport(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise AssertionError(f"El veto no cortó {request.url}")

        http = httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(http.close)
        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            self.addCleanup(cache.close)
            client = ExternalClient(cache=cache, http=http)
            with net.no_network():
                with self.assertRaises(ExternalHttpError):
                    net.inherited(client.get_text)(FBREF_URL, ttl=0.0, fresh=True)
        self.assertEqual(calls, 0)

    def test_the_real_lineup_loader_stays_offline_when_vetoed(self) -> None:
        """``load_lineups`` abre su propio pool: era la fuga del enriquecimiento.

        Es el camino real de lectura: ``GET /api/optimize`` →
        ``_patch_optimize_titularity`` → ``refresh_squad_titularity_in_index``
        → ``load_lineups``. Antes del arreglo, sus dos workers recuperaban el
        permiso de red y el GET acababa descargando.
        """
        from toolbox.fantasy_scraper import load_lineups

        calls = 0

        def transport(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, text="<html></html>")

        http = httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(http.close)
        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            self.addCleanup(cache.close)
            client = ExternalClient(cache=cache, http=http)
            with net.no_network():
                _sources, rows = load_lineups(client, ttl=0.0, fresh=False)

        # Sin copia en disco, cada fuente degrada a lista vacía en vez de salir.
        self.assertEqual(rows, [])
        self.assertEqual(calls, 0)

    def test_the_same_loader_does_reach_the_transport_without_the_veto(self) -> None:
        """Control: sin veto, la misma llamada sí sale (el veto es lo que frena)."""
        from toolbox.fantasy_scraper import load_lineups

        calls = 0

        def transport(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, text="<html></html>")

        http = httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(http.close)
        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            self.addCleanup(cache.close)
            client = ExternalClient(cache=cache, http=http)
            load_lineups(client, ttl=0.0, fresh=False)

        self.assertGreater(calls, 0)


class OfflineTokenTests(unittest.TestCase):
    def test_refreshing_the_token_is_blocked(self) -> None:
        from toolbox.auth import AuthError, TokenManager

        with patch.dict(
            "os.environ",
            {"FANTASY_OFFLINE": "1", "LALIGA_REFRESH_TOKEN": "refresh", "LALIGA_ACCESS_TOKEN": ""},
            clear=False,
        ):
            with patch("toolbox.auth._load_env"):
                with patch("toolbox.auth.httpx.post") as post:
                    with self.assertRaises(AuthError) as raised:
                        TokenManager().authorization_value()

        self.assertEqual(raised.exception.code, "offline")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Air-gap del catálogo: ni un socket hacia LaLiga fuera de producción.

El requisito es duro: con ``LALIGA_ENV`` distinto de ``production`` el cliente
no puede abrir una conexión al dominio de la liga y solo sirve lo que ya está
en ``.cache/``. Si no hay copia, ``OfflineCacheError`` (503). Estas pruebas
fijan ese contrato en los tres puntos donde podría romperse: la fábrica de
sesión, el envío y el refresco manual del catálogo.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from toolbox import net
from toolbox.cache import ResponseCache
from toolbox.net import (
    OfflineCacheError,
    PLAYERS_TTL_SECONDS,
    LaligaClient,
    air_gapped,
    close_official_session,
    environment,
    is_production,
    official_session,
)


class FakeTokens:
    def authorization_value(self) -> str:
        return "Bearer test-token"

    def refresh(self) -> str:
        return "Bearer refreshed"


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.cache = ResponseCache(self.root)
        self.addCleanup(self.cache.close)
        # ``air_gapped()`` mira el entorno y el ``.env``; se fija aquí para que
        # la prueba no dependa de la máquina donde corre.
        env = patch.dict("os.environ", {"LALIGA_ENV": "development", "FANTASY_OFFLINE": "0"})
        env.start()
        self.addCleanup(env.stop)
        net._ENV_FILE_LALIGA_ENV = ""

    def _client(self, http: httpx.Client | None = None) -> LaligaClient:
        return LaligaClient(tokens=FakeTokens(), cache=self.cache, http=http, sleeper=lambda _s: None)


class EnvironmentTests(unittest.TestCase):
    def test_development_is_the_default(self) -> None:
        with patch.dict("os.environ", {"LALIGA_ENV": ""}):
            with patch.object(net, "_ENV_FILE_LALIGA_ENV", ""):
                self.assertEqual(environment(), "development")
                self.assertTrue(air_gapped())
                self.assertFalse(is_production())

    def test_production_opens_the_gate(self) -> None:
        with patch.dict("os.environ", {"LALIGA_ENV": "production"}):
            self.assertFalse(air_gapped())
            self.assertTrue(is_production())

    def test_any_other_value_stays_gated(self) -> None:
        for value in ("staging", "PROD", "test", "development"):
            with patch.dict("os.environ", {"LALIGA_ENV": value}):
                self.assertTrue(air_gapped(), value)


class SessionFactoryTests(_Fixture):
    def test_no_session_is_built_outside_production(self) -> None:
        close_official_session()
        with self.assertRaises(net.FantasyHttpError) as caught:
            official_session()
        self.assertEqual(caught.exception.code, "air_gapped")

    def test_client_has_no_http_object_in_development(self) -> None:
        client = self._client()
        self.assertIsNone(client._http)

    def test_real_transport_is_rejected_outside_production(self) -> None:
        real = httpx.Client()
        self.addCleanup(real.close)
        with self.assertRaises(net.FantasyHttpError) as caught:
            LaligaClient(tokens=FakeTokens(), cache=self.cache, http=real)
        self.assertEqual(caught.exception.code, "air_gapped")


class OfflineServeTests(_Fixture):
    URL = "https://fantasy-api.llt-services.com/api/v1/competition/1/players"

    def test_missing_cache_raises_offline_cache_error(self) -> None:
        client = self._client()
        with self.assertRaises(OfflineCacheError) as caught:
            client.get_json(self.URL, ttl=0, fresh=True)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, net.OFFLINE_MISS_CODE)

    def test_offline_cache_error_is_a_http_error(self) -> None:
        # La capa de arriba captura ``FantasyHttpError``; si esto dejara de
        # heredar, un catálogo sin caché sería un 500 en vez de un 503 claro.
        self.assertTrue(issubclass(OfflineCacheError, net.FantasyHttpError))

    def test_cached_body_is_served_without_network(self) -> None:
        self.cache.put_json(self.URL, [{"id": "1"}], 3600)
        client = self._client()
        payload = client.get_json(self.URL, ttl=0, fresh=True)
        self.assertEqual(payload, [{"id": "1"}])

    def test_fresh_is_ignored_in_air_gap(self) -> None:
        self.cache.put_json(self.URL, [{"id": "old"}], 1)
        time.sleep(0.01)  # deja la entrada caducada
        client = self._client()
        # ``fresh=True`` no debe intentar red: devuelve la copia y punto.
        self.assertEqual(client.get_json(self.URL, ttl=0, fresh=True), [{"id": "old"}])

    def test_send_refuses_even_if_called_directly(self) -> None:
        client = self._client()
        with self.assertRaises(OfflineCacheError):
            client._send(self.URL)

    def test_entry_without_stored_at_reports_file_age(self) -> None:
        """Una entrada vieja sin ``stored_at`` no puede parecer recién escrita.

        Las copias guardadas antes de que existiera ese campo no llevan sello.
        Devolver ``None`` dejaba que el documento de mercado se fechara con la
        hora del proceso y el snapshot diario grababa el mismo precio con día
        nuevo: el motor leía una subida de 0 € que nunca ocurrió.
        """
        from toolbox.cache import _scraper_body_path, cache_key

        self.cache.put_json(self.URL, [{"id": "1"}], 86400)
        path = _scraper_body_path(self.root, cache_key(self.URL))
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry.pop("stored_at", None)
        path.write_text(json.dumps(entry), encoding="utf-8")
        captured = time.time() - 9 * 24 * 3600
        os.utime(path, (captured, captured))

        age = self.cache.age_seconds(self.URL)
        self.assertIsNotNone(age)
        self.assertGreater(age, 8 * 24 * 3600)
        self.assertLess(age, 10 * 24 * 3600)

    def test_entry_with_stored_at_prefers_the_stamp(self) -> None:
        """Con sello, la edad sale del sello y no del mtime del fichero."""
        from toolbox.cache import _scraper_body_path, cache_key

        self.cache.put_json(self.URL, [{"id": "1"}], 86400)
        captured = time.time() - 2 * 3600
        path = _scraper_body_path(self.root, cache_key(self.URL))
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["stored_at"] = captured
        path.write_text(json.dumps(entry), encoding="utf-8")
        os.utime(path, (time.time(), time.time()))

        age = self.cache.age_seconds(self.URL)
        self.assertIsNotNone(age)
        self.assertAlmostEqual(age, 2 * 3600, delta=60)

    def test_simulated_transport_still_works(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http.close)
        client = self._client(http=http)
        self.assertEqual(client.get_json(self.URL, ttl=0, fresh=True), {"ok": True})

    def test_injected_client_cannot_reach_other_hosts(self) -> None:
        client = self._client()
        with self.assertRaises(net.FantasyHttpError) as caught:
            client.get_json("https://evil.example.com/players", ttl=0, fresh=True)
        self.assertEqual(caught.exception.code, "forbidden_url")


class ManualRefreshTests(_Fixture):
    # La URL real del catálogo lleva ``?x-lang=es``; sembrar la caché con una
    # URL distinta probaría otra entrada y el TTL nunca daría «no toca».
    URL = net.players_urls()[0]
    # El catálogo se valida por forma: una fila sin ``image``/``positionId``
    # no es un catálogo y el cliente la rechaza aunque exista el fichero.
    ROWS = [{"id": "1", "positionId": "1", "image": "https://assets-fantasy.llt-services.com/p1.png"}]

    def test_ttl_is_six_hours(self) -> None:
        self.assertEqual(PLAYERS_TTL_SECONDS, 6 * 60 * 60)

    def test_refresh_due_without_cache(self) -> None:
        client = self._client()
        self.assertTrue(client.catalog_refresh_due())

    def test_refresh_not_due_with_fresh_cache(self) -> None:
        self.cache.put_json(self.URL, self.ROWS, PLAYERS_TTL_SECONDS)
        client = self._client()
        self.assertFalse(client.catalog_refresh_due())

    def test_refresh_due_after_ttl(self) -> None:
        self.cache.put_json(self.URL, self.ROWS, PLAYERS_TTL_SECONDS)
        client = self._client()
        future = time.time() + PLAYERS_TTL_SECONDS + 1
        self.assertTrue(client.catalog_refresh_due(now=future))

    def test_manual_refresh_does_not_hit_network_in_air_gap(self) -> None:
        self.cache.put_json(self.URL, self.ROWS, PLAYERS_TTL_SECONDS)
        client = self._client()
        # Pedir refresco manual en development no abre nada: devuelve la copia.
        self.assertEqual(client.catalog_refresh_document(force=True), self.ROWS)

    def test_manual_refresh_without_cache_raises(self) -> None:
        client = self._client()
        with self.assertRaises(OfflineCacheError):
            client.catalog_refresh_document(force=True)


if __name__ == "__main__":
    unittest.main()

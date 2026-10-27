"""Contrato de sigilo: las cuatro capas que protegen la cuenta de LALIGA.

Esta suite es el candado del contrato, no una prueba de implementación. Cada
clase cubre una capa y falla si alguien relaja el diseño:

1. ``AirGapTests``      — en development/test no se abre un socket, ni con
                          ``fresh=True``; sin copia en disco, ``offline_miss``.
2. ``PacingTests``      — 12–25 s por GET y una pausa de 45–90 s cada 3–4.
3. ``MimicryTests``     — una sola sesión ``curl_cffi`` con ``chrome110`` y
                          cabeceras inmutables y coherentes con el perfil.
4. ``KillSwitchTests``  — un 401/403/429/5xx mata el proceso sin reintentar y
                          deja el marcador en ``.cache/``.

Ninguna prueba abre un socket: ``tests/conftest.py`` parchea
``socket.connect`` para abortar cualquier conexión que no sea loopback.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import httpx

from toolbox import net
from toolbox.cache import ResponseCache
from toolbox.net import (
    ACTIVITY_PAUSE_EVERY_MAX,
    ACTIVITY_PAUSE_EVERY_MIN,
    ACTIVITY_PAUSE_MAX_SECONDS,
    ACTIVITY_PAUSE_MIN_SECONDS,
    HUMAN_DELAY_MAX_SECONDS,
    HUMAN_DELAY_MIN_SECONDS,
    HUMAN_REQUESTS_PER_REFRESH,
    KILL_SWITCH_STATUSES,
    REQUIRED_HEADERS,
    TLS_IMPERSONATE,
    HumanPacer,
    LaligaClient,
    environment,
    expected_pass_seconds,
    is_production,
    traffic_pacer,
)

URL = "https://fantasy-api.llt-services.com/api/v4/leagues/7/market?x-lang=es"


class _Tokens:
    def authorization_value(self) -> str:
        return "Bearer test-token"

    def force_refresh(self) -> str:
        return "Bearer fresh-token"


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        # El entorno y la caché se fijan por prueba: la suite no depende de la
        # máquina ni del ``.env`` de quien la ejecute.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cache = ResponseCache(self.root)
        self.addCleanup(self.cache.close)
        env = patch.dict(
            "os.environ",
            {"LALIGA_ENV": "development", "FANTASY_OFFLINE": "0", "FANTASY_NET_PACING": "0"},
        )
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(net.reset_kill_switch)
        self.addCleanup(net.reset_human_pacer)

    def _client(self, http: httpx.Client | None = None, *, jitter: bool = False) -> LaligaClient:
        return LaligaClient(
            tokens=_Tokens(),
            cache=self.cache,
            http=http,
            sleeper=lambda _seconds: None,
            jitter=jitter,
        )


# ---------------------------------------------------------------------------
# Capa 1: air-gap
# ---------------------------------------------------------------------------
class AirGapTests(_Fixture):
    def test_development_is_the_default_environment(self) -> None:
        with patch.dict("os.environ", {"LALIGA_ENV": ""}):
            with patch.object(net, "_ENV_FILE_LALIGA_ENV", ""):
                self.assertEqual(environment(), "development")
                self.assertFalse(is_production())
                self.assertTrue(net.air_gapped())

    def test_only_production_opens_the_gate(self) -> None:
        for value in ("", "development", "test", "staging", "PROD", "production "):
            with patch.dict("os.environ", {"LALIGA_ENV": value}):
                self.assertTrue(net.air_gapped() or value.strip() == "production", value)

    def test_no_http_object_is_built_in_development(self) -> None:
        self.assertIsNone(self._client()._http)

    def test_official_session_refuses_to_exist_outside_production(self) -> None:
        net.close_official_session()
        with self.assertRaises(net.FantasyHttpError) as caught:
            net.official_session()
        self.assertEqual(caught.exception.code, "air_gapped")

    def test_a_real_client_cannot_be_injected(self) -> None:
        real = httpx.Client()
        self.addCleanup(real.close)
        with self.assertRaises(net.FantasyHttpError) as caught:
            LaligaClient(tokens=_Tokens(), cache=self.cache, http=real)
        self.assertEqual(caught.exception.code, "air_gapped")

    def test_fresh_true_still_reads_only_the_disk(self) -> None:
        self.cache.put_json(URL, {"elements": [{"id": "ayer"}]}, 1)
        self.assertEqual(self._client().get_json(URL, ttl=0, fresh=True), {"elements": [{"id": "ayer"}]})

    def test_a_missing_file_is_a_clear_offline_error(self) -> None:
        with self.assertRaises(net.OfflineCacheError) as caught:
            self._client().get_json(URL, ttl=0, fresh=True)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, net.OFFLINE_MISS_CODE)

    def test_external_sources_are_gated_too(self) -> None:
        """El air-gap es del proceso: una fuente externa tampoco sale.

        ``scrapers.refresh_player_titularity`` construye su propio
        ``ExternalClient()``. Si ese cliente pudiera salir en development, la
        suite (y cualquier lectura del tablero) llamaría a FútbolFantasy sin
        que nadie lo hubiera pedido.
        """
        client = net.ExternalClient(cache=self.cache)
        self.addCleanup(client.close)
        self.assertIsNone(client._http)
        with self.assertRaises(net.ExternalHttpError) as caught:
            client.get_text("https://www.futbolfantasy.com/laliga/analisis", ttl=0, fresh=True)
        self.assertEqual(caught.exception.code, net.OFFLINE_MISS_CODE)


# ---------------------------------------------------------------------------
# Capa 2: cadencia de ultra-baja frecuencia
# ---------------------------------------------------------------------------
class PacingTests(unittest.TestCase):
    def test_the_base_wait_is_twelve_to_twentyfive_seconds(self) -> None:
        self.assertEqual(HUMAN_DELAY_MIN_SECONDS, 12.0)
        self.assertEqual(HUMAN_DELAY_MAX_SECONDS, 25.0)

    def test_the_activity_pause_is_three_to_four_requests_of_45_to_90s(self) -> None:
        self.assertEqual((ACTIVITY_PAUSE_EVERY_MIN, ACTIVITY_PAUSE_EVERY_MAX), (3, 4))
        self.assertEqual(ACTIVITY_PAUSE_MIN_SECONDS, 45.0)
        self.assertEqual(ACTIVITY_PAUSE_MAX_SECONDS, 90.0)

    def test_every_draw_stays_inside_its_band(self) -> None:
        pacer = HumanPacer()
        normal: list[float] = []
        pauses: list[float] = []
        for _ in range(400):
            delay, is_pause = pacer.next_delay()
            (pauses if is_pause else normal).append(delay)
        self.assertTrue(normal and pauses)
        self.assertGreaterEqual(min(normal), HUMAN_DELAY_MIN_SECONDS)
        self.assertLessEqual(max(normal), HUMAN_DELAY_MAX_SECONDS)
        self.assertGreaterEqual(min(pauses), ACTIVITY_PAUSE_MIN_SECONDS)
        self.assertLessEqual(max(pauses), ACTIVITY_PAUSE_MAX_SECONDS)

    def test_a_pause_lands_every_three_or_four_requests(self) -> None:
        pacer = HumanPacer()
        gaps: list[int] = []
        served = 0
        for _ in range(400):
            _delay, is_pause = pacer.next_delay()
            served += 1
            if is_pause:
                gaps.append(served)
                served = 0
        self.assertTrue(gaps)
        self.assertGreaterEqual(min(gaps), ACTIVITY_PAUSE_EVERY_MIN)
        self.assertLessEqual(max(gaps), ACTIVITY_PAUSE_EVERY_MAX)

    def test_a_pass_of_thirty_gets_takes_the_fifteen_to_twenty_minute_budget(self) -> None:
        """Con estas bandas, 15–20 min dan para ~27–37 GET (≈33 s por petición).

        Las bandas mandadas no caben 50 GET en 20 minutos: 50 × 12–25 s ya son
        10–21 min **sin** contar las pausas, y con una de 45–90 s cada 3–4 el
        suelo real son 18,8 min y la media ~33 s por GET. La pasada rápida
        (``core``, ~25–30 GET) es la que cae en el presupuesto de 15–20 min; la
        completa (``full``, ~60 GET) tarda unos 33 min, y es aceptable porque el
        refresco es nocturno y nadie lo espera.
        """
        pacer = HumanPacer(rng=random.Random(11))
        total = sum(pacer.next_delay()[0] for _ in range(30))
        self.assertGreaterEqual(total, 12 * 60)
        self.assertLessEqual(total, 21 * 60)

    def test_the_full_pass_is_slower_and_nothing_compresses_it(self) -> None:
        """~60 GET (tier ``full``) ronda la media hora larga: es lo esperado."""
        pacer = HumanPacer(rng=random.Random(11))
        total = sum(pacer.next_delay()[0] for _ in range(HUMAN_REQUESTS_PER_REFRESH))
        self.assertGreaterEqual(total, 26 * 60)
        self.assertLessEqual(total, 45 * 60)

    def test_the_slowest_possible_configuration_is_still_the_floor(self) -> None:
        """Ni con todos los mínimos a la vez se baja del suelo: no hay atajo.

        La pausa de actividad *sustituye* la espera de esa petición (no se
        suma) y con ``pause_every=3`` cae en los GET 3, 6, 9…: 16 pausas y 34
        esperas normales en 50 peticiones, es decir 18,8 min de suelo físico.
        """
        pacer = HumanPacer(
            minimum=HUMAN_DELAY_MIN_SECONDS,
            maximum=HUMAN_DELAY_MIN_SECONDS,
            pause_every=(ACTIVITY_PAUSE_EVERY_MIN, ACTIVITY_PAUSE_EVERY_MIN),
            pause_seconds=(ACTIVITY_PAUSE_MIN_SECONDS, ACTIVITY_PAUSE_MIN_SECONDS),
        )
        total = sum(pacer.next_delay()[0] for _ in range(50))
        pauses = 50 // ACTIVITY_PAUSE_EVERY_MIN
        normal = 50 - pauses
        self.assertAlmostEqual(
            total,
            normal * HUMAN_DELAY_MIN_SECONDS + pauses * ACTIVITY_PAUSE_MIN_SECONDS,
            delta=1.0,
        )
        self.assertGreaterEqual(total, 18 * 60)

    def test_the_first_request_also_waits(self) -> None:
        """No hay «primer GET gratis»: el patrón es el mismo desde el socket 1."""
        pacer = HumanPacer()
        delay, _pause = pacer.next_delay()
        self.assertGreaterEqual(delay, HUMAN_DELAY_MIN_SECONDS)

    def test_a_request_pays_the_pause_exactly_once(self) -> None:
        """La cadencia se paga una vez: dormirla también en ``pace_domain`` la duplicaba.

        El bug era invisible en las pruebas porque todas usan un ``sleeper``
        nulo; solo se veía en producción, donde cada GET habría esperado 12–25 s
        dos veces y la pasada completa se habría ido al doble del presupuesto.
        """
        slept: list[float] = []

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http.close)
        cache = ResponseCache(Path(tempfile.mkdtemp()))
        self.addCleanup(cache.close)
        client = LaligaClient(
            tokens=_Tokens(),
            cache=cache,
            http=http,
            sleeper=slept.append,
            jitter=True,
        )
        with patch.dict("os.environ", {"FANTASY_NET_PACING": "1"}):
            net.reset_rate_limits()
            client.get_json(URL, ttl=0, fresh=True)
        # Exactamente una espera, y dentro de la banda humana: la pausa de
        # actividad de 45–90 s también es válida aquí (cae cada 3–4 GET).
        self.assertEqual(len(slept), 1, slept)
        self.assertGreaterEqual(slept[0], HUMAN_DELAY_MIN_SECONDS)
        self.assertLessEqual(slept[0], ACTIVITY_PAUSE_MAX_SECONDS)

    def test_production_cannot_turn_the_pacing_off(self) -> None:
        with patch.dict("os.environ", {"LALIGA_ENV": "production", "FANTASY_NET_PACING": "0"}):
            self.assertTrue(net.pacing_enabled())

    def test_development_can_turn_it_off_for_tests(self) -> None:
        with patch.dict("os.environ", {"LALIGA_ENV": "development", "FANTASY_NET_PACING": "0"}):
            self.assertFalse(net.pacing_enabled())

    def test_there_is_a_single_process_wide_pacer(self) -> None:
        """El contador es de proceso: una instancia por cliente nunca pausaría."""
        self.assertIs(traffic_pacer(), traffic_pacer())
        self.assertIs(traffic_pacer(), net.HUMAN_PACER)

    def test_the_estimate_counts_the_activity_pauses(self) -> None:
        """Estimar 18,5 s/GET se dejaba fuera la pausa y erraba por casi 2×."""
        estimate = expected_pass_seconds(HUMAN_REQUESTS_PER_REFRESH)
        # ~33 s/GET con las pausas incluidas, no 18,5 s.
        self.assertGreater(estimate / HUMAN_REQUESTS_PER_REFRESH, 30.0)
        self.assertLess(estimate / HUMAN_REQUESTS_PER_REFRESH, 35.0)

    def test_a_generous_budget_lands_on_the_target_instead_of_doubling_it(self) -> None:
        """Un presupuesto de 60 min tiene que dar 60 min, no 106."""
        factor = net.pace_stretch_for(60 * 60.0, expected_requests=HUMAN_REQUESTS_PER_REFRESH)
        stretched = expected_pass_seconds(HUMAN_REQUESTS_PER_REFRESH) * factor
        self.assertAlmostEqual(stretched / 60.0, 60.0, delta=2.0)

    def test_official_calls_are_serialized_one_at_a_time(self) -> None:
        """Concurrencia 1 de verdad: la pausa y el GET van en el mismo cerrojo."""
        import threading
        import time as _time

        inside = 0
        peak = 0
        guard = threading.Lock()

        def worker() -> None:
            nonlocal inside, peak
            with net.laliga_serialized():
                with guard:
                    inside += 1
                    peak = max(peak, inside)
                _time.sleep(0.01)
                with guard:
                    inside -= 1

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)

        self.assertEqual(peak, 1)


# ---------------------------------------------------------------------------
# Capa 3: mimicry con curl_cffi
# ---------------------------------------------------------------------------
class MimicryTests(_Fixture):
    def test_the_tls_profile_is_a_real_chrome(self) -> None:
        self.assertEqual(TLS_IMPERSONATE, "chrome110")

    def test_headers_are_immutable(self) -> None:
        self.assertIsInstance(REQUIRED_HEADERS, MappingProxyType)
        with self.assertRaises(TypeError):
            REQUIRED_HEADERS["User-Agent"] = "python-requests/2.31"  # type: ignore[index]

    def test_the_fingerprint_and_the_user_agent_match(self) -> None:
        """Un JA3 de Chrome 110 con UA de iPhone es una firma de bot trivial."""
        ua = REQUIRED_HEADERS["User-Agent"]
        self.assertIn("Mozilla/5.0", ua)
        self.assertIn("Windows NT 10.0", ua)
        self.assertIn("Chrome/110.0.0.0", ua)
        self.assertNotIn("python", ua.lower())
        self.assertIn("es-ES", REQUIRED_HEADERS["Accept-Language"])
        self.assertIn("br", REQUIRED_HEADERS["Accept-Encoding"])

    def test_the_official_session_uses_curl_with_the_chrome_profile(self) -> None:
        with patch.dict("os.environ", {"LALIGA_ENV": "production"}):
            net.close_official_session()
            self.addCleanup(net.close_official_session)
            session = net.official_session()
            inner = session._session
            self.assertEqual(inner.impersonate, TLS_IMPERSONATE)
            self.assertTrue(getattr(inner, "headers", None))
            # Keep-alive: la sesión es de proceso y sobrevive entre llamadas.
            self.assertIs(net.official_session(), session)

    def test_the_session_only_exposes_read_methods(self) -> None:
        """La API oficial es de solo lectura: la forma más segura es no tener POST."""
        for method in ("post", "put", "patch", "delete"):
            self.assertFalse(hasattr(net.OfficialSession, method), method)


# ---------------------------------------------------------------------------
# Capa 4: kill switch
# ---------------------------------------------------------------------------
class KillSwitchTests(_Fixture):
    def _client_with(self, status: int) -> LaligaClient:
        http = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(status, json={})))
        self.addCleanup(http.close)
        return self._client(http)

    def test_the_alarm_statuses_are_the_documented_ones(self) -> None:
        self.assertEqual(KILL_SWITCH_STATUSES, frozenset({401, 403, 429}))

    def test_401_403_429_and_5xx_all_trip_it(self) -> None:
        for status in (401, 403, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                net.reset_kill_switch()
                client = self._client_with(status)
                with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
                    client.get_json(URL, ttl=0, fresh=True)
                self.assertEqual(net.kill_switch_state()["status"], status)

    def test_there_is_exactly_one_request_and_no_retry(self) -> None:
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http.close)
        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            self._client(http).get_json(URL, ttl=0, fresh=True)
        self.assertEqual(calls["n"], 1)

    def test_a_404_is_not_an_alarm(self) -> None:
        """Un recurso que no existe no es una acusación del WAF."""
        with self.assertRaises(net.FantasyHttpError) as caught:
            self._client_with(404).get_json(URL, ttl=0, fresh=True)
        self.assertEqual(caught.exception.code, "not_found")
        self.assertFalse(net.kill_switch_tripped())

    def test_it_leaves_a_marker_on_disk_before_dying(self) -> None:
        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            self._client_with(403).get_json(URL, ttl=0, fresh=True)
        marker = net.marker_path()
        self.assertTrue(marker.is_file())
        self.assertIn("403", marker.read_text(encoding="utf-8"))

    def test_it_exits_with_code_one_in_production(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            net.trip_kill_switch(status=429, url=URL)
        self.assertEqual(caught.exception.code, 1)

    def test_a_tripped_switch_always_exits_again(self) -> None:
        """No existe «ya lo apunté, sigo»: la segunda llamada también muere."""
        with self.assertRaises(SystemExit):
            net.trip_kill_switch(status=403, url=URL)
        with self.assertRaises(SystemExit):
            net.trip_kill_switch(status=403, url=URL)


if __name__ == "__main__":
    unittest.main()

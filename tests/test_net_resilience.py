"""Resiliencia del cliente de LALIGA: jitter, backoff 5xx y copia en disco.

Ninguna prueba toca la red: ``httpx.MockTransport`` sirve las respuestas y un
``sleeper`` que apunta lo pedido sustituye a ``time.sleep``, así que una espera
de ocho segundos no cuesta ocho segundos.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from toolbox import net
from toolbox.cache import ResponseCache, cache_key
from toolbox.net import (
    JITTER_MAX_SECONDS,
    JITTER_MIN_SECONDS,
    UPSTREAM_BACKOFF_BASE_SECONDS,
    UPSTREAM_BACKOFF_MAX_SECONDS,
    ExternalClient,
    FantasyHttpError,
    LaligaClient,
    upstream_backoff_delay,
)

URL = "https://fantasy-api.llt-services.com/api/v4/leagues/7/market?x-lang=es"
LEGACY_URL = "https://api-fantasy.llt-services.com/api/v4/leagues/7/market?x-lang=es"


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


class _ClientFixture(unittest.TestCase):
    """Cliente con ``MockTransport`` y un sleeper que solo apunta lo pedido.

    El controlador de tráfico se apaga aquí a propósito: estas pruebas miden el
    jitter y el backoff, y sus listas de esperas tienen que ser exactas. El
    espaciado por dominio tiene sus propias pruebas en ``TrafficControllerTests``.
    """

    def setUp(self) -> None:
        pacing = patch.dict("os.environ", {"FANTASY_NET_PACING": "0"})
        pacing.start()
        self.addCleanup(pacing.stop)
        net.reset_rate_limits()
        self.addCleanup(net.reset_rate_limits)

    def _build(
        self,
        handler,
        *,
        slept: list[float] | None = None,
        jitter: bool = True,
    ) -> tuple[LaligaClient, ResponseCache]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cache = ResponseCache(Path(directory.name))
        self.addCleanup(cache.close)
        http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        self.addCleanup(http.close)
        sleeps = slept if slept is not None else []
        client = LaligaClient(
            tokens=_Tokens(),
            cache=cache,
            http=http,
            sleeper=sleeps.append,
            jitter=jitter,
        )
        return client, cache


class HumanJitterTests(_ClientFixture):
    def test_send_pauses_before_the_get(self) -> None:
        seen_at_request: list[int] = []
        slept: list[float] = []

        def handler(_request: httpx.Request) -> httpx.Response:
            seen_at_request.append(len(slept))
            return httpx.Response(200, json={"ok": True})

        client, _cache = self._build(handler, slept=slept)
        self.assertEqual(client.get_json(URL, ttl=0, fresh=True), {"ok": True})

        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(slept[0], JITTER_MIN_SECONDS)
        self.assertLessEqual(slept[0], JITTER_MAX_SECONDS)
        # La pausa ocurrió antes de disparar la petición, no después.
        self.assertEqual(seen_at_request, [1])

    def test_jitter_can_be_switched_off(self) -> None:
        slept: list[float] = []
        client, _cache = self._build(
            lambda _request: httpx.Response(200, json={"ok": True}),
            slept=slept,
            jitter=False,
        )
        client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(slept, [])

    def test_a_rate_limit_kills_the_process_instead_of_retrying(self) -> None:
        """Un 429 no se reintenta: es la señal más clara de que hay que parar.

        El contrato anterior dormía ``Retry-After`` y volvía a pedir. Eso es
        justo lo que un WAF interpreta como insistencia, así que ahora el
        primer 429 cierra el proceso y deja el marcador en ``.cache/``.
        """
        slept: list[float] = []
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow"})

        client, _cache = self._build(handler, slept=slept)
        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client.get_json(URL, ttl=0, fresh=True)

        self.assertEqual(calls["n"], 1)
        # Ni un reintento: la única espera posible es la pausa humana previa.
        self.assertLessEqual(len(slept), 1)


class UpstreamBackoffTests(_ClientFixture):
    def test_delay_doubles_and_stops_at_the_ceiling(self) -> None:
        self.assertEqual(upstream_backoff_delay(0), UPSTREAM_BACKOFF_BASE_SECONDS)
        self.assertEqual(upstream_backoff_delay(1), UPSTREAM_BACKOFF_BASE_SECONDS * 2)
        self.assertEqual(upstream_backoff_delay(2), UPSTREAM_BACKOFF_BASE_SECONDS * 4)
        self.assertEqual(upstream_backoff_delay(3), UPSTREAM_BACKOFF_BASE_SECONDS * 8)
        self.assertEqual(upstream_backoff_delay(20), UPSTREAM_BACKOFF_MAX_SECONDS)

    def test_retry_after_wins_over_the_exponential_ramp(self) -> None:
        self.assertEqual(upstream_backoff_delay(0, "5"), 5.0)
        self.assertEqual(upstream_backoff_delay(3, "0"), 0.0)

    def test_upstream_retries_are_ignored_on_the_official_client(self) -> None:
        """``upstream_retries`` se acepta por compatibilidad y no hace nada.

        El backoff exponencial sigue existiendo para las fuentes externas, pero
        contra LaLiga un 5xx es una sola petición y el kill switch.
        """
        slept: list[float] = []
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, json={"error": "down"})

        client, _cache = self._build(handler, slept=slept, jitter=False)
        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client.get_json(URL, ttl=0, fresh=True, upstream_retries=3)

        self.assertEqual(calls["n"], 1)
        self.assertEqual(slept, [])

    def test_upstream_retry_after_is_ignored_on_the_official_client(self) -> None:
        slept: list[float] = []
        client, _cache = self._build(
            lambda _request: httpx.Response(502, headers={"Retry-After": "7"}, json={}),
            slept=slept,
            jitter=False,
        )
        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client.get_json(URL, ttl=0, fresh=True, upstream_retries=1)
        self.assertEqual(slept, [])


class StaleSurvivalTests(_ClientFixture):
    def test_a_5xx_trips_the_kill_switch_without_serving_the_cache(self) -> None:
        """Un 5xx ya no se «sortea» con la copia de ayer: se para.

        Antes se reintentaba y, si todo fallaba, se servía la copia caducada
        para no romper el tablero. Eso convertía una alerta del WAF en varias
        peticiones seguidas. Ahora el primer 5xx dispara el kill switch y la
        caché no lo tapa.
        """
        cached = {"elements": [{"id": "m1", "salePrice": 13000000}]}
        client, cache = self._build(
            lambda _request: httpx.Response(503, json={"error": "down"}),
            jitter=False,
        )
        cache.put_json(URL, cached, 60)
        _expire(cache, URL)

        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(net.kill_switch_state()["status"], 503)

    def test_network_drop_also_survives(self) -> None:
        cached = {"elements": [{"id": "ayer"}]}

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sin ruta al host", request=request)

        client, cache = self._build(handler, jitter=False)
        cache.put_json(URL, cached, 60)
        _expire(cache, URL)

        self.assertEqual(client.get_json(URL, ttl=0, fresh=True), cached)

    def test_without_a_disk_copy_the_network_error_still_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sin ruta al host", request=request)

        client, _cache = self._build(handler, jitter=False)
        with self.assertRaises(FantasyHttpError) as raised:
            client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(raised.exception.code, "network")

    def test_a_rate_limit_trips_the_kill_switch_not_the_cache(self) -> None:
        """Un 429 dice «frena». Servir caché ahí taparía el aviso del tablero."""
        client, cache = self._build(
            lambda _request: httpx.Response(429, headers={"Retry-After": "0"}, json={}),
            jitter=False,
        )
        cache.put_json(URL, {"elements": [{"id": "viejo"}]}, 60)
        _expire(cache, URL)

        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(net.kill_switch_state()["status"], 429)

    def test_a_live_host_beats_a_stale_copy_of_the_dead_one(self) -> None:
        """El respaldo vivo manda: la caché del host muerto no puede ganarle."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "api-fantasy.llt-services.com" in str(request.url):
                return httpx.Response(404, json={"error": "gone"})
            return httpx.Response(200, json={"elements": [{"id": "vivo"}]})

        client, cache = self._build(handler, jitter=False)
        cache.put_json(LEGACY_URL, {"elements": [{"id": "viejo"}]}, 60)
        _expire(cache, LEGACY_URL)

        source, payload = client._first_matching(
            [LEGACY_URL, URL],
            ttl=0,
            fresh=True,
            accept=lambda body: bool(body.get("elements")),
        )

        self.assertEqual(source, URL)
        self.assertEqual(payload["elements"][0]["id"], "vivo")

    def test_first_matching_does_not_resurrect_the_cache_after_a_5xx(self) -> None:
        client, cache = self._build(
            lambda _request: httpx.Response(503, json={"error": "down"}),
            jitter=False,
        )
        cache.put_json(URL, {"elements": [{"id": "ayer"}]}, 60)
        _expire(cache, URL)

        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client._first_matching(
                [URL],
                ttl=0,
                fresh=True,
                accept=lambda body: bool(body.get("elements")),
            )

    def test_a_404_endpoint_does_not_resurrect_the_cache(self) -> None:
        client, cache = self._build(
            lambda _request: httpx.Response(404, json={}),
            jitter=False,
        )
        cache.put_json(URL, {"elements": [{"id": "viejo"}]}, 60)
        _expire(cache, URL)

        with self.assertRaises(FantasyHttpError) as raised:
            client._first_matching(
                [URL],
                ttl=0,
                fresh=True,
                accept=lambda body: bool(body.get("elements")),
            )
        self.assertEqual(raised.exception.code, "endpoint_not_found")


class _FakeClock:
    """Reloj y sleeper de mentira: dormir avanza el reloj, no el proceso."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.slept: list[float] = []
        self._guard = threading.Lock()

    def clock(self) -> float:
        with self._guard:
            return self.now

    def sleep(self, seconds: float) -> None:
        with self._guard:
            self.slept.append(round(seconds, 6))
            self.now += seconds


class TrafficControllerTests(unittest.TestCase):
    """El controlador de tráfico espacia los GET al mismo dominio.

    Es lo que impide el thundering herd del arranque en frío: 8 workers con la
    caché vacía no pueden pedirle 8 veces a LaLiga en el mismo segundo. El
    cooldown se mide en huecos reservados, no en tiempo de reloj real, así que
    la prueba es exacta y no espera.
    """

    def setUp(self) -> None:
        self._env = patch.dict("os.environ", {"FANTASY_NET_PACING": "1"})
        self._env.start()
        self.addCleanup(self._env.stop)
        net.reset_rate_limits()
        self.addCleanup(net.reset_rate_limits)
        # El reloj del controlador también es de mentira: es el punto por el
        # que ``pace_domain`` mide los huecos, así que dormir avanza el tiempo
        # y la espera pedida es exactamente el cooldown, no «casi».
        self.fake = _FakeClock()
        clock_patch = patch.object(net, "_PACING_CLOCK", self.fake.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.fake.slept.clear()

    def _client(self, handler=None) -> tuple[LaligaClient, ResponseCache]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cache = ResponseCache(Path(directory.name))
        self.addCleanup(cache.close)
        http = httpx.Client(
            transport=httpx.MockTransport(handler or (lambda _request: httpx.Response(200, json={"ok": True}))),
            follow_redirects=False,
        )
        self.addCleanup(http.close)
        client = LaligaClient(
            tokens=_Tokens(),
            cache=cache,
            http=http,
            sleeper=self.fake.sleep,
            jitter=False,
        )
        return client, cache

    def test_the_cooldown_table_matches_the_agreed_budget(self) -> None:
        self.assertEqual(net.cooldown_for("fantasy-api.llt-services.com"), 1.5)
        self.assertEqual(net.cooldown_for("api-fantasy.llt-services.com"), 1.5)
        self.assertEqual(net.cooldown_for("www.futbolfantasy.com"), 2.0)
        # Un host sin entrada cae en ``default``, nunca en 0 (que sería vía
        # libre y volvería el problema).
        self.assertEqual(net.cooldown_for("fbref.com"), 1.0)
        self.assertGreater(net.COOLDOWNS["default"], 0)

    def test_the_first_request_to_a_domain_does_not_wait(self) -> None:
        client, _cache = self._client()
        client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(self.fake.slept, [])

    def test_the_second_request_waits_exactly_the_cooldown(self) -> None:
        client, _cache = self._client()
        client.get_json(URL, ttl=0, fresh=True)
        client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(self.fake.slept, [1.5])

    def test_each_host_has_its_own_queue(self) -> None:
        """Los dos hosts de LaLiga tienen entrada propia en ``COOLDOWNS``.

        ``_first_matching`` puede probar el host vivo y caer al histórico de
        respaldo, así que alternar de host no es una vía de escape: cada uno
        paga su propio cooldown de 1,5 s.
        """
        client, _cache = self._client()
        client.get_json(URL, ttl=0, fresh=True)
        client.get_json(LEGACY_URL, ttl=0, fresh=True)
        self.assertEqual(self.fake.slept, [])
        client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(self.fake.slept, [1.5])

    def test_a_third_request_keeps_the_strict_spacing(self) -> None:
        client, _cache = self._client()
        for _ in range(3):
            client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(self.fake.slept, [1.5, 1.5])

    def test_a_429_stops_before_the_second_request(self) -> None:
        """Un 429 ya no se reintenta: la segunda petición no llega a existir."""
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})

        client, _cache = self._client(handler)
        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(calls["n"], 1)

    def test_threads_get_consecutive_slots_and_never_the_same_one(self) -> None:
        """N hilos a la vez reservan N huecos de 1,5 s, no uno compartido.

        Es la prueba de fondo del thundering herd, en el peor caso: el reloj
        está congelado, así que nada avanza solo y el único reparto posible es
        el de la cola. El lock protege la reserva (leer el último hueco y
        escribir el siguiente), no la espera. Con 8 hilos las esperas pedidas
        tienen que ser exactamente 0, 1,5, 3, ... 10,5 s: ninguna repetida.
        """
        waits: list[float] = []
        frozen = _FakeClock()
        start = threading.Barrier(8)

        def worker() -> None:
            start.wait(timeout=5.0)
            # Sleeper nulo: se mide lo reservado, no cuánto se duerme.
            waits.append(net.pace_domain(URL, sleeper=lambda _s: None, clock=frozen.clock))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)

        self.assertEqual(len(waits), 8)
        self.assertEqual(sorted(waits), [1.5 * index for index in range(8)])

    def test_the_queue_holds_even_if_the_clock_does_not_advance(self) -> None:
        """La garantía no depende de que la petición anterior ya haya vuelto.

        Si el reloj se congela (o el host tarda más que el cooldown en otra
        petición), los huecos se siguen reservando en cola: 0, 1,5, 3, 4,5 s.
        Sin la reserva, todos verían «ya pasó el cooldown» y saldrían a la vez.
        """
        frozen = _FakeClock()
        waits = [
            net.pace_domain(URL, sleeper=lambda _s: None, clock=frozen.clock)
            for _ in range(4)
        ]
        self.assertEqual(waits, [0.0, 1.5, 3.0, 4.5])

    def test_a_domain_with_its_own_cooldown_does_not_block_another(self) -> None:
        """FútbolFantasy a 2 s no puede frenar una petición a LaLiga."""
        fake = self.fake
        net.pace_domain("https://www.futbolfantasy.com/analytics/x", sleeper=fake.sleep, clock=fake.clock)
        net.pace_domain("https://www.futbolfantasy.com/laliga/lesionados", sleeper=fake.sleep, clock=fake.clock)
        self.assertEqual(fake.slept, [2.0])
        fake.slept.clear()
        # Dominio distinto: su cola está vacía, espera cero.
        net.pace_domain(URL, sleeper=fake.sleep, clock=fake.clock)
        self.assertEqual(fake.slept, [])

    def test_the_switch_turns_the_pacing_off(self) -> None:
        with patch.dict("os.environ", {"FANTASY_NET_PACING": "0"}):
            net.reset_rate_limits()
            fake = self.fake
            net.pace_domain(URL, sleeper=fake.sleep, clock=fake.clock)
            net.pace_domain(URL, sleeper=fake.sleep, clock=fake.clock)
        self.assertEqual(fake.slept, [])

    def test_the_external_client_is_paced_too(self) -> None:
        """FútbolFantasy es la otra fuente que abre 8 workers en el arranque."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cache = ResponseCache(Path(directory.name))
        self.addCleanup(cache.close)
        http = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, text="<html>x</html>")))
        self.addCleanup(http.close)
        ff_url = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"
        with ExternalClient(cache=cache, http=http, sleeper=self.fake.sleep) as client:
            client.get_text(ff_url, ttl=0, fresh=True)
            client.get_text(ff_url, ttl=0, fresh=True)
        self.assertEqual(self.fake.slept, [2.0])

    def test_offline_mode_never_touches_the_pacing_queue(self) -> None:
        with patch.dict("os.environ", {"FANTASY_OFFLINE": "1"}):
            client, cache = self._client()
            cache.put_json(URL, {"ok": True}, 60)
            _expire(cache, URL)
            client.get_json(URL, ttl=0, fresh=True)
        self.assertEqual(self.fake.slept, [])


if __name__ == "__main__":
    unittest.main()

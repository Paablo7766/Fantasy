from __future__ import annotations

import unittest
from unittest.mock import patch

from toolbox import api_meter


class ApiMeterTests(unittest.TestCase):
    def setUp(self) -> None:
        api_meter.reset()

    def tearDown(self) -> None:
        api_meter.reset()

    def test_source_for_url_maps_every_known_host(self) -> None:
        self.assertEqual(api_meter.source_for_url("https://fantasy-api.llt-services.com/api/v1/x")[0], "laliga")
        self.assertEqual(api_meter.source_for_url("https://transfermarkt-api.fly.dev/x")[0], "transfermarkt")
        self.assertEqual(api_meter.source_for_url("https://fbref.com/en/comps/12/x")[0], "fbref")
        self.assertEqual(api_meter.source_for_url("https://www.analiticafantasy.com/x")[0], "analiticafantasy")
        unknown, host = api_meter.source_for_url("https://example.org/x")
        self.assertEqual(unknown, "example.org")
        self.assertEqual(host, "example.org")

    def test_cache_hits_do_not_count_as_calls(self) -> None:
        api_meter.record_cache_hit(url="https://fbref.com/en/comps/12/x")
        report = api_meter.build_usage_report()
        self.assertEqual(report["rate"]["calls_1m"], 0)
        self.assertEqual(report["totals"]["cache_hits"], 1)
        row = next(row for row in report["sources"] if row["id"] == "fbref")
        self.assertEqual(row["calls"], 0)
        self.assertEqual(row["cache_hits"], 1)

    def test_retries_and_429_raise_the_risk(self) -> None:
        url = "https://fantasy-api.llt-services.com/api/v1/league/1/market"
        api_meter.record_call(url=url, status=429)
        report = api_meter.build_usage_report()
        self.assertEqual(report["risk"]["level"], "alto")
        self.assertEqual(report["windows"][1]["rate_limited"], 1)
        self.assertTrue(any("429" in reason for reason in report["risk"]["reasons"]))

    def test_fallback_404_is_not_a_failure(self) -> None:
        """Probar cinco URLs de respaldo no puede parecer una fuente rota."""
        url = "https://fantasy-api.llt-services.com/api/v3/league/1/market"
        for _ in range(4):
            api_meter.record_call(url=url, status=404)
        api_meter.record_call(url=url, status=200)
        report = api_meter.build_usage_report()
        self.assertEqual(report["windows"][1]["errors"], 0)
        self.assertEqual(report["windows"][1]["not_found"], 4)
        self.assertEqual(report["risk"]["level"], "bajo")
        row = report["sources"][0]
        self.assertEqual(row["not_found"], 4)
        self.assertEqual(row["calls"], 5)

    def test_retry_ratio_flags_medium_risk(self) -> None:
        url = "https://fbref.com/en/comps/12/x"
        for index in range(6):
            api_meter.record_call(url=url, status=200, retry=index > 0)
        report = api_meter.build_usage_report()
        self.assertEqual(report["risk"]["level"], "medio")
        self.assertEqual(report["totals"]["retries"], 5)

    def test_fallback_5xx_is_instability_not_rate_risk(self) -> None:
        """Un 502 en el host de respaldo no puede decir «te estan frenando»."""
        url = "https://fantasy-api.llt-services.com/api/v3/league/1/market"
        for _ in range(8):
            api_meter.record_call(url=url, status=502)
        report = api_meter.build_usage_report()
        self.assertEqual(report["risk"]["level"], "bajo")
        self.assertEqual(report["windows"][1]["errors"], 8)
        self.assertEqual(report["stability"]["level"], "warn")
        self.assertTrue(any("5xx" in reason for reason in report["risk"]["reasons"]))

    def test_failures_the_next_host_resolved_do_not_alarm(self) -> None:
        """El 502 del host viejo seguido del 200 del bueno es el camino normal."""
        old = "https://api-fantasy.llt-services.com/api/v1/market"
        good = "https://fantasy-api.llt-services.com/api/v1/market"
        now = 1_000_000.0
        for offset in range(4):
            api_meter.record_call(url=old, status=502, now=now + offset)
        api_meter.record_call(url=good, status=200, now=now + 4)
        report = api_meter.build_usage_report(now=now + 5)
        self.assertEqual(report["windows"][1]["errors"], 4)
        self.assertEqual(report["risk"]["level"], "bajo")
        self.assertEqual(report["stability"]["level"], "ok")
        self.assertEqual(report["stability"]["errors_10m"], 0)
        self.assertEqual(report["stability"]["recovered_10m"], 4)
        self.assertTrue(any("respaldo hizo su trabajo" in reason for reason in report["risk"]["reasons"]))
        row = report["sources"][0]
        self.assertEqual(row["recovered"], 4)
        self.assertEqual(row["errors_pending"], 0)

    def test_an_unresolved_outage_still_shows_as_instability(self) -> None:
        """Sin un 200 posterior no hay respaldo que valga: la caida se ve."""
        url = "https://fantasy-api.llt-services.com/api/v1/market"
        now = 2_000_000.0
        for offset in range(6):
            api_meter.record_call(url=url, status=500, now=now + offset)
        report = api_meter.build_usage_report(now=now + 30)
        self.assertEqual(report["stability"]["level"], "warn")
        self.assertEqual(report["stability"]["errors_10m"], 6)
        self.assertEqual(report["stability"]["recovered_10m"], 0)
        self.assertEqual(report["risk"]["level"], "bajo")
        self.assertIn("no responde", report["risk"]["headline"])

    def test_auth_failures_lift_risk_to_medium(self) -> None:
        api_meter.record_call(url="https://fantasy-api.llt-services.com/api/v1/x", status=401)
        report = api_meter.build_usage_report()
        self.assertEqual(report["risk"]["level"], "medio")
        self.assertEqual(report["windows"][1]["auth"], 1)

    def test_empty_process_reads_clean(self) -> None:
        report = api_meter.build_usage_report()
        self.assertEqual(report["risk"]["level"], "bajo")
        self.assertEqual(report["risk"]["score"], 100)
        self.assertEqual(report["sources"], [])
        self.assertEqual(len(report["timeline"]), api_meter.TIMELINE_MINUTES)

    def test_call_context_manager_records_an_exception_as_error(self) -> None:
        with self.assertRaises(RuntimeError):
            with api_meter.call(url="https://understat.com/league/La_liga") as probe:
                probe.status = 500
                raise RuntimeError("boom")
        report = api_meter.build_usage_report()
        row = next(row for row in report["sources"] if row["id"] == "understat")
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["errors"], 1)

    def test_laliga_client_counts_a_real_http_call(self) -> None:
        import httpx

        from toolbox.net import LaligaClient

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        tokens = _StubTokens()
        with LaligaClient(
            tokens=tokens,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            sleeper=lambda _seconds: None,
        ) as client:
            client.get_json("https://fantasy-api.llt-services.com/api/v1/x", ttl=0, fresh=True)
        report = api_meter.build_usage_report()
        self.assertEqual(report["rate"]["calls_1m"], 1)
        self.assertEqual(report["sources"][0]["id"], "laliga")

    def test_external_client_counts_a_real_http_call(self) -> None:
        import tempfile
        from pathlib import Path

        import httpx

        from toolbox.cache import ResponseCache
        from toolbox.net import ExternalClient

        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            transport = httpx.MockTransport(lambda _r: httpx.Response(200, text="<html>x</html>"))
            with ExternalClient(
                cache=cache,
                http=httpx.Client(transport=transport),
                sleeper=lambda _seconds: None,
            ) as client:
                client.get_text("https://fbref.com/en/comps/12/x", ttl=0, fresh=True)
            cache.close()
        report = api_meter.build_usage_report()
        self.assertEqual(report["rate"]["calls_1m"], 1)
        self.assertEqual(report["sources"][0]["id"], "fbref")

    def test_endpoint_is_read_only_and_cheap(self) -> None:
        from fastapi.testclient import TestClient

        import server

        client = TestClient(server.app)
        with patch.object(server, "snapshot", side_effect=AssertionError("no debe construir tablero")):
            response = client.get("/api/api-usage")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "api-usage")
        self.assertIn("risk", payload)


class NetworkLogTests(unittest.TestCase):
    """La bitácora de red tiene que sobrevivir al reinicio y no tocar el repo."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        api_meter.reset()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = patch.dict("os.environ", {"FANTASY_CACHE_DIR": str(self.root)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()
        api_meter.reset()

    def test_real_call_is_logged_and_cache_hit_is_not(self) -> None:
        import httpx

        from toolbox.net import LaligaClient, network_log_path

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        url = "https://fantasy-api.llt-services.com/api/v1/x?x-lang=es"
        with LaligaClient(
            tokens=_StubTokens(),
            http=httpx.Client(transport=httpx.MockTransport(handler)),
            sleeper=lambda _seconds: None,
        ) as client:
            client.get_json(url, ttl=60, fresh=True)
            client.get_json(url, ttl=60, fresh=False)

        path = network_log_path()
        self.assertEqual(path, self.root / "network_logs.jsonl")
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        import json

        row = json.loads(lines[0])
        self.assertEqual(row["fuente"], "laliga")
        self.assertEqual(row["metodo"], "GET")
        self.assertEqual(row["status"], 200)
        self.assertIn("duracion_ms", row)
        self.assertIn("timestamp", row)
        self.assertNotIn("x-lang", row["url"])

    def test_every_retry_status_is_recorded(self) -> None:
        import httpx

        from toolbox.net import ExternalClient, network_log_path
        from toolbox.cache import ResponseCache

        cache = ResponseCache(self.root)
        transport = httpx.MockTransport(lambda _r: httpx.Response(503))
        with ExternalClient(
            cache=cache,
            http=httpx.Client(transport=transport),
            sleeper=lambda _seconds: None,
            clock=lambda: 0.0,
        ) as client:
            with self.assertRaises(Exception):
                client.get_text("https://www.fbref.com/en/comps/12/x", ttl=0, fresh=True)
        cache.close()
        lines = network_log_path().read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(all('"status":503' in line for line in lines))

    def test_endpoint_without_file_returns_empty_array(self) -> None:
        from fastapi.testclient import TestClient

        import server

        client = TestClient(server.app)
        payload = client.get("/api/diagnostics/network").json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["file_exists"])
        self.assertEqual(payload["calls"], [])
        self.assertEqual(payload["errors"], [])

    def test_endpoint_sorts_newest_first_and_counts_errors(self) -> None:
        import json

        from fastapi.testclient import TestClient

        import server
        from toolbox.net import network_log_path

        rows = [
            {"timestamp": "2026-01-01T10:00:00+00:00", "fuente": "fbref", "metodo": "GET", "status": 403, "duracion_ms": 1.0},
            {"timestamp": "2026-01-01T11:00:00+00:00", "fuente": "LALIGA", "metodo": "GET", "status": 200, "duracion_ms": 2.0},
            {"timestamp": "2026-01-01T12:00:00+00:00", "fuente": "fbref", "metodo": "GET", "status": 503, "duracion_ms": 3.0},
            "",
            "{roto",
        ]
        network_log_path().write_text("\n".join(json.dumps(r) if isinstance(r, dict) else r for r in rows) + "\n", encoding="utf-8")

        client = TestClient(server.app)
        payload = client.get("/api/diagnostics/network").json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual([row["status"] for row in payload["calls"]], [503, 200, 403])
        self.assertEqual(len(payload["errors"]), 1)
        bucket = payload["errors"][0]
        self.assertEqual(bucket["fuente"], "fbref")
        self.assertEqual(bucket["total"], 2)
        self.assertEqual(bucket["por_status"], {"403": 1, "503": 1})

    def test_endpoint_keeps_only_the_last_200_lines(self) -> None:
        import json

        from fastapi.testclient import TestClient

        import server
        from toolbox.net import network_log_path

        with network_log_path().open("w", encoding="utf-8") as handle:
            for index in range(250):
                handle.write(
                    json.dumps(
                        {
                            "timestamp": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
                            "fuente": "laliga",
                            "metodo": "GET",
                            "status": 200,
                            "duracion_ms": 1.0,
                        }
                    )
                    + "\n"
                )

        payload = TestClient(server.app).get("/api/diagnostics/network").json()
        self.assertEqual(payload["count"], 200)
        self.assertEqual(payload["total_count"], 250)
        self.assertEqual(payload["calls"][0]["timestamp"], "2026-01-01T00:04:09+00:00")


class _StubTokens:
    def authorization_value(self) -> str:
        return "Bearer test"

    def force_refresh(self) -> str:
        return "Bearer test"


if __name__ == "__main__":
    unittest.main()

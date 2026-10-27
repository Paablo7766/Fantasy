"""Pruebas de la Fase 1. No llaman a la API real."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

import cli
from toolbox.auth import (
    callback_url,
    extract_authorization_code,
    extract_state,
    login_with_browser,
    make_pkce_pair,
    write_env_values,
)
from toolbox.cache import ResponseCache, cache_key
from toolbox import net
from toolbox.net import (
    LEAGUE_BASE,
    REQUIRED_HEADERS,
    FantasyHttpError,
    LaligaClient,
    backoff_delay,
    league_list_urls,
)
from toolbox.normalize import build_squads_document, clause_lock_from, normalize_squad, parse_clause_lock


class FakeTokens:
    def __init__(self, header: str = "Bearer test-token") -> None:
        self.header = header
        self.refreshes = 0

    def authorization_value(self) -> str:
        return self.header

    def force_refresh(self) -> str:
        self.refreshes += 1
        self.header = "Bearer fresh-token"
        return "fresh-token"


class Phase1Test(unittest.TestCase):
    def test_callback_url_accepts_only_authredirect(self) -> None:
        redirect = "authredirect://com.lfp.laligafantasy?code=abc.def&state=qq"
        self.assertEqual(callback_url(f"  {redirect}  "), redirect)
        self.assertIsNone(callback_url("https://login.laliga.es/oauth2/v2.0/authorize"))
        self.assertIsNone(callback_url(""))

    def test_login_with_browser_hides_code_and_saves_league(self) -> None:
        redirect = "authredirect://com.lfp.laligafantasy?code=abc.def&state=qq"
        exchanged = {
            "ok": True,
            "command": "auth",
            "action": "exchange",
            "persisted_to": ".env",
            "refresh_token_present": True,
        }
        league = {
            "league_id": "7",
            "league_name": "Mi liga",
            "league_saved": True,
            "leagues": [{"league_id": "7", "name": "Mi liga"}],
        }
        with (
            patch("toolbox.auth._capture_auth_redirect", return_value=redirect) as capture,
            patch("toolbox.auth.complete_pkce_login", return_value=dict(exchanged)) as exchange,
            patch("toolbox.auth.persist_detected_league", return_value=league),
        ):
            result = login_with_browser()
        capture.assert_called_once()
        exchange.assert_called_once_with(redirect)
        self.assertEqual(result["action"], "browser")
        self.assertEqual(result["league_id"], "7")
        self.assertTrue(result["league_saved"])
        rendered = json.dumps(result)
        self.assertNotIn("abc.def", rendered)
        self.assertNotIn("eyJ", rendered)

    def test_cli_auth_browser_json_omits_secrets(self) -> None:
        payload = {
            "ok": True,
            "command": "auth",
            "action": "browser",
            "persisted_to": ".env",
            "refresh_token_present": True,
            "league_id": "42",
            "league_name": "Mi liga",
            "league_saved": True,
            "leagues": [{"league_id": "42", "name": "Mi liga"}],
        }
        stdout = StringIO()
        stderr = StringIO()
        with patch("cli.login_with_browser", return_value=dict(payload)):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main(["auth", "browser", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        body = json.loads(stdout.getvalue())
        self.assertEqual(body["league_id"], "42")
        self.assertNotIn("abc", stdout.getvalue())
        self.assertNotIn("eyJ", stdout.getvalue())

    def test_extracts_code_from_authredirect(self) -> None:
        redirect = "authredirect://com.lfp.laligafantasy?code=abc.def-xyz&state=qq"
        self.assertEqual(extract_authorization_code(redirect), "abc.def-xyz")
        self.assertEqual(extract_state(redirect), "qq")
        self.assertEqual(extract_authorization_code("solo-el-code"), "solo-el-code")

    def test_pkce_challenge_is_s256(self) -> None:
        verifier, challenge = make_pkce_pair()
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        self.assertEqual(challenge, expected)
        self.assertGreaterEqual(len(verifier), 43)

    def test_clause_lock_keeps_hour_and_minute(self) -> None:
        past = parse_clause_lock(
            "2025-10-11T10:25:00+02:00",
            now=datetime(2026, 10, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(past["local_date"], "2025-10-11")
        self.assertEqual(past["local_time"], "10:25")
        self.assertFalse(past["is_locked"])

        moment = datetime(2026, 10, 15, 18, 34, tzinfo=timezone.utc)
        future = parse_clause_lock(int(moment.timestamp() * 1000), now=datetime(2026, 10, 14, tzinfo=timezone.utc))
        self.assertEqual(future["local_time"], "20:34")
        self.assertEqual(future["local_date"], "2026-10-15")
        self.assertTrue(future["is_locked"])

    def test_squad_reads_nested_clause_timestamp(self) -> None:
        payload = {
            "players": [
                {
                    "playerMaster": {
                        "id": 1001,
                        "nickname": "B. Méndez",
                        "name": "Brais Méndez",
                        "marketValue": 12345678,
                        "marketValueChange": 1325257,
                        "positionId": 3,
                    },
                    "buyoutClause": 25000000,
                    "meta": {"buyoutClauseLockedEndTime": "2026-12-01T07:05:00+01:00"},
                }
            ]
        }
        squad = normalize_squad(
            payload,
            seed={"team_id": "9", "manager_name": "Ana", "fantasy_team_name": "Ana FC", "rank": 1, "points": 0},
            own_team_id="9",
            source_url="https://fantasy-api.llt-services.com/team",
            now=datetime(2026, 10, 14, tzinfo=timezone.utc),
        )
        player = squad["players"][0]
        self.assertEqual(player["position"], "MC")
        self.assertEqual(player["market_value_change"], 1325257)
        self.assertEqual(player["buyout_clause"], 25000000)
        self.assertEqual(player["clause_lock"]["local_time"], "07:05")
        self.assertTrue(player["clause_lock"]["is_locked"])
        self.assertTrue(squad["is_self"])
        self.assertEqual(squad["points"], 0)
        document = build_squads_document(
            league_id="7",
            league_name="Liga",
            index_url="https://fantasy-api.llt-services.com/index",
            squads=[squad],
            fetched_at="2026-10-14T12:00:00+00:00",
        )
        self.assertEqual(document["schema_version"], 1)
        self.assertIn("hora y minuto", document["clause_lock_note"])

    def test_absent_lock_is_explicit(self) -> None:
        lock = clause_lock_from({"playerMaster": {"id": 1}})
        self.assertFalse(lock["present"])
        self.assertFalse(lock["is_locked"])
        self.assertIsNone(lock["local_time"])

    def test_league_base_is_the_contract_url(self) -> None:
        self.assertEqual(LEAGUE_BASE, "https://api-fantasy.llt-services.com/api/v4/leagues")

    def test_the_live_league_route_is_first_and_the_dead_ones_are_gone(self) -> None:
        """Las rutas retiradas no pueden quedarse «de respaldo».

        ``/api/v4/leagues`` contesta 500 en ``fantasy-api`` y 502 en
        ``api-fantasy``. Un 5xx dispara el kill switch, así que dejarlas en la
        lista —aunque sea al final— convierte el primer fallo de la ruta buena
        en el fin de la pasada. Con las muertas delante, todo refresco moría
        en ``resolve_league`` y el panel servía la foto de ayer.
        """
        urls = league_list_urls()
        self.assertEqual(urls[0], "https://fantasy-api.llt-services.com/api/v1/competition/1/leagues?x-lang=es")
        for url in urls:
            self.assertNotIn("api-fantasy.llt-services.com", url)
            self.assertNotIn("/api/v4/leagues", url)

    def test_required_headers_and_backoff(self) -> None:
        for name in ("Origin", "Referer", "X-App", "X-Lang"):
            self.assertIn(name, REQUIRED_HEADERS)
        self.assertEqual(REQUIRED_HEADERS["X-App"], "Fantasy-web")
        self.assertEqual(backoff_delay(0, "0"), 0.0)
        self.assertEqual(backoff_delay(3, "120"), 120.0)
        delay = backoff_delay(2, None, rng=random.Random(1))
        self.assertGreaterEqual(delay, 4.0)
        self.assertLessEqual(delay, 4.8)

    def test_429_trips_the_kill_switch_without_a_retry(self) -> None:
        """Un 429 es una orden de parar, no un reintento con espera."""
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow"})

        client = self._client(handler)
        with self.assertRaises(SystemExit):
            client.get_json(
                "https://fantasy-api.llt-services.com/api/v4/leagues?x-lang=es",
                ttl=0,
                fresh=True,
            )
        # Una sola petición: los reintentos sobre un 429 son justo lo que
        # dispara el baneo de la IP.
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].headers["Authorization"], "Bearer test-token")
        self.assertEqual(calls[0].headers["Origin"], "https://fantasy.laliga.com")
        self.assertEqual(calls[0].headers["Referer"], "https://fantasy.laliga.com/")
        self.assertEqual(calls[0].headers["X-App"], "Fantasy-web")
        self.assertEqual(calls[0].headers["X-Lang"], "es")
        self.addCleanup(net.reset_kill_switch)

    def test_401_trips_the_kill_switch_without_a_retry(self) -> None:
        """Un 401 ya no refresca el token y reintenta: mata el proceso.

        Refrescar el token y repetir convertía un token caducado en dos
        peticiones con la misma IP y el mismo segundo. El contrato vivo es
        parar en seco y pedir un login manual.
        """
        tokens = FakeTokens()
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.headers["Authorization"])
            return httpx.Response(401, json={"message": "expired"})

        client = self._client(handler, tokens=tokens)
        with net.kill_switch_as_exception(), self.assertRaises(net.KillSwitchTripped):
            client.get_json("https://fantasy-api.llt-services.com/api/v4/ping", ttl=0, fresh=True)
        self.assertEqual(tokens.refreshes, 0)
        self.assertEqual(calls, ["Bearer test-token"])

    def test_legacy_host_502_falls_through_to_market(self) -> None:
        photo = "https://assets-fantasy.llt-services.com/players/t81/p5/256x256/p5_t81_1_001_000.png"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "api-fantasy.llt-services.com" in url:
                return httpx.Response(502, json={"error": "down"})
            if "/competition/1/players" in url:
                return httpx.Response(
                    200,
                    json=[{"id": "5", "nickname": "Vinicius", "positionId": "4", "image": photo}],
                )
            if url.endswith("/market?x-lang=es") or "/market?" in url:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "m1",
                            "salePrice": 12000000,
                            "playerMaster": {"id": 5, "nickname": "Vinicius", "positionId": 4},
                            "bids": [{"id": "b1", "money": 13000000, "managerName": "Luis"}],
                        }
                    ],
                )
            return httpx.Response(200, json=[{"id": "7", "name": "Mi liga", "team": {"id": "3", "teamMoney": 0}}])

        document = self._client(handler).market_document("7", fresh=True)
        self.assertTrue(document["ok"])
        self.assertEqual(document["league_id"], "7")
        self.assertEqual(document["count"], 1)
        self.assertEqual(document["listings"][0]["nickname"], "Vinicius")
        self.assertEqual(document["listings"][0]["position"], "DEL")
        self.assertEqual(document["listings"][0]["leading_bid"], 13000000)
        self.assertEqual(document["listings"][0]["image_url"], photo)
        self.assertNotIn("api-fantasy.llt-services.com", document["source_url"])

    def test_squads_keep_clause_minute_from_api(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "api-fantasy.llt-services.com" in url:
                return httpx.Response(502, json={"error": "down"})
            if "/standing" in url:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "position": 2,
                            "points": 40,
                            "team": {"id": "44", "name": "Rival", "manager": {"managerName": "Nuria"}},
                        }
                    ],
                )
            if "/teams/44" in url:
                return httpx.Response(
                    200,
                    json={
                        "teamMoney": 0,
                        "players": [
                            {
                                "id": "slot-1",
                                "playerMaster": {
                                    "id": 8,
                                    "nickname": "Courtois",
                                    "positionId": 1,
                                    "team": {"name": "Real Madrid"},
                                },
                                "buyoutClause": 20000000,
                                "buyoutClauseLockedEndTime": "2027-06-01T09:15:00+02:00",
                                "isShielded": False,
                            }
                        ],
                    },
                )
            return httpx.Response(200, json=[{"id": "7", "name": "Mi liga", "team": {"id": "3"}}])

        document = self._client(handler).squads_document("7", fresh=True)
        self.assertTrue(document["ok"])
        self.assertEqual(document["count"], 1)
        squad = document["squads"][0]
        self.assertEqual(squad["manager_name"], "Nuria")
        self.assertFalse(squad["is_self"])
        self.assertEqual(squad["cash"], 0)
        lock = squad["players"][0]["clause_lock"]
        self.assertEqual(lock["local_date"], "2027-06-01")
        self.assertEqual(lock["local_time"], "09:15")
        self.assertTrue(lock["is_locked"])
        self.assertEqual(squad["players"][0]["position"], "POR")
        self.assertFalse(squad["players"][0]["is_shielded"])

    def test_cache_skips_second_request(self) -> None:
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"ok": True})

        client = self._client(handler)
        url = "https://fantasy-api.llt-services.com/api/v4/cached"
        self.assertEqual(client.get_json(url, ttl=60, fresh=False), {"ok": True})
        self.assertEqual(client.get_json(url, ttl=60, fresh=False), {"ok": True})
        self.assertEqual(calls["n"], 1)

    def test_disk_cache_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            cache.put_page("https://example.test/a", "<html>hola</html>", 60)
            cache.put_json("https://example.test/b", {"n": 1}, 60)
            self.assertEqual(cache.get_page("https://example.test/a"), "<html>hola</html>")
            self.assertEqual(cache.get_json("https://example.test/b"), {"n": 1})
            cache.close()

    def test_page_cache_writes_one_file_per_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = ResponseCache(root)
            cache.put_page("https://example.test/a", "A" * 1000, 60)
            path_a = root / "scraper_bodies" / cache_key("https://example.test/a")
            stamp = path_a.stat().st_mtime_ns
            time.sleep(0.05)
            cache.put_page("https://example.test/b", "B" * 1000, 60)
            self.assertEqual(path_a.stat().st_mtime_ns, stamp)
            self.assertEqual(cache.get_page("https://example.test/a"), "A" * 1000)
            monolith = root / "supabase-local" / "scraper_cache.json"
            self.assertFalse(monolith.exists())
            cache.close()

    def test_legacy_scraper_cache_is_split_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            url = "https://example.test/legacy"
            key = cache_key(url)
            folder = root / "supabase-local"
            folder.mkdir(parents=True)
            legacy = folder / "scraper_cache.json"
            legacy.write_text(
                json.dumps(
                    [
                        {
                            "cache_key": key,
                            "kind": "page",
                            "expires_at": time.time() + 60,
                            "body": "<html>viejo</html>",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            cache = ResponseCache(root)
            self.assertEqual(cache.get_page(url), "<html>viejo</html>")
            self.assertEqual(json.loads(legacy.read_text(encoding="utf-8")), [])
            self.assertTrue((root / "scraper_bodies" / key).is_file())
            cache.close()

    def test_env_writer_replaces_only_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("LEAGUE_ID=7\nLALIGA_ACCESS_TOKEN=\"viejo\"\n", encoding="utf-8")
            write_env_values(
                {"LALIGA_ACCESS_TOKEN": "nuevo", "LALIGA_REFRESH_TOKEN": "refresh"},
                path=path,
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("LEAGUE_ID=7", text)
            self.assertIn('LALIGA_ACCESS_TOKEN="nuevo"', text)
            self.assertIn('LALIGA_REFRESH_TOKEN="refresh"', text)
            self.assertNotIn("viejo", text)

    def test_env_writer_keeps_the_new_token_when_the_file_is_read_only(self) -> None:
        """En el contenedor, /app/.env puede ser de solo lectura para el uid que corre.

        El token recién canjeado no se puede perder por eso: se aplica al
        entorno del proceso y el fallo de escritura solo deja un aviso.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("LEAGUE_ID=7\n", encoding="utf-8")
            path.chmod(0o444)
            try:
                if os.access(path, os.W_OK):
                    self.skipTest("el usuario de la prueba puede escribir ficheros de solo lectura (root)")
                with patch.dict(os.environ, {}, clear=False):
                    with self.assertLogs("fantasy.auth", level="WARNING"):
                        write_env_values({"LALIGA_ACCESS_TOKEN": "nuevo"}, path=path)
                    self.assertEqual(os.environ["LALIGA_ACCESS_TOKEN"], "nuevo")
            finally:
                path.chmod(0o644)

    def test_cli_optimize_without_cache_is_strict_json_and_offline(self) -> None:
        """Sin tokens y sin copia en ``.cache/`` el air-gap responde ``offline_miss``.

        Antes esta prueba esperaba ``auth_required`` porque el cliente salía a
        la red y el fallo llegaba al renovar el token. Con el air-gap por
        defecto no hay petición que hacer: el error correcto es «no hay copia»,
        y sigue siendo un JSON estricto sin filtrar el bearer.
        """
        stdout = StringIO()
        stderr = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "LALIGA_ACCESS_TOKEN": "",
                    "LALIGA_REFRESH_TOKEN": "",
                    "LEAGUE_ID": "",
                    "FANTASY_CACHE_DIR": directory,
                    "LALIGA_ENV": "development",
                },
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli.main(["optimize", "--json"])
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "offline_miss")
        self.assertNotIn("Bearer ", stdout.getvalue())

        stdout = StringIO()
        stderr = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            previous = {key: os.environ.get(key) for key in ("LALIGA_ACCESS_TOKEN", "LALIGA_REFRESH_TOKEN", "LEAGUE_ID", "FANTASY_CACHE_DIR")}
            os.environ["LALIGA_ACCESS_TOKEN"] = ""
            os.environ["LALIGA_REFRESH_TOKEN"] = ""
            os.environ["LEAGUE_ID"] = ""
            os.environ["FANTASY_CACHE_DIR"] = directory
            try:
                with redirect_stdout(stdout), redirect_stderr(stderr), patch.dict(os.environ, {"LALIGA_ACCESS_TOKEN": "", "LALIGA_REFRESH_TOKEN": "", "LEAGUE_ID": ""}):
                    code = cli.main(["market", "--json", "--league", "7"])
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertNotIn("Bearer ", stdout.getvalue())

    def test_parser_accepts_json_flag_on_commands(self) -> None:
        args = cli.build_parser().parse_args(["squads", "--json", "--fresh", "--league", "15"])
        self.assertTrue(args.json)
        self.assertTrue(args.fresh)
        self.assertEqual(args.league, "15")
        agent = cli.build_parser().parse_args(["agent", "--execute", "--json"])
        self.assertTrue(agent.execute)

    def test_fantasy_api_rejects_writes(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"ok": True})

        client = self._client(handler)
        targets = (
            ("post", "https://fantasy-api.llt-services.com/api/v4/leagues/7/market"),
            ("put", "https://fantasy-api.llt-services.com/api/v4/leagues/7/lineup"),
            ("patch", "https://api-fantasy.llt-services.com/api/v3/league/7/bid"),
            ("delete", "https://api-fantasy.llt-services.com/api/v3/league/7/bid"),
        )
        for method, url in targets:
            with self.subTest(method=method):
                with self.assertRaises(FantasyHttpError) as raised:
                    getattr(client._http, method)(url)
                self.assertEqual(raised.exception.code, "read_only")
        self.assertEqual(calls["n"], 0)
        self.assertEqual(
            client.get_json("https://fantasy-api.llt-services.com/api/v4/ping", ttl=0, fresh=True),
            {"ok": True},
        )
        self.assertEqual(calls["n"], 1)

    def test_rejects_url_outside_laliga(self) -> None:
        client = self._client(lambda _request: httpx.Response(200, json={}))
        with self.assertRaises(FantasyHttpError) as raised:
            client.get_json("https://example.test/secret", ttl=0, fresh=True)
        self.assertEqual(raised.exception.code, "forbidden_url")

    def _client(self, handler, tokens: FakeTokens | None = None) -> LaligaClient:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        cache = ResponseCache(Path(self._directory.name))
        self.addCleanup(cache.close)
        http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        self.addCleanup(http.close)
        return LaligaClient(tokens=tokens or FakeTokens(), cache=cache, http=http, sleeper=lambda _seconds: None)


if __name__ == "__main__":
    unittest.main()

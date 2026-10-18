"""Pruebas del tablero. No llaman a la API real."""

from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox.auth import AuthError


def _xi() -> list[dict]:
    roster = []
    for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
        for index in range(count):
            roster.append(
                {
                    "player_id": f"{position}-{index}",
                    "name": f"Nombre {position} {index}",
                    "nickname": f"{position}{index}",
                    "position": position,
                    "club": "Club",
                    "expected_points": 4.5 + index,
                    "objective": 3.0 + index,
                    "p_titular": 0.8,
                }
            )
    return roster


def fixture() -> dict:
    xi = _xi()
    return {
        "dashboard_at": "2026-10-14T18:00:00+00:00",
        "market": {
            "ok": True,
            "league_id": "liga-1",
            "league_name": "Liga de prueba",
            "count": 2,
            "fetched_at": "2026-10-14T18:00:00+00:00",
            "listings": [
                {
                    "player_id": "flip-1",
                    "nickname": "Flip",
                    "name": "Flip Player",
                    "position": "DEL",
                    "sale_price": 1000000,
                    "leading_bid": 900000,
                }
            ],
        },
        "squads": {
            "ok": True,
            "schema_version": 1,
            "league_id": "liga-1",
            "league_name": "Liga de prueba",
            "fetched_at": "2026-10-14T18:00:00+00:00",
            "clause_lock_timezone": "Europe/Madrid",
            "clause_lock_note": "local_time es hora y minuto.",
            "squads": [
                {
                    "team_id": "own",
                    "is_self": True,
                    "manager_name": "Yo",
                    "fantasy_team_name": "Mi equipo",
                    "rank": 2,
                    "cash": 1500000,
                    "players": [
                        {
                            "player_id": "risk-1",
                            "nickname": "Expuesto",
                            "name": "Jugador Expuesto",
                            "position": "DEF",
                            "buyout_clause": 1000000,
                            "market_value": 1000000,
                        },
                        {
                            "player_id": "peak-1",
                            "nickname": "Pico",
                            "name": "Jugador Pico",
                            "position": "DEL",
                            "buyout_clause": 9000000,
                            "market_value": 2000000,
                        },
                    ],
                },
                {
                    "team_id": "rival",
                    "is_self": False,
                    "manager_name": "Rival Uno",
                    "fantasy_team_name": "Equipo Rival",
                    "rank": 1,
                    "points": 40,
                    "cash": 250000,
                    "players": [
                        {
                            "player_id": "p1",
                            "nickname": "Clausula",
                            "name": "Jugador Clausula",
                            "position": "DEL",
                            "buyout_clause": 8000000,
                            "market_value": 5000000,
                            "average_points": 4.5,
                            "is_shielded": False,
                            "clause_lock": {
                                "present": True,
                                "is_locked": True,
                                "local_date": "2026-10-15",
                                "local_time": "18:34",
                                "local_clock": "18:34:00",
                                "expires_at": "2026-10-15T16:34:00+00:00",
                                "timezone": "Europe/Madrid",
                            },
                        },
                        {
                            "player_id": "p2",
                            "nickname": "SinHora",
                            "name": "Sin Hora",
                            "position": "MC",
                            "buyout_clause": 1000,
                            "market_value": 1000,
                            "average_points": 1.0,
                            "is_shielded": False,
                            "clause_lock": {
                                "present": False,
                                "is_locked": False,
                                "local_date": None,
                                "local_time": None,
                            },
                        },
                        {
                            "player_id": "p3",
                            "nickname": "Caro",
                            "name": "Jugador Caro",
                            "position": "MC",
                            "buyout_clause": 20000000,
                            "market_value": 5000000,
                            "average_points": 8.0,
                            "is_shielded": False,
                            "clause_lock": {
                                "present": True,
                                "is_locked": True,
                                "local_date": "2026-10-16",
                                "local_time": "12:00",
                                "local_clock": "12:00:00",
                                "expires_at": "2026-10-16T10:00:00+00:00",
                                "timezone": "Europe/Madrid",
                            },
                        },
                    ],
                },
            ],
        },
        "trends": {
            "ok": True,
            "schema_version": 1,
            "league_id": "liga-1",
            "league_name": "Liga de prueba",
            "fetched_at": "2026-10-14T18:00:00+00:00",
            "partial": False,
            "catalog_count": 20,
            "rising": [
                {
                    "player_id": "rise-1",
                    "nickname": "Sube",
                    "position": "MC",
                    "acceleration": 12,
                    "p_titular": 0.7,
                }
            ],
            "falling": [],
            "undervalued": [],
            "availability": [],
            "players": [
                {
                    "player_id": "peak-1",
                    "nickname": "Pico",
                    "acceleration": 6,
                    "price_delta": -1,
                }
            ],
            "sources": {"futbolfantasy": {"ok": True, "count": 10, "error": None}},
        },
        "optimize": {
            "ok": True,
            "command": "optimize",
            "schema_version": 1,
            "league_id": "liga-1",
            "manager_name": "Yo",
            "formation": "4-3-3",
            "counts": {"POR": 1, "DEF": 4, "MC": 3, "DEL": 3},
            "xi": xi,
            "benched": [],
            "expected_points": 48.5,
            "objective": 48.5,
            "cash_eur": 1500000,
            "cash_known": True,
            "cash_negative": False,
            "matchday_void": False,
            "void_reasons": [],
            "eligible_count": 15,
            "calibration_note": "Nota de calibración.",
        },
        "flip": {
            "ok": True,
            "cash_eur": 1500000,
            "signings": [
                {
                    "player_id": "flip-1",
                    "nickname": "Flip",
                    "position": "DEL",
                    "acceleration": 9,
                    "bid_eur": 900001,
                    "expected_points": 5.2,
                    "p_titular": 0.66,
                    "snipe": {"fire_local_clock": "21:07:52"},
                }
            ],
        },
        "needs": {
            "ok": True,
            "schema_version": 1,
            "league_id": "liga-1",
            "rival_count": 1,
            "activity": {"ok": True, "event_count": 0},
            "ledger_note": "Caja reconstruida.",
            "rivals": [
                {
                    "team_id": "rival",
                    "manager_name": "Rival Uno",
                    "cash_eur": 250000,
                    "direct": True,
                    "lacks_liquidity": False,
                    "lacks_replacements": True,
                    "thin_positions": ["DEL"],
                    "clause_alerts": [],
                    "ledger": {"observed_cash_eur": 250000, "events": [{"kind": "buy"}]},
                }
            ],
            "clause_alerts": [
                {
                    "team_id": "rival",
                    "nickname": "Clausula",
                    "alert_local_date": "2026-10-15",
                    "alert_local_time": "18:34",
                    "scheduled": True,
                }
            ],
        },
    }


class DashboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        server.clear_snapshot_cache()
        self._patch = patch.object(server, "load_snapshot", return_value=fixture())
        self.loader = self._patch.start()
        self.client = TestClient(server.app)

    def tearDown(self) -> None:
        self._patch.stop()
        server.clear_snapshot_cache()

    def test_index_serves_the_pitch(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("class=\"pitch\"", response.text)
        self.assertIn("cdn.tailwindcss.com", response.text)
        self.assertIn("Mercado y flips", response.text)

    def test_cors_allows_localhost(self) -> None:
        response = self.client.get("/", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_cors_allows_vercel_preview(self) -> None:
        origin = "https://fantasy-git-main-user.vercel.app"
        response = self.client.get("/api/optimize", headers={"Origin": origin})
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

    def test_optimize_returns_xi_and_formation(self) -> None:
        payload = self.client.get("/api/optimize").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["formation"], "4-3-3")
        self.assertEqual(len(payload["xi"]), 11)
        positions = [player["position"] for player in payload["xi"]]
        self.assertEqual(positions.count("POR"), 1)
        self.assertEqual(positions.count("DEF"), 4)

    def test_trends_returns_flips_and_market(self) -> None:
        payload = self.client.get("/api/trends").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["flips"][0]["acceleration"], 9)
        self.assertEqual(payload["rising"][0]["nickname"], "Sube")
        self.assertEqual(payload["market"]["count"], 2)
        self.assertEqual(payload["market"]["listings"][0]["sale_price"], 1000000)

    def test_squads_keep_exact_clause_time_and_skip_missing_marks(self) -> None:
        payload = self.client.get("/api/squads").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["rivals"][0]["cash_eur"], 250000)
        self.assertEqual(payload["self"]["manager_name"], "Yo")
        self.assertEqual(len(payload["clauses"]), 1)
        lock = payload["clauses"][0]["clause_lock"]
        self.assertEqual(lock["local_date"], "2026-10-15")
        self.assertEqual(lock["local_time"], "18:34")
        self.assertTrue(payload["clauses"][0]["at_risk"])
        self.assertEqual(payload["clauses"][0]["clause_rule"], "A")
        names = [row["nickname"] for row in payload["clauses"]]
        self.assertNotIn("SinHora", names)
        self.assertNotIn("Caro", names)
        self.assertEqual([row["nickname"] for row in payload["shield"]], ["Expuesto"])
        self.assertTrue(payload["shield"][0]["is_at_risk"])
        self.assertEqual([row["nickname"] for row in payload["sell"]], ["Pico"])
        self.assertTrue(payload["sell"][0]["sell_signal"])

    def test_needs_reports_safe_liquidity(self) -> None:
        payload = self.client.get("/api/needs").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["liquidity"]["status"], "safe")
        self.assertIn("Caja segura", payload["liquidity"]["headline"])
        self.assertEqual(payload["liquidity"]["cash_eur"], 1500000)
        self.assertEqual(payload["alert_count"], 1)
        self.assertNotIn("events", payload["rivals"][0]["ledger"])

    def test_penalty_and_empty_slot_copy(self) -> None:
        negative = liquidity_case(cash=-20, void=True, reasons=["negative_cash"])
        self.assertEqual(negative["status"], "penalty_risk")
        self.assertIn("negativo", negative["detail"])
        empty = liquidity_case(cash=10, void=True, reasons=["empty_slot"], eligible=7)
        self.assertIn("11 jugadores", empty["detail"])
        self.assertIn("7 jugadores", empty["detail"])

    def test_four_endpoints_share_one_snapshot(self) -> None:
        self.client.get("/api/optimize")
        self.client.get("/api/trends")
        self.client.get("/api/squads")
        self.client.get("/api/needs")
        self.assertEqual(self.loader.call_count, 1)

    def test_parallel_loads_run_once(self) -> None:
        calls = {"n": 0}

        def slow(league: str | None, fresh: bool) -> dict:
            calls["n"] += 1
            time.sleep(0.4)
            return fixture()

        server.clear_snapshot_cache()
        with patch.object(server, "load_snapshot", side_effect=slow):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(server.snapshot, None, False) for _ in range(4)]
                results = [future.result(timeout=5) for future in futures]
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(results), 4)

    def test_index_has_connect_button(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Conectar cuenta con 1 clic", response.text)
        self.assertIn("/api/auth/browser", response.text)

    def test_auth_browser_endpoint_returns_league_without_tokens(self) -> None:
        payload = {
            "ok": True,
            "command": "auth",
            "action": "browser",
            "persisted_to": ".env",
            "refresh_token_present": True,
            "league_id": "9",
            "league_name": "Liga",
            "league_saved": True,
        }
        with patch("server.login_with_browser", return_value=dict(payload)):
            response = self.client.post("/api/auth/browser")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["league_id"], "9")
        self.assertNotIn("access_token", response.text)
        self.assertNotIn("eyJ", response.text)

    def test_auth_browser_endpoint_maps_timeout(self) -> None:
        with patch("server.login_with_browser", side_effect=AuthError("Se agotó la espera.", code="login_timeout")):
            response = self.client.post("/api/auth/browser")
        self.assertEqual(response.status_code, 408)
        self.assertEqual(response.json()["error"]["code"], "login_timeout")

    def test_auth_error_is_401(self) -> None:
        self.loader.side_effect = AuthError("Necesitas entrar.", code="auth_required")
        server.clear_snapshot_cache()
        response = self.client.get("/api/optimize?fresh=true")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "auth_required")


def liquidity_case(*, cash: int, void: bool, reasons: list[str], eligible: int = 11) -> dict:
    return server.liquidity_from(
        {
            "ok": True,
            "cash_eur": cash,
            "cash_known": True,
            "matchday_void": void,
            "void_reasons": reasons,
            "eligible_count": eligible,
            "formation": "4-4-2",
        }
    )


if __name__ == "__main__":
    unittest.main()

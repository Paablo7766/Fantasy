"""Pruebas del tablero. No llaman a la API real."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox.auth import AuthError
from toolbox.normalize import daily_market_is_past


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
        "dashboard_at": "2026-10-20T18:00:00+00:00",
        "market": {
            "ok": True,
            "league_id": "liga-1",
            "league_name": "Liga de prueba",
            "count": 2,
            "fetched_at": "2026-10-20T18:00:00+00:00",
            "listings": [
                {
                    "player_id": "flip-1",
                    "nickname": "Flip",
                    "name": "Flip Player",
                    "position": "DEL",
                    "sale_price": 1000000,
                    "leading_bid": 900000,
                    "listing_expires_at": "2099-01-01T00:00:00+00:00",
                },
                {
                    "player_id": "liga-dummy",
                    "nickname": "Liga",
                    "position": "MC",
                    "sale_price": 100,
                    "listing_expires_at": "2099-01-01T00:00:00+00:00",
                },
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
                            "market_value_change": 250_000,
                        },
                        {
                            "player_id": "own-titular",
                            "nickname": "Titular",
                            "name": "Titular Mal Escalado",
                            "position": "MC",
                            "buyout_clause": 5_000_000,
                            "market_value": 3_000_000,
                            "p_titular": 85,
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
                    "price_delta": 1325257,
                    "p_titular": 0.7,
                },
                {
                    "player_id": "own-titular",
                    "nickname": "Titular",
                    "position": "MC",
                    "price_delta": 12_000,
                    "p_titular": 0.72,
                    "own_expected_points": 5.4,
                },
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
                },
                *[
                    {"player_id": f"catalog-{index}", "nickname": f"Cat{index}", "acceleration": 0, "price_delta": 0}
                    for index in range(19)
                ],
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
                    "price_delta": 1325257,
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
        self._cache_dir = tempfile.mkdtemp(prefix="fantasy-dash-")
        self._env = patch.dict(os.environ, {"FANTASY_CACHE_DIR": self._cache_dir})
        self._env.start()
        server.clear_snapshot_cache()
        board = fixture()
        self.board = board
        self._patch = patch.object(server, "load_snapshot", return_value=board)
        self._core_patch = patch.object(server, "load_core_snapshot", return_value=board)
        self._refresh_titular = patch.object(server, "refresh_squad_titularity_in_index")
        self._optimize_stub = patch.object(
            server,
            "optimize_from_documents",
            side_effect=lambda squads, trends, **kwargs: dict(board["optimize"]),
        )
        self.loader = self._patch.start()
        self.core_loader = self._core_patch.start()
        self._refresh_titular.start()
        self._optimize_stub.start()
        # La lectura ya no descarga: cada prueba arranca con una foto en disco,
        # igual que el panel al abrirse después de un refresco anterior.
        server._write_disk_snapshot("core", None, board)
        server._write_disk_snapshot("full", None, board)
        server.clear_ram_snapshot_cache()
        self.client = TestClient(server.app)

    def _seed(self, board: dict, *, kind: str = "full", age_seconds: float | None = None) -> None:
        """Escribe una foto y, opcionalmente, envejece su marca de guardado."""
        server._write_disk_snapshot(kind, None, board)
        if age_seconds is not None:
            path = server._disk_snapshot_path(kind, None)
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["saved_unix"] = time.time() - age_seconds
            path.write_text(json.dumps(envelope), encoding="utf-8")
        server.clear_ram_snapshot_cache()

    def test_same_league_under_another_key_serves_the_newest_photo(self) -> None:
        """``?league=`` no puede resucitar una foto vieja de la misma liga.

        El panel puede pedir la liga por su slug corto (``7``), por el id
        canónico (``018668579``) o sin parámetro (``_default``). Las tres claves
        eran carpetas distintas, así que la misma liga convivía en varias fotos
        con edades diferentes: abrir un enlace con el id canónico servía datos
        de hace días mientras la portada mostraba los de hace un minuto. Eso es
        «veo información desactualizada», y no tenía nada que ver con el
        refresco.
        """
        board = fixture()
        # Foto vieja guardada bajo el id canónico de la liga.
        server._write_disk_snapshot("core", "018668579", board)
        old_path = server._disk_snapshot_path("core", "018668579")
        envelope = json.loads(old_path.read_text(encoding="utf-8"))
        envelope["saved_unix"] = time.time() - 6 * 3600
        old_path.write_text(json.dumps(envelope), encoding="utf-8")
        # Foto nueva de la misma liga guardada sin clave (``_default``).
        server._write_disk_snapshot("core", None, board)
        server.clear_ram_snapshot_cache()

        fresh = self.client.get("/api/plan?league=018668579").json()
        # No se compara contra 0.0 exacto: entre la escritura de la foto y este
        # GET pasa tiempo real y la edad sube unas décimas. Lo que se protege
        # es «sirve la nueva, no la de hace 6 h».
        self.assertLess(fresh["photo_age_seconds"], 60.0)
        self.assertFalse(fresh["stale"])

    def test_a_different_league_never_borrows_another_photo(self) -> None:
        """La corrección compara el ``league_id`` de dentro, no el nombre.

        ``?league=`` puede ser un slug corto o el id canónico: si la foto
        pedida existe pero es de otra liga, la más nueva de la liga pedida es
        la suya y no la de la portada.
        """
        board = fixture()
        other = fixture()
        other["market"] = dict(other["market"], league_id="liga-2")
        other["squads"] = dict(other["squads"], league_id="liga-2")
        server._write_disk_snapshot("core", None, board)
        server._write_disk_snapshot("core", "otra", other)
        server.clear_ram_snapshot_cache()

        payload = self.client.get("/api/plan?league=otra").json()
        self.assertEqual(payload["league_name"], "Liga de prueba")
        # Sirve su propia foto (liga-2), no la de la portada aunque sea más
        # nueva: la liga manda sobre la antigüedad.
        self.assertEqual(payload["league_id"], "liga-2")

    def test_refresh_replaces_the_ram_photo_instead_of_serving_the_old_one(self) -> None:
        """Un refresco debe cambiar lo que sirve el GET, no solo el disco.

        La foto vive en RAM (lectura instantánea) y en disco. Si la RAM no se
        invalida al guardar la nueva, el GET sigue sirviendo la anterior: la
        descarga termina bien, el disco está actualizado y el panel no cambia.
        Ese era el fallo que hacía imposible saber si la actualización sirvió.
        """
        board = fixture()
        server._write_disk_snapshot("core", None, board)
        server.clear_ram_snapshot_cache()
        primero = self.client.get("/api/plan").json()
        # ``photo_age_seconds`` se redondea a una décima: recién guardada la
        # foto vale 0.0, pero el reloj de pared puede colar una décima entre
        # el guardado y la lectura. Lo que importa es que sea *fresca*.
        self.assertLess(primero["photo_age_seconds"], 1.0)

        nuevo = fixture()
        nuevo["squads"] = dict(nuevo["squads"], league_name="Liga renombrada")
        time.sleep(1.1)
        server._write_disk_snapshot("core", None, nuevo)
        segundo = self.client.get("/api/plan").json()
        # El disco es más nuevo: la copia en RAM no puede seguir ganando.
        self.assertLess(segundo["photo_age_seconds"], 1.0)
        self.assertEqual(segundo["league_name"], "Liga renombrada")

    def test_saving_a_photo_drops_the_other_ram_keys_of_the_same_league(self) -> None:
        """``_store_snapshot`` no puede dejar vivas las claves hermanas.

        La misma liga se cachea bajo ``_default``, el id canónico y el slug
        corto. Un refresco escrito en una clave dejaba las otras intactas, así
        que la respuesta dependía de por dónde se preguntara.
        """
        board = fixture()
        server._store_snapshot("core", None, True, board)
        viejo = dict(board)
        viejo["market"] = dict(board["market"], league_name="Nombre viejo")
        # Una copia antigua bajo la clave del id canónico.
        server._store_snapshot("core", "liga-1", True, viejo)

        nuevo = dict(board)
        nuevo["market"] = dict(board["market"], league_name="Nombre nuevo")
        server._store_snapshot("core", None, True, nuevo)

        for league in (None, "liga-1"):
            payload = server.snapshot(league, tier="core")
            self.assertEqual(payload["market"]["league_name"], "Nombre nuevo")

    def _wait_loader(self, count: int = 1, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.loader.call_count >= count:
                return
            time.sleep(0.02)
        self.fail(f"load_snapshot no llegó a {count} llamadas ({self.loader.call_count})")

    def tearDown(self) -> None:
        self._patch.stop()
        self._core_patch.stop()
        self._refresh_titular.stop()
        self._optimize_stub.stop()
        server.clear_snapshot_cache()
        self._env.stop()
        shutil.rmtree(self._cache_dir, ignore_errors=True)

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

    def test_cors_allows_production_vercel(self) -> None:
        origin = "https://fantasy-45mn.vercel.app"
        response = self.client.get("/api/plan", headers={"Origin": origin})
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

    def test_plan_uses_core_snapshot(self) -> None:
        payload = self.client.get("/api/plan").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(self.loader.call_count, 0)
        self.assertEqual(self.core_loader.call_count, 0)
        self.assertIsInstance(payload.get("actions"), list)
        self.assertEqual(payload["dashboard_at"], fixture()["dashboard_at"])

    def test_clause_intel_uses_core_snapshot(self) -> None:
        payload = self.client.get("/api/clause-intel").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload.get("command"), "clause-intel")
        self.assertEqual(self.loader.call_count, 0)
        self.assertIn("offers", payload)
        self.assertIn("clause_window_open", payload)

    def test_optimize_returns_xi_and_formation(self) -> None:
        payload = self.client.get("/api/optimize").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["formation"], "4-3-3")
        self.assertEqual(len(payload["xi"]), 11)
        positions = [player["position"] for player in payload["xi"]]
        self.assertEqual(positions.count("POR"), 1)
        self.assertEqual(positions.count("DEF"), 4)

    def test_optimize_without_block_answers_503_instead_of_500(self) -> None:
        """Una foto sin once no puede tumbar el endpoint.

        El ``KeyError`` devolvía 500 y el panel se quedaba pintando el once que
        tenía guardado el navegador: se veía «no ha cargado» con datos de días
        atrás. Ahora se responde sin once y con el motivo.
        """
        board = dict(self.board)
        board.pop("optimize", None)
        self._seed(board)
        self._seed(board, kind="core")
        with patch.object(server, "_enrich_board_optimize", side_effect=lambda b, *a, **k: b):
            response = self.client.get("/api/optimize")
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "optimize_missing")

    def test_optimize_propagates_the_measured_delta_to_the_lineup(self) -> None:
        """El once no puede disfrazar el estimado de FútbolFantasy.

        El catálogo ya distingue el Δ medido entre dos capturas propias de la
        estimación de terceros, pero ``/api/optimize`` solo copiaba
        ``price_delta``: el campo pintaba todo con ``≈`` aunque el dato medido
        existiera, y el once contaba una historia distinta que el mercado.
        """
        body = {
            "xi": [{"player_id": "p1", "name": "Medido"}],
            "benched": [{"player_id": "p2", "name": "SoloEstimado"}],
        }
        board = {
            "trends": {
                "players": [
                    {"player_id": "p1", "price_delta": 12_000, "measured_price_delta": 12_000},
                    {"player_id": "p2", "price_delta": -3_500, "measured_price_delta": None},
                ]
            },
            "squads": {},
        }

        server._stamp_squad_price_delta(body, board)

        medido = body["xi"][0]
        self.assertEqual(medido["measured_price_delta"], 12_000)
        self.assertEqual(medido["measured_price_delta_source"], "capturas_propias")
        self.assertEqual(medido["price_delta_estimated"], 12_000)

        # Sin capturas propias que restar no se inventa un medido: queda solo
        # el estimado, que la interfaz marcará con ``≈``.
        estimado = body["benched"][0]
        self.assertNotIn("measured_price_delta", estimado)
        self.assertEqual(estimado["price_delta"], -3_500)

    def test_trends_returns_flips_and_market(self) -> None:
        payload = self.client.get("/api/trends").json()
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload.get("sources"), dict)
        self.assertIn("partial", payload)
        self.assertEqual(payload["flips"][0]["acceleration"], 9)
        self.assertEqual(payload["flips"][0]["price_delta"], 1325257)
        self.assertEqual(payload["rising"][0]["nickname"], "Sube")
        self.assertEqual(payload["rising"][0]["price_delta"], 1325257)
        self.assertEqual(payload["market"]["count"], 2)
        self.assertEqual(payload["market"]["listings"][0]["sale_price"], 1000000)

    def test_trends_market_decisions_expose_auction_v2_contract(self) -> None:
        payload = self.client.get("/api/trends").json()
        decisions = payload.get("market_decisions")
        self.assertIsInstance(decisions, list)
        self.assertGreater(len(decisions), 0)
        row = decisions[0]
        for key in (
            "optimal_bid_eur",
            "win_probability",
            "intrinsic_valuation_eur",
            "expected_surplus_eur",
            "rival_knockout_targets",
            "bid_intent",
        ):
            self.assertIn(key, row)
        self.assertIsInstance(row["rival_knockout_targets"], list)

    def test_trends_replaces_closed_daily_market(self) -> None:
        past = fixture()
        past["trends"]["players"] = [{"player_id": str(index)} for index in range(20)]
        past["market"] = {
            "ok": True,
            "count": 2,
            "fetched_at": "2026-10-19T18:00:00+00:00",
            "listings": [
                {
                    "player_id": "old",
                    "nickname": "Ayer",
                    "position": "DEL",
                    "sale_price": 100,
                    "listing_expires_at": "2020-01-01T00:00:00+00:00",
                },
                {
                    "player_id": "rival-old",
                    "nickname": "RivalViejo",
                    "position": "MC",
                    "sale_price": 50,
                    "seller_team_id": "rival",
                    "listing_expires_at": "2099-01-01T00:00:00+00:00",
                },
            ],
        }
        current = fixture()
        current["market"] = {
            "ok": True,
            "count": 1,
            "fetched_at": "2026-10-20T19:00:00+00:00",
            "listings": [
                {
                    "player_id": "new",
                    "nickname": "Hoy",
                    "position": "DEL",
                    "sale_price": 200,
                    "listing_expires_at": "2099-01-01T00:00:00+00:00",
                }
            ],
        }
        self._seed(past, kind="full")
        self._seed(current, kind="core")
        payload = self.client.get("/api/trends").json()
        self.assertEqual(self.loader.call_count, 0)
        names = [row["nickname"] for row in payload["market"]["listings"]]
        self.assertEqual(names, ["Hoy"])
        self.assertTrue(daily_market_is_past(past["market"]))
        self.assertFalse(daily_market_is_past(current["market"]))
        self.assertFalse(daily_market_is_past({"listings": [{"nickname": "SinCierre"}]}))
        self.assertTrue(
            daily_market_is_past(
                {"fetched_at": "2026-10-14T18:00:00+00:00", "listings": [{"nickname": "Viejo"}]}
            )
        )

    def test_trends_fills_missing_flip_price_delta_from_catalog(self) -> None:
        board = fixture()
        board["flip"]["signings"][0] = {
            **board["flip"]["signings"][0],
            "price_delta": None,
        }
        board["trends"]["players"] = [
            {
                "player_id": "flip-1",
                "nickname": "Flip",
                "price_delta": 1325257,
                "acceleration": 9,
                "fantasy_price": 10_000_000,
                "sale_price": 8_674_743,
            }
        ]
        self._patch.stop()
        self._core_patch.stop()
        self._patch = patch.object(server, "load_snapshot", return_value=board)
        self._core_patch = patch.object(server, "load_core_snapshot", return_value=board)
        self.loader = self._patch.start()
        self.core_loader = self._core_patch.start()
        self._seed(board, kind="full")
        payload = self.client.get("/api/trends").json()
        self.assertEqual(payload["flips"][0]["price_delta"], 1325257)

    def test_clause_board_returns_every_rival_clause_not_only_golden_rule(self) -> None:
        """El tablero completo no filtra por regla de oro: 3 rivales, 3 filas.

        ``/api/squads`` solo publica las de regla A/B (aquí, una). Antes de un
        desbloqueo eso deja al usuario a ciegas con el resto de la liga.
        """
        payload = self.client.get("/api/clause-board").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["counts"]["total"], 3)
        self.assertEqual(payload["counts"]["golden"], 1)
        names = [row["nickname"] for row in payload["rows"]]
        self.assertIn("Caro", names)
        self.assertIn("SinHora", names)
        rules = {row["nickname"]: row["clause_rule"] for row in payload["rows"]}
        self.assertEqual(rules["Clausula"], "A")
        self.assertIsNone(rules["Caro"])
        # Sin histórico guardado no se inventa la cláusula anterior.
        self.assertIsNone(payload["from_day"])
        self.assertTrue(all(row["prev_clause_eur"] is None for row in payload["rows"]))
        self.assertFalse(any(row["raised_today"] for row in payload["rows"]))

    def test_clause_board_diff_uses_the_photo_day(self) -> None:
        """La subida se fecha contra la foto servida, no contra el reloj."""
        photo_day = self.client.get("/api/clause-board").json()["photo_day"]
        self.assertIsNotNone(photo_day)
        previous = (date.fromisoformat(photo_day) - timedelta(days=1)).isoformat()
        history = Path(self._cache_dir) / "clause_snapshot_history.json"
        history.write_text(
            json.dumps(
                {
                    "version": 1,
                    "days": {
                        previous: {"rival": {"p1": 7_000_000, "p2": 1000, "p3": 20_000_000}},
                    },
                }
            ),
            encoding="utf-8",
        )
        payload = self.client.get("/api/clause-board").json()
        self.assertEqual(payload["from_day"], previous)
        self.assertEqual(payload["diff_gap_days"], 1)
        rows = {row["nickname"]: row for row in payload["rows"]}
        raised = rows["Clausula"]
        self.assertTrue(raised["raised_today"])
        self.assertEqual(raised["prev_clause_eur"], 7_000_000)
        self.assertEqual(raised["clause_delta_eur"], 1_000_000)
        self.assertEqual(raised["raises"][0]["cost_eur"], 500_000)
        self.assertFalse(rows["Caro"]["raised_today"])

    def test_core_reuses_cached_full_snapshot(self) -> None:
        """Con foto completa en disco, la lectura rápida no descarga nada."""
        self.client.get("/api/trends")
        self.client.get("/api/squads")
        self.assertEqual(self.loader.call_count, 0)
        self.assertEqual(self.core_loader.call_count, 0)

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
        own_players = {row["player_id"]: row for row in payload["self"]["players"]}
        self.assertEqual(own_players["peak-1"]["price_delta"], 250_000)
        self.assertEqual(own_players["own-titular"]["p_titular"], 0.72)
        self.assertEqual(own_players["own-titular"]["own_expected_points"], 5.4)
        self.assertEqual(own_players["own-titular"]["price_delta"], 12_000)
        self.assertEqual(payload["self"]["market_value_total"], 1_000_000 + 2_000_000 + 3_000_000)
        self.assertEqual(payload["self"]["price_delta_day"], 250_000 + 12_000)

    def test_squads_borrow_full_trends_when_core_is_hollow(self) -> None:
        full = fixture()
        hollow = fixture()
        hollow["trends"] = server._empty_trends(
            league_id=hollow["squads"]["league_id"],
            league_name=hollow["squads"]["league_name"],
        )
        with patch.object(server, "_board", return_value=hollow):
            with patch.object(server, "_borrow_full_trends", return_value=full["trends"]):
                payload = self.client.get("/api/squads").json()
        own = {row["player_id"]: row for row in payload["self"]["players"]}
        self.assertEqual(own["own-titular"]["price_delta"], 12_000)
        self.assertEqual(own["own-titular"]["p_titular"], 0.72)

    def test_needs_reports_safe_liquidity(self) -> None:
        payload = self.client.get("/api/needs").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["liquidity"]["status"], "safe")
        self.assertIn("Caja segura", payload["liquidity"]["headline"])
        self.assertEqual(payload["liquidity"]["cash_eur"], 1500000)
        self.assertEqual(payload["alert_count"], 1)
        self.assertNotIn("events", payload["rivals"][0]["ledger"])

    def test_rival_intel_exposes_cash_and_bid_limit(self) -> None:
        payload = self.client.get("/api/rival-intel").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "rival-intel")
        self.assertGreater(payload["days_elapsed"], 0)
        teams = payload["teams"]
        self.assertIn("rival", teams)
        rival = teams["rival"]
        self.assertIsInstance(rival["calculated_cash"], int)
        self.assertIsInstance(rival["max_bid_limit"], int)
        self.assertGreaterEqual(rival["max_bid_limit"], rival["calculated_cash"])
        self.assertIsInstance(rival["detected_hidden_expenses"], list)
        # La cota nunca queda por debajo del saldo que la API ya publica.
        if isinstance(rival.get("reconciliation"), dict):
            self.assertTrue(rival["reconciliation"]["covers_observed"])

    def test_penalty_and_empty_slot_copy(self) -> None:
        negative = liquidity_case(cash=-20, void=True, reasons=["negative_cash"])
        self.assertEqual(negative["status"], "penalty_risk")
        self.assertIn("negativo", negative["detail"])
        empty = liquidity_case(cash=10, void=True, reasons=["empty_slot"], eligible=7)
        self.assertIn("11 jugadores", empty["detail"])
        self.assertIn("7 jugadores", empty["detail"])

    def test_read_endpoints_never_download(self) -> None:
        """Todos los GET sirven la foto guardada: cero llamadas al cargador."""
        for path in (
            "/api/optimize",
            "/api/trends",
            "/api/squads",
            "/api/needs",
            "/api/plan",
            "/api/clause-intel",
            "/api/league-race",
            "/api/data-health",
            "/api/market/quant-radar",
        ):
            payload = self.client.get(path).json()
            self.assertTrue(payload.get("ok") is not False, path)
        self.assertEqual(self.core_loader.call_count, 0)
        self.assertEqual(self.loader.call_count, 0)

    def test_read_ignores_fresh_flag(self) -> None:
        """``?fresh=true`` ya no descarga: la red solo la mueve el POST."""
        payload = self.client.get("/api/trends?fresh=true").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(self.loader.call_count, 0)
        self.assertEqual(self.core_loader.call_count, 0)

    def test_read_serves_six_hour_old_photo_with_metadata(self) -> None:
        board = fixture()
        board["dashboard_at"] = "2026-10-19T18:00:00+00:00"
        board["trends"]["players"] = [{"player_id": f"p{index}", "nickname": f"J{index}"} for index in range(20)]
        six_hours = 6 * 60 * 60
        self._seed(board, kind="full", age_seconds=six_hours)
        self._seed(board, kind="core", age_seconds=six_hours)

        started = time.perf_counter()
        payload = self.client.get("/api/plan").json()
        elapsed = time.perf_counter() - started

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dashboard_at"], "2026-10-19T18:00:00+00:00")
        self.assertTrue(payload["is_stale"])
        self.assertGreaterEqual(payload["photo_age_seconds"], six_hours - 5)
        self.assertTrue(payload["last_updated"])
        self.assertLess(elapsed, 1.0)
        self.assertEqual(self.core_loader.call_count, 0)
        self.assertEqual(self.loader.call_count, 0)

    def test_read_without_photo_asks_to_refresh_instead_of_downloading(self) -> None:
        server.clear_snapshot_cache()
        response = self.client.get("/api/plan")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "offline_miss")
        self.assertEqual(self.core_loader.call_count, 0)
        self.assertEqual(self.loader.call_count, 0)

    def test_refresh_downloads_and_overwrites_the_photo(self) -> None:
        old = fixture()
        old["dashboard_at"] = "2026-10-01T09:00:00+00:00"
        self._seed(old, kind="core", age_seconds=3 * 24 * 60 * 60)

        fresh_board = fixture()
        fresh_board["dashboard_at"] = "2026-10-24T16:00:00+00:00"
        fresh_board["trends"]["players"] = [
            {"player_id": f"p{index}", "nickname": f"J{index}"} for index in range(20)
        ]
        self.core_loader.side_effect = lambda league, fresh: fresh_board if fresh else old
        self.loader.side_effect = lambda league, fresh: fresh_board if fresh else old

        payload = self.client.post("/api/plan/refresh").json()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dashboard_at"], "2026-10-24T16:00:00+00:00")
        self.assertFalse(payload["is_stale"])
        self.assertTrue(payload["refresh"]["ok"])
        self.assertEqual(self.core_loader.call_count, 1)
        self.assertEqual(self.loader.call_count, 1)
        # El refresco escribió en disco: el siguiente GET ya ve la foto nueva.
        self.assertEqual(server.snapshot(None, tier="core")["dashboard_at"], "2026-10-24T16:00:00+00:00")

    def test_refresh_reports_core_photo_when_full_fails(self) -> None:
        fresh_core = fixture()
        fresh_core["dashboard_at"] = "2026-10-24T16:00:00+00:00"
        self.core_loader.side_effect = lambda league, fresh: fresh_core
        self.loader.side_effect = RuntimeError("scrapers caídos")

        payload = self.client.post("/api/plan/refresh").json()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dashboard_at"], "2026-10-24T16:00:00+00:00")
        self.assertFalse(payload["refresh"]["ok"])
        self.assertTrue(payload["refresh"]["core"])
        self.assertIn("scrapers", payload["refresh"]["error"]["message"])

    def test_parallel_loads_read_the_same_photo_without_network(self) -> None:
        calls = {"n": 0}

        def slow(league: str | None, fresh: bool) -> dict:
            calls["n"] += 1
            return fixture()

        with patch.object(server, "load_snapshot", side_effect=slow):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [future.result(timeout=5) for future in (
                    pool.submit(server.snapshot, None, tier="full") for _ in range(4)
                )]
        self.assertEqual(calls["n"], 0)
        self.assertEqual(len(results), 4)

    def test_index_has_connect_button(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Conectar cuenta con 1 clic", response.text)
        self.assertIn("/api/auth/browser", response.text)

    def test_squads_keep_exact_clause_time_and_skip_missing_marks(self) -> None:
        payload = self.client.get("/api/squads").json()

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
        """El 401 de credenciales sale del refresco, que es el único que descarga."""
        self.core_loader.side_effect = AuthError("Necesitas entrar.", code="auth_required")
        response = self.client.post("/api/plan/refresh")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "auth_required")

    def test_disk_photo_survives_ram_reset(self) -> None:
        first = self.client.get("/api/optimize").json()
        self.assertTrue(first["ok"])
        server.clear_ram_snapshot_cache()

        started = threading.Event()

        def fail_if_called(league: str | None, fresh: bool) -> dict:
            started.set()
            return fixture()

        with patch.object(server, "load_core_snapshot", side_effect=fail_if_called):
            t0 = time.perf_counter()
            payload = self.client.get("/api/optimize").json()
            elapsed = time.perf_counter() - t0
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dashboard_at"], first["dashboard_at"])
        self.assertLess(elapsed, 1.0)
        # La foto salió de disco: nadie llamó al cargador.
        self.assertFalse(started.is_set())

    def test_hollow_full_disk_prefers_core_for_trends(self) -> None:
        hollow = fixture()
        hollow["dashboard_at"] = "2026-10-19T17:00:00+00:00"
        hollow["squads"]["league_name"] = "Liga de prueba"
        hollow["trends"]["players"] = [{"player_id": f"p{index}", "nickname": f"J{index}"} for index in range(11)]
        core = fixture()
        core["dashboard_at"] = "2026-10-21T12:00:00+00:00"
        core["squads"]["league_name"] = "Liga real"
        core["trends"] = {"ok": True, "partial": True, "players": [], "league_name": "Liga real"}
        server._write_disk_snapshot("full", None, hollow)
        server._write_disk_snapshot("core", None, core)
        server.clear_ram_snapshot_cache()

        payload = self.client.get("/api/trends").json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["league_name"], "Liga real")
        self.assertIn("photo_age_seconds", payload)
        self.assertIn("last_updated", payload)

    def test_trends_uses_disk_full_when_ram_core_has_no_sources(self) -> None:
        rich = fixture()
        rich["dashboard_at"] = "2026-10-22T10:00:00+00:00"
        rich["trends"]["players"] = [{"player_id": f"p{index}", "nickname": f"J{index}"} for index in range(20)]
        rich["trends"]["sources"] = {"understat": {"ok": True, "count": 3, "error": None}}
        core = fixture()
        core["dashboard_at"] = "2026-10-22T11:00:00+00:00"
        core["trends"] = {"ok": True, "partial": True, "players": [], "sources": {}, "league_name": "Liga real"}
        server._write_disk_snapshot("full", None, rich)
        server.clear_ram_snapshot_cache()
        server._cache["core:0:"] = (time.monotonic(), core)

        payload = self.client.get("/api/trends").json()
        self.assertEqual(payload["dashboard_at"], "2026-10-22T10:00:00+00:00")
        self.assertIn("understat", payload["sources"])

    def test_background_photo_keeps_the_cache_dir_it_started_with(self) -> None:
        """El refresco fija el directorio de caché al empezar, no al terminar."""
        release = threading.Event()
        started = threading.Event()

        def slow(league: str | None, fresh: bool) -> dict:
            started.set()
            release.wait(3)
            return fixture()

        self.loader.side_effect = slow
        server.clear_snapshot_cache()
        other = tempfile.mkdtemp(prefix="fantasy-dash-other-")
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(server.refresh_board, None, tier="full")
                self.assertTrue(started.wait(2))
                os.environ["FANTASY_CACHE_DIR"] = other
                release.set()
                future.result(timeout=5)
            expected = os.path.join(self._cache_dir, "dashboard", "_default", "full.json")
            self.assertTrue(os.path.isfile(expected))
            leaked = os.path.join(other, "dashboard", "_default", "full.json")
            self.assertFalse(os.path.exists(leaked))
        finally:
            release.set()
            os.environ["FANTASY_CACHE_DIR"] = self._cache_dir
            shutil.rmtree(other, ignore_errors=True)

    def test_hollow_full_disk_served_without_downloading(self) -> None:
        """Sin foto rápida, una completa a medias se sirve igual: no se descarga."""
        board = fixture()
        board["dashboard_at"] = "2026-10-19T19:00:00+00:00"
        board["trends"]["players"] = [{"player_id": f"p{index}", "nickname": f"J{index}"} for index in range(11)]
        self._seed(board, kind="full")
        server._disk_snapshot_path("core", None).unlink(missing_ok=True)

        started = time.perf_counter()
        payload = self.client.get("/api/trends").json()
        elapsed = time.perf_counter() - started
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dashboard_at"], "2026-10-19T19:00:00+00:00")
        self.assertLess(elapsed, 1.0)
        self.assertEqual(self.loader.call_count, 0)

    def test_day_old_market_snapshot_returns_without_waiting(self) -> None:
        board = fixture()
        board["dashboard_at"] = "2026-10-19T18:00:00+00:00"
        board["trends"]["players"] = [{"player_id": f"p{index}", "nickname": f"J{index}"} for index in range(20)]
        self._seed(board, kind="full", age_seconds=36 * 60 * 60)

        started = time.perf_counter()
        payload = self.client.get("/api/trends").json()
        elapsed = time.perf_counter() - started
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dashboard_at"], "2026-10-19T18:00:00+00:00")
        self.assertTrue(payload["is_stale"])
        self.assertLess(elapsed, 1.0)
        self.assertEqual(self.loader.call_count, 0)

    def test_fresh_flag_does_not_bypass_the_photo(self) -> None:
        """``?fresh=true`` en un GET sigue leyendo la foto, no descarga."""
        board = fixture()
        board["dashboard_at"] = "2026-10-18T15:00:00+00:00"
        self._seed(board, kind="core")
        loader = self.core_loader

        payload = self.client.get("/api/optimize?fresh=true").json()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dashboard_at"], "2026-10-18T15:00:00+00:00")
        self.assertEqual(loader.call_count, 0)


class EnrichOptimizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cache_dir = tempfile.mkdtemp(prefix="fantasy-enrich-")
        self._env = patch.dict(os.environ, {"FANTASY_CACHE_DIR": self._cache_dir})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        shutil.rmtree(self._cache_dir, ignore_errors=True)

    def test_core_optimize_borrows_full_trends(self) -> None:
        board = fixture()
        board["trends"] = {"ok": True, "partial": True, "players": []}
        full = fixture()
        full["trends"]["players"] = [{"player_id": f"catalog-{index}", "nickname": f"J{index}"} for index in range(20)]
        server._write_disk_snapshot("full", None, full)
        patched: list[object] = []

        def record(optimize, squad, trends, **kwargs):
            patched.append(trends)
            return dict(optimize)

        with patch.object(server, "_patch_optimize_titularity", side_effect=record):
            enriched = server._enrich_board_optimize(board, None)
        self.assertEqual(len(patched), 1)
        trends_arg = patched[0]
        self.assertIsInstance(trends_arg, dict)
        self.assertGreaterEqual(len(trends_arg.get("players") or []), 20)
        self.assertTrue(enriched["optimize"]["ok"])


class OverlayHistoryTests(unittest.TestCase):
    def test_full_board_takes_newer_core_history(self) -> None:
        full = {
            "dashboard_at": "2026-10-20T18:00:00+00:00",
            "needs": {"history": {"buy_count": 0, "war_count": 0}},
        }
        core = {
            "dashboard_at": "2026-10-20T21:00:00+00:00",
            "needs": {
                "history": {
                    "buy_count": 35,
                    "priced_count": 15,
                    "war_count": 6,
                    "median_premium": 0.18,
                }
            },
        }
        with patch.object(server, "_core_boards", return_value=[core]):
            merged = server._overlay_core_history(full, None)
        self.assertEqual(merged["needs"]["history"]["war_count"], 6)
        self.assertEqual(merged["needs"]["history"]["buy_count"], 35)


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

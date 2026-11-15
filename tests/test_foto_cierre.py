"""Foto del mercado antes del cierre (``toolbox.foto_cierre`` y su endpoint).

Ninguna prueba abre un socket ni espera de verdad.
"""

from __future__ import annotations

import random
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from toolbox import foto_cierre

TOKEN = "token-de-prueba"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class FranjaTests(unittest.TestCase):
    def test_invierno_y_verano(self) -> None:
        # 12:47 UTC es 13:47 en Madrid en noviembre; en julio es 14:47.
        self.assertTrue(foto_cierre.en_ventana(utc("2026-11-16T12:47:00")))
        self.assertFalse(foto_cierre.en_ventana(utc("2027-07-16T12:47:00")))
        self.assertTrue(foto_cierre.en_ventana(utc("2027-07-16T11:47:00")))
        self.assertFalse(foto_cierre.en_ventana(utc("2026-11-16T11:47:00")))

    def test_la_espera_nunca_pasa_de_las_14_03(self) -> None:
        rng = random.Random(1)
        for minuto in range(30, 60):
            now = utc(f"2026-11-16T12:{minuto:02d}:00")
            for _ in range(50):
                espera = foto_cierre.espera_al_azar(now, rng)
                hora = (foto_cierre.ahora_madrid(now).timestamp() + espera)
                tope = datetime(2026, 11, 16, 14, 3, tzinfo=foto_cierre.MADRID).timestamp()
                self.assertGreaterEqual(espera, 0.0)
                self.assertLessEqual(espera, foto_cierre.ESPERA_MAX_MIN * 60.0)
                self.assertLessEqual(hora, tope + 1e-6)

    def test_una_foto_por_dia(self) -> None:
        foto_cierre._reset_para_pruebas()
        now = utc("2026-11-16T12:47:00")
        self.assertTrue(foto_cierre.reservar_dia(now))
        self.assertFalse(foto_cierre.reservar_dia(now))
        self.assertTrue(foto_cierre.reservar_dia(utc("2026-11-17T12:47:00")))
        foto_cierre._reset_para_pruebas()


class _Cliente:
    """Cliente de mentira: cuenta las peticiones al mercado."""

    def __init__(self) -> None:
        self.llamadas = 0

    def market_snapshot(self, league):  # noqa: ANN001
        self.llamadas += 1
        return {
            "league_id": "018668579",
            "own_team_id": "40960918",
            "listings": [
                {"market_id": "1", "player_id": "10", "own_bid": 1_200_000, "bid_count": 2,
                 "market_value": 1_000_000, "listing_expires_at": "2026-11-16T13:08:00+00:00"},
                {"market_id": "2", "player_id": "11", "own_bid": None, "bid_count": 0,
                 "market_value": 500_000, "listing_expires_at": "2026-11-16T13:08:00+00:00"},
            ],
        }


class CapturaTests(unittest.TestCase):
    def test_una_peticion_y_guarda_el_tablero_sin_cerrar_subastas(self) -> None:
        cliente = _Cliente()
        visto = {}

        def falso_capture_live(market, squads, ledgers, *, now):  # noqa: ANN001
            visto.update(market=market, squads=squads, ledgers=ledgers)
            return {"board": 2, "results": 0}

        with patch("toolbox.auction_journal.capture_live", falso_capture_live):
            res = foto_cierre.capturar(cliente, None, now=utc("2026-11-16T12:55:00"))
        self.assertEqual(cliente.llamadas, 1)
        self.assertEqual(res["anuncios"], 2)
        self.assertEqual(res["con_tu_puja"], 1)
        self.assertEqual(res["guardadas"], 2)
        self.assertEqual(visto["ledgers"], [])
        self.assertEqual(visto["squads"]["squads"], [{"team_id": "40960918", "is_self": True}])

    def test_programar_espera_y_lanza_en_un_hilo(self) -> None:
        foto_cierre._reset_para_pruebas()
        hecho = threading.Event()
        dormido = []

        def lanzar():
            hecho.set()
            return {"anuncios": 0}

        espera = foto_cierre.programar(
            lanzar, now=utc("2026-11-16T12:47:00"), rng=random.Random(3), dormir=dormido.append
        )
        self.assertTrue(hecho.wait(2.0))
        self.assertEqual(dormido, [espera])
        foto_cierre._reset_para_pruebas()

    def test_un_fallo_llega_al_manejador(self) -> None:
        foto_cierre._reset_para_pruebas()
        fallos = []
        listo = threading.Event()

        def lanzar():
            raise SystemExit(1)

        def al_fallar(exc):  # noqa: ANN001
            fallos.append(exc)
            listo.set()

        foto_cierre.programar(lanzar, now=utc("2026-11-16T12:47:00"), dormir=lambda s: None, al_fallar=al_fallar)
        self.assertTrue(listo.wait(2.0))
        self.assertIsInstance(fallos[0], SystemExit)
        self.assertFalse(foto_cierre.estado()["resultado"]["ok"])
        foto_cierre._reset_para_pruebas()


class UnaSolaPeticionTests(unittest.TestCase):
    """``LaligaClient.market_snapshot``: con la lista de ligas caducada, solo sale el mercado."""

    def test_solo_el_mercado_sale_a_la_red(self) -> None:
        import tempfile
        import time as _time
        from pathlib import Path

        import httpx

        from toolbox import net
        from toolbox.cache import ResponseCache

        class Tokens:
            def authorization_value(self) -> str:
                return "Bearer test-token"

            def refresh(self) -> str:
                return "Bearer refreshed"

        with tempfile.TemporaryDirectory() as folder:
            cache = ResponseCache(Path(folder))
            try:
                # Lista de ligas guardada hace dos días: caducada (TTL 30 min).
                for url in net.league_list_urls():
                    cache.put_json(url, [{"id": "018668579", "name": "Liga", "team": {"id": "40960918"}}], 1.0)
                pedidas: list[str] = []

                def responder(request: httpx.Request) -> httpx.Response:
                    pedidas.append(str(request.url))
                    return httpx.Response(200, json=[{"id": "1", "playerMaster": {"id": "10"}, "salePrice": 1000000}])

                http = httpx.Client(transport=httpx.MockTransport(responder))
                env = patch.dict("os.environ", {"LALIGA_ENV": "production", "LEAGUE_ID": "018668579"})
                with env, patch.object(_time, "time", wraps=_time.time):
                    client = net.LaligaClient(tokens=Tokens(), cache=cache, http=http, sleeper=lambda _s: None)
                    with patch.object(cache, "get_json", return_value=None):
                        doc = client.market_snapshot(None)
                self.assertEqual(len(pedidas), 1, pedidas)
                self.assertIn("/market", pedidas[0])
                self.assertEqual(doc["league_id"], "018668579")
                self.assertEqual(doc["own_team_id"], "40960918")
            finally:
                cache.close()
                net.reset_human_pacer()


class EndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(server.app)
        self._env = patch.dict("os.environ", {"REMOTE_REFRESH_TOKEN": TOKEN})
        self._env.start()
        foto_cierre._reset_para_pruebas()

    def tearDown(self) -> None:
        self._env.stop()
        foto_cierre._reset_para_pruebas()

    def test_sin_token_no_hace_nada(self) -> None:
        with patch("toolbox.foto_cierre.programar") as programar:
            r = self.client.post("/api/remote/foto-cierre")
        self.assertEqual(r.status_code, 401)
        programar.assert_not_called()

    def test_fuera_de_franja_no_programa(self) -> None:
        with patch("toolbox.foto_cierre.en_ventana", return_value=False), patch(
            "toolbox.foto_cierre.programar"
        ) as programar:
            r = self.client.post("/api/remote/foto-cierre", headers={"X-Remote-Token": TOKEN})
        self.assertEqual(r.json()["estado"], "fuera_de_franja")
        programar.assert_not_called()

    def test_dentro_programa_una_vez(self) -> None:
        with patch("toolbox.foto_cierre.en_ventana", return_value=True), patch(
            "toolbox.foto_cierre.programar", return_value=120.0
        ) as programar, patch.object(server, "kill_switch_state", return_value={"tripped": False}):
            r1 = self.client.post("/api/remote/foto-cierre", headers={"X-Remote-Token": TOKEN})
            r2 = self.client.post("/api/remote/foto-cierre", headers={"X-Remote-Token": TOKEN})
        self.assertEqual(r1.status_code, 202)
        self.assertEqual(r1.json()["estado"], "programada")
        self.assertEqual(r2.json()["estado"], "ya_programada")
        self.assertEqual(programar.call_count, 1)

    def test_con_kill_switch_no_programa(self) -> None:
        with patch("toolbox.foto_cierre.en_ventana", return_value=True), patch(
            "toolbox.foto_cierre.programar"
        ) as programar, patch.object(server, "kill_switch_state", return_value={"tripped": True}):
            r = self.client.post("/api/remote/foto-cierre", headers={"X-Remote-Token": TOKEN})
        self.assertEqual(r.json()["estado"], "kill_switch")
        programar.assert_not_called()


if __name__ == "__main__":
    unittest.main()

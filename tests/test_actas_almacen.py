"""Almacén acumulado de actas: el xP 2.0 no pierde a quien fichas después de la última descarga a disco."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from toolbox import player_history
from toolbox.cache import ResponseCache
from toolbox.net import LaligaClient


def _acta(semana: int, puntos: int, minutos: int, goles: int = 0) -> dict:
    return {
        "weekNumber": semana,
        "totalPoints": puntos,
        "stats": {
            "mins_played": [minutos, 2],
            "goals": [goles, 6 * goles],
            "marca_points": [-1, puntos - 2 - 6 * goles],
        },
    }


def _plantilla(*jugadores: tuple[int, str, list[dict]]) -> dict:
    return {
        "teamMoney": 0,
        "players": [
            {
                "id": f"slot-{pid}",
                "playerMaster": {
                    "id": pid,
                    "nickname": nombre,
                    "positionId": 3,
                    "team": {"name": "Real Betis"},
                    "lastStats": actas,
                },
            }
            for pid, nombre, actas in jugadores
        ],
    }


class AlmacenDeActasTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directorio = tempfile.TemporaryDirectory()
        self.addCleanup(self._directorio.cleanup)
        patcher = patch.dict(os.environ, {"FANTASY_CACHE_DIR": self._directorio.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        player_history._CACHE_ACTAS["firma"] = None
        self.addCleanup(lambda: player_history._CACHE_ACTAS.update({"firma": None, "jugadores": {}}))

    def test_registrar_guarda_puntos_minutos_y_desglose(self) -> None:
        cambiados = player_history.registrar_actas([_plantilla((3090, "Isco", [_acta(11, 15, 90, goles=1)]))])
        self.assertEqual(cambiados, 1)
        isco = player_history.actas_en_cache()["3090"]
        self.assertEqual(isco["weeks"][11], (15.0, 90.0))
        self.assertEqual(isco["desglose"][11]["puntos"]["goal"], 6.0)
        self.assertEqual(isco["desglose"][11]["puntos"]["min"], 2.0)

    def test_quien_sale_de_las_plantillas_conserva_sus_actas(self) -> None:
        player_history.registrar_actas([_plantilla((3090, "Isco", [_acta(10, 7, 80)]))])
        # Nueva lectura de la liga: Isco ya no aparece en ninguna plantilla.
        player_history.registrar_actas([_plantilla((1, "Otro", [_acta(10, 3, 60)]))])
        actas = player_history.actas_en_cache()
        self.assertIn("3090", actas)
        self.assertIn("1", actas)

    def test_las_jornadas_nuevas_se_suman_y_la_lectura_reciente_manda(self) -> None:
        player_history.registrar_actas([_plantilla((3090, "Isco", [_acta(10, 7, 80)]))])
        player_history.registrar_actas([_plantilla((3090, "Isco", [_acta(10, 8, 80), _acta(11, 15, 90)]))])
        isco = player_history.actas_en_cache()["3090"]
        self.assertEqual(sorted(isco["weeks"]), [10, 11])
        self.assertEqual(isco["weeks"][10][0], 8.0)

    def test_repetir_la_misma_lectura_no_reescribe(self) -> None:
        payload = _plantilla((3090, "Isco", [_acta(11, 15, 90)]))
        self.assertEqual(player_history.registrar_actas([payload]), 1)
        self.assertEqual(player_history.registrar_actas([payload]), 0)

    def test_un_cuerpo_roto_no_tumba_nada(self) -> None:
        self.assertEqual(player_history.registrar_actas([None, 3, "x", {"players": "mal"}]), 0)
        self.assertEqual(player_history.actas_en_cache(), {})

    def test_una_lectura_de_plantillas_alimenta_el_almacen(self) -> None:
        plantilla = _plantilla((3090, "Isco", [_acta(11, 15, 90)]), (3260, "Mujaid", [_acta(11, 6, 90)]))

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/standing" in url:
                return httpx.Response(
                    200,
                    json=[{"position": 1, "points": 40, "team": {"id": "44", "name": "Yo", "manager": {"managerName": "Pablo"}}}],
                )
            if "/teams/44" in url:
                return httpx.Response(200, json=plantilla)
            return httpx.Response(200, json=[{"id": "7", "name": "Mi liga", "team": {"id": "44"}}])

        class _Tokens:
            def authorization_value(self) -> str:
                return "Bearer test"

            def force_refresh(self) -> str:
                return "Bearer test"

        with tempfile.TemporaryDirectory() as raiz:
            cache = ResponseCache(Path(raiz))
            http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
            try:
                cliente = LaligaClient(tokens=_Tokens(), cache=cache, http=http, sleeper=lambda _s: None)
                documento = cliente.squads_document("7", fresh=True)
            finally:
                http.close()
                cache.close()
        self.assertTrue(documento["ok"])
        actas = player_history.actas_en_cache()
        self.assertEqual(sorted(actas), ["3090", "3260"])


if __name__ == "__main__":
    unittest.main()

"""Post-mortem del lunes: fuga de alineación y contrafactual de no operar."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from toolbox.engine.auditoria_jornada import (
    caja_sin_fichajes,
    construir_post_mortem,
    fuga_alineacion,
    guardar_snapshot,
    lunes_de_referencia,
)


def _jugador(pid: str, position: str, puntos: float, valor: int = 1_000_000) -> dict:
    return {
        "player_id": pid,
        "nickname": pid,
        "position": position,
        "puntos": puntos,
        "valor": valor,
        "en_xi": False,
    }


def _once_442() -> list[dict]:
    """4-4-2 con un medio de 2 puntos y otro de 10 en el banquillo."""
    filas = [_jugador("por", "POR", 5)]
    filas.extend(_jugador(f"def{index}", "DEF", 4) for index in range(4))
    filas.append(_jugador("mc_flojo", "MC", 2))
    filas.extend(_jugador(f"mc{index}", "MC", 8) for index in range(3))
    filas.append(_jugador("mc_banquillo", "MC", 10, 2_000_000))
    filas.extend(_jugador(f"del{index}", "DEL", 6) for index in range(2))
    for fila in filas:
        fila["en_xi"] = fila["player_id"] != "mc_banquillo"
    return filas


def _player(pid: str, position: str, puntos: float, valor: int) -> dict:
    return {
        "player_id": pid,
        "nickname": pid,
        "position": position,
        "market_value": valor,
        "week_points_by_round": {"12": puntos},
    }


class FugaTests(unittest.TestCase):
    def test_benching_the_hot_midfielder_is_the_leak(self) -> None:
        informe = fuga_alineacion(_once_442())
        self.assertTrue(informe["disponible"])
        self.assertEqual(informe["puntos_once"], 59.0)
        self.assertEqual(informe["puntos_maximos"], 67.0)
        self.assertEqual(informe["fuga"], 8.0)
        self.assertEqual([row["player_id"] for row in informe["dejados_fuera"]], ["mc_banquillo"])
        self.assertEqual([row["player_id"] for row in informe["sobraban"]], ["mc_flojo"])

    def test_missing_points_or_a_short_xi_stay_unavailable(self) -> None:
        corto = _once_442()[:-1]
        self.assertEqual(fuga_alineacion(corto)["motivo"], "sin_once")
        sin_puntos = _once_442()
        sin_puntos[0]["puntos"] = None
        self.assertEqual(fuga_alineacion(sin_puntos)["motivo"], "puntos_pendientes")


class TradingTests(unittest.TestCase):
    def test_cash_undoes_buys_and_sells_after_the_snapshot(self) -> None:
        desde = datetime(2026, 10, 26, 8, tzinfo=timezone.utc)
        eventos = [
            {"kind": "buy", "amount_eur": 3_000_000, "at": "2026-10-20T08:00:00+00:00"},
            {"kind": "buy", "amount_eur": 3_000_000, "at": "2026-10-28T08:00:00+00:00"},
            {"kind": "sell", "amount_eur": 1_000_000, "at": "2026-10-29T08:00:00+00:00"},
            {"kind": "premium", "amount_eur": 500_000, "at": "2026-10-29T09:00:00+00:00"},
        ]
        caja, resumen = caja_sin_fichajes(7_000_000, eventos, desde)
        self.assertEqual(caja, 9_000_000)
        self.assertEqual(resumen["operaciones"], 2)
        self.assertEqual(resumen["compras_eur"], 3_000_000)
        self.assertEqual(resumen["ventas_eur"], 1_000_000)

    def test_only_a_previous_monday_is_the_baseline(self) -> None:
        hoy = datetime(2026, 11, 3, tzinfo=timezone.utc).date()
        fotos = [
            {"day": "2026-10-28", "league_id": "L1"},
            {"day": "2026-10-26", "league_id": "L1"},
            {"day": "2026-11-02", "league_id": "L1"},
            {"day": "2026-11-03", "league_id": "L1"},
            {"day": "2026-10-19", "league_id": "otra"},
        ]
        elegida = lunes_de_referencia(fotos, hoy, "L1")
        self.assertIsNotNone(elegida)
        assert elegida is not None
        self.assertEqual(elegida["day"], "2026-11-02")

    def test_post_mortem_uses_last_monday_and_keeps_the_first_photo(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "auditoria_lunes.json"
            lunes = {
                "day": "2026-10-26",
                "league_id": "L1",
                "guardado_en": "2026-10-26T08:00:00+00:00",
                "jugadores": [
                    {"player_id": pid, "nombre": pid, "position": position, "valor": 1_000_000, "en_xi": True}
                    for pid, position in (
                        ("por", "POR"),
                        ("def0", "DEF"),
                        ("def1", "DEF"),
                        ("def2", "DEF"),
                        ("def3", "DEF"),
                        ("mc0", "MC"),
                        ("mc1", "MC"),
                        ("mc2", "MC"),
                        ("mc3", "MC"),
                        ("del0", "DEL"),
                        ("del_vendido", "DEL"),
                    )
                ],
            }
            guardar_snapshot(lunes, path)
            repetida = dict(lunes)
            repetida["guardado_en"] = "2026-10-26T22:00:00+00:00"
            self.assertEqual(guardar_snapshot(repetida, path)["guardado_en"], "2026-10-26T08:00:00+00:00")

            propios = [
                _player("por", "POR", 5, 1_000_000),
                *[_player(f"def{index}", "DEF", 4, 1_000_000) for index in range(4)],
                *[_player(f"mc{index}", "MC", 6, 1_000_000) for index in range(4)],
                _player("del0", "DEL", 6, 1_000_000),
                _player("del_nuevo", "DEL", 9, 4_000_000),
            ]
            vendido = _player("del_vendido", "DEL", 1, 1_200_000)
            xi = [row["player_id"] for row in propios]
            board = {
                "league_id": "L1",
                "squads": {
                    "league_id": "L1",
                    "squads": [
                        {
                            "team_id": "yo",
                            "is_self": True,
                            "cash": 7_000_000,
                            "points": 400,
                            "players": propios,
                        },
                        {"team_id": "rival", "is_self": False, "players": [vendido]},
                    ],
                },
                "optimize": {"saved_lineup": {"xi": [{"player_id": pid} for pid in xi]}},
                "needs": {
                    "ledgers": [
                        {
                            "team_id": "yo",
                            "events": [
                                {
                                    "kind": "buy",
                                    "amount_eur": 3_000_000,
                                    "player_id": "del_nuevo",
                                    "at": "2026-10-28T08:00:00+00:00",
                                },
                                {
                                    "kind": "sell",
                                    "amount_eur": 1_000_000,
                                    "player_id": "del_vendido",
                                    "at": "2026-10-29T08:00:00+00:00",
                                },
                            ],
                        }
                    ]
                },
            }
            ahora = datetime(2026, 11, 3, 10, tzinfo=timezone.utc)
            informe = construir_post_mortem(board, now=ahora, path=path)
            self.assertFalse(informe["es_lunes"])
            self.assertEqual(informe["jornada"], "12")
            self.assertEqual(informe["once_fuente"], "guardado")
            self.assertEqual(informe["fuga"]["fuga"], 0.0)
            trading = informe["trading"]
            self.assertTrue(trading["disponible"])
            self.assertEqual(trading["snapshot_day"], "2026-10-26")
            self.assertEqual(trading["hoy"]["valor"], 14_000_000)
            self.assertEqual(trading["sin_operar"]["valor"], 11_200_000)
            self.assertEqual(trading["delta_valor"], 2_800_000)
            self.assertEqual(trading["sin_operar"]["caja"], 9_000_000)
            self.assertEqual(trading["delta_caja"], -2_000_000)
            self.assertEqual(trading["hoy"]["puntos"], 60.0)
            self.assertEqual(trading["sin_operar"]["puntos"], 52.0)
            self.assertEqual(trading["delta_puntos"], 8.0)
            self.assertTrue(informe["snapshot_guardado"]["nuevo"])

            otra = construir_post_mortem(board, now=ahora, path=path)
            self.assertFalse(otra["snapshot_guardado"]["nuevo"])

    def test_without_a_monday_photo_the_trading_metric_waits(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "auditoria_lunes.json"
            board = {
                "squads": {
                    "league_id": "L1",
                    "squads": [
                        {
                            "team_id": "yo",
                            "is_self": True,
                            "cash": 1_000_000,
                            "players": [_player("por", "POR", 1, 1_000_000)],
                        }
                    ],
                }
            }
            informe = construir_post_mortem(
                board,
                now=datetime(2026, 11, 3, 10, tzinfo=timezone.utc),
                path=path,
            )
            self.assertEqual(informe["trading"]["motivo"], "sin_snapshot")
            self.assertTrue(informe["snapshot_guardado"]["nuevo"])
            self.assertTrue(path.is_file())

    def test_latest_series_point_is_used_when_the_round_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "auditoria_lunes.json"
            players = []
            for fila in _once_442():
                players.append(
                    {
                        "player_id": fila["player_id"],
                        "nickname": fila["player_id"],
                        "position": fila["position"],
                        "market_value": 1_000_000,
                        "week_points": [0.0, fila["puntos"]],
                    }
                )
            xi = [fila["player_id"] for fila in _once_442() if fila["en_xi"]]
            board = {
                "squads": {
                    "league_id": "L1",
                    "squads": [{"team_id": "yo", "is_self": True, "cash": 1, "players": players}],
                },
                "optimize": {"saved_lineup": {"xi": [{"player_id": pid} for pid in xi]}},
            }
            informe = construir_post_mortem(
                board,
                now=datetime(2026, 11, 3, 10, tzinfo=timezone.utc),
                path=path,
            )
            self.assertEqual(informe["jornada"], "ultima")
            self.assertEqual(informe["fuga"]["fuga"], 8.0)

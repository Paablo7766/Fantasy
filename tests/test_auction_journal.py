"""Diario de subastas: tablero del día y cierre con la actividad. Sin red."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from toolbox.auction_journal import (
    BlobJournal,
    board_row,
    buys_from_ledgers,
    capture_market_day,
    merge_own_bids,
    resolve_auctions,
)

NOW = datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc)
CLOSE = "2026-11-11T14:08:00+01:00"


def _listing(**extra: object) -> dict:
    row = {
        "market_id": "m1",
        "player_id": "7",
        "nickname": "Suyo",
        "position": "DEL",
        "market_value": 5_000_000,
        "sale_price": 5_000_000,
        "listing_expires_at": CLOSE,
        "own_bid": None,
        "bid_count": 2,
        "direct_offer": False,
    }
    row.update(extra)
    return row


class _Memoria:
    def __init__(self) -> None:
        self.board: list[dict] = []
        self.results: list[dict] = []

    def load_board(self, league_id: str, *, since_day: str) -> list[dict]:
        return [row for row in self.board if row["league_id"] == league_id and row["day"] >= since_day]

    def load_result_keys(self, league_id: str, *, since_day: str) -> set[tuple[str, str, str]]:
        return {
            (row["league_id"], row["day"], row["market_id"])
            for row in self.results
            if row["league_id"] == league_id and row["day"] >= since_day
        }

    def upsert_board(self, rows: list[dict]) -> None:
        keys = {(row["league_id"], row["day"], row["market_id"]) for row in rows}
        self.board = [row for row in self.board if (row["league_id"], row["day"], row["market_id"]) not in keys]
        self.board.extend(rows)

    def upsert_results(self, rows: list[dict]) -> None:
        keys = {(row["league_id"], row["day"], row["market_id"]) for row in rows}
        self.results = [row for row in self.results if (row["league_id"], row["day"], row["market_id"]) not in keys]
        self.results.extend(rows)


class DiarioTest(unittest.TestCase):
    def test_el_dia_es_el_del_cierre_en_madrid(self) -> None:
        row = board_row(_listing(), league_id="L", now=NOW)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["day"], "2026-11-11")
        self.assertEqual(row["player_name"], "Suyo")
        self.assertTrue(row["league_auction"])

    def test_una_venta_de_rival_no_es_subasta_de_laliga(self) -> None:
        row = board_row(_listing(seller_team_id="rival"), league_id="L", now=NOW)
        assert row is not None
        self.assertFalse(row["league_auction"])

    def test_la_puja_propia_no_se_borra_si_el_refresco_ya_no_la_trae(self) -> None:
        guardada = board_row(_listing(own_bid=4_200_000), league_id="L", now=NOW)
        nueva = board_row(_listing(own_bid=None), league_id="L", now=NOW)
        assert guardada is not None and nueva is not None
        merged = merge_own_bids([nueva], [guardada])
        self.assertEqual(merged[0]["own_bid_eur"], 4_200_000)

    def test_si_gano_yo_la_puja_queda_ganada(self) -> None:
        row = board_row(_listing(own_bid=5_100_000), league_id="L", now=NOW)
        assert row is not None
        buys = [
            {
                "team_id": "yo",
                "player_id": "7",
                "amount_eur": 5_100_000,
                "at": CLOSE,
                "day": "2026-11-11",
            }
        ]
        results = resolve_auctions([row], buys, own_team_id="yo", now=NOW, feed_latest=NOW)
        self.assertEqual(results[0]["status"], "vendida")
        self.assertEqual(results[0]["own_result"], "ganada")
        self.assertEqual(results[0]["amount_eur"], 5_100_000)

    def test_si_la_gana_un_rival_la_puja_queda_perdida(self) -> None:
        row = board_row(_listing(own_bid=4_000_000), league_id="L", now=NOW)
        assert row is not None
        buys = [
            {
                "team_id": "rival",
                "player_id": "7",
                "amount_eur": 6_000_000,
                "at": CLOSE,
                "day": "2026-11-11",
            }
        ]
        results = resolve_auctions([row], buys, own_team_id="yo", now=NOW, feed_latest=NOW)
        self.assertEqual(results[0]["winner_team_id"], "rival")
        self.assertEqual(results[0]["own_result"], "perdida")

    def test_sin_compra_y_actividad_al_dia_queda_sin_comprador(self) -> None:
        row = board_row(_listing(), league_id="L", now=NOW)
        assert row is not None
        results = resolve_auctions([row], [], own_team_id="yo", now=NOW, feed_latest=NOW)
        self.assertEqual(results[0]["status"], "sin_comprador")
        self.assertEqual(results[0]["own_result"], "sin_puja")
        self.assertIsNone(results[0]["amount_eur"])

    def test_sin_actividad_posterior_no_se_cierra_en_vacio(self) -> None:
        row = board_row(_listing(), league_id="L", now=NOW)
        assert row is not None
        antes = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(resolve_auctions([row], [], own_team_id="yo", now=NOW, feed_latest=antes), [])

    def test_una_venta_entre_managers_no_se_cierra_como_subasta(self) -> None:
        row = board_row(_listing(seller_team_id="otro"), league_id="L", now=NOW)
        assert row is not None
        self.assertEqual(resolve_auctions([row], [], own_team_id="yo", now=NOW, feed_latest=NOW), [])

    def test_el_cierre_aun_no_llegado_no_se_resuelve(self) -> None:
        temprano = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
        row = board_row(_listing(), league_id="L", now=temprano)
        assert row is not None
        self.assertEqual(resolve_auctions([row], [], own_team_id="yo", now=temprano, feed_latest=temprano), [])

    def test_captura_guarda_tablero_y_resultado(self) -> None:
        memoria = _Memoria()
        ledgers = [
            {
                "team_id": "rival",
                "events": [
                    {
                        "kind": "buy",
                        "player_id": "7",
                        "amount_eur": 6_000_000,
                        "at": CLOSE,
                    }
                ],
            }
        ]
        squads = {"squads": [{"team_id": "yo", "is_self": True}]}
        market = {"league_id": "L", "listings": [_listing(own_bid=4_000_000)]}
        summary = capture_market_day(market, squads, ledgers, now=NOW, journal=memoria)
        self.assertEqual(summary["board"], 1)
        self.assertEqual(summary["results"], 1)
        self.assertEqual(memoria.results[0]["own_result"], "perdida")
        self.assertEqual(buys_from_ledgers(ledgers)[0]["day"], "2026-11-11")

    def test_el_sobre_conserva_el_dia_anterior(self) -> None:
        estado = {"board": [], "results": []}

        def load() -> dict:
            return estado

        def save(document: dict) -> None:
            estado.clear()
            estado.update(document)

        journal = BlobJournal(load, save)
        market = {"league_id": "L", "listings": [_listing(own_bid=4_000_000)]}
        ledgers = [
            {
                "team_id": "rival",
                "events": [{"kind": "buy", "player_id": "7", "amount_eur": 6_000_000, "at": CLOSE}],
            }
        ]
        squads = {"squads": [{"team_id": "yo", "is_self": True}]}
        capture_market_day(market, squads, ledgers, now=NOW, journal=journal)
        otro = _listing(market_id="m2", player_id="8", nickname="Otro", listing_expires_at="2026-11-12T14:08:00+01:00")
        despues = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
        capture_market_day(
            {"league_id": "L", "listings": [otro]},
            squads,
            [],
            now=despues,
            journal=journal,
        )
        dias = sorted(row["day"] for row in estado["board"])
        self.assertEqual(dias, ["2026-11-11", "2026-11-12"])
        self.assertEqual(estado["results"][0]["own_result"], "perdida")


if __name__ == "__main__":
    unittest.main()

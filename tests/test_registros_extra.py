from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from toolbox.market_listing_log import TABLE, record_market_listings
from toolbox.normalize import normalize_listing
from toolbox.odds_archive import archive_match_odds, ensure_schema, extra_lines


def _linea(outcome_id: str, price: float, active: bool = True) -> dict:
    return {"players": {"0": {"active": active, "bookmakerOutcomeId": outcome_id, "price": price}}}


FIXTURE = {
    "bookmakerOdds": {
        "pinnacle": {
            "markets": {
                "101": {"bookmakerMarketId": "line/1/moneyline", "marketActive": True, "outcomes": {"101": _linea("home", 2.0)}},
                "10242": {
                    "bookmakerMarketId": "line/1/0/teamTotal",
                    "marketActive": True,
                    "outcomes": {
                        "1": _linea("away/0.5/under", 3.1),
                        "2": _linea("away/0.5/over", 1.4),
                        "3": _linea("home/0.5/under", 4.0, active=False),
                    },
                },
                "10300": {"bookmakerMarketId": "line/1/0/totals", "marketActive": True, "outcomes": {"1": _linea("2.5/over", 1.9)}},
                "10400": {"bookmakerMarketId": "1639/6602/1639", "marketActive": True, "outcomes": {"1": _linea("12345", 20.0)}},
                "10500": {"bookmakerMarketId": "line/1/0/spreads", "marketActive": False, "outcomes": {"1": _linea("home/-1/x", 2.0)}},
            }
        }
    }
}


class ExtraLinesTest(unittest.TestCase):
    def test_solo_guarda_lineas_activas_de_totales_y_hándicaps(self) -> None:
        lines = extra_lines(FIXTURE, bookmaker="pinnacle")
        self.assertEqual(
            sorted((x["kind"], x["outcome"]) for x in lines),
            [("teamTotal", "away/0.5/over"), ("teamTotal", "away/0.5/under"), ("totals", "2.5/over")],
        )

    def test_sin_casa_no_hay_lineas(self) -> None:
        self.assertEqual(extra_lines(FIXTURE, bookmaker="bet365"), [])

    def test_se_archivan_por_partido_y_dia(self) -> None:
        bundle = {
            "odds_1x2": (2.0, 3.0, 4.0),
            "source": "oddspapi",
            "kickoff": "2026-11-14T20:00:00Z",
            "extra_lines": extra_lines(FIXTURE, bookmaker="pinnacle"),
        }
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        archive_match_odds({"a|b": bundle}, day="2026-11-12", conn=conn)
        bundle["extra_lines"][0]["price"] = 9.0
        archive_match_odds({"a|b": bundle}, day="2026-11-12", conn=conn)
        rows = conn.execute("select count(*), max(price) from odds_lines_snapshots").fetchone()
        self.assertEqual(rows, (3, 9.0))


class AnuncioTest(unittest.TestCase):
    def test_normaliza_oferta_directa_y_valor_del_vendedor(self) -> None:
        item = {
            "id": "m1",
            "playerMaster": {"id": "7"},
            "salePrice": 5_000_000,
            "directOffer": False,
            "sellerTeam": {"id": 3, "teamValue": 206_696_570},
        }
        listing = normalize_listing(item)
        self.assertIs(listing["direct_offer"], False)
        self.assertEqual(listing["seller_team_value"], 206_696_570)

    def test_sin_esos_campos_quedan_vacios(self) -> None:
        listing = normalize_listing({"id": "m2", "playerMaster": {"id": "8"}})
        self.assertIsNone(listing["direct_offer"])
        self.assertIsNone(listing["seller_team_value"])


class RegistroAnunciosTest(unittest.TestCase):
    def test_guarda_una_fila_por_anuncio_y_dia(self) -> None:
        listings = [
            {"market_id": "m1", "player_id": "7", "sale_price": 5_000_000, "bid_count": 1, "offer_count": 0,
             "direct_offer": False, "seller_team_value": 100, "listing_expires_at": "2026-11-10T14:08:00+01:00"},
            {"market_id": "m2", "player_id": "8", "direct_offer": True},
            {"player_id": "sin id"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            self.assertEqual(record_market_listings(listings, league_id="L", day="2026-11-09", path=path), 2)
            listings[0]["bid_count"] = 3
            self.assertEqual(record_market_listings(listings, league_id="L", day="2026-11-09", path=path), 2)
            conn = sqlite3.connect(path)
            rows = conn.execute(
                f"select market_id, bid_count, direct_offer, seller_team_value from {TABLE} order by market_id"
            ).fetchall()
            conn.close()
        self.assertEqual(rows, [("m1", 3, 0, 100), ("m2", None, 1, None)])

    def test_sin_dia_o_sin_anuncios_no_escribe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "responses.sqlite"
            self.assertEqual(record_market_listings([{"market_id": "m"}], league_id=None, day=None, path=path), 0)
            self.assertEqual(record_market_listings([], league_id=None, day="2026-11-09", path=path), 0)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

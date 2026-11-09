"""Prima, estado oficial y reloj de cláusulas. Fixtures sintéticas, sin red."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.jornada_plan import clause_unlocks_within
from toolbox.market_intel import build_market_decisions
from toolbox.normalize import normalize_listing
from toolbox.player_status import resolve_status
from toolbox.premium_audit import build_premium_report


NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def _event(
    event_id: str,
    activity_type: int,
    *,
    amount: int = 1_100_000,
    player: str = "jugador-1",
    buyer: str = "comprador-1",
    seller: str | None = None,
    at: str = "2026-11-04T11:00:00Z",
) -> dict:
    row = {
        "id": event_id,
        "activityTypeId": activity_type,
        "amount": amount,
        "playerMasterId": player,
        "user1Id": buyer,
        "createdAt": at,
    }
    if seller is not None:
        row["user2Id"] = seller
    return row


class PremiumTests(unittest.TestCase):
    def test_dedupe_y_snapshot_del_mismo_dia(self) -> None:
        events = [
            _event("e1", 31, amount=1_100_000, at="2026-11-04T11:00:00Z"),
            _event("e1", 31, amount=9_999_999, at="2026-11-04T11:00:00Z"),
            _event("e2", 31, amount=1_200_000, player="jugador-2", at="2026-11-03T11:00:00Z"),
            _event("e3", 31, amount=1_300_000, player="jugador-1", at="2026-11-02T11:00:00Z"),
        ]
        snapshots = {
            ("jugador-1", "2026-11-04"): 1_000_000,
            ("jugador-1", "2026-11-01"): 500_000,
            ("jugador-2", "2026-11-01"): 1_000_000,
        }
        report = build_premium_report(events, snapshots)
        table = report["compras_laliga"]
        self.assertEqual(report["n_distintos"], 3)
        self.assertEqual(table["n"], 1)
        self.assertEqual(table["n_sin_referencia"], 2)
        self.assertAlmostEqual(table["mediana"], 0.1)
        self.assertEqual(table["por_comprador"][0]["buyer_id"], "comprador-1")
        self.assertTrue(table["muestra_pequena"])
        self.assertIn("no se extrapola", report["comparacion_laliga"]["nota"])
        self.assertIn("por rival", report["comparacion_laliga"]["nota"])

    def test_cuantiles_y_tipos_separados(self) -> None:
        events = []
        snapshots = {}
        premiums = (1.00, 1.10, 1.20, 1.30, 1.40)
        for index, ratio in enumerate(premiums):
            player = f"jugador-{index}"
            events.append(
                _event(
                    f"laliga-{index}",
                    31,
                    amount=int(1_000_000 * ratio),
                    player=player,
                    buyer=f"comprador-{index % 2}",
                )
            )
            events.append(
                _event(
                    f"clausula-{index}",
                    1,
                    amount=int(2_000_000 * ratio),
                    player=player,
                    buyer="comprador-clausula",
                    seller=f"vendedor-{index}",
                )
            )
            snapshots[(player, "2026-11-04")] = 1_000_000
        report = build_premium_report(events, snapshots)
        laliga = report["compras_laliga"]
        clause = report["clausulazos"]
        self.assertEqual(laliga["n"], 5)
        self.assertEqual(clause["n"], 5)
        self.assertAlmostEqual(laliga["mediana"], 0.2)
        self.assertAlmostEqual(laliga["p25"], 0.1)
        self.assertAlmostEqual(laliga["p75"], 0.3)
        self.assertAlmostEqual(laliga["minimo"], 0.0)
        self.assertAlmostEqual(laliga["maximo"], 0.4)
        self.assertEqual(clause["por_vendedor"][0]["n"], 1)
        self.assertNotEqual(laliga["mediana"], clause["por_comprador"][0]["mediana"] * 0)
        self.assertEqual(laliga["n_eventos"], 5)
        self.assertEqual(clause["n_eventos"], 5)
        self.assertAlmostEqual(clause["mediana"], 1.4)


class StatusConflictTests(unittest.TestCase):
    def test_gana_la_foto_mas_nueva(self) -> None:
        older = "2026-11-01T00:00:00+00:00"
        newer = "2026-11-04T00:00:00+00:00"
        self.assertEqual(
            resolve_status(
                [
                    {"status": "injured", "at": older, "source": "squad"},
                    {"status": "ok", "at": newer, "source": "market"},
                ]
            )["status"],
            "ok",
        )
        self.assertEqual(
            resolve_status(
                [
                    {"status": "ok", "at": older, "source": "market"},
                    {"status": "suspended", "at": newer, "source": "catalog"},
                ]
            )["status"],
            "suspended",
        )
        self.assertEqual(
            resolve_status(
                [
                    {"status": "injured", "source": "catalog"},
                    {"status": "ok", "at": older, "source": "squad"},
                ]
            )["status"],
            "ok",
        )

    def test_el_anuncio_conserva_el_estado_y_no_cambia_el_veredicto(self) -> None:
        listing = normalize_listing(
            {
                "id": "m1",
                "salePrice": 1_000_000,
                "playerMaster": {"id": "jugador-1", "playerStatus": "injured", "nickname": "Sintetico"},
            }
        )
        self.assertEqual(listing["player_status"], "injured")
        market_old = {
            "fetched_at": "2026-11-01T00:00:00+00:00",
            "listings": [{**listing, "player_id": "jugador-1"}],
        }
        squads_new = {
            "fetched_at": "2026-11-04T00:00:00+00:00",
            "squads": [{"players": [{"player_id": "jugador-1", "player_status": "ok"}]}],
        }
        clean = {key: value for key, value in listing.items() if key != "player_status"}
        clean["player_id"] = "jugador-1"
        base = build_market_decisions(
            {"listings": [clean]},
            {"players": [{"player_id": "jugador-1", "position": "MC", "matching_confidence": 0.95}]},
            {"cash_eur": 5_000_000, "team_id": "equipo-1"},
            {"gaps": []},
            now=NOW,
        )
        overruled = build_market_decisions(
            market_old,
            {"players": [{"player_id": "jugador-1", "position": "MC", "matching_confidence": 0.95}]},
            {"cash_eur": 5_000_000, "team_id": "equipo-1"},
            {"gaps": []},
            squads=squads_new,
            status_index={},
            now=NOW,
        )
        fresh_market = build_market_decisions(
            {
                "fetched_at": "2026-11-04T00:00:00+00:00",
                "listings": [{**listing, "player_id": "jugador-1"}],
            },
            {"players": [{"player_id": "jugador-1", "position": "MC", "matching_confidence": 0.95}]},
            {"cash_eur": 5_000_000, "team_id": "equipo-1"},
            {"gaps": []},
            squads={
                "fetched_at": "2026-11-01T00:00:00+00:00",
                "squads": [{"players": [{"player_id": "jugador-1", "player_status": "ok"}]}],
            },
            status_index={},
            now=NOW,
        )
        plain = base["decisions"][0]
        kept = overruled["decisions"][0]
        warned = fresh_market["decisions"][0]
        self.assertEqual(plain["decision"], warned["decision"])
        self.assertEqual(plain["score"], warned["score"])
        self.assertEqual(plain["action"], warned["action"])
        self.assertNotIn("lesionado", kept["action_reason"].lower())
        self.assertIn("Está lesionado.", warned["action_reason"])
        self.assertEqual(warned["official_status"], "injured")


class ClauseWindowTests(unittest.TestCase):
    def test_ventana_de_24_horas_sin_blindados(self) -> None:
        soon = (NOW + timedelta(hours=2)).isoformat()
        later = (NOW + timedelta(hours=30)).isoformat()
        past = (NOW - timedelta(hours=1)).isoformat()
        squads = {
            "fetched_at": "2026-11-04T00:00:00+00:00",
            "squads": [
                {
                    "manager_name": "Equipo sintetico",
                    "is_self": False,
                    "players": [
                        {
                            "player_id": "abre",
                            "nickname": "Abre",
                            "buyout_clause": 8_000_000,
                            "is_shielded": False,
                            "clause_lock": {"present": True, "expires_at": soon},
                        },
                        {
                            "player_id": "lejos",
                            "nickname": "Lejos",
                            "buyout_clause": 9_000_000,
                            "is_shielded": False,
                            "clause_lock": {"present": True, "expires_at": later},
                        },
                        {
                            "player_id": "pasado",
                            "nickname": "Pasado",
                            "buyout_clause": 7_000_000,
                            "is_shielded": False,
                            "clause_lock": {"present": True, "expires_at": past},
                        },
                        {
                            "player_id": "blindado",
                            "nickname": "Blindado",
                            "buyout_clause": 6_000_000,
                            "is_shielded": True,
                            "clause_lock": {"present": True, "expires_at": soon},
                        },
                    ],
                }
            ],
        }
        market = {
            "fetched_at": "2026-11-08T00:00:00+00:00",
            "listings": [
                {
                    "player_id": "abre",
                    "nickname": "Abre",
                    "seller_manager": "Equipo sintetico",
                    "clause_lock": {"present": True, "expires_at": soon},
                }
            ],
        }
        rows = clause_unlocks_within(squads, market, now=NOW)
        self.assertEqual([row["player_id"] for row in rows], ["abre"])
        self.assertEqual(rows[0]["buyout_clause"], 8_000_000)
        self.assertEqual(rows[0]["manager_name"], "Equipo sintetico")
        self.assertTrue(rows[0]["local_time"])

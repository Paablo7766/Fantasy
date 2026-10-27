"""Pruebas de la Fase 3. El solver y la caja no salen a la red."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

import cli
from toolbox.analyzer import (
    FORMATIONS,
    candidates_from_squad,
    exposed_clause_rule,
    is_at_risk,
    display_price_delta,
    official_price_delta,
    optimize_from_documents,
    sell_signal,
    solve_lineup,
    apply_doubt_titular_discount,
    starter_fallback,
    unavailable_reason,
)
from toolbox.normalize import (
    attach_image_urls,
    image_index_from_players,
    normalize_listing,
    normalize_player,
    official_week_points,
)
from toolbox.net import LaligaClient
from toolbox.bidding import (
    SNIPE_LEAD_SECONDS,
    build_agent_command,
    flip_from_documents,
    needs_from_documents,
    parse_events,
    read_governance,
    reconstruct_ledgers,
    schedule_snipe,
)
from toolbox.cache import ResponseCache
from toolbox.normalize import display_zone


def _player(
    player_id: str,
    position: str,
    *,
    xg: float = 0.0,
    xa: float = 0.0,
    p_titular: float = 1.0,
    fitness: str | None = None,
    relevo: int | None = None,
    suspended: bool = False,
) -> dict:
    payload = {
        "player_id": player_id,
        "name": player_id,
        "nickname": player_id,
        "position": position,
        "club": "Club",
        "p_titular": p_titular,
        "form": {
            "xg": xg,
            "xa": xa,
            "key_passes": 4,
            "duels_won": 3,
            "clearances": 2,
            "saves": 1,
            "average_rating": 9.9,
        },
    }
    if fitness:
        payload["fitness"] = fitness
    if relevo is not None:
        payload["relevo_bonus"] = relevo
    if suspended:
        payload["suspended"] = True
    return payload


def _squad(players: list[dict], *, cash: int | None = 1_000_000, rank: int = 1, team_id: str = "1", self_team: bool = True) -> dict:
    return {
        "team_id": team_id,
        "is_self": self_team,
        "manager_name": "Yo" if self_team else f"Rival {team_id}",
        "fantasy_team_name": team_id,
        "rank": rank,
        "cash": cash,
        "points": 0,
        "players": players,
        "error": None,
    }


def _document(squad_rows: list[dict]) -> dict:
    return {"ok": True, "league_id": "7", "squads": squad_rows}


def _rich_squad(*, cash: int = 1_000_000) -> list[dict]:
    players = [_player("por", "POR", xg=0.0)]
    for index, xg in enumerate((2.0, 1.5, 1.0, 0.5, 0.1), start=1):
        players.append(_player(f"def{index}", "DEF", xg=xg))
    for index, xg in enumerate((2.0, 1.0, 0.5, 0.2, 0.1), start=1):
        players.append(_player(f"mc{index}", "MC", xg=xg))
    for index, xg in enumerate((3.0, 2.0, 1.0), start=1):
        players.append(_player(f"del{index}", "DEL", xg=xg))
    players.append(_player("lesion", "DEL", xg=10.0, fitness="lesionado"))
    players.append(_player("sancion", "MC", xg=10.0, suspended=True))
    return players


class _Tokens:
    def authorization_value(self) -> str:
        return "Bearer test-token"

    def force_refresh(self) -> str:
        return "test-token"


class Phase3Test(unittest.TestCase):
    def test_solver_picks_standard_formation_and_drops_unavailable(self) -> None:
        solved = optimize_from_documents(_document([_squad(_rich_squad())]), None)
        self.assertTrue(solved["ok"])
        self.assertFalse(solved["matchday_void"])
        self.assertEqual(solved["formation"], "4-3-3")
        self.assertEqual(solved["counts"], FORMATIONS["4-3-3"])
        self.assertEqual(len(solved["xi"]), 11)
        self.assertEqual(solved["solver"]["status"], "Optimal")
        self.assertEqual(solved["penalties"]["empty_slot_lambda"], "inf")
        self.assertEqual(solved["penalties"]["negative_cash_lambda"], "inf")
        picked = {player["player_id"] for player in solved["xi"]}
        self.assertNotIn("lesion", picked)
        self.assertNotIn("sancion", picked)
        self.assertEqual(sum(1 for player in solved["xi"] if player["position"] == "DEL"), 3)
        porter = next(player for player in solved["xi"] if player["position"] == "POR")
        self.assertEqual(porter["objective"], 0.0)
        self.assertNotIn("average_rating", porter["components"])

    def test_only_three_defenders_forces_352(self) -> None:
        players = [_player("por", "POR")]
        players += [_player(f"def{i}", "DEF", xg=1) for i in range(1, 4)]
        players += [_player(f"mc{i}", "MC", xg=1) for i in range(1, 6)]
        players += [_player(f"del{i}", "DEL", xg=1) for i in range(1, 3)]
        solved = solve_lineup(candidates_from_squad(_squad(players), {}), cash=10)
        self.assertEqual(solved["formation"], "3-5-2")
        self.assertEqual(solved["counts"], FORMATIONS["3-5-2"])

    def test_negative_cash_zeros_the_matchday(self) -> None:
        solved = optimize_from_documents(_document([_squad(_rich_squad(), cash=-1)]), None)
        self.assertTrue(solved["ok"])
        self.assertTrue(solved["matchday_void"])
        self.assertIn("negative_cash", solved["void_reasons"])
        self.assertEqual(solved["xi"], [])
        self.assertEqual(solved["expected_points"], 0.0)
        self.assertEqual(solved["solver"]["status"], "NotSolved")

    def test_short_or_impossible_lineup_is_an_empty_slot(self) -> None:
        short = optimize_from_documents(_document([_squad(_rich_squad()[:10])]), None)
        self.assertIn("empty_slot", short["void_reasons"])
        self.assertEqual(short["expected_points"], 0.0)

        players = [_player("por", "POR")]
        players += [_player(f"def{i}", "DEF") for i in range(1, 3)]
        players += [_player(f"mc{i}", "MC") for i in range(1, 6)]
        players += [_player(f"del{i}", "DEL") for i in range(1, 5)]
        impossible = solve_lineup(candidates_from_squad(_squad(players), {}), cash=10)
        self.assertTrue(impossible["matchday_void"])
        self.assertIn("empty_slot", impossible["void_reasons"])
        self.assertEqual(impossible["expected_points"], 0.0)
        self.assertTrue(impossible["partial"])
        self.assertGreaterEqual(len(impossible["xi"]), 1)
        self.assertTrue(any(gap["position"] == "DEF" and gap["missing"] >= 1 for gap in impossible["gaps"]))

    def test_official_doubtful_beats_scraped_injury(self) -> None:
        player = _player("militao", "DEF", xg=1.0)
        player["player_status"] = "doubtful"
        player["fitness"] = "lesionado"
        trend = {"player_id": "militao", "matching_confidence": 0.99, "fitness": "lesionado", "p_titular": 0.4}
        roster = candidates_from_squad(_squad([player]), {"militao": trend})
        self.assertEqual(roster[0].excluded_reason, None)
        self.assertEqual(roster[0].player_status, "doubtful")

    def test_official_injured_is_excluded(self) -> None:
        player = _player("guridi", "MC")
        player["player_status"] = "injured"
        roster = candidates_from_squad(_squad([player]), {})
        self.assertEqual(roster[0].excluded_reason, "lesionado")

    def test_partial_xi_keeps_players_and_names_the_gap(self) -> None:
        players = [_player("por", "POR")]
        players += [_player(f"def{i}", "DEF", xg=1) for i in range(3)]
        players += [_player(f"mc{i}", "MC", xg=1) for i in range(4)]
        players += [_player(f"del{i}", "DEL", xg=2) for i in range(2)]
        listings = [
            {"player_id": "caro", "nickname": "Caro", "position": "DEL", "sale_price": 9_000_000},
            {"player_id": "barato", "nickname": "Barato", "position": "DEL", "sale_price": 1_000_000},
        ]
        solved = solve_lineup(
            candidates_from_squad(_squad(players), {}),
            cash=10,
            listings=listings,
            owned_ids={"por"},
        )
        self.assertTrue(solved["matchday_void"])
        self.assertEqual(solved["expected_points"], 0.0)
        self.assertEqual(len(solved["xi"]), 10)
        self.assertTrue(any(gap["position"] == "DEL" and gap["missing"] == 1 for gap in solved["gaps"]))
        options = solved["market_fills"][0]["options"]
        self.assertEqual(options[0]["nickname"], "Barato")
        self.assertEqual(options[0]["sale_price"], 1_000_000)
        self.assertNotIn("por", {item["player_id"] for item in options})

    def test_relevo_and_opta_are_not_invented(self) -> None:
        rewarded = _player("mc", "MC", xg=1.0, xa=1.0, p_titular=0.5, relevo=2)
        plain = _player("mc2", "MC", xg=1.0, xa=1.0, p_titular=0.5)
        roster = candidates_from_squad(_squad([rewarded, plain]), {})
        by_id = {candidate.player_id: candidate for candidate in roster}
        self.assertEqual(by_id["mc"].components, {"xg": 5.0, "xa": 3.0})
        self.assertEqual(by_id["mc"].relevo_bonus, 2)
        self.assertEqual(by_id["mc"].objective, 5.0)
        self.assertIsNone(by_id["mc2"].relevo_bonus)
        self.assertEqual(by_id["mc2"].objective, 4.0)

    def test_low_confidence_trend_does_not_exclude_or_score(self) -> None:
        squad = _squad([_player("a", "DEL", xg=0.0, p_titular=0.0)])
        squad["players"][0]["p_titular"] = None
        squad["players"][0]["form"] = None
        trends = {
            "players": [
                {
                    "player_id": "a",
                    "matching_confidence": 0.5,
                    "p_titular": 1,
                    "fitness": "lesionado",
                    "form": {"xg": 5},
                }
            ]
        }
        roster = candidates_from_squad(squad, {"a": trends["players"][0]})
        self.assertIsNone(roster[0].excluded_reason)
        self.assertEqual(roster[0].objective, 0.0)
        self.assertIsNone(roster[0].p_titular)

    def test_optimize_uses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            document = _document([_squad(_rich_squad())])
            first = optimize_from_documents(document, None, cache=cache, fresh=False)
            second = optimize_from_documents(document, None, cache=cache, fresh=False)
            cache.close()
        self.assertFalse(first["from_cache"])
        self.assertTrue(second["from_cache"])
        self.assertEqual(second["formation"], first["formation"])

    def test_ledger_rebuilds_cash_and_refuses_to_invent_it(self) -> None:
        events = parse_events(
            [
                {"type": "presupuesto", "teamId": 4, "money": 100, "createdAt": "2026-08-01T10:00:00Z"},
                {"type": "prima", "teamId": "4", "amount": 10, "createdAt": "2026-08-08T10:00:00Z"},
                {"operation": "compra", "teamId": "4", "price": 40, "playerId": "p1"},
                {"type": "venta", "teamId": "4", "money": 15, "playerId": "p2"},
                {"type": "cláusula", "teamId": "4", "money": 5},
                {"type": "presupuesto", "teamId": "4", "money": 999},
            ]
        )
        self.assertEqual(
            sorted(event["kind"] for event in events if event["kind"] != "initial"),
            ["buy", "clause", "premium", "sell"],
        )
        ledger = reconstruct_ledgers([_squad([], cash=80, team_id="4", self_team=False)], events)[0]
        self.assertEqual(ledger["initial_budget_eur"], 100)
        self.assertEqual(ledger["premiums_eur"], 10)
        self.assertEqual(ledger["purchases_eur"], 40)
        self.assertEqual(ledger["sales_eur"], 15)
        self.assertEqual(ledger["clauses_eur"], 5)
        self.assertEqual(ledger["reconstructed_cash_eur"], 80)
        self.assertTrue(ledger["balanced"])
        self.assertEqual(ledger["ignored_events"], 1)

        empty = reconstruct_ledgers([_squad([], cash=80, team_id="4", self_team=False)], [])[0]
        self.assertIsNone(empty["reconstructed_cash_eur"])
        self.assertEqual(empty["observed_cash_eur"], 80)
        self.assertIsNone(empty["balanced"])

    def test_snipe_hides_the_bid_until_seconds_before_close(self) -> None:
        expires = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)
        now = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)
        listing = {
            "market_id": "m",
            "player_id": "del1",
            "name": "Delantero",
            "position": "DEL",
            "sale_price": 20,
            "leading_bid": 30,
            "listing_expires_at": expires.isoformat(),
            "seller_team_id": "9",
        }
        snipe = schedule_snipe(listing, cash=40, lineup_void=False, own_team_id="1", now=now)
        fire = expires - timedelta(seconds=SNIPE_LEAD_SECONDS)
        zone_name, zone = display_zone()
        local = fire.astimezone(zone)
        self.assertEqual(snipe["bid_eur"], 31)
        self.assertEqual(snipe["status"], "hidden")
        self.assertTrue(snipe["interest_hidden"])
        self.assertTrue(snipe["eligible"])
        self.assertEqual(snipe["fire_local_clock"], local.strftime("%H:%M:%S"))
        self.assertEqual(snipe["fire_local_time"], local.strftime("%H:%M"))
        self.assertEqual(zone_name, "Europe/Madrid")
        self.assertEqual(snipe["cash_after_eur"], 9)

        broke = schedule_snipe(listing, cash=5, lineup_void=False, own_team_id="1", now=now)
        self.assertFalse(broke["eligible"])
        self.assertIn("negative_cash", broke["reasons"])
        self.assertEqual(broke["cash_after_eur"], -26)

        closed = schedule_snipe(
            listing,
            cash=40,
            lineup_void=False,
            own_team_id="1",
            now=expires + timedelta(seconds=1),
        )
        self.assertEqual(closed["status"], "window_passed")
        self.assertFalse(closed["interest_hidden"])

    def test_flip_keeps_only_affordable_speculation(self) -> None:
        now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        expires = "2026-10-14T18:00:00+00:00"
        market = {
            "league_id": "7",
            "listings": [
                {"market_id": "ok", "player_id": "sube", "position": "DEL", "sale_price": 10, "leading_bid": None, "listing_expires_at": expires, "seller_team_id": "9"},
                {"market_id": "caro", "player_id": "caro", "position": "DEL", "sale_price": 80, "listing_expires_at": expires, "seller_team_id": "9"},
                {"market_id": "ruido", "player_id": "ruido", "position": "MC", "sale_price": 5, "listing_expires_at": expires, "seller_team_id": "9"},
                {"market_id": "cerrado", "player_id": "cerrado", "position": "DEL", "sale_price": 5, "listing_expires_at": "2026-10-14T10:00:00+00:00", "seller_team_id": "9"},
            ],
        }
        trends = {
            "players": [
                {
                    "player_id": "sube",
                    "name": "Sube",
                    "position": "DEL",
                    "acceleration": 246_253,
                    "price_delta": 1_325_257,
                    "matching_confidence": 0.91,
                    "p_titular": 0.8,
                    "form": {"xg": 1},
                },
                {"player_id": "caro", "name": "Caro", "position": "DEL", "acceleration": 20, "matching_confidence": 0.95, "p_titular": 1, "form": {"xg": 1}},
                {"player_id": "ruido", "name": "Ruido", "position": "MC", "acceleration": 4, "matching_confidence": 0.4, "p_titular": 1},
                {"player_id": "cerrado", "name": "Cerrado", "position": "DEL", "acceleration": 6, "matching_confidence": 0.9, "p_titular": 1, "form": {"xg": 1}},
            ]
        }
        lineup = {"ok": True, "matchday_void": False}
        flipped = flip_from_documents(
            market,
            _document([_squad([], cash=40)]),
            trends,
            lineup=lineup,
            now=now,
        )
        self.assertTrue(flipped["ok"])
        self.assertEqual([item["player_id"] for item in flipped["signings"]], ["sube"])
        self.assertEqual(flipped["signings"][0]["cash_after_eur"], 30)
        self.assertEqual(flipped["signings"][0]["expected_points"], 4.0)
        self.assertEqual(flipped["signings"][0]["acceleration"], 246_253)
        self.assertEqual(flipped["signings"][0]["price_delta"], 1_325_257)
        self.assertTrue(flipped["bid_run"][0]["interest_hidden"])
        rejected = {item["player_id"]: item["reasons"] for item in flipped["rejected"]}
        self.assertIn("negative_cash", rejected["caro"])
        self.assertIn("matching_confidence", rejected["ruido"])
        self.assertIn("mercado_cerrado", rejected["cerrado"])

    def test_flip_price_delta_from_listing_when_trend_omits_day_move(self) -> None:
        market = {
            "ok": True,
            "listings": [
                {
                    "player_id": "sube",
                    "nickname": "Sube",
                    "position": "DEL",
                    "sale_price": 8_674_743,
                    "market_value": 10_000_000,
                    "seller_team_id": "9",
                    "listing_expires_at": "2099-01-01T20:00:00+00:00",
                }
            ],
        }
        trends = {
            "ok": True,
            "players": [
                {
                    "player_id": "sube",
                    "name": "Sube",
                    "nickname": "Sube",
                    "position": "DEL",
                    "acceleration": 246_253,
                    "price_delta": None,
                    "fantasy_price": 10_000_000,
                    "matching_confidence": 0.95,
                    "p_titular": 1,
                    "form": {"xg": 1, "xa": 0},
                    "flip_candidate": True,
                }
            ],
        }
        flipped = flip_from_documents(
            market,
            _document([_squad([], cash=20_000_000)]),
            trends,
            lineup={"ok": True, "matchday_void": False},
            now=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(flipped["ok"])
        self.assertEqual(flipped["signings"][0]["price_delta"], 1_325_257)

    def test_sabotage_schedules_clause_minute_only_for_a_thin_direct_rival(self) -> None:
        now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        lock = {
            "present": True,
            "is_locked": True,
            "local_date": "2026-10-18",
            "local_time": "18:34",
            "expires_at": "2026-10-18T16:34:00+00:00",
            "timezone": "Europe/Madrid",
        }
        keeper = {
            "player_id": "gk",
            "name": "Portero",
            "nickname": "Portero",
            "position": "POR",
            "buyout_clause": 500,
            "is_shielded": False,
            "clause_lock": lock,
        }
        shielded = {**keeper, "player_id": "blind", "is_shielded": True, "name": "Blindado"}
        missing = {
            **keeper,
            "player_id": "sinhora",
            "clause_lock": {"present": False, "is_locked": False, "local_date": None, "local_time": None},
        }
        own = _squad(_rich_squad(), cash=1_000, rank=1)
        direct = _squad([keeper], cash=0, rank=2, team_id="2", self_team=False)
        far = _squad([dict(keeper, player_id="lejos")], cash=0, rank=9, team_id="9", self_team=False)
        covered = _squad([keeper], cash=100, rank=3, team_id="3", self_team=False)
        blind = _squad([shielded], cash=0, rank=1, team_id="5", self_team=False)
        unknown = _squad([missing], cash=0, rank=2, team_id="6", self_team=False)
        market = {"listings": [{"player_id": "repuesto", "position": "POR", "sale_price": 10}]}
        activity = {
            "ok": True,
            "source_url": "https://fantasy-api.llt-services.com/news",
            "error": None,
            "events": parse_events([{"type": "presupuesto", "teamId": "2", "money": 20}, {"type": "compra", "teamId": "2", "money": 20}]),
        }
        report = needs_from_documents(
            market,
            _document([own, direct, far, covered, blind, unknown]),
            None,
            activity,
            now=now,
        )
        nested = {
            (alert["team_id"], alert["player_id"]): alert
            for rival in report["rivals"]
            for alert in rival["clause_alerts"]
        }
        scheduled = nested[("2", "gk")]
        self.assertEqual(scheduled["alert_local_date"], "2026-10-18")
        self.assertEqual(scheduled["alert_local_time"], "18:34")
        self.assertTrue(scheduled["scheduled"])
        self.assertTrue(scheduled["lacks_replacements"])
        self.assertTrue(scheduled["lacks_liquidity"])
        self.assertTrue(scheduled["we_can_pay"])
        self.assertEqual([(alert["team_id"], alert["player_id"]) for alert in report["clause_alerts"]], [("2", "gk")])
        self.assertNotIn(("9", "lejos"), nested)
        self.assertNotIn(("3", "gk"), nested)
        self.assertFalse(nested[("5", "blind")]["scheduled"])
        self.assertEqual(nested[("5", "blind")]["schedule_reason"], "blindado_o_sin_dato")
        self.assertFalse(nested[("6", "sinhora")]["scheduled"])
        self.assertIsNone(nested[("6", "sinhora")]["alert_local_time"])
        rival = next(item for item in report["rivals"] if item["team_id"] == "2")
        self.assertEqual(rival["ledger"]["reconstructed_cash_eur"], 0)
        self.assertTrue(rival["direct"])

    def test_governance_blocks_silent_spend_while_thresholds_are_open(self) -> None:
        text = Path("context/USER.md").read_text(encoding="utf-8")
        governance = read_governance(text, execute=True)
        self.assertFalse(governance["silent_money_enabled"])
        self.assertTrue(governance["clause_requires_telegram"])
        by_operation = {order["operation"]: order["status"] for order in governance["orders"]}
        self.assertEqual(by_operation["alineacion"], "not_sent")
        self.assertEqual(by_operation["puja"], "blocked")
        self.assertEqual(by_operation["clausula"], "blocked")

    def test_cli_commands_return_typed_json(self) -> None:
        players = _rich_squad()
        own = _squad(players, cash=100)
        market = {
            "ok": True,
            "league_id": "7",
            "listings": [
                {
                    "market_id": "m",
                    "player_id": "sube",
                    "name": "Sube",
                    "position": "DEL",
                    "sale_price": 10,
                    "leading_bid": None,
                    "listing_expires_at": "2026-12-01T18:00:00+00:00",
                    "seller_team_id": "9",
                }
            ],
        }
        squads = _document([own, _squad([
            {
                "player_id": "gk",
                "name": "Portero",
                "position": "POR",
                "buyout_clause": 20,
                "is_shielded": False,
                "clause_lock": {
                    "present": True,
                    "is_locked": True,
                    "local_date": "2026-10-18",
                    "local_time": "18:34",
                    "timezone": "Europe/Madrid",
                },
            }
        ], cash=0, rank=2, team_id="2", self_team=False)])
        trends = {
            "ok": True,
            "partial": False,
            "players": [
                {
                    "player_id": "sube",
                    "name": "Sube",
                    "position": "DEL",
                    "acceleration": 8,
                    "flip_candidate": True,
                    "matching_confidence": 0.9,
                    "p_titular": 0.7,
                    "form": {"xg": 0.5},
                    "sanction": {"suspended": False},
                }
            ],
        }

        class FakeClient:
            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def market_document(self, _league: str | None, *, fresh: bool) -> dict:
                self.fresh = fresh
                return market

            def squads_document(self, _league: str | None, *, fresh: bool) -> dict:
                return squads

            def activity_payload(self, _league_id: str, *, fresh: bool) -> dict:
                return {"ok": False, "source_url": None, "payload": None, "error": "endpoint_not_found", "attempts": []}

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"FANTASY_CACHE_DIR": directory}), patch(
            "cli.LaligaClient", return_value=FakeClient()
        ), patch("toolbox.scrapers.build_trends", return_value=trends):
            optimize_out = StringIO()
            with redirect_stdout(optimize_out), redirect_stderr(StringIO()):
                optimize_code = cli.main(["optimize", "--json"])
            flip_out = StringIO()
            with redirect_stdout(flip_out), redirect_stderr(StringIO()):
                flip_code = cli.main(["flip", "--json"])
            needs_out = StringIO()
            with redirect_stdout(needs_out), redirect_stderr(StringIO()):
                needs_code = cli.main(["needs", "--json"])
            agent_out = StringIO()
            with redirect_stdout(agent_out), redirect_stderr(StringIO()):
                agent_code = cli.main(["agent", "--execute", "--json"])

        optimize = json.loads(optimize_out.getvalue())
        flipped = json.loads(flip_out.getvalue())
        needs = json.loads(needs_out.getvalue())
        agent = json.loads(agent_out.getvalue())
        self.assertEqual(optimize_code, 0)
        self.assertEqual(optimize["formation"], "4-3-3")
        self.assertEqual(len(optimize["xi"]), 11)
        self.assertEqual(flip_code, 0)
        self.assertEqual(flipped["signings"][0]["player_id"], "sube")
        self.assertEqual(flipped["bid_run"][0]["lead_seconds"], SNIPE_LEAD_SECONDS)
        self.assertEqual(needs_code, 0)
        self.assertEqual(needs["clause_alerts"][0]["alert_local_time"], "18:34")
        self.assertIsNone(needs["ledgers"][0]["reconstructed_cash_eur"])
        self.assertEqual(agent_code, 0)
        self.assertTrue(agent["execute_requested"])
        self.assertEqual(agent["optimize"]["formation"], "4-3-3")
        self.assertIn("ejecutado: no", agent["memory_entry"])
        self.assertTrue(any(order["status"] == "blocked" for order in agent["governance"]["orders"]))
        self.assertIsInstance(agent["flip"]["signings"], list)
        self.assertIsInstance(agent["needs"]["rivals"], list)

    def test_agent_command_reads_injected_governance(self) -> None:
        class FakeClient:
            def market_document(self, _league: str | None, *, fresh: bool) -> dict:
                return {"league_id": "7", "listings": []}

            def squads_document(self, _league: str | None, *, fresh: bool) -> dict:
                return _document([_squad(_rich_squad(), cash=10)])

            def activity_payload(self, _league_id: str, *, fresh: bool) -> dict:
                return {"ok": True, "source_url": "https://fantasy-api.llt-services.com/api/v3/leagues/7/news", "payload": [], "error": None, "attempts": []}

        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            document = build_agent_command(
                FakeClient(),
                league="7",
                fresh=True,
                execute=False,
                trends_document={"ok": True, "partial": False, "players": []},
                cache=cache,
                governance_text="- reserva_caja_eur: COMPLETAR\n- puja_silenciosa_max_eur: COMPLETAR\n- puja_silenciosa_max_pct_caja: COMPLETAR\n- suelo_venta_eur: COMPLETAR\n- clausula_max_sin_preguntar_eur: 0\n",
            )
            cache.close()
        self.assertTrue(document["ok"])
        self.assertEqual(document["governance"]["orders"], [])
        self.assertIn("optimize", document)
        self.assertIn("flip", document)
        self.assertIn("needs", document)

    def test_activity_skips_404_and_uses_cache(self) -> None:
        calls = {"miss": 0, "hit": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/league/7/news"):
                calls["hit"] += 1
                return httpx.Response(
                    200,
                    json=[{"type": "prima", "teamId": "2", "money": 3, "createdAt": "2026-09-01T12:00:00Z"}],
                )
            calls["miss"] += 1
            return httpx.Response(404, json={"missing": True})

        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
            client = LaligaClient(tokens=_Tokens(), cache=cache, http=http, sleeper=lambda _seconds: None)
            first = client.activity_payload("7", fresh=False)
            second = client.activity_payload("7", fresh=False)
            client.close()
            cache.close()
        self.assertTrue(first["ok"])
        self.assertEqual(parse_events(first["payload"])[0]["kind"], "premium")
        self.assertEqual(parse_events(first["payload"])[0]["amount_eur"], 3)
        self.assertGreaterEqual(calls["miss"], 1)
        self.assertEqual(calls["hit"], 1)
        self.assertEqual(second["payload"], first["payload"])


class FinancialSignalTests(unittest.TestCase):
    def test_stale_api_injury_overridden_by_lineup(self) -> None:
        player = {"player_id": "1147", "player_status": "injured", "position": "DEF"}
        trend = {
            "matching_confidence": 0.91,
            "p_titular": 0.88,
            "p_titular_source": "scraper",
            "lineup_status": "titular",
            "fitness": "lesionado",
        }
        self.assertIsNone(unavailable_reason(player, trend))

    def test_week_points_replace_a_missing_scraper_probability(self) -> None:
        player = _player("a", "DEL", p_titular=0.0)
        player["p_titular"] = None
        player["week_points"] = [0, 4, 0, 2, 8]
        roster = candidates_from_squad(_squad([player]), {})
        self.assertEqual(roster[0].p_titular, 0.55)
        self.assertEqual(roster[0].p_titular_source, "week_points")

        scraped = {"player_id": "a", "matching_confidence": 0.91, "p_titular": 0.25}
        kept = candidates_from_squad(_squad([player]), {"a": scraped})
        self.assertEqual(kept[0].p_titular, 0.25)
        self.assertEqual(kept[0].p_titular_source, "scraper")

    def test_trends_payload_falls_back_to_official_week_points(self) -> None:
        from toolbox.matching import CanonicalPlayer
        from toolbox.scrapers import _player_payload

        player = CanonicalPlayer(
            player_id="a",
            name="Alpha",
            nickname="Alpha",
            club="Celta",
            position="DEL",
            fantasy_price=1_000_000,
            week_points=(0.0, 4.0, 0.0, 2.0, 8.0),
        )
        row = _player_payload(
            player,
            intel=None,
            form={},
            transfermarkt_value=None,
            confidence=None,
            matches={},
        )
        self.assertEqual(row["p_titular"], 0.55)
        self.assertEqual(row["p_titular_source"], "week_points")

    def test_official_last_stats_count_as_week_points(self) -> None:
        raw = {
            "playerMaster": {
                "id": 8,
                "nickname": "Sarr",
                "lastStats": [
                    {"weekNumber": 4, "totalPoints": 3},
                    {"weekNumber": 5, "totalPoints": 0},
                    {"weekNumber": 6, "totalPoints": 0},
                    {"weekNumber": 7, "totalPoints": 0},
                    {"weekNumber": 8, "totalPoints": 4},
                    {"weekNumber": 3, "totalPoints": 9},
                ],
            }
        }
        self.assertEqual(official_week_points(raw), [3.0, 0.0, 0.0, 0.0, 4.0])
        self.assertEqual(starter_fallback(raw), 0.4)
        self.assertEqual(starter_fallback({**raw, "lastStats": [{"weekNumber": i, "totalPoints": 3} for i in range(1, 6)]}), 0.55)
        self.assertEqual(
            apply_doubt_titular_discount(0.8, {"player_status": "doubtful"}, None),
            0.36,
        )
        normalized = normalize_player(raw)
        self.assertEqual(normalized["week_points"], [3.0, 0.0, 0.0, 0.0, 4.0])

    def test_player_image_url_from_master_and_catalog(self) -> None:
        photo = "https://assets-fantasy.llt-services.com/players/t174/p68/256x256/p68_t174_1_001_000.png"
        normalized = normalize_player(
            {
                "playerMaster": {
                    "id": 68,
                    "nickname": "Unai Simón",
                    "positionId": 1,
                    "image": photo,
                }
            }
        )
        self.assertEqual(normalized["image_url"], photo)
        listing = normalize_listing(
            {
                "salePrice": 1_000_000,
                "playerMaster": {"id": 140, "nickname": "Iván Villar", "positionId": 1},
            }
        )
        self.assertIsNone(listing["image_url"])
        index = image_index_from_players(
            [
                {"id": "68", "image": photo},
                {"id": "140", "image": "https://assets-fantasy.llt-services.com/players/t176/p140/256x256/p140_t176_1_001_000.png"},
            ]
        )
        self.assertEqual(index["68"], photo)
        attach_image_urls([listing], index)
        self.assertEqual(
            listing["image_url"],
            "https://assets-fantasy.llt-services.com/players/t176/p140/256x256/p140_t176_1_001_000.png",
        )
        attach_image_urls([normalized], index)
        self.assertEqual(normalized["image_url"], photo)

    def test_ensure_board_images_fills_cached_optimize(self) -> None:
        from server import ensure_board_images

        photo = "https://assets-fantasy.llt-services.com/players/t174/p68/256x256/p68_t174_1_001_000.png"
        board = {
            "optimize": {"xi": [{"player_id": "68", "nickname": "Unai Simón"}]},
            "market": {"listings": [{"player_id": "68", "nickname": "Unai Simón"}]},
            "squads": {"squads": [{"players": [{"player_id": "68"}]}]},
            "trends": {"rising": [{"player_id": "68"}]},
            "flip": {"signings": [{"player_id": "68"}]},
        }
        ensure_board_images(board, index={"68": photo})
        self.assertEqual(board["optimize"]["xi"][0]["image_url"], photo)
        self.assertEqual(board["market"]["listings"][0]["image_url"], photo)
        self.assertEqual(board["squads"]["squads"][0]["players"][0]["image_url"], photo)
        self.assertEqual(board["trends"]["rising"][0]["image_url"], photo)
        self.assertEqual(board["flip"]["signings"][0]["image_url"], photo)

    def test_own_clause_risk_and_sell_peak(self) -> None:
        self.assertTrue(is_at_risk({"buyout_clause": 125, "market_value": 100}))
        self.assertFalse(is_at_risk({"buyout_clause": 126, "market_value": 100}))
        self.assertFalse(is_at_risk({"buyout_clause": 100}))
        self.assertEqual(official_price_delta({"market_value_change": 1_325_257, "acceleration": 246_253}), 1_325_257)
        self.assertEqual(official_price_delta({"price_delta": 1_325_257, "acceleration": 246_253}), 1_325_257)
        self.assertEqual(display_price_delta({"market_value_change": 902_732, "ff_price_delta": 823_000}), 902_732)
        self.assertEqual(
            official_price_delta({"market_value": 10_000_000, "sale_price": 8_674_743, "acceleration": 246_253}),
            1_325_257,
        )
        self.assertIsNone(official_price_delta({"acceleration": 246_253}))
        self.assertTrue(sell_signal({"acceleration": 6, "price_delta": 0}))
        self.assertTrue(sell_signal({"acceleration": 6, "market_value_change": -2}))
        self.assertFalse(sell_signal({"acceleration": 6, "price_delta": 3}))
        self.assertFalse(sell_signal({"acceleration": -1, "price_delta": -2}))
        self.assertTrue(sell_signal({"price_delta_3": 8, "acceleration": 0}))
        self.assertFalse(sell_signal(None))

    def test_golden_clause_rule_keeps_only_the_two_bargains(self) -> None:
        option_a = {"average_points": 3, "buyout_clause": 160, "market_value": 100}
        option_b = {"average_points": 6, "buyout_clause": 220, "market_value": 100}
        both = {"average_points": 7, "buyout_clause": 150, "market_value": 100}
        expensive = {"average_points": 8, "buyout_clause": 400, "market_value": 100}
        quiet = {"average_points": 2.9, "buyout_clause": 100, "market_value": 100}
        self.assertEqual(exposed_clause_rule(option_a), "A")
        self.assertEqual(exposed_clause_rule(option_b), "B")
        self.assertEqual(exposed_clause_rule(both), "A")
        self.assertIsNone(exposed_clause_rule(expensive))
        self.assertIsNone(exposed_clause_rule(quiet))


if __name__ == "__main__":
    unittest.main()

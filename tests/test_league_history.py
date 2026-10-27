"""Caja inferida y puja de liga a partir de la actividad oficial."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from toolbox.bidding import parse_events
from toolbox.cache import ResponseCache
from toolbox.net import ACTIVITY_PAGE_BATCH, LaligaClient
from toolbox.league_history import (
    apply_league_clearing,
    books_from_activity,
    clearing_quote,
    madrid_day,
    round_extra,
)


class _Tokens:
    def authorization_value(self) -> str:
        return "Bearer test-token"

    def force_refresh(self) -> str:
        return "test-token"


def _squad(team_id: str, *, manager_id: str, cash: int | None, self_team: bool) -> dict:
    return {
        "team_id": team_id,
        "manager_id": manager_id,
        "is_self": self_team,
        "manager_name": manager_id,
        "cash": cash,
        "players": [],
    }


class LeagueHistoryTests(unittest.TestCase):
    def test_activity_buy_clause_and_reward_parse(self) -> None:
        events = parse_events(
            [
                {
                    "activityTypeId": 31,
                    "id": "1",
                    "user1Id": 10,
                    "playerMasterId": 99,
                    "amount": 12_000_001,
                    "createdAt": "2026-10-18T14:08:00+02:00",
                },
                {
                    "activityTypeId": 1,
                    "id": "2",
                    "user1Id": 10,
                    "user2Id": 20,
                    "playerMasterId": 5,
                    "amount": 7_500_000,
                    "createdAt": "2026-10-15T07:53:00+02:00",
                },
                {"activityTypeId": 6, "id": "3", "user1Id": 20, "amount": 2_800_000, "createdAt": "2026-10-20T05:00:00+02:00", "weekNumber": 9},
                {"activityTypeId": 9, "id": "4", "user1Id": 10, "createdAt": "2026-10-13T14:00:00+02:00"},
            ]
        )
        self.assertEqual([event["kind"] for event in events], ["clause", "buy", "premium"])
        buy = next(event for event in events if event["kind"] == "buy")
        self.assertEqual(buy["manager_id"], "10")
        self.assertEqual(buy["amount_eur"], 12_000_001)
        self.assertEqual(round_extra(12_000_001), 1)
        self.assertEqual(round_extra(25_000_000), 0)
        self.assertEqual(round_extra(3_100_000), 0)
        self.assertIsNone(round_extra(18_617_759))

    def test_residual_cash_is_shared_and_rival_cash_is_a_ceiling(self) -> None:
        own = _squad("me", manager_id="1", cash=115_000_000, self_team=True)
        rival = _squad("them", manager_id="2", cash=None, self_team=False)
        events = parse_events(
            [
                {"activityTypeId": 6, "user1Id": 1, "amount": 2_000_000, "createdAt": "2026-10-20T05:00:00+02:00"},
                {"activityTypeId": 33, "user1Id": 1, "playerMasterId": 8, "amount": 5_000_000, "createdAt": "2026-10-18T14:12:00+02:00"},
                {"activityTypeId": 1, "user1Id": 2, "user2Id": 1, "playerMasterId": 4, "amount": 8_000_000, "createdAt": "2026-10-15T07:00:00+02:00"},
                {"activityTypeId": 31, "user1Id": 2, "playerMasterId": 7, "amount": 20_000_000, "createdAt": "2026-10-16T14:08:00+02:00"},
            ]
        )
        ledgers, history = books_from_activity([own, rival], events, {})
        by_team = {row["team_id"]: row for row in ledgers}
        self.assertEqual(history["initial_source"], "caja_propia")
        self.assertEqual(by_team["me"]["initial_budget_eur"], 100_000_000)
        self.assertEqual(by_team["me"]["reconstructed_cash_eur"], 115_000_000)
        self.assertFalse(by_team["me"]["cash_is_ceiling"])
        self.assertEqual(by_team["them"]["reconstructed_cash_eur"], 72_000_000)
        self.assertTrue(by_team["them"]["cash_is_ceiling"])

    def test_empty_history_does_not_invent_a_budget(self) -> None:
        ledgers, history = books_from_activity([_squad("me", manager_id="1", cash=50, self_team=True)], [], {})
        self.assertIsNone(ledgers[0]["reconstructed_cash_eur"])
        self.assertIsNone(history["initial_source"])
        self.assertEqual(history["war_count"], 0)
        self.assertEqual(history["buy_count"], 0)

    def test_explicit_initial_is_not_replaced(self) -> None:
        events = parse_events([{"type": "presupuesto", "teamId": "me", "money": 40}])
        ledgers, history = books_from_activity(
            [_squad("me", manager_id="1", cash=10, self_team=True)],
            events,
            {},
        )
        self.assertEqual(ledgers[0]["initial_budget_eur"], 40)
        self.assertEqual(history["initial_source"], "historial")
        self.assertFalse(ledgers[0]["cash_is_ceiling"])

    def test_war_quote_uses_median_and_counts_extreme_wars(self) -> None:
        own = _squad("me", manager_id="1", cash=100_000_000, self_team=True)
        rich = _squad("rich", manager_id="2", cash=None, self_team=False)
        poor = _squad("poor", manager_id="3", cash=None, self_team=False)
        events = []
        # residual: own cash 100M with no own flow => initial 100M
        # rich buys three wars; poor buys one extreme war that canonicalises the
        # cutoff (a >100 % premium is still a real bid, not noise to drop).
        specs = [
            (2, "a", 11_000_000, 10_000_000),
            (2, "b", 12_000_000, 10_000_000),
            (2, "c", 13_000_004, 10_000_000),
            (2, "d", 10_100_000, 10_000_000),
            (3, "e", 20_000_001, 10_000_000),
        ]
        for user, player, paid, ref in specs:
            events.append(
                {
                    "activityTypeId": 31,
                    "user1Id": user,
                    "playerMasterId": player,
                    "amount": paid,
                    "createdAt": "2026-10-18T14:08:00+02:00",
                }
            )
        snapshots = {(player, "2026-10-18"): 10_000_000 for _user, player, _paid, ref in specs}
        ledgers, history = books_from_activity([own, rich, poor], parse_events(events), snapshots)
        self.assertEqual(history["buy_count"], 5)
        self.assertEqual(history["priced_count"], 5)
        self.assertEqual(history["bomb_count"], 1)
        self.assertEqual(history["war_count"], 4)
        quote = clearing_quote(30_000_000, history)
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["war_count"], 4)
        self.assertEqual(quote["extreme_count"], 1)
        self.assertAlmostEqual(quote["median_premium"], 0.2500002, places=5)
        self.assertEqual(quote["league_bid_eur"], 37_600_005)
        self.assertIsNone(clearing_quote(90_000_000, history))
        poor_cash = next(row["reconstructed_cash_eur"] for row in ledgers if row["team_id"] == "poor")
        self.assertLess(poor_cash, 90_000_000)

    def test_extreme_war_sets_the_cutoff_when_the_rival_can_pay(self) -> None:
        """Una guerra > BOMB no se descarta: sube la puja de corte real."""
        own = _squad("me", manager_id="1", cash=100_000_000, self_team=True)
        rich = _squad("rich", manager_id="2", cash=None, self_team=False)
        events = []
        specs = [
            (2, "a", 11_000_000, 10_000_000),
            (2, "b", 12_000_000, 10_000_000),
            (2, "c", 13_000_004, 10_000_000),
            (2, "e", 25_000_000, 10_000_000),
        ]
        for user, player, paid, ref in specs:
            events.append(
                {
                    "activityTypeId": 31,
                    "user1Id": user,
                    "playerMasterId": player,
                    "amount": paid,
                    "createdAt": "2026-10-18T14:08:00+02:00",
                }
            )
        snapshots = {(player, "2026-10-18"): 10_000_000 for _user, player, _paid, ref in specs}
        _ledgers, history = books_from_activity([own, rich], parse_events(events), snapshots)
        self.assertEqual(history["bomb_count"], 1)
        self.assertEqual(history["war_count"], 4)
        quote = clearing_quote(30_000_000, history)
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote["war_count"], 4)
        self.assertEqual(quote["extreme_count"], 1)
        self.assertAlmostEqual(quote["median_premium"], 0.25, places=5)
        self.assertAlmostEqual(quote["p75_premium"], 0.3000004, places=5)
        self.assertEqual(quote["stretch_bid_eur"], 39_100_005)

    def test_apply_raises_open_bid_and_lowers_snipe(self) -> None:
        quote = {"league_bid_eur": 1_200_000, "stretch_bid_eur": 1_400_000, "war_count": 4}
        opened = apply_league_clearing(
            {"suggested_bid": 1_000_000, "bid_limit": "abrir", "value_ceiling": 1_500_000, "raise_to": None},
            quote,
            to_lead=900_000,
            cash=2_000_000,
        )
        self.assertEqual(opened["suggested_bid"], 1_200_000)
        self.assertEqual(opened["raise_to"], 1_400_000)
        self.assertFalse(opened["league_bid_blocked"])
        sniped = apply_league_clearing(
            {"suggested_bid": 1_500_000, "bid_limit": "snipe_techo", "value_ceiling": 1_500_000},
            quote,
            to_lead=1_000_001,
            cash=2_000_000,
        )
        self.assertEqual(sniped["suggested_bid"], 1_200_000)
        self.assertEqual(sniped["bid_limit"], "snipe_liga")
        blocked = apply_league_clearing(
            {"suggested_bid": 1_000_000, "bid_limit": "abrir", "value_ceiling": 1_100_000},
            quote,
            to_lead=900_000,
            cash=2_000_000,
        )
        self.assertEqual(blocked["suggested_bid"], 1_000_000)
        self.assertTrue(blocked["league_bid_blocked"])

    def test_activity_pages_concatenate_and_stop(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/activity/0"):
                return httpx.Response(200, json=[{"id": "a", "activityTypeId": 6, "user1Id": 1, "amount": 10, "createdAt": "2026-10-20T00:00:00+02:00"}])
            if path.endswith("/activity/1"):
                return httpx.Response(200, json=[{"id": "b", "activityTypeId": 33, "user1Id": 1, "playerMasterId": 4, "amount": 5, "createdAt": "2026-10-19T00:00:00+02:00"}])
            if path.endswith("/activity/2"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, json={"missing": True})

        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
            client = LaligaClient(tokens=_Tokens(), cache=cache, http=http, sleeper=lambda _seconds: None)
            payload = client.activity_payload("7", fresh=True)
            client.close()
            cache.close()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["payload"]), 2)
        self.assertTrue(payload["source_url"].endswith("/activity/1?x-lang=es"))

    def test_madrid_day_from_utc_stamp(self) -> None:
        self.assertEqual(madrid_day("2026-10-17T22:30:00Z"), "2026-10-18")
        self.assertEqual(madrid_day("2026-10-18T14:08:00+02:00"), "2026-10-18")

    def test_activity_stops_at_the_first_rate_limit(self) -> None:
        """Un 429 a mitad de historial para el proceso, no pagina más.

        Contrato actual: cualquier 429 es la señal más clara de que hay que
        parar, así que dispara el kill switch en lugar de seguir pidiendo
        páginas. La página 0 ya leída no se publica: el proceso muere antes de
        devolver nada. El disparo se captura con ``kill_switch_as_exception``
        para no matar la sesión de pytest.
        """
        from toolbox import net

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            path = request.url.path
            if path.endswith("/activity/0"):
                return httpx.Response(
                    200,
                    json=[{"id": "a", "activityTypeId": 31, "user1Id": 1, "playerMasterId": 9, "amount": 10, "createdAt": "2026-10-20T00:00:00+02:00"}],
                )
            if path.endswith("/activity/1"):
                return httpx.Response(429, json={"error": "rate"}, headers={"Retry-After": "120"})
            return httpx.Response(404, json={"missing": True})

        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
            client = LaligaClient(tokens=_Tokens(), cache=cache, http=http, sleeper=lambda _seconds: None)
            try:
                with net.kill_switch_as_exception():
                    with self.assertRaises(net.KillSwitchTripped):
                        client.activity_payload("7", fresh=True)
            finally:
                client.close()
                cache.close()
        # Página 0 más el primer lote de páginas (``ACTIVITY_PAGE_BATCH`` de 5),
        # que ya iba lanzado en paralelo cuando llegó el 429. No hay segundo lote.
        self.assertEqual(calls["n"], 1 + ACTIVITY_PAGE_BATCH)
        self.addCleanup(net.reset_kill_switch)

    def test_activity_concat_cache_skips_pages_on_second_read(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if "/activity/" in path and path.rstrip("/").endswith("/activity/concat"):
                return httpx.Response(404, json={"missing": True})
            if path.endswith("/activity/0"):
                calls["n"] += 1
                return httpx.Response(
                    200,
                    json=[{"id": "a", "activityTypeId": 6, "user1Id": 1, "amount": 10, "createdAt": "2026-10-20T00:00:00+02:00"}],
                )
            if path.endswith("/activity/1"):
                return httpx.Response(200, json=[])
            return httpx.Response(404, json={"missing": True})

        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
            client = LaligaClient(tokens=_Tokens(), cache=cache, http=http, sleeper=lambda _seconds: None)
            first = client.activity_payload("7", fresh=True)
            second = client.activity_payload("7", fresh=False)
            client.close()
            cache.close()
        self.assertTrue(first["ok"])
        self.assertEqual(second["payload"], first["payload"])
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()

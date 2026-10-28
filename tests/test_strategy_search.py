"""Búsqueda conjunta de planes: mercado, cláusulas y ventas. Sin red."""

from __future__ import annotations

import unittest

from toolbox.analyzer import Candidate
from toolbox.jornada_plan import plan_from_documents
from toolbox.strategy_search import (
    OwnedAsset,
    TargetAsset,
    collect_universe,
    search_strategies,
)


def _candidate(
    player_id: str,
    position: str,
    ev: float,
    *,
    excluded: str | None = None,
) -> Candidate:
    return Candidate(
        key=player_id,
        player_id=player_id,
        name=player_id,
        nickname=player_id,
        position=position,
        club="Test",
        p_titular=1.0,
        expected_points=ev,
        jornada_ev=ev,
        points_if_starts=ev,
        relevo_bonus=None,
        objective=ev,
        components={},
        player_status=None,
        excluded_reason=excluded,
    )


def _xi(prefix: str, *, default: float = 5.0, ev: dict[str, float] | None = None, sell: int | None = None) -> list[OwnedAsset]:
    slots = (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3))
    owned: list[OwnedAsset] = []
    scores = ev or {}
    for position, count in slots:
        for index in range(count):
            player_id = f"{prefix}-{position}-{index}"
            owned.append(
                OwnedAsset(
                    candidate=_candidate(player_id, position, scores.get(player_id, default)),
                    sell_eur=sell,
                )
            )
    return owned


class StrategySearchTests(unittest.TestCase):
    def test_sale_funds_clause_and_cash_only_appears(self) -> None:
        owned = _xi("own", ev={"own-DEL-0": 1.0})
        owned.append(OwnedAsset(candidate=_candidate("bench", "MC", 0.2), sell_eur=10_000_000))
        targets = [
            TargetAsset(
                candidate=_candidate("star", "DEL", 12.0),
                cost_eur=12_000_000,
                kind="clausular",
                manager_name="Rival",
            ),
            TargetAsset(
                candidate=_candidate("market", "DEL", 6.0),
                cost_eur=3_000_000,
                kind="pujar",
            ),
        ]
        document = search_strategies(cash=3_000_000, owned=owned, targets=targets, baseline_points=51.0)
        kinds = [[move["kind"] for move in plan["moves"]] for plan in document["strategies"]]
        self.assertTrue(any("vender" in row and "clausular" in row for row in kinds))
        self.assertTrue(any(plan.get("cash_only") and any(move["kind"] == "pujar" for move in plan["moves"]) for plan in document["strategies"]))
        self.assertTrue(all(plan["cash_after_eur"] >= 0 for plan in document["strategies"]))

    def test_two_signings_beat_single_star(self) -> None:
        owned = _xi("own", ev={"own-DEL-0": 1.0, "own-DEL-1": 1.0})
        targets = [
            TargetAsset(candidate=_candidate("cheap-a", "DEL", 8.0), cost_eur=2_000_000, kind="pujar"),
            TargetAsset(candidate=_candidate("cheap-b", "DEL", 8.0), cost_eur=2_000_000, kind="pujar"),
            TargetAsset(candidate=_candidate("star", "DEL", 12.0), cost_eur=5_000_000, kind="pujar"),
        ]
        document = search_strategies(cash=5_000_000, owned=owned, targets=targets, baseline_points=47.0)
        self.assertTrue(document["strategies"])
        best = document["strategies"][0]
        bought = {move["player_id"] for move in best["moves"] if move["kind"] == "pujar"}
        self.assertEqual(bought, {"cheap-a", "cheap-b"})
        self.assertGreater(best["expected_points"], 58.0)

    def test_cheaper_plan_wins_tied_points(self) -> None:
        owned = _xi("own", ev={"own-DEL-0": 1.0, "own-DEL-1": 10.0, "own-DEL-2": 10.0})
        targets = [
            TargetAsset(candidate=_candidate("dear", "DEL", 10.0), cost_eur=5_000_000, kind="pujar"),
            TargetAsset(candidate=_candidate("cheap", "DEL", 10.0), cost_eur=2_000_000, kind="pujar"),
        ]
        document = search_strategies(cash=10_000_000, owned=owned, targets=targets, baseline_points=61.0)
        best = document["strategies"][0]
        bought = [move["player_id"] for move in best["moves"] if move["kind"] == "pujar"]
        self.assertEqual(bought, ["cheap"])
        self.assertEqual(best["spend_eur"], 2_000_000)
        self.assertEqual(best["cash_after_eur"], 8_000_000)

    def test_does_not_sell_extra_bench(self) -> None:
        owned = _xi("own", ev={"own-DEL-0": 1.0})
        owned.append(OwnedAsset(candidate=_candidate("bench-a", "MC", 0.1), sell_eur=4_000_000))
        owned.append(OwnedAsset(candidate=_candidate("bench-b", "MC", 0.1), sell_eur=4_000_000))
        targets = [
            TargetAsset(candidate=_candidate("star", "DEL", 10.0), cost_eur=6_000_000, kind="clausular"),
        ]
        document = search_strategies(cash=3_000_000, owned=owned, targets=targets, baseline_points=51.0)
        sold = [move["player_id"] for move in document["strategies"][0]["moves"] if move["kind"] == "vender"]
        self.assertEqual(len(sold), 1)

    def test_cannot_go_negative(self) -> None:
        owned = _xi("own", ev={"own-DEL-0": 1.0})
        targets = [TargetAsset(candidate=_candidate("star", "DEL", 20.0), cost_eur=20_000_000, kind="clausular")]
        document = search_strategies(cash=1_000_000, owned=owned, targets=targets, baseline_points=51.0)
        self.assertEqual(document["strategies"], [])

    def test_excludes_own_listing_shielded_and_locked(self) -> None:
        own_players = []
        slots = (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3))
        for position, count in slots:
            for index in range(count):
                own_players.append(
                    {
                        "player_id": f"own-{position}-{index}",
                        "name": f"own-{position}-{index}",
                        "nickname": f"own-{position}-{index}",
                        "position": position,
                        "club": "Test",
                        "market_value": 1_000_000,
                        "average_points": 5,
                        "p_titular": 1.0,
                    }
                )
        squads = {
            "squads": [
                {"is_self": True, "team_id": "me", "cash": 8_000_000, "players": own_players},
                {
                    "is_self": False,
                    "team_id": "riv",
                    "manager_name": "Rival",
                    "players": [
                        {
                            "player_id": "locked",
                            "name": "locked",
                            "nickname": "locked",
                            "position": "DEL",
                            "buyout_clause": 2_000_000,
                            "is_shielded": False,
                            "clause_lock": {"is_locked": True},
                            "average_points": 9,
                            "p_titular": 1.0,
                        },
                        {
                            "player_id": "shielded",
                            "name": "shielded",
                            "nickname": "shielded",
                            "position": "DEL",
                            "buyout_clause": 2_000_000,
                            "is_shielded": True,
                            "clause_lock": {"is_locked": False},
                            "average_points": 9,
                            "p_titular": 1.0,
                        },
                        {
                            "player_id": "open",
                            "name": "open",
                            "nickname": "open",
                            "position": "DEL",
                            "buyout_clause": 2_000_000,
                            "is_shielded": False,
                            "clause_lock": {"is_locked": False},
                            "average_points": 9,
                            "p_titular": 1.0,
                        },
                    ],
                },
            ]
        }
        market = {
            "listings": [
                {
                    "player_id": "mine",
                    "name": "mine",
                    "nickname": "mine",
                    "position": "DEL",
                    "sale_price": 1_000_000,
                    "seller_team_id": "me",
                    "average_points": 9,
                    "p_titular": 1.0,
                },
                {
                    "player_id": "free",
                    "name": "free",
                    "nickname": "free",
                    "position": "DEL",
                    "sale_price": 1_000_000,
                    "average_points": 9,
                    "p_titular": 1.0,
                },
            ]
        }
        _cash, _owned, targets = collect_universe(market, squads, None)
        ids = {asset.candidate.player_id for asset in targets}
        self.assertIn("free", ids)
        self.assertIn("open", ids)
        self.assertNotIn("mine", ids)
        self.assertNotIn("locked", ids)
        self.assertNotIn("shielded", ids)

    def test_plan_document_includes_strategies(self) -> None:
        document = plan_from_documents(
            {"listings": []},
            {"squads": [{"is_self": True, "team_id": "me", "cash": 1_000_000, "players": []}]},
            {"players": []},
            {"ok": True, "xi": [], "matchday_void": True},
            None,
            {"rivals": []},
        )
        self.assertIn("strategies", document)
        self.assertEqual(document["strategies"], [])


if __name__ == "__main__":
    unittest.main()

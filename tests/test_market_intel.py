"""Motor de decisión de mercado. Sin red."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.market_intel import build_market_decisions, price_band


def _listing(
    player_id: str,
    *,
    sale: int = 1_000_000,
    leading: int | None = None,
    position: str = "MC",
    expires_at: str | None = None,
    seller: str | None = "rival-1",
) -> dict:
    body: dict = {
        "player_id": player_id,
        "name": player_id,
        "nickname": player_id,
        "position": position,
        "club": "Test FC",
        "sale_price": sale,
        "seller_team_id": seller,
    }
    if leading is not None:
        body["leading_bid"] = leading
    if expires_at is not None:
        body["listing_expires_at"] = expires_at
    return body


def _trend(player_id: str, **extra) -> dict:
    base = {
        "player_id": player_id,
        "name": player_id,
        "nickname": player_id,
        "position": "MC",
        "matching_confidence": 0.95,
    }
    base.update(extra)
    return base


class PriceBandTests(unittest.TestCase):
    def test_bargain_fair_overpay_unknown(self) -> None:
        self.assertEqual(price_band(100, 120, 150), "bargain")
        self.assertEqual(price_band(120, 120, 150), "bargain")
        self.assertEqual(price_band(130, 120, 150), "fair")
        self.assertEqual(price_band(151, 120, 150), "overpay")
        self.assertEqual(price_band(100, None, None), "unknown")
        self.assertEqual(price_band(None, 120, 150), "unknown")
        # Ideal sin máx: por encima del ideal es overpay relativo
        self.assertEqual(price_band(130, 120, None), "overpay")


class MarketDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        self.cash = 5_000_000
        self.flip = {
            "ok": True,
            "cash_eur": self.cash,
            "matchday_void": False,
            "team_id": "self-1",
            "signings": [],
            "rejected": [],
        }
        self.optimize = {"ok": True, "gaps": [], "market_fills": []}

    def _run(self, listings: list[dict], players: list[dict], **kwargs) -> dict:
        market = {"ok": True, "league_id": "L1", "listings": listings}
        trends = {"ok": True, "players": players}
        return build_market_decisions(
            market,
            trends,
            self.flip,
            self.optimize,
            now=self.now,
            **kwargs,
        )

    def test_decision_includes_auction_v2_metadata(self) -> None:
        doc = self._run(
            [_listing("p-v2", sale=1_000_000, leading=900_000)],
            [
                _trend(
                    "p-v2",
                    af_ideal_bid=1_200_000,
                    af_max_bid=1_500_000,
                    af_market_signal="up",
                    af_expected_points=8.0,
                    p_titular=0.9,
                    acceleration=50_000,
                )
            ],
        )
        row = doc["decisions"][0]
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
        if row["optimal_bid_eur"] is not None:
            self.assertIsInstance(row["optimal_bid_eur"], int)
            self.assertGreater(row["optimal_bid_eur"], 0)
        if row["win_probability"] is not None:
            self.assertGreaterEqual(row["win_probability"], 0.0)
            self.assertLessEqual(row["win_probability"], 1.0)
        if row["intrinsic_valuation_eur"] is not None:
            self.assertIsInstance(row["intrinsic_valuation_eur"], int)
        if row["bid_intent"] is not None:
            self.assertIn(row["bid_intent"], {"FLIP", "STRUCTURAL", "NONE"})

    def test_bargain_and_af_up_pujar_without_expiry(self) -> None:
        doc = self._run(
            [_listing("p1", sale=1_000_000)],
            [
                _trend(
                    "p1",
                    af_ideal_bid=1_200_000,
                    af_max_bid=1_500_000,
                    af_market_signal="up",
                    af_expected_points=8.0,
                    p_titular=0.9,
                    acceleration=50_000,
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertEqual(row["price_band"], "bargain")
        self.assertIn(row["primary_motive"], {"flip", "puntos"})
        self.assertEqual(row["bid_eur"], 1_000_000)

    def test_overpay_with_strong_motive_is_esperar(self) -> None:
        doc = self._run(
            [_listing("p2", sale=2_000_000)],
            [
                _trend(
                    "p2",
                    af_ideal_bid=1_000_000,
                    af_max_bid=1_200_000,
                    af_market_signal="up",
                    acceleration=100_000,
                    af_expected_points=7.0,
                    p_titular=0.8,
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "ESPERAR")
        self.assertEqual(row["price_band"], "overpay")
        self.assertIn("sobreprecio", row["reasons"])

    def test_injury_is_no(self) -> None:
        doc = self._run(
            [_listing("p3", sale=500_000)],
            [
                _trend(
                    "p3",
                    af_ideal_bid=600_000,
                    af_max_bid=700_000,
                    af_market_signal="up",
                    acceleration=80_000,
                    af_injury={"status": "lesionado", "info": "rodilla"},
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "NO")
        self.assertIn("lesionado", row["reasons"])

    def test_injury_list_does_not_veto_when_lineup_titular_is_high(self) -> None:
        doc = self._run(
            [_listing("p3b", sale=500_000)],
            [
                _trend(
                    "p3b",
                    af_ideal_bid=600_000,
                    af_max_bid=700_000,
                    af_market_signal="up",
                    acceleration=80_000,
                    p_titular=0.9,
                    p_titular_source="scraper",
                    lineup_status="titular",
                    af_injury={"status": "lesionado", "info": "molestia menor"},
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertNotIn("lesionado", row["reasons"])
        self.assertEqual(row["p_titular"], 0.9)
        self.assertIsNotNone(row.get("af_injury"))

    def test_missing_ideal_bid_does_not_invent_band(self) -> None:
        doc = self._run(
            [_listing("p4", sale=800_000)],
            [
                _trend(
                    "p4",
                    acceleration=40_000,
                    af_expected_points=6.0,
                    p_titular=0.7,
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["price_band"], "unknown")
        self.assertIn("ideal_bid", row["missing_inputs"])
        self.assertIn("max_bid", row["missing_inputs"])
        # Sin techo pero con aceleración LALIGA → puede pujar
        self.assertEqual(row["decision"], "PUJAR")

    def test_low_matching_blocks_af_only_pujar(self) -> None:
        doc = self._run(
            [_listing("p5", sale=900_000)],
            [
                _trend(
                    "p5",
                    matching_confidence=0.5,
                    af_ideal_bid=1_000_000,
                    af_max_bid=1_200_000,
                    af_market_signal="up",
                    af_expected_points=9.0,
                    p_titular=0.95,
                    # sin acceleration LALIGA
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertNotEqual(row["decision"], "PUJAR")
        self.assertIn("matching_confidence", row["reasons"] + row["missing_inputs"])

    def test_owned_player_is_no(self) -> None:
        doc = self._run(
            [_listing("p6", sale=400_000)],
            [_trend("p6", acceleration=10_000, af_ideal_bid=500_000, af_max_bid=600_000)],
            owned_ids={"p6"},
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "NO")
        self.assertIn("ya_en_plantilla", row["reasons"])

    def test_hidden_snipe_is_esperar(self) -> None:
        expires = (self.now + timedelta(hours=2)).isoformat()
        doc = self._run(
        [_listing("p7", sale=1_000_000, leading=1_000_000, expires_at=expires)],
            [
                _trend(
                    "p7",
                    af_ideal_bid=1_200_000,
                    af_max_bid=1_400_000,
                    acceleration=60_000,
                    af_market_signal="up",
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "ESPERAR")
        self.assertEqual(row["primary_motive"], "snipe")
        self.assertIn("esperar_snipe", row["reasons"])

    def test_gap_position_counts_as_motive(self) -> None:
        self.optimize = {
            "ok": True,
            "gaps": [{"position": "DEL", "missing": 1, "options": []}],
            "market_fills": [],
        }
        doc = self._run(
            [_listing("p8", sale=700_000, position="DEL")],
            [
                _trend(
                    "p8",
                    position="DEL",
                    af_ideal_bid=800_000,
                    af_max_bid=900_000,
                    # sin flip; el hueco basta
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertEqual(row["primary_motive"], "hueco")

    def test_league_offer_has_no_seller_and_rival_does(self) -> None:
        league = _listing("free", sale=500_000, seller=None)
        rival = _listing("sold", sale=500_000, seller="rival-9")
        rival["seller_manager"] = "Nuria"
        own = _listing("mine", sale=500_000, seller="self-1")
        doc = self._run(
            [league, rival, own],
            [
                _trend("free", acceleration=10_000),
                _trend("sold", acceleration=10_000),
                _trend("mine", acceleration=10_000),
            ],
        )
        by_id = {row["player_id"]: row for row in doc["decisions"]}
        self.assertEqual(by_id["free"]["offer_source"], "liga")
        self.assertIsNone(by_id["free"]["seller_manager"])
        self.assertEqual(by_id["sold"]["offer_source"], "rival")
        self.assertEqual(by_id["sold"]["seller_manager"], "Nuria")
        self.assertEqual(by_id["mine"]["offer_source"], "propio")
        self.assertEqual(by_id["mine"]["decision"], "NO")
        self.assertEqual(doc["summary"]["liga"], 1)
        self.assertEqual(doc["summary"]["rival"], 1)
        self.assertEqual(doc["summary"]["propio"], 1)

    def test_summary_counts(self) -> None:
        doc = self._run(
            [
                _listing("good", sale=500_000),
                _listing("hurt", sale=500_000),
            ],
            [
                _trend("good", acceleration=20_000, af_ideal_bid=600_000, af_max_bid=700_000),
                _trend(
                    "hurt",
                    acceleration=20_000,
                    af_ideal_bid=600_000,
                    af_max_bid=700_000,
                    af_injury={"status": "out"},
                ),
            ],
        )
        self.assertEqual(doc["summary"]["pujar"], 1)
        self.assertEqual(doc["summary"]["no"], 1)
        self.assertEqual(doc["summary"]["count"], 2)
        self.assertEqual(doc["summary"]["cash_eur"], self.cash)

    def test_own_expected_points_are_already_jornada_ev(self) -> None:
        doc = self._run(
            [_listing("own-ev", sale=2_000_000)],
            [
                _trend(
                    "own-ev",
                    own_expected_points=4.0,
                    own_ideal_bid=2_200_000,
                    own_max_bid=2_500_000,
                    p_titular=0.5,
                    acceleration=20_000,
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["expected_points_source"], "own")
        self.assertEqual(row["jornada_ev"], 4.0)
        self.assertEqual(row["points_roi"], 2.0)

    def test_af_expected_points_are_scaled_by_titular(self) -> None:
        doc = self._run(
            [_listing("af-ev", sale=1_000_000)],
            [
                _trend(
                    "af-ev",
                    af_expected_points=8.0,
                    af_ideal_bid=1_200_000,
                    af_max_bid=1_500_000,
                    p_titular=0.5,
                    acceleration=20_000,
                )
            ],
        )
        row = doc["decisions"][0]
        self.assertEqual(row["expected_points_source"], "af")
        self.assertEqual(row["jornada_ev"], 4.0)
        self.assertEqual(row["points_roi"], 4.0)


class JornadaBidTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        self.flip = {
            "ok": True,
            "cash_eur": 5_000_000,
            "matchday_void": False,
            "team_id": "self-1",
            "signings": [],
            "rejected": [],
        }

    def test_snipe_uses_lower_ceiling_not_plus_one(self) -> None:
        expires = (self.now + timedelta(hours=3)).isoformat()
        listing = _listing("p9", sale=1_000_000, leading=1_200_000, expires_at=expires)
        listing["bids"] = [
            {"amount": 1_200_000, "manager_name": "Ana", "team_id": "r1"},
            {"amount": 1_000_000, "manager_name": "Luis", "team_id": "r2"},
        ]
        doc = build_market_decisions(
            {"ok": True, "listings": [listing]},
            {
                "ok": True,
                "players": [
                    _trend(
                        "p9",
                        own_ideal_bid=1_500_000,
                        own_max_bid=1_800_000,
                        af_ideal_bid=1_400_000,
                        af_max_bid=1_600_000,
                        own_market_signal="up",
                        acceleration=40_000,
                        own_expected_points=7.0,
                        p_titular=0.9,
                    )
                ],
            },
            self.flip,
            {"ok": True, "gaps": [], "xi": [], "market_fills": []},
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "ESPERAR")
        self.assertEqual(row["value_ceiling"], 1_600_000)
        self.assertEqual(row["value_ceiling_source"], "af")
        self.assertEqual(row["aggressive_ceiling"], 1_800_000)
        self.assertEqual(row["suggested_bid"], 1_600_000)
        self.assertEqual(row["bid_limit"], "snipe_techo")
        self.assertEqual(row["rival_bids"][0]["manager_name"], "Ana")
        self.assertEqual(row["bid_eur"], 1_200_001)

    def test_leader_above_both_ceilings_is_not_chased(self) -> None:
        doc = build_market_decisions(
            {"ok": True, "listings": [_listing("p10", sale=800_000, leading=2_000_000)]},
            {
                "ok": True,
                "players": [
                    _trend(
                        "p10",
                        own_max_bid=1_500_000,
                        af_max_bid=1_400_000,
                        own_ideal_bid=1_200_000,
                        acceleration=30_000,
                        own_market_signal="up",
                    )
                ],
            },
            self.flip,
            {"ok": True, "gaps": [], "xi": [], "market_fills": []},
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertIsNone(row["suggested_bid"])
        self.assertEqual(row["bid_limit"], "sobre_techo")
        self.assertNotEqual(row["decision"], "PUJAR")

    def test_worse_than_xi_is_not_a_points_buy(self) -> None:
        doc = build_market_decisions(
            {"ok": True, "listings": [_listing("mkt", sale=900_000, position="DEL")]},
            {
                "ok": True,
                "players": [
                    _trend(
                        "mkt",
                        position="DEL",
                        own_expected_points=4.0,
                        own_max_bid=1_200_000,
                        own_ideal_bid=1_000_000,
                        p_titular=0.8,
                    ),
                    _trend("starter", position="DEL", own_expected_points=7.5, p_titular=0.9),
                ],
            },
            self.flip,
            {
                "ok": True,
                "gaps": [],
                "market_fills": [],
                "xi": [{"player_id": "starter", "name": "Starter", "nickname": "Starter", "position": "DEL"}],
            },
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["points_delta"], -3.5)
        self.assertEqual(row["replaces"]["name"], "Starter")
        self.assertNotEqual(row["decision"], "PUJAR")
        self.assertIn("no_mejora_xi", row["motives"])

    def test_better_than_xi_and_board_order(self) -> None:
        doc = build_market_decisions(
            {"ok": True, "listings": [{**_listing("mkt", sale=900_000, position="DEL"), "club": "Getafe"}]},
            {
                "ok": True,
                "players": [
                    _trend(
                        "mkt",
                        position="DEL",
                        club="Getafe",
                        own_expected_points=8.0,
                        own_ideal_bid=1_100_000,
                        own_max_bid=1_300_000,
                        p_titular=0.85,
                        own_calendar=[
                            {
                                "opponent": "Las Palmas",
                                "is_home": True,
                                "predicted_score": "2-0",
                                "recommendation_pct": 81,
                                "difficulty": "facil",
                            }
                        ],
                    ),
                    _trend(
                        "starter",
                        position="DEL",
                        club="Real Madrid",
                        own_expected_points=5.0,
                        own_calendar=[
                            {
                                "opponent": "Barcelona",
                                "is_home": False,
                                "predicted_score": "1-2",
                                "recommendation_pct": 40,
                                "difficulty": "dificil",
                            }
                        ],
                    ),
                    _trend(
                        "low-match",
                        club="Villarreal",
                        matching_confidence=0.4,
                        af_calendar=[
                            {
                                "opponent": "Celta",
                                "is_home": True,
                                "recommendation_pct": 99,
                                "difficulty": "muy_facil",
                            }
                        ],
                    ),
                ],
            },
            self.flip,
            {
                "ok": True,
                "gaps": [],
                "market_fills": [],
                "xi": [{"player_id": "starter", "nickname": "Starter", "position": "DEL"}],
            },
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertEqual(row["primary_motive"], "mejora_xi")
        self.assertEqual(row["points_delta"], 3.0)
        self.assertEqual(row["suggested_bid"], 1_100_000)
        self.assertEqual(row["raise_to"], 1_300_000)
        board = doc["jornada_board"]
        self.assertEqual([item["club"] for item in board], ["Getafe", "Real Madrid"])
        self.assertEqual(board[0]["market_count"], 1)
        self.assertNotIn("Villarreal", [item["club"] for item in board])

    def test_league_history_raises_open_bid(self) -> None:
        history = {
            "buy_count": 4,
            "priced_count": 4,
            "war_count": 3,
            "bomb_count": 0,
            "median_premium": 0.2,
            "p75_premium": 0.3,
            "samples": [
                {"team_id": "rich", "premium": 0.2, "round_extra": 0},
                {"team_id": "rich", "premium": 0.2, "round_extra": 0},
                {"team_id": "rich", "premium": 0.2, "round_extra": 0},
            ],
            "cash": [{"team_id": "rich", "cash_eur": 5_000_000, "cash_is_ceiling": True}],
        }
        doc = build_market_decisions(
            {"listings": [_listing("p-hist", sale=1_000_000, seller=None)]},
            {
                "players": [
                    _trend(
                        "p-hist",
                        own_ideal_bid=1_050_000,
                        own_max_bid=1_400_000,
                        own_expected_points=6.0,
                        acceleration=20_000,
                    )
                ]
            },
            self.flip,
            {"ok": True, "gaps": [], "market_fills": []},
            history=history,
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertEqual(row["league_war_count"], 3)
        self.assertEqual(row["league_buy_count"], 4)
        self.assertEqual(row["suggested_bid"], 1_200_001)
        self.assertEqual(row["league_bid"], 1_200_001)
        self.assertEqual(doc["summary"]["league_buy_count"], 4)


class SourceConflictActionTests(unittest.TestCase):
    """Conflicto de puntos con plusvalía esperada: ESPERAR, no veto duro."""

    def _row(self, player_id: str, *, af_points: float) -> dict:
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        flip = {
            "ok": True,
            "cash_eur": 20_000_000,
            "matchday_void": False,
            "team_id": "self-1",
            "signings": [],
            "rejected": [],
        }
        doc = build_market_decisions(
            {"ok": True, "listings": [_listing(player_id, sale=1_000_000, position="DEL")]},
            {
                "ok": True,
                "players": [
                    _trend(
                        player_id,
                        position="DEL",
                        own_expected_points=8.0,
                        af_expected_points=af_points,
                        own_ideal_bid=4_000_000,
                        own_max_bid=9_000_000,
                        af_ideal_bid=4_000_000,
                        af_max_bid=9_000_000,
                        p_titular=0.95,
                        acceleration=50_000,
                        own_market_signal="up",
                        af_market_signal="up",
                    )
                ],
            },
            flip,
            {"ok": True, "gaps": [], "market_fills": []},
            now=now,
        )
        return doc["decisions"][0]

    def test_profitable_puntos_conflict_waits_instead_of_veto(self) -> None:
        row = self._row("conflict-profitable", af_points=4.0)
        # 8.0 vs 4.0 → ratio 2.0 ≥ 1.5: conflicto de puntos.
        self.assertEqual(row["source_conflict"], "puntos")
        self.assertGreater(row["expected_surplus_eur"], 0)
        self.assertEqual(row["action"], "ESPERAR")
        self.assertFalse(row["is_vetoed"])

    def test_puntos_conflict_without_surplus_keeps_hard_veto(self) -> None:
        from toolbox.market_intel import _action_from_decision

        for surplus in (0, None):
            action, vetoed, _ = _action_from_decision(
                "ESPERAR",
                conflict="puntos",
                bid_limit=None,
                hard_veto=False,
                reasons=[],
                expected_surplus_eur=surplus,
            )
            self.assertEqual((action, vetoed), ("NO", True))

    def test_non_puntos_conflict_is_still_vetoed_when_profitable(self) -> None:
        from toolbox.market_intel import _action_from_decision

        action, vetoed, _ = _action_from_decision(
            "PUJAR",
            conflict="techo",
            bid_limit=None,
            hard_veto=False,
            reasons=[],
            expected_surplus_eur=500_000,
        )
        self.assertEqual((action, vetoed), ("NO", True))


class DayBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        self.kickoff = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc).isoformat()

    def _flip(self, cash: int) -> dict:
        return {
            "ok": True,
            "cash_eur": cash,
            "matchday_void": False,
            "team_id": "self-1",
            "signings": [],
            "rejected": [],
        }

    def _strong(self, player_id: str, **extra) -> dict:
        body = _trend(
            player_id,
            acceleration=50_000,
            af_ideal_bid=extra.pop("ideal", 1_400_000),
            af_max_bid=extra.pop("maximum", 1_800_000),
            af_expected_points=extra.pop("points", 8.0),
            p_titular=0.9,
        )
        body.update(extra)
        return body

    def test_does_not_stack_the_same_cash_twice(self) -> None:
        doc = build_market_decisions(
            {
                "listings": [
                    _listing("cheap", sale=1_200_000),
                    _listing("pricey", sale=1_500_000),
                ]
            },
            {
                "players": [
                    self._strong("cheap", ideal=1_400_000, maximum=1_800_000, points=9.0, acceleration=80_000),
                    self._strong("pricey", ideal=1_600_000, maximum=2_000_000, points=6.0, acceleration=20_000),
                ]
            },
            self._flip(2_000_000),
            {"ok": True, "gaps": [], "market_fills": []},
            now=self.now,
        )
        by_id = {row["player_id"]: row for row in doc["decisions"]}
        self.assertEqual(by_id["cheap"]["decision"], "PUJAR")
        self.assertEqual(by_id["pricey"]["decision"], "ESPERAR")
        self.assertEqual(by_id["pricey"]["primary_motive"], "caja_otras_pujas")
        self.assertIn("caja_otras_pujas", by_id["pricey"]["motives"])
        self.assertEqual(doc["summary"]["pujar"], 1)
        self.assertEqual(doc["summary"]["markets_left"], 1)
        self.assertEqual(doc["summary"]["plan_spend_eur"], by_id["cheap"]["suggested_bid"])
        self.assertEqual(
            doc["summary"]["plan_cash_after_eur"],
            2_000_000 - by_id["cheap"]["suggested_bid"],
        )

    def test_splits_cash_across_markets_until_kickoff(self) -> None:
        doc = build_market_decisions(
            {"listings": [_listing("star", sale=3_500_000)]},
            {
                "players": [
                    self._strong(
                        "star",
                        ideal=4_000_000,
                        maximum=4_500_000,
                        fixture={"kickoff": self.kickoff},
                    )
                ]
            },
            self._flip(9_000_000),
            {"ok": True, "gaps": [], "market_fills": []},
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(doc["summary"]["markets_left"], 3)
        self.assertEqual(doc["summary"]["day_budget_eur"], 3_000_000)
        self.assertEqual(row["decision"], "ESPERAR")
        self.assertEqual(row["primary_motive"], "caja_otros_mercados")
        self.assertEqual(row["suggested_bid"], 4_000_000)
        self.assertEqual(doc["summary"]["pujar"], 0)
        self.assertEqual(doc["summary"]["plan_spend_eur"], 0)
        self.assertEqual(doc["summary"]["plan_cash_after_eur"], 9_000_000)

    def test_gap_fill_can_use_more_than_today_slice(self) -> None:
        doc = build_market_decisions(
            {"listings": [_listing("keeper", sale=3_500_000, position="POR")]},
            {
                "players": [
                    self._strong(
                        "keeper",
                        position="POR",
                        ideal=4_000_000,
                        maximum=4_500_000,
                        fixture={"kickoff": self.kickoff},
                    )
                ]
            },
            self._flip(9_000_000),
            {
                "ok": True,
                "gaps": [{"position": "POR", "missing": 1, "options": []}],
                "market_fills": [],
            },
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertEqual(row["primary_motive"], "hueco")
        self.assertEqual(doc["summary"]["markets_left"], 3)
        self.assertEqual(doc["summary"]["day_budget_eur"], 3_000_000)
        self.assertEqual(doc["summary"]["plan_spend_eur"], 4_000_000)
        self.assertEqual(doc["summary"]["plan_cash_after_eur"], 5_000_000)

    def test_midweek_two_clubs_do_not_eat_the_jornada_budget(self) -> None:
        midweek = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc).isoformat()
        weekend = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc).isoformat()
        clubs = ["Rayo Vallecano", "Elche CF", "Valencia CF", "Villarreal CF", "Real Madrid"]
        extras = [
            _trend(f"bench-{index}", club=club, fixture={"kickoff": weekend})
            for index, club in enumerate(clubs)
        ]
        doc = build_market_decisions(
            {"listings": [_listing("star", sale=3_500_000)]},
            {
                "players": [
                    self._strong("star", club="Celta", ideal=4_000_000, maximum=4_500_000, fixture={"kickoff": weekend}),
                    _trend("mid-a", club="Athletic Club", fixture={"kickoff": midweek}),
                    _trend("mid-b", club="Levante UD", fixture={"kickoff": midweek}),
                    *extras,
                ]
            },
            self._flip(9_000_000),
            {"ok": True, "gaps": [], "market_fills": []},
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(doc["summary"]["markets_left"], 6)
        self.assertEqual(doc["summary"]["day_budget_eur"], 1_500_000)
        self.assertEqual(row["decision"], "ESPERAR")
        self.assertEqual(row["primary_motive"], "caja_otros_mercados")

    def test_single_listing_still_pujar_without_kickoff(self) -> None:
        doc = build_market_decisions(
            {"listings": [_listing("p1", sale=1_000_000)]},
            {"players": [self._strong("p1")]},
            self._flip(5_000_000),
            {"ok": True, "gaps": [], "market_fills": []},
            now=self.now,
        )
        row = doc["decisions"][0]
        self.assertEqual(row["decision"], "PUJAR")
        self.assertEqual(doc["summary"]["markets_left"], 1)
        self.assertEqual(doc["summary"]["day_budget_eur"], 5_000_000)


if __name__ == "__main__":
    unittest.main()

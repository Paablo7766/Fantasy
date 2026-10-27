"""Auditoría de caja rival: cota superior, gasto oculto y asientos manuales."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from toolbox.rival_intel import (
    CLAUSE_INCREASE_MULTIPLIER,
    DAILY_AD_REVENUE,
    DEFAULT_CLAUSE_INCREASE_MULTIPLIER,
    DEFAULT_LEAGUE_START_DATE,
    DEFAULT_STARTING_CLAUSE_MULTIPLIER,
    INITIAL_BUDGET,
    LedgerAuditor,
    cash_control_thermometer,
    configured_clause_increase_multiplier,
    configured_league_start_date,
    configured_starting_clause_multiplier,
    events_from_ledgers,
    extract_money,
    get_financial_intel,
    parse_activities,
    reward_amount,
)

_NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _squad(
    team_id: str,
    *,
    manager_id: str | None = None,
    cash: int | None = None,
    players: list[dict] | None = None,
    self_team: bool = False,
) -> dict:
    return {
        "team_id": team_id,
        "manager_id": manager_id or team_id,
        "manager_name": f"Manager {team_id}",
        "is_self": self_team,
        "cash": cash,
        "players": players or [],
    }


def _squads(*rows: dict, league_id: str = "liga-1") -> dict:
    return {"ok": True, "league_id": league_id, "squads": list(rows)}


class _Paths:
    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp())

    def auditor(self, **kwargs) -> LedgerAuditor:
        options = {
            "adjustments_path": self.dir / "ledger_adjustments.json",
            "expenses_path": self.dir / "hidden_expenses_log.json",
            "snapshot_path": self.dir / "clause_snapshot_history.json",
        }
        options.update(kwargs)
        return LedgerAuditor(**options)


class RewardExtractionTests(unittest.TestCase):
    def test_regex_reads_the_amount_of_a_reward_sentence(self) -> None:
        text = "El equipo Rival ha recibido 4.500.000 € por los puntos de la jornada 7"
        self.assertEqual(reward_amount(text), 4_500_000)

    def test_accepts_abonado_and_plain_euros(self) -> None:
        self.assertEqual(reward_amount("Se ha abonado 1.250.000 € al equipo"), 1_250_000)
        self.assertEqual(reward_amount("Ingresado 980.000 € por la jornada 3"), 980_000)

    def test_accepts_english_and_comma_thousands(self) -> None:
        self.assertEqual(reward_amount("You have received 2,500,000 € for matchday 5"), 2_500_000)
        self.assertEqual(reward_amount("Amount credited: 750.000 €"), 750_000)

    def test_ignores_sentences_without_a_prize(self) -> None:
        self.assertIsNone(reward_amount("El jugador ha fichado por el equipo rival"))
        self.assertIsNone(reward_amount("Jornada 12"))

    def test_extract_money_marks_currency(self) -> None:
        tokens = extract_money("Prima de 300.000 € y bonus de 2 por 20.000")
        self.assertEqual([token["amount"] for token in tokens], [300_000, 2, 20_000])
        self.assertTrue(tokens[0]["currency"])
        self.assertFalse(tokens[1]["currency"])


class ParseActivitiesTests(unittest.TestCase):
    def test_official_rows_map_to_canonical_kinds(self) -> None:
        events = parse_activities(
            {
                "events": [
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
                    {
                        "activityTypeId": 6,
                        "id": "3",
                        "user1Id": 20,
                        "amount": 2_800_000,
                        "createdAt": "2026-10-20T05:00:00+02:00",
                    },
                ]
            }
        )
        by_kind = {event["kind"]: event for event in events}
        self.assertEqual(set(by_kind), {"buy", "clause", "premium"})
        self.assertEqual(by_kind["buy"]["team_id"], "10")
        self.assertEqual(by_kind["buy"]["player_id"], "99")
        self.assertEqual(by_kind["clause"]["counterparty_manager_id"], "20")
        self.assertEqual(by_kind["buy"]["signed_eur"], -12_000_001)
        self.assertEqual(by_kind["premium"]["signed_eur"], 2_800_000)

    def test_prose_reward_is_parsed_when_amount_is_missing(self) -> None:
        events = parse_activities(
            [
                {
                    "id": "p",
                    "user1Id": 4,
                    "label": "El equipo ha recibido 4.500.000 € por los puntos de la jornada",
                    "createdAt": "2026-10-20T05:00:00+02:00",
                }
            ]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "premium")
        self.assertEqual(events[0]["amount_eur"], 4_500_000)
        self.assertEqual(events[0]["matched_by"], "regex")

    def test_duplicated_pages_do_not_double_count(self) -> None:
        row = {
            "activityTypeId": 6,
            "id": "same",
            "user1Id": 10,
            "amount": 1_000_000,
            "createdAt": "2026-10-20T05:00:00+02:00",
        }
        self.assertEqual(len(parse_activities([row, dict(row)])), 1)

    def test_unknown_type_without_money_is_dropped(self) -> None:
        self.assertEqual(
            parse_activities([{"activityTypeId": 99, "id": "x", "user1Id": 10}]),
            [],
        )

    def test_join_and_no_score_rows_are_kept_as_markers(self) -> None:
        events = parse_activities(
            [
                {"activityTypeId": 9, "id": "j", "user1Id": 10, "createdAt": "2026-10-13T09:00:00+02:00"},
                {"activityTypeId": 8, "id": "n", "user1Id": 10, "createdAt": "2026-10-20T09:00:00+02:00"},
                {"activityTypeId": 7, "id": "m", "user1Id": 11, "createdAt": "2026-10-21T09:00:00+02:00"},
            ]
        )
        self.assertEqual([event["kind"] for event in events], ["marker"] * 3)
        markers = {event["marker"] for event in events}
        self.assertEqual(markers, {"join", "no_score"})
        negative = [event for event in events if event["no_score_reason"] == "saldo_negativo"]
        self.assertEqual(len(negative), 1)
        self.assertEqual(negative[0]["team_id"], "10")
        self.assertEqual(negative[0]["signed_eur"], 0)

    def test_events_from_ledgers_keeps_team_and_player(self) -> None:
        payload = events_from_ledgers(
            [
                {
                    "team_id": "r",
                    "events": [{"kind": "buy", "amount_eur": 9_000_000, "player_id": "p9", "at": None}],
                }
            ]
        )
        self.assertTrue(payload["ok"])
        events = parse_activities(payload)
        self.assertEqual(events[0]["team_id"], "r")
        self.assertEqual(events[0]["player_id"], "p9")


class HistoricalReconstructionTests(unittest.TestCase):
    def test_budget_plus_income_minus_expense_plus_ads(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("r", players=[]))
        activity = {
            "events": [
                {"activityTypeId": 6, "id": "a", "user1Id": "r", "amount": 2_000_000},
                {"activityTypeId": 33, "id": "b", "user1Id": "r", "amount": 5_000_000},
                {"activityTypeId": 31, "id": "c", "user1Id": "r", "amount": 8_000_000},
            ]
        }
        document = get_financial_intel(squads, activity, auditor=paths.auditor(), now=_NOW)
        team = document["teams"]["r"]
        days = document["days_elapsed"]
        # 1 ago → 24 oct, ambos incluidos.
        self.assertEqual(days, 85)
        expected = INITIAL_BUDGET + 2_000_000 + 5_000_000 - 8_000_000 + days * DAILY_AD_REVENUE
        self.assertEqual(team["calculated_cash"], expected)
        self.assertEqual(team["max_bid_limit"], expected)
        self.assertTrue(team["cash_is_upper_bound"])
        self.assertEqual(document["ad_revenue_per_team_eur"], days * DAILY_AD_REVENUE)

    def test_every_rival_receives_all_daily_ads(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("a"), _squad("b"), _squad("me", self_team=True))
        document = get_financial_intel(squads, {"events": []}, auditor=paths.auditor(), now=_NOW)
        ads = document["ad_revenue_per_team_eur"]
        for team_id in ("a", "b", "me"):
            self.assertEqual(document["teams"][team_id]["calculated_cash"], INITIAL_BUDGET + ads)

    def test_explicit_initial_budget_in_history_overrides_the_constant(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("r"))
        activity = {"events": [{"kind": "initial", "team_id": "r", "amount_eur": 40_000_000}]}
        document = get_financial_intel(squads, activity, auditor=paths.auditor(), now=_NOW)
        self.assertEqual(document["config"]["initial_budget_source"], "historial")
        self.assertEqual(
            document["teams"]["r"]["breakdown"]["initial_budget_eur"], 40_000_000
        )

    def test_clause_credits_the_seller_through_the_manager_map(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("buyer", manager_id="10"), _squad("seller", manager_id="20"))
        activity = {
            "events": [
                {
                    "activityTypeId": 1,
                    "id": "1",
                    "user1Id": 10,
                    "user2Id": 20,
                    "playerMasterId": 5,
                    "amount": 7_500_000,
                }
            ]
        }
        document = get_financial_intel(squads, activity, auditor=paths.auditor(), now=_NOW)
        ads = document["ad_revenue_per_team_eur"]
        self.assertEqual(
            document["teams"]["buyer"]["calculated_cash"],
            INITIAL_BUDGET - 7_500_000 + ads,
        )
        self.assertEqual(
            document["teams"]["seller"]["calculated_cash"],
            INITIAL_BUDGET + 7_500_000 + ads,
        )
        self.assertEqual(document["teams"]["seller"]["breakdown"]["sales_eur"], 7_500_000)

    def test_debt_limit_raises_the_bid_ceiling(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("r"))
        document = get_financial_intel(
            squads,
            {"events": []},
            auditor=paths.auditor(debt_limit_eur=2_000_000),
            now=_NOW,
        )
        team = document["teams"]["r"]
        self.assertEqual(team["max_bid_limit"], team["calculated_cash"] + 2_000_000)

    def test_observed_cash_below_the_bound_is_flagged(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("r", cash=500_000_000))
        document = get_financial_intel(squads, {"events": []}, auditor=paths.auditor(), now=_NOW)
        reconciliation = document["teams"]["r"]["reconciliation"]
        self.assertFalse(reconciliation["covers_observed"])
        self.assertTrue(reconciliation["underestimated"])
        self.assertTrue(any("por debajo" in warning for warning in document["warnings"]))

    def test_observed_cash_inside_the_bound_reconciles(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("r", cash=1_000_000))
        document = get_financial_intel(squads, {"events": []}, auditor=paths.auditor(), now=_NOW)
        reconciliation = document["teams"]["r"]["reconciliation"]
        self.assertTrue(reconciliation["covers_observed"])
        self.assertFalse(reconciliation["underestimated"])


class ForensicClauseTests(unittest.TestCase):
    def test_signed_player_base_is_the_price_paid(self) -> None:
        paths = _Paths()
        player = {"player_id": "p1", "buyout_clause": 15_000_000, "market_value": 10_000_000}
        activity = {
            "events": [
                {"activityTypeId": 31, "id": "b", "user1Id": "r", "playerMasterId": "p1", "amount": 12_000_000}
            ]
        }
        document = get_financial_intel(
            _squads(_squad("r", players=[player])), activity, auditor=paths.auditor(), now=_NOW
        )
        hidden = document["teams"]["r"]["detected_hidden_expenses"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0]["basis"], "fichado")
        self.assertEqual(hidden[0]["classification"], "FICHADO")
        self.assertEqual(hidden[0]["clause_base_eur"], 12_000_000)
        self.assertEqual(hidden[0]["cost_eur"], round(3_000_000 * CLAUSE_INCREASE_MULTIPLIER))

    def test_hidden_json_field_wins_over_market_value(self) -> None:
        paths = _Paths()
        player = {
            "player_id": "p2",
            "buyout_clause": 8_000_000,
            "market_value": 5_000_000,
            "meta": {"buyPrice": 4_000_000},
        }
        document = get_financial_intel(
            _squads(_squad("r", players=[player])), {"events": []}, auditor=paths.auditor(), now=_NOW
        )
        hidden = document["teams"]["r"]["detected_hidden_expenses"][0]
        self.assertEqual(hidden["basis"], "campo_oculto")
        self.assertEqual(hidden["basis_field"], "buyPrice")
        self.assertEqual(hidden["clause_base_eur"], 4_000_000)

    def test_drafted_player_falls_back_to_market_value_times_multiplier(self) -> None:
        paths = _Paths()
        player = {"player_id": "p3", "buyout_clause": 9_000_000, "market_value": 5_000_000}
        document = get_financial_intel(
            _squads(_squad("r", players=[player])), {"events": []}, auditor=paths.auditor(), now=_NOW
        )
        hidden = document["teams"]["r"]["detected_hidden_expenses"][0]
        self.assertEqual(hidden["basis"], "valor_mercado")
        self.assertEqual(hidden["classification"], "REPARTO")
        self.assertEqual(hidden["clause_base_eur"], 7_500_000)

    def test_clause_at_or_below_base_is_not_an_expense(self) -> None:
        paths = _Paths()
        player = {"player_id": "p4", "buyout_clause": 5_000_000, "market_value": 5_000_000}
        document = get_financial_intel(
            _squads(_squad("r", players=[player])), {"events": []}, auditor=paths.auditor(), now=_NOW
        )
        team = document["teams"]["r"]
        self.assertEqual(team["detected_hidden_expenses"], [])
        self.assertEqual(team["hidden_expenses_eur"], 0)

    def test_player_without_clause_lowers_confidence(self) -> None:
        paths = _Paths()
        players = [
            {"player_id": "p1", "market_value": 1_000_000},
            {"player_id": "p2", "buyout_clause": 9_000_000, "market_value": 5_000_000},
        ]
        activity = {"events": [{"activityTypeId": 6, "id": "a", "user1Id": "r", "amount": 1_000_000}]}
        document = get_financial_intel(
            _squads(_squad("r", players=players)), activity, auditor=paths.auditor(), now=_NOW
        )
        team = document["teams"]["r"]
        self.assertEqual(team["players_without_clause"], 1)
        self.assertEqual(team["confidence"], "medium")

    def test_full_data_gives_high_confidence(self) -> None:
        paths = _Paths()
        players = [{"player_id": "p1", "buyout_clause": 9_000_000, "market_value": 5_000_000}]
        activity = {"events": [{"activityTypeId": 6, "id": "a", "user1Id": "r", "amount": 1_000_000}]}
        document = get_financial_intel(
            _squads(_squad("r", players=players)), activity, auditor=paths.auditor(), now=_NOW
        )
        self.assertEqual(document["teams"]["r"]["confidence"], "high")


class DailyDiffTests(unittest.TestCase):
    def _snapshot(self, *players: dict, team_id: str = "r") -> dict:
        return {"squads": [{"team_id": team_id, "players": list(players)}]}

    def test_a_rise_in_24h_is_charged_and_persisted(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        yesterday = self._snapshot({"player_id": "p1", "buyout_clause": 10_000_000})
        today = self._snapshot({"player_id": "p1", "buyout_clause": 14_000_000})
        diff = auditor.calculate_daily_diff(yesterday, today, now=_NOW)
        self.assertEqual(diff["total_cost_eur"], round(4_000_000 * CLAUSE_INCREASE_MULTIPLIER))
        self.assertEqual(diff["cost_by_team"], {"r": round(4_000_000 * CLAUSE_INCREASE_MULTIPLIER)})
        self.assertTrue(diff["persisted"])
        stored = json.loads((paths.dir / "hidden_expenses_log.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stored["entries"]), 1)
        self.assertEqual(stored["entries"][0]["day"], "2026-10-24")

    def test_a_drop_is_not_a_cost(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        yesterday = self._snapshot({"player_id": "p1", "buyout_clause": 14_000_000})
        today = self._snapshot({"player_id": "p1", "buyout_clause": 10_000_000})
        diff = auditor.calculate_daily_diff(yesterday, today, now=_NOW)
        self.assertEqual(diff["changes"], [])
        self.assertFalse(diff["persisted"])

    def test_repeating_the_same_diff_does_not_duplicate_the_log(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        yesterday = self._snapshot({"player_id": "p1", "buyout_clause": 10_000_000})
        today = self._snapshot({"player_id": "p1", "buyout_clause": 14_000_000})
        auditor.calculate_daily_diff(yesterday, today, now=_NOW)
        auditor.calculate_daily_diff(yesterday, today, now=_NOW)
        stored = json.loads((paths.dir / "hidden_expenses_log.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stored["entries"]), 1)

    def test_sold_player_keeps_his_cost_after_leaving_the_squad(self) -> None:
        """El "agujero fantasma": la subida sobrevive a la venta del jugador."""
        paths = _Paths()
        auditor = paths.auditor()
        yesterday = self._snapshot({"player_id": "ghost", "buyout_clause": 5_000_000})
        today = self._snapshot({"player_id": "ghost", "buyout_clause": 7_000_000})
        auditor.calculate_daily_diff(yesterday, today, now=_NOW)

        after_sale = _squads(_squad("r", players=[]))
        document = get_financial_intel(
            after_sale, {"events": []}, auditor=auditor, now=_NOW, persist=False
        )
        team = document["teams"]["r"]
        self.assertEqual(team["hidden_expenses_eur"], 400_000)
        self.assertEqual(team["detected_hidden_expenses"][0]["player_id"], "ghost")

    def test_a_player_still_in_the_squad_is_not_counted_twice(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        player = {"player_id": "p1", "buyout_clause": 14_000_000, "market_value": 10_000_000}
        yesterday = self._snapshot({"player_id": "p1", "buyout_clause": 10_000_000})
        today = self._snapshot(dict(player))
        auditor.calculate_daily_diff(yesterday, today, now=_NOW)

        document = get_financial_intel(
            _squads(_squad("r", players=[player])), {"events": []}, auditor=auditor, now=_NOW, persist=False
        )
        team = document["teams"]["r"]
        # Base 10M por valor de mercado → subida 4M cobrada una sola vez.
        self.assertEqual(team["hidden_expenses_eur"], round(4_000_000 * CLAUSE_INCREASE_MULTIPLIER))
        self.assertEqual(len(team["detected_hidden_expenses"]), 1)

    def test_several_daily_rises_are_all_charged(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        player = {"player_id": "p1", "buyout_clause": 14_000_000, "market_value": 10_000_000}
        day1 = self._snapshot({"player_id": "p1", "buyout_clause": 10_000_000})
        day2 = self._snapshot({"player_id": "p1", "buyout_clause": 11_000_000})
        day3 = self._snapshot(dict(player))
        auditor.calculate_daily_diff(day1, day2, now=_NOW, day="2026-10-22")
        auditor.calculate_daily_diff(day2, day3, now=_NOW, day="2026-10-23")

        document = get_financial_intel(
            _squads(_squad("r", players=[player])), {"events": []}, auditor=auditor, now=_NOW, persist=False
        )
        team = document["teams"]["r"]
        # Dos saltos medidos (1M + 3M) superan la estimación retroactiva (4M).
        self.assertEqual(team["hidden_expenses_eur"], round(4_000_000 * CLAUSE_INCREASE_MULTIPLIER))
        self.assertEqual(len(team["detected_hidden_expenses"]), 2)

    def test_stored_snapshot_is_used_when_no_explicit_pair_is_given(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        before = _squads(_squad("r", players=[{"player_id": "p1", "buyout_clause": 10_000_000}]))
        auditor.save_clause_snapshot(before, day="2026-10-20", now=_NOW)
        after = _squads(_squad("r", players=[{"player_id": "p1", "buyout_clause": 12_000_000}]))
        document = get_financial_intel(after, {"events": []}, auditor=auditor, now=_NOW)
        self.assertEqual(document["daily_diff"]["from_day"], "2026-10-20")
        self.assertEqual(document["daily_diff"]["change_count"], 1)

    def test_stale_photo_is_stamped_with_its_own_day(self) -> None:
        """Una foto de hace tres días no se fecha como si fuera de hoy."""
        paths = _Paths()
        auditor = paths.auditor()
        before = _squads(_squad("r", players=[{"player_id": "p1", "buyout_clause": 10_000_000}]))
        auditor.save_clause_snapshot(before, day="2026-10-20", now=_NOW)
        stale = _squads(_squad("r", players=[{"player_id": "p1", "buyout_clause": 12_000_000}]))
        document = get_financial_intel(
            stale, {"events": []}, auditor=auditor, now=_NOW, observed_on="2026-10-21"
        )
        self.assertEqual(document["daily_diff"]["day"], "2026-10-21")
        stored = json.loads((paths.dir / "clause_snapshot_history.json").read_text(encoding="utf-8"))
        self.assertNotIn("2026-10-24", stored["days"])
        self.assertIn("2026-10-21", stored["days"])

    def test_first_reading_of_the_day_is_not_overwritten(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        first = _squads(_squad("r", players=[{"player_id": "p1", "buyout_clause": 10_000_000}]))
        auditor.save_clause_snapshot(first, day="2026-10-24", now=_NOW)
        later = _squads(_squad("r", players=[{"player_id": "p1", "buyout_clause": 13_000_000}]))
        auditor.save_clause_snapshot(later, day="2026-10-24", now=_NOW, keep_existing=True)
        stored = json.loads((paths.dir / "clause_snapshot_history.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["days"]["2026-10-24"]["r"]["p1"], 10_000_000)


class AdjustmentTests(unittest.TestCase):
    def _write(self, paths: _Paths, payload: dict) -> None:
        (paths.dir / "ledger_adjustments.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_anchor_pins_cash_and_only_post_entries_move_it(self) -> None:
        paths = _Paths()
        self._write(paths, {"r": {"2026-10-21": {"cash_override": 5_000_000, "reason": "Micropagos premium"}}})
        activity = {
            "events": [
                {"activityTypeId": 31, "id": "old", "user1Id": "r", "amount": 9_000_000, "createdAt": "2026-09-01T10:00:00+02:00"},
                {"activityTypeId": 6, "id": "new", "user1Id": "r", "amount": 1_000_000, "createdAt": "2026-10-22T10:00:00+02:00"},
            ]
        }
        document = get_financial_intel(_squads(_squad("r")), activity, auditor=paths.auditor(), now=_NOW)
        team = document["teams"]["r"]
        self.assertFalse(team["cash_is_upper_bound"])
        self.assertEqual(team["breakdown"]["period"], "post_ancla")
        self.assertEqual(team["breakdown"]["initial_budget_eur"], 5_000_000)
        self.assertEqual(team["breakdown"]["purchases_eur"], 0)
        self.assertEqual(team["breakdown"]["premiums_eur"], 1_000_000)
        # El día del asiento ya está resumido en el override: el anuncio corre desde el día siguiente.
        self.assertEqual(team["breakdown"]["ad_days"], 3)
        self.assertEqual(team["calculated_cash"], 5_000_000 + 1_000_000 + 3 * DAILY_AD_REVENUE)

    def test_latest_past_anchor_wins(self) -> None:
        paths = _Paths()
        self._write(
            paths,
            {
                "r": {
                    "2026-10-01": {"cash_override": 1_000_000},
                    "2026-10-20": {"cash_override": 9_000_000},
                    "2026-12-01": {"cash_override": 50_000_000},
                }
            },
        )
        document = get_financial_intel(_squads(_squad("r")), {"events": []}, auditor=paths.auditor(), now=_NOW)
        breakdown = document["teams"]["r"]["breakdown"]
        self.assertEqual(breakdown["anchor_day"], "2026-10-20")
        self.assertEqual(breakdown["initial_budget_eur"], 9_000_000)

    def test_anchor_suppresses_the_undated_retroactive_estimate(self) -> None:
        paths = _Paths()
        self._write(paths, {"r": {"2026-10-21": {"cash_override": 5_000_000}}})
        player = {"player_id": "p1", "buyout_clause": 15_000_000, "market_value": 5_000_000}
        document = get_financial_intel(
            _squads(_squad("r", players=[player])), {"events": []}, auditor=paths.auditor(), now=_NOW
        )
        team = document["teams"]["r"]
        self.assertEqual(team["hidden_expenses_eur"], 0)
        self.assertEqual(team["detected_hidden_expenses"], [])

    def test_daily_expense_after_the_anchor_is_still_charged(self) -> None:
        paths = _Paths()
        auditor = paths.auditor()
        yesterday = {"squads": [{"team_id": "r", "players": [{"player_id": "p1", "buyout_clause": 10_000_000}]}]}
        today = {"squads": [{"team_id": "r", "players": [{"player_id": "p1", "buyout_clause": 12_000_000}]}]}
        auditor.calculate_daily_diff(yesterday, today, now=_NOW)
        self._write(paths, {"r": {"2026-10-21": {"cash_override": 5_000_000}}})
        document = get_financial_intel(
            _squads(_squad("r", players=[])), {"events": []}, auditor=auditor, now=_NOW, persist=False
        )
        team = document["teams"]["r"]
        self.assertEqual(team["hidden_expenses_eur"], 400_000)
        self.assertEqual(team["calculated_cash"], 5_000_000 + 3 * DAILY_AD_REVENUE - 400_000)

    def test_broken_adjustments_file_does_not_break_the_audit(self) -> None:
        paths = _Paths()
        (paths.dir / "ledger_adjustments.json").write_text("{no es json", encoding="utf-8")
        document = get_financial_intel(_squads(_squad("r")), {"events": []}, auditor=paths.auditor(), now=_NOW)
        self.assertTrue(document["ok"])
        self.assertTrue(document["warnings"])

    def test_documentation_keys_are_not_teams(self) -> None:
        paths = _Paths()
        auditor = paths.auditor(adjustments_path=Path("ledger_adjustments.example.json"))
        adjustments, warnings = auditor.load_adjustments()
        self.assertEqual(warnings, [])
        self.assertEqual(list(adjustments), ["example-team-id"])


class OutputContractTests(unittest.TestCase):
    def test_every_team_exposes_the_frontend_contract(self) -> None:
        paths = _Paths()
        player = {"player_id": "p1", "buyout_clause": 15_000_000, "market_value": 10_000_000}
        document = get_financial_intel(
            _squads(_squad("r", players=[player])), {"events": []}, auditor=paths.auditor(), now=_NOW
        )
        team = document["teams"]["r"]
        for key in ("calculated_cash", "max_bid_limit", "detected_hidden_expenses"):
            self.assertIn(key, team)
        self.assertIsInstance(team["calculated_cash"], int)
        self.assertIsInstance(team["max_bid_limit"], int)
        self.assertIsInstance(team["detected_hidden_expenses"], list)

    def test_squads_document_with_errors_still_returns_a_row(self) -> None:
        paths = _Paths()
        broken = _squad("r")
        broken["error"] = "boom"
        document = get_financial_intel(_squads(broken), {"events": []}, auditor=paths.auditor(), now=_NOW)
        team = document["teams"]["r"]
        self.assertEqual(team["squad_error"], "boom")
        self.assertEqual(team["confidence"], "low")


class RiskConfigurationTests(unittest.TestCase):
    """Los parámetros de riesgo salen del entorno/``.env``, con fallback."""

    def setUp(self) -> None:
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for name in (
            "CLAUSE_INCREASE_MULTIPLIER",
            "STARTING_CLAUSE_MULTIPLIER",
            "LEAGUE_START_DATE",
            "CASH_THERMOMETER_TAU",
            "CASH_ARBITRAGE_BAND",
            "CASH_UNCERTAINTY_FLOOR_EUR",
        ):
            os.environ.pop(name, None)
        self.addCleanup(self._env.stop)

    def test_defaults_when_the_variables_are_absent(self) -> None:
        self.assertEqual(configured_clause_increase_multiplier(), DEFAULT_CLAUSE_INCREASE_MULTIPLIER)
        self.assertEqual(configured_starting_clause_multiplier(), DEFAULT_STARTING_CLAUSE_MULTIPLIER)
        self.assertEqual(configured_league_start_date(), DEFAULT_LEAGUE_START_DATE)
        self.assertEqual(DEFAULT_CLAUSE_INCREASE_MULTIPLIER, 0.20)
        self.assertEqual(DEFAULT_STARTING_CLAUSE_MULTIPLIER, 1.5)
        self.assertEqual(DEFAULT_LEAGUE_START_DATE, "2026-08-01")

    def test_environment_overrides_the_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CLAUSE_INCREASE_MULTIPLIER": "0.35",
                "STARTING_CLAUSE_MULTIPLIER": "1.8",
                "LEAGUE_START_DATE": "2026-08-10",
            },
        ):
            self.assertEqual(configured_clause_increase_multiplier(), 0.35)
            self.assertEqual(configured_starting_clause_multiplier(), 1.8)
            self.assertEqual(configured_league_start_date(), "2026-08-10")
            auditor = LedgerAuditor(persist=False)
            self.assertEqual(auditor.clause_increase_multiplier, 0.35)
            self.assertEqual(auditor.starting_clause_multiplier, 1.8)
            self.assertEqual(auditor.league_start_date.isoformat(), "2026-08-10")

    def test_a_comma_decimal_is_accepted(self) -> None:
        with patch.dict(os.environ, {"CLAUSE_INCREASE_MULTIPLIER": "0,35"}):
            self.assertEqual(configured_clause_increase_multiplier(), 0.35)

    def test_a_bad_value_falls_back_instead_of_breaking_the_bound(self) -> None:
        for value in ("", "mucho", "-0.1", "0", "2.5", "nan"):
            with self.subTest(value=value), patch.dict(os.environ, {"CLAUSE_INCREASE_MULTIPLIER": value}):
                self.assertEqual(
                    configured_clause_increase_multiplier(), DEFAULT_CLAUSE_INCREASE_MULTIPLIER
                )
        with patch.dict(os.environ, {"LEAGUE_START_DATE": "2026-13-45"}):
            self.assertEqual(configured_league_start_date(), DEFAULT_LEAGUE_START_DATE)

    def test_the_league_start_date_moves_the_ad_accrual(self) -> None:
        """Corregir el inicio de liga corrige los anuncios devengados."""
        paths = _Paths()
        with patch.dict(os.environ, {"LEAGUE_START_DATE": "2026-10-20"}):
            document = get_financial_intel(
                _squads(_squad("r")), {"events": []}, auditor=paths.auditor(), now=_NOW
            )
        # 20 → 24 de octubre, ambos incluidos.
        self.assertEqual(document["days_elapsed"], 5)
        self.assertEqual(document["ad_revenue_per_team_eur"], 5 * DAILY_AD_REVENUE)
        self.assertEqual(document["config"]["league_start_date"], "2026-10-20")

    def test_the_dotenv_file_is_read_when_the_shell_is_silent(self) -> None:
        directory = Path(tempfile.mkdtemp())
        (directory / ".env").write_text(
            "CLAUSE_INCREASE_MULTIPLIER=0.30\n# comentario\nLEAGUE_START_DATE=2026-09-01\n",
            encoding="utf-8",
        )
        with patch("toolbox.rival_intel.project_root", return_value=directory):
            self.assertEqual(configured_clause_increase_multiplier(), 0.30)
            self.assertEqual(configured_league_start_date(), "2026-09-01")

    def test_the_engine_reports_the_effective_configuration(self) -> None:
        paths = _Paths()
        document = get_financial_intel(
            _squads(_squad("r")), {"events": []}, auditor=paths.auditor(), now=_NOW
        )
        config = document["config"]
        self.assertEqual(config["clause_increase_multiplier"], DEFAULT_CLAUSE_INCREASE_MULTIPLIER)
        self.assertEqual(config["starting_clause_multiplier"], DEFAULT_STARTING_CLAUSE_MULTIPLIER)
        self.assertEqual(config["league_start_date"], DEFAULT_LEAGUE_START_DATE)
        self.assertIn("thermometer_tau", config)
        self.assertIn("arbitrage_band", config)


class ControlThermometerTests(unittest.TestCase):
    """El hueco entre cota y saldo se traduce a temperatura y arbitraje."""

    def _read(self, calculated: int, observed: int, **kwargs) -> dict:
        options = {"tau": 0.10, "band": 0.02}
        options.update(kwargs)
        return cash_control_thermometer(calculated, observed, **options)

    def test_an_exact_match_is_the_hottest_reading(self) -> None:
        reading = self._read(5_000_000, 5_000_000)
        self.assertEqual(reading["gap_eur"], 0)
        self.assertEqual(reading["temperature"], 1.0)
        self.assertEqual(reading["status"], "exact")
        self.assertEqual(reading["arbitrage_eur"], 0)
        self.assertTrue(reading["covers_observed"])

    def test_the_temperature_decays_with_the_relative_gap(self) -> None:
        near = self._read(5_100_000, 5_000_000)
        far = self._read(60_000_000, 5_000_000)
        self.assertGreater(near["temperature"], far["temperature"])
        self.assertLessEqual(near["temperature"], 1.0)
        self.assertGreater(near["temperature"], 0.0)

    def test_a_shortfall_publishes_the_unexplained_cash(self) -> None:
        reading = self._read(3_000_000, 4_000_000, band=0.05)
        self.assertTrue(reading["underestimated"])
        self.assertFalse(reading["covers_observed"])
        self.assertEqual(reading["status"], "underestimated")
        # Hueco 1M; el 5 % de 4M (200k) es ruido: quedan 800k sin explicar.
        self.assertEqual(reading["arbitrage_eur"], 800_000)

    def test_a_shortfall_inside_the_noise_band_is_not_arbitrage(self) -> None:
        reading = self._read(4_950_000, 5_000_000, band=0.05)
        self.assertTrue(reading["underestimated"])
        self.assertEqual(reading["arbitrage_eur"], 0)
        self.assertEqual(reading["status"], "within_band")

    def test_the_calibrated_ceiling_never_goes_below_the_observed_cash(self) -> None:
        """El saldo publicado es un hecho: la cota calibrada lo cubre siempre."""
        for calculated, observed in ((3_000_000, 4_000_000), (9_000_000, 4_000_000), (4_000_000, 4_000_000)):
            with self.subTest(calculated=calculated, observed=observed):
                reading = self._read(calculated, observed)
                self.assertGreaterEqual(reading["tight_ceiling_eur"], observed)

    def test_a_loose_bound_is_trimmed_and_a_short_one_is_not_inflated(self) -> None:
        loose = self._read(60_000_000, 5_000_000)
        short = self._read(3_000_000, 4_000_000)
        self.assertLess(loose["tight_ceiling_eur"], 60_000_000)
        self.assertEqual(loose["tight_ceiling_eur"], 5_000_000 + loose["tightening_margin_eur"])
        # Se queda corta: no se sube la cifra a la observada sin decirlo.
        self.assertEqual(short["tight_ceiling_eur"], 4_000_000)
        self.assertGreater(short["arbitrage_eur"], 0)

    def test_the_accrual_widens_the_margin(self) -> None:
        plain = self._read(6_000_000, 5_000_000)
        accrued = self._read(6_000_000, 5_000_000, accrual_eur=400_000)
        self.assertGreater(accrued["tight_ceiling_eur"], plain["tight_ceiling_eur"])

    def test_the_cover_probability_is_a_cdf_of_the_gap(self) -> None:
        covered = self._read(9_000_000, 5_000_000)
        short = self._read(1_000_000, 5_000_000)
        self.assertGreater(covered["cover_probability"], 0.5)
        self.assertLess(short["cover_probability"], 0.5)
        self.assertEqual(covered["posterior_sigma_eur"], 4_000_000)

    def test_the_sigma_has_a_floor_so_an_exact_match_is_not_degenerate(self) -> None:
        reading = self._read(5_000_000, 5_000_000, floor_eur=200_000)
        self.assertEqual(reading["posterior_sigma_eur"], 200_000)

    def test_the_reconciliation_exposes_the_thermometer(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("r", cash=500_000_000))
        document = get_financial_intel(squads, {"events": []}, auditor=paths.auditor(), now=_NOW)
        reconciliation = document["teams"]["r"]["reconciliation"]
        for key in (
            "temperature",
            "cover_probability",
            "arbitrage_eur",
            "posterior_sigma_eur",
            "tight_ceiling_eur",
            "status",
        ):
            self.assertIn(key, reconciliation)
        self.assertGreater(reconciliation["arbitrage_eur"], 0)
        self.assertTrue(any("fuera de los libros" in warning for warning in document["warnings"]))

    def test_the_risk_adjusted_ceiling_is_exposed_per_team(self) -> None:
        paths = _Paths()
        squads = _squads(_squad("r", cash=250_000))
        document = get_financial_intel(squads, {"events": []}, auditor=paths.auditor(), now=_NOW)
        team = document["teams"]["r"]
        self.assertLessEqual(team["risk_adjusted_cash"], team["calculated_cash"])
        self.assertGreaterEqual(team["risk_adjusted_cash"], 250_000)
        self.assertEqual(
            team["risk_adjusted_bid_limit"], max(0, team["risk_adjusted_cash"] + team["debt_limit_eur"])
        )

    def test_a_team_without_observed_cash_keeps_the_full_bound(self) -> None:
        paths = _Paths()
        document = get_financial_intel(_squads(_squad("r")), {"events": []}, auditor=paths.auditor(), now=_NOW)
        team = document["teams"]["r"]
        self.assertIsNone(team["reconciliation"])
        self.assertEqual(team["risk_adjusted_cash"], team["calculated_cash"])


class DailyVideoBandTests(unittest.TestCase):
    """El vídeo diario no se ve: cada rival tiene una banda, no una cifra."""

    def test_the_band_is_bounded_by_zero_and_all_videos(self) -> None:
        paths = _Paths()
        document = get_financial_intel(_squads(_squad("r")), {"events": []}, auditor=paths.auditor(), now=_NOW)
        team = document["teams"]["r"]
        bounds = team["ad_bounds"]
        self.assertEqual(bounds["days"], document["days_elapsed"])
        self.assertEqual(bounds["max_ad_eur"], bounds["days"] * DAILY_AD_REVENUE)
        self.assertEqual(bounds["min_ad_eur"], 0)
        self.assertEqual(team["cash_floor_eur"], team["calculated_cash"] - bounds["max_ad_eur"])
        self.assertEqual(team["cash_band_eur"], bounds["max_ad_eur"] - bounds["min_ad_eur"])
        self.assertLessEqual(team["cash_floor_eur"], team["cash_expected_eur"])
        self.assertLessEqual(team["cash_expected_eur"], team["calculated_cash"])
        self.assertEqual(
            team["floor_bid_limit"], max(0, team["cash_floor_eur"] + team["debt_limit_eur"])
        )

    def test_the_join_day_closes_the_window_instead_of_the_env_date(self) -> None:
        """La liga nació el 13: los días de agosto no devengan anuncios."""
        paths = _Paths()
        activity = {
            "events": [
                {
                    "activityTypeId": 9,
                    "id": "join",
                    "user1Id": "r",
                    "createdAt": "2026-10-13T09:00:00+02:00",
                }
            ]
        }
        document = get_financial_intel(_squads(_squad("r")), activity, auditor=paths.auditor(), now=_NOW)
        # 13 → 24 de octubre, ambos incluidos.
        self.assertEqual(document["days_elapsed"], 12)
        self.assertEqual(document["config"]["league_start_source"], "alta")
        self.assertEqual(document["config"]["season_start_date"], "2026-10-13")
        self.assertEqual(document["ad_revenue_per_team_eur"], 12 * DAILY_AD_REVENUE)

    def test_a_late_joiner_accrues_fewer_days_than_the_league(self) -> None:
        paths = _Paths()
        activity = {
            "events": [
                {"activityTypeId": 9, "id": "j1", "user1Id": "old", "createdAt": "2026-10-13T09:00:00+02:00"},
                {"activityTypeId": 9, "id": "j2", "user1Id": "new", "createdAt": "2026-10-22T09:00:00+02:00"},
            ]
        }
        document = get_financial_intel(
            _squads(_squad("old"), _squad("new")), activity, auditor=paths.auditor(), now=_NOW
        )
        self.assertEqual(document["teams"]["old"]["ad_bounds"]["days"], 12)
        self.assertEqual(document["teams"]["new"]["ad_bounds"]["days"], 3)
        self.assertEqual(document["teams"]["new"]["ad_bounds"]["team_start_day"], "2026-10-22")

    def test_own_cash_calibrates_the_expected_video_rate(self) -> None:
        """Si mi caja cuadra con el 50 % de los vídeos, el rival esperado va al 50 %."""
        paths = _Paths()
        days = 12
        half = days * DAILY_AD_REVENUE // 2
        own_cash = INITIAL_BUDGET + half
        activity = {
            "events": [
                {"activityTypeId": 9, "id": "j1", "user1Id": "me", "createdAt": "2026-10-13T09:00:00+02:00"},
                {"activityTypeId": 9, "id": "j2", "user1Id": "r", "createdAt": "2026-10-13T09:00:00+02:00"},
            ]
        }
        document = get_financial_intel(
            _squads(_squad("me", cash=own_cash, self_team=True), _squad("r")),
            activity,
            auditor=paths.auditor(),
            now=_NOW,
        )
        self.assertEqual(document["config"]["own_ad_rate_pct"], 50.0)
        rival = document["teams"]["r"]
        self.assertEqual(rival["ad_bounds"]["own_rate_pct"], 50.0)
        self.assertEqual(rival["ad_bounds"]["expected_ad_eur"], half)
        self.assertEqual(rival["cash_expected_eur"], INITIAL_BUDGET + half)
        self.assertEqual(rival["calculated_cash"], INITIAL_BUDGET + days * DAILY_AD_REVENUE)

    def test_a_gap_below_the_books_pins_the_rate_to_zero(self) -> None:
        paths = _Paths()
        activity = {
            "events": [
                {"activityTypeId": 9, "id": "j1", "user1Id": "me", "createdAt": "2026-10-13T09:00:00+02:00"},
            ]
        }
        document = get_financial_intel(
            _squads(_squad("me", cash=INITIAL_BUDGET - 900_000, self_team=True)),
            activity,
            auditor=paths.auditor(),
            now=_NOW,
        )
        self.assertEqual(document["config"]["own_ad_rate_pct"], 0.0)
        self.assertTrue(any("gasto propio sin registrar" in warning for warning in document["warnings"]))

    def test_a_negative_balance_penalty_does_not_erase_the_forced_floor(self) -> None:
        """El tipo 8 no borra el suelo: la cota se aplica siempre."""
        paths = _Paths()
        activity = {
            "events": [
                {"activityTypeId": 9, "id": "j", "user1Id": "r", "createdAt": "2026-10-13T09:00:00+02:00"},
                {
                    "activityTypeId": 31,
                    "id": "big",
                    "user1Id": "r",
                    "amount": 120_000_000,
                    "createdAt": "2026-10-15T10:00:00+02:00",
                },
                {
                    "activityTypeId": 8,
                    "id": "neg",
                    "user1Id": "r",
                    "createdAt": "2026-10-16T09:00:00+02:00",
                },
            ]
        }
        document = get_financial_intel(_squads(_squad("r")), activity, auditor=paths.auditor(), now=_NOW)
        bounds = document["teams"]["r"]["ad_bounds"]
        # El aviso de saldo negativo solo prueba que el mecanismo de anuncios
        # existe; no excusa los días de descubierto del libro.
        self.assertEqual(bounds["no_score_reasons"], ["saldo_negativo"])
        self.assertTrue(bounds["forced_by_balance"])
        self.assertGreater(bounds["min_ad_eur"], 0)
        self.assertEqual(bounds["min_ad_eur"] % DAILY_AD_REVENUE, 0)
        self.assertLessEqual(bounds["min_ad_eur"], bounds["max_ad_eur"])
        team = document["teams"]["r"]
        # El suelo se descuenta una sola vez: la cota inferior es la caja
        # reconstruida más el suelo, no el piso del libro inflado otra vez.
        self.assertLessEqual(team["cash_floor_eur"], team["calculated_cash"] + bounds["min_ad_eur"])

    def test_an_impossible_purchase_forces_the_video_floor(self) -> None:
        """Sin tipo 8, un gasto que deja el libro en negativo solo se explica con vídeos."""
        paths = _Paths()
        activity = {
            "events": [
                {"activityTypeId": 9, "id": "j", "user1Id": "r", "createdAt": "2026-10-13T09:00:00+02:00"},
                {
                    "activityTypeId": 31,
                    "id": "big",
                    "user1Id": "r",
                    "amount": 100_500_000,
                    "createdAt": "2026-10-15T10:00:00+02:00",
                },
            ]
        }
        document = get_financial_intel(_squads(_squad("r")), activity, auditor=paths.auditor(), now=_NOW)
        team = document["teams"]["r"]
        bounds = team["ad_bounds"]
        self.assertGreater(bounds["min_ad_eur"], 0)
        self.assertTrue(bounds["forced_by_balance"])
        self.assertEqual(bounds["min_ad_eur"] % DAILY_AD_REVENUE, 0)
        self.assertEqual(bounds["lowest_book_balance_eur"], -500_000)
        self.assertEqual(
            team["cash_floor_eur"],
            INITIAL_BUDGET - 100_500_000 + bounds["min_ad_eur"],
        )
        self.assertGreaterEqual(team["cash_floor_eur"], 0)


if __name__ == "__main__":
    unittest.main()

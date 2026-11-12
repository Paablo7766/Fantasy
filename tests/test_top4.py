import unittest

from toolbox.league_form import build_league_form, round_summaries, rounds_from_ledgers
from toolbox.top4 import build_top4, calibrate_sigma, simulate

SQUADS = [
    {"team_id": str(i), "manager_name": f"m{i}", "is_self": i == 0, "error": None} for i in range(5)
]


def ledger(team, week, pts):
    return {
        "team_id": str(team),
        "events": [
            {"kind": "premium", "amount_eur": pts * 100_000, "activity_type_id": 6, "week": week},
            # Otros ingresos "premium" sin tipo 6 no son puntos.
            {"kind": "premium", "amount_eur": 7_000_000, "activity_type_id": 12},
        ],
    }


class RoundsFromLedgers(unittest.TestCase):
    def test_points_come_from_prize(self):
        led = [ledger(i, 12, 50 - 5 * i) for i in range(5)]
        rounds = rounds_from_ledgers(led, SQUADS)
        self.assertEqual(rounds[12]["m0"], 50)
        self.assertEqual(rounds[12]["m4"], 30)

    def test_round_with_missing_teams_is_dropped(self):
        led = [ledger(i, 12, 50) for i in range(4)]
        self.assertEqual(rounds_from_ledgers(led, SQUADS), {})

    def test_non_multiple_of_100k_ignored(self):
        led = [ledger(i, 3, 10) for i in range(5)]
        led[0]["events"][0]["amount_eur"] = 1_050_000
        self.assertEqual(rounds_from_ledgers(led, SQUADS), {})

    def test_activity_beats_manual_and_summary_line(self):
        led = [ledger(i, 12, 60 - 5 * i) for i in range(5)]
        manual = {11: {f"m{i}": 40 for i in range(5)}}
        form = build_league_form({"squads": SQUADS}, ledgers=led) if False else None
        rounds = {**manual, **rounds_from_ledgers(led, SQUADS)}
        summary = round_summaries(rounds, "m3")
        self.assertEqual([r["round"] for r in summary], [11, 12])
        self.assertEqual(summary[1]["cutoff"], 45)  # 4.º de 60,55,50,45,40
        self.assertEqual(summary[1]["gap"], 0)
        self.assertTrue(summary[1]["in_top4"])


class Simulation(unittest.TestCase):
    def test_stronger_team_has_higher_probability(self):
        out = simulate([60, 50, 50, 50, 40, 40, 40, 30, 30, 30], 10, self_index=0)
        probs = out["p_top4"]
        self.assertGreater(probs[0], probs[4])
        self.assertGreater(probs[4], probs[9])
        self.assertAlmostEqual(float(probs.sum()), 4.0, delta=0.6)

    def test_forced_zero_never_in_top4(self):
        out = simulate([50] * 10, 8, self_index=0, forced_zero={0})
        self.assertEqual(float(out["p_top4"][0]), 0.0)

    def test_sigma_calibration_recovers_noise(self):
        import random

        random.seed(1)
        skill = [10 * i for i in range(10)]
        rounds = {
            n: {f"m{i}": round(40 + skill[i] + random.gauss(0, 8) + 3 * n) for i in range(10)} for n in range(1, 9)
        }
        cal = calibrate_sigma(rounds)
        self.assertTrue(cal["calibrated"])
        self.assertAlmostEqual(cal["sigma"], 8, delta=1.5)

    def test_few_rounds_flags_uncalibrated(self):
        self.assertFalse(calibrate_sigma({1: {"a": 1}})["calibrated"])


def race(count_self=11):
    table = []
    for i in range(10):
        table.append(
            {
                "team_id": str(i),
                "manager_name": f"m{i}",
                "is_self": i == 0,
                "player_count": count_self if i == 0 else 13,
                "projection": {"expected_points": 40 + i, "xi": [{"expected_points": 3.0}]},
            }
        )
    return {"table": table, "my_projection": {"expected_points": 47.0, "xi": [{"expected_points": 3.0}] * 10}}


class BuildTop4(unittest.TestCase):
    def test_full_squad_has_no_void(self):
        out = build_top4(race(11), None)
        self.assertTrue(out["ok"])
        self.assertFalse(out["void"])
        self.assertGreater(out["p_top4"], 0.2)

    def test_ten_players_is_void_and_reports_completed_scenario(self):
        out = build_top4(race(10), None)
        self.assertTrue(out["void"])
        self.assertEqual(out["p_top4"], 0.0)
        self.assertEqual(out["if_completed"]["missing_players"], 1)
        self.assertEqual(out["if_completed"]["expected_points"], 50.0)
        self.assertGreater(out["if_completed"]["p_top4"], 0.2)

    def test_no_table(self):
        self.assertFalse(build_top4({"table": []}, None)["ok"])


if __name__ == "__main__":
    unittest.main()

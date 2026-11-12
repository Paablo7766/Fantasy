import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from toolbox.top4_log import evaluar, freeze_forecast

NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
KICK = (NOW + timedelta(days=8)).isoformat()
NAMES = [f"m{i}" for i in range(10)]


def race(base=40):
    table = [
        {"team_id": str(i), "manager_name": f"m{i}", "is_self": i == 0, "player_count": 13,
         "projection": {"expected_points": base + i, "xi": []}}
        for i in range(10)
    ]
    return {"table": table, "my_projection": {"expected_points": float(base), "xi": []}}


def rounds():
    return {r: {n: 30 + 2 * i + r for i, n in enumerate(NAMES)} for r in (9, 10, 11, 12)}


class Log(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def test_writes_next_jornada_and_keeps_newest_photo(self):
        a = freeze_forecast(race(), rounds(), kickoff=KICK, photo_at="2026-11-12T10:00:00+00:00", now=NOW, conn=self.db)
        self.assertTrue(a["wrote"])
        self.assertEqual(a["jornada"], 13)
        old = freeze_forecast(race(), rounds(), kickoff=KICK, photo_at="2026-11-12T09:00:00+00:00", now=NOW, conn=self.db)
        self.assertFalse(old["wrote"])
        new = freeze_forecast(race(), rounds(), kickoff=KICK, photo_at="2026-11-12T11:00:00+00:00", now=NOW, conn=self.db)
        self.assertTrue(new["wrote"])

    def test_frozen_after_kickoff(self):
        late = NOW + timedelta(days=9)
        r = freeze_forecast(race(), rounds(), kickoff=KICK, photo_at="2026-11-20T10:00:00+00:00", now=late, conn=self.db)
        self.assertFalse(r["wrote"])

    def test_evaluar_compares_with_actual(self):
        freeze_forecast(race(), rounds(), kickoff=KICK, photo_at="2026-11-12T10:00:00+00:00", now=NOW, conn=self.db)
        real = rounds()
        real[13] = {n: 30 + 2 * i for i, n in enumerate(NAMES)}  # m9 mejor, m0 peor
        out = evaluar(real, conn=self.db)
        self.assertEqual(out["n"], 10)
        self.assertIsNotNone(out["brier"])
        self.assertEqual(out["jornadas"][0]["corte_real"], 42)
        self.assertIsInstance(out["gana_a_la_tasa_base"], bool)

    def test_sin_previsiones_no_rompe(self):
        out = evaluar(rounds(), conn=self.db)
        self.assertEqual(out["n"], 0)
        self.assertIsNone(out["brier"])


if __name__ == "__main__":
    unittest.main()

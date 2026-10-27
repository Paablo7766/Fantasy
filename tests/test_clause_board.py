"""Tablero completo de cláusulas: sin filtro de regla de oro y con diff fechado.

Lo que se protege aquí:

1. **Cobertura.** ``/api/squads`` solo publica las cláusulas que cumplen la
   regla de oro (A/B). El tablero tiene que devolver **todas**: si vuelve a
   filtrar, el usuario sigue a ciegas antes de un desbloqueo.
2. **Diff honesto.** Una subida solo se marca si hay dos lecturas comparables.
   Sin histórico, ``prev_clause_eur`` queda vacío: no se estima la cláusula
   base ni se inventa una subida.
3. **Foto vieja.** El diff se fecha contra el día de la foto, no contra el
   reloj: servir una foto de ayer no puede marcar subidas de hoy.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from toolbox.clause_board import build_clause_board, clause_cost_eur


def _player(
    player_id: str,
    *,
    clause: int,
    value: int | None = None,
    average: float | None = None,
    lock: dict | None = None,
    shielded: bool = False,
) -> dict:
    row: dict = {
        "player_id": player_id,
        "name": f"Jugador {player_id}",
        "nickname": f"Nick {player_id}",
        "position": "MC",
        "club": "Club",
        "buyout_clause": clause,
        "is_shielded": shielded,
    }
    if value is not None:
        row["market_value"] = value
    if average is not None:
        row["average_points"] = average
    if lock is not None:
        row["clause_lock"] = lock
    return row


def _lock(day: str, clock: str = "14:08") -> dict:
    return {
        "present": True,
        "is_locked": True,
        "local_date": day,
        "local_time": clock,
        "local_clock": f"{clock}:00",
        "expires_at": f"{day}T{clock}:00+02:00",
        "timezone": "Europe/Madrid",
    }


def _squads(*squads: dict) -> dict:
    return {"ok": True, "league_id": "liga-1", "squads": list(squads)}


def _squad(team_id: str, players: list[dict], *, self_team: bool = False, name: str | None = None) -> dict:
    return {
        "team_id": team_id,
        "is_self": self_team,
        "manager_name": name or f"Manager {team_id}",
        "fantasy_team_name": f"Equipo {team_id}",
        "players": players,
    }


class _Store:
    """Caché temporal con el histórico de cláusulas y el log de gasto oculto."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="clause-board-"))
        self.snapshots = self.dir / "clause_snapshot_history.json"
        self.expenses = self.dir / "hidden_expenses_log.json"

    def write_snapshots(self, days: dict[str, dict]) -> None:
        self.snapshots.write_text(json.dumps({"version": 1, "days": days}), encoding="utf-8")

    def write_expenses(self, entries: list[dict]) -> None:
        self.expenses.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")

    def build(self, squads: dict, *, photo_day: str | None = None) -> dict:
        return build_clause_board(
            squads,
            photo_day=photo_day,
            snapshot_path=self.snapshots,
            expenses_path=self.expenses,
        )


class ClauseBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _Store()

    def test_returns_every_clause_not_only_the_golden_rule_ones(self) -> None:
        """Un jugador caro o sin media también aparece: el tablero no filtra."""
        squads = _squads(
            _squad(
                "rival",
                [
                    # Cumple la regla A.
                    _player("bargain", clause=8_000_000, value=5_000_000, average=4.5, lock=_lock("2026-10-27")),
                    # Cláusula diez veces el valor: fuera de regla, pero visible.
                    _player("expensive", clause=20_000_000, value=2_000_000, average=8.0, lock=_lock("2026-10-27")),
                    # Sin media: no se puede evaluar la regla de oro.
                    _player("unknown", clause=3_000_000, value=1_000_000, lock=_lock("2026-10-28")),
                ],
            )
        )
        document = self.store.build(squads)

        self.assertTrue(document["ok"])
        names = [row["player_id"] for row in document["rows"]]
        # Mismo minuto de desbloqueo: manda la cláusula más alta primero.
        self.assertEqual(names, ["expensive", "bargain", "unknown"])
        self.assertEqual(document["counts"]["total"], 3)
        self.assertEqual(document["counts"]["golden"], 1)
        rules = {row["player_id"]: row["clause_rule"] for row in document["rows"]}
        self.assertEqual(rules["bargain"], "A")
        self.assertIsNone(rules["expensive"])
        self.assertIsNone(rules["unknown"])

    def test_rows_are_sorted_by_unlock_time(self) -> None:
        squads = _squads(
            _squad(
                "rival",
                [
                    _player("later", clause=5_000_000, lock=_lock("2026-10-28", "09:00")),
                    _player("earlier", clause=2_000_000, lock=_lock("2026-10-27", "14:08")),
                    _player("no-hour", clause=9_000_000),
                ],
            )
        )
        document = self.store.build(squads)
        self.assertEqual([row["player_id"] for row in document["rows"]], ["earlier", "later", "no-hour"])

    def test_raise_is_detected_against_the_previous_day(self) -> None:
        self.store.write_snapshots({"2026-10-24": {"rival": {"p1": 10_000_000, "p2": 4_000_000}}})
        squads = _squads(
            _squad(
                "rival",
                [
                    _player("p1", clause=12_000_000, lock=_lock("2026-10-27")),
                    _player("p2", clause=4_000_000, lock=_lock("2026-10-27")),
                ],
            )
        )
        document = self.store.build(squads, photo_day="2026-10-25")

        self.assertEqual(document["from_day"], "2026-10-24")
        rows = {row["player_id"]: row for row in document["rows"]}
        raised = rows["p1"]
        self.assertTrue(raised["raised_today"])
        self.assertEqual(raised["prev_clause_eur"], 10_000_000)
        self.assertEqual(raised["clause_delta_eur"], 2_000_000)
        self.assertEqual(raised["clause_delta_pct"], 0.2)
        self.assertEqual(raised["raise_count"], 1)
        # La mitad del incremento, redondeando al alza: 2 M → 1 M.
        self.assertEqual(raised["raises"][0]["cost_eur"], 1_000_000)
        self.assertFalse(rows["p2"]["raised_today"])
        self.assertEqual(document["counts"]["raised_today"], 1)

    def test_equal_clause_is_not_a_raise(self) -> None:
        self.store.write_snapshots({"2026-10-24": {"rival": {"p1": 10_000_000}}})
        squads = _squads(_squad("rival", [_player("p1", clause=10_000_000, lock=_lock("2026-10-27"))]))
        document = self.store.build(squads, photo_day="2026-10-25")
        row = document["rows"][0]
        self.assertFalse(row["raised_today"])
        self.assertIsNone(row["clause_delta_eur"])
        self.assertEqual(row["prev_clause_eur"], 10_000_000)

    def test_without_history_there_is_no_previous_clause(self) -> None:
        """Sin histórico no se estima base ni se marca subida: el campo queda vacío."""
        squads = _squads(_squad("rival", [_player("p1", clause=10_000_000, lock=_lock("2026-10-27"))]))
        document = self.store.build(squads, photo_day="2026-10-25")
        self.assertIsNone(document["from_day"])
        row = document["rows"][0]
        self.assertIsNone(row["prev_clause_eur"])
        self.assertIsNone(row["clause_delta_eur"])
        self.assertFalse(row["raised_today"])
        self.assertEqual(document["counts"]["raised_ever"], 0)

    def test_stale_photo_does_not_borrow_todays_diff(self) -> None:
        """Una foto del 24 no se compara con el snapshot del 24: sería el mismo día."""
        self.store.write_snapshots({"2026-10-24": {"rival": {"p1": 10_000_000}}})
        squads = _squads(_squad("rival", [_player("p1", clause=12_000_000, lock=_lock("2026-10-27"))]))
        document = self.store.build(squads, photo_day="2026-10-24")
        self.assertIsNone(document["from_day"])
        self.assertFalse(document["rows"][0]["raised_today"])

        # Con la foto al día siguiente sí hay diff contra el 24.
        self.assertEqual(self.store.build(squads, photo_day="2026-10-25")["from_day"], "2026-10-24")

    def test_historical_raises_come_from_the_expense_log(self) -> None:
        """Una subida de un jugador que ya no está sigue fechada en su fila."""
        self.store.write_snapshots({"2026-10-20": {"rival": {"p1": 5_000_000}}})
        self.store.write_expenses(
            [
                {
                    "team_id": "rival",
                    "player_id": "p1",
                    "day": "2026-10-21",
                    "clause_before_eur": 5_000_000,
                    "clause_after_eur": 9_000_000,
                }
            ]
        )
        squads = _squads(_squad("rival", [_player("p1", clause=9_000_000, lock=_lock("2026-10-27"))]))
        document = self.store.build(squads, photo_day="2026-10-25")
        row = document["rows"][0]
        self.assertFalse(row["raised_today"])
        self.assertEqual(row["raise_count"], 1)
        self.assertEqual(row["raise_latest_day"], "2026-10-21")
        self.assertEqual(row["raise_latest_eur"], 4_000_000)
        self.assertEqual(document["counts"]["raised_ever"], 1)

    def test_todays_raise_is_labelled_even_without_the_expense_log(self) -> None:
        """``/api/clause-board`` no escribe el log: el diff se marca en la fila."""
        self.store.write_snapshots({"2026-10-24": {"rival": {"p1": 5_000_000}}})
        squads = _squads(_squad("rival", [_player("p1", clause=6_000_000, lock=_lock("2026-10-27"))]))
        document = self.store.build(squads, photo_day="2026-10-25")
        latest = document["rows"][0]["raises"][0]
        self.assertEqual(latest["day"], "2026-10-25")
        self.assertEqual(latest["source"], "diff_hoy")
        self.assertEqual(latest["increase_eur"], 1_000_000)
        self.assertEqual(latest["cost_eur"], 500_000)

    def test_self_squad_is_excluded_by_default(self) -> None:
        squads = _squads(
            _squad("mine", [_player("own-1", clause=4_000_000, lock=_lock("2026-10-27"))], self_team=True),
            _squad("rival", [_player("p1", clause=9_000_000, lock=_lock("2026-10-27"))]),
        )
        document = self.store.build(squads)
        self.assertEqual([row["player_id"] for row in document["rows"]], ["p1"])

        everything = build_clause_board(squads, include_self=True)
        self.assertEqual({row["player_id"] for row in everything["rows"]}, {"own-1", "p1"})

    def test_shielded_players_stay_visible_but_flagged(self) -> None:
        squads = _squads(
            _squad(
                "rival",
                [
                    _player("p1", clause=9_000_000, lock=_lock("2026-10-27"), shielded=True),
                    _player("no-clause", clause=0, lock=_lock("2026-10-27")),
                ],
            )
        )
        document = self.store.build(squads)
        self.assertEqual([row["player_id"] for row in document["rows"]], ["p1"])
        self.assertTrue(document["rows"][0]["is_shielded"])

    def test_empty_roster_is_an_explicit_error(self) -> None:
        document = self.store.build({"ok": True, "squads": []})
        self.assertFalse(document["ok"])
        self.assertEqual(document["error"], "sin_plantillas")
        self.assertEqual(document["rows"], [])

    def test_counts_split_locked_and_open(self) -> None:
        open_lock = dict(_lock("2026-10-20"), is_locked=False)
        squads = _squads(
            _squad(
                "rival",
                [
                    _player("open", clause=1_000_000, lock=open_lock),
                    _player("locked", clause=2_000_000, lock=_lock("2026-10-27")),
                ],
            )
        )
        document = self.store.build(squads)
        self.assertEqual(document["counts"]["locked"], 1)
        self.assertEqual(document["counts"]["open"], 1)
        self.assertFalse(document["rows"][0]["is_locked"])


class ClauseCostTests(unittest.TestCase):
    def test_cost_is_half_the_increase_rounded_up(self) -> None:
        self.assertEqual(clause_cost_eur(2_000_000), 1_000_000)
        self.assertEqual(clause_cost_eur(1), 1)
        self.assertEqual(clause_cost_eur(3), 2)

    def test_non_positive_increase_has_no_cost(self) -> None:
        self.assertIsNone(clause_cost_eur(0))
        self.assertIsNone(clause_cost_eur(-5))
        self.assertIsNone(clause_cost_eur(None))
        self.assertIsNone(clause_cost_eur(True))


if __name__ == "__main__":
    unittest.main()

"""La subida de cláusula puede ser gratis (valor de mercado) o pagada.

La app real fija la cláusula de un jugador **fichado** en ``max(1 M€, precio
pagado, valor de mercado)``. Verificado sobre la liga: 55 de 55 fichajes. Si el
valor sube, la cláusula sube sola y el rival no paga. Llamar «subida» a ese
movimiento haría creer al usuario que el rival se está blindando cuando solo
está el mercado tirando del precio.

Lo que se protege aquí:

1. **Fichaje:** ``clause_auto_raise_eur`` recoge el tramo gratis y
   ``clause_paid_raise_eur`` lo que el rival puso de su caja. Solo el segundo
   cuenta como subida pagada.
2. **Reparto:** la cláusula no flota (82 de 82 sin cambios con el valor
   moviéndose), así que cualquier salto es dinero del rival.
3. **Sin libros:** si no hay precio pagado no se inventa el desglose.
"""

from __future__ import annotations

import unittest

from toolbox.clause_board import build_clause_board


def _player(player_id: str, *, clause: int, value: int) -> dict:
    return {
        "player_id": player_id,
        "name": f"Jugador {player_id}",
        "nickname": f"Nick {player_id}",
        "position": "MC",
        "club": "Club",
        "buyout_clause": clause,
        "market_value": value,
    }


def _squads(*players: dict) -> dict:
    return {
        "ok": True,
        "league_id": "liga-1",
        "squads": [
            {
                "team_id": "rival",
                "is_self": False,
                "manager_name": "Rival",
                "players": list(players),
            }
        ],
    }


def _ledgers(entries: list[tuple[str, int]]) -> list[dict]:
    """Libros mínimos: una compra por jugador, con su precio."""
    return [
        {
            "team_id": "rival",
            "events": [
                {"kind": "buy", "player_id": player_id, "amount_eur": amount}
                for player_id, amount in entries
            ],
        }
    ]


class PaidRaiseTests(unittest.TestCase):
    def test_market_value_lift_on_a_signing_is_free(self) -> None:
        """Fichado a 10 M€ que vale 14 M€: la cláusula sube 4 M€ sin coste."""
        squads = _squads(_player("p1", clause=14_000_000, value=14_000_000))
        document = build_clause_board(squads, ledgers=_ledgers([("p1", 10_000_000)]))
        row = document["rows"][0]

        self.assertEqual(row["clause_paid_eur"], 10_000_000)
        self.assertEqual(row["clause_floor_eur"], 10_000_000)
        self.assertEqual(row["clause_auto_raise_eur"], 4_000_000)
        self.assertEqual(row["clause_paid_raise_eur"], 0)
        self.assertFalse(row["clause_paid_by_rival"])
        self.assertEqual(document["counts"]["paid_raise"], 0)
        self.assertEqual(document["counts"]["auto_raise"], 1)

    def test_clause_above_the_value_ceiling_was_paid(self) -> None:
        """Cláusula 20 M€ sobre un fichado de 10 M€ que vale 14 M€."""
        squads = _squads(_player("p1", clause=20_000_000, value=14_000_000))
        row = build_clause_board(squads, ledgers=_ledgers([("p1", 10_000_000)]))["rows"][0]

        self.assertEqual(row["clause_auto_raise_eur"], 4_000_000)
        self.assertEqual(row["clause_paid_raise_eur"], 6_000_000)
        self.assertTrue(row["clause_paid_by_rival"])

    def test_floor_is_the_million_when_the_price_is_lower(self) -> None:
        """Fichado por 600 k: el suelo es 1 M€, no el precio."""
        squads = _squads(_player("p1", clause=1_000_000, value=600_000))
        row = build_clause_board(squads, ledgers=_ledgers([("p1", 600_000)]))["rows"][0]

        self.assertEqual(row["clause_floor_eur"], 1_000_000)
        self.assertEqual(row["clause_auto_raise_eur"], 0)
        self.assertEqual(row["clause_paid_raise_eur"], 0)

    def test_value_below_the_price_does_not_shrink_the_clause(self) -> None:
        """Fichado por 30 M€ que hoy vale 20 M€: la cláusula se queda en 30."""
        squads = _squads(_player("p1", clause=30_000_000, value=20_000_000))
        row = build_clause_board(squads, ledgers=_ledgers([("p1", 30_000_000)]))["rows"][0]

        self.assertEqual(row["clause_auto_raise_eur"], 0)
        self.assertEqual(row["clause_paid_raise_eur"], 0)
        self.assertFalse(row["clause_paid_by_rival"])

    def test_a_reparto_player_never_floats_with_the_market(self) -> None:
        """Sin precio pagado no hay tramo gratis: cualquier salto es del rival."""
        squads = _squads(_player("p1", clause=18_000_000, value=12_000_000))
        row = build_clause_board(squads)["rows"][0]

        self.assertIsNone(row["clause_paid_eur"])
        self.assertIsNone(row["clause_floor_eur"])
        self.assertEqual(row["clause_auto_raise_eur"], 0)
        self.assertEqual(row["clause_paid_raise_eur"], 0)

    def test_reparto_raise_against_the_photo_counts_as_paid(self) -> None:
        """Con foto previa, el salto de un reparto es dinero puesto por el rival."""
        import json
        import tempfile
        from pathlib import Path

        folder = Path(tempfile.mkdtemp(prefix="clause-paid-"))
        snapshots = folder / "snap.json"
        snapshots.write_text(
            json.dumps({"version": 1, "days": {"2026-10-24": {"rival": {"p1": 12_000_000}}}}),
            encoding="utf-8",
        )
        squads = _squads(_player("p1", clause=18_000_000, value=12_000_000))
        document = build_clause_board(
            squads,
            photo_day="2026-10-25",
            snapshot_path=snapshots,
            expenses_path=folder / "none.json",
        )
        row = document["rows"][0]

        self.assertEqual(row["clause_auto_raise_eur"], 0)
        self.assertEqual(row["clause_paid_raise_eur"], 6_000_000)
        self.assertTrue(row["clause_paid_by_rival"])

    def test_without_books_the_split_is_not_invented(self) -> None:
        squads = _squads(_player("p1", clause=14_000_000, value=14_000_000))
        row = build_clause_board(squads)["rows"][0]

        self.assertIsNone(row["clause_paid_eur"])
        self.assertEqual(row["clause_auto_raise_eur"], 0)
        self.assertEqual(row["clause_paid_raise_eur"], 0)


if __name__ == "__main__":
    unittest.main()

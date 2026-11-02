"""Poisson propio a cuatro jornadas: calendario de Understat, xP por partido y su uso."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.engine.comparador_liga import calendario_combinado, xp_4_jornadas, xp_jornadas_siguientes
from toolbox.own_intel import apply_own_intel
from toolbox.understat import FixtureInfo, TeamStrength, next_fixtures


def _partido(home: tuple[str, str], away: tuple[str, str], kickoff: datetime) -> dict:
    return {
        "isResult": False,
        "datetime": kickoff.strftime("%Y-%m-%d %H:%M:%S"),
        "h": {"id": home[0], "title": home[1]},
        "a": {"id": away[0], "title": away[1]},
    }


STRENGTHS = {
    "real madrid": TeamStrength("1", "Real Madrid", 2.0, 0.8, 10),
    "sevilla": TeamStrength("2", "Sevilla", 1.1, 1.5, 10),
    "barcelona": TeamStrength("3", "Barcelona", 2.1, 0.9, 10),
    "getafe": TeamStrength("4", "Getafe", 0.9, 1.0, 10),
    "elche": TeamStrength("5", "Elche", 0.8, 1.8, 10),
}
MADRID = ("1", "Real Madrid")


class CalendarioUnderstatTests(unittest.TestCase):
    def test_cada_club_lleva_sus_tres_partidos_siguientes(self) -> None:
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        rivales = [("2", "Sevilla"), ("3", "Barcelona"), ("4", "Getafe"), ("5", "Elche"), ("2", "Sevilla")]
        dates = [
            _partido(MADRID if index % 2 == 0 else rival, rival if index % 2 == 0 else MADRID, now + timedelta(days=3 + 7 * index))
            for index, rival in enumerate(rivales)
        ]
        fixtures = next_fixtures(dates, STRENGTHS, now=now)
        madrid = fixtures["real madrid"]
        self.assertEqual(madrid.opponent, "Sevilla")
        self.assertTrue(madrid.home)
        # Tres siguientes, no cuatro: la cuarta posterior queda fuera.
        self.assertEqual([f.opponent for f in madrid.siguientes], ["Barcelona", "Getafe", "Elche"])
        self.assertEqual([f.home for f in madrid.siguientes], [False, True, False])
        # Los siguientes no anidan otra ventana.
        self.assertEqual(madrid.siguientes[0].siguientes, ())


class XpPorPartidoTests(unittest.TestCase):
    def _fixture(self, opponent: str, opponent_id: str, days: int, siguientes=()) -> FixtureInfo:
        return FixtureInfo(
            opponent=opponent,
            opponent_id=opponent_id,
            home=True,
            kickoff=(datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
            fdr=3,
            opponent_xga=None,
            opponent_xg=None,
            siguientes=tuple(siguientes),
        )

    def test_el_modelo_propio_da_xp_y_calendario_de_cuatro_jornadas(self) -> None:
        siguientes = [self._fixture("Barcelona", "3", 10), self._fixture("Elche", "5", 17), self._fixture("Getafe", "4", 24)]
        fixtures = {"real madrid": self._fixture("Sevilla", "2", 3, siguientes)}
        players = [
            {
                "player_id": "p1",
                "club": "Real Madrid",
                "position": "DEL",
                "p_titular": 0.9,
                "form": {"xg": 6.0, "xa": 2.0},
            }
        ]
        apply_own_intel(players, histories={}, fixtures_by_club=fixtures, strengths=STRENGTHS)
        player = players[0]
        self.assertEqual([cell["opponent"] for cell in player["own_calendar"]], ["Sevilla", "Barcelona", "Elche", "Getafe"])
        self.assertEqual([cell["matchday"] for cell in player["own_calendar"]], [0, 1, 2, 3])
        xps = player["own_xp_siguientes"]
        self.assertEqual(len(xps), 3)
        # Un delantero rinde más contra la defensa del Elche que contra la del Barcelona.
        self.assertGreater(xps[1], xps[0])

    def test_el_horizonte_usa_el_xp_propio_antes_que_la_reescala(self) -> None:
        jugador = {
            "jornada": 5.0,
            "own_xp_siguientes": [4.0, 6.0, 5.0],
            "af_calendar": [{"matchday": 1, "difficulty": "muy_facil"}],
        }
        self.assertEqual(xp_jornadas_siguientes(jugador), 15.0)
        self.assertEqual(xp_4_jornadas(jugador), 5.0)

    def test_el_calendario_propio_completo_manda_sobre_af(self) -> None:
        jugador = {
            "own_calendar": [{"matchday": 0, "opponent": "A"}, {"matchday": 1, "opponent": "B"}],
            "af_calendar": [{"matchday": 1, "opponent": "otro"}],
        }
        self.assertEqual([cell["opponent"] for cell in calendario_combinado(jugador)], ["A", "B"])


if __name__ == "__main__":
    unittest.main()

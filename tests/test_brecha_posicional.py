from __future__ import annotations

import unittest

from toolbox.engine.brecha_posicional import brecha_posicional
from toolbox.engine.signing_plan import build_plan_fichajes


def _jugadores(puesto: str, n: int, por_jornada: float, jornadas=(10, 11)) -> list[dict]:
    return [
        {"position": puesto, "week_points_by_round": {str(j): por_jornada for j in jornadas}} for _ in range(n)
    ]


def _plantilla(delantero: float, defensa: float, mc: float = 4.0, portero: float = 4.0) -> list[dict]:
    return [
        *_jugadores("POR", 1, portero),
        *_jugadores("DEF", 4, defensa),
        *_jugadores("MC", 4, mc),
        *_jugadores("DEL", 2, delantero),
    ]


class BrechaPosicionalTest(unittest.TestCase):
    def test_la_brecha_apunta_a_delantera_y_defensa(self) -> None:
        squads = [
            {"is_self": True, "manager_name": "yo", "players": _plantilla(delantero=1.0, defensa=2.0, mc=6.0)},
            {"is_self": False, "manager_name": "PABS FC", "players": _plantilla(delantero=4.0, defensa=3.0, mc=3.0)},
        ]
        brecha = brecha_posicional(squads)
        assert brecha is not None
        self.assertEqual(brecha["rival"], "PABS FC")
        self.assertLess(brecha["diferencia"]["DEL"], brecha["diferencia"]["DEF"])
        self.assertGreater(brecha["diferencia"]["MC"], 0)
        self.assertEqual(brecha["bonus_xp"]["DEL"], 0.3)
        self.assertNotIn("MC", brecha["bonus_xp"])
        self.assertIn("DEL", brecha["texto"])

    def test_si_voy_por_delante_no_hay_bonus(self) -> None:
        squads = [
            {"is_self": True, "players": _plantilla(5.0, 5.0, 5.0)},
            {"is_self": False, "players": _plantilla(1.0, 1.0, 1.0)},
        ]
        brecha = brecha_posicional(squads)
        assert brecha is not None
        self.assertEqual(brecha["bonus_xp"], {})

    def test_sin_datos_devuelve_none(self) -> None:
        self.assertIsNone(brecha_posicional([]))
        self.assertIsNone(brecha_posicional([{"is_self": True, "players": []}]))


def _owned() -> list[dict]:
    filas = []
    for i, p in enumerate(["POR"] + ["DEF"] * 4 + ["MC"] * 4 + ["DEL"] * 2):
        filas.append({"player_id": f"o{i}", "nombre": f"O{i}", "position": p, "jornada": 3.0,
                      "elegible": True, "valor": 10_000_000})
    return filas


class OptimizadorTest(unittest.TestCase):
    def _plan(self, **extra):
        mercado = [
            {"player_id": "mc", "nombre": "Medio", "position": "MC", "jornada": 5.05, "euros": 7_000_000, "valor": 6_500_000},
            {"player_id": "del", "nombre": "Delantero", "position": "DEL", "jornada": 5.0, "euros": 7_000_000, "valor": 6_500_000},
        ]
        return build_plan_fichajes(
            cash=8_000_000, owned=_owned(), mercado=mercado, clausulas=[], ratio=1_000_000.0,
            dias_para_jornada=None, baseline_puntos=33.0, **extra,
        )

    def test_empate_se_decide_a_favor_del_puesto_con_brecha(self) -> None:
        sin = {a["player_id"] for a in self._plan()["acciones"] if a["tipo"] == "PUJA"}
        con = {a["player_id"] for a in self._plan(bonus_posicional={"DEL": 0.3})["acciones"] if a["tipo"] == "PUJA"}
        self.assertEqual(sin, {"mc"})
        self.assertEqual(con, {"del"})


if __name__ == "__main__":
    unittest.main()


class LiderTest(unittest.TestCase):
    def test_el_rival_de_referencia_es_el_primero_de_la_clasificacion(self) -> None:
        squads = [
            {"is_self": True, "players": _plantilla(1.0, 1.0)},
            {"is_self": False, "manager_name": "PABS FC", "points": 201, "players": _plantilla(2.0, 2.0)},
            {"is_self": False, "manager_name": "Otro", "points": 150, "players": _plantilla(9.0, 9.0)},
        ]
        brecha = brecha_posicional(squads)
        assert brecha is not None
        self.assertEqual(brecha["rival"], "PABS FC")

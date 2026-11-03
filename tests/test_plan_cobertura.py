"""Pujas cubiertas en cualquier resultado, tope de deuda del 20 % y sancionado de un partido."""

from __future__ import annotations

import itertools
import unittest
from datetime import datetime, timedelta, timezone

from toolbox.engine.signing_plan import build_plan_fichajes
from toolbox.own_intel import apply_own_intel, jugador_tras_sancion
from toolbox.understat import FixtureInfo, TeamStrength


def _jugador(player_id: str, position: str, jornada: float, **extra: object) -> dict:
    row = {"player_id": player_id, "nombre": player_id, "position": position, "jornada": jornada, "elegible": True}
    row.update(extra)
    return row


def _once(puntos: float = 5.0, **extra: object) -> list[dict]:
    return [
        _jugador(f"{position}-{index}", position, puntos, **extra)
        for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3))
        for index in range(count)
    ]


def _por_id(rows: list[dict], player_id: str) -> dict:
    return next(row for row in rows if row["player_id"] == player_id)


class CoberturaPujasTests(unittest.TestCase):
    def _assert_cualquier_resultado_cubre(self, plan: dict) -> None:
        cobertura = plan["cobertura_pujas"]
        pujas = cobertura["pujas"]
        self.assertLessEqual(sum(item["caja"] for item in pujas), cobertura["caja_al_pujar"])
        for size in range(len(pujas) + 1):
            for ganadas in itertools.combinations(pujas, size):
                saldo =cobertura["caja_al_pujar"] + sum(
                    sum(venta["euros"] for venta in item["ventas"]) - item["euros"] for item in ganadas
                )
                self.assertGreaterEqual(saldo, 0, f"ganando {[item['player_id'] for item in ganadas]}")

    def test_ganar_solo_la_puja_cara_no_deja_saldo_negativo(self) -> None:
        # Emparejar por puesto ataba la venta de 3 M (DEL) a la puja de 10 M (DEL)
        # y la de 9 M (DEF) a la de 2 M: ganar solo la cara dejaba -7 M.
        owned = _once(5.0)
        _por_id(owned, "DEL-2").update(jornada=1.0, venta_eur=3_000_000)
        _por_id(owned, "DEF-3").update(jornada=1.0, venta_eur=9_000_000)
        owned.append(_jugador("MC-banca", "MC", 3.0))
        mercado = [
            _jugador("grande", "DEL", 9.0, euros=10_000_000),
            _jugador("chico", "DEF", 7.0, euros=2_000_000),
        ]
        plan = build_plan_fichajes(
            cash=2_000_000,
            owned=owned,
            mercado=mercado,
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=1.5,
            baseline_puntos=5.0 * 9 + 2.0,
        )
        pujas = {item["player_id"] for item in plan["cobertura_pujas"]["pujas"]}
        self.assertEqual(pujas, {"grande", "chico"})
        self._assert_cualquier_resultado_cubre(plan)
        grande = next(item for item in plan["cobertura_pujas"]["pujas"] if item["player_id"] == "grande")
        self.assertGreaterEqual(sum(venta["euros"] for venta in grande["ventas"]) + grande["caja"], 10_000_000)

    def test_perder_todas_las_pujas_deja_once_completo(self) -> None:
        owned = _once(5.0)
        _por_id(owned, "DEL-2").update(jornada=1.0, venta_eur=6_000_000)
        _por_id(owned, "DEL-1").update(jornada=1.0, venta_eur=6_000_000)
        mercado = [_jugador("estrella", "DEL", 12.0, euros=11_000_000)]
        plan = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=mercado,
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=1.5,
            baseline_puntos=5.0 * 9 + 2.0,
        )
        # Con 11 jugadores no se pueden atar dos ventas a una puja: si se gana
        # quedan 10. La puja no entra.
        self.assertNotIn("estrella", {item["player_id"] for item in (plan.get("cobertura_pujas") or {}).get("pujas", [])})
        self.assertFalse(any(accion["tipo"] in {"VENDE", "VENDER HOY"} for accion in plan["acciones"]))


class TopeDeudaTests(unittest.TestCase):
    def _plan(self, con_valor: bool) -> dict:
        extra = {"valor": 5_000_000} if con_valor else {}
        owned = _once(5.0, **extra)
        _por_id(owned, "DEL-2").update(jornada=1.0, venta_eur=16_000_000, valor=16_000_000)
        return build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=[_jugador("crack", "DEL", 12.0, euros=15_000_000)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=1.5,
            baseline_puntos=5.0 * 10 + 1.0,
        )

    def test_puja_que_pasa_del_20_por_ciento_no_entra(self) -> None:
        # Valor del equipo 66 M: tope 13,2 M. Pujar 15 M con 0 en caja es 15 M de deuda.
        plan = self._plan(con_valor=True)
        self.assertFalse(any(accion["tipo"] == "PUJA" for accion in plan["acciones"]))

    def test_sin_valor_de_plantilla_no_se_aplica(self) -> None:
        plan = self._plan(con_valor=False)
        self.assertTrue(any(accion["tipo"] == "PUJA" and accion["player_id"] == "crack" for accion in plan["acciones"]))
        self.assertIsNone(plan["cobertura_pujas"]["tope_deuda"])

    def test_la_deuda_al_pujar_respeta_el_tope(self) -> None:
        owned = _once(5.0, valor=10_000_000)
        _por_id(owned, "DEL-2").update(jornada=1.0, venta_eur=10_000_000)
        plan = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=[_jugador("crack", "DEL", 12.0, euros=9_000_000)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=1.5,
            baseline_puntos=5.0 * 10 + 1.0,
        )
        cobertura = plan["cobertura_pujas"]
        self.assertEqual(cobertura["tope_deuda"], 22_000_000)
        self.assertLessEqual(cobertura["deuda_al_pujar"], cobertura["tope_deuda"])


class SancionadoTests(unittest.TestCase):
    def test_sancionado_de_un_partido_no_se_vende(self) -> None:
        owned = _once(5.0)
        owned.append(
            _jugador(
                "sancionado",
                "DEL",
                0.0,
                elegible=False,
                futuro=27.0,
                p_titular=0.0,
                sancion_temporal=True,
                venta_eur=20_000_000,
            )
        )
        plan = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=[_jugador("sustituto", "DEL", 7.0, euros=15_000_000, futuro=21.0)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=1.5,
            baseline_puntos=55.0,
        )
        self.assertFalse(any(accion.get("player_id") == "sancionado" for accion in plan["acciones"] if accion["tipo"] in {"VENDE", "VENDER HOY"}))

    def test_lesionado_sin_futuro_si_se_vende(self) -> None:
        owned = _once(5.0)
        owned.append(_jugador("lesionado", "DEL", 0.0, elegible=False, p_titular=0.0, venta_eur=20_000_000))
        plan = build_plan_fichajes(
            cash=0,
            owned=owned,
            mercado=[_jugador("sustituto", "DEL", 7.0, euros=15_000_000, futuro=21.0)],
            clausulas=[],
            ratio=2_000_000,
            dias_para_jornada=1.5,
            baseline_puntos=55.0,
        )
        self.assertTrue(any(accion.get("player_id") == "lesionado" for accion in plan["acciones"] if accion["tipo"] in {"VENDE", "VENDER HOY"}))


STRENGTHS = {
    "real madrid": TeamStrength("1", "Real Madrid", 2.0, 0.8, 10),
    "sevilla": TeamStrength("2", "Sevilla", 1.1, 1.5, 10),
    "barcelona": TeamStrength("3", "Barcelona", 2.1, 0.9, 10),
    "getafe": TeamStrength("4", "Getafe", 0.9, 1.0, 10),
    "elche": TeamStrength("5", "Elche", 0.8, 1.8, 10),
}


def _fixture(opponent: str, opponent_id: str, days: int, siguientes=()) -> FixtureInfo:
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


class SancionOwnIntelTests(unittest.TestCase):
    def _sancionado(self, **extra: object) -> dict:
        player = {
            "player_id": "p1",
            "club": "Real Madrid",
            "position": "DEL",
            "p_titular": 0.0,
            "player_status": "suspended",
            "sanction": {"suspended": True},
            "week_points": [6, 7, 8, 9, 7],
            "form": {"xg": 6.0, "xa": 2.0},
        }
        player.update(extra)
        return player

    def test_sancion_sin_lesion_recupera_su_titularidad(self) -> None:
        resultado = jugador_tras_sancion(self._sancionado())
        self.assertIsNotNone(resultado)
        limpio, p_titular, partidos = resultado
        self.assertEqual(partidos, 1)
        self.assertGreater(p_titular, 0.5)
        self.assertFalse(limpio["sanction"]["suspended"])

    def test_lee_los_partidos_de_sancion_del_parte(self) -> None:
        resultado = jugador_tras_sancion(self._sancionado(fitness_detail="Sancionado 2 partidos por roja directa"))
        self.assertEqual(resultado[2], 2)

    def test_una_lesion_no_es_sancion_temporal(self) -> None:
        self.assertIsNone(jugador_tras_sancion(self._sancionado(af_injury={"status": "injured"})))
        self.assertIsNone(jugador_tras_sancion({"player_id": "p2", "p_titular": 0.9}))

    def test_j1_vale_cero_y_j2_j4_no(self) -> None:
        siguientes = [_fixture("Barcelona", "3", 10), _fixture("Elche", "5", 17), _fixture("Getafe", "4", 24)]
        fixtures = {"real madrid": _fixture("Sevilla", "2", 3, siguientes)}
        players = [self._sancionado()]
        apply_own_intel(players, histories={}, fixtures_by_club=fixtures, strengths=STRENGTHS)
        player = players[0]
        self.assertEqual(player["own_expected_points"], 0.0)
        self.assertEqual(player["own_sancion_partidos"], 1)
        self.assertEqual(len(player["own_xp_siguientes"]), 3)
        self.assertTrue(all(value > 2.0 for value in player["own_xp_siguientes"]))

    def test_sancion_de_dos_partidos_anula_tambien_j2(self) -> None:
        siguientes = [_fixture("Barcelona", "3", 10), _fixture("Elche", "5", 17), _fixture("Getafe", "4", 24)]
        fixtures = {"real madrid": _fixture("Sevilla", "2", 3, siguientes)}
        players = [self._sancionado(fitness_detail="2 partidos de sanción")]
        apply_own_intel(players, histories={}, fixtures_by_club=fixtures, strengths=STRENGTHS)
        xps = players[0]["own_xp_siguientes"]
        self.assertEqual(xps[0], 0.0)
        self.assertGreater(xps[1], 2.0)


if __name__ == "__main__":
    unittest.main()

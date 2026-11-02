"""Plan estable: prima por seguir con los objetivos de ayer, umbral para cambiar y memoria."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from toolbox.engine.signing_plan import CONTINUIDAD_XP, UMBRAL_CAMBIO_XP, build_plan_fichajes
from toolbox.league_history import collect_activity_buys
from toolbox.plan_memory import load_objetivos_previos, plan_stability, save_plan


def _jugador(player_id: str, position: str, jornada: float, **extra: object) -> dict:
    row = {
        "player_id": player_id,
        "nombre": player_id,
        "position": position,
        "jornada": jornada,
        "elegible": True,
    }
    row.update(extra)
    return row


def _once(puntos: float = 5.0) -> list[dict]:
    plantilla = []
    for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
        for index in range(count):
            plantilla.append(_jugador(f"{position}-{index}", position, puntos))
    return plantilla


def _viernes(mercado: list[dict], previos: list[str] | None = None) -> dict:
    # Viernes: sin peaje de liquidez, solo cuentan los puntos.
    return build_plan_fichajes(
        cash=3_000_000,
        owned=_once(5.0),
        mercado=mercado,
        clausulas=[],
        ratio=2_000_000,
        dias_para_jornada=0,
        baseline_puntos=5.0 * 11,
        objetivos_previos=previos,
    )


def _pujas(plan: dict) -> list[str]:
    return [accion["player_id"] for accion in plan["acciones"] if accion["tipo"] == "PUJA"]


class ContinuidadTests(unittest.TestCase):
    def test_sin_memoria_gana_el_de_mas_puntos(self) -> None:
        mercado = [
            _jugador("ayer", "DEL", 5.8, euros=3_000_000),
            _jugador("nuevo", "DEL", 6.0, euros=3_000_000),
        ]
        self.assertEqual(_pujas(_viernes(mercado)), ["nuevo"])

    def test_un_empate_de_decimas_no_desplaza_el_objetivo_de_ayer(self) -> None:
        mercado = [
            _jugador("ayer", "DEL", 5.8, euros=3_000_000),
            _jugador("nuevo", "DEL", 6.0, euros=3_000_000),
        ]
        plan = _viernes(mercado, previos=["ayer"])
        self.assertEqual(_pujas(plan), ["ayer"])
        self.assertTrue(plan["acciones"][0]["sigue_plan"])
        self.assertEqual(plan["objetivos_previos"], ["ayer"])

    def test_un_objetivo_claramente_mejor_si_lo_desplaza(self) -> None:
        mercado = [
            _jugador("ayer", "DEL", 5.3, euros=3_000_000),
            _jugador("nuevo", "DEL", 5.3 + CONTINUIDAD_XP + 0.5, euros=3_000_000),
        ]
        plan = _viernes(mercado, previos=["ayer"])
        self.assertEqual(_pujas(plan), ["nuevo"])
        self.assertFalse(plan["acciones"][0]["sigue_plan"])

    def test_una_mejora_pequena_no_abre_un_plan_nuevo(self) -> None:
        mercado = [_jugador("justo", "DEL", 5.0 + UMBRAL_CAMBIO_XP - 0.2, euros=3_000_000)]
        plan = _viernes(mercado)
        self.assertEqual(plan["acciones"], [])

    def test_la_misma_mejora_basta_para_seguir_con_el_plan_de_ayer(self) -> None:
        mercado = [_jugador("justo", "DEL", 5.0 + UMBRAL_CAMBIO_XP - 0.2, euros=3_000_000)]
        plan = _viernes(mercado, previos=["justo"])
        self.assertEqual(_pujas(plan), ["justo"])
        self.assertEqual(plan["umbral_cambio_xp"], 0.1)


class HorizonteTests(unittest.TestCase):
    def test_a_igual_jornada_gana_el_de_mejor_calendario(self) -> None:
        mercado = [
            _jugador("duro", "DEL", 6.0, euros=3_000_000, futuro=12.0),
            _jugador("blando", "DEL", 6.0, euros=3_000_000, futuro=18.0),
        ]
        plan = _viernes(mercado)
        self.assertEqual(_pujas(plan), ["blando"])

    def test_el_calendario_compensa_una_jornada_algo_peor(self) -> None:
        mercado = [
            _jugador("hoy", "DEL", 6.2, euros=3_000_000, futuro=12.0),
            _jugador("despues", "DEL", 5.8, euros=3_000_000, futuro=18.0),
        ]
        plan = _viernes(mercado)
        self.assertEqual(_pujas(plan), ["despues"])
        self.assertGreater(plan["mejora_horizonte"], plan["mejora_puntos_jornada"])

    def test_las_tres_siguientes_se_reescalan_por_dificultad(self) -> None:
        from toolbox.engine.comparador_liga import xp_jornadas_siguientes

        calendario = [{"difficulty": "media"}, {"difficulty": "facil"}, {"difficulty": "dificil"}, {"difficulty": "media"}]
        self.assertAlmostEqual(xp_jornadas_siguientes({"jornada": 5.0, "calendario": calendario}), 5.3 + 4.6 + 5.0)
        self.assertIsNone(xp_jornadas_siguientes({"jornada": 5.0, "calendario": calendario[:1]}))


class CalendarioCombinadoTests(unittest.TestCase):
    def test_el_propio_da_la_proxima_y_af_las_siguientes(self) -> None:
        from toolbox.engine.comparador_liga import calendario_combinado

        jugador = {
            "own_calendar": [{"matchday": 0, "opponent": "Getafe"}],
            "af_calendar": [{"matchday": 2, "opponent": "Espanyol"}, {"matchday": 1, "opponent": "Real Madrid"}],
        }
        rivales = [cell["opponent"] for cell in calendario_combinado(jugador)]
        self.assertEqual(rivales, ["Getafe", "Real Madrid", "Espanyol"])

    def test_sin_celda_propia_af_no_se_toma_por_la_proxima(self) -> None:
        from toolbox.engine.comparador_liga import calendario_combinado

        jugador = {"af_calendar": [{"matchday": 1, "opponent": "Real Madrid", "difficulty": "very_hard"}]}
        calendario = calendario_combinado(jugador)
        self.assertEqual(calendario[0], {"difficulty": "media"})
        self.assertEqual(calendario[1]["opponent"], "Real Madrid")


class MemoriaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "responses.sqlite"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _plan(self, *ids: str) -> dict:
        return {
            "mejora_puntos_jornada": 1.0,
            "acciones": [{"tipo": "PUJA", "player_id": player_id} for player_id in ids]
            + [{"tipo": "ESCAPARATE", "player_id": "vendo"}],
        }

    def test_el_plan_de_ayer_vuelve_y_el_de_hoy_no(self) -> None:
        save_plan("L", self._plan("a", "b"), day="2026-11-02", db_path=self.db)
        self.assertEqual(load_objetivos_previos("L", day="2026-11-03", db_path=self.db), ["a", "b"])
        # El plan de hoy no se premia a sí mismo en cada recarga.
        self.assertEqual(load_objetivos_previos("L", day="2026-11-02", db_path=self.db), [])

    def test_un_plan_viejo_caduca(self) -> None:
        save_plan("L", self._plan("a"), day="2026-10-20", db_path=self.db)
        self.assertEqual(load_objetivos_previos("L", day="2026-11-02", db_path=self.db), [])

    def test_cada_liga_tiene_su_memoria(self) -> None:
        save_plan("L", self._plan("a"), day="2026-11-02", db_path=self.db)
        self.assertEqual(load_objetivos_previos("otra", day="2026-11-03", db_path=self.db), [])

    def test_la_estabilidad_mide_cuanto_cambia_el_plan(self) -> None:
        save_plan("L", self._plan("a", "b"), day="2026-11-01", db_path=self.db)
        save_plan("L", self._plan("a", "b"), day="2026-11-02", db_path=self.db)
        save_plan("L", self._plan("c"), day="2026-11-03", db_path=self.db)
        conn = sqlite3.connect(self.db)
        try:
            report = plan_stability(conn, "L")
        finally:
            conn.close()
        self.assertEqual(report["pares_comparados"], 2)
        self.assertEqual(report["cambio_medio"], 0.5)
        self.assertEqual(report["planes_nuevos_enteros"], 1)


class ProbabilidadDeGanarTests(unittest.TestCase):
    def test_el_brier_sale_de_pujas_reales_con_resultado(self) -> None:
        from toolbox.engine_calibration import _ensure_tracking_schema, win_probability_calibration

        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "db.sqlite")
            try:
                _ensure_tracking_schema(conn)
                rows = [
                    ("2026-11-01", "a", "PUJAR", 0.8, "hit"),
                    ("2026-11-01", "b", "PUJAR", 0.6, "lost"),
                    ("2026-11-01", "c", "PUJAR", 0.5, "unknown"),
                    ("2026-11-01", "d", "NO", 0.9, None),
                ]
                conn.executemany(
                    """
                    insert into market_decision_snapshots
                    (snapshot_day, player_id, decision, win_probability, outcome, stored_at)
                    values (?, ?, ?, ?, ?, 0)
                    """,
                    rows,
                )
                report = win_probability_calibration(conn)
            finally:
                conn.close()
        self.assertEqual(report["samples"], 2)
        self.assertAlmostEqual(report["brier"], ((0.8 - 1) ** 2 + 0.6**2) / 2, places=4)
        self.assertFalse(report["suficiente"])


class PujaPropiaTests(unittest.TestCase):
    def test_la_puja_propia_sale_del_anuncio(self) -> None:
        from toolbox.normalize import normalize_listing

        listing = normalize_listing({"id": "m1", "playerMaster": {"id": "p1"}, "salePrice": 100, "bid": {"money": 1_500_000}})
        self.assertEqual(listing["own_bid"], 1_500_000)
        self.assertIsNone(normalize_listing({"id": "m2", "playerMaster": {"id": "p2"}})["own_bid"])

    def test_con_pujas_propias_solo_cuentan_esas(self) -> None:
        from toolbox.engine_calibration import _ensure_tracking_schema, win_probability_calibration

        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "db.sqlite")
            try:
                _ensure_tracking_schema(conn)
                conn.executemany(
                    """
                    insert into market_decision_snapshots
                    (snapshot_day, player_id, decision, win_probability, outcome, stored_at, own_bid)
                    values (?, ?, 'PUJAR', ?, ?, 0, ?)
                    """,
                    [("2026-11-01", "a", 0.9, "hit", 2_000_000), ("2026-11-01", "b", 0.9, "lost", None)],
                )
                report = win_probability_calibration(conn)
            finally:
                conn.close()
        self.assertTrue(report["solo_pujas_propias"])
        self.assertEqual(report["samples"], 1)


class ComprasSinReferenciaTests(unittest.TestCase):
    def test_una_compra_sin_foto_de_precio_sigue_contando_para_saber_quien_gano(self) -> None:
        events = [
            {"activity_type_id": 31, "team_id": "t1", "player_id": "p1", "amount_eur": 5_000_000, "at": "2026-11-01T14:00:00+01:00"}
        ]
        self.assertEqual(collect_activity_buys(events, {}), [])
        buys = collect_activity_buys(events, {}, require_reference=False)
        self.assertEqual(len(buys), 1)
        self.assertIsNone(buys[0]["reference_value_eur"])
        self.assertEqual(buys[0]["team_id"], "t1")


if __name__ == "__main__":
    unittest.main()

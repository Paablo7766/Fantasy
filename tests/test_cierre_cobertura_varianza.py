"""Rojo leve con hueco, cobertura del partido inaugural y varianza de titularidad."""

from __future__ import annotations

import unittest

from toolbox.bid_war import overbid_risk, probability_of_winning_bid
from toolbox.bidding import URGENCIA_HUECO
from toolbox.engine.liquidacion import ACCION_MANTENER, cobertura_inaugural, plan_liquidacion
from toolbox.engine.lineup_math import huecos_obligatorios, penalizacion_varianza, solve_best_xi
from toolbox.league_history import RivalProfile
from toolbox.rival_intel import ROJO_SEGURO

INICIO = "2026-11-06T19:00:00+00:00"


def _rojo(**extra) -> dict:
    base = {
        "team_id": "n",
        "manager_name": "Naviis10",
        "cash_eur": -1_000_000,
        "bid_limit_eur": 0,
        "legal_bid_limit_eur": 5_000_000,
        "en_rojo": ROJO_SEGURO,
        "urgencia": {"POR": URGENCIA_HUECO},
    }
    base.update(extra)
    return base


class RojoLeveConHuecoTest(unittest.TestCase):
    def test_rojo_leve_con_hueco_sigue_pujando(self) -> None:
        self.assertEqual(overbid_risk("POR", 2_000_000, [_rojo()])["status"], "guerra")

    def test_rojo_sin_hueco_en_ese_puesto_se_queda_en_cero(self) -> None:
        risk = overbid_risk("DEF", 2_000_000, [_rojo()])
        self.assertEqual(risk["status"], "low")

    def test_rojo_con_tope_legal_agotado_se_queda_en_cero(self) -> None:
        risk = overbid_risk("POR", 2_000_000, [_rojo(legal_bid_limit_eur=1_500_000)])
        self.assertEqual(risk["status"], "low")
        self.assertEqual(risk["rivales_sin_caja"], ["Naviis10"])

    def test_probabilidad_cuenta_al_rojo_leve_con_hueco(self) -> None:
        def perfil(**extra) -> RivalProfile:
            base = dict(
                team_id="n", manager_name="n", alpha_aggressiveness=-1.0, sigma_dispersion=0.5,
                cash_eur=0.0, cash_uncertainty_eur=500_000.0, thin_positions=["POR"], xi_gaps=["POR"],
                lacks_replacements=True, en_rojo=True,
            )
            base.update(extra)
            return RivalProfile(**base)

        args = (2_000_000.0, 2_000_000.0, 2_000_000.0, "POR", 5.0)
        self.assertEqual(probability_of_winning_bid(*args, [perfil()]), 1.0)
        self.assertLess(probability_of_winning_bid(*args, [perfil(legal_bid_limit_eur=5_000_000.0)]), 1.0)
        self.assertEqual(
            probability_of_winning_bid(*args, [perfil(legal_bid_limit_eur=5_000_000.0, xi_gaps=[])]), 1.0
        )


def _fila(pid: str, pos: str, xp: float, p: float | None, **extra) -> dict:
    return {"player_id": pid, "position": pos, "jornada": xp, "p_titular": p, "elegible": True, **extra}


class CoberturaInauguralTest(unittest.TestCase):
    def test_cubre_dudoso_del_partido_inaugural(self) -> None:
        owned = [
            _fila("dudoso", "DEL", 6.0, 0.6, kickoff=INICIO),
            _fila("suplente", "DEL", 3.0, 0.9),
            _fila("otro_puesto", "MC", 4.0, 0.9),
        ]
        cob = cobertura_inaugural(owned, {"dudoso"}, inicio=INICIO)
        self.assertEqual(cob["conservar"], {"suplente"})
        self.assertAlmostEqual(cob["valor"], 0.4 * 3.0)

    def test_no_cubre_si_no_juega_el_primer_partido_ni_fuera_de_rango(self) -> None:
        tarde = [_fila("d", "DEL", 6.0, 0.6, kickoff="2026-11-07T19:00:00+00:00"), _fila("s", "DEL", 3.0, 0.9)]
        self.assertEqual(cobertura_inaugural(tarde, {"d"}, inicio=INICIO)["conservar"], set())
        seguro = [_fila("d", "DEL", 6.0, 0.95, kickoff=INICIO), _fila("s", "DEL", 3.0, 0.9)]
        self.assertEqual(cobertura_inaugural(seguro, {"d"}, inicio=INICIO)["conservar"], set())

    def test_sin_suplente_sano_no_hay_cobertura(self) -> None:
        owned = [_fila("d", "DEL", 6.0, 0.6, kickoff=INICIO), _fila("s", "DEL", 3.0, 0.9, elegible=False)]
        self.assertEqual(cobertura_inaugural(owned, {"d"}, inicio=INICIO)["conservar"], set())

    def test_plan_liquidacion_no_vende_la_cobertura(self) -> None:
        once = [
            _fila(f"p{i}", pos, 5.0, 0.95, kickoff="2026-11-08T19:00:00+00:00")
            for i, pos in enumerate(["POR", "DEF", "DEF", "DEF", "DEF", "MC", "MC", "MC", "DEL", "DEL"])
        ]
        once.append(_fila("dudoso", "DEL", 6.0, 0.6, kickoff=INICIO))
        owned = [*once, _fila("suplente", "DEL", 3.0, 0.9, valor=2_000_000)]
        plan = plan_liquidacion(owned, saldo=0, dias_para_jornada=1.0, inicio=INICIO)
        fila = next(item for item in plan["sobrantes"] if item["player_id"] == "suplente")
        self.assertEqual(fila["accion"], ACCION_MANTENER)
        self.assertGreater(plan["puntos_once_con_cobertura"], solve_best_xi(owned)["puntos"])


class VarianzaTest(unittest.TestCase):
    def test_penalizacion_formula(self) -> None:
        fila = _fila("x", "DEL", 5.0, 0.5)
        self.assertAlmostEqual(penalizacion_varianza(fila, 0.1), 0.1 * 0.5 * 0.5 * 25.0)
        self.assertEqual(penalizacion_varianza(_fila("y", "DEL", 5.0, None)), 0.0)

    def test_el_solver_prefiere_el_seguro_si_la_media_es_parecida(self) -> None:
        base = [
            _fila(f"p{i}", pos, 5.0, 1.0)
            for i, pos in enumerate(["DEF", "DEF", "DEF", "DEF", "MC", "MC", "MC", "MC", "DEL", "DEL"])
        ]
        arriesgado = _fila("arriesgado", "POR", 5.05, 0.3)
        seguro = _fila("seguro", "POR", 5.0, 0.95)
        once = solve_best_xi([*base, arriesgado, seguro])
        self.assertIn("seguro", once["player_ids"])
        self.assertNotIn("arriesgado", once["player_ids"])

    def test_hueco_obligatorio_a_30_por_ciento_o_menos(self) -> None:
        filas = [_fila("yeray", "DEF", 4.0, 0.2), _fila("limite", "DEF", 4.0, 0.3), _fila("ok", "DEF", 4.0, 0.31)]
        self.assertEqual(huecos_obligatorios(filas), ["yeray", "limite"])


if __name__ == "__main__":
    unittest.main()

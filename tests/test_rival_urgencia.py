"""Rivales en rojo y urgencia posicional (hueco frente a justo)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.bid_war import overbid_risk, probability_of_winning_bid
from toolbox.bidding import (
    URGENCIA_HUECO,
    URGENCIA_JUSTO,
    anotar_urgencia_compras,
    nivel_urgencia,
    urgencia_posicional,
)
from toolbox.league_history import RivalProfile, collect_activity_buys, fit_rival_profiles_eb
from toolbox.rival_intel import ROJO_PROBABLE, ROJO_SEGURO, estado_rojo

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


class EstadoRojoTest(unittest.TestCase):
    def test_seguro_probable_y_sano(self) -> None:
        self.assertEqual(estado_rojo(-20_600_000, -20_600_000), ROJO_SEGURO)
        self.assertEqual(estado_rojo(1_000_000, -500_000), ROJO_PROBABLE)
        self.assertIsNone(estado_rojo(1_000_000, 900_000))
        self.assertIsNone(estado_rojo(None, None))


class UrgenciaPosicionalTest(unittest.TestCase):
    def test_sin_portero_es_hueco(self) -> None:
        urgencia = urgencia_posicional({"POR": 0, "DEF": 5, "MC": 4, "DEL": 3})
        self.assertEqual(urgencia.get("POR"), URGENCIA_HUECO)

    def test_un_portero_es_justo(self) -> None:
        urgencia = urgencia_posicional({"POR": 1, "DEF": 5, "MC": 5, "DEL": 4})
        self.assertEqual(urgencia, {"POR": URGENCIA_JUSTO})

    def test_dos_defensas_es_hueco(self) -> None:
        urgencia = urgencia_posicional({"POR": 1, "DEF": 2, "MC": 5, "DEL": 3})
        self.assertEqual(urgencia.get("DEF"), URGENCIA_HUECO)
        self.assertNotIn("MC", urgencia)

    def test_once_exacto_todo_justo(self) -> None:
        urgencia = urgencia_posicional({"POR": 1, "DEF": 4, "MC": 4, "DEL": 2})
        self.assertEqual(set(urgencia.values()), {URGENCIA_JUSTO})
        self.assertEqual(set(urgencia), {"POR", "DEF", "MC", "DEL"})

    def test_plantilla_holgada_sin_urgencia(self) -> None:
        self.assertEqual(urgencia_posicional({"POR": 2, "DEF": 6, "MC": 6, "DEL": 4}), {})

    def test_nivel(self) -> None:
        urgencia = {"POR": URGENCIA_HUECO, "DEF": URGENCIA_JUSTO}
        self.assertEqual(nivel_urgencia(urgencia, "POR"), 2.0)
        self.assertEqual(nivel_urgencia(urgencia, "DEF"), 1.0)
        self.assertEqual(nivel_urgencia(urgencia, "DEL"), 0.0)


class OverbidRiskTest(unittest.TestCase):
    def test_guerra_segura_con_hueco_y_caja(self) -> None:
        rivals = [{"team_id": "p", "manager_name": "PABS FC", "cash_eur": 50_000_000, "urgencia": {"POR": URGENCIA_HUECO}}]
        risk = overbid_risk("POR", 2_000_000, rivals)
        self.assertEqual(risk["status"], "guerra")
        self.assertIn("PABS FC", risk["etiqueta"])
        self.assertTrue(risk["etiqueta"].startswith("Habrá guerra de pujas"))

    def test_justo_es_high(self) -> None:
        rivals = [{"team_id": "s", "manager_name": "Sausor10", "cash_eur": 50_000_000, "urgencia": {"POR": URGENCIA_JUSTO}}]
        self.assertEqual(overbid_risk("POR", 2_000_000, rivals)["status"], "high")

    def test_rival_en_rojo_no_puja(self) -> None:
        rivals = [
            {
                "team_id": "g",
                "manager_name": "gerardo_vp",
                "cash_eur": -20_000_000,
                "bid_limit_eur": 0,
                "en_rojo": ROJO_SEGURO,
                "urgencia": {"POR": URGENCIA_HUECO},
            }
        ]
        risk = overbid_risk("POR", 2_000_000, rivals)
        self.assertEqual(risk["status"], "low")
        self.assertEqual(risk["rivales_sin_caja"], ["gerardo_vp"])
        self.assertTrue(risk["etiqueta"].startswith("Sin competencia"))

    def test_libre_si_nadie_cojea(self) -> None:
        rivals = [{"team_id": "a", "cash_eur": 50_000_000, "urgencia": {}}]
        risk = overbid_risk("DEF", 2_000_000, rivals)
        self.assertEqual(risk["etiqueta"], "Sin competencia: ningún rival necesita este puesto")

    def test_compat_thin_positions_sin_urgencia(self) -> None:
        risk = overbid_risk("DEL", 1_000_000, [{"team_id": "r", "cash_eur": 2_000_000, "thin_positions": ["DEL"]}])
        self.assertEqual(risk["status"], "high")


class ProbabilidadRojoTest(unittest.TestCase):
    def _profile(self, **extra) -> RivalProfile:
        base = dict(
            team_id="g",
            manager_name="g",
            alpha_aggressiveness=-1.0,
            sigma_dispersion=0.5,
            cash_eur=0.0,
            cash_uncertainty_eur=5_000_000.0,
            thin_positions=["POR"],
            xi_gaps=["POR"],
            lacks_replacements=True,
        )
        base.update(extra)
        return RivalProfile(**base)

    def test_rojo_no_resta_probabilidad(self) -> None:
        args = (2_000_000.0, 2_000_000.0, 2_000_000.0, "POR", 5.0)
        vivo = probability_of_winning_bid(*args, [self._profile()])
        rojo = probability_of_winning_bid(*args, [self._profile(en_rojo=True)])
        self.assertLess(vivo, 1.0)
        self.assertEqual(rojo, 1.0)

    def test_rojo_que_ya_puja_cuenta(self) -> None:
        args = (2_000_000.0, 2_000_000.0, 2_000_000.0, "POR", 5.0)
        rojo = probability_of_winning_bid(*args, [self._profile(en_rojo=True, already_bidding=True)])
        self.assertLess(rojo, 1.0)

    def test_perfil_hereda_rojo(self) -> None:
        profiles = fit_rival_profiles_eb([], [{"team_id": "g", "cash_eur": -1, "en_rojo": ROJO_SEGURO}])
        self.assertTrue(profiles["g"].en_rojo)


def _squad(team_id: str, players: list[tuple[str, str]]) -> dict:
    return {
        "team_id": team_id,
        "players": [
            {"player_id": pid, "position": pos, "name": pid, "nickname": pid, "market_value": 1_000_000, "player_status": "ok"}
            for pid, pos in players
        ],
    }


class AnotarUrgenciaTest(unittest.TestCase):
    def setUp(self) -> None:
        # Tras comprar al portero "nuevo", el rival tiene 1 POR: antes tenía 0.
        players = [("nuevo", "POR")]
        players += [(f"d{i}", "DEF") for i in range(5)]
        players += [(f"m{i}", "MC") for i in range(5)]
        players += [(f"f{i}", "DEL") for i in range(3)]
        self.squads = [_squad("t", players)]

    def _ledgers(self, at: datetime) -> list[dict]:
        return [
            {
                "team_id": "t",
                "events": [{"kind": "buy", "player_id": "nuevo", "amount_eur": 1_500_000, "at": at.isoformat()}],
            }
        ]

    def test_compra_reciente_se_fecha_como_hueco(self) -> None:
        ledgers = self._ledgers(NOW - timedelta(hours=5))
        fechadas = anotar_urgencia_compras(ledgers, self.squads, {}, now=NOW)
        self.assertEqual(fechadas, 1)
        self.assertEqual(ledgers[0]["events"][0]["positional_urgency"], 2.0)

    def test_compra_antigua_conserva_lo_guardado(self) -> None:
        at = NOW - timedelta(days=5)
        previos = self._ledgers(at)
        previos[0]["events"][0]["positional_urgency"] = 1.0
        ledgers = self._ledgers(at)
        self.assertEqual(anotar_urgencia_compras(ledgers, self.squads, {}, now=NOW, previos=previos), 0)
        self.assertEqual(ledgers[0]["events"][0]["positional_urgency"], 1.0)

    def test_compra_antigua_sin_dato_queda_vacia(self) -> None:
        ledgers = self._ledgers(NOW - timedelta(days=5))
        anotar_urgencia_compras(ledgers, self.squads, {}, now=NOW)
        self.assertNotIn("positional_urgency", ledgers[0]["events"][0])

    def test_activity_buys_lee_la_urgencia_del_libro(self) -> None:
        at = NOW - timedelta(hours=5)
        ledgers = self._ledgers(at)
        anotar_urgencia_compras(ledgers, self.squads, {}, now=NOW)
        events = [
            {"activity_type_id": 31, "team_id": "t", "player_id": "nuevo", "amount_eur": 1_500_000, "at": at.isoformat()}
        ]
        buys = collect_activity_buys(events, {}, ledgers, require_reference=False)
        self.assertEqual(buys[0]["positional_urgency"], 2.0)


if __name__ == "__main__":
    unittest.main()

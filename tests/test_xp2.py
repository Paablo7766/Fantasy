"""xP 2.0: suelo, gol, asistencia y portería por separado."""

from __future__ import annotations

import unittest

from toolbox.analitica_fantasy import parse_set_pieces
from toolbox.engine import xp2
from toolbox.opta_points_v2 import compute_expected_opta_points_v2
from toolbox.player_history import desglose_acta


def acta(jornada: int, *, minutos: int = 90, suelo: float = 4.0, goles: int = 0, pts_gol: float = 0.0,
         ast: float = 0.0, porteria: float = 0.0) -> dict:
    bloques = {"min": 2.0 if minutos >= 60 else 1.0, "rating": suelo - 2.0, "goal": pts_gol, "ast": ast, "def": porteria}
    total = sum(bloques.values())
    return {
        "puntos": total,
        "minutos": minutos,
        "jornada": jornada,
        "desglose": {"puntos": bloques, "cantidades": {"mins_played": minutos, "goals": goles}},
    }


def jugador(posicion: str, actas: list[dict], **extra) -> dict:
    return {"position": posicion, "p_titular": 0.9, "historial": actas, **extra}


def xp(player: dict, **kw) -> dict:
    return xp2.prediccion_xp2(player, prob_titular=kw.pop("p", 0.9), lambda_favor=kw.pop("lf", 1.3),
                              lambda_contra=kw.pop("lc", 1.3), **kw)


class Xp2Tests(unittest.TestCase):
    def test_gol_aislado_no_infla_como_el_suelo(self) -> None:
        # Mismo total (3 partidos): uno lo hace con un gol de rebote, otro con juego cada semana.
        suerte = jugador("DEF", [acta(9, suelo=3), acta(10, suelo=3), acta(11, suelo=3, goles=1, pts_gol=6)])
        suelo = jugador("DEF", [acta(9, suelo=5), acta(10, suelo=5), acta(11, suelo=5)])
        self.assertGreater(xp(suelo)["xp_condicional"], xp(suerte)["xp_condicional"] + 0.2)

    def test_porteria_depende_del_partido(self) -> None:
        defensa = jugador("DEF", [acta(j) for j in range(7, 12)])
        facil = xp(defensa, lc=0.6)
        dificil = xp(defensa, lc=2.2)
        self.assertGreater(facil["porteria"], dificil["porteria"] + 1.0)
        # Con P(cero) del calendario manda esa.
        self.assertAlmostEqual(xp2.puntos_porteria("PT", 1.0, 1.0 - 1e-9), 4.0, places=3)

    def test_favorito_suma(self) -> None:
        medio = jugador("MC", [acta(j) for j in range(7, 12)])
        self.assertGreater(xp(medio, lf=2.2, lc=0.6)["xp_condicional"], xp(medio, lf=0.8, lc=1.8)["xp_condicional"])

    def test_sin_desglose_devuelve_none(self) -> None:
        player = {"position": "MC", "historial": [{"puntos": 6, "minutos": 90, "jornada": 9}]}
        self.assertIsNone(xp(player))

    def test_breakout_barato_no_se_castiga_por_precio(self) -> None:
        actas = [acta(8, suelo=3), acta(9, suelo=3), acta(10, suelo=7), acta(11, suelo=7)]
        barato = jugador("DEL", actas, market_value=600_000)
        resultado = xp(barato)
        self.assertTrue(resultado["breakout"])
        # Sin breakout (dos partidos flojos al final) el precio bajo sí resta.
        flojo = jugador("DEL", [acta(8, suelo=7), acta(9, suelo=7), acta(10, suelo=3), acta(11, suelo=3)], market_value=600_000)
        self.assertFalse(xp(flojo)["breakout"])
        sin_precio = jugador("DEL", actas)
        # Con breakout, ser barato no resta nada frente a no saber el precio.
        self.assertGreaterEqual(resultado["suelo"], xp(sin_precio)["suelo"] - 1e-9)

    def test_breakout_por_gol_no_cuenta(self) -> None:
        actas = [acta(10, suelo=3, goles=1, pts_gol=4), acta(11, suelo=3, goles=1, pts_gol=4)]
        self.assertFalse(xp(jugador("DEL", actas, market_value=600_000))["breakout"])

    def test_lanzador_de_penaltis_suma_gol(self) -> None:
        actas = [acta(j) for j in range(7, 12)]
        normal = xp(jugador("DEL", actas))
        lanzador = xp(jugador("DEL", actas, af_set_pieces=[{"role": "penalties", "shirt": 9}]))
        self.assertAlmostEqual(lanzador["gol"] - normal["gol"], xp2.GOLES_PENALTI_POR_PARTIDO * 4.0, places=2)

    def test_portero_suplente_y_titular(self) -> None:
        suplente = {"position": "POR", "historial": [{"puntos": 0, "minutos": 0, "jornada": j} for j in range(8, 12)]}
        self.assertEqual(xp2.prob_titular_portero(suplente, 0.32), 0.03)
        titular = {"position": "POR", "historial": [{"puntos": 8, "minutos": 90, "jornada": j} for j in range(8, 12)]}
        self.assertEqual(xp2.prob_titular_portero(titular, 0.87), 0.95)
        # Si el once publicado dice que el suplente juega (lesión del titular), manda el once.
        suplente_confirmado = {**suplente, "p_titular": 0.9, "p_titular_source": "lineup"}
        self.assertEqual(xp2.prob_titular_portero(suplente_confirmado, 0.9), 0.9)
        # Los de campo no se tocan.
        self.assertEqual(xp2.prob_titular_portero({"position": "DEF", "historial": suplente["historial"]}, 0.32), 0.32)

    def test_opta_points_v2_usa_xp2_y_portero_suplente(self) -> None:
        defensa = jugador("DEF", [acta(j) for j in range(7, 12)])
        out = compute_expected_opta_points_v2(defensa, run_monte_carlo=False)
        self.assertEqual(out["xp_modelo"], "2.0")
        self.assertIn("porteria", out["xp_desglose"])
        self.assertGreaterEqual(out["ceiling_points"], out["expected_points"])
        suplente = {"position": "POR", "p_titular": 0.32,
                    "historial": [{"puntos": 0, "minutos": 0, "jornada": j} for j in range(8, 12)]}
        self.assertLess(compute_expected_opta_points_v2(suplente, run_monte_carlo=False)["expected_points"], 0.5)
        sin_actas = {"position": "MC", "p_titular": 0.8, "historial": [{"puntos": 6, "minutos": 90, "jornada": 9}]}
        self.assertEqual(compute_expected_opta_points_v2(sin_actas, run_monte_carlo=False)["xp_modelo"], "respaldo")


class DesgloseActaTests(unittest.TestCase):
    def test_valoracion_es_el_segundo_valor(self) -> None:
        d = desglose_acta({"mins_played": [90, 2], "marca_points": [-1, 3], "goals": [1, 5], "ball_recovery": [8, 1]})
        self.assertEqual(d["puntos"], {"min": 2.0, "rating": 3.0, "goal": 5.0, "act": 1.0})
        self.assertEqual(d["cantidades"]["goals"], 1.0)


class BalonParadoTests(unittest.TestCase):
    HTML = (
        '<a href="/equipo/athletic-club-531">Ver ficha</a>'
        '<p class="x">Directas</p><span>Principal</span>'
        '<a class="af-link" href="/jugadores/berenguer-1">Berenguer</a><span class="b" title="Delantero">DL</span>'
        '<p class="x">Penaltis</p><span>Principal#10</span>'
        '<a class="af-link" href="/jugadores/n-williams-2">Nico Williams</a><span class="b" title="Delantero">DL</span>'
        '<a href="/equipo/real-betis-543">Ver ficha</a>'
        '<p class="x">Penaltis</p><span>Principal</span>'
        '<a class="af-link" href="/jugadores/isco-3">Isco</a><span class="b" title="Centrocampista">MC</span>'
    )

    def test_maquetacion_actual_trae_nombre_club_y_puesto(self) -> None:
        rows = parse_set_pieces(self.HTML)
        got = {(r.name, r.club, r.role, r.position) for r in rows}
        self.assertIn(("Berenguer", "athletic club", "direct", "DEL"), got)
        self.assertIn(("Nico Williams", "athletic club", "penalties", "DEL"), got)
        self.assertIn(("Isco", "real betis", "penalties", "MC"), got)
        self.assertEqual(next(r.shirt for r in rows if r.name == "Nico Williams"), 10)

    def test_el_dorsal_nunca_es_el_nombre(self) -> None:
        self.assertEqual(parse_set_pieces("<span>Directas</span><span>Principal#15</span><span>15</span>"), [])


if __name__ == "__main__":
    unittest.main()

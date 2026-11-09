"""Rival posicional: ajuste suave de valoración + acciones según lo que el rival concede al puesto."""

from __future__ import annotations

import unittest

from toolbox.engine import xp2
from toolbox.rival_posicional import AJUSTE_MAX, ajuste_de, construir_tabla
from tests.test_xp2 import acta, jugador, xp


def _clave(nombre: str) -> str:
    return nombre.lower()


def _entrada(equipo: str, posicion: str, por_jornada: dict[int, float]) -> dict:
    """Jugador titular cuyo (rating+act) en cada jornada es ``por_jornada[j]``."""
    return {
        "team": equipo,
        "position": posicion,
        "weeks": {j: (6.0, 90.0) for j in por_jornada},
        "desglose": {j: {"puntos": {"rating": v, "act": 0.0}} for j, v in por_jornada.items()},
    }


class TablaTests(unittest.TestCase):
    def setUp(self) -> None:
        # El equipo "a" juega contra "regala" en la J1-J4 y contra "seca" en la J5-J8.
        rivales = {("a", j): "regala" for j in range(1, 5)} | {("a", j): "seca" for j in range(5, 9)}
        actas = {
            str(i): _entrada("a", "DEF", {**{j: 4.0 for j in range(1, 5)}, **{j: 0.0 for j in range(5, 9)}})
            for i in range(6)
        }
        self.tabla = construir_tabla(actas, rivales, _clave)

    def test_el_rival_que_regala_suma_y_el_que_seca_resta(self) -> None:
        self.assertGreater(ajuste_de(self.tabla, "regala", "DEF"), 0.2)
        self.assertLess(ajuste_de(self.tabla, "seca", "DEF"), -0.2)

    def test_acotado_y_encogido_por_muestra(self) -> None:
        self.assertLessEqual(abs(ajuste_de(self.tabla, "regala", "DEF")), AJUSTE_MAX)
        pequena = construir_tabla(
            {"1": _entrada("a", "DEF", {1: 9.0, 2: 0.0, 3: 0.0})},
            {("a", 1): "unico", ("a", 2): "otro", ("a", 3): "otro"},
            _clave,
        )
        # Una sola observación apenas mueve el ajuste (n/(n+12)).
        self.assertLess(abs(ajuste_de(pequena, "unico", "DEF")), AJUSTE_MAX - 0.1)

    def test_sin_datos_no_ajusta(self) -> None:
        self.assertEqual(ajuste_de(self.tabla, "desconocido", "DEF"), 0.0)
        self.assertEqual(ajuste_de(self.tabla, "regala", "MC"), 0.0)
        self.assertEqual(ajuste_de({}, None, "DEF"), 0.0)


class Xp2AjusteTests(unittest.TestCase):
    def test_el_ajuste_entra_en_valoracion_y_acciones(self) -> None:
        player = jugador("DEF", [acta(j) for j in range(8, 12)])
        base = xp(player)
        con = xp(player, ajuste_rival=0.5)
        sin = xp(player, ajuste_rival=-0.5)
        self.assertAlmostEqual(con["xp_condicional"] - base["xp_condicional"], 0.5, places=2)
        self.assertAlmostEqual(base["xp_condicional"] - sin["xp_condicional"], 0.5, places=2)
        self.assertEqual(con["ajuste_rival_posicional"], 0.5)
        self.assertEqual(xp2.prediccion_xp2.__name__, "prediccion_xp2")

    def test_el_cambio_cronico_reduce_el_ajuste(self) -> None:
        cronico = jugador("MC", [acta(j, minutos=45) for j in range(8, 12)])
        self.assertLess(xp(cronico, ajuste_rival=0.6)["ajuste_rival_posicional"], 0.6)


if __name__ == "__main__":
    unittest.main()

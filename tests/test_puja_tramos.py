"""Tres cifras de puja: mediana del tramo, percentil 90 solo si la cola es fina, máxima personal."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from toolbox.engine.puja_tramos import (
    _compras_locales,
    _referencia,
    _sumar_diario,
    cifras,
    cola_fina,
    frescura_xp,
    mejora_xp,
    precio_punto,
    reventa_eur,
    rivales_con_hueco,
    tabla,
    tiene_xp,
    tope_eur,
)


class ColaFina(unittest.TestCase):
    def test_una_muestra_corta_no_se_ensena(self) -> None:
        ratios = [1.0] * 15 + [2.5, 3.0]
        self.assertFalse(cola_fina(ratios))

    def test_treinta_sin_extremos_si_se_ensena(self) -> None:
        ratios = [1.0 + i * 0.01 for i in range(30)]
        self.assertTrue(cola_fina(ratios))

    def test_dos_bombas_que_mueven_el_90_lo_esconden(self) -> None:
        # Con 20 compras, el percentil 90 cae entre el bloque y la primera bomba.
        ratios = [1.05] * 17 + [8.0, 9.0, 10.0]
        self.assertFalse(cola_fina(ratios))


class PrecioPunto(unittest.TestCase):
    def test_sin_muestra_un_punto_vale_solo_su_premio(self) -> None:
        punto = precio_punto([{"ratio": 1.3}] * 3)
        # 100.000 € por punto y jornada, cuatro jornadas.
        self.assertEqual(punto["euros_por_punto"], 400_000)
        self.assertEqual(punto["sobreprecio_eur"], 0)

    def test_con_muestra_suma_el_sobreprecio_de_la_liga(self) -> None:
        punto = precio_punto([{"ratio": 1.05}] * 20, 16_000_000)
        # 5 % de sobrepuja sobre 16 M por punto = 800.000 € que no vuelven al revender.
        self.assertEqual(punto["sobreprecio_eur"], 800_000)
        self.assertEqual(punto["euros_por_punto"], 1_200_000)

    def test_una_liga_que_compra_por_debajo_del_valor_no_resta(self) -> None:
        punto = precio_punto([{"ratio": 0.95}] * 20, 16_000_000)
        self.assertEqual(punto["euros_por_punto"], 400_000)

    def test_la_maxima_no_cuenta_dos_veces_el_valor(self) -> None:
        # Un jugador de 3 M que mejora el once 1,4 puntos no puede valer 26 M.
        punto = precio_punto([{"ratio": 1.047}] * 34)
        stats = {"banda": "1.5-4", "etiqueta": "1,5–4 M", "n": 34, "mediana": 1.047, "p90": 1.31, "fiable": True}
        ficha = cifras(3_010_000, stats, xp=1.4, reventa=3_240_000, subida=True, tope=None, tope_motivo=None, euros_por_punto=punto["euros_por_punto"])
        maxima = ficha["xp_delta"] * ficha["euros_por_punto"] + ficha["reventa_eur"]
        self.assertLess(maxima, 2 * 3_010_000)
        self.assertGreater(maxima, ficha["ideal_eur"])


class Cifras(unittest.TestCase):
    def test_ideal_es_la_mediana_y_asegurar_solo_si_es_fiable(self) -> None:
        stats = {"banda": ">=15", "etiqueta": "15 M o más", "n": 30, "mediana": 1.1, "p90": 1.26, "fiable": True}
        ficha = cifras(20_000_000, stats, xp=0.0, reventa=20_000_000, subida=False, tope=None, tope_motivo=None)
        self.assertEqual(ficha["ideal_eur"], 22_000_000)
        self.assertEqual(ficha["asegurar_eur"], 25_200_000)

    def test_sin_cola_fina_no_hay_cifra_de_asegurar(self) -> None:
        stats = {"banda": "1.5-4", "etiqueta": "1,5–4 M", "n": 15, "mediana": 1.51, "p90": 2.17, "fiable": False}
        ficha = cifras(2_000_000, stats, xp=1.0, reventa=2_000_000, subida=False, tope=5_000_000, tope_motivo="guardarrail")
        self.assertEqual(ficha["ideal_eur"], 3_020_000)
        self.assertIsNone(ficha["asegurar_eur"])
        self.assertEqual(ficha["asegurar_texto"], "sin cifra fiable")
        self.assertEqual(ficha["n"], 15)

    def test_el_aviso_de_un_rival_no_entra_en_la_cifra(self) -> None:
        stats = {"banda": "1.5-4", "etiqueta": "1,5–4 M", "n": 15, "mediana": 1.5, "p90": 2.0, "fiable": False}
        sola = cifras(2_000_000, stats, xp=0.0, reventa=2_000_000, subida=False, tope=None, tope_motivo=None)
        self.assertNotIn("pabs", json.dumps(sola).casefold())
        self.assertEqual(sola["ideal_eur"], 3_000_000)


class ReventaYTope(unittest.TestCase):
    def test_por_debajo_de_1_5_no_suma_la_subida(self) -> None:
        valor, subida = reventa_eur(900_000, 1_200_000)
        self.assertEqual(valor, 900_000)
        self.assertFalse(subida)

    def test_desde_1_5_usa_el_valor_a_7_dias(self) -> None:
        valor, subida = reventa_eur(2_000_000, 2_400_000)
        self.assertEqual(valor, 2_400_000)
        self.assertTrue(subida)

    def test_el_guardarrail_recorta_antes_que_la_caja(self) -> None:
        tope, motivo = tope_eur({"guardarrail_ruina": {"margen_eur": 4_000_000}, "poder_pujas": 20_000_000})
        self.assertEqual((tope, motivo), (4_000_000, "guardarrail"))

    def test_sin_guardarrail_vale_la_caja_mas_el_credito(self) -> None:
        tope, motivo = tope_eur({"poder_pujas": 12_000_000})
        self.assertEqual((tope, motivo), (12_000_000, "caja_credito"))

    def test_un_margen_negativo_deja_el_tope_en_cero(self) -> None:
        tope, motivo = tope_eur({"guardarrail_ruina": {"margen_eur": -500_000}})
        self.assertEqual((tope, motivo), (0, "guardarrail"))


class Mejora(unittest.TestCase):
    def test_cero_si_no_entra_en_el_once(self) -> None:
        self.assertEqual(mejora_xp({"points_delta": 2.0, "points_delta_source": "own", "replaces": {"name": "X"}}), 0.0)

    def test_cuenta_la_mejora_propia_cuando_el_solver_lo_alinea(self) -> None:
        fila = {"points_delta": 1.25, "points_delta_source": "own", "replaces": {"formation": "4-4-2"}}
        self.assertEqual(mejora_xp(fila), 1.25)

    def test_ignora_una_fuente_que_no_sea_la_propia(self) -> None:
        fila = {"points_delta": 3.0, "points_delta_source": "af", "replaces": {"formation": "4-4-2"}}
        self.assertEqual(mejora_xp(fila), 0.0)


class Muestra(unittest.TestCase):
    def test_interpola_entre_las_dos_fotos_y_no_arrastra_un_solo_lado(self) -> None:
        self.assertEqual(_referencia({"2026-10-01": 100, "2026-10-05": 180}, "2026-10-03"), (140, "interpolada"))
        self.assertIsNone(_referencia({"2026-10-01": 100}, "2026-10-03"))
        self.assertEqual(_referencia({"2026-10-03": 100}, "2026-10-03"), (100, "mismo_dia"))

    def test_el_diario_nuevo_mueve_la_mediana_y_no_duplica(self) -> None:
        historicas = [
            {"team_id": "a", "player_id": "1", "day": "2026-11-01", "reference_eur": 20_000_000, "ratio": 1.0},
            {"team_id": "b", "player_id": "2", "day": "2026-11-02", "reference_eur": 20_000_000, "ratio": 1.2},
        ]
        diario = [
            {"team_id": "a", "player_id": "1", "day": "2026-11-01", "amount_eur": 20_000_000, "reference_eur": 20_000_000},
            {"team_id": "c", "player_id": "3", "day": "2026-11-03", "amount_eur": 30_000_000, "reference_eur": 20_000_000},
        ]
        unidas = _sumar_diario(historicas, diario, propio="mio")
        self.assertEqual(len(unidas), 3)
        bandas = tabla(unidas)
        self.assertEqual(bandas[">=15"]["n"], 3)
        self.assertGreater(bandas[">=15"]["mediana"], 1.0)

    def test_el_libro_local_excluye_al_propio_y_marca_la_interpolada(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            db = raiz / "responses.sqlite"
            conn = sqlite3.connect(db)
            conn.execute("create table price_snapshots (player_id text, day text, market_value integer)")
            conn.execute("create table activity_buys (team_id text, player_id text, amount_eur integer, at text)")
            conn.executemany(
                "insert into price_snapshots values (?, ?, ?)",
                [("1", "2026-11-01", 1_000_000), ("1", "2026-11-05", 1_400_000), ("2", "2026-11-03", 3_000_000)],
            )
            conn.executemany(
                "insert into activity_buys values (?, ?, ?, ?)",
                [
                    ("rival", "1", 1_200_000, "2026-11-03T12:00:00+00:00"),
                    ("rival", "2", 3_300_000, "2026-11-03T12:00:00+00:00"),
                    ("mio", "2", 9_000_000, "2026-11-03T12:00:00+00:00"),
                ],
            )
            conn.commit()
            conn.close()
            filas = _compras_locales(raiz, "mio")
        origenes = {fila["player_id"]: fila["origen"] for fila in filas}
        self.assertEqual(origenes, {"1": "interpolada", "2": "mismo_dia"})
        ratios = {fila["player_id"]: round(fila["ratio"], 2) for fila in filas}
        self.assertEqual(ratios["2"], 1.1)


class Rivales(unittest.TestCase):
    def _board(self) -> dict:
        def rival(team_id: str, manager: str, huecos: list[str], caja: int, inicial: int) -> dict:
            return {
                "team_id": team_id,
                "manager_name": manager,
                "fantasy_team_name": manager,
                "xi_gaps": huecos,
                "ledger": {"reconstructed_cash_eur": caja, "initial_budget_eur": inicial},
            }

        return {
            "needs": {
                "rivals": [
                    rival("1", "gerardo_vp", ["MC"], 5_000_000, 100_000_000),
                    rival("2", "PABS FC", ["MC"], 1_000_000, 91_200_000),
                    rival("3", "floren romi", ["DEF"], 20_000_000, 100_000_000),
                    rival("4", "Sausor10", ["MC"], -30_000_000, 100_000_000),
                ]
            },
            "squads": {
                "squads": [
                    {"team_id": "1", "is_self": False, "manager_avatar": "https://ejemplo/gerardo.png", "players": [{"market_value": 10_000_000, "position": "MC"}]},
                    {"team_id": "2", "is_self": False, "players": [{"market_value": 10_000_000, "position": "MC"}]},
                    {"team_id": "3", "is_self": False, "players": [{"market_value": 10_000_000, "position": "DEF"}]},
                    {"team_id": "4", "is_self": False, "players": [{"market_value": 1_000_000, "position": "MC"}]},
                    {"team_id": "yo", "is_self": True, "players": []},
                ]
            },
        }

    def test_lista_quien_tiene_caja_alta_y_hueco_en_el_puesto(self) -> None:
        lista = rivales_con_hueco(self._board(), "MC", 2_000_000)
        nombres = [fila["manager"] for fila in lista]
        # PABS parte de 91,2 M: la cota alta le suma los 8,8 M que faltan hasta 100, y con el crédito llega.
        self.assertEqual(nombres, ["gerardo_vp", "PABS FC"])
        por_nombre = {fila["manager"]: fila for fila in lista}
        self.assertEqual(por_nombre["gerardo_vp"]["aviso"], "suele ganar al valor")
        self.assertEqual(por_nombre["gerardo_vp"]["avatar"], "https://ejemplo/gerardo.png")
        self.assertEqual(por_nombre["PABS FC"]["aviso"], "dispara")
        # 1 M reconstruidos + 8,8 M de ajuste + 20 % de 10 M.
        self.assertEqual(por_nombre["PABS FC"]["puede_pujar_eur"], 1_000_000 + 8_800_000 + 2_000_000)


class FrescuraXp(unittest.TestCase):
    def test_un_dia_justo_sigue_fresco_y_al_segundo_siguiente_no(self) -> None:
        ahora = datetime(2026, 11, 11, 21, 0, tzinfo=timezone.utc)
        dentro = frescura_xp("2026-11-10T21:00:00+00:00", True, now=ahora)
        fuera = frescura_xp("2026-11-10T20:59:59+00:00", True, now=ahora)
        self.assertTrue(dentro["xp_fresco"])
        self.assertEqual(dentro["xp_edad_horas"], 24)
        self.assertFalse(fuera["xp_fresco"])
        self.assertEqual(fuera["horizonte_jornadas"], 4)

    def test_sin_xp_no_esta_fresco_aunque_la_foto_sea_de_hoy(self) -> None:
        ahora = datetime(2026, 11, 11, 21, 0, tzinfo=timezone.utc)
        hoy = frescura_xp("2026-11-11T20:00:00+00:00", False, now=ahora)
        self.assertFalse(hoy["xp_fresco"])
        self.assertFalse(hoy["xp_presente"])
        self.assertLess(hoy["xp_edad_horas"], 24)

    def test_sin_fecha_no_hay_maxima(self) -> None:
        self.assertFalse(frescura_xp(None, True)["xp_fresco"])
        self.assertIsNone(frescura_xp(None, True)["xp_edad_horas"])

    def test_el_xp_cuenta_si_es_propio_aunque_sea_cero(self) -> None:
        self.assertTrue(tiene_xp({"own_expected_points": 0}))
        self.assertTrue(tiene_xp({"expected_points_source": "own", "expected_points": 1.2}))
        self.assertFalse(tiene_xp({"expected_points_source": "af", "expected_points": 4}))
        self.assertFalse(tiene_xp({}))


class Tabla(unittest.TestCase):
    def test_los_multiplicadores_salen_de_las_compras(self) -> None:
        filas = [{"reference_eur": 20_000_000, "ratio": 1.0 + i * 0.01} for i in range(30)]
        bandas = tabla(filas)
        self.assertEqual(bandas[">=15"]["n"], 30)
        self.assertTrue(bandas[">=15"]["fiable"])
        self.assertAlmostEqual(bandas[">=15"]["mediana"], 1.145, places=3)
        self.assertEqual(bandas["1.5-4"]["n"], 0)
        self.assertFalse(bandas["1.5-4"]["fiable"])


if __name__ == "__main__":
    unittest.main()

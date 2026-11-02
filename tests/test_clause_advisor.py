"""Asesor de cláusulas: jugadores en peligro, cláusula perfecta y mejores clausulazos."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.engine.clause_advisor import auditar_clausulas_plantilla, coste_reposicion, coste_subida, evaluar_clausulas
from toolbox.engine.strategy_layer import build_strategy

AHORA = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
CIERRE = AHORA + timedelta(hours=48)
RATIO = 2_000_000
ABIERTA = {"is_locked": False}


def _once() -> list[dict]:
    plantilla = []
    for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
        for index in range(count):
            plantilla.append(
                {
                    "player_id": f"{position}-{index}",
                    "nombre": f"{position}{index}",
                    "position": position,
                    "valor": 8_000_000,
                    "clausula": 20_000_000,
                    "bloqueo": ABIERTA,
                    "jornada": 4.0,
                    "en_xi": True,
                    "tu_once_pierde_sin_el": 0.0,
                    "elegible": True,
                }
            )
    for position in ("POR", "DEF", "MC", "DEL"):
        plantilla.append(
            {
                "player_id": f"{position}-banq",
                "nombre": f"Suplente {position}",
                "position": position,
                "valor": 1_000_000,
                "clausula": 20_000_000,
                "bloqueo": ABIERTA,
                "jornada": 0.5,
                "en_xi": False,
                "tu_once_pierde_sin_el": 0.0,
                "elegible": True,
            }
        )
    return plantilla


def _con(plantilla: list[dict], player_id: str, **cambios: object) -> list[dict]:
    for fila in plantilla:
        if fila["player_id"] == player_id:
            fila.update(cambios)
    return plantilla


def _rival(manager: str, saldo: int | None, posiciones: list[str] | None = None) -> dict:
    return {"team_id": f"t-{manager}", "manager": manager, "saldo": saldo, "posiciones": posiciones or []}


def _ajeno(player_id: str, position: str, xp: float, clausula: int, **extra: object) -> dict:
    fila = {
        "player_id": player_id,
        "nombre": player_id,
        "position": position,
        "valor": clausula,
        "valor_justo": clausula,
        "clausula": clausula,
        "bloqueo": ABIERTA,
        "jornada": xp,
        "manager": "Luis",
        "team_id": "t-Luis",
    }
    fila.update(extra)
    return fila


def _evaluar(propios: list[dict], rivales: list[dict], ajenos: list[dict] | None = None, saldo: int = 10_000_000, cierre=CIERRE) -> dict:
    return evaluar_clausulas(
        propios=propios,
        ajenos=ajenos or [],
        rivales=rivales,
        saldo=saldo,
        ratio=RATIO,
        ahora=AHORA,
        cierre=cierre,
    )


def _fila(resultado: dict, clave: str, player_id: str) -> dict:
    return next(fila for fila in resultado[clave] if fila["player_id"] == player_id)


class CosteTests(unittest.TestCase):
    def test_subir_dos_euros_cuesta_uno_redondeando_al_alza(self) -> None:
        self.assertEqual(coste_subida(8_000_000, 12_000_000), 2_000_000)
        self.assertEqual(coste_subida(8_000_000, 8_000_001), 1)
        self.assertEqual(coste_subida(8_000_000, 7_000_000), 0)


class ProtegerTests(unittest.TestCase):
    def test_cubrir_a_todos_exige_superar_la_caja_del_mas_rico(self) -> None:
        plantilla = _con(_once(), "DEL-0", clausula=8_000_000, tu_once_pierde_sin_el=3.0)
        resultado = _evaluar(plantilla, [_rival("Luis", 12_000_000), _rival("Ana", 9_000_000), _rival("Pepe", 2_000_000)])
        fila = _fila(resultado, "proteger", "DEL-0")
        self.assertEqual(fila["rivales_que_pueden_pagar"], 2)
        self.assertEqual(fila["rival_mas_rico"]["manager"], "Luis")
        perfecta = fila["clausula_perfecta"]
        self.assertEqual(perfecta["clausula_objetivo"], 12_250_000)
        self.assertEqual(perfecta["coste_eur"], 2_125_000)
        self.assertEqual(perfecta["rivales_sin_cubrir"], 0)
        self.assertEqual(fila["riesgo"], "ALTO")
        self.assertEqual(fila["veredicto_codigo"], "PROTEGER_YA")
        self.assertEqual(fila["subida_recomendada"]["clausula_objetivo"], 12_250_000)

    def test_sin_caja_suficiente_avisa_de_lo_que_falta(self) -> None:
        plantilla = _con(_once(), "DEL-0", clausula=8_000_000, tu_once_pierde_sin_el=3.0)
        resultado = _evaluar(plantilla, [_rival("Luis", 12_000_000)], saldo=1_000_000)
        fila = _fila(resultado, "proteger", "DEL-0")
        self.assertEqual(fila["veredicto_codigo"], "SIN_CAJA")
        self.assertIn("faltan", fila["motivo_detallado"])

    def test_si_proteger_cuesta_mas_de_lo_que_protege_y_cobras_mas_que_su_valor_se_asume(self) -> None:
        plantilla = _con(_once(), "MC-0", clausula=10_000_000, tu_once_pierde_sin_el=0.0)
        resultado = _evaluar(plantilla, [_rival("Luis", 12_000_000)])
        fila = _fila(resultado, "proteger", "MC-0")
        self.assertEqual(fila["veredicto_codigo"], "ASUMIR")
        self.assertIn("cobras", fila["motivo_detallado"])

    def test_cobrar_menos_de_lo_que_vale_y_no_poder_protegerlo_aconseja_vender(self) -> None:
        plantilla = _con(_once(), "MC-1", clausula=6_000_000, tu_once_pierde_sin_el=0.5)
        resultado = _evaluar(plantilla, [_rival("Luis", 30_000_000)], saldo=20_000_000)
        fila = _fila(resultado, "proteger", "MC-1")
        self.assertEqual(fila["veredicto_codigo"], "VENDER_ANTES")

    def test_la_suma_de_las_subidas_recomendadas_nunca_supera_la_caja(self) -> None:
        plantilla = _once()
        for player_id in ("DEL-0", "DEL-1", "MC-0"):
            _con(plantilla, player_id, clausula=8_000_000, tu_once_pierde_sin_el=3.0)
        resultado = _evaluar(plantilla, [_rival("Luis", 12_000_000)], saldo=5_000_000)
        gastado = sum((fila["subida_recomendada"] or {}).get("coste_eur", 0) for fila in resultado["proteger"])
        self.assertEqual(gastado, 2 * 2_125_000)
        self.assertLessEqual(gastado, 5_000_000)
        self.assertEqual(resultado["resumen"]["coste_proteger_eur"], gastado)
        # El tercero ya no tiene caja: se le avisa en lugar de recomendarle algo imposible.
        codigos = [fila["veredicto_codigo"] for fila in resultado["proteger"]]
        self.assertIn("SIN_CAJA", codigos)

    def test_un_rival_con_la_posicion_floja_se_senala(self) -> None:
        plantilla = _con(_once(), "DEF-0", clausula=8_000_000, tu_once_pierde_sin_el=2.0)
        resultado = _evaluar(plantilla, [_rival("Luis", 12_000_000, ["DEF"]), _rival("Ana", 12_000_000, ["POR"])])
        fila = _fila(resultado, "proteger", "DEF-0")
        self.assertEqual(fila["necesitan_su_posicion"], ["Luis"])

    def test_jugador_bloqueado_mas_alla_del_cierre_no_esta_en_peligro(self) -> None:
        lock = {"expires_at": (CIERRE + timedelta(hours=5)).isoformat()}
        plantilla = _con(_once(), "DEL-1", clausula=8_000_000, bloqueo=lock)
        resultado = _evaluar(plantilla, [_rival("Luis", 12_000_000)])
        self.assertTrue(all(fila["player_id"] != "DEL-1" for fila in resultado["proteger"]))
        self.assertGreaterEqual(resultado["resumen"]["bloqueadas"], 1)

    def test_blindado_o_con_clausula_alta_y_nadie_con_caja_queda_fuera(self) -> None:
        plantilla = _con(_once(), "DEL-2", blindado=True, clausula=8_000_000)
        resultado = _evaluar(plantilla, [_rival("Luis", 3_000_000)])
        self.assertEqual(resultado["proteger"], [])
        self.assertGreaterEqual(resultado["resumen"]["seguros"], 1)

    def test_clausula_fragil_se_vigila_aunque_nadie_pueda_pagarla(self) -> None:
        plantilla = _con(_once(), "MC-2", clausula=9_000_000)
        resultado = _evaluar(plantilla, [_rival("Luis", 3_000_000)])
        fila = _fila(resultado, "proteger", "MC-2")
        self.assertEqual(fila["riesgo"], "BAJO")
        self.assertEqual(resultado["resumen"]["en_peligro"], 0)

    def test_orden_por_riesgo(self) -> None:
        plantilla = _once()
        _con(plantilla, "DEL-0", clausula=8_000_000, tu_once_pierde_sin_el=3.0)
        _con(plantilla, "MC-0", clausula=8_000_000, en_xi=False, tu_once_pierde_sin_el=0.0)
        resultado = _evaluar(plantilla, [_rival("Luis", 12_000_000)])
        riesgos = [fila["riesgo"] for fila in resultado["proteger"]]
        self.assertEqual(riesgos, sorted(riesgos, key=["ALTO", "MEDIO", "BAJO"].index))
        self.assertEqual(resultado["proteger"][0]["player_id"], "DEL-0")


    def test_una_clausula_que_nadie_pagaria_no_esta_en_peligro(self) -> None:
        plantilla = _con(_once(), "DEF-1", clausula=40_000_000, valor_justo=8_000_000)
        resultado = _evaluar(plantilla, [_rival("Luis", 50_000_000)])
        self.assertTrue(all(fila["player_id"] != "DEF-1" for fila in resultado["proteger"]))


class ClausulazosTests(unittest.TestCase):
    def test_clausulazo_abierto_y_asequible_que_mejora_el_once(self) -> None:
        ajeno = _ajeno("rival-del", "DEL", 8.0, 6_000_000, valor_justo=9_000_000)
        resultado = _evaluar(_once(), [_rival("Luis", 1_000_000)], [ajeno])
        fila = _fila(resultado, "clausulazos", "rival-del")
        self.assertEqual(fila["veredicto_codigo"], "CLAUSULAR_YA")
        self.assertEqual(fila["cuando"], "ahora")
        self.assertAlmostEqual(fila["mejora_once"], 4.0)
        self.assertEqual(fila["margen_valor_justo_pct"], 50.0)
        self.assertEqual(fila["caja_tras"], 4_000_000)

    def test_clausulazo_bloqueado_que_se_abre_antes_del_cierre_se_programa(self) -> None:
        lock = {"expires_at": (AHORA + timedelta(hours=26)).isoformat()}
        ajeno = _ajeno("rival-del", "DEL", 8.0, 6_000_000, bloqueo=lock)
        resultado = _evaluar(_once(), [], [ajeno])
        fila = _fila(resultado, "clausulazos", "rival-del")
        self.assertEqual(fila["veredicto_codigo"], "PROGRAMAR")
        self.assertTrue(fila["cuando"].startswith("mañana"))
        self.assertFalse(fila["abierta_ahora"])

    def test_bloqueado_mas_alla_del_cierre_no_se_puede_hacer(self) -> None:
        lock = {"expires_at": (CIERRE + timedelta(hours=1)).isoformat()}
        resultado = _evaluar(_once(), [], [_ajeno("rival-del", "DEL", 8.0, 6_000_000, bloqueo=lock)])
        self.assertEqual(resultado["clausulazos"], [])

    def test_sin_caja_se_dice_cuanto_falta(self) -> None:
        ajeno = _ajeno("rival-del", "DEL", 8.0, 12_000_000)
        resultado = _evaluar(_once(), [], [ajeno], saldo=10_000_000)
        fila = _fila(resultado, "clausulazos", "rival-del")
        self.assertEqual(fila["veredicto_codigo"], "SIN_CAJA")
        self.assertEqual(fila["falta_caja_eur"], 2_000_000)

    def test_cuenta_los_rivales_que_pueden_quitartelo(self) -> None:
        ajeno = _ajeno("rival-del", "DEL", 8.0, 6_000_000)
        rivales = [_rival("Luis", 20_000_000), _rival("Ana", 9_000_000), _rival("Pepe", 1_000_000)]
        resultado = _evaluar(_once(), rivales, [ajeno])
        # Luis es el dueño y no compite por su propio jugador: solo Ana puede pagar la misma cláusula.
        self.assertEqual(_fila(resultado, "clausulazos", "rival-del")["rivales_que_pueden_quitartelo"], 1)

    def test_ventana_cerrada_no_hay_clausulazos(self) -> None:
        ajeno = _ajeno("rival-del", "DEL", 8.0, 6_000_000)
        resultado = _evaluar(_once(), [], [ajeno], cierre=AHORA - timedelta(hours=1))
        self.assertEqual(resultado["clausulazos"], [])
        self.assertFalse(resultado["resumen"]["ventana_abierta"])

    def test_oportunidad_de_valor_aunque_no_mejore_el_once(self) -> None:
        ajeno = _ajeno("rival-mc", "MC", 1.0, 5_000_000, valor_justo=8_000_000)
        resultado = _evaluar(_once(), [], [ajeno])
        self.assertEqual(_fila(resultado, "clausulazos", "rival-mc")["veredicto_codigo"], "OPORTUNIDAD")

    def test_ni_mejora_ni_valor_se_descarta_y_el_orden_prefiere_lo_asequible(self) -> None:
        malo = _ajeno("malo", "MC", 1.0, 9_000_000, valor_justo=9_000_000)
        caro = _ajeno("caro", "DEL", 9.0, 13_000_000)
        bueno = _ajeno("bueno", "DEL", 7.0, 5_000_000)
        resultado = _evaluar(_once(), [], [malo, caro, bueno])
        ids = [fila["player_id"] for fila in resultado["clausulazos"]]
        self.assertNotIn("malo", ids)
        self.assertEqual(ids, ["bueno", "caro"])
        self.assertEqual(resultado["resumen"]["clausulazos_listos"], 1)


    def test_un_clausulazo_que_ni_vendiendo_el_banquillo_se_paga_no_aparece(self) -> None:
        resultado = _evaluar(_once(), [], [_ajeno("imposible", "DEL", 9.0, 40_000_000)], saldo=10_000_000)
        self.assertEqual(resultado["clausulazos"], [])


class IntegracionTests(unittest.TestCase):
    def test_build_strategy_publica_el_asesor_de_clausulas(self) -> None:
        xi = []
        for position, count in (("POR", 1), ("DEF", 4), ("MC", 3), ("DEL", 3)):
            for index in range(count):
                xi.append(
                    {
                        "player_id": f"{position}-{index}",
                        "nickname": f"{position}{index}",
                        "position": position,
                        "jornada_ev": 4.0,
                        "p_titular": 0.9,
                        "market_value": 8_000_000,
                        "buyout_clause": 8_000_000 if position == "DEL" and index == 0 else 40_000_000,
                        "clause_lock": {"is_locked": False},
                    }
                )
        board = {
            "squads": {
                "squads": [
                    {"team_id": "own", "is_self": True, "manager_name": "Yo", "cash": 6_000_000, "players": xi},
                    {
                        "team_id": "rival",
                        "is_self": False,
                        "manager_name": "Luis",
                        "cash": 12_000_000,
                        "players": [
                            {
                                "player_id": "joya",
                                "nickname": "Joya",
                                "position": "DEL",
                                "market_value": 5_000_000,
                                "buyout_clause": 5_000_000,
                                "clause_lock": {"is_locked": False},
                                "jornada_ev": 9.0,
                                "p_titular": 0.9,
                            }
                        ],
                    },
                ]
            },
            "market": {"listings": []},
            "trends": {"players": []},
            "optimize": {"xi": xi, "benched": [], "excluded": []},
        }
        informe = build_strategy(board, now=AHORA)["asesor_clausulas"]
        peligro = {fila["player_id"]: fila for fila in informe["proteger"]}
        self.assertIn("DEL-0", peligro)
        self.assertEqual(peligro["DEL-0"]["rival_mas_rico"]["manager"], "Luis")
        self.assertGreater(peligro["DEL-0"]["clausula_perfecta"]["clausula_objetivo"], 12_000_000)
        joya = {fila["player_id"]: fila for fila in informe["clausulazos"]}["joya"]
        self.assertEqual(joya["propietario"], "Luis")
        self.assertEqual(joya["veredicto_codigo"], "CLAUSULAR_YA")
        self.assertEqual(informe["resumen"]["clausulazos_listos"], 1)
        radar = {fila["player_id"]: fila for fila in informe["radar_anti_robo"]}
        self.assertEqual(radar["DEL-0"]["estado"], "RIESGO_ALTO")
        self.assertEqual(radar["DEL-0"]["badge"], "rojo")
        self.assertIn("1 rivales tienen caja", radar["DEL-0"]["consejo"])
        self.assertEqual(radar["DEL-1"]["estado"], "SOBREPROTEGIDO")
        self.assertEqual(radar["DEL-1"]["badge"], "verde")


class RadarAntiRoboTests(unittest.TestCase):
    def _jugador(self, player_id: str, clausula: int, valor: int, abre: object) -> dict:
        return {
            "player_id": player_id,
            "nombre": player_id,
            "clausula": clausula,
            "valor_mercado": valor,
            "prevision_7d_pct": 10,
            "clausulaAbre": abre,
        }

    def test_vulnerable_con_caja_rival_es_riesgo_alto(self) -> None:
        filas = auditar_clausulas_plantilla(
            [self._jugador("chollo", 8_000_000, 10_000_000, AHORA - timedelta(days=1))],
            [{"dineroEstimado": 9_000_000}, {"dineroEstimado": 3_000_000}],
            ahora=AHORA,
        )
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["estado"], "RIESGO_ALTO")
        self.assertEqual(filas[0]["rivales_con_caja"], 1)
        self.assertIn("¡Blíndalo hoy!", filas[0]["consejo"])

    def test_vulnerable_sin_caja_es_riesgo_cero(self) -> None:
        filas = auditar_clausulas_plantilla(
            [self._jugador("chollo", 8_000_000, 10_000_000, {"is_locked": False})],
            [{"dineroEstimado": 1_000_000, "saldo": 50_000_000}],
            ahora=AHORA,
        )
        self.assertEqual(filas[0]["estado"], "RIESGO_CERO")
        self.assertEqual(filas[0]["badge"], "gris")
        self.assertEqual(filas[0]["rivales_con_caja"], 0)

    def test_sobreprotegido_no_depende_de_la_caja(self) -> None:
        filas = auditar_clausulas_plantilla(
            [self._jugador("banco", 13_000_000, 10_000_000, AHORA + timedelta(days=2))],
            [{"dineroEstimado": 40_000_000}],
            ahora=AHORA,
        )
        self.assertEqual(filas[0]["estado"], "SOBREPROTEGIDO")
        self.assertEqual(filas[0]["badge"], "verde")
        self.assertIn("ganas +3,0M", filas[0]["consejo"])
        self.assertIn("No subir cláusula", filas[0]["consejo"])

    def test_escasez_si_lo_que_cobras_no_alcanza_para_reponerlo(self) -> None:
        # Cláusula 1,33× el valor: antes "sobreprotegido". Pero el sustituto cuesta 31 M.
        jugador = self._jugador("lejeune", 13_300_000, 10_000_000, AHORA + timedelta(days=2))
        jugador.update({"position": "DF", "jornada": 6.0})
        alternativas = [
            {"player_id": "caro", "position": "DF", "coste": 31_000_000, "xp": 5.9},
            {"player_id": "peor", "position": "DF", "coste": 4_000_000, "xp": 3.0},
            {"player_id": "otra_pos", "position": "MC", "coste": 2_000_000, "xp": 9.0},
        ]
        filas = auditar_clausulas_plantilla([jugador], [{"dineroEstimado": 40_000_000}], ahora=AHORA, alternativas=alternativas)
        self.assertEqual(filas[0]["estado"], "ESCASEZ")
        self.assertEqual(filas[0]["coste_reposicion"], 31_000_000)
        self.assertEqual(filas[0]["perdida_si_te_lo_roban"], 17_700_000)
        self.assertIn("Pierdes 17,7M", filas[0]["consejo"])

    def test_con_sustituto_barato_sigue_sobreprotegido(self) -> None:
        jugador = self._jugador("banco", 13_000_000, 10_000_000, AHORA + timedelta(days=2))
        jugador.update({"position": "DF", "jornada": 6.0})
        alternativas = [{"player_id": "ok", "position": "DF", "coste": 9_000_000, "xp": 5.8}]
        filas = auditar_clausulas_plantilla([jugador], [{"dineroEstimado": 40_000_000}], ahora=AHORA, alternativas=alternativas)
        self.assertEqual(filas[0]["estado"], "SOBREPROTEGIDO")
        self.assertEqual(filas[0]["perdida_si_te_lo_roban"], 0)

    def test_sin_sustituto_la_reposicion_es_un_sesenta_por_ciento_mas(self) -> None:
        jugador = {"player_id": "x", "position": "DL", "jornada": 7.0}
        self.assertEqual(coste_reposicion(jugador, [], 20_000_000), (32_000_000, False))
        ya = {"player_id": "y", "position": "DL", "coste": 25_000_000, "xp": 6.8}
        self.assertEqual(coste_reposicion(jugador, [ya], 20_000_000), (25_000_000, True))

    def test_candado_a_tres_dias_o_mas_no_entra(self) -> None:
        lejos = (AHORA + timedelta(days=3)).isoformat()
        filas = auditar_clausulas_plantilla(
            [self._jugador("lejos", 8_000_000, 10_000_000, lejos)],
            [{"dineroEstimado": 20_000_000}],
            ahora=AHORA,
        )
        self.assertEqual(filas, [])

    def test_multiplo_intermedio_no_genera_tarjeta(self) -> None:
        filas = auditar_clausulas_plantilla(
            [self._jugador("medio", 12_000_000, 10_000_000, AHORA - timedelta(hours=1))],
            [{"dineroEstimado": 20_000_000}],
            ahora=AHORA,
        )
        self.assertEqual(filas, [])


if __name__ == "__main__":
    unittest.main()

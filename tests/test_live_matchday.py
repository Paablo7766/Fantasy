"""Jornada en juego: puntos reales + xP pendiente, clasificación virtual y premio."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from toolbox.engine.live_matchday import (
    ABONO_JORNADA_EUR,
    EUROS_POR_PUNTO,
    construir_jornada_en_juego,
)

AHORA = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
JUGADO = "2026-11-21T20:00:00+00:00"  # J13: el partido de la J12 ya se jugó
HOY = "2026-11-08T20:00:00+00:00"  # pendiente de hoy
EN_JUEGO = "2026-11-08T11:30:00+00:00"  # empezó hace 30 min


def _fila(pid: str, pos: str, club: str, kick: str, xp: float) -> dict:
    return {
        "player_id": pid,
        "name": f"J{pid}",
        "nickname": f"J{pid}",
        "position": pos,
        "club": club,
        "own_expected_points": xp,
        "p_titular": 1.0,
        "lineup_status": "titular",
        "fixture": {"kickoff": kick},
    }


#: 1 POR, 4 DEF, 4 MC, 2 DEL = 11 (4-4-2 válido).
POSICIONES = ["POR"] + ["DEF"] * 4 + ["MC"] * 4 + ["DEL"] * 2


def _equipo(prefijo: str, kicks: list[str], xp: float = 5.0, **extra) -> tuple[dict, list[dict]]:
    filas = [_fila(f"{prefijo}{i}", pos, f"club{i}", kicks[i], xp) for i, pos in enumerate(POSICIONES)]
    squad = {"team_id": prefijo, "manager_name": prefijo, "players": [dict(f) for f in filas], **extra}
    return squad, filas


def _tablero(propio_kicks, rival_kicks):
    propio, f1 = _equipo("a", propio_kicks, is_self=True, rank=2, points=100, cash_eur=1_000_000)
    rival, f2 = _equipo("b", rival_kicks, rank=1, points=120, cash_eur=-5)
    squads = {"squads": [propio, rival]}
    trends = {"players": [*f1, *f2]}
    return squads, trends


def _actas(pid_puntos: dict[str, tuple[float, float]], jornada: int = 12) -> dict:
    return {pid: {"weeks": {jornada: [p, m]}} for pid, (p, m) in pid_puntos.items()}


def test_jornada_no_empezada_o_cerrada_no_esta_activa():
    # Nadie ha jugado: todos los partidos siguen en el bloque futuro.
    squads, trends = _tablero([HOY] * 11, [HOY] * 11)
    assert construir_jornada_en_juego(squads, trends, {}, now=AHORA)["activa"] is False
    # Todos jugaron: no queda bloque en curso.
    squads, trends = _tablero([JUGADO] * 11, [JUGADO] * 11)
    assert construir_jornada_en_juego(squads, trends, {}, now=AHORA, jornada=12)["activa"] is False


def test_separa_puntos_reales_de_xp_pendiente():
    kicks = [JUGADO, JUGADO, JUGADO] + [HOY] * 8
    squads, trends = _tablero(kicks, [JUGADO] * 11)
    actas = _actas({"a0": (8.0, 90.0), "a1": (0.0, 90.0), "a2": (11.0, 90.0)})
    live = construir_jornada_en_juego(squads, trends, actas, now=AHORA)
    assert live["activa"] is True and live["jornada"] == 12
    propio = live["propio"]
    assert propio["puntos_actuales"] == 19.0
    assert propio["jugadores_jugados"] == 3 and propio["jugadores_pendientes"] == 8
    assert propio["resumen_jugados"] == "3/11 jugados, faltan 8"
    assert propio["xp_pendiente"] == 40.0
    assert propio["puntos_proyectados_final_jornada"] == 59.0
    assert [f["player_id"] for f in propio["roscos"]] == ["a1"]
    assert [f["player_id"] for f in propio["explosiones"]] == ["a2"]
    assert len(propio["pendientes"]) == 8


def test_no_jugo_es_rosco_y_no_suma_xp():
    kicks = [JUGADO] + [HOY] * 10
    squads, trends = _tablero(kicks, [JUGADO] * 11)
    live = construir_jornada_en_juego(squads, trends, _actas({"a0": (0.0, 0.0)}), now=AHORA)
    propio = live["propio"]
    fila = next(f for f in propio["once"] if f["player_id"] == "a0")
    assert fila["no_jugo"] is True and fila["rosco"] is True
    assert propio["puntos_actuales"] == 0.0


def test_partido_en_juego_cuenta_como_pendiente_y_sin_acta_usa_xp():
    kicks = [EN_JUEGO, JUGADO] + [HOY] * 9
    squads, trends = _tablero(kicks, [JUGADO] * 11)
    live = construir_jornada_en_juego(squads, trends, {}, now=AHORA, jornada=12)
    propio = live["propio"]
    assert propio["jugadores_en_juego"] == 1
    assert propio["sin_acta"] == 1
    # 10 con xP (9 de hoy + 1 en juego) + 1 jugado sin acta con xP: todo estimado.
    assert propio["puntos_actuales"] == 0.0
    assert propio["puntos_proyectados_final_jornada"] == 55.0


def test_clasificacion_virtual_premio_y_recorte_al_lider():
    kicks = [JUGADO] * 6 + [HOY] * 5
    squads, trends = _tablero(kicks, [JUGADO] * 11)
    actas = _actas({f"a{i}": (6.0, 90.0) for i in range(6)} | {f"b{i}": (4.0, 90.0) for i in range(11)})
    live = construir_jornada_en_juego(squads, trends, actas, now=AHORA)
    propio, lider = live["propio"], live["lider"]
    assert propio["puntos_proyectados_final_jornada"] == 36.0 + 25.0
    assert lider["manager"] == "b" and lider["puntos_proyectados_final_jornada"] == 44.0
    assert propio["puesto_jornada"] == 1
    assert propio["recorte_vs_lider"] == 17.0
    assert propio["premio_jornada_eur"] == int(61 * EUROS_POR_PUNTO) + ABONO_JORNADA_EUR
    assert live["liquidez_entrante_eur"] == propio["premio_jornada_eur"]
    # Tabla virtual: 100 + 61 contra 120 + 44.
    assert propio["puntos_tabla_proyectados"] == 161.0
    assert propio["recorte_tabla_vs_lider"] == -3.0
    assert propio["caja_proyectada_lunes_eur"] == 1_000_000 + propio["premio_jornada_eur"]
    rival = next(e for e in live["clasificacion_jornada"] if not e["is_self"])
    assert rival["saldo_negativo"] is True and rival["dif_jornada_vs_ti"] == 17.0


def test_plantilla_sin_once_completo_se_avisa():
    squads, trends = _tablero([JUGADO] * 6 + [HOY] * 5, [JUGADO] * 11)
    squads["squads"][0]["players"] = squads["squads"][0]["players"][:9]
    propio = construir_jornada_en_juego(squads, trends, {}, now=AHORA, jornada=12)["propio"]
    assert propio["once_completo"] is False and propio["puntos_proyectados_final_jornada"] == 0.0


def test_inicio_y_fin_de_bloque_toleran_horas_sueltas():
    # Un partido que empezó hace menos de 115 min sigue siendo del bloque en curso.
    kicks = [JUGADO] * 5 + [(AHORA - timedelta(minutes=100)).isoformat()] * 6
    squads, trends = _tablero(kicks, [JUGADO] * 11)
    live = construir_jornada_en_juego(squads, trends, {}, now=AHORA, jornada=12)
    assert live["activa"] is True and live["propio"]["jugadores_en_juego"] == 6

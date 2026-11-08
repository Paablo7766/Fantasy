"""Jornada objetivo única: con la J12 en curso, todo habla de la J13; el en vivo conserva la J12."""

from __future__ import annotations

from datetime import datetime, timezone

from toolbox.engine.live_matchday import _vista_en_juego
from toolbox.own_intel import promover_jornada_bloqueada

AHORA = datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)
J12_HOY = "2026-11-08T17:30:00+00:00"
J13 = "2026-11-22T17:30:00+00:00"


def _celda(kickoff: str, rival: str) -> dict:
    return {"kickoff": kickoff, "opponent": rival, "is_home": True, "recommendation_pct": 50}


def _jugadores() -> list[dict]:
    radu = {
        "player_id": "radu",
        "club": "Celta",
        "own_expected_points": 8.8,
        "own_ceiling_points": 16.0,
        "own_xp_siguientes": [6.5, 5.0],
        "fantasy_price": 50_000_000,
        "own_calendar": [_celda(J12_HOY, "Levante"), _celda(J13, "Real Madrid"), _celda("2026-11-29T17:00:00+00:00", "Elche")],
        "fixture": {"kickoff": J12_HOY, "opponent": "Levante", "home": True},
    }
    # Sevilla y Athletic ya jugaron la J12: su próximo partido es de la J13.
    sevilla = {"player_id": "salas", "club": "Sevilla FC", "own_expected_points": 5.7, "own_xp_siguientes": [5.0],
               "own_calendar": [_celda("2026-11-20T20:00:00+00:00", "Betis")]}
    athletic = {"player_id": "canales", "club": "Athletic Club", "own_expected_points": 4.7, "own_xp_siguientes": [4.0],
                "own_calendar": [_celda("2026-11-21T15:00:00+00:00", "Espanyol")]}
    return [radu, sevilla, athletic]


def test_con_la_jornada_en_curso_el_xp_y_el_rival_son_de_la_j13():
    jugadores = _jugadores()
    assert promover_jornada_bloqueada(jugadores, now=AHORA) == 1
    radu = jugadores[0]
    assert radu["own_expected_points"] == 6.5
    assert radu["own_calendar"][0]["opponent"] == "Real Madrid"
    assert radu["fixture"]["opponent"] == "Real Madrid" and radu["fixture"]["kickoff"] == J13
    assert radu["own_xp_siguientes"] == [5.0]
    assert round(radu["own_ceiling_points"], 2) == round(16.0 * 6.5 / 8.8, 2)
    assert radu["own_en_juego"] == {"kickoff": J12_HOY, "opponent": "Levante", "is_home": True, "expected_points": 8.8}
    # Quien ya jugó no se toca.
    assert jugadores[1]["own_expected_points"] == 5.7


def test_sin_jornada_en_curso_no_se_corre_nada():
    jugadores = _jugadores()
    lunes = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
    jugadores[0]["own_calendar"] = jugadores[0]["own_calendar"][1:]
    jugadores[0]["fixture"]["kickoff"] = J13
    assert promover_jornada_bloqueada(jugadores, now=lunes) == 0


def test_el_en_vivo_recupera_el_partido_de_la_j12():
    jugadores = _jugadores()
    promover_jornada_bloqueada(jugadores, now=AHORA)
    vista = _vista_en_juego(jugadores[0])
    assert vista["own_expected_points"] == 8.8
    assert vista["fixture"]["kickoff"] == J12_HOY
    assert vista["own_calendar"][0]["opponent"] == "Levante"
    assert jugadores[0]["own_expected_points"] == 6.5  # la vista no toca al original

"""Coherencia del xP del once: sin rellenar ceros, solver alineado con la UI."""

from toolbox.analyzer import ObjectiveWeights, candidate_from_player
from toolbox.own_intel import _condicional_tras_mezcla

PLAYER = {"player_id": "1", "position": "DEL", "name": "X", "average_points": 7.5}


def _cand(trend):
    return candidate_from_player(PLAYER, trend, weights=ObjectiveWeights(), ordinal=0)


def test_xp_propio_cero_no_se_rellena_con_media_ni_af():
    for extra in ({}, {"af_expected_points": 6.0}):
        c = _cand({"matching_confidence": 1, "own_expected_points": 0.0, "p_titular": 0.05, **extra})
        assert c.jornada_ev == 0.0
        assert c.objective == 0.0


def test_sin_xp_propio_el_solver_valora_lo_que_se_muestra():
    c = _cand({"matching_confidence": 1, "p_titular": 0.6})
    assert c.jornada_ev == 4.5
    assert c.objective == c.jornada_ev


def test_si_titular_reescalado_y_nunca_bajo_el_xp():
    player = {"own_xp_modelo": 4.0, "own_expected_points": 5.0, "own_xp_fuente": "af_mezcla"}
    assert _condicional_tras_mezcla(player, 4.4) == 5.5
    player = {"own_expected_points": 4.0}
    assert _condicional_tras_mezcla(player, 3.5) == 4.0

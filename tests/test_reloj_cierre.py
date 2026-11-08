"""Reloj de Inicio: con la jornada en curso, la cuenta atrás va al saque de la siguiente."""

from __future__ import annotations

from datetime import datetime, timezone

from toolbox.jornada_plan import build_clock, next_lock

AHORA = datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)  # domingo de J12, antes del partido de las 14:00


def _jugador(club: str, saque: str, siguiente: str | None = None) -> dict:
    calendario = [{"kickoff": saque}]
    if siguiente:
        calendario.append({"kickoff": siguiente})
    return {"club": club, "fixture": {"kickoff": saque}, "own_calendar": calendario}


def _trends() -> dict:
    # Sevilla y Athletic ya jugaron la J12: su próximo partido es de la J13.
    # Celta y Betis juegan hoy la J12; su siguiente es la J13.
    return {
        "players": [
            _jugador("Sevilla FC", "2026-11-20T20:00:00+00:00"),
            _jugador("Athletic Club", "2026-11-21T15:00:00+00:00"),
            _jugador("Celta", "2026-11-08T13:00:00+00:00", "2026-11-22T17:30:00+00:00"),
            _jugador("Real Betis", "2026-11-08T15:15:00+00:00", "2026-11-20T20:00:00+00:00"),
        ]
    }


def test_jornada_en_curso_apunta_al_saque_de_la_siguiente():
    assert next_lock(_trends(), now=AHORA) == "2026-11-20T20:00:00+00:00"


def test_reloj_sin_desbloqueos_pasados_y_cierre_de_clausulazos_24h_antes():
    squads = {
        "squads": [
            {
                "manager_name": "yo",
                "is_self": True,
                "players": [
                    {"player_id": "1", "nickname": "Viejo", "clause_lock": {"present": True, "expires_at": "2026-10-27T13:08:16+00:00"}},
                    {"player_id": "2", "nickname": "Radu", "clause_lock": {"present": True, "expires_at": "2026-11-15T13:08:16+00:00"}},
                ],
            }
        ]
    }
    eventos, kickoff, cierre_clausulas = build_clock(trends=_trends(), squads=squads, decisions=[], now=AHORA)
    assert kickoff == "2026-11-20T20:00:00+00:00"
    assert cierre_clausulas["at"] == "2026-11-19T20:00:00+00:00"
    desbloqueos = [e["nickname"] for e in eventos if e["kind"] == "desbloqueo"]
    assert desbloqueos == ["Radu"]

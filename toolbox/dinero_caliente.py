"""Víctima de un clausulazo reciente: dinero caliente que se gastará en horas.

Medido en la liga real: el 65 % (24 de 37) de las víctimas de un clausulazo se
gasta lo cobrado en menos de 24 horas (mediana 17,7 h), comprando o clausulando
de rebote. Mientras dure esa ventana el rival es peligroso para nuestras pujas
y para nuestras cláusulas. Solo lee el flujo de actividad; no decide nada.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from toolbox.league_history import _parse_at

_MADRID = ZoneInfo("Europe/Madrid")

#: Cuánto tiempo después del cobro se sigue marcando al rival.
VENTANA_HORAS = 36.0
#: Fracción de víctimas que gasta el cobro en menos de 24 h (24 de 37).
PROB_GASTO_INMEDIATO = 24 / 37
PROB_GASTO_PCT = 65


def _millones(importe: int) -> str:
    return f"{importe / 1_000_000:.1f}".replace(".", ",")


def aviso_dinero_caliente(importe: int, jugador: str, horas: float) -> str:
    """Texto de la alerta, tal como se enseña en Rivales, Cláusulas y Pujas."""
    cuando = "menos de 1" if horas < 1 else f"{horas:.0f}".replace(".", ",")
    return (
        f"🔥 Dinero caliente: acaba de cobrar +{_millones(importe)} M€ por cláusula de {jugador} "
        f"hace {cuando} h ({PROB_GASTO_PCT}% prob. de gasto inmediato en <24h)"
    )


def victimas_recientes(
    ledgers: list[dict[str, Any]] | None,
    squads: list[dict[str, Any]] | None,
    names: dict[str, str] | None = None,
    *,
    now: datetime | None = None,
    horas: float = VENTANA_HORAS,
) -> dict[str, dict[str, Any]]:
    """``{team_id: alerta}`` de los rivales a los que han clausulado en las últimas ``horas``.

    Cada cláusula del flujo (``kind == clause`` con ``counterparty_manager_id``)
    nombra a la víctima. Si hay varias dentro de la ventana, el importe se suma
    y el jugador y la hora son los del cobro más reciente.
    """
    ahora = (now or datetime.now(timezone.utc)).astimezone(_MADRID)
    manager_a_team: dict[str, str] = {}
    for squad in squads or []:
        if not isinstance(squad, dict):
            continue
        manager = squad.get("manager_id")
        team = squad.get("team_id")
        if isinstance(manager, (str, int)) and not isinstance(manager, bool) and isinstance(team, str) and team:
            manager_a_team[str(manager)] = team
    vistas: set[tuple[Any, ...]] = set()
    cobros: dict[str, list[tuple[datetime, int, str | None]]] = {}
    for ledger in ledgers or []:
        if not isinstance(ledger, dict):
            continue
        for event in ledger.get("events") or []:
            if not isinstance(event, dict) or event.get("kind") != "clause":
                continue
            victima = event.get("counterparty_manager_id")
            importe = event.get("amount_eur")
            momento = _parse_at(event.get("at"))
            if (
                victima is None
                or isinstance(importe, bool)
                or not isinstance(importe, int)
                or importe <= 0
                or momento is None
            ):
                continue
            clave = (event.get("at"), importe, event.get("player_id"), str(victima))
            if clave in vistas:
                continue
            vistas.add(clave)
            team = manager_a_team.get(str(victima), str(victima))
            cobros.setdefault(team, []).append((momento, importe, event.get("player_id")))
    salida: dict[str, dict[str, Any]] = {}
    for team, filas in cobros.items():
        dentro = [
            fila for fila in filas if 0 <= (ahora - fila[0]).total_seconds() / 3600.0 <= float(horas)
        ]
        if not dentro:
            continue
        dentro.sort(key=lambda fila: fila[0])
        ultimo_momento, _importe, ultimo_jugador = dentro[-1]
        total = sum(fila[1] for fila in dentro)
        hace = (ahora - ultimo_momento).total_seconds() / 3600.0
        nombre = (names or {}).get(str(ultimo_jugador)) if ultimo_jugador is not None else None
        nombre = nombre or "un jugador"
        salida[team] = {
            "importe_eur": total,
            "jugador_id": str(ultimo_jugador) if ultimo_jugador is not None else None,
            "jugador": nombre,
            "hace_horas": round(hace, 1),
            "at": ultimo_momento.isoformat(),
            "n_cobros": len(dentro),
            "prob_gasto_24h": round(PROB_GASTO_INMEDIATO, 3),
            "aviso": aviso_dinero_caliente(total, nombre, hace),
        }
    return salida

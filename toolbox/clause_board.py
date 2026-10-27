"""Tablero completo de cláusulas rivales, con las subidas ya detectadas.

El plan de cláusulas solo mira los jugadores que cumplen la regla de oro (A/B):
son los chollos, pero dejan fuera al 60 % de la liga. Cuando se acerca un
desbloqueo eso es ir a ciegas: no se ve si el rival acaba de mover la cláusula
ni cuánto pide por un jugador que no entra en la regla.

Este módulo no decide nada ni sale a la red. Cruza dos fuentes que ya están en
disco y devuelve una fila por jugador con cláusula:

1. La foto de plantillas de hoy (``squads``): cláusula actual y candado.
2. El histórico de cláusulas (``clause_snapshot_history.json``) y el log de
   gasto oculto (``hidden_expenses_log.json``): cuánto valía antes y qué
   subidas se detectaron, con su día.

``prev_clause_eur`` es la cláusula del último día guardado **anterior** a la
foto: si hoy vale más, hubo subida en las últimas 24 h. Sin histórico el campo
queda ausente; nunca se rellena con una estimación.

La cláusula de un jugador **fichado** no es una constante: se queda en
``max(1.000.000, precio pagado, valor de mercado)``. Verificado con la liga
real (55 de 55 fichajes): cuando el valor sube por encima del precio, la
cláusula sube sola y el rival no paga nada. Por eso ``raised_today`` no
distingue un movimiento gratuito de una subida pagada; para eso están
``clause_floor_eur`` (suelo), ``clause_auto_raise_eur`` (lo que subió porque
subió el valor) y ``clause_paid_raise_eur`` (lo que el rival pagó de verdad).

El coste de una subida se publica a la regla real de la app (1:2, redondeo al
alza). El auditor de caja usa 0,20 a propósito para no pasarse cobrando; aquí
el número es informativo y no entra en ninguna cota.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from toolbox.analyzer import clause_multiple, exposed_clause_rule
from toolbox.cache import cache_root
from toolbox.rival_intel import (
    CLAUSE_SNAPSHOTS_FILENAME,
    HIDDEN_EXPENSES_FILENAME,
    _clause_map,
    _player_view,
)

__all__ = ["build_clause_board", "clause_cost_eur"]

_COMMAND = "clause-board"

#: Suelo de cláusula que fija la app: nadie puede bajarla de aquí.
CLAUSE_MIN_EUR = 1_000_000


def clause_cost_eur(increase_eur: int | None) -> int | None:
    """Coste de subir la cláusula: la mitad del incremento, redondeando al alza."""
    if not isinstance(increase_eur, int) or isinstance(increase_eur, bool) or increase_eur <= 0:
        return None
    return int(math.ceil(increase_eur / 2))


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _roster(squads: Any) -> list[dict[str, Any]]:
    if not isinstance(squads, Mapping):
        return []
    rows = squads.get("squads")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, Mapping)]
    if isinstance(squads.get("players"), list):
        return [squads]
    return []


def _as_iso_day(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) >= 10:
        head = value[:10]
        if head[4] == "-" and head[7] == "-":
            return head
    return None


def _average(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number:
        return None
    return round(number, 2)


def _days_between(from_day: str, to_day: str) -> int | None:
    try:
        start = date.fromisoformat(from_day)
        end = date.fromisoformat(to_day)
    except ValueError:
        return None
    return (end - start).days


def _lock_view(lock: Any) -> dict[str, Any]:
    body = lock if isinstance(lock, Mapping) else {}
    return {
        "present": body.get("present") is True,
        "is_locked": body.get("is_locked") if isinstance(body.get("is_locked"), bool) else None,
        "local_date": body.get("local_date") if isinstance(body.get("local_date"), str) else None,
        "local_time": body.get("local_time") if isinstance(body.get("local_time"), str) else None,
        "local_clock": body.get("local_clock") if isinstance(body.get("local_clock"), str) else None,
        "expires_at": body.get("expires_at") if isinstance(body.get("expires_at"), str) else None,
        "timezone": body.get("timezone") if isinstance(body.get("timezone"), str) else None,
    }


def _history(
    *,
    photo_day: str | None,
    snapshot_path: Path,
    expenses_path: Path,
) -> tuple[str | None, dict[str, dict[str, int]], dict[tuple[str, str], list[dict[str, Any]]]]:
    """Día de referencia, cláusulas de ese día y subidas ya fechadas por jugador."""
    snapshot = _load_json(snapshot_path) or {}
    days = snapshot.get("days") if isinstance(snapshot.get("days"), Mapping) else {}
    available = sorted(
        day for day in (_as_iso_day(key) for key in days) if day is not None
    )
    from_day: str | None = None
    previous: dict[str, dict[str, int]] = {}
    if available:
        if photo_day is None:
            from_day = available[-1]
        else:
            earlier = [day for day in available if day < photo_day]
            from_day = earlier[-1] if earlier else None
        if from_day is not None:
            previous = _clause_map(days.get(from_day))

    raises: dict[tuple[str, str], list[dict[str, Any]]] = {}
    log = _load_json(expenses_path) or {}
    entries = log.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            day = _as_iso_day(entry.get("day"))
            team_id = entry.get("team_id")
            player_id = entry.get("player_id")
            if day is None or not isinstance(team_id, str) or not isinstance(player_id, str):
                continue
            before = entry.get("clause_before_eur")
            after = entry.get("clause_after_eur")
            if not isinstance(before, int) or not isinstance(after, int) or after <= before:
                continue
            raises.setdefault((team_id, player_id), []).append(
                {
                    "day": day,
                    "before_eur": before,
                    "after_eur": after,
                    "increase_eur": after - before,
                    "cost_eur": clause_cost_eur(after - before),
                }
            )
    for rows in raises.values():
        rows.sort(key=lambda row: row["day"], reverse=True)
    return from_day, previous, raises


def _acquisitions(ledgers: Any) -> dict[tuple[str, str], int]:
    """Precio pagado por jugador, de los libros de la liga (compra o cláusula).

    Es la única forma de separar una subida **pagada** de una **gratuita**: la
    cláusula de un fichado se queda en ``max(1.000.000, precio, valor)``, así
    que el tramo que sube el valor de mercado no le cuesta nada al rival.
    """
    prices: dict[tuple[str, str], int] = {}
    for ledger in ledgers if isinstance(ledgers, list) else []:
        if not isinstance(ledger, Mapping):
            continue
        team_id = ledger.get("team_id")
        if not isinstance(team_id, str) or not team_id:
            continue
        for event in ledger.get("events") or []:
            if not isinstance(event, Mapping) or event.get("kind") not in {"buy", "clause"}:
                continue
            player_id = event.get("player_id")
            amount = event.get("amount_eur")
            if not isinstance(player_id, str) or not player_id:
                continue
            if isinstance(amount, int) and not isinstance(amount, bool) and amount > 0:
                prices[(team_id, player_id)] = amount
    return prices


def _sort_row(row: dict[str, Any]) -> tuple[int, int, str, str, str]:
    lock = row.get("clause_lock") or {}
    missing = 0 if lock.get("local_date") and lock.get("local_time") else 1
    return (
        missing,
        str(lock.get("local_date") or "9999-99-99"),
        str(lock.get("local_time") or "99:99"),
        -int(row.get("buyout_clause_eur") or 0),
        str(row.get("nickname") or row.get("name") or ""),
    )


def build_clause_board(
    squads: Any,
    *,
    photo_day: Any = None,
    snapshot_path: Path | None = None,
    expenses_path: Path | None = None,
    include_self: bool = False,
    ledgers: Any = None,
) -> dict[str, Any]:
    """Una fila por jugador con cláusula, ordenada por hora de desbloqueo.

    ``photo_day`` fecha el diff contra el último día guardado anterior: sirve
    una foto vieja sin marcar subidas que no han ocurrido. ``ledgers`` (los
    libros de la liga) permiten separar la subida pagada de la automática.
    """
    roster = _roster(squads)
    if not roster:
        return {"ok": False, "command": _COMMAND, "error": "sin_plantillas", "rows": []}

    day = _as_iso_day(photo_day)
    from_day, previous, raises = _history(
        photo_day=day,
        snapshot_path=Path(snapshot_path) if snapshot_path else cache_root() / CLAUSE_SNAPSHOTS_FILENAME,
        expenses_path=Path(expenses_path) if expenses_path else cache_root() / HIDDEN_EXPENSES_FILENAME,
    )
    # Con una referencia de hace varios días el salto es real, pero llamarlo
    # «hoy» sería mentir: se marca como subida «desde la foto» y el día exacto
    # queda en ``from_day``.
    gap_days = _days_between(from_day, day) if from_day and day else None
    paid_index = _acquisitions(ledgers)

    rows: list[dict[str, Any]] = []
    for squad in roster:
        if squad.get("is_self") is True and not include_self:
            continue
        team_id = squad.get("team_id")
        if not isinstance(team_id, str) or not team_id:
            continue
        players = squad.get("players") if isinstance(squad.get("players"), list) else []
        for player in players:
            if not isinstance(player, Mapping):
                continue
            view = _player_view(player)
            player_id = view["player_id"]
            clause = view["buyout_clause"]
            if not isinstance(player_id, str) or not player_id:
                continue
            if not isinstance(clause, int) or clause <= 0:
                continue
            lock = _lock_view(player.get("clause_lock"))
            before = (previous.get(team_id) or {}).get(player_id)
            delta = clause - before if isinstance(before, int) and clause > before else None
            history = list(raises.get((team_id, player_id), []))
            # El log manda: si ya hay una subida fechada que deja la cláusula
            # donde está hoy, el salto contra la foto es esa misma subida vista
            # desde más atrás. Contarla otra vez inflaría el historial.
            logged_after = history[0]["after_eur"] if history else None
            fresh_jump = delta is not None and (logged_after is None or clause > logged_after)
            if fresh_jump:
                history.insert(
                    0,
                    {
                        "day": day,
                        "before_eur": before,
                        "after_eur": clause,
                        "increase_eur": delta,
                        "cost_eur": clause_cost_eur(delta),
                        "source": "diff_hoy" if gap_days is not None and gap_days <= 1 else "diff_foto",
                    },
                )
            latest = history[0] if history else None
            # Suelo real de la cláusula. En un fichaje es fijo (1 M€ o el precio
            # pagado) y lo que sube el valor de mercado lo empuja gratis: por eso
            # ``clause_auto_raise_eur`` no cuesta nada al rival. En un jugador de
            # reparto la cláusula no flota (verificado: 82 de 82 no se movieron
            # aunque cambiara el valor), así que cualquier salto desde la foto es
            # dinero puesto por el rival.
            paid = paid_index.get((team_id, player_id))
            market_value = view["market_value"] or 0
            if isinstance(paid, int):
                floor: int | None = max(CLAUSE_MIN_EUR, paid)
                auto_raise = max(0, min(clause, market_value) - floor)
                paid_raise = max(0, clause - max(floor, market_value))
            else:
                floor = before if isinstance(before, int) else None
                auto_raise = 0
                paid_raise = max(0, clause - floor) if floor is not None else 0
            rows.append(
                {
                    "team_id": team_id,
                    "manager_name": squad.get("manager_name"),
                    "fantasy_team_name": squad.get("fantasy_team_name"),
                    "player_id": player_id,
                    "name": view["name"],
                    "nickname": view["nickname"],
                    "position": view["position"],
                    "club": player.get("club") if isinstance(player.get("club"), str) else None,
                    "image_url": player.get("image_url") if isinstance(player.get("image_url"), str) else None,
                    "buyout_clause_eur": clause,
                    "market_value": view["market_value"],
                    "average_points": _average(player.get("average_points")),
                    "clause_multiple": clause_multiple(dict(player)),
                    "clause_rule": exposed_clause_rule(dict(player)),
                    "is_shielded": player.get("is_shielded") is True,
                    "is_locked": lock["is_locked"] is True,
                    "at_risk": lock["is_locked"] is True,
                    "clause_lock": lock,
                    "prev_clause_eur": before if isinstance(before, int) else None,
                    "clause_delta_eur": delta,
                    "clause_delta_pct": round(delta / before, 4) if delta and before else None,
                    "raised_since_photo": delta is not None,
                    "raised_today": delta is not None and gap_days is not None and gap_days <= 1,
                    "raise_latest_day": latest["day"] if latest else None,
                    "raise_latest_eur": latest["increase_eur"] if latest else None,
                    "raise_count": len(history),
                    "raises": history[:6],
                    "clause_paid_eur": paid if isinstance(paid, int) else None,
                    "clause_floor_eur": floor,
                    "clause_auto_raise_eur": auto_raise,
                    "clause_paid_raise_eur": paid_raise,
                    "clause_paid_by_rival": paid_raise > 0,
                }
            )

    rows.sort(key=_sort_row)
    locked = sum(1 for row in rows if row["is_locked"])
    return {
        "ok": True,
        "command": _COMMAND,
        "photo_day": day,
        "from_day": from_day,
        "diff_gap_days": gap_days,
        "counts": {
            "total": len(rows),
            "golden": sum(1 for row in rows if row["clause_rule"]),
            "raised_today": sum(1 for row in rows if row["raised_today"]),
            "raised_since_photo": sum(1 for row in rows if row["raised_since_photo"]),
            "raised_ever": sum(1 for row in rows if row["raise_count"]),
            "locked": locked,
            "open": len(rows) - locked,
            "paid_raise": sum(1 for row in rows if row["clause_paid_by_rival"]),
            "auto_raise": sum(1 for row in rows if row["clause_auto_raise_eur"]),
        },
        "rows": rows,
    }

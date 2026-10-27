"""Auditoría de jornada: puntos previstos del XI contra la última cifra oficial.

No reescribe entradas viejas de ``context/MEMORY.md``. Si falta la serie de un
titular, no se suma un total parcial como si la jornada estuviera completa.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from toolbox.analyzer import own_squad
from toolbox.normalize import official_week_points

_MARKER = "auditoria-xi:"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_audit(
    optimize: dict[str, Any] | None,
    squads: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    kickoff: str | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    xi = optimize.get("xi") if isinstance(optimize, dict) and isinstance(optimize.get("xi"), list) else []
    own = own_squad(squads) if isinstance(squads, dict) else None
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(own, dict):
        for player in own.get("players") or []:
            if isinstance(player, dict) and isinstance(player.get("player_id"), str):
                by_id[player["player_id"]] = player

    predicted_parts: list[float] = []
    actual_parts: list[float] = []
    missing: list[str] = []
    ids: list[str] = []
    for row in xi:
        if not isinstance(row, dict):
            continue
        player_id = row.get("player_id") if isinstance(row.get("player_id"), str) else None
        label = row.get("nickname") or row.get("name") or player_id or "jugador"
        if player_id:
            ids.append(player_id)
        expected = _number(row.get("expected_points"))
        if expected is None:
            missing.append(f"{label}: previsto")
        else:
            predicted_parts.append(expected)
        series = official_week_points(by_id.get(player_id or "", {}))
        if not series:
            missing.append(f"{label}: puntos oficiales")
        else:
            actual_parts.append(float(series[-1]))

    complete = bool(xi) and not missing and len(predicted_parts) == len(xi) and len(actual_parts) == len(xi)
    predicted = round(sum(predicted_parts), 4) if complete else None
    actual = round(sum(actual_parts), 4) if complete else None
    error = round(actual - predicted, 4) if predicted is not None and actual is not None else None
    fingerprint = None
    if complete:
        fingerprint = f"{_MARKER}{predicted}:{actual}:{','.join(sorted(ids))}"
    played = _kickoff_passed(kickoff, current)
    return {
        "ok": True,
        "complete": complete,
        "played": played,
        "predicted_points": predicted,
        "actual_points": actual,
        "error": error,
        "missing": missing,
        "xi_ids": ids,
        "fingerprint": fingerprint,
        "kickoff": kickoff,
        "at": current.astimezone(timezone.utc).isoformat(),
    }


def _kickoff_passed(kickoff: str | None, now: datetime) -> bool | None:
    if not isinstance(kickoff, str) or not kickoff.strip():
        return None
    text = kickoff.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return now >= moment


def render_audit_entry(audit: dict[str, Any], *, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    from zoneinfo import ZoneInfo

    local = current.astimezone(ZoneInfo("Europe/Madrid"))
    predicted = audit.get("predicted_points")
    actual = audit.get("actual_points")
    error = audit.get("error")
    missing = audit.get("missing") if isinstance(audit.get("missing"), list) else []
    causa = "la serie oficial no trae número de jornada; se usa el último weekPoints de cada titular"
    if missing:
        causa = "faltan datos: " + ", ".join(str(item) for item in missing)
    lines = [
        f"## AUDITORÍA {local.date().isoformat()} {local.strftime('%H:%M')} Europe/Madrid · jornada última",
        "",
        f"- previsto: {predicted if predicted is not None else 's/d'} puntos del XI",
        f"- realizado: {actual if actual is not None else 's/d'} (último weekPoints de cada titular)",
        f"- error: {error if error is not None else 's/d'}",
        f"- causa: {causa}",
        "- corrección: no se cambian los pesos del solver en este ciclo",
        f"- {audit.get('fingerprint') or 'auditoria-xi:incompleta'}",
        "",
    ]
    return "\n".join(lines)


def append_audit(audit: dict[str, Any], path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Escribe la entrada solo si la jornada ya empezó, el XI está completo y no está repetida."""
    if audit.get("played") is not True or audit.get("complete") is not True:
        return {**audit, "written": False, "reason": "jornada_abierta_o_incompleta"}
    fingerprint = audit.get("fingerprint")
    if not isinstance(fingerprint, str):
        return {**audit, "written": False, "reason": "sin_huella"}
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
    if fingerprint in existing:
        return {**audit, "written": False, "reason": "ya_registrada"}
    entry = render_audit_entry(audit, now=now)
    separator = "" if existing.endswith("\n") or not existing else "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing + separator + "\n" + entry, encoding="utf-8")
    return {**audit, "written": True, "reason": None}

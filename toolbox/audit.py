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


# -- Auditoría por jornada: previsión de la jornada N contra las actas de la jornada N ----------
#
# La serie oficial (weekPoints) no trae número de jornada: el último valor de cada
# titular mezclaba la J12 con la J11 (82 «reales» frente a 70,5 previstos). Las actas
# sí lo traen (``weeks[N] = [puntos, minutos]``). La previsión se guarda antes del
# bloqueo con su número de jornada y solo se audita contra las actas de esa jornada.

#: Horas desde el inicio de la jornada hasta darla por terminada aunque falte algún acta.
HORAS_JORNADA_CERRADA = 108.0
#: Con todas las actas del XI, horas mínimas desde el inicio (un acta llega al acabar cada partido).
HORAS_MINIMAS_CON_ACTAS = 48.0
_MARKER_JORNADA = "auditoria-xi-j"


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def ultima_jornada_con_actas(actas: dict[str, dict[str, Any]]) -> int | None:
    semanas = [
        int(semana)
        for datos in actas.values()
        if isinstance(datos, dict)
        for semana in (datos.get("weeks") or {})
        if str(semana).isdigit()
    ]
    return max(semanas) if semanas else None


def _leer_previas(path: Path) -> dict[str, Any]:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _guardar_previas(path: Path, data: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def guardar_previa_xi(
    optimize: dict[str, Any] | None,
    *,
    inicio: datetime,
    now: datetime,
    path: Path,
    ultima_actas: int | None = None,
) -> dict[str, Any] | None:
    """Guarda (o actualiza) la previsión del XI de la jornada que empieza en ``inicio``.

    Se guarda por fecha de inicio, no por número: con el primer partido en juego y
    sin actas aún, el número de la jornada no se puede saber con seguridad.
    """
    if now >= inicio:
        return None
    xi = optimize.get("xi") if isinstance(optimize, dict) and isinstance(optimize.get("xi"), list) else []
    ids: list[str] = []
    total = 0.0
    for row in xi:
        if not isinstance(row, dict) or not isinstance(row.get("player_id"), str):
            continue
        # El xP esperado (con la probabilidad de ser titular), no los puntos «si juega».
        valor = _number(row.get("jornada_ev"))
        if valor is None:
            valor = _number(row.get("expected_points"))
        if valor is None:
            return None
        ids.append(row["player_id"])
        total += valor
    if len(ids) != 11:
        return None
    clave = inicio.astimezone(timezone.utc).isoformat()
    previa = {
        "xi_ids": sorted(ids),
        "predicted_points": round(total, 2),
        "inicio": inicio.astimezone(timezone.utc).isoformat(),
        "stored_at": now.astimezone(timezone.utc).isoformat(),
        # Última jornada con actas al guardar: la auditada tiene que ser posterior.
        "ultima_actas_al_guardar": ultima_actas,
    }
    data = _leer_previas(path)
    data[clave] = previa
    _guardar_previas(path, data)
    return previa


def auditar_jornada(
    previa: dict[str, Any],
    actas: dict[str, dict[str, Any]],
    *,
    jornada: int,
    now: datetime,
) -> dict[str, Any]:
    """Previsión de la jornada ``jornada`` frente a los puntos de sus actas."""
    ids = [str(item) for item in previa.get("xi_ids") or []]
    inicio = _parse(previa.get("inicio"))
    reales: list[float] = []
    sin_acta: list[str] = []
    for player_id in ids:
        semana = ((actas.get(player_id) or {}).get("weeks") or {}).get(str(jornada))
        puntos = _number(semana[0]) if isinstance(semana, list) and semana else None
        if puntos is None:
            sin_acta.append(player_id)
        else:
            reales.append(puntos)
    horas = (now - inicio).total_seconds() / 3600.0 if inicio is not None else 0.0
    cerrada = horas >= HORAS_JORNADA_CERRADA or (not sin_acta and horas >= HORAS_MINIMAS_CON_ACTAS)
    predicted = _number(previa.get("predicted_points"))
    actual = round(sum(reales), 2) if cerrada else None
    error = round(actual - predicted, 2) if actual is not None and predicted is not None else None
    huella = f"{_MARKER_JORNADA}{jornada}:{predicted}:{actual}:{','.join(ids)}" if cerrada else None
    return {
        "ok": True,
        "jornada": jornada,
        "complete": cerrada,
        "played": cerrada,
        "predicted_points": predicted,
        "actual_points": actual,
        "error": error,
        # Sin acta tras cerrar la jornada = no jugó: 0 puntos (se dice, no se esconde).
        "missing": [f"{pid}: sin acta (0 pts)" for pid in sin_acta] if cerrada else [],
        "xi_ids": ids,
        "fingerprint": huella,
        "kickoff": previa.get("inicio"),
        "previa_guardada": previa.get("stored_at"),
        "at": now.astimezone(timezone.utc).isoformat(),
    }


def render_auditoria_jornada(audit: dict[str, Any], *, now: datetime) -> str:
    from zoneinfo import ZoneInfo

    local = now.astimezone(ZoneInfo("Europe/Madrid"))
    jornada = audit["jornada"]
    missing = audit.get("missing") or []
    causa = "previsión guardada antes del bloqueo y actas de la misma jornada"
    if missing:
        causa += "; sin acta (0 pts): " + ", ".join(str(item).split(":")[0] for item in missing)
    return "\n".join(
        [
            f"## AUDITORÍA {local.date().isoformat()} {local.strftime('%H:%M')} Europe/Madrid · jornada {jornada}",
            "",
            f"- previsto: {audit.get('predicted_points')} puntos del XI (guardado {audit.get('previa_guardada')})",
            f"- realizado: {audit.get('actual_points')} (actas de la jornada {jornada})",
            f"- error: {audit.get('error')}",
            f"- causa: {causa}",
            "- corrección: no se cambian los pesos del solver en este ciclo",
            f"- {audit.get('fingerprint')}",
            "",
        ]
    )


def ciclo_auditoria(
    optimize: dict[str, Any] | None,
    actas: dict[str, dict[str, Any]],
    *,
    inicio_proxima: datetime | None,
    now: datetime,
    previas_path: Path,
    memory_path: Path | None,
) -> dict[str, Any]:
    """Guarda la previa de la próxima jornada y audita la última cerrada que tenga previa.

    Nunca compara jornadas distintas: sin previa guardada de esa jornada, no hay auditoría.
    """
    ultima = ultima_jornada_con_actas(actas)
    if inicio_proxima is not None:
        guardar_previa_xi(optimize, inicio=inicio_proxima, now=now, path=previas_path, ultima_actas=ultima)
    previas = _leer_previas(previas_path)
    empezadas = sorted(
        (inicio, clave)
        for clave, previa in previas.items()
        if isinstance(previa, dict) and (inicio := _parse(previa.get("inicio") or clave)) is not None and inicio <= now
    )
    if empezadas and ultima is not None:
        # Solo la última jornada empezada y con sus actas como las últimas: así el número es seguro.
        previa = previas[empezadas[-1][1]]
        antes = previa.get("ultima_actas_al_guardar")
        if not isinstance(antes, int) or ultima <= antes:
            # Aún no hay actas de la jornada de esta previa: no se compara con la anterior.
            return {"ok": True, "complete": False, "played": False, "written": False, "reason": "sin_actas_de_la_jornada"}
        audit = auditar_jornada(previa, actas, jornada=ultima, now=now)
        if not audit["complete"]:
            return {**audit, "written": False, "reason": "jornada_abierta"}
        if memory_path is None:
            return {**audit, "written": False, "reason": "sin_memoria"}
        existente = memory_path.read_text(encoding="utf-8") if memory_path.is_file() else ""
        if audit["fingerprint"] in existente:
            return {**audit, "written": False, "reason": "ya_registrada"}
        entrada = render_auditoria_jornada(audit, now=now)
        separador = "" if existente.endswith("\n") or not existente else "\n"
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(existente + separador + "\n" + entrada, encoding="utf-8")
        return {**audit, "written": True, "reason": None}
    return {"ok": True, "complete": False, "played": False, "written": False, "reason": "sin_previa_de_jornada"}

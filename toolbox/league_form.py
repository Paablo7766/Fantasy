"""Forma de cada mánager: puntos por jornada y tendencia.

La clasificación oficial solo trae el acumulado. Los puntos de cada jornada
salen de ``data/jornada_points.json``, que se rellena con la columna PFSY de
la app. No hace ninguna llamada a la red: cruza ese archivo con las plantillas
que ya hay en el tablero. Si un nombre no casa con ningún equipo se informa en
``unmatched`` en vez de adivinar.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from toolbox import project_root

DATA_FILE = Path(project_root()) / "data" / "jornada_points.json"
RECENT = 3


def _fold(text: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in raw.lower() if ch.isalnum())


def load_rounds(path: Path | None = None) -> dict[int, dict[str, int]]:
    """``{jornada: {nombre: puntos}}``. Archivo ausente o roto = vacío."""
    try:
        document = json.loads((path or DATA_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rounds = document.get("rounds") if isinstance(document, dict) else None
    clean: dict[int, dict[str, int]] = {}
    for key, rows in (rounds or {}).items():
        if not (isinstance(rows, dict) and str(key).isdigit()):
            continue
        scores = {
            str(name): int(value)
            for name, value in rows.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if scores:
            clean[int(key)] = scores
    return clean


def _ranks(scores: dict[str, int]) -> dict[str, int]:
    """Puesto con empates (dos con 19 comparten puesto)."""
    ordered = sorted(scores.values(), reverse=True)
    return {name: ordered.index(value) + 1 for name, value in scores.items()}


def build_league_form(squads: dict[str, Any] | None, rounds: dict[int, dict[str, int]] | None = None) -> dict[str, Any]:
    rounds = load_rounds() if rounds is None else rounds
    if not rounds:
        return {"ok": False, "reason": "sin_datos", "detail": "Aún no hay puntos por jornada."}
    document = squads if isinstance(squads, dict) else {}
    teams = [s for s in document.get("squads") or [] if isinstance(s, dict) and s.get("error") is None]
    by_name: dict[str, dict[str, Any]] = {}
    for squad in teams:
        for label in (squad.get("manager_name"), squad.get("fantasy_team_name")):
            if _fold(label):
                by_name.setdefault(_fold(label), squad)

    numbers = sorted(rounds)
    per_round_rank = {number: _ranks(rounds[number]) for number in numbers}
    names = sorted({name for scores in rounds.values() for name in scores})
    rows: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for name in names:
        squad = by_name.get(_fold(name))
        if squad is None:
            unmatched.append(name)
            continue
        series = [
            {"round": n, "points": rounds[n][name], "rank": per_round_rank[n][name]}
            for n in numbers
            if name in rounds[n]
        ]
        values = [item["points"] for item in series]
        recent = values[-RECENT:]
        earlier = values[:-1]
        recent_avg = sum(recent) / len(recent)
        trend = round(values[-1] - sum(earlier) / len(earlier), 1) if earlier else None
        rows.append(
            {
                "team_id": squad.get("team_id"),
                "manager_name": squad.get("manager_name") or name,
                "fantasy_team_name": squad.get("fantasy_team_name"),
                "is_self": squad.get("is_self") is True,
                "rounds": series,
                "recent_avg": round(recent_avg, 1),
                "total": sum(values),
                "best": max(values),
                "trend": trend,
            }
        )
    rows.sort(key=lambda row: (-row["recent_avg"], -row["total"]))
    for index, row in enumerate(rows, start=1):
        row["form_rank"] = index
    return {
        "ok": bool(rows),
        "rounds": numbers,
        "recent_window": RECENT,
        "rows": rows,
        "unmatched": unmatched,
    }

"""Forma de cada mánager: puntos por jornada y tendencia.

La clasificación oficial solo trae el acumulado. Los puntos de cada jornada
salen solos del premio de jornada de la actividad de la liga (tipo 6, con su
``weekNumber``): 100.000 € por punto. ``data/jornada_points.json`` queda como
respaldo manual para las jornadas que la actividad ya no alcanza. No hace
ninguna llamada a la red: cruza esas fuentes con las plantillas del tablero. Si un nombre no casa con ningún equipo se informa en
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
EUR_PER_POINT = 100_000
TOP_N = 4


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


def rounds_from_ledgers(
    ledgers: list[Any] | None, squads: list[dict[str, Any]]
) -> dict[int, dict[str, int]]:
    """``{jornada: {mánager: puntos}}`` a partir de los premios de jornada.

    Solo cuenta el tipo 6 con ``weekNumber`` y un importe múltiplo exacto de
    100.000 €. Una jornada con premios de menos equipos que la liga se descarta
    entera: un puesto calculado con huecos sería mentira.
    """
    names = {
        str(s.get("team_id")): s.get("manager_name") or s.get("fantasy_team_name")
        for s in squads
        if s.get("team_id") is not None
    }
    found: dict[int, dict[str, int]] = {}
    for ledger in ledgers or []:
        if not isinstance(ledger, dict):
            continue
        name = names.get(str(ledger.get("team_id"))) or ledger.get("manager_name")
        if not name:
            continue
        for line in ledger.get("events") or []:
            if not isinstance(line, dict) or line.get("activity_type_id") != 6:
                continue
            week, amount = line.get("week"), line.get("amount_eur")
            if not isinstance(week, int) or not isinstance(amount, int) or isinstance(amount, bool):
                continue
            if amount % EUR_PER_POINT:
                continue
            found.setdefault(week, {})[str(name)] = amount // EUR_PER_POINT
    return {week: rows for week, rows in found.items() if len(rows) >= len(names) and rows}


def round_summaries(rounds: dict[int, dict[str, int]], self_name: str | None) -> list[dict[str, Any]]:
    """Mi puesto en cada jornada contra la línea del 4.º (el corte de la multa)."""
    if not self_name:
        return []
    out: list[dict[str, Any]] = []
    for number in sorted(rounds):
        scores = rounds[number]
        mine = scores.get(self_name)
        if mine is None or len(scores) < TOP_N:
            continue
        ordered = sorted(scores.values(), reverse=True)
        cutoff = ordered[TOP_N - 1]
        out.append(
            {
                "round": number,
                "points": mine,
                "rank": ordered.index(mine) + 1,
                "cutoff": cutoff,
                "gap": mine - cutoff,
                "in_top4": mine >= cutoff,
                "tied_at_cutoff": ordered.count(cutoff) > 1 and mine == cutoff,
                "leader": ordered[0],
                "field": len(scores),
            }
        )
    return out


def _ranks(scores: dict[str, int]) -> dict[str, int]:
    """Puesto con empates (dos con 19 comparten puesto)."""
    ordered = sorted(scores.values(), reverse=True)
    return {name: ordered.index(value) + 1 for name, value in scores.items()}


def build_league_form(
    squads: dict[str, Any] | None,
    rounds: dict[int, dict[str, int]] | None = None,
    ledgers: list[Any] | None = None,
) -> dict[str, Any]:
    document = squads if isinstance(squads, dict) else {}
    teams = [s for s in document.get("squads") or [] if isinstance(s, dict) and s.get("error") is None]
    derived = rounds_from_ledgers(ledgers, teams) if rounds is None else {}
    manual = load_rounds() if rounds is None else rounds
    # La actividad manda; el JSON solo rellena jornadas que ella ya no trae.
    rounds = {**manual, **derived}
    sources = {n: ("actividad" if n in derived else "manual") for n in rounds}
    if not rounds:
        return {"ok": False, "reason": "sin_datos", "detail": "Aún no hay puntos por jornada."}
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
    me = next((s for s in teams if s.get("is_self") is True), None)
    self_name = None
    if me is not None:
        mine = {_fold(me.get("manager_name")), _fold(me.get("fantasy_team_name"))}
        self_name = next((n for n in names if _fold(n) in mine), None)
    return {
        "ok": bool(rows),
        "sources": {str(n): sources[n] for n in numbers},
        "scores": {str(n): rounds[n] for n in numbers},
        "my_rounds": round_summaries(rounds, self_name),
        "top_n": TOP_N,
        "rounds": numbers,
        "recent_window": RECENT,
        "rows": rows,
        "unmatched": unmatched,
    }

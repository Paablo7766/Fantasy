"""Cuaderno del top 4: el xP del once esperado de cada mánager antes del cierre.

Para medir cuánto acierta la probabilidad de top 4 hace falta lo que se creía
ANTES de cada jornada. Cada pasada reescribe la foto mientras el primer saque no
haya llegado (manda la última foto del tablero); después no se toca. Cuando
salen los premios de jornada, ``evaluar`` compara con los puntos reales.

Es independiente de ``toolbox.pre_lock`` (que guarda cuotas, onces y señales):
usa su propia tabla en el mismo sqlite y no lo importa.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root
from toolbox.top4 import TOP_N, build_top4

SEASON = "2026/27"
TABLE = "top4_forecasts"

_SCHEMA = f"""
create table if not exists {TABLE} (
    season text not null,
    jornada integer not null,
    kickoff text not null,
    photo_at text,
    stored_at real not null,
    payload text not null,
    primary key (season, jornada)
)
"""


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def freeze_forecast(
    race: dict[str, Any] | None,
    rounds: dict[int, dict[str, int]] | None,
    *,
    kickoff: str | None,
    photo_at: str | None,
    now: datetime | None = None,
    conn: sqlite3.Connection | None = None,
    season: str = SEASON,
) -> dict[str, Any]:
    """Guarda la previsión de la próxima jornada si su primer saque no ha llegado.

    La jornada es la siguiente a la última con premios. Solo reescribe si la foto
    del tablero es más nueva que la guardada.
    """
    moment = now or datetime.now(timezone.utc)
    cierre = _parse(kickoff)
    if cierre is None:
        return {"wrote": False, "reason": "sin hora de cierre"}
    if moment >= cierre:
        return {"wrote": False, "reason": "jornada ya cerrada"}
    if not rounds:
        return {"wrote": False, "reason": "sin jornadas jugadas: no se sabe qué número toca"}
    jornada = max(rounds) + 1
    forecast = build_top4(race, rounds)
    if not forecast.get("ok"):
        return {"wrote": False, "reason": forecast.get("reason", "sin simulación"), "jornada": jornada}
    payload = {
        "p_top4": forecast["p_top4"],
        "void": forecast["void"],
        "cutoff_median": forecast["cutoff_median"],
        "calibration": forecast["calibration"],
        "managers": [
            {
                "team_id": m["team_id"],
                "manager_name": m["manager_name"],
                "is_self": m["is_self"],
                "expected_points": m["expected_points"],
                "has_xp": m["has_xp"],
                "player_count": m["player_count"],
                "void": m["void"],
                "p_top4": m["p_top4"],
            }
            for m in forecast["managers"]
        ],
    }
    own = conn is None
    db = conn or sqlite3.connect(_db_path())
    try:
        db.execute(_SCHEMA)
        previous = db.execute(f"select photo_at from {TABLE} where season = ? and jornada = ?", (season, jornada)).fetchone()
        old, new = _parse(previous[0]) if previous else None, _parse(photo_at)
        if previous is not None and old is not None and new is not None and new <= old:
            return {"wrote": False, "reason": "ya hay una previsión de una foto igual o más nueva", "jornada": jornada}
        db.execute(
            f"""
            insert into {TABLE} (season, jornada, kickoff, photo_at, stored_at, payload)
            values (?, ?, ?, ?, ?, ?)
            on conflict(season, jornada) do update set
                kickoff = excluded.kickoff, photo_at = excluded.photo_at,
                stored_at = excluded.stored_at, payload = excluded.payload
            """,
            (season, jornada, cierre.isoformat(), photo_at, moment.timestamp(), json.dumps(payload, ensure_ascii=False)),
        )
        db.commit()
    finally:
        if own:
            db.close()
    return {"wrote": True, "jornada": jornada, "managers": len(payload["managers"])}


def _brier(pairs: list[tuple[float, int]]) -> float | None:
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None


def evaluar(
    rounds: dict[int, dict[str, int]],
    *,
    conn: sqlite3.Connection | None = None,
    season: str = SEASON,
) -> dict[str, Any]:
    """Compara cada previsión guardada con los puntos reales de esa jornada.

    Devuelve, por jornada y en conjunto: Brier de la probabilidad de top 4 frente
    a la tasa base (4 de 10), error medio y error absoluto del xP, y la
    calibración por tramos. Con pocas jornadas es solo orientativo.
    """
    own = conn is None
    db = conn or sqlite3.connect(_db_path())
    try:
        db.execute(_SCHEMA)
        rows = db.execute(f"select jornada, kickoff, payload from {TABLE} where season = ? order by jornada", (season,)).fetchall()
    finally:
        if own:
            db.close()
    por_jornada: list[dict[str, Any]] = []
    pares: list[tuple[float, int]] = []
    errores: list[float] = []
    for jornada, kickoff, raw in rows:
        reales = rounds.get(int(jornada))
        if not reales:
            continue
        previsto = json.loads(raw)
        puntos = sorted(reales.values(), reverse=True)
        if len(puntos) < TOP_N:
            continue
        corte = puntos[TOP_N - 1]
        jp: list[tuple[float, int]] = []
        je: list[float] = []
        for m in previsto.get("managers", []):
            real = reales.get(str(m.get("manager_name")))
            if real is None:
                continue
            jp.append((float(m["p_top4"]), int(real >= corte)))
            if m.get("has_xp") and not m.get("void"):
                je.append(real - float(m["expected_points"]))
        pares += jp
        errores += je
        por_jornada.append(
            {
                "jornada": int(jornada),
                "managers": len(jp),
                "brier": _brier(jp),
                "error_xp_medio": sum(je) / len(je) if je else None,
                "corte_real": corte,
                "corte_previsto": previsto.get("cutoff_median"),
            }
        )
    base = TOP_N / 10.0
    tramos = []
    for lo, hi in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)):
        dentro = [(p, y) for p, y in pares if lo <= p < hi]
        if dentro:
            tramos.append(
                {
                    "tramo": f"{round(lo * 100)}-{min(100, round(hi * 100))} %",
                    "n": len(dentro),
                    "p_media": sum(p for p, _ in dentro) / len(dentro),
                    "frecuencia": sum(y for _, y in dentro) / len(dentro),
                }
            )
    brier = _brier(pares)
    brier_base = _brier([(base, y) for _, y in pares])
    return {
        "jornadas": por_jornada,
        "n": len(pares),
        "brier": brier,
        "brier_tasa_base": brier_base,
        "gana_a_la_tasa_base": None if brier is None or brier_base is None else brier < brier_base,
        "error_xp_medio": sum(errores) / len(errores) if errores else None,
        "error_xp_abs": sum(abs(e) for e in errores) / len(errores) if errores else None,
        "tramos": tramos,
        "aviso": "Con menos de ~8 jornadas el Brier es ruido: sirve para detectar un fallo grueso, no para afinar.",
    }

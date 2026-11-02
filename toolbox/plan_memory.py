"""Memoria del plan de fichajes: qué se recomendó ayer y cuánto cambia de un día a otro.

El solver no sabía qué dijo el día anterior. Con un mercado nuevo cada mañana
y empates de décimas, el plan saltaba de un objetivo a otro. Aquí se guarda
cada plan publicado para dos cosas:

- dar al día siguiente los objetivos que siguen en pie (``objetivos_previos``),
  que el solver premia con una prima de continuidad;
- medir la estabilidad: cuántos objetivos cambian de un día a otro. Con esa
  cifra y los puntos reales se calibran el umbral y la prima.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root, madrid_day

# Pasado este tiempo el plan anterior ya no es de esta semana de mercado.
VIGENCIA_DIAS = 4
_TIPOS_OBJETIVO = {"PUJA", "CLAUSULAZO"}


def default_db() -> Path:
    return cache_root() / "responses.sqlite"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists plan_snapshots (
            league_id text not null,
            day text not null,
            stored_at real not null,
            objetivos text not null,
            ventas text not null,
            mejora real,
            sigue_plan integer not null default 0,
            primary key (league_id, day)
        )
        """
    )
    conn.commit()


def objetivos_de(plan: dict[str, Any] | None) -> list[str]:
    """Jugadores que el plan quiere fichar (pujas y cláusulas), sin repetir."""
    salida: list[str] = []
    for accion in (plan or {}).get("acciones") or []:
        if not isinstance(accion, dict) or accion.get("tipo") not in _TIPOS_OBJETIVO:
            continue
        player_id = accion.get("player_id")
        if isinstance(player_id, str) and player_id and player_id not in salida:
            salida.append(player_id)
    return salida


def _ventas_de(plan: dict[str, Any] | None) -> list[str]:
    salida: list[str] = []
    for accion in (plan or {}).get("acciones") or []:
        if not isinstance(accion, dict) or accion.get("tipo") not in {"VENDE", "VENDER HOY"}:
            continue
        player_id = accion.get("player_id")
        if isinstance(player_id, str) and player_id and player_id not in salida:
            salida.append(player_id)
    return salida


def _league_key(league_id: str | None) -> str:
    return league_id or "_default"


def load_objetivos_previos(
    league_id: str | None,
    *,
    day: str | None = None,
    db_path: Path | None = None,
) -> list[str]:
    """Objetivos del último plan de un día anterior, si sigue vigente.

    Se ignora el plan de hoy: si no, cada recarga del tablero se premiaría a
    sí misma y el primer plan del día quedaría fijado aunque el mercado cambie.
    """
    path = db_path or default_db()
    if not path.is_file():
        return []
    today = day or madrid_day()
    conn = sqlite3.connect(path)
    try:
        ensure_schema(conn)
        row = conn.execute(
            """
            select day, objetivos from plan_snapshots
            where league_id = ? and day < ?
            order by day desc limit 1
            """,
            (_league_key(league_id), today),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return []
    previous_day, raw = row
    if _dias_entre(str(previous_day), today) > VIGENCIA_DIAS:
        return []
    try:
        ids = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in ids if isinstance(item, str) and item]


def save_plan(
    league_id: str | None,
    plan: dict[str, Any] | None,
    *,
    day: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Guarda el plan publicado hoy. La última recarga del día es la que cuenta."""
    if not isinstance(plan, dict):
        return
    path = db_path or default_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    acciones = [accion for accion in plan.get("acciones") or [] if isinstance(accion, dict)]
    sigue = sum(1 for accion in acciones if accion.get("sigue_plan") is True)
    mejora = plan.get("mejora_puntos_jornada")
    conn = sqlite3.connect(path)
    try:
        ensure_schema(conn)
        conn.execute(
            """
            insert or replace into plan_snapshots
            (league_id, day, stored_at, objetivos, ventas, mejora, sigue_plan)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _league_key(league_id),
                day or madrid_day(),
                time.time(),
                json.dumps(objetivos_de(plan)),
                json.dumps(_ventas_de(plan)),
                float(mejora) if isinstance(mejora, (int, float)) and not isinstance(mejora, bool) else None,
                sigue,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _dias_entre(start: str, end: str) -> int:
    from datetime import date

    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return 10**6


def plan_stability(conn: sqlite3.Connection, league_id: str | None = None, *, limit: int = 30) -> dict[str, Any]:
    """Cuánto cambia el plan entre días seguidos.

    ``cambio_medio`` es 1 - Jaccard de los objetivos de dos días consecutivos
    con plan: 0 es el mismo plan, 1 es un plan nuevo entero. Los días sin
    objetivos en ninguno de los dos no cuentan: «no hacer nada» dos días
    seguidos es estable, pero no dice nada de la prima.
    """
    ensure_schema(conn)
    rows = conn.execute(
        """
        select day, objetivos from plan_snapshots
        where league_id = ?
        order by day desc limit ?
        """,
        (_league_key(league_id), limit),
    ).fetchall()
    serie: list[tuple[str, set[str]]] = []
    for day, raw in reversed(rows):
        try:
            ids = {str(item) for item in json.loads(raw) if isinstance(item, str)}
        except (TypeError, json.JSONDecodeError):
            ids = set()
        serie.append((str(day), ids))
    cambios: list[float] = []
    for (day_a, prev), (day_b, cur) in zip(serie, serie[1:]):
        if _dias_entre(day_a, day_b) > VIGENCIA_DIAS or not (prev or cur):
            continue
        cambios.append(1.0 - len(prev & cur) / len(prev | cur))
    return {
        "dias_con_plan": len(serie),
        "pares_comparados": len(cambios),
        "cambio_medio": round(sum(cambios) / len(cambios), 3) if cambios else None,
        "planes_nuevos_enteros": sum(1 for value in cambios if value >= 0.999),
    }

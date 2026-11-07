"""Registro diario de puntos y señales de precio por jugador.

Sirve para medir con datos propios dos cosas que hoy son supuestos: cuántos
días tarda LaLiga en subir el precio tras un partidazo y cuántos tardan las
señales externas (AF), y para calibrar los umbrales del detector de shock
(``toolbox.engine.shock_jornada``).

Una fila por (jugador, día Madrid). Se reescribe si el proceso corre dos veces
el mismo día. No lee red ni tumba trends: quien llama captura la excepción.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root

TABLE = "player_signal_log"

_SCHEMA = f"""
create table if not exists {TABLE} (
    player_id text not null,
    day text not null,
    league_id text,
    price integer,
    market_value_change integer,
    last_points real,
    af_predicted_delta real,
    af_price_delta real,
    own_predicted_delta real,
    own_expected_points real,
    stored_at real not null,
    af_expected_points real,
    own_xp_modelo real,
    p_titular_ff real,
    p_titular_af real,
    p_titular_final real,
    p_titular_fuente text,
    lineup_status text,
    primary key (player_id, day)
)
"""

#: Columnas añadidas después de crear la tabla, con su tipo.
#: La titularidad por fuente se guarda cada día desde nov 2026: saber el once
#: bajaba el error del xP de 2,75 a 2,32 en el backtest y hasta ahora no había
#: histórico con el que medir qué fuente acierta más.
_COLUMNAS_NUEVAS = (
    ("af_expected_points", "real"),
    ("own_xp_modelo", "real"),
    ("p_titular_ff", "real"),
    ("p_titular_af", "real"),
    ("p_titular_final", "real"),
    ("p_titular_fuente", "text"),
    ("lineup_status", "text"),
)


def _migrar(conn: sqlite3.Connection) -> None:
    existentes = {row[1] for row in conn.execute(f"pragma table_info({TABLE})")}
    for columna, tipo in _COLUMNAS_NUEVAS:
        if columna not in existentes:
            conn.execute(f"alter table {TABLE} add column {columna} {tipo}")


def _fraccion(value: Any) -> float | None:
    """Probabilidad 0..1 (las fuentes dan a veces 0..100)."""
    number = _num(value)
    if number is None:
        return None
    if number > 1.0:
        number /= 100.0
    return number if 0.0 <= number <= 1.0 else None


def _texto(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _last_points(player: dict[str, Any]) -> float | None:
    raw = player.get("week_points")
    if not isinstance(raw, list):
        form = player.get("form") if isinstance(player.get("form"), dict) else {}
        raw = form.get("week_points")
    if not isinstance(raw, list):
        return None
    for item in reversed(raw):
        number = _num(item.get("points", item.get("puntos"))) if isinstance(item, dict) else _num(item)
        if number is not None:
            return number
    return None


def _p_titular_futbolfantasy(player: dict[str, Any]) -> float | None:
    """Cifra de FútbolFantasy: ``startProbability`` si viaja; si no, ``p_titular`` cuando su fuente es FF.

    FF entra como fuente ``scraper``. Solo el consenso (AF y FF ≤ 20 %) la
    rebaja al mínimo de las dos, y ahí las dos ya dicen «no juega».
    """
    cruda = _fraccion(player.get("startProbability"))
    if cruda is not None:
        return cruda
    if player.get("p_titular_source") == "scraper":
        return _fraccion(player.get("p_titular"))
    return None


def rows_from_players(players: list[dict[str, Any]], *, league_id: str | None, day: str) -> list[tuple[Any, ...]]:
    now = time.time()
    rows: list[tuple[Any, ...]] = []
    for player in players:
        pid = player.get("player_id")
        if not isinstance(pid, str) or not pid:
            continue
        price = _int(player.get("fantasy_price"))
        if price is None:
            price = _int(player.get("market_value"))
        rows.append(
            (
                pid,
                day,
                league_id,
                price,
                _int(player.get("market_value_change")),
                _last_points(player),
                _num(player.get("af_predicted_delta")),
                _num(player.get("af_price_delta")),
                _num(player.get("own_predicted_delta")),
                _num(player.get("own_expected_points")),
                now,
                _num(player.get("af_expected_points")),
                _num(player.get("own_xp_modelo")),
                _p_titular_futbolfantasy(player),
                _fraccion(player.get("af_p_titular")),
                _fraccion(player.get("p_titular")),
                _texto(player.get("p_titular_source")),
                _texto(player.get("lineup_status")) or _texto(player.get("lineupStatus")),
            )
        )
    return rows


def record_signal_log(
    players: list[dict[str, Any]],
    *,
    league_id: str | None,
    day: str | None,
    path: Path | None = None,
) -> int:
    """Upsert del día. Devuelve las filas escritas; 0 si no hay día o jugadores."""
    if not day:
        return 0
    rows = rows_from_players(players, league_id=league_id, day=day)
    if not rows:
        return 0
    target = path or _db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    try:
        conn.execute(_SCHEMA)
        _migrar(conn)
        conn.executemany(
            f"insert or replace into {TABLE} (player_id, day, league_id, price, market_value_change, "
            "last_points, af_predicted_delta, af_price_delta, own_predicted_delta, own_expected_points, "
            "stored_at, af_expected_points, own_xp_modelo, p_titular_ff, p_titular_af, p_titular_final, "
            "p_titular_fuente, lineup_status) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)

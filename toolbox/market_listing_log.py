"""Registro diario de los anuncios del mercado.

El mercado de LaLiga se reescribe cada día y la API no guarda historia. Sin
este registro no se puede medir cuántos anuncios de rival acaban en venta, ni
si una venta con ``directOffer`` se paga distinto, ni cuánto valía la plantilla
del vendedor cuando puso al jugador. Una fila por (anuncio, día Madrid). Solo
mide: no entra en ninguna decisión. No lee red ni tumba trends.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root

TABLE = "market_listing_log"

_SCHEMA = f"""
create table if not exists {TABLE} (
    market_id text not null,
    day text not null,
    league_id text,
    player_id text,
    seller_team_id text,
    sale_price integer,
    market_value integer,
    bid_count integer,
    offer_count integer,
    direct_offer integer,
    seller_team_value integer,
    expires_at text,
    stored_at real not null,
    last_season_points integer,
    is_in_ideal_formation integer,
    primary key (market_id, day)
)
"""

#: Columnas añadidas después de crear la tabla: se migran en bases ya existentes.
_COLUMNAS_NUEVAS = (("last_season_points", "integer"), ("is_in_ideal_formation", "integer"))


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _flag(value: Any) -> int | None:
    return int(value) if isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def rows_from_listings(listings: list[dict[str, Any]], *, league_id: str | None, day: str) -> list[tuple[Any, ...]]:
    now = time.time()
    rows: list[tuple[Any, ...]] = []
    for listing in listings:
        market_id = _text(listing.get("market_id"))
        if market_id is None:
            continue
        rows.append(
            (
                market_id,
                day,
                league_id,
                _text(listing.get("player_id")),
                _text(listing.get("seller_team_id")),
                _int(listing.get("sale_price")),
                _int(listing.get("market_value")),
                _int(listing.get("bid_count")),
                _int(listing.get("offer_count")),
                _flag(listing.get("direct_offer")),
                _int(listing.get("seller_team_value")),
                _text(listing.get("listing_expires_at")),
                now,
                _int(listing.get("last_season_points")),
                _flag(listing.get("is_in_ideal_formation")),
            )
        )
    return rows


def record_market_listings(
    listings: list[dict[str, Any]] | None,
    *,
    league_id: str | None,
    day: str | None,
    path: Path | None = None,
) -> int:
    """Upsert del día. Devuelve las filas escritas; 0 si no hay día o anuncios."""
    if not day or not listings:
        return 0
    rows = rows_from_listings([item for item in listings if isinstance(item, dict)], league_id=league_id, day=day)
    if not rows:
        return 0
    target = path or _db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    try:
        conn.execute(_SCHEMA)
        have = {str(fila[1]) for fila in conn.execute(f"pragma table_info({TABLE})")}
        for nombre, tipo in _COLUMNAS_NUEVAS:
            if nombre not in have:
                conn.execute(f"alter table {TABLE} add column {nombre} {tipo}")
        conn.executemany(f"insert or replace into {TABLE} values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)

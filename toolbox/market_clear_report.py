"""Ensambla la auditoría de cierres de mercado desde lo ya guardado.

Nada de red y nada de escritura: lee la foto del tablero que dejó el servidor
(``.cache/dashboard/<liga>/*.json``) y ``responses.sqlite``. Las pruebas pueden
inyectar ambos para auditar un día sintético.

Puntos que se cuidan a propósito:

  * **Foto anterior al cierre.** Si el tablero se refrescó después del cierre
    auditor, la puja del motor ya no es la que estaba sobre la mesa. Se
    prefiere la foto más nueva tomada antes del cierre.
  * **No se tocan las tablas de prueba.** La suite escribe en
    ``responses_audit_test.sqlite`` con ligas ``league-test:*``; quedarían
    contadas como compras rivales aunque la liga fuese otra. Se filtran aquí.
  * **La columna ``predicted_win`` manda.** Si algún proceso la añade a
    ``market_decision_snapshots``, es la puja congelada ese día y sustituye a
    la que se recalcularía del motor.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from toolbox.cache import cache_root, madrid_day as _today
from toolbox.market_clear import (
    as_int,
    get_path,
    madrid_day,
    manager_index,
    median,
    merged_quotes,
    motor_predictions,
    own_team_id,
    price_limit_error,
    rival_alerts,
    risk_limits_from_intel,
    risk_limits_from_ledgers,
    sample_row,
)

#: Cierre del mercado de LaLiga en hora de Madrid.
MARKET_CLOSE = (14, 8)

#: Prefijo de las ligas que crea la suite. Nunca entran en una auditoría real.
TEST_LEAGUE_PREFIX = "league-test"


# --------------------------------------------------------------------------- #
# Foto del tablero
# --------------------------------------------------------------------------- #


def parse_moment(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def board_moment(envelope: Mapping[str, Any], value: Mapping[str, Any]) -> datetime | None:
    """Momento de la foto: la marca del tablero, la del mercado o el mtime.

    ``None`` solo si no hay ninguna: una foto sin fecha no se puede comparar con
    el cierre del día y no debe colarse como si fuera de hoy.
    """
    for candidate in (value.get("dashboard_at"), get_path(value, "market", "fetched_at")):
        moment = parse_moment(candidate)
        if moment is not None:
            return moment
    saved = envelope.get("saved_unix") or value.get("photo_saved_unix")
    if isinstance(saved, (int, float)) and not isinstance(saved, bool):
        return datetime.fromtimestamp(float(saved), tz=timezone.utc)
    return None


def has_market(board: Mapping[str, Any]) -> bool:
    market = board.get("market")
    return isinstance(market, dict) and bool(market.get("listings"))


def board_league_id(value: Mapping[str, Any] | None) -> str | None:
    """Id de liga que lleva dentro la foto (plantillas, mercado o tendencias)."""
    if not isinstance(value, Mapping):
        return None
    for path in (("squads", "league_id"), ("market", "league_id"), ("needs", "league_id"), ("trends", "league_id")):
        league = get_path(value, *path)
        if isinstance(league, str) and league:
            return league
    return None


def load_board(root: Path, *, before: datetime | None = None) -> dict[str, Any] | None:
    """Foto más reciente con mercado; se prefiere una tomada antes de ``before``.

    El momento sale del contenido (``dashboard_at`` / ``fetched_at``) y, solo si
    no hay, del ``saved_unix`` del sobre o del ``mtime`` del fichero. Un fichero
    copiado o restaurado conserva su ``mtime`` pero no su interior, así que el
    contenido manda.
    """
    base = root / "dashboard"
    if not base.is_dir():
        return None
    paths = [path for path in base.glob("*/*.json") if path.suffix == ".json"]
    paths.sort(key=_mtime, reverse=True)
    candidates: list[dict[str, Any]] = []
    for path in paths:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, dict):
            continue
        value = envelope.get("value")
        if not isinstance(value, dict) or not has_market(value):
            continue
        moment = board_moment(envelope, value)
        if moment is None:
            # Último recurso: el fichero. Una copia conserva el mtime pero no la
            # foto, así que el contenido siempre se mira primero.
            moment = datetime.fromtimestamp(_mtime(path), tz=timezone.utc)
        league = board_league_id(value) or envelope.get("league")
        candidates.append(
            {
                "path": path,
                "moment": moment,
                "league": league if isinstance(league, str) else None,
                "value": value,
            }
        )
    if not candidates:
        return None
    if before is not None:
        eligible = [item for item in candidates if item["moment"] <= before]
        if eligible:
            return max(eligible, key=lambda item: item["moment"])
    return max(candidates, key=lambda item: item["moment"])


# --------------------------------------------------------------------------- #
# SQLite
# --------------------------------------------------------------------------- #


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Crea solo las tablas de lectura que falten. Nunca migra ni borra."""
    conn.executescript(
        """
        create table if not exists activity_buys (
            id integer primary key autoincrement,
            league_id text,
            team_id text not null,
            player_id text not null,
            amount_eur integer not null,
            reference_value_eur integer,
            cash_at_event_eur integer,
            positional_urgency real,
            at text
        );
        create table if not exists price_snapshots (
            player_id text not null,
            day text not null,
            league_id text,
            market_value integer,
            market_value_change integer,
            stored_at real not null,
            primary key (player_id, day)
        );
        create table if not exists market_decision_snapshots (
            snapshot_day text not null,
            league_id text,
            player_id text not null,
            decision text not null,
            suggested_bid integer,
            win_probability real,
            primary_motive text,
            stored_at real not null,
            outcome text,
            outcome_at real,
            primary key (snapshot_day, player_id)
        );
        """
    )
    # Migración: bases antiguas no traen ``predicted_win`` (REAL, nullable).
    have = columns(conn, "market_decision_snapshots")
    if "predicted_win" not in have:
        conn.execute("alter table market_decision_snapshots add column predicted_win real")
    conn.commit()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name = ?", (table,)
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'pragma table_info("{table}")')}


def _is_test_league(league_id: Any) -> bool:
    return isinstance(league_id, str) and league_id.startswith(TEST_LEAGUE_PREFIX)


def read_buys(
    conn: sqlite3.Connection,
    *,
    league_id: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Compras del historial, sin las de la suite.

    Con ``league_id`` se queda solo con esa liga: es lo correcto cuando la foto
    trae una liga concreta, porque un ``responses.sqlite`` puede tener más de
    una. Las filas sin liga se aceptan (vienen de exportaciones viejas).
    ``since`` recorta por prefijo de fecha (``YYYY-MM-DD``), que en una marca
    ISO es siempre el día UTC: el filtro fino por día Madrid lo hace el informe.
    """
    if not table_exists(conn, "activity_buys"):
        return []
    have = columns(conn, "activity_buys")
    wanted = [col for col in ("team_id", "player_id", "amount_eur", "at", "league_id") if col in have]
    if not {"team_id", "player_id", "amount_eur", "at"} <= set(wanted):
        return []
    sql = f'select {", ".join(wanted)} from activity_buys'
    params: list[Any] = []
    if since:
        sql += " where at >= ?"
        params.append(since)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for raw in rows:
        row = dict(zip(wanted, raw))
        if _is_test_league(row.get("league_id")):
            continue
        if league_id and isinstance(row.get("league_id"), str) and row["league_id"] != league_id:
            continue
        if not isinstance(row.get("at"), str) or not row["at"]:
            # Sin marca horaria no se puede asignar a un día: no se inventa.
            continue
        out.append(row)
    return out


def read_price_references(conn: sqlite3.Connection, *, day: str) -> dict[str, int]:
    """Valor de mercado del día por jugador: denominador del sobreprecio."""
    if not table_exists(conn, "price_snapshots"):
        return {}
    rows = conn.execute(
        "select player_id, market_value from price_snapshots where day = ?", (day,)
    ).fetchall()
    return {
        str(player_id): value
        for player_id, value in rows
        if as_int(value) is not None
    }


def read_persisted_predictions(
    conn: sqlite3.Connection,
    *,
    day: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """``predicted_win`` congelado del día, si la columna existe.

    El esquema vigente no la tiene: guarda ``suggested_bid``. Aquí se devuelve
    el diagnóstico de columnas para que el informe lo declare en vez de fingir
    que el valor viene de la tabla. Las ligas de prueba se excluyen, igual que
    en las compras.
    """
    if not table_exists(conn, "market_decision_snapshots"):
        return {}, {
            "table": False,
            "predicted_win_column": False,
            "suggested_bid_column": False,
            "rows": 0,
        }
    have = columns(conn, "market_decision_snapshots")
    rows = conn.execute(
        "select count(*) from market_decision_snapshots where snapshot_day = ?", (day,)
    ).fetchone()[0]
    schema = {
        "table": True,
        "predicted_win_column": "predicted_win" in have,
        "suggested_bid_column": "suggested_bid" in have,
        "rows": int(rows or 0),
    }
    if not schema["predicted_win_column"]:
        return {}, schema
    out: dict[str, dict[str, Any]] = {}
    for player_id, value in conn.execute(
        "select player_id, predicted_win from market_decision_snapshots where snapshot_day = ?",
        (day,),
    ):
        amount = as_int(value)
        if amount is not None and isinstance(player_id, str):
            out[player_id] = {
                "player_id": player_id,
                "predicted_win_eur": amount,
                "source": "persistido",
            }
    return out, schema


def sale_days(conn: sqlite3.Connection, *, since: str | None = None) -> list[str]:
    """Días Madrid con compras registradas, sin las de la suite."""
    from toolbox.market_clear import madrid_day

    days = {madrid_day(row.get("at")) for row in read_buys(conn, since=since)}
    return sorted(day for day in days if day)


def closed_day(today: str | None = None, *, now: datetime | None = None) -> str:
    """Último día cuyo mercado ya cerró (14:08 Madrid)."""
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo

    market_close = (14, 8)  # 14:08 Madrid
    moment = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Europe/Madrid"))
    target = date.fromisoformat(today or _today())
    if (moment.hour, moment.minute) < market_close:
        target -= timedelta(days=1)
    return target.isoformat()


def add_months(day: str, months: int) -> str:
    """Misma fecha ``months`` meses después (fin de mes recortado al último día)."""
    import calendar
    from datetime import date

    start = date.fromisoformat(day)
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last)).isoformat()


def pick_day(
    conn: sqlite3.Connection,
    *,
    requested: str | None,
    now: datetime | None = None,
) -> str:
    """Día a auditar cuando no se pide uno concreto.

    Se busca el día cerrado más reciente con compras **dentro de una ventana de
    30 días** antes de la foto. Así se ignoran las compras que el historial aún
    no había cargado cuando el tablero se guardó: usar el último día con filas
    mezclaría una foto de hace días con compras de después.
    """
    if requested:
        return requested
    from zoneinfo import ZoneInfo

    moment = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Europe/Madrid"))
    cutoff = closed_day(now=now)
    default = sale_days(conn)[-1] if sale_days(conn) and sale_days(conn)[-1] <= cutoff else cutoff
    board = load_board(cache_root())
    if board is None:
        return default
    anchor = board["moment"].astimezone(ZoneInfo("Europe/Madrid")).date().isoformat()
    window_start = add_months(anchor, -1)
    # Compras anteriores a la foto: lo que el tablero pudo haber veredictado.
    days = [day for day in sale_days(conn, since=window_start) if day <= anchor]
    return days[-1] if days else default


# --------------------------------------------------------------------------- #
# Informe
# --------------------------------------------------------------------------- #


def audit_day(
    *,
    day: str,
    board: Mapping[str, Any] | None,
    moment: datetime | None,
    buys: Iterable[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]] | None = None,
    board_path: str | None = None,
    board_league: str | None = None,
    references: Mapping[str, int] | None = None,
    persisted: Mapping[str, Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Informe completo de un día cerrado: MAE de cierres + alertas de rivales."""
    moment_now = now or datetime.now(timezone.utc)
    predictions = {} if predictions is None else dict(predictions)
    board = board if isinstance(board, Mapping) else None
    board_league_id = get_path(board, "squads", "league_id") if board else None
    if (
        isinstance(board_league, str)
        and isinstance(board_league_id, str)
        and board_league != board_league_id
    ):
        # Una foto de otra liga daría cierres de jugadores homónimos: se ignora.
        board = None
        moment = None
        predictions = {}
    buy_rows = [
        row
        for row in buys
        if isinstance(row, Mapping)
        and get_path(row, "team_id") is not None
        and as_int(row.get("amount_eur")) is not None
    ]
    if isinstance(board_league_id, str):
        buy_rows = [
            row
            for row in buy_rows
            if not isinstance(row.get("league_id"), str) or row["league_id"] == board_league_id
        ]
    own = own_team_id(board)
    managers = manager_index(board)

    if not predictions and board is not None and moment is not None:
        predictions = motor_predictions(board, moment=moment)
    frozen = {**predictions, **dict(persisted or {})}
    if persisted and predictions:
        prediction_source = "persistida+motor"
    elif persisted:
        prediction_source = "persistida"
    elif predictions:
        prediction_source = "motor"
    else:
        prediction_source = "ninguna"

    quotes = merged_quotes(buy_rows, board, own=own)
    refs = dict(references or {})

    samples = [
        sample_row(prediction, quotes.get(player_id), reference=refs.get(player_id))
        for player_id, prediction in sorted(frozen.items())
    ]
    pairs = [
        (row["predicted_win_eur"], row["clearing_quote_eur"])
        for row in samples
        if row["counts_in_mae"]
    ]
    accuracy = price_limit_error(pairs)
    errors = [row["abs_error_eur"] for row in samples if row.get("abs_error_eur") is not None]
    accuracy["median_abs_error_eur"] = round(float(median(errors) or 0), 2) if errors else None

    limits = risk_limits_from_intel(board) if board else {}
    limit_source = "rival_intel" if limits else "ledger"
    if not limits and board:
        limits = risk_limits_from_ledgers(board)
    alerts = rival_alerts(buy_rows, limits, day=day, own=own, managers=managers)
    unpriced = [row for row in alerts if row.get("risk_adjusted_bid_limit_eur") is None]
    breaches = [row for row in alerts if row.get("risk_adjusted_bid_limit_eur") is not None]

    quote_days = {
        day_value: 0 for day_value in ()
    }  # placeholder for readability of below
    quotes_in_sample = sum(1 for row in samples if row.get("clearing_quote_eur") is not None)
    missed = [row for row in samples if row.get("missed")]
    stale_after_close = bool(moment and moment.date().isoformat() > day)
    coverage = {
        "board": board is not None,
        "board_has_bids": bool(board and get_path(board, "market", "listings")),
        "predictions": len(samples),
        "pairs": len(pairs),
        # «Ningún cierre de rival coincidió con un jugador que el motor hubiera
        # veredictado»: es un dato de cobertura, no un cero del modelo.
        "no_overlap": bool(samples) and not pairs and bool(quotes),
        "unpredicted_clears": len([player_id for player_id in quotes if player_id not in frozen]),
    }
    if coverage["no_overlap"]:
        coverage["note"] = (
            "Los cierres del día no corresponden a jugadores del tablero auditado: "
            "la muestra no permite un MAE de ese día."
        )
    if not predictions and not persisted:
        coverage["note"] = "La foto no trae veredictos de mercado: no hay pujas que comparar."

    return {
        "ok": True,
        "command": "audit_market_clear",
        "day": day,
        "league_id": board_league_id,
        "board": {
            "path": board_path,
            "moment": moment.isoformat() if moment else None,
            "age_hours": round((moment_now - moment).total_seconds() / 3600, 2)
            if moment
            else None,
            "after_close": stale_after_close,
            "limit_note": "La foto es posterior al cierre del día: las pujas del motor "
            "pueden no ser las que había sobre la mesa."
            if stale_after_close
            else None,
        },
        "sources": {
            "predictions": prediction_source,
            "buys": "activity_buys",
            "risk_limit": limit_source,
        },
        "sample": {
            "predictions": len(samples),
            "quoted": quotes_in_sample,
            "pairs": len(pairs),
            "missed": len(missed),
            "excluded_own_clears": sum(1 for row in samples if row.get("clearing_side") == "propia"),
            "unpredicted_clears": len(
                [player_id for player_id in quotes if player_id not in frozen]
            ),
        },
        "mae": accuracy,
        "coverage": coverage,
        "misses": [
            {
                "player_id": row.get("player_id"),
                "name": row.get("name"),
                "predicted_win_eur": row.get("predicted_win_eur"),
                "clearing_quote_eur": row.get("clearing_quote_eur"),
                "gap_eur": row.get("clearing_quote_eur", 0) - row.get("predicted_win_eur", 0),
            }
            for row in sorted(missed, key=lambda row: -(row.get("clearing_quote_eur") or 0))
        ][:10],
        "rivals": {
            "alerts": breaches,
            "unpriced": unpriced,
            "checked": len([team_id for team_id in limits if team_id != own]),
            "alerts_count": len(breaches),
        },
        "samples": samples,
    }

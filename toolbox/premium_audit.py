"""Prima real pagada en esta liga, solo con lo que ya está en disco.

Tipo 31: compra a LaLiga. Tipo 1: clausulazo a otro mánager. Van en tablas
distintas. El valor de referencia es el ``marketValue`` del mismo jugador el
mismo día de Madrid en ``price_snapshots``. Si ese día no hay snapshot, el
evento sale de la cuenta y se anota como sin referencia.

No modifica ``PRIMA_PUJA`` ni ``SOBREPRECIO_RIVAL_PCT``. Solo dice a cuál se
acerca la mediana, y con qué n.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any

from toolbox.engine.auction_intel import PRIMA_PUJA
from toolbox.engine.sales_audit import SOBREPRECIO_RIVAL_PCT
from toolbox.league_history import madrid_day

_TYPE_LALIGA = 31
_TYPE_CLAUSE = 1
_SMALL_N = 30

_EVENTS: list[dict[str, Any]] | None = None
_EVENT_STAMP: tuple[int, float] | None = None


def _cache_root() -> Path:
    return Path(__file__).resolve().parents[1] / ".cache"


def _json_files() -> list[Path]:
    """Cuerpos de la caché. No llevan extensión: el nombre es el hash de la URL."""
    files: list[Path] = []
    root = _cache_root()
    for folder in ("bodies", "scraper_bodies"):
        base = root / folder
        if not base.is_dir():
            continue
        files.extend(path for path in base.iterdir() if path.is_file() and path.stat().st_size <= 40_000_000)
    return files


def _unwrap(payload: Any) -> Any:
    current = payload
    for _ in range(3):
        if not isinstance(current, dict):
            break
        body = current.get("body")
        if isinstance(body, str) and body[:1] in "[{":
            try:
                current = json.loads(body)
                continue
            except json.JSONDecodeError:
                return None
        if isinstance(body, (dict, list)):
            current = body
            continue
        inner = current.get("payload")
        if isinstance(inner, (dict, list)) and ("source_url" in current or "ok" in current or "kind" in current):
            current = inner
            continue
        break
    return current


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _player_id(row: dict[str, Any]) -> str | None:
    raw = row.get("playerMasterId")
    if raw is None and isinstance(row.get("playerMaster"), dict):
        raw = row["playerMaster"].get("id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _buyer_id(row: dict[str, Any]) -> str | None:
    raw = row.get("user1Id")
    if raw is None:
        raw = row.get("user1_id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _seller_id(row: dict[str, Any]) -> str | None:
    raw = row.get("user2Id")
    if raw is None:
        raw = row.get("user2_id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def dedupe_events(rows: list[Any]) -> list[dict[str, Any]]:
    """Una fila por ``id``. La caché guarda cada evento dos veces; se queda el primero."""
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_id = row.get("id")
        if event_id is None:
            kept.append(row)
            continue
        key = str(event_id)
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _quantile(sorted_values: list[float], p: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _stats(premiums: list[float]) -> dict[str, Any]:
    if not premiums:
        return {
            "n": 0,
            "mediana": None,
            "p25": None,
            "p75": None,
            "minimo": None,
            "maximo": None,
            "muestra_pequena": True,
        }
    ordered = sorted(premiums)
    return {
        "n": len(ordered),
        "mediana": statistics.median(ordered),
        "p25": _quantile(ordered, 0.25),
        "p75": _quantile(ordered, 0.75),
        "minimo": ordered[0],
        "maximo": ordered[-1],
        "muestra_pequena": len(ordered) < _SMALL_N,
    }


def _group(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        ident = row.get(key)
        if not isinstance(ident, str) or not ident:
            continue
        buckets.setdefault(ident, []).append(float(row["premium"]))
    grouped: list[dict[str, Any]] = []
    for ident, premiums in buckets.items():
        item = _stats(premiums)
        item[key] = ident
        grouped.append(item)
    grouped.sort(key=lambda item: (-int(item["n"]), str(item.get(key) or "")))
    return grouped


def _price_rows(
    events: list[dict[str, Any]],
    snapshots: dict[tuple[str, str], int],
    *,
    activity_type: int,
) -> dict[str, Any]:
    """Prima ``amount / marketValue - 1`` de un solo tipo de evento."""
    considered = [row for row in events if _as_int(row.get("activityTypeId")) == activity_type]
    priced: list[dict[str, Any]] = []
    sin_referencia = 0
    sin_datos = 0
    for row in considered:
        amount = _as_int(row.get("amount"))
        player_id = _player_id(row)
        day = madrid_day(row.get("createdAt") if isinstance(row.get("createdAt"), str) else None)
        buyer = _buyer_id(row)
        if amount is None or amount <= 0 or not player_id or not day or not buyer:
            sin_datos += 1
            continue
        value = snapshots.get((player_id, day))
        if not isinstance(value, int) or value <= 0:
            sin_referencia += 1
            continue
        item = {
            "buyer_id": buyer,
            "player_id": player_id,
            "day": day,
            "amount": amount,
            "market_value": value,
            "premium": amount / value - 1.0,
        }
        if activity_type == _TYPE_CLAUSE:
            item["seller_id"] = _seller_id(row)
        priced.append(item)
    premiums = [float(row["premium"]) for row in priced]
    summary = _stats(premiums)
    summary["n_eventos"] = len(considered)
    summary["n_sin_referencia"] = sin_referencia
    summary["n_sin_datos"] = sin_datos
    summary["por_comprador"] = _group(priced, "buyer_id")
    if activity_type == _TYPE_CLAUSE:
        summary["por_vendedor"] = _group(
            [row for row in priced if isinstance(row.get("seller_id"), str)],
            "seller_id",
        )
    return summary


def _closer(median: float | None) -> dict[str, Any]:
    prima = float(PRIMA_PUJA) - 1.0
    rival = float(SOBREPRECIO_RIVAL_PCT) / 100.0
    base = {
        "prima_puja": PRIMA_PUJA,
        "prima_puja_ratio": prima,
        "sobreprecio_rival_pct": SOBREPRECIO_RIVAL_PCT,
        "sobreprecio_rival_ratio": rival,
        "mediana": median,
        "mas_cerca": None,
        "distancia_prima_puja": None if median is None else abs(median - prima),
        "distancia_sobreprecio_rival": None if median is None else abs(median - rival),
    }
    if median is None:
        base["nota"] = "Sin mediana: no hay compras con snapshot del mismo día."
        return base
    if abs(median - prima) < abs(median - rival):
        base["mas_cerca"] = "prima_puja"
    elif abs(median - rival) < abs(median - prima):
        base["mas_cerca"] = "sobreprecio_rival"
    else:
        base["mas_cerca"] = "empate"
    return base


def build_premium_report(
    events: list[Any],
    snapshots: dict[tuple[str, str], int],
    *,
    n_filas: int | None = None,
) -> dict[str, Any]:
    """Informe puro. ``events`` puede traer duplicados; se deduplican por ``id``."""
    rows = [row for row in events if isinstance(row, dict)]
    distinct = dedupe_events(rows)
    laliga = _price_rows(distinct, snapshots, activity_type=_TYPE_LALIGA)
    clause = _price_rows(distinct, snapshots, activity_type=_TYPE_CLAUSE)
    median = laliga.get("mediana")
    comparison = _closer(median if isinstance(median, float) else None)
    comparison["n"] = laliga.get("n")
    comparison["muestra_pequena"] = bool(laliga.get("muestra_pequena"))
    notes: list[str] = []
    if laliga.get("muestra_pequena"):
        notes.append("n < 30 en compras a LaLiga: no se extrapola.")
    buyers = laliga.get("por_comprador") if isinstance(laliga.get("por_comprador"), list) else []
    if buyers and all(isinstance(row, dict) and row.get("muestra_pequena") for row in buyers):
        notes.append("Cada comprador tiene n < 30: no se extrapola por rival.")
    if notes:
        comparison["nota"] = " ".join(notes)
    clause_median = clause.get("mediana")
    clause_comparison = _closer(clause_median if isinstance(clause_median, float) else None)
    clause_comparison["n"] = clause.get("n")
    clause_comparison["muestra_pequena"] = bool(clause.get("muestra_pequena"))
    if clause.get("muestra_pequena"):
        clause_comparison["nota"] = "n < 30 en clausulazos: no se extrapola."
    return {
        "ok": True,
        "red": False,
        "n_filas": n_filas if isinstance(n_filas, int) else len(rows),
        "n_distintos": len(distinct),
        "compras_laliga": laliga,
        "clausulazos": clause,
        "comparacion_laliga": comparison,
        "comparacion_clausulazos": clause_comparison,
        "constantes_sin_cambiar": {
            "PRIMA_PUJA": PRIMA_PUJA,
            "SOBREPRECIO_RIVAL_PCT": SOBREPRECIO_RIVAL_PCT,
        },
    }


def _events_in(payload: Any) -> list[dict[str, Any]]:
    body = _unwrap(payload)
    if isinstance(body, dict) and "activityTypeId" in body:
        return [body]
    rows = body if isinstance(body, list) else None
    if rows is None and isinstance(body, dict):
        for key in ("items", "activity", "activities", "data"):
            candidate = body.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break
    if not isinstance(rows, list) or not rows:
        return []
    sample = next((row for row in rows if isinstance(row, dict)), None)
    if not isinstance(sample, dict) or "activityTypeId" not in sample:
        return []
    return [row for row in rows if isinstance(row, dict)]


def load_activity_events() -> list[dict[str, Any]]:
    """Eventos de actividad tal como están en la caché, duplicados incluidos."""
    global _EVENTS, _EVENT_STAMP
    files = _json_files()
    newest = 0.0
    for path in files:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    stamp = (len(files), newest)
    if _EVENTS is not None and _EVENT_STAMP == stamp:
        return _EVENTS
    found: list[dict[str, Any]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            if not text.lstrip()[:1] in "{[":
                continue
            payload = json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        found.extend(_events_in(payload))
    _EVENTS = found
    _EVENT_STAMP = stamp
    return found


def _remember_snapshot(
    table: dict[tuple[str, str], tuple[int, float, int]],
    row: dict[str, Any],
    *,
    league_id: str | None,
    priority: int,
) -> None:
    raw_id = row.get("player_id")
    player_id = str(raw_id).strip() if raw_id is not None and not isinstance(raw_id, bool) else ""
    day = row.get("day")
    value = _as_int(row.get("market_value"))
    if not player_id or not isinstance(day, str) or len(day) < 10:
        return
    if value is None or value <= 0:
        return
    row_league = row.get("league_id")
    if league_id and isinstance(row_league, str) and row_league and row_league != league_id:
        return
    stored = row.get("stored_at")
    stamp = float(stored) if isinstance(stored, (int, float)) and not isinstance(stored, bool) else 0.0
    key = (player_id, day[:10])
    current = table.get(key)
    if current is None or priority > current[2] or (priority == current[2] and stamp >= current[1]):
        table[key] = (value, stamp, priority)


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return [row for row in payload["rows"] if isinstance(row, dict)]
    return []


def _read_sqlite_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        exists = conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'price_snapshots'"
        ).fetchone()
        if not exists:
            return []
        cursor = conn.execute(
            "select player_id, day, league_id, market_value, stored_at from price_snapshots"
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def load_price_snapshots(league_id: str | None = None) -> dict[tuple[str, str], int]:
    """``(player_id, día) -> market_value`` desde el espejo local. Sin red.

    Si el filtro de liga deja la tabla vacía y sin filtro hay filas, se usan
    todas: el valor de mercado del jugador no cambia por liga.
    """
    root = _cache_root()
    sources = (
        (_read_json_rows(root / "supabase-local" / "price_snapshots.json"), 2),
        (_read_sqlite_rows(root / "responses.sqlite"), 1),
    )
    picked = _pick_snapshots(sources, league_id)
    if picked or league_id is None:
        return picked
    return _pick_snapshots(sources, None)


def _pick_snapshots(
    sources: tuple[tuple[list[dict[str, Any]], int], ...],
    league_id: str | None,
) -> dict[tuple[str, str], int]:
    table: dict[tuple[str, str], tuple[int, float, int]] = {}
    for rows, priority in sources:
        for row in rows:
            _remember_snapshot(table, row, league_id=league_id, priority=priority)
    return {key: value[0] for key, value in table.items()}


def report_from_cache(league_id: str | None = None) -> dict[str, Any]:
    """Informe de la liga con la actividad y los snapshots que ya están en disco."""
    events = load_activity_events()
    snapshots = load_price_snapshots(league_id)
    report = build_premium_report(events, snapshots, n_filas=len(events))
    report["league_id"] = league_id
    report["n_snapshots"] = len(snapshots)
    report["fuente"] = "cache_local"
    return report

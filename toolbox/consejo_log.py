"""Cuaderno de consejos: cada plan distinto se añade, el día no se pisa.

``plan_snapshots`` sigue guardando solo los identificadores del último plan
del día, porque el solver los usa como continuidad. Aquí va lo que hacía
falta para auditar: la cifra de la puja, la reserva, la probabilidad de
ganar y el once. La copia que sobrevive a Render está en Supabase. Sin
Supabase se queda en el sqlite local y no tumba la caja.

El once que tienes guardado en la app se reescribe mientras el primer
partido de la jornada no ha empezado. A partir de ese saque no se toca.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root, madrid_day

logger = logging.getLogger("fantasy.consejo_log")

TABLE_PLAN = "advice_events"
TABLE_XI = "xi_locks"
SEASON = "2026/27"
_TIPOS = {"PUJA", "CLAUSULAZO", "VENDE", "VENDER HOY"}


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists consejo_eventos (
            id integer primary key autoincrement,
            league_id text not null,
            day text not null,
            kind text not null,
            fingerprint text not null,
            stored_at real not null,
            payload text not null
        )
        """
    )
    conn.execute(
        """
        create unique index if not exists consejo_eventos_fp
        on consejo_eventos (league_id, kind, fingerprint)
        """
    )
    conn.commit()


def _entero(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _proba(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 4)


def _texto(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def segunda_oferta(listings: list[Any] | None) -> dict[str, Any]:
    """Segunda puja de cada anuncio, solo si la API mandó el array.

    Hoy el mercado trae el recuento y no los importes. Si el array no viene,
    se deja escrito: no se inventa una segunda oferta.
    """
    segundas: list[dict[str, Any]] = []
    con_array = 0
    for listing in listings or []:
        if not isinstance(listing, dict):
            continue
        raw = listing.get("bids")
        if not isinstance(raw, list) or not raw:
            continue
        importes = sorted(
            {
                amount
                for item in raw
                if isinstance(item, dict) and (amount := _entero(item.get("amount"))) is not None and amount > 0
            },
            reverse=True,
        )
        if not importes:
            continue
        con_array += 1
        if len(importes) < 2:
            continue
        segundas.append(
            {
                "player_id": _texto(listing.get("player_id")),
                "market_id": _texto(listing.get("market_id")),
                "primera_eur": importes[0],
                "segunda_eur": importes[1],
            }
        )
    nota = None if con_array else "la API no manda el array de pujas, solo el recuento"
    return {"anuncios_con_pujas": con_array, "segundas": segundas, "nota": nota}


def _accion(accion: dict[str, Any]) -> dict[str, Any] | None:
    tipo = accion.get("tipo")
    if tipo not in _TIPOS:
        return None
    player_id = _texto(accion.get("player_id"))
    if player_id is None and tipo != "BUSCA":
        return None
    proba = _proba(accion.get("p_ganar_por_valor"))
    if proba is None:
        proba = _proba(accion.get("p_ganar_estimada"))
    return {
        "tipo": tipo,
        "player_id": player_id,
        "nombre": _texto(accion.get("nombre")),
        "posicion": _texto(accion.get("posicion") or accion.get("position")),
        "momento": _texto(accion.get("momento")),
        "euros": _entero(accion.get("euros")),
        "puja_final": _entero(accion.get("puja_final")),
        "p_ganar": proba,
        "reserva_de": _texto(accion.get("reserva_de")),
    }


def consejo_de(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Lo que hay que poder auditar, sin el resto del informe."""
    acciones = []
    for accion in (plan or {}).get("acciones") or []:
        if isinstance(accion, dict) and (fila := _accion(accion)) is not None:
            acciones.append(fila)
    once = []
    for row in (plan or {}).get("once") or []:
        if not isinstance(row, dict):
            continue
        player_id = _texto(row.get("player_id"))
        if player_id is None:
            continue
        once.append(
            {
                "player_id": player_id,
                "nombre": _texto(row.get("nombre")),
                "posicion": _texto(row.get("posicion") or row.get("position")),
            }
        )
    mejora = (plan or {}).get("mejora_puntos_jornada")
    return {
        "mejora_puntos_jornada": float(mejora) if isinstance(mejora, (int, float)) and not isinstance(mejora, bool) else None,
        "once_recomendado": once,
        "acciones": acciones,
        "reservas": [
            {
                "player_id": _texto(row.get("player_id")),
                "nombre": _texto(row.get("nombre")),
                "reserva_de": _texto(row.get("reserva_de")),
                "euros": _entero(row.get("euros")),
            }
            for row in (plan or {}).get("reservas") or []
            if isinstance(row, dict) and _texto(row.get("player_id"))
        ],
    }


def _once_guardado(board: dict[str, Any] | None, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    fuentes: list[Any] = []
    if isinstance(payload, dict):
        fuentes.append(payload.get("saved_lineup"))
    optimize = board.get("optimize") if isinstance(board, dict) else None
    if isinstance(optimize, dict):
        fuentes.append(optimize.get("saved_lineup"))
    for source in fuentes:
        if not isinstance(source, dict):
            continue
        xi = source.get("xi")
        if not isinstance(xi, list):
            continue
        filas = []
        for row in xi:
            if not isinstance(row, dict):
                continue
            player_id = _texto(row.get("player_id"))
            if player_id is None:
                continue
            filas.append(
                {
                    "player_id": player_id,
                    "nombre": _texto(row.get("nickname") or row.get("nombre") or row.get("name")),
                    "posicion": _texto(row.get("position")),
                }
            )
        if filas:
            return filas
    return []


def _anuncios(board: dict[str, Any] | None) -> list[Any]:
    market = board.get("market") if isinstance(board, dict) else None
    listings = market.get("listings") if isinstance(market, dict) else None
    return listings if isinstance(listings, list) else []


def _huella(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parse(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _cierre_abierto(conn: sqlite3.Connection, now: datetime) -> tuple[str, int, datetime] | None:
    """Próximo primer saque ya fotografiado por ``pre_lock``. Sin foto, no hay cierre."""
    try:
        rows = conn.execute("select season, jornada, kickoff from pre_lock_snapshots").fetchall()
    except sqlite3.OperationalError:
        return None
    abierto: tuple[str, int, datetime] | None = None
    for season, jornada, kickoff in rows:
        if not isinstance(kickoff, str):
            continue
        moment = _parse(kickoff)
        if moment is None or moment <= now:
            continue
        if abierto is None or moment < abierto[2]:
            abierto = (str(season), int(jornada), moment)
    return abierto


def _append(conn: sqlite3.Connection, event: dict[str, Any]) -> bool:
    """Añade la fila si esa huella no estaba. ``False`` si era la misma."""
    ensure_schema(conn)
    before = conn.total_changes
    conn.execute(
        """
        insert or ignore into consejo_eventos
        (league_id, day, kind, fingerprint, stored_at, payload)
        values (?, ?, ?, ?, ?, ?)
        """,
        (
            event["league_id"],
            event["day"],
            event["kind"],
            event["fingerprint"],
            event["stored_at"],
            json.dumps(event["payload"], ensure_ascii=False),
        ),
    )
    conn.commit()
    return conn.total_changes > before


def _guardar_xi(conn: sqlite3.Connection, event: dict[str, Any], kickoff: datetime, now: datetime) -> bool:
    """La última foto anterior al saque. Después del saque no se escribe."""
    if now >= kickoff:
        return False
    ensure_schema(conn)
    previa = conn.execute(
        """
        select stored_at from consejo_eventos
        where league_id = ? and kind = 'xi' and fingerprint = ?
        """,
        (event["league_id"], event["fingerprint"]),
    ).fetchone()
    if previa is not None and float(previa[0]) >= float(event["stored_at"]):
        return False
    conn.execute(
        """
        insert into consejo_eventos
        (league_id, day, kind, fingerprint, stored_at, payload)
        values (?, ?, 'xi', ?, ?, ?)
        on conflict(league_id, kind, fingerprint) do update set
            day = excluded.day,
            stored_at = excluded.stored_at,
            payload = excluded.payload
        """,
        (
            event["league_id"],
            event["day"],
            event["fingerprint"],
            event["stored_at"],
            json.dumps(event["payload"], ensure_ascii=False),
        ),
    )
    conn.commit()
    return True


def _missing_table(exc: BaseException) -> bool:
    text = str(exc)
    return "PGRST205" in text or "schema cache" in text or "advice_events" in text or "xi_locks" in text


def _push_remote(events: list[dict[str, Any]]) -> None:
    from toolbox import snapshot_remote

    if not events or not snapshot_remote.enabled():
        return
    try:
        _push_tables(events)
    except Exception as exc:  # noqa: BLE001 — sin tablas queda el sobre
        if not _missing_table(exc):
            logger.warning("No se pudo guardar el consejo en Supabase: %s", exc)
            return
        _push_blob(events)


def _client() -> Any:
    import os

    from toolbox import cache as cache_module

    return cache_module.create_client(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_KEY"].strip())


def _push_tables(events: list[dict[str, Any]]) -> None:
    client = _client()
    planes = [event for event in events if event["kind"] == "plan"]
    onces = [event for event in events if event["kind"] == "xi"]
    if planes:
        client.table(TABLE_PLAN).upsert(
            [
                {
                    "league_id": event["league_id"],
                    "day": event["day"],
                    "kind": "plan",
                    "fingerprint": event["fingerprint"],
                    "stored_at": event["stored_at"],
                    "payload": json.dumps(event["payload"], ensure_ascii=False),
                }
                for event in planes
            ],
            on_conflict="league_id,kind,fingerprint",
        ).execute()
    if onces:
        client.table(TABLE_XI).upsert(
            [
                {
                    "league_id": event["league_id"],
                    "season": event["payload"]["season"],
                    "jornada": event["payload"]["jornada"],
                    "kickoff": event["payload"]["kickoff"],
                    "stored_at": event["stored_at"],
                    "payload": json.dumps(event["payload"], ensure_ascii=False),
                }
                for event in onces
            ],
            on_conflict="league_id,season,jornada",
        ).execute()


def _push_blob(events: list[dict[str, Any]]) -> None:
    from toolbox import snapshot_remote

    envelope = snapshot_remote.load("advice", "journal")
    value = dict(envelope.get("value") or {}) if isinstance(envelope, dict) else {}
    planes = [row for row in value.get("planes") or [] if isinstance(row, dict)]
    onces = {str(row.get("fingerprint")): row for row in value.get("onces") or [] if isinstance(row, dict)}
    known = {(str(row.get("league_id")), str(row.get("fingerprint"))) for row in planes}
    for event in events:
        if event["kind"] == "plan":
            key = (event["league_id"], event["fingerprint"])
            if key in known:
                continue
            known.add(key)
            planes.append(event)
            continue
        previa = onces.get(event["fingerprint"])
        if previa is not None and float(previa.get("stored_at") or 0) >= float(event["stored_at"]):
            continue
        onces[event["fingerprint"]] = event
    snapshot_remote.save(
        "advice",
        "journal",
        {"saved_unix": time.time(), "value": {"planes": planes, "onces": list(onces.values())}},
    )


def registrar(
    league_id: str | None,
    plan: dict[str, Any] | None,
    board: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    db_path: Path | None = None,
    remote: Any = None,
) -> dict[str, bool]:
    """Añade el plan si cambió y congela el once propio si el saque no ha llegado.

    ``remote`` a ``False`` no sale de la base local. Cualquier otro fallo de
    red se traga: el tablero no depende de este cuaderno.
    """
    if not isinstance(plan, dict):
        return {"plan": False, "xi": False}
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamp = moment.timestamp()
    day = madrid_day(stamp)
    liga = league_id or "_default"
    cuerpo = consejo_de(plan)
    cuerpo["once_guardado"] = _once_guardado(board, payload)
    cuerpo["segunda_oferta"] = segunda_oferta(_anuncios(board))
    plan_event = {
        "league_id": liga,
        "day": day,
        "kind": "plan",
        "fingerprint": _huella(cuerpo),
        "stored_at": stamp,
        "payload": cuerpo,
    }
    events = [plan_event]
    xi_written = False
    path = db_path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        wrote_plan = _append(conn, plan_event)
        cierre = _cierre_abierto(conn, moment)
        guardado = cuerpo["once_guardado"]
        if cierre is not None and len(guardado) == 11:
            season, jornada, kickoff = cierre
            xi_payload = {
                "season": season,
                "jornada": jornada,
                "kickoff": kickoff.isoformat(),
                "formacion": None,
                "xi": guardado,
            }
            xi_event = {
                "league_id": liga,
                "day": day,
                "kind": "xi",
                "fingerprint": f"{season}:{jornada}",
                "stored_at": stamp,
                "payload": xi_payload,
            }
            xi_written = _guardar_xi(conn, xi_event, kickoff, moment)
            if xi_written:
                events.append(xi_event)
    finally:
        conn.close()
    if remote is not False and (wrote_plan or xi_written):
        try:
            (remote or _push_remote)([event for event in events if event["kind"] == "plan" and wrote_plan or event["kind"] == "xi" and xi_written])
        except Exception:
            logger.exception("registro del consejo")
    return {"plan": wrote_plan, "xi": xi_written}

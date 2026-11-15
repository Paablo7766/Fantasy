"""Cargadores de solo lectura para la investigación de caja y pujas.

Nada de aquí escribe en ``.cache`` ni en Supabase. La base SQLite se abre en
modo ``ro``. Las funciones puras de ``toolbox`` se importan solo cuando hace
falta comparar con el cálculo vivo (``caja.py``).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
LOCAL = CACHE / "supabase-local"
OUT = Path(__file__).resolve().parent
MADRID = ZoneInfo("Europe/Madrid")

INICIAL = 100_000_000
VIDEO_DIA = 100_000
MULT_CLAUSULA = 0.5  # regla oficial 1:2: 2 M de cláusula cuestan 1 M de saldo
CREDITO = 0.20
CIERRE = time(14, 8)

# Mánager (user1Id del feed) -> equipo. Sale de las fichas de equipo cacheadas
# el 15-oct (.cache/bodies); el emparejamiento no cambia en la temporada.
EQUIPOS: dict[str, dict[str, str]] = {
    "160213": {"team_id": "40960918", "nombre": "paaabsnz"},
    "2481395": {"team_id": "40960899", "nombre": "floren romi"},
    "7008776": {"team_id": "40960858", "nombre": "pablooceballos"},
    "2247792": {"team_id": "40960836", "nombre": "Gon redon"},
    "4490595": {"team_id": "40960880", "nombre": "PABS FC"},
    "4496476": {"team_id": "40960871", "nombre": "Pedro Salcines Fc"},
    "800935": {"team_id": "40960857", "nombre": "gerardo_vp"},
    "5253411": {"team_id": "40963981", "nombre": "Sausor10"},
    "2287098": {"team_id": "40960864", "nombre": "iaaagocab"},
    "12131430": {"team_id": "40961384", "nombre": "Naviis10"},
}
PROPIO = "40960918"
NOMBRE = {v["team_id"]: v["nombre"] for v in EQUIPOS.values()}
MANAGER = {v["team_id"]: k for k, v in EQUIPOS.items()}


def team_of(manager: Any) -> str:
    return EQUIPOS[str(manager)]["team_id"]


def parse_at(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(MADRID)


def from_ts(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(MADRID)


def cierre_de(day: date) -> datetime:
    return datetime.combine(day, CIERRE, tzinfo=MADRID)


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --- Feed de actividad -------------------------------------------------------

def actividad() -> list[dict[str, Any]]:
    """Movimientos con dinero, ya resueltos a equipo, en orden de tiempo.

    Un clausulazo genera dos asientos: pago del comprador y cobro del vendedor.
    El feed no trae el cobro aparte (comprobado: ninguna fila del vendedor con
    el mismo importe y hora), así que se abona una sola vez aquí.
    """
    raw = load_json(CACHE / "activity_raw_log.json")
    out: list[dict[str, Any]] = []
    for row in raw.values():
        tipo = row.get("activityTypeId")
        if tipo not in (1, 6, 31, 33):
            continue
        at = parse_at(row["createdAt"])
        amount = int(row["amount"])
        player = str(row["playerMasterId"]) if row.get("playerMasterId") is not None else None
        team = team_of(row["user1Id"])
        base = {"id": row["id"], "at": at, "player_id": player, "amount": amount, "tipo": tipo}
        if tipo == 31:
            out.append({**base, "team_id": team, "kind": "buy", "signed": -amount})
        elif tipo == 33:
            out.append({**base, "team_id": team, "kind": "sell", "signed": amount})
        elif tipo == 6:
            out.append({**base, "team_id": team, "kind": "prize", "signed": amount, "week": row.get("weekNumber")})
        else:
            seller = team_of(row["user2Id"])
            out.append({**base, "team_id": team, "kind": "clause_paid", "signed": -amount, "counterparty": seller})
            out.append({**base, "team_id": seller, "kind": "clause_cobrada", "signed": amount, "counterparty": team})
    out.sort(key=lambda e: (e["at"], e["id"]))
    return out


# --- Cajas propias observadas -----------------------------------------------

def cajas_propias() -> list[dict[str, Any]]:
    """Saldos reales del equipo propio con su hora. Se quitan repeticiones idénticas
    en días seguidos: son la misma ficha cacheada, no un saldo nuevo."""
    obs: list[dict[str, Any]] = []
    for path in (CACHE / "bodies").iterdir():
        if not path.name.startswith("d82d3722"):
            continue
        data = load_json(path)
        if isinstance(data, dict) and isinstance(data.get("teamMoney"), int):
            con = ro(CACHE / "responses.sqlite")
            stored = con.execute(
                "select stored_at from responses where url like ?", ("%teams/40960918?%",)
            ).fetchone()
            con.close()
            obs.append(
                {"at": from_ts(stored[0]), "caja": int(data["teamMoney"]), "valor_equipo": data.get("teamValue"), "fuente": "ficha 15-oct"}
            )
    for led in load_json(LOCAL / "cash_ledgers.json"):
        if led.get("team_id") == PROPIO and isinstance(led.get("observed_cash_eur"), int):
            obs.append({"at": from_ts(led["updated_at"]), "caja": led["observed_cash_eur"], "valor_equipo": None, "fuente": "cash_ledgers"})
    prev = None
    for row in load_json(CACHE / "auditoria_lunes.json"):
        if row.get("team_id") != PROPIO:
            continue
        if prev is not None and row["caja"] == prev:
            continue
        prev = row["caja"]
        obs.append(
            {
                "at": parse_at(row["guardado_en"]),
                "caja": int(row["caja"]),
                "valor_equipo": row.get("valor_equipo"),
                "fuente": "auditoria_lunes",
            }
        )
    obs.sort(key=lambda r: r["at"])
    return obs


# --- Subidas de cláusula ----------------------------------------------------

def subidas_registradas() -> list[dict[str, Any]]:
    data = load_json(CACHE / "hidden_expenses_log.json")
    return [dict(r) for r in data.get("entries") or []]


def fotos_clausulas() -> dict[str, dict[str, dict[str, int]]]:
    return load_json(CACHE / "clause_snapshot_history.json").get("days") or {}


# --- Valores de mercado -----------------------------------------------------

def cambios_valor() -> dict[tuple[str, str], int]:
    """Variación diaria publicada con cada foto (``market_value_change``), por (jugador, día)."""
    out: dict[tuple[str, str], int] = {}
    for row in load_json(LOCAL / "price_snapshots.json"):
        if isinstance(row.get("market_value_change"), int):
            out[(str(row["player_id"]), str(row["day"]))] = row["market_value_change"]
    con = ro(CACHE / "responses.sqlite")
    for sql in (
        "select player_id, day, market_value_change from price_snapshots",
        "select player_id, day, market_value_change from player_signal_log",
    ):
        for pid, day, ch in con.execute(sql):
            if isinstance(ch, int):
                out.setdefault((str(pid), str(day)), ch)
    con.close()
    return out


def fotos_valor() -> dict[str, list[tuple[datetime, str, int, str]]]:
    """Por jugador: (guardado, día de la foto, valor, fuente), en orden de guardado.

    Se juntan cuatro tablas. Todas guardan el valor de mercado del día; lo que
    importa para no mirar el futuro es ``stored_at``.
    """
    fotos: dict[str, list[tuple[datetime, str, int, str]]] = {}

    def add(pid: Any, day: Any, value: Any, stored: Any, src: str) -> None:
        if pid is None or not isinstance(value, int) or value <= 0 or stored is None:
            return
        fotos.setdefault(str(pid), []).append((from_ts(stored), str(day), int(value), src))

    for row in load_json(LOCAL / "price_snapshots.json"):
        add(row.get("player_id"), row.get("day"), row.get("market_value"), row.get("stored_at"), "price_snapshots")
    con = ro(CACHE / "responses.sqlite")
    for pid, day, value, stored in con.execute("select player_id, day, market_value, stored_at from price_snapshots"):
        add(pid, day, value, stored, "price_snapshots_sqlite")
    for pid, day, value, stored in con.execute("select player_id, day, price, stored_at from player_signal_log"):
        add(pid, day, value, stored, "player_signal_log")
    for pid, day, value, stored in con.execute("select player_id, day, market_value, stored_at from market_listing_log"):
        add(pid, day, value, stored, "market_listing_log")
    con.close()
    for pid in fotos:
        fotos[pid].sort(key=lambda r: r[0])
    return fotos


def valor_antes(fotos: dict[str, list], pid: str, instante: datetime, max_horas: float = 36.0) -> dict[str, Any] | None:
    """Última foto guardada antes de ``instante`` y con menos de ``max_horas``."""
    previas = [f for f in fotos.get(pid, []) if f[0] < instante]
    if not previas:
        return None
    stored, day, value, src = previas[-1]
    edad = (instante - stored).total_seconds() / 3600.0
    if edad > max_horas:
        return None
    return {"valor": value, "guardado": stored, "dia_foto": day, "fuente": src, "edad_h": round(edad, 1)}


def posiciones() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in load_json(LOCAL / "player_links.json"):
        if row.get("position") and row.get("player_id"):
            out.setdefault(str(row["player_id"]), row["position"])
    for row in subidas_registradas():
        if row.get("position"):
            out.setdefault(str(row["player_id"]), row["position"])
    for pid, row in load_json(CACHE / "actas_jugadores.json").items():
        if isinstance(row, dict) and row.get("position"):
            out.setdefault(str(pid), row["position"])
    return out


def señales() -> dict[str, list[dict[str, Any]]]:
    """player_signal_log por jugador, con ``stored_at`` para no usar lo posterior."""
    con = ro(CACHE / "responses.sqlite")
    rows = con.execute(
        "select player_id, day, price, last_points, own_expected_points, stored_at from player_signal_log"
    ).fetchall()
    con.close()
    out: dict[str, list[dict[str, Any]]] = {}
    for pid, day, price, pts, xp, stored in rows:
        out.setdefault(str(pid), []).append(
            {"day": day, "price": price, "last_points": pts, "xp": xp, "stored": from_ts(stored)}
        )
    for pid in out:
        out[pid].sort(key=lambda r: r["stored"])
    return out


def listados() -> list[dict[str, Any]]:
    con = ro(CACHE / "responses.sqlite")
    rows = con.execute(
        "select market_id, day, player_id, seller_team_id, sale_price, market_value, bid_count, expires_at, stored_at "
        "from market_listing_log"
    ).fetchall()
    con.close()
    return [
        {
            "market_id": r[0],
            "day": r[1],
            "player_id": str(r[2]) if r[2] is not None else None,
            "seller": r[3],
            "sale_price": r[4],
            "market_value": r[5],
            "bid_count": r[6],
            "expires": parse_at(r[7]) if r[7] else None,
            "stored": from_ts(r[8]),
        }
        for r in rows
    ]


def mis_pujas() -> list[dict[str, Any]]:
    con = ro(CACHE / "responses.sqlite")
    rows = con.execute(
        "select snapshot_day, player_id, decision, suggested_bid, own_bid, paid_eur, winner_team_id, outcome, offer_source "
        "from market_decision_snapshots where own_bid is not null or outcome in ('lost','won','hit')"
    ).fetchall()
    con.close()
    keys = ["day", "player_id", "decision", "suggested_bid", "own_bid", "paid_eur", "winner_team_id", "outcome", "offer_source"]
    return [dict(zip(keys, r)) for r in rows]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    import math

    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - margen), min(1.0, centro + margen)


def m(x: float | int | None) -> str:
    """Millones con una coma decimal, al estilo del informe."""
    if x is None:
        return "—"
    return f"{x / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def dia_madrid(at: datetime) -> date:
    return at.astimezone(MADRID).date()


__all__ = [name for name in globals() if not name.startswith("_")]
_ = timedelta

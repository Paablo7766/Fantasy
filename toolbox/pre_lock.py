"""Foto de lo que se sabía antes del primer saque de la jornada.

Cada actualización reescribe la foto mientras ese saque no ha llegado: manda
la última. A partir del saque no se toca. El sqlite de ``.cache`` es el
cuaderno; la copia que sobrevive a un despliegue la sube
``toolbox.history_remote`` a Supabase.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root
from toolbox.matching import normalize_club
from toolbox.understat import parse_openfootball_matchdays

SEASON = "2026/27"
TABLE = "pre_lock_snapshots"

_SCHEMA = f"""
create table if not exists {TABLE} (
    season text not null,
    jornada integer not null,
    kickoff text not null,
    stored_at real not null,
    payload text not null,
    primary key (season, jornada)
)
"""


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)


def _jornadas() -> dict[tuple[str, str], int]:
    path = cache_root() / "laliga_2026_27.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    table = parse_openfootball_matchdays(text)
    # La misma clave que usan las cuotas (alias de club incluidos).
    from toolbox.scrapers import match_odds_key

    folded: dict[tuple[str, str], int] = {}
    for (home, away), jornada in table.items():
        key = match_odds_key(home, away)
        local, _, visita = key.partition("|")
        folded[(local, visita)] = jornada
        folded[(normalize_club(home), normalize_club(away))] = jornada
    return folded


def _kickoff(bundle: dict[str, Any]) -> datetime | None:
    raw = bundle.get("kickoff")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cierre_proximo(
    match_odds: dict[str, Any] | None,
    now: datetime,
    *,
    jornadas: dict[tuple[str, str], int] | None = None,
) -> tuple[int, datetime] | None:
    """Jornada del próximo saque y la hora de ese primer partido."""
    table = jornadas if jornadas is not None else _jornadas()
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    por_jornada: dict[int, datetime] = {}
    for key, bundle in (match_odds or {}).items():
        if not isinstance(bundle, dict):
            continue
        if bundle.get("source") in (None, "simulated"):
            continue
        cuando = _kickoff(bundle)
        if cuando is None or cuando <= moment:
            continue
        local, _, visita = str(key).partition("|")
        jornada = table.get((local, visita))
        if jornada is None:
            continue
        previo = por_jornada.get(jornada)
        if previo is None or cuando < previo:
            por_jornada[jornada] = cuando
    if not por_jornada:
        return None
    jornada = min(por_jornada, key=lambda j: por_jornada[j])
    return jornada, por_jornada[jornada]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _texto(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


_ACTAS: dict[str, dict[str, Any]] | None = None
_RECETA: dict[str, Any] | None = None
_RECETA_LEIDA = False


def _actas() -> dict[str, dict[str, Any]]:
    global _ACTAS
    if _ACTAS is None:
        try:
            from toolbox.player_history import actas_en_cache

            _ACTAS = actas_en_cache()
        except Exception:  # noqa: BLE001 — sin actas la foto sigue, con las dos probabilidades vacías
            _ACTAS = {}
    return _ACTAS


def _receta() -> dict[str, Any] | None:
    global _RECETA, _RECETA_LEIDA
    if not _RECETA_LEIDA:
        _RECETA_LEIDA = True
        try:
            _RECETA = json.loads((cache_root() / "reajuste_receta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _RECETA = None
    return _RECETA if isinstance(_RECETA, dict) else None


def _sigmoido(z: float) -> float:
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def probabilidades_sombra(player_id: str, week: int) -> tuple[float | None, float | None]:
    """Producción y reajuste con los minutos ya jugados, sin tocar el xP.

    El reajuste es el congelado en 24/25+25/26. Si no hay acta anterior a
    esta jornada, las dos quedan vacías: un libre del catálogo no tiene minutos.
    """
    entry = _actas().get(player_id)
    if not isinstance(entry, dict):
        return None, None
    previos = sorted(w for w in (entry.get("weeks") or {}) if isinstance(w, int) and w < week)
    if not previos:
        return None, None
    minutos = [float(entry["weeks"][w][1]) for w in previos]
    from toolbox.engine.xp2 import prob_titular_portero
    from toolbox.engine.xp_calculator import FantasyXPEngine, PartidoHistorico

    historial = [PartidoHistorico(puntos=0.0, minutos=int(m), jornada=j) for m, j in zip(minutos, previos)]
    base = FantasyXPEngine.prob_titular_heuristica(historial)
    if base is None:
        return None, None
    ficha = {
        "position": entry.get("position") or "MC",
        "p_titular": float(base),
        "historial": [
            {"jornada": j, "minutos": m, "puntos": 0, "desglose": {"puntos": {}, "cantidades": {}}}
            for m, j in zip(minutos, previos)
        ],
    }
    produccion = float(prob_titular_portero(ficha, float(base)))
    receta = _receta()
    if receta is None:
        return produccion, None
    beta = receta.get("beta")
    platt = receta.get("platt")
    if not isinstance(beta, list) or len(beta) < 6 or not isinstance(platt, list) or len(platt) != 2:
        return produccion, None
    arr = [1.0 if m >= 45 else 0.0 for m in minutos]
    season = sum(arr) / len(arr)
    recent = minutos[-3:]
    minutes = sum(min(max(m, 0.0), 90.0) / 90.0 for m in recent) / len(recent)
    k5 = sum(arr[-5:]) / len(arr[-5:])
    j1 = 1.0 if any(j == week - 1 and m >= 45 for j, m in zip(previos, minutos)) else 0.0
    starts = [j for j, m in zip(previos, minutos) if m >= 45]
    gap = 12.0 if not starts else min(12.0, float(week - max(starts)))
    z = beta[0] + beta[1] * season + beta[2] * minutes + beta[3] * k5 + beta[4] * j1 + beta[5] * (gap / 12.0)
    reajuste = _sigmoido(float(platt[0]) + float(platt[1]) * z)
    return produccion, reajuste


def _jugador(player: dict[str, Any], *, week: int | None = None) -> dict[str, Any] | None:
    pid = player.get("player_id")
    if not isinstance(pid, str) or not pid:
        return None
    precio = _num(player.get("fantasy_price"))
    if precio is None:
        precio = _num(player.get("market_value"))
    if precio is None:
        precio = _num(player.get("price"))
    fila = {
        "player_id": pid,
        "name": _texto(player.get("name")) or _texto(player.get("nickname")),
        "club": _texto(player.get("club")),
        "position": _texto(player.get("position")),
        "p_titular_ff": _num(player.get("p_titular_ff")),
        "p_titular_af": _num(player.get("p_titular_af")) if player.get("p_titular_af") is not None else _num(player.get("af_p_titular")),
        "p_titular": _num(player.get("p_titular")),
        "p_titular_source": _texto(player.get("p_titular_source")) or _texto(player.get("p_titular_fuente")),
        "lineup_status": _texto(player.get("lineup_status")) or _texto(player.get("lineupStatus")),
        "own_expected_points": _num(player.get("own_expected_points")),
        "price": precio,
        "market_goal_probability": _num(player.get("market_goal_probability")),
        "market_goal_price": _num(player.get("market_goal_price")),
        "signal_stored_at": _num(player.get("signal_stored_at")),
        "p_titular_prod": None,
        "p_titular_reajuste": None,
    }
    if week is not None:
        prod, reajuste = probabilidades_sombra(str(pid), week)
        fila["p_titular_prod"] = prod
        fila["p_titular_reajuste"] = reajuste
    return fila


def build_payload(
    players: list[dict[str, Any]] | None,
    match_odds: dict[str, Any] | None,
    *,
    week: int | None = None,
) -> dict[str, Any]:
    gente = [row for row in (_jugador(p, week=week) for p in players or [] if isinstance(p, dict)) if row]
    partidos: list[dict[str, Any]] = []
    goleadores: list[dict[str, Any]] = []
    for key, bundle in (match_odds or {}).items():
        if not isinstance(bundle, dict) or bundle.get("source") in (None, "simulated"):
            continue
        odds = bundle.get("odds_1x2")
        if not isinstance(odds, (list, tuple)) or len(odds) != 3:
            continue
        partidos.append(
            {
                "match_key": str(key),
                "kickoff": bundle.get("kickoff") if isinstance(bundle.get("kickoff"), str) else None,
                "odds_1x2": [float(x) for x in odds],
                "odds_ou25": list(bundle["odds_ou25"]) if isinstance(bundle.get("odds_ou25"), (list, tuple)) else None,
                "source": bundle.get("source"),
            }
        )
        for scorer in bundle.get("anytime_scorers") or []:
            if not isinstance(scorer, dict) or not isinstance(scorer.get("name"), str):
                continue
            price = _num(scorer.get("price"))
            if price is None:
                continue
            goleadores.append(
                {
                    "match_key": str(key),
                    "name": scorer["name"],
                    "player_id": scorer.get("player_id") if isinstance(scorer.get("player_id"), str) else None,
                    "price": price,
                    "market_goal_probability": _num(scorer.get("market_goal_probability")),
                    "suspended": bool(scorer.get("suspended")),
                }
            )
    return {"players": gente, "matches": partidos, "scorers": goleadores}


def freeze_pre_lock(
    players: list[dict[str, Any]] | None,
    match_odds: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    conn: sqlite3.Connection | None = None,
    lock: tuple[int, datetime] | None = None,
    season: str = SEASON,
) -> dict[str, Any]:
    """Guarda la foto si el primer saque de esa jornada todavía no ha llegado."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cierre = lock if lock is not None else cierre_proximo(match_odds, moment)
    if cierre is None:
        return {"wrote": False, "reason": "sin partido pendiente con jornada"}
    jornada, kickoff = cierre
    if moment >= kickoff:
        return {"wrote": False, "reason": "jornada ya cerrada", "jornada": jornada}
    payload = build_payload(players, match_odds, week=jornada)
    if not payload["players"] and not payload["matches"] and not payload["scorers"]:
        return {"wrote": False, "reason": "foto vacía", "jornada": jornada}
    stamp = moment.timestamp()
    own = conn is None
    db = conn or sqlite3.connect(_db_path())
    try:
        ensure_schema(db)
        previous = db.execute(
            f"select stored_at from {TABLE} where season = ? and jornada = ?",
            (season, jornada),
        ).fetchone()
        if previous is not None and float(previous[0]) >= stamp:
            return {"wrote": False, "reason": "ya hay una foto igual o más nueva", "jornada": jornada}
        db.execute(
            f"""
            insert into {TABLE} (season, jornada, kickoff, stored_at, payload)
            values (?, ?, ?, ?, ?)
            on conflict(season, jornada) do update set
                kickoff = excluded.kickoff,
                stored_at = excluded.stored_at,
                payload = excluded.payload
            """,
            (season, jornada, kickoff.astimezone(timezone.utc).isoformat(), stamp, json.dumps(payload, ensure_ascii=False)),
        )
        db.commit()
    finally:
        if own:
            db.close()
    return {
        "wrote": True,
        "jornada": jornada,
        "kickoff": kickoff.astimezone(timezone.utc).isoformat(),
        "players": len(payload["players"]),
        "matches": len(payload["matches"]),
        "scorers": len(payload["scorers"]),
    }


def leer(jornada: int, *, season: str = SEASON, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    own = conn is None
    db = conn or sqlite3.connect(_db_path())
    try:
        ensure_schema(db)
        row = db.execute(
            f"select kickoff, stored_at, payload from {TABLE} where season = ? and jornada = ?",
            (season, jornada),
        ).fetchone()
    finally:
        if own:
            db.close()
    if row is None:
        return None
    payload = json.loads(row[2])
    return {"kickoff": row[0], "stored_at": float(row[1]), "payload": payload if isinstance(payload, dict) else {}}


def players_desde_senales(antes_de: float, *, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Última fila de ``player_signal_log`` de cada jugador anterior a un saque."""
    try:
        filas = conn.execute(
            """
            select player_id, stored_at, price, own_expected_points, p_titular_ff, p_titular_af,
                   p_titular_final, p_titular_fuente, lineup_status
            from player_signal_log
            where stored_at < ?
            order by stored_at
            """,
            (antes_de,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    ultima: dict[str, Any] = {}
    for pid, stored_at, price, xp, ff, af, final, fuente, lineup in filas:
        ultima[str(pid)] = {
            "player_id": str(pid),
            "signal_stored_at": float(stored_at),
            "price": price,
            "own_expected_points": xp,
            "p_titular_ff": ff,
            "p_titular_af": af,
            "p_titular": final,
            "p_titular_source": fuente,
            "lineup_status": lineup,
        }
    return list(ultima.values())

"""Informe del modelo para el Laboratorio y texto para pegar en una conversación.

Junta en un sitio lo que hoy está repartido: de dónde sale cada dato (y si es
un respaldo), qué dice el mercado frente al modelo para la próxima jornada,
goleadores de bet365 frente a la probabilidad propia, qué se ha guardado de
cada jornada y qué está en modo sombra con la regla que tiene que cumplir.

Solo lee: el tablero en memoria y las tablas de ``responses.sqlite``.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root
from toolbox.matching import normalize_club

# Fuentes que se enseñan arriba, en este orden, con su nombre de persona.
KEY_SOURCES: tuple[tuple[str, str], ...] = (
    ("understat", "xG y calendario"),
    ("laliga_odds", "Cuotas de partido"),
    ("laliga_scorer_odds", "Cuotas de goleador"),
    ("futbolfantasy_lineups", "Alineaciones probables"),
    ("futbolfantasy_fitness", "Lesionados"),
    ("futbolfantasy_sanctions", "Sancionados"),
    ("own_intel_points", "Puntos esperados (propio)"),
    ("analiticafantasy", "AnalíticaFantasy"),
    ("jornadaperfecta", "Jornada Perfecta"),
    ("fbref", "FBref"),
    ("sofascore", "Sofascore"),
)

# Regla fijada el 2026-11-04, antes de ver datos: el mercado de goleador solo
# entra en el xP si la gana con margen y con muestra suficiente.
SCORER_RULE = {
    "min_jornadas": 4,
    "min_players": 300,
    "rule": (
        "Entra en el xP solo con ≥4 jornadas y ≥300 jugadores medidos, si su Brier de «marca» "
        "es al menos un 3 % mejor que el propio con el intervalo al 90 % sin cruzar el cero. "
        "Peso máximo del mercado: 50 %."
    ),
}


def _db(path: Path | None) -> sqlite3.Connection | None:
    db = path or cache_root() / "responses.sqlite"
    if not db.is_file():
        return None
    return sqlite3.connect(db)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("select name from sqlite_master where type='table'")}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --- Fuentes ----------------------------------------------------------------


def sources_summary(trends: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = trends.get("sources") if isinstance(trends, dict) and isinstance(trends.get("sources"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key, label in KEY_SOURCES:
        status = raw.get(key)
        if not isinstance(status, dict):
            continue
        error = status.get("error") if isinstance(status.get("error"), str) and status.get("error") else None
        ok = status.get("ok") is not False
        fallback = bool(ok and error and "caído" in error)
        rows.append(
            {
                "id": key,
                "label": label,
                "state": "respaldo" if fallback else ("ok" if ok else "fallo"),
                "count": status.get("count"),
                "source": status.get("source"),
                "detail": error,
            }
        )
    return rows


# --- Partidos: mercado frente a modelo ---------------------------------------


JORNADA_SPAN_DAYS = 4


def _market_weight(hours: float | None) -> float:
    h = 48.0 if hours is None else max(0.0, hours)
    return 0.55 + (0.82 - 0.55) * math.exp(-h / 72.0)


def _devig(odds: tuple[float, ...]) -> list[float]:
    raw = [1.0 / o for o in odds]
    total = sum(raw)
    return [r / total for r in raw]


def _latest_odds(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if "odds_snapshots" not in _tables(conn):
        return {}
    rows = conn.execute(
        """
        select o.match_key, o.day, o.kickoff, o.odds_home, o.odds_draw, o.odds_away,
               o.odds_over25, o.odds_under25, o.odds_btts_yes, o.odds_btts_no,
               (select count(*) from odds_snapshots x where x.match_key = o.match_key) as days
        from odds_snapshots o
        where o.day = (select max(day) from odds_snapshots y where y.match_key = o.match_key)
        """
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for key, day, kickoff, h, d, a, over, under, yes, no, days in rows:
        out[str(key)] = {
            "day": day,
            "kickoff": kickoff,
            "odds_1x2": (h, d, a),
            "odds_ou25": (over, under) if over and under else None,
            "odds_btts": (yes, no) if yes and no else None,
            "days_stored": days,
        }
    return out


def upcoming_matches(trends: dict[str, Any] | None, conn: sqlite3.Connection | None, *, now: datetime) -> list[dict[str, Any]]:
    """Próximo partido de cada club, con lo que dice el modelo y lo que dice el mercado."""
    players = trends.get("players") if isinstance(trends, dict) and isinstance(trends.get("players"), list) else []
    cells: dict[str, dict[str, Any]] = {}
    for player in players:
        if not isinstance(player, dict):
            continue
        calendar = player.get("own_calendar")
        club = player.get("club")
        if not isinstance(calendar, list) or not calendar or not isinstance(club, str):
            continue
        cell = calendar[0]
        if not isinstance(cell, dict) or not isinstance(cell.get("opponent"), str):
            continue
        key = normalize_club(club)
        cells.setdefault(key, {**cell, "club": club})
    odds = _latest_odds(conn) if conn is not None else {}
    matches: dict[str, dict[str, Any]] = {}
    for club_key, cell in cells.items():
        opp_key = normalize_club(str(cell["opponent"]))
        home = cell.get("is_home") is not False
        match_key = f"{club_key}|{opp_key}" if home else f"{opp_key}|{club_key}"
        row = matches.setdefault(
            match_key,
            {"match_key": match_key, "kickoff": cell.get("kickoff"), "home": None, "away": None},
        )
        side = {
            "club": cell["club"],
            "lambda_for": _num(cell.get("lambda_for")),
            "p_cs": _num(cell.get("p_cs_for")),
            "predicted_score": cell.get("predicted_score"),
        }
        row["home" if home else "away"] = side
    out: list[dict[str, Any]] = []
    for key, row in matches.items():
        market = odds.get(key)
        kickoff = _parse_time(row.get("kickoff") or (market or {}).get("kickoff"))
        if kickoff is not None and kickoff < now:
            continue
        hours = (kickoff - now).total_seconds() / 3600 if kickoff else None
        entry: dict[str, Any] = {
            "match_key": key,
            "kickoff": kickoff.isoformat() if kickoff else None,
            "home": row["home"],
            "away": row["away"],
            "market": None,
            "market_weight": round(_market_weight(hours), 2) if market else 0.0,
        }
        if market and all(isinstance(x, (int, float)) and x > 1 for x in market["odds_1x2"]):
            p_home, p_draw, p_away = _devig(tuple(float(x) for x in market["odds_1x2"]))
            lambdas = None
            try:
                from toolbox.understat import invert_market_to_dixon_coles

                lh, la, _rho = invert_market_to_dixon_coles(
                    tuple(float(x) for x in market["odds_1x2"]),  # type: ignore[arg-type]
                    market["odds_ou25"],
                    market["odds_btts"],
                )
                lambdas = (round(lh, 2), round(la, 2))
            except Exception:  # noqa: BLE001 — sin λ de mercado se enseñan solo las probabilidades
                lambdas = None
            entry["market"] = {
                "odds_1x2": market["odds_1x2"],
                "p_home": round(p_home, 3),
                "p_draw": round(p_draw, 3),
                "p_away": round(p_away, 3),
                "lambda_home": lambdas[0] if lambdas else None,
                "lambda_away": lambdas[1] if lambdas else None,
                "captured_day": market["day"],
                "days_stored": market["days_stored"],
            }
        out.append(entry)
    out.sort(key=lambda item: item["kickoff"] or "9999")
    # Solo la próxima jornada: un club que ya jugó la suya (p. ej. el viernes)
    # traía como «próximo» el partido de la jornada siguiente, con el rival en
    # «?». Una jornada cabe en 4 días (viernes-lunes); lo que cae más lejos del
    # primer partido pendiente es de la siguiente.
    first = next((_parse_time(item["kickoff"]) for item in out if item["kickoff"]), None)
    if first is not None:
        limit = first + timedelta(days=JORNADA_SPAN_DAYS)
        out = [item for item in out if not item["kickoff"] or (_parse_time(item["kickoff"]) or first) <= limit]
    return out


# --- Goleadores ---------------------------------------------------------------


def scorers(trends: dict[str, Any] | None, squads: dict[str, Any] | None, conn: sqlite3.Connection | None, *, now: datetime) -> dict[str, Any]:
    if conn is None or "scorer_odds_snapshots" not in _tables(conn):
        return {"rows": [], "linked": 0, "listed": 0}
    rows = conn.execute(
        """
        select s.match_key, s.player_name, s.price, s.player_id, s.market_goal_probability, s.kickoff
        from scorer_odds_snapshots s
        where s.day = (select max(day) from scorer_odds_snapshots y where y.match_key = s.match_key)
        """
    ).fetchall()
    players = trends.get("players") if isinstance(trends, dict) and isinstance(trends.get("players"), list) else []
    by_id = {p.get("player_id"): p for p in players if isinstance(p, dict)}
    mine: set[str] = set()
    if isinstance(squads, dict):
        from toolbox.analyzer import own_squad

        own = own_squad(squads)
        if isinstance(own, dict):
            mine = {str(p.get("player_id")) for p in own.get("players") or [] if isinstance(p, dict)}
    out: list[dict[str, Any]] = []
    listed = 0
    for match_key, name, price, player_id, market_p, kickoff in rows:
        moment = _parse_time(kickoff)
        if moment is not None and moment < now:
            continue
        listed += 1
        player = by_id.get(player_id) if player_id else None
        if player is None:
            continue
        own_p = _num(player.get("own_goal_probability"))
        out.append(
            {
                "player_id": player_id,
                "name": player.get("nickname") or player.get("name") or name,
                "club": player.get("club"),
                "position": player.get("position"),
                "mine": str(player_id) in mine,
                "price": price,
                "market_p": _num(market_p),
                "own_p": own_p,
                "gap": round(_num(market_p) - own_p, 3) if _num(market_p) is not None and own_p is not None else None,
                "match_key": match_key,
            }
        )
    out.sort(key=lambda item: -(item["market_p"] or 0))
    return {"rows": out, "linked": len(out), "listed": listed}


# --- Histórico guardado -------------------------------------------------------


def history(conn: sqlite3.Connection | None) -> dict[str, Any]:
    if conn is None:
        return {"jornadas": [], "odds_days": 0, "odds_matches": 0, "scorer_rows": 0}
    tables = _tables(conn)
    jornadas: list[dict[str, Any]] = []
    if "matchday_snapshots" in tables:
        for jornada, total, scored, mae, xi in conn.execute(
            """
            select jornada_id, count(*), sum(actual_points is not null),
                   avg(case when actual_points is not null and expected_points is not null
                            then abs(actual_points - expected_points) end),
                   sum(in_once_optimo)
            from matchday_snapshots group by jornada_id
            order by cast(jornada_id as integer)
            """
        ):
            days = 0
            if "matchday_snapshot_log" in tables:
                days = conn.execute(
                    "select count(distinct snapshot_day) from matchday_snapshot_log where jornada_id = ?", (jornada,)
                ).fetchone()[0]
            jornadas.append(
                {
                    "jornada": str(jornada),
                    "players": int(total or 0),
                    "evaluated": int(scored or 0),
                    "mae": round(float(mae), 2) if mae is not None else None,
                    "xi": int(xi or 0),
                    "days_logged": int(days or 0),
                }
            )
    odds_days = odds_matches = scorer_rows = 0
    if "odds_snapshots" in tables:
        odds_days, odds_matches = conn.execute("select count(distinct day), count(distinct match_key) from odds_snapshots").fetchone()
    if "scorer_odds_snapshots" in tables:
        scorer_rows = conn.execute("select count(*) from scorer_odds_snapshots").fetchone()[0]
    return {
        "jornadas": jornadas,
        "odds_days": int(odds_days or 0),
        "odds_matches": int(odds_matches or 0),
        "scorer_rows": int(scorer_rows or 0),
    }


def shadow_items(conn: sqlite3.Connection | None, hist: dict[str, Any], *, now: datetime) -> list[dict[str, Any]]:
    played_scorer_matches = 0
    if conn is not None and "scorer_odds_snapshots" in _tables(conn):
        played_scorer_matches = conn.execute(
            "select count(distinct match_key) from scorer_odds_snapshots where kickoff is not null and kickoff < ?",
            (now.isoformat(),),
        ).fetchone()[0]
    played_odds_matches = 0
    if conn is not None and "odds_snapshots" in _tables(conn):
        played_odds_matches = conn.execute(
            "select count(distinct match_key) from odds_snapshots where kickoff is not null and kickoff < ?",
            (now.isoformat(),),
        ).fetchone()[0]
    jornadas_scored = sum(1 for row in hist["jornadas"] if row["evaluated"] > 0)
    return [
        {
            "id": "scorer_odds",
            "label": "Cuotas de goleador (bet365) en el xP",
            "state": "sombra",
            "progress": min(1.0, (played_scorer_matches / 10) / SCORER_RULE["min_jornadas"]),
            "progress_text": f"{played_scorer_matches} partidos con cuota de goleador ya jugados (≈{played_scorer_matches / 10:.1f} de {SCORER_RULE['min_jornadas']} jornadas)",
            "rule": SCORER_RULE["rule"],
        },
        {
            "id": "match_odds_weight",
            "label": "Peso del mercado en los goles esperados (55–82 %)",
            "state": "activo, sin validar",
            "progress": min(1.0, (played_odds_matches / 10) / 4),
            "progress_text": f"{played_odds_matches} partidos con cuotas guardadas ya jugados",
            "rule": "Con ≥4 jornadas guardadas: comparar el error de goles de la mezcla frente al mercado solo y al xG solo, y fijar el peso que menos falle.",
        },
        {
            "id": "xp_snapshots",
            "label": "Histórico de xP por jornada",
            "state": "guardando",
            "progress": min(1.0, jornadas_scored / 4),
            "progress_text": f"{jornadas_scored} jornada{'' if jornadas_scored == 1 else 's'} ya evaluada{'' if jornadas_scored == 1 else 's'} con puntos reales",
            "rule": "Base para medir cualquier cambio del modelo: sin jornadas evaluadas no se toca nada.",
        },
        {
            "id": "fotmob_scale",
            "label": "Escala FotMob → Understat (×1,16)",
            "state": "provisional",
            "progress": 0.25,
            "progress_text": "Medida una vez (4-nov, 89 jugadores, correlación 0,97)",
            "rule": "Repetir la comparación el mismo día en que Understat vuelva a responder y ajustar el factor.",
        },
    ]


# --- Texto para pegar ---------------------------------------------------------


def _pct(value: Any) -> str:
    number = _num(value)
    return f"{number * 100:.0f} %" if number is not None else "—"


def _f(value: Any, digits: int = 2) -> str:
    number = _num(value)
    return f"{number:.{digits}f}" if number is not None else "—"


def render_text(report: dict[str, Any], calibration: dict[str, Any] | None = None) -> str:
    lines: list[str] = []
    lines.append(f"# Informe del modelo · LaLiga Fantasy · {report['generated_at'][:16].replace('T', ' ')} UTC")
    lines.append("")
    lines.append(f"Liga {report.get('league_id') or '—'} · próxima jornada J{report.get('jornada') or '?'} · foto del tablero: {report.get('dashboard_at') or '—'}")
    lines.append("")
    lines.append("## Fuentes")
    for row in report["sources"]:
        extra = f" · {row['detail']}" if row.get("detail") else ""
        count = f" ({row['count']})" if row.get("count") not in (None, 0) else ""
        lines.append(f"- {row['label']}: {row['state']}{count}{extra}")
    lines.append("")
    lines.append("## Próxima jornada: modelo frente a mercado")
    lines.append("Partido | Hora (UTC) | Mercado 1-X-2 | Goles mercado | Goles modelo (mezcla) | Peso mercado | Portería a cero (modelo)")
    for m in report["matches"]:
        home, away, market = m.get("home") or {}, m.get("away") or {}, m.get("market")
        name = f"{home.get('club', '?')} - {away.get('club', '?')}"
        probs = f"{_pct(market['p_home'])}-{_pct(market['p_draw'])}-{_pct(market['p_away'])}" if market else "sin cuotas"
        goals_mkt = f"{_f(market.get('lambda_home'))}-{_f(market.get('lambda_away'))}" if market else "—"
        goals_model = f"{_f(home.get('lambda_for'))}-{_f(away.get('lambda_for'))}"
        cs = f"{_pct(home.get('p_cs'))} / {_pct(away.get('p_cs'))}"
        lines.append(f"{name} | {(m.get('kickoff') or '')[:16]} | {probs} | {goals_mkt} | {goals_model} | {_pct(m.get('market_weight'))} | {cs}")
    lines.append("")
    sc = report["scorers"]
    lines.append(f"## Goleadores: bet365 frente al modelo (modo sombra) · {sc['linked']} de {sc['listed']} enlazados")
    lines.append("Jugador | Club | Mío | Cuota | P(gol) mercado | P(gol) modelo | Diferencia")
    for row in sc["rows"][:40]:
        lines.append(
            f"{row['name']} | {row.get('club') or '—'} | {'sí' if row['mine'] else ''} | {_f(row['price'])} | "
            f"{_pct(row['market_p'])} | {_pct(row['own_p'])} | {_pct(row['gap']) if row['gap'] is not None else '—'}"
        )
    lines.append("")
    hist = report["history"]
    lines.append("## Histórico guardado")
    lines.append(f"Cuotas de partido: {hist['odds_matches']} partidos en {hist['odds_days']} días · filas de goleador: {hist['scorer_rows']}")
    lines.append("Jornada | Jugadores | Evaluados | Error medio (pts) | Días guardados")
    for row in hist["jornadas"]:
        lines.append(f"J{row['jornada']} | {row['players']} | {row['evaluated']} | {_f(row['mae'])} | {row['days_logged']}")
    lines.append("")
    lines.append("## En pruebas (no deciden nada todavía)")
    for item in report["shadow"]:
        lines.append(f"- {item['label']} · {item['state']} · {item['progress_text']}. Regla: {item['rule']}")
    if isinstance(calibration, dict) and calibration.get("ok") is not False:
        lines.append("")
        lines.append("## Calibración del motor")
        for key in ("points", "engine_confidence", "coverage"):
            value = calibration.get(key)
            if value:
                lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, default=str)[:900]}")
    lines.append("")
    lines.append(
        "Contexto: el xP sale solo de own_intel. Las cuotas de partido (Pinnacle) se mezclan con el xG para "
        "los goles esperados de la próxima jornada; las de goleador (bet365) solo se miden. Si Understat cae, "
        "el xG viene de FotMob + football-data escalado ×1,16."
    )
    return "\n".join(lines)


def build_model_report(
    board: dict[str, Any],
    *,
    calibration: dict[str, Any] | None = None,
    db_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
    jornada = None
    try:
        from toolbox.matchday_auto import _load_track

        jornada = _load_track().infer_jornada_id(trends, squads, fallback="")
    except Exception:  # noqa: BLE001 — sin jornada el informe sigue
        jornada = None
    conn = _db(db_path)
    try:
        hist = history(conn)
        report = {
            "generated_at": moment.isoformat(),
            "dashboard_at": board.get("dashboard_at"),
            "league_id": (trends or {}).get("league_id") or (squads or {}).get("league_id"),
            "jornada": jornada or None,
            "sources": sources_summary(trends),
            "matches": upcoming_matches(trends, conn, now=moment),
            "scorers": scorers(trends, squads, conn, now=moment),
            "history": hist,
            "shadow": shadow_items(conn, hist, now=moment),
        }
    finally:
        if conn is not None:
            conn.close()
    report["text"] = render_text(report, calibration)
    return report

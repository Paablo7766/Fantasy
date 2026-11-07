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


# --- Marcador por fuente ------------------------------------------------------

# Con menos casos que esto la cifra se enseña, pero no se saca conclusión.
SCORE_MIN_N = 30


def _verdict(n: int, better: bool | None) -> str:
    """«pocos datos» hasta SCORE_MIN_N; después gana/pierde frente a la referencia."""
    if n < SCORE_MIN_N or better is None:
        return "pocos_datos"
    return "mejor" if better else "peor"


def scoreboard(conn: sqlite3.Connection | None, board: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Cuánto acierta cada fuente contra la realidad, con su referencia y cuántos casos hay.

    Cada fila: ``id``, ``label``, ``measure`` (qué se mide), ``value`` y ``baseline``
    (texto ya formateado), ``n``, ``verdict`` (``mejor`` / ``peor`` / ``pocos_datos`` /
    ``sin_medir``) y ``note``. Solo lee. Lo que aún no se puede medir sale como
    ``sin_medir`` con el motivo, para que se vea que se guarda pero no se compara.
    """
    rows: list[dict[str, Any]] = []
    if conn is None:
        return rows
    tables = _tables(conn)

    # 1. xP del modelo frente a puntos reales (y frente a no saber nada).
    if "matchday_snapshots" in tables:
        n, mae, bias, mean_actual = conn.execute(
            """select count(*), avg(abs(actual_points - expected_points)),
                      avg(actual_points - expected_points), avg(actual_points)
               from matchday_snapshots where actual_points is not null and expected_points is not null"""
        ).fetchone()
        n = int(n or 0)
        base = None
        if n and mean_actual is not None:
            base = conn.execute(
                "select avg(abs(actual_points - ?)) from matchday_snapshots where actual_points is not null and expected_points is not null",
                (mean_actual,),
            ).fetchone()[0]
        rows.append(
            {
                "id": "xp_modelo",
                "label": "Puntos esperados (modelo propio)",
                "measure": "Error medio en puntos por jugador y jornada. Menos es mejor.",
                "value": f"{_f(mae)} pts" if n else "—",
                "baseline": f"{_f(base)} pts si se predijera siempre la media" if base is not None else None,
                "n": n,
                "verdict": _verdict(n, (mae < base) if n and base is not None and mae is not None else None),
                "note": f"Sesgo medio {_f(bias)} pts (positivo = el modelo se queda corto)." if n and bias is not None else None,
            }
        )

    # 2. Modelo propio frente a AF, mismo jugador y mismo día de foto.
    if "matchday_snapshots" in tables and "player_signal_log" in tables:
        cols = {r[1] for r in conn.execute("pragma table_info(player_signal_log)")}
        if "af_expected_points" in cols:
            n, mine, theirs = conn.execute(
                """select count(*), avg(abs(m.actual_points - m.expected_points)), avg(abs(m.actual_points - s.af_expected_points))
                   from matchday_snapshots m join player_signal_log s
                     on s.player_id = m.player_id and s.day = m.snapshot_day and s.league_id = m.league_id
                   where m.actual_points is not null and m.expected_points is not null and s.af_expected_points is not null"""
            ).fetchone()
            n = int(n or 0)
            rows.append(
                {
                    "id": "af_vs_propio",
                    "label": "AF frente a tu modelo",
                    "measure": "Mismos jugadores y misma foto: error medio de cada uno. Menos es mejor.",
                    "value": f"AF {_f(theirs)} pts" if n else "—",
                    "baseline": f"Tu modelo {_f(mine)} pts" if n else None,
                    "n": n,
                    "verdict": _verdict(n, (theirs < mine) if n and mine is not None and theirs is not None else None),
                    "note": "«Mejor» aquí significa que AF falla menos que tu modelo.",
                }
            )

    # 3. Decisiones de mercado ya resueltas.
    if "market_decision_snapshots" in tables:
        won, lost, unknown = (
            int(x or 0)
            for x in conn.execute(
                """select sum(outcome = 'won'), sum(outcome = 'lost'),
                          sum(outcome is null or outcome = 'unknown')
                   from market_decision_snapshots where decision = 'PUJAR'"""
            ).fetchone()
        )
        resolved = won + lost
        expected = conn.execute(
            "select avg(win_probability) from market_decision_snapshots where decision = 'PUJAR' and outcome in ('won','lost')"
        ).fetchone()[0]
        rows.append(
            {
                "id": "pujar",
                "label": "Pujas recomendadas (PUJAR)",
                "measure": "Porcentaje de pujas ganadas frente a la probabilidad que prometía el motor.",
                "value": f"{won} de {resolved} ganadas" if resolved else "sin resolver",
                "baseline": f"Prometía {_pct(expected)}" if expected is not None else None,
                "n": resolved,
                "verdict": _verdict(resolved, (won / resolved >= expected) if resolved and expected is not None else None),
                "note": f"{unknown} más sin resultado conocido todavía." if unknown else None,
            }
        )

    # 4. Previa: TOP frente a la regla ingenua.
    if board is not None:
        try:
            from toolbox.previa import evaluate

            ev = evaluate(conn, board)
        except Exception:  # noqa: BLE001 — la previa no tumba el informe
            ev = []
        top_n = top_sum = naive_sum = 0.0
        for row in ev:
            t, nv = row.get("top") or {}, row.get("naive_top") or {}
            if t.get("mean") is not None and nv.get("mean") is not None:
                top_n += t["n"]
                top_sum += t["mean"] * t["n"]
                naive_sum += nv["mean"] * nv["n"]
        if top_n:
            top_mean, naive_mean = top_sum / top_n, naive_sum / top_n
            rows.append(
                {
                    "id": "previa_top",
                    "label": "Previa: TOP de cada partido",
                    "measure": "Puntos medios reales de los elegidos frente a la regla ingenua guardada en la misma edición.",
                    "value": f"{_f(top_mean)} pts",
                    "baseline": f"Ingenua {_f(naive_mean)} pts",
                    "n": int(top_n),
                    "verdict": _verdict(int(top_n), top_mean > naive_mean),
                    "note": f"{len(ev)} edición{'' if len(ev) == 1 else 'es'} evaluada{'' if len(ev) == 1 else 's'}.",
                }
            )
        else:
            rows.append(
                {
                    "id": "previa_top", "label": "Previa: TOP de cada partido",
                    "measure": "Puntos medios reales de los elegidos frente a la regla ingenua.",
                    "value": "—", "baseline": None, "n": 0, "verdict": "sin_medir",
                    "note": "Aún no hay una edición congelada de una jornada ya jugada.",
                }
            )

    # 5 y 6. Lo que se guarda pero todavía no se puede comparar con resultados.
    odds_n = scorer_n = 0
    if "odds_snapshots" in tables:
        odds_n = conn.execute("select count(distinct match_key) from odds_snapshots").fetchone()[0]
    if "scorer_odds_snapshots" in tables:
        scorer_n = conn.execute("select count(*) from scorer_odds_snapshots").fetchone()[0]
    rows.append(
        {
            "id": "mercado_partido",
            "label": "Cuotas de partido (Pinnacle)",
            "measure": "Si la mezcla mercado + xG acierta los goles mejor que cada uno por separado.",
            "value": f"{odds_n} partidos guardados", "baseline": None, "n": int(odds_n or 0),
            "verdict": "sin_medir",
            "note": "Se guardan cada día, pero la app aún no guarda el resultado de cada partido para compararlo.",
        }
    )
    rows.append(
        {
            "id": "mercado_goleador",
            "label": "Cuotas de goleador (bet365)",
            "measure": "Si la probabilidad de gol de las casas acierta más que la de tu modelo.",
            "value": f"{scorer_n} cuotas guardadas" if scorer_n else "nada guardado",
            "baseline": None, "n": int(scorer_n or 0), "verdict": "sin_medir",
            "note": "No hay ninguna cuota de goleador guardada: hay que revisar por qué la fuente no las trae."
            if not scorer_n
            else "Se guardan, pero aún no se comparan con los goles reales.",
        }
    )
    return rows


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
    lines.append("## Marcador por fuente (frente a la realidad)")
    for row in report.get("scoreboard") or []:
        base = f" · {row['baseline']}" if row.get("baseline") else ""
        note = f" · {row['note']}" if row.get("note") else ""
        lines.append(f"- {row['label']}: {row['value']}{base} · n={row['n']} · {row['verdict']}{note}")
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
            "scoreboard": scoreboard(conn, board),
            "shadow": shadow_items(conn, hist, now=moment),
        }
    finally:
        if conn is not None:
            conn.close()
    report["text"] = render_text(report, calibration)
    return report

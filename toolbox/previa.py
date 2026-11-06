"""Previa de la jornada: TOP, Apuesta y No recomendable por partido.

Regla validada el 2026-11-04 con un backtest walk-forward de J3 a J11 (88
partidos, solo datos previos a cada jornada y cuotas de antes del partido):

    puntuación = media de la temporada × disponibilidad × ajuste por rival

* Disponibilidad: probabilidad de titular de las alineaciones probables (0 si
  está lesionado, sancionado o fuera); sin ese dato, si jugó las últimas 3
  jornadas de su equipo.
* Ajuste por rival: delanteros (λ propio/1,32)^0,8, medios ^0,5; defensas y
  porteros (portería a cero / media)^0,5. Exponentes fijados a priori.

Resultado del backtest: TOP 6,65 pts frente a 5,81 de «los 2 con mejor media»
(+0,84 por jugador, IC90 +0,36…+1,36). En los 67 partidos con previa de El
Bielsa: 7,28 frente a 5,74. Su Apuesta (6,08) y su No recomendable (2,65)
siguen siendo mejores que los nuestros: la Apuesta va marcada como
experimental.

Cada edición (martes: lunes-miércoles; jueves: jueves-domingo) se congela la
primera vez que se genera y no se reescribe. El lunes se evalúa contra los
puntos reales y contra la regla ingenua guardada en la misma edición.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from toolbox.cache import cache_root
from toolbox.matching import normalize_club

LIGA_LAMBDA = 1.32
OBVIOUS_PER_MATCH = 6
PICKS = 2
MADRID = ZoneInfo("Europe/Madrid")
_POS = {"POR": "POR", "PT": "POR", "DEF": "DEF", "DF": "DEF", "MC": "MED", "MED": "MED", "DEL": "DEL", "DC": "DEL"}
_OUT = {"lesionado", "baja", "fuera", "sancionado", "injured", "suspended"}


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def edition_for(moment: datetime) -> str:
    """Lunes-miércoles → «martes»; jueves-domingo → «jueves» (hora de Madrid)."""
    return "martes" if moment.astimezone(MADRID).weekday() <= 2 else "jueves"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# --- Universo de jugadores ---------------------------------------------------


def _universe(board: dict[str, Any]) -> list[dict[str, Any]]:
    """Jugadores de todas las plantillas de la liga y del mercado, con lo que se sabe de cada uno."""
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    by_trend = {p.get("player_id"): p for p in trends.get("players") or [] if isinstance(p, dict)}
    rows: dict[str, dict[str, Any]] = {}
    for team in squads.get("squads") or []:
        if not isinstance(team, dict):
            continue
        owner = "tuyo" if team.get("is_self") else (team.get("manager_name") or team.get("fantasy_team_name") or "rival")
        for player in team.get("players") or []:
            if isinstance(player, dict) and isinstance(player.get("player_id"), str):
                rows[player["player_id"]] = {**player, "_owner": owner, "_mine": bool(team.get("is_self"))}
    for listing in market.get("listings") or []:
        if isinstance(listing, dict) and isinstance(listing.get("player_id"), str):
            row = rows.setdefault(listing["player_id"], {**listing, "_owner": "mercado", "_mine": False})
            row["_on_market"] = True
            row["_sale_price"] = listing.get("sale_price") or listing.get("market_value")
    out: list[dict[str, Any]] = []
    for pid, row in rows.items():
        trend = by_trend.get(pid) or {}
        club = row.get("club") or trend.get("club")
        if not isinstance(club, str) or not club:
            continue
        out.append({**row, "_trend": trend, "_club_key": normalize_club(club), "club": club})
    return out


def _rounds(player: dict[str, Any]) -> dict[int, float]:
    raw = player.get("week_points_by_round")
    if not isinstance(raw, dict):
        return {}
    out: dict[int, float] = {}
    for key, value in raw.items():
        number = _num(value)
        try:
            out[int(key)] = number if number is not None else 0.0
        except (TypeError, ValueError):
            continue
    return out


def _season_mean(player: dict[str, Any]) -> tuple[float | None, int]:
    avg = _num(player.get("average_points"))
    rounds = _rounds(player)
    trend_points = (player.get("_trend") or {}).get("week_points")
    series = [x for x in (trend_points if isinstance(trend_points, list) else []) if _num(x) is not None]
    apps = max(len(rounds), len(series))
    if avg is not None and avg > 0:
        return avg, apps
    if series:
        return statistics.mean(float(x) for x in series), apps
    if rounds:
        return statistics.mean(rounds.values()), apps
    return None, 0


def _availability(player: dict[str, Any], club_rounds: list[int]) -> tuple[float, str]:
    trend = player.get("_trend") or {}
    texts = {str(x).lower() for x in (trend.get("lineup_status"), trend.get("fitness"), player.get("fitness"), player.get("player_status")) if x}
    sanction = trend.get("sanction") if isinstance(trend.get("sanction"), dict) else {}
    if texts & _OUT or sanction.get("suspended"):
        return 0.0, "baja"
    p_titular = _num(trend.get("p_titular"))
    if p_titular is not None:
        share = p_titular / 100 if p_titular > 1 else p_titular
        return max(0.0, min(1.0, share)), "alineaciones"
    rounds = _rounds(player)
    last = club_rounds[-3:]
    if last:
        return sum(1 for r in last if r in rounds) / len(last), "últimas 3"
    return 0.5, "sin dato"


def _fixture_factor(position: str, lam_for: float | None, lam_against: float | None) -> float:
    if position in ("DEL", "MED"):
        if lam_for is None:
            return 1.0
        return (max(lam_for, 0.05) / LIGA_LAMBDA) ** (0.8 if position == "DEL" else 0.5)
    if lam_against is None:
        return 1.0
    return (math.exp(-lam_against) / math.exp(-LIGA_LAMBDA)) ** 0.5


# --- Partidos ----------------------------------------------------------------


def _fixtures(board: dict[str, Any], conn: sqlite3.Connection | None, now: datetime) -> dict[str, dict[str, Any]]:
    """Partido → equipos, hora, λ y probabilidades, usando ``model_report``."""
    from toolbox.model_report import upcoming_matches

    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    out: dict[str, dict[str, Any]] = {}
    for match in upcoming_matches(trends, conn, now=now):
        home, away, market = match.get("home") or {}, match.get("away") or {}, match.get("market") or {}
        home_key, _, away_key = match["match_key"].partition("|")
        lam_home = _num(home.get("lambda_for")) or _num(market.get("lambda_home"))
        lam_away = _num(away.get("lambda_for")) or _num(market.get("lambda_away"))
        out[match["match_key"]] = {
            "match_key": match["match_key"],
            "home_key": home_key,
            "away_key": away_key,
            "home": home.get("club") or home_key,
            "away": away.get("club") or away_key,
            "kickoff": match.get("kickoff"),
            "lambda_home": round(lam_home, 2) if lam_home else None,
            "lambda_away": round(lam_away, 2) if lam_away else None,
            "p_cs_home": round(math.exp(-lam_away), 3) if lam_away else None,
            "p_cs_away": round(math.exp(-lam_home), 3) if lam_home else None,
            "market": match.get("market"),
            "source": "mercado+modelo" if match.get("market") and home.get("lambda_for") else ("modelo" if home.get("lambda_for") else ("mercado" if match.get("market") else "neutro")),
        }
    return out


def _calendar_fixtures(jornada: str | None, clubs: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Último respaldo: el calendario oficial en caché, sin λ (rival neutro).

    Sirve cuando el tablero no trae calendario propio (xG caído) ni hay cuotas
    guardadas: la previa sale igual, solo sin el ajuste por rival.
    """
    if not jornada:
        return {}
    path = cache_root() / "laliga_2026_27.txt"
    if not path.is_file():
        return {}
    from toolbox.understat import parse_openfootball_matchdays

    out: dict[str, dict[str, Any]] = {}
    for (home_key, away_key), number in parse_openfootball_matchdays(path.read_text(encoding="utf-8")).items():
        if str(number) != jornada:
            continue
        key = f"{home_key}|{away_key}"
        out[key] = {
            "match_key": key,
            "home_key": home_key,
            "away_key": away_key,
            "home": clubs.get(home_key, home_key.title()),
            "away": clubs.get(away_key, away_key.title()),
            "kickoff": None,
            "lambda_home": None,
            "lambda_away": None,
            "p_cs_home": None,
            "p_cs_away": None,
            "market": None,
            "source": "calendario",
        }
    return out


def _pick(player: dict[str, Any], score: float, mean: float, avail: float, avail_src: str) -> dict[str, Any]:
    return {
        "player_id": player.get("player_id"),
        "name": player.get("nickname") or player.get("name"),
        "club": player.get("club"),
        "position": player.get("_pos"),
        "score": round(score, 2),
        "mean": round(mean, 2),
        "availability": round(avail, 2),
        "availability_source": avail_src,
        "owner": player.get("_owner"),
        "mine": bool(player.get("_mine")),
        "on_market": bool(player.get("_on_market")),
        "price": player.get("_sale_price") or player.get("market_value"),
    }


def build_previa(board: dict[str, Any], *, conn: sqlite3.Connection | None = None, now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    universe = _universe(board)
    club_rounds: dict[str, set[int]] = {}
    for player in universe:
        club_rounds.setdefault(player["_club_key"], set()).update(_rounds(player))
    # Próxima jornada de cada club = su última jugada + 1; la de la previa, la más repetida.
    upcoming = [max(r) + 1 for r in club_rounds.values() if r]
    jornada = str(statistics.mode(upcoming)) if upcoming else None
    fixtures = _fixtures(board, conn, moment)
    if not fixtures:
        fixtures = _calendar_fixtures(jornada, {p["_club_key"]: p["club"] for p in universe})
    by_club: dict[str, list[dict[str, Any]]] = {}
    for player in universe:
        player["_pos"] = _POS.get(str(player.get("position") or "").upper(), "MED")
        by_club.setdefault(player["_club_key"], []).append(player)

    matches: list[dict[str, Any]] = []
    for key, fx in fixtures.items():
        scored: list[tuple[dict[str, Any], float, float, float, str]] = []
        for side_key, lam_for, lam_against in (
            (fx["home_key"], fx["lambda_home"], fx["lambda_away"]),
            (fx["away_key"], fx["lambda_away"], fx["lambda_home"]),
        ):
            rounds = sorted(club_rounds.get(side_key, set()))
            for player in by_club.get(side_key, []):
                mean, apps = _season_mean(player)
                if mean is None or apps < 2:
                    continue
                avail, src = _availability(player, rounds)
                score = mean * avail * _fixture_factor(player["_pos"], lam_for, lam_against)
                scored.append((player, score, mean, avail, src))
        if not scored:
            continue
        ranked = sorted(scored, key=lambda item: -item[1])
        obvious = sorted(scored, key=lambda item: -item[2])[:OBVIOUS_PER_MATCH]
        obvious_ids = {item[0].get("player_id") for item in obvious}
        top = [item for item in ranked if item[3] > 0][:PICKS]
        top_ids = {item[0].get("player_id") for item in top}
        # Apuesta: fuera de los 6 obvios, con opciones reales de jugar y puntuar.
        apuesta = [
            item for item in ranked
            if item[0].get("player_id") not in obvious_ids | top_ids and item[3] >= 0.4 and item[1] >= 1.5
        ][:PICKS]
        # No recomendable: de los obvios que sí juegan, los peor valorados; las bajas van aparte.
        no = sorted(
            [item for item in obvious if item[0].get("player_id") not in top_ids and item[3] > 0],
            key=lambda item: item[1],
        )[:PICKS]
        naive = sorted(scored, key=lambda item: -item[2])[:PICKS]
        as_pick = lambda item: _pick(item[0], item[1], item[2], item[3], item[4])  # noqa: E731
        matches.append(
            {
                **fx,
                "top": [as_pick(i) for i in top],
                "apuesta": [as_pick(i) for i in apuesta],
                "no_recomendable": [as_pick(i) for i in no],
                "bajas": [as_pick(i) for i in obvious if i[3] == 0],
                "naive_top": [as_pick(i) for i in naive],
                "mine": [as_pick(i) for i in ranked if i[0].get("_mine")],
                "market_buys": [as_pick(i) for i in ranked if i[0].get("_on_market") and i[3] > 0][:3],
                "players_scored": len(scored),
            }
        )
    matches.sort(key=lambda m: m.get("kickoff") or "9999")
    return {
        "jornada": jornada,
        "edition": edition_for(moment),
        "generated_at": moment.isoformat(),
        "dashboard_at": board.get("dashboard_at"),
        "rule": "media × disponibilidad × rival (backtest J3–J11: TOP 6,65 frente a 5,81 de la regla simple)",
        "matches": matches,
        "universe": len(universe),
    }


# --- Congelar y evaluar ---------------------------------------------------------


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists previa_snapshots (
            jornada text not null,
            edition text not null,
            generated_at text not null,
            payload text not null,
            stored_at real not null,
            primary key (jornada, edition)
        )
        """
    )
    conn.commit()


def freeze(conn: sqlite3.Connection, previa: dict[str, Any]) -> bool:
    """Guarda la edición si aún no existe. Una edición guardada no se reescribe."""
    if not previa.get("jornada") or not previa.get("matches"):
        return False
    ensure_schema(conn)
    before = conn.total_changes
    conn.execute(
        "insert or ignore into previa_snapshots values (?, ?, ?, ?, ?)",
        (previa["jornada"], previa["edition"], previa["generated_at"], json.dumps(previa, ensure_ascii=False), time.time()),
    )
    conn.commit()
    return conn.total_changes > before


def frozen_editions(conn: sqlite3.Connection, jornada: str | None = None) -> list[dict[str, Any]]:
    ensure_schema(conn)
    query = "select payload from previa_snapshots"
    params: tuple[Any, ...] = ()
    if jornada:
        query += " where jornada = ?"
        params = (jornada,)
    query += " order by cast(jornada as integer), edition desc"
    return [json.loads(row[0]) for row in conn.execute(query, params)]


def _actual_points(board: dict[str, Any]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for player in _universe(board):
        rounds = _rounds(player)
        if rounds:
            out[str(player.get("player_id"))] = rounds
    return out


def evaluate(conn: sqlite3.Connection, board: dict[str, Any]) -> list[dict[str, Any]]:
    """Puntos reales de cada edición congelada cuya jornada ya se jugó."""
    actual = _actual_points(board)
    played_rounds = {r for rounds in actual.values() for r in rounds}
    rows: list[dict[str, Any]] = []
    for previa in frozen_editions(conn):
        try:
            jornada = int(previa["jornada"])
        except (TypeError, ValueError):
            continue
        if jornada not in played_rounds:
            continue
        summary: dict[str, Any] = {"jornada": str(jornada), "edition": previa.get("edition")}
        # Solo partidos ya jugados: con un partido de la jornada en el viernes,
        # el resto contaba 0 puntos y la evaluación salía «0.0» en todo.
        cats = ("top", "apuesta", "no_recomendable", "naive_top")
        # LALIGA publica la jornada en curso con 0 a todos antes de jugarse:
        # un partido cuenta como jugado si algún elegido ya tiene puntos
        # distintos de 0 (que todos los elegidos de un partido jugado saquen
        # exactamente 0 no pasa en la práctica).
        played = [
            match for match in previa.get("matches") or []
            if any(
                (actual.get(str(pick.get("player_id"))) or {}).get(jornada)
                for cat in cats for pick in match.get(cat) or []
            )
        ]
        if not played:
            continue
        summary["matches_played"] = len(played)
        summary["matches_total"] = len(previa.get("matches") or [])
        for cat in cats:
            values: list[float] = []
            missing = 0
            for match in played:
                for pick in match.get(cat) or []:
                    rounds = actual.get(str(pick.get("player_id")))
                    if rounds is None:
                        missing += 1
                        continue
                    values.append(rounds.get(jornada, 0.0))
            summary[cat] = {
                "n": len(values),
                "missing": missing,
                "mean": round(statistics.mean(values), 2) if values else None,
            }
        rows.append(summary)
    return rows


def previa_report(board: dict[str, Any], *, db_path: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Edición en vivo, ediciones congeladas de la jornada y evaluación de las pasadas."""
    path = db_path or _db_path()
    moment = now or datetime.now(timezone.utc)
    conn = sqlite3.connect(path)
    try:
        live = build_previa(board, conn=conn, now=moment)
        photo = None
        if isinstance(board.get("dashboard_at"), str):
            try:
                photo = datetime.fromisoformat(board["dashboard_at"].replace("Z", "+00:00"))
            except ValueError:
                photo = None
            if photo is not None and photo.tzinfo is None:
                photo = photo.replace(tzinfo=timezone.utc)
        # Solo se congela con una foto fresca de la misma edición: una foto del
        # domingo no puede quedar guardada como la previa del martes.
        fresh = (
            photo is not None
            and (moment - photo).total_seconds() < 24 * 3600
            and edition_for(photo) == live["edition"]
        )
        live["frozen_eligible"] = fresh
        stored = freeze(conn, live) if fresh else False
        editions = frozen_editions(conn, live.get("jornada")) if live.get("jornada") else []
        evaluation = evaluate(conn, board)
    finally:
        conn.close()
    if stored:
        from toolbox.history_remote import push as push_history

        push_history()
    return {"live": live, "frozen_now": stored, "editions": editions, "evaluation": evaluation}


def render_text(report: dict[str, Any]) -> str:
    """Resumen corto para el informe copiable del Laboratorio."""
    lines = ["## Previa (en pruebas)"]
    live = report.get("live") or {}
    lines.append(f"J{live.get('jornada') or '?'} · edición {live.get('edition')} · {len(live.get('matches') or [])} partidos · regla: {live.get('rule')}")
    for match in live.get("matches") or []:
        names = lambda key: ", ".join(p["name"] for p in match.get(key) or []) or "—"  # noqa: E731
        lines.append(f"- {match['home']} - {match['away']}: TOP {names('top')} · Apuesta {names('apuesta')} · No {names('no_recomendable')}")
    for row in report.get("evaluation") or []:
        parts = [f"{cat} {row[cat]['mean']}" for cat in ("top", "apuesta", "no_recomendable", "naive_top") if row.get(cat, {}).get("mean") is not None]
        partial = "" if row.get("matches_played") == row.get("matches_total") else f" · {row.get('matches_played')} de {row.get('matches_total')} partidos jugados"
        lines.append(f"Evaluación J{row['jornada']} ({row['edition']}){partial}: " + " · ".join(parts))
    return "\n".join(lines)

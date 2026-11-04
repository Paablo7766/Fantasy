"""Respaldo de Understat: FotMob (jugadores y calendario) + football-data (xG por partido).

Understat es la única fuente de xG por jugador y por partido del modelo. Si
cae (mantenimiento, cambio de API), ``own_goal_probability`` sale a 0 para
toda la liga y el calendario se queda sin λ. Aquí se monta el mismo payload que
devuelve Understat con dos fuentes públicas y sin clave:

* FotMob: xG, xA y ocasiones creadas por jugador de la temporada, y el
  calendario completo con jornada y hora.
* football-data.co.uk: xG de cada partido jugado (columnas ``HxG``/``AxG``).

Escala: el 2026-11-04, con 89 jugadores en ambas fuentes, el xG/90 de FotMob
correlaba 0,97 con el de Understat pero era un 14 % menor (xA: 0,82 y el mismo
14 %). football-data cuadra con FotMob (0,98). El modelo está calibrado con
Understat, así que todo se multiplica por ``FOTMOB_TO_UNDERSTAT``.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from toolbox.understat import (
    load_understat,
    next_fixtures,
    parse_understat_payload,
    team_rolling_windows_from_payload,
)

FOTMOB_LEAGUE_ID = 87  # LaLiga
FOTMOB_LEAGUE_URL = f"https://www.fotmob.com/api/data/leagues?id={FOTMOB_LEAGUE_ID}"
FOTMOB_STAT_URL = "https://data.fotmob.com/stats/{league}/season/{season}/{stat}.json"
FOOTBALL_DATA_URL = "https://football-data.co.uk/mmz4281/{code}/SP1.csv"
FOTMOB_TO_UNDERSTAT = round(1 / 0.861, 4)
_STATS = ("expected_goals", "expected_assists", "total_att_assist")
_SEASON_IN_URL = re.compile(r"/season/(\d+)/")

# football-data abrevia; se usan los nombres de FotMob para que el calendario
# y las fuerzas compartan clave al normalizar.
FOOTBALL_DATA_TITLES = {
    "Alaves": "Deportivo Alavés",
    "Ath Bilbao": "Athletic Club",
    "Ath Madrid": "Atlético Madrid",
    "Betis": "Real Betis",
    "Celta": "Celta Vigo",
    "Espanol": "Espanyol",
    "La Coruna": "Deportivo A Coruña",
    "Malaga": "Málaga",
    "Santander": "Racing Santander",
    "Sociedad": "Real Sociedad",
    "Vallecano": "Rayo Vallecano",
}


def football_data_code(now: datetime | None = None) -> str:
    """Temporada en formato football-data: 2026/27 → «2627». Empieza en julio."""
    moment = now or datetime.now()
    start = moment.year if moment.month >= 7 else moment.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def fotmob_season_id(league: Any) -> str | None:
    stats = league.get("stats") if isinstance(league, dict) else None
    for row in (stats or {}).get("players") or []:
        url = row.get("fetchAllUrl") if isinstance(row, dict) else None
        match = _SEASON_IN_URL.search(url) if isinstance(url, str) else None
        if match:
            return match.group(1)
    return None


def _stat_rows(payload: Any) -> list[dict[str, Any]]:
    lists = payload.get("TopLists") if isinstance(payload, dict) else None
    if not isinstance(lists, list) or not lists or not isinstance(lists[0], dict):
        return []
    rows = lists[0].get("StatList")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fotmob_players(stats: dict[str, Any]) -> list[dict[str, Any]]:
    """Filas con el formato de ``players`` de Understat, ya en escala Understat."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for stat in _STATS:
        for row in _stat_rows(stats.get(stat)):
            name, team = row.get("ParticipantName"), row.get("TeamName")
            if not isinstance(name, str) or not isinstance(team, str):
                continue
            player = merged.setdefault(
                (name, team),
                {
                    "player_name": name,
                    "team_title": team,
                    "position": "",
                    "id": row.get("ParticiantId") or row.get("ParticipantId"),
                    "xG": 0.0,
                    "xA": 0.0,
                    "key_passes": None,
                },
            )
            minutes, games = _number(row.get("MinutesPlayed")), _number(row.get("MatchesPlayed"))
            if minutes is not None:
                player["time"] = max(minutes, _number(player.get("time")) or 0.0)
            if games is not None:
                player["games"] = max(games, _number(player.get("games")) or 0.0)
            value = _number(row.get("StatValue"))
            if value is None:
                continue
            if stat == "expected_goals":
                player["xG"] = round(value * FOTMOB_TO_UNDERSTAT, 4)
            elif stat == "expected_assists":
                player["xA"] = round(value * FOTMOB_TO_UNDERSTAT, 4)
            else:
                player["key_passes"] = value
    return [row for row in merged.values() if row.get("time")]


def football_data_matches(text: str) -> list[dict[str, Any]]:
    """Partidos jugados con xG, en orden de fecha."""
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for row in reader:
        home, away = row.get("HomeTeam"), row.get("AwayTeam")
        hxg, axg = _number(row.get("HxG")), _number(row.get("AxG"))
        date = row.get("Date") or ""
        if not home or not away or hxg is None or axg is None:
            continue
        try:
            when = datetime.strptime(f"{date} {row.get('Time') or '00:00'}", "%d/%m/%Y %H:%M")
        except ValueError:
            continue
        rows.append(
            {
                "home": FOOTBALL_DATA_TITLES.get(home, home),
                "away": FOOTBALL_DATA_TITLES.get(away, away),
                "xg_home": round(hxg * FOTMOB_TO_UNDERSTAT, 4),
                "xg_away": round(axg * FOTMOB_TO_UNDERSTAT, 4),
                "datetime": when.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    rows.sort(key=lambda item: item["datetime"])
    return rows


def build_backup_payload(league: Any, stats: dict[str, Any], csv_text: str) -> dict[str, Any]:
    """Payload con la forma de ``getLeagueData`` de Understat."""
    played = football_data_matches(csv_text)
    teams: dict[str, dict[str, Any]] = {}
    for match in played:
        for title, xg, xga in (
            (match["home"], match["xg_home"], match["xg_away"]),
            (match["away"], match["xg_away"], match["xg_home"]),
        ):
            team = teams.setdefault(title, {"id": title, "title": title, "history": []})
            team["history"].append({"xG": xg, "xGA": xga, "date": match["datetime"]})
    dates: list[dict[str, Any]] = [
        {
            "isResult": True,
            "h": {"title": match["home"]},
            "a": {"title": match["away"]},
            "xG": {"h": match["xg_home"], "a": match["xg_away"]},
            "datetime": match["datetime"],
        }
        for match in played
    ]
    fixtures = league.get("fixtures") if isinstance(league, dict) else None
    for match in (fixtures or {}).get("allMatches") or []:
        if not isinstance(match, dict):
            continue
        status = match.get("status") if isinstance(match.get("status"), dict) else {}
        if status.get("finished") or status.get("cancelled") or status.get("started"):
            continue
        home = (match.get("home") or {}).get("name")
        away = (match.get("away") or {}).get("name")
        kickoff = status.get("utcTime")
        if isinstance(home, str) and isinstance(away, str) and isinstance(kickoff, str):
            dates.append({"isResult": False, "h": {"title": home}, "a": {"title": away}, "datetime": kickoff, "round": match.get("round")})
    return {"players": fotmob_players(stats), "teams": teams, "dates": dates}


def load_stats_backup(client: Any, *, ttl: float, fresh: bool, now: datetime | None = None):
    """Mismo resultado que ``load_understat`` a partir de FotMob + football-data."""
    sources: list[str] = []
    league, _cached = client.get_json(FOTMOB_LEAGUE_URL, ttl=ttl, fresh=fresh)
    season = fotmob_season_id(league)
    stats: dict[str, Any] = {}
    if season:
        for stat in _STATS:
            try:
                stats[stat], _ = client.get_json(
                    FOTMOB_STAT_URL.format(league=FOTMOB_LEAGUE_ID, season=season, stat=stat), ttl=ttl, fresh=fresh
                )
            except Exception:  # noqa: BLE001 — una lista que falle no tumba las demás
                continue
        sources.append("fotmob")
    csv_text = ""
    try:
        csv_text, _ = client.get_text(FOOTBALL_DATA_URL.format(code=football_data_code(now)), ttl=ttl, fresh=fresh)
        sources.append("football-data")
    except Exception:  # noqa: BLE001 — sin xG por partido quedan los jugadores y el calendario
        csv_text = ""
    payload = build_backup_payload(league, stats, csv_text)
    players, strengths, dates = parse_understat_payload(payload)
    for player in players:
        player["source"] = "fotmob"
    fixtures = next_fixtures(dates, strengths, now=now)
    rolling = team_rolling_windows_from_payload(payload)
    return players, fixtures, strengths, rolling, {
        "count": len(players),
        "fixtures": len(fixtures),
        "teams": len({id(v): v for v in strengths.values()}),
        "rolling_teams": len({id(v): v for v in rolling.values()}),
        "source": "+".join(sources),
    }


def load_understat_with_fallback(client: Any, *, ttl: float, fresh: bool, season: str | None = None):
    """Understat; si no da jugadores, FotMob + football-data con el aviso en el estado."""
    players, fixtures, strengths, rolling, status = load_understat(client, ttl=ttl, fresh=fresh, season=season)
    if players and fixtures:
        return players, fixtures, strengths, rolling, {**status, "source": "understat"}
    reason = status.get("error") or "Understat sin datos"
    try:
        b_players, b_fixtures, b_strengths, b_rolling, b_status = load_stats_backup(client, ttl=ttl, fresh=fresh)
    except Exception as exc:  # noqa: BLE001 — sin respaldo se devuelve lo de Understat tal cual
        return players, fixtures, strengths, rolling, {**status, "error": f"{reason}; respaldo falló: {exc}"}
    if not b_players:
        return players, fixtures, strengths, rolling, {**status, "error": f"{reason}; respaldo sin jugadores"}
    return b_players, b_fixtures or fixtures, b_strengths or strengths, b_rolling or rolling, {
        "ok": True,
        "from_cache": False,
        "url": FOTMOB_LEAGUE_URL,
        **b_status,
        "error": f"Understat caído ({reason}): xG de {b_status['source']} (escala ×{FOTMOB_TO_UNDERSTAT})",
    }


__all__ = [
    "FOTMOB_TO_UNDERSTAT",
    "build_backup_payload",
    "football_data_code",
    "football_data_matches",
    "fotmob_players",
    "fotmob_season_id",
    "load_stats_backup",
    "load_understat_with_fallback",
]

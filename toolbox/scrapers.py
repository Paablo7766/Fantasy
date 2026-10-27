"""Ingesta de Fútbol Fantasy, Sofascore, FBref, Understat, Jornada Perfecta y Transfermarkt.

Las páginas y los JSON pasan por ``ExternalClient``: caché en Supabase y, en
Transfermarkt, el tope de 2 peticiones cada 3 segundos. Un fallo de una fuente
no tira el cruce; queda anotado en ``sources`` y el documento sale parcial.

El bonus Relevo de 0 a 4 no se calcula aquí. Solo se guardan las métricas
(xG, xA, minutos, pases clave, duelos, despejes, paradas, nota, tip JP y FDR)
que alimentan la proyección.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
import urllib.parse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from toolbox.cache import EntityStore, madrid_day
from toolbox.matching import (
    MATCH_THRESHOLD,
    CanonicalPlayer,
    EntityResolver,
    ExternalRecord,
    MatchDecision,
    canonical_position,
    normalize_club,
    normalize_name,
)
from toolbox.net import ExternalClient, ExternalHttpError, FantasyHttpError, inherited, transfermarkt_api_base
from toolbox.analyzer import official_price_delta, starter_fallback
from toolbox.normalize import SCHEMA_VERSION, attach_image_urls

logger = logging.getLogger("fantasy.scrapers")

FF_MARKET_URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"
FF_FITNESS_URL = "https://www.futbolfantasy.com/laliga/lesionados"
FF_SANCTIONS_URL = "https://www.futbolfantasy.com/laliga/sancionados"
FF_WARNINGS_URL = "https://www.futbolfantasy.com/laliga/apercibidos"
FBREF_URLS = (
    "https://fbref.com/en/comps/12/shooting/La-Liga-Stats",
    "https://fbref.com/en/comps/12/passing/La-Liga-Stats",
    "https://fbref.com/en/comps/12/defense/La-Liga-Stats",
    "https://fbref.com/en/comps/12/keepers/La-Liga-Stats",
    "https://fbref.com/en/comps/12/playingtime/La-Liga-Stats",
)
# LaLiga (unique-tournament 8). Se puede sustituir con SOFASCORE_STATS_URL.
SOFASCORE_DEFAULT_SEASON = "77559"
SOFASCORE_DEFAULT_URL = (
    f"https://api.sofascore.com/api/v1/unique-tournament/8/season/{SOFASCORE_DEFAULT_SEASON}/top-players/overall"
)
# Solo estas fuentes marcan ``partial`` en trends; el núcleo (FF, AF, Understat, own) sigue siendo decisorio.
_OPTIONAL_TRENDS_SOURCES = frozenset({"fbref", "sofascore", "transfermarkt", "laliga_odds"})

RANK_LIMIT = 15
FORM_NOTE = (
    "Las métricas de forma alimentan el bonus Relevo de 0 a 4 y la proyección OPTA. "
    "Understat manda en xG/xA; minutos y FDR ajustan expected_points. "
    "Este documento no asigna el bonus Relevo."
)
_FORM_KEYS = (
    "xg",
    "xa",
    "key_passes",
    "duels_won",
    "clearances",
    "saves",
    "average_rating",
    "minutes",
    "starts",
    "minutes_pct",
    "jp_tip",
    "jp_projected_points",
    "jp_multiplier",
    "jp_racha",
)
_TEAM_LINK = re.compile(r'href="[^"]*/laliga/equipos/[a-z0-9-]+"[^>]*>([^<]+)</a>', re.IGNORECASE)
_FBREF_STATS = {
    "xg": "xg",
    "xg_assist": "xa",
    "xa": "xa",
    "assisted_shots": "key_passes",
    "key_passes": "key_passes",
    "challenges_won": "duels_won",
    "tackles_won": "duels_won",
    "aerials_won": "duels_won",
    "clearances": "clearances",
    "saves": "saves",
    "gk_saves": "saves",
    "minutes": "minutes",
    "games_starts": "starts",
    "minutes_pct": "minutes_pct",
}


class LeagueCatalog(Protocol):
    def market_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]: ...

    def squads_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ScrapeTTL:
    market: float = 30 * 60
    fitness: float = 30 * 60
    sanctions: float = 6 * 60 * 60
    stats: float = 6 * 60 * 60
    odds: float = 6 * 60 * 60
    transfermarkt: float = 24 * 60 * 60

    @classmethod
    def from_env(cls) -> ScrapeTTL:
        return cls(
            market=_env_float("FANTASY_TTL_FUTBOLFANTASY_MARKET", 30 * 60),
            fitness=_env_float("FANTASY_TTL_FITNESS", 30 * 60),
            sanctions=_env_float("FANTASY_TTL_SANCTIONS", 6 * 60 * 60),
            stats=_env_float("FANTASY_TTL_STATS", 6 * 60 * 60),
            odds=_env_float("FANTASY_TTL_ODDS", 6 * 60 * 60),
            transfermarkt=_env_float("FANTASY_TTL_TRANSFERMARKT", 24 * 60 * 60),
        )


THE_ODDS_API_URL = (
    "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds"
    "?regions=eu&markets=h2h,totals,btts&oddsFormat=decimal"
)
LALIGA_ODDS_SIM_CACHE_KEY = "laliga_odds_sim:v1"


@dataclass(frozen=True)
class MatchOddsBundle:
    match_key: str
    odds_1x2: tuple[float, float, float]
    odds_ou25: tuple[float, float] | None = None
    odds_btts: tuple[float, float] | None = None
    source: str = "simulated"

    def as_dict(self) -> dict[str, Any]:
        return {
            "match_key": self.match_key,
            "odds_1x2": self.odds_1x2,
            "odds_ou25": self.odds_ou25,
            "odds_btts": self.odds_btts,
            "source": self.source,
        }


def match_odds_key(home_club: str, away_club: str) -> str:
    return f"{normalize_club(home_club)}|{normalize_club(away_club)}"


def _fixture_home_away_keys(club_key: str, fixture: Any) -> tuple[str, str]:
    opponent_key = normalize_club(str(getattr(fixture, "opponent", "") or ""))
    if getattr(fixture, "home", False):
        return club_key, opponent_key
    return opponent_key, club_key


def _decimal_odds_from_probs(probs: tuple[float, float, float], *, margin: float = 1.06) -> tuple[float, float, float]:
    ph, pd, pa = probs
    ph = max(ph, 1e-4)
    pd = max(pd, 1e-4)
    pa = max(pa, 1e-4)
    return (round(margin / ph, 3), round(margin / pd, 3), round(margin / pa, 3))


def _simulate_totals_btts(lh: float, la: float) -> tuple[tuple[float, float], tuple[float, float]]:
    from toolbox.understat import _dixon_coles_grid

    grid = _dixon_coles_grid(lh, la, -0.08, max_goals=10)
    import numpy as np

    idx = np.add.outer(np.arange(grid.shape[0]), np.arange(grid.shape[1]))
    over25 = float(np.sum(grid[idx >= 3]))
    under25 = max(1e-4, 1.0 - over25)
    btts = float(np.sum(grid[1:, 1:]))
    not_btts = max(1e-4, 1.0 - btts)
    margin = 1.05
    return (
        (round(margin / max(over25, 1e-4), 3), round(margin / under25, 3)),
        (round(margin / max(btts, 1e-4), 3), round(margin / not_btts, 3)),
    )


def build_simulated_match_odds_index(
    fixtures_by_club: dict[str, Any],
    *,
    strengths: dict[str, Any],
    team_rolling: dict[str, Any],
    league_avg_xg: float = 1.32,
) -> dict[str, dict[str, Any]]:
    """Cuotas sintéticas a partir de rolling xG cuando no hay API key."""
    from toolbox.understat import (
        TeamStrength,
        build_hybrid_match_projection,
        resolve_rolling_window,
        stat_lambdas_for_fixture,
    )

    unique_matches: dict[str, tuple[str, str]] = {}
    for club_key, fixture in fixtures_by_club.items():
        home_key, away_key = _fixture_home_away_keys(club_key, fixture)
        if not home_key or not away_key:
            continue
        unique_matches[match_odds_key(home_key, away_key)] = (home_key, away_key)

    index: dict[str, dict[str, Any]] = {}
    strength_map = strengths if isinstance(strengths, dict) else {}

    def _team(key: str) -> TeamStrength | None:
        raw = strength_map.get(key)
        return raw if isinstance(raw, TeamStrength) else None

    for key, (home_key, away_key) in unique_matches.items():
        home_team = _team(home_key) or _team(normalize_name(home_key))
        away_team = _team(away_key) or _team(normalize_name(away_key))
        home_roll = resolve_rolling_window(home_team, team_rolling, home_key)
        away_roll = resolve_rolling_window(away_team, team_rolling, away_key)
        lh, la = stat_lambdas_for_fixture(
            home_team=home_team,
            away_team=away_team,
            home_rolling=home_roll,
            away_rolling=away_roll,
            league_avg_xg=league_avg_xg,
        )
        stat_proj = build_hybrid_match_projection(lh, la, odds_1x2=None)
        odds_1x2 = _decimal_odds_from_probs(
            (stat_proj.p_home_win, stat_proj.p_draw, stat_proj.p_away_win),
        )
        odds_ou25, odds_btts = _simulate_totals_btts(lh, la)
        bundle = MatchOddsBundle(
            match_key=key,
            odds_1x2=odds_1x2,
            odds_ou25=odds_ou25,
            odds_btts=odds_btts,
            source="simulated",
        )
        index[key] = bundle.as_dict()
    return index


def parse_the_odds_api_payload(payload: Any) -> dict[str, dict[str, Any]]:
    """Normaliza eventos The Odds API → índice ``home|away``."""
    if not isinstance(payload, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for event in payload:
        if not isinstance(event, dict):
            continue
        home_name = event.get("home_team")
        away_name = event.get("away_team")
        if not isinstance(home_name, str) or not isinstance(away_name, str):
            continue
        key = match_odds_key(home_name, away_name)
        bookmakers = event.get("bookmakers") if isinstance(event.get("bookmakers"), list) else []
        if not bookmakers:
            continue
        book = bookmakers[0] if isinstance(bookmakers[0], dict) else {}
        markets = book.get("markets") if isinstance(book.get("markets"), list) else []
        h2h: dict[str, float] = {}
        over: float | None = None
        under: float | None = None
        btts_yes: float | None = None
        btts_no: float | None = None
        for market in markets:
            if not isinstance(market, dict):
                continue
            mkey = market.get("key")
            outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), list) else []
            if mkey == "h2h":
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    name = outcome.get("name")
                    price = outcome.get("price")
                    if isinstance(name, str) and isinstance(price, (int, float)) and float(price) > 1.0:
                        h2h[name] = float(price)
            elif mkey == "totals":
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    point = outcome.get("point")
                    if point is not None and float(point) != 2.5:
                        continue
                    name = str(outcome.get("name") or "").lower()
                    price = outcome.get("price")
                    if not isinstance(price, (int, float)) or float(price) <= 1.0:
                        continue
                    if name == "over":
                        over = float(price)
                    elif name == "under":
                        under = float(price)
            elif mkey == "btts":
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    name = str(outcome.get("name") or "").lower()
                    price = outcome.get("price")
                    if not isinstance(price, (int, float)) or float(price) <= 1.0:
                        continue
                    if name in {"yes", "si", "sí"}:
                        btts_yes = float(price)
                    elif name == "no":
                        btts_no = float(price)
        home_odds = h2h.get(home_name)
        away_odds = h2h.get(away_name)
        draw_odds = None
        for name, price in h2h.items():
            if name not in {home_name, away_name}:
                draw_odds = price
                break
        if home_odds is None or away_odds is None or draw_odds is None:
            continue
        bundle = MatchOddsBundle(
            match_key=key,
            odds_1x2=(home_odds, draw_odds, away_odds),
            odds_ou25=(over, under) if over is not None and under is not None else None,
            odds_btts=(btts_yes, btts_no) if btts_yes is not None and btts_no is not None else None,
            source="the_odds_api",
        )
        index[key] = bundle.as_dict()
    return index


def load_laliga_match_odds(
    client: ExternalClient,
    *,
    fixtures_by_club: dict[str, Any],
    strengths: dict[str, Any],
    team_rolling: dict[str, Any],
    ttl: float,
    fresh: bool,
    league_avg_xg: float = 1.32,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Ingesta cuotas LaLiga (API o simulación) con caché de 6 h por defecto."""
    api_key = os.getenv("THE_ODDS_API_KEY", "").strip()
    if api_key:
        url = f"{THE_ODDS_API_URL}&apiKey={urllib.parse.quote(api_key)}"
        try:
            payload, cached = client.get_json(url, ttl=ttl, fresh=fresh)
            index = parse_the_odds_api_payload(payload)
            if index:
                return index, {
                    "ok": True,
                    "count": len(index),
                    "error": None,
                    "from_cache": cached,
                    "source": "the_odds_api",
                }
        except ExternalHttpError as exc:
            api_error = str(exc)
        else:
            api_error = "the_odds_api_sin_eventos"
    else:
        api_error = "sin_api_key"

    if not fresh and ttl > 0:
        cached_sim = client._cache.get_json(LALIGA_ODDS_SIM_CACHE_KEY)
        if isinstance(cached_sim, dict) and cached_sim.get("matches"):
            return cached_sim["matches"], {
                "ok": True,
                "count": len(cached_sim["matches"]),
                "error": None if not api_error else api_error,
                "from_cache": True,
                "source": "simulated",
            }

    index = build_simulated_match_odds_index(
        fixtures_by_club,
        strengths=strengths,
        team_rolling=team_rolling,
        league_avg_xg=league_avg_xg,
    )
    if ttl > 0 and index:
        client._cache.put_json(
            LALIGA_ODDS_SIM_CACHE_KEY,
            {"matches": index, "generated_at": datetime.now(timezone.utc).isoformat()},
            ttl,
        )
    return index, {
        "ok": bool(index),
        "count": len(index),
        "error": None if index else api_error,
        "from_cache": False,
        "source": "simulated",
    }


@dataclass
class IntelPlayer:
    name: str
    club: str | None = None
    position: str | None = None
    external_id: str | None = None
    p_titular: float | None = None
    price_delta: int | None = None
    # Acumulados de la misma fuente (FútbolFantasy): ``diferencia2`` y
    # ``diferencia3`` son la subida de 2 y 3 días. La app oficial muestra a veces
    # el tramo de 2 días, así que sin estos campos una subida real de 519.675 €
    # parecía un error cuando el panel enseñaba 257.864 €.
    price_delta_2: int | None = None
    price_delta_3: int | None = None
    acceleration: int | None = None
    fitness: str | None = None
    fitness_detail: str | None = None
    yellow_cards: int | None = None
    on_verge: bool = False
    suspended: bool = False
    lineup_status: str | None = None
    lineup_source: str | None = None


@dataclass
class FormLine:
    name: str
    source: str
    club: str | None = None
    position: str | None = None
    external_id: str | None = None
    xg: float | None = None
    xa: float | None = None
    key_passes: float | None = None
    duels_won: float | None = None
    clearances: float | None = None
    saves: float | None = None
    average_rating: float | None = None
    minutes: float | None = None
    starts: float | None = None
    minutes_pct: float | None = None
    jp_tip: str | None = None
    jp_projected_points: float | None = None
    jp_multiplier: float | None = None
    jp_racha: float | None = None


@dataclass
class RealValue:
    record: ExternalRecord
    value_eur: int | None


@dataclass
class _SourceFetch:
    ok: bool
    count: int = 0
    error: str | None = None
    from_cache: bool = False
    rows: list[Any] = field(default_factory=list)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _status(fetch: _SourceFetch) -> dict[str, Any]:
    return {
        "ok": fetch.ok,
        "count": fetch.count,
        "error": fetch.error,
        "from_cache": fetch.from_cache,
    }


def _blank_form() -> dict[str, Any]:
    payload: dict[str, Any] = {key: None for key in _FORM_KEYS}
    payload["source"] = None
    return payload


def _percent_token(raw: str) -> float | None:
    value = float(raw.replace(",", "."))
    if value > 1:
        value /= 100.0
    if value < 0 or value > 1:
        return None
    return round(value, 4)


def _percent(text: str | None) -> float | None:
    """Titularidad en FútbolFantasy: no confundir con columnas de variación de precio."""
    if not text:
        return None
    widget = re.search(
        r'class="probabilidad-widget"[^>]*>.*?(\d+(?:[.,]\d+)?)\s*%',
        text,
        flags=re.S | re.I,
    )
    if widget is not None:
        return _percent_token(widget.group(1))
    profile = re.search(
        r'porcentaje-perfil"[^>]*>.*?(\d+(?:[.,]\d+)?)\s*%',
        text,
        flags=re.S | re.I,
    )
    if profile is not None:
        return _percent_token(profile.group(1))
    attr = re.search(r'data-probabilidad="(\d+(?:[.,]\d+)?)\s*%"', text, flags=re.I)
    if attr is not None:
        return _percent_token(attr.group(1))
    for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", text):
        window = text[max(0, match.start() - 140) : match.start()]
        if any(
            marker in window
            for marker in ("columna_diferencia", "analytics-down", "analytics-up")
        ):
            continue
        parsed = _percent_token(match.group(1))
        if parsed is not None:
            return parsed
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:
            return None
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", ".")
        if not text or text in {"-", "—"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if number != number:
        return None
    return number


def parse_money(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        return parse_money(value.get("value", value.get("marketValue")))
    if isinstance(value, int):
        return value or None
    if isinstance(value, float):
        return int(value) or None
    text = str(value).strip().lower().replace("€", "").replace(" ", "")
    if re.fullmatch(r"\d+", text):
        number = int(text)
        return number or None
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)([mbk])", text)
    if match is None:
        return None
    amount = float(match.group(1).replace(",", "."))
    factor = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2)]
    parsed = int(amount * factor)
    return parsed or None


def _fitness_status(text: str | None) -> str | None:
    if not text:
        return None
    folded = normalize_name(text)
    if "baja" in folded or "lesion" in folded:
        return "lesionado"
    if "duda" in folded or "molest" in folded:
        return "duda"
    if "disponible" in folded or folded == "alta":
        return "disponible"
    return None


_SPACE = re.compile(r"\s+")


def _data_attrs(opening: str) -> dict[str, str]:
    return {
        key: html.unescape(value)
        for key, value in re.findall(r'data-([a-zA-Z0-9_-]+)="([^"]*)"', opening)
    }


def _chunks(page: str, marker: str) -> list[tuple[int, str]]:
    indexes: list[int] = []
    start = 0
    while True:
        found = page.find(marker, start)
        if found < 0:
            break
        indexes.append(found)
        start = found + len(marker)
    chunks: list[tuple[int, str]] = []
    for position, index in enumerate(indexes):
        tag = page.rfind("<", 0, index)
        if tag < 0:
            continue
        end = page.rfind("<", 0, indexes[position + 1]) if position + 1 < len(indexes) else len(page)
        if end < tag:
            end = len(page)
        chunks.append((tag, page[tag:end]))
    return chunks


def _club_before(page: str, offset: int) -> str | None:
    club = None
    for match in _TEAM_LINK.finditer(page, 0, offset):
        label = html.unescape(match.group(1)).strip()
        if label:
            club = label
    return club


def _visible_name(chunk: str) -> str | None:
    block = re.search(r'class="player-name"(.*?)</a>', chunk, flags=re.S)
    if block:
        spans = [
            html.unescape(item).strip()
            for item in re.findall(r"<span[^>]*>([^<]+)</span>", block.group(1))
        ]
        spans = [item for item in spans if item]
        if spans:
            return max(spans, key=len)
    link = re.search(r'class="jugador"[^>]*>([^<]+)', chunk)
    if link:
        name = html.unescape(link.group(1)).strip()
        return name or None
    return None


def _club_in_row(chunk: str) -> str | None:
    block = re.search(r'class="player-equipo"(.*?)</div>', chunk, flags=re.S)
    if block is None:
        return None
    span = re.search(r"<span>([^<]+)</span>", block.group(1))
    if span is None:
        return None
    name = html.unescape(span.group(1)).strip()
    return name or None


def parse_market_board(page: str) -> list[IntelPlayer]:
    players: list[IntelPlayer] = []
    for _offset, chunk in _chunks(page, "elemento_jugador"):
        opening, _, _rest = chunk.partition(">")
        attrs = _data_attrs(opening)
        name = _visible_name(chunk) or attrs.get("nombre")
        if not name:
            continue
        players.append(
            IntelPlayer(
                name=name,
                club=_club_in_row(chunk),
                position=canonical_position(attrs.get("posicion")),
                external_id=attrs.get("id"),
                p_titular=_percent(chunk),
                price_delta=_as_int(attrs.get("diferencia1")),
                price_delta_2=_as_int(attrs.get("diferencia2")),
                price_delta_3=_as_int(attrs.get("diferencia3")),
                acceleration=_as_int(attrs.get("aceleracion")),
            )
        )
    return players


def _parse_status_cards(page: str, marker: str, *, kind: str) -> list[IntelPlayer]:
    players: list[IntelPlayer] = []
    for offset, chunk in _chunks(page, marker):
        name = _visible_name(chunk)
        if not name:
            continue
        detail_match = re.search(r'<span class="lesion">([^<]*)</span>', chunk)
        status_match = re.search(r'rounded-card__status[^"]*"[^>]*>([^<]+)', chunk)
        detail = html.unescape(detail_match.group(1)).strip() if detail_match else None
        status_text = html.unescape(status_match.group(1)).strip() if status_match else None
        yellows = len(re.findall(r'class="[^"]*\btarjetasA\b', chunk))
        player = IntelPlayer(
            name=name,
            club=_club_before(page, offset),
            external_id=None,
            p_titular=_percent(chunk),
            fitness_detail=detail or None,
        )
        if kind == "fitness":
            player.fitness = _fitness_status(status_text) or _fitness_status(detail)
        elif kind == "suspended":
            player.suspended = True
        elif kind == "warnings":
            player.yellow_cards = yellows
            player.on_verge = yellows >= 4
        players.append(player)
    return players


def parse_fitness_board(page: str) -> list[IntelPlayer]:
    return _parse_status_cards(page, "elemento lesionado", kind="fitness")


def parse_sanction_board(page: str) -> list[IntelPlayer]:
    return _parse_status_cards(page, "elemento sancionado", kind="suspended")


def parse_warning_board(page: str) -> list[IntelPlayer]:
    return _parse_status_cards(page, "elemento sancionado", kind="warnings")


def _cell_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(_SPACE.sub(" ", text)).strip()


def parse_fbref_html(page: str) -> list[FormLine]:
    visible = re.sub(r"<!--(.*?)-->", lambda match: match.group(1), page, flags=re.S)
    merged: dict[str, FormLine] = {}
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", visible, flags=re.S):
        cells = re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', row, flags=re.S)
        if not cells:
            continue
        values = {key: _cell_text(raw) for key, raw in cells}
        name = values.get("player") or ""
        if not name or name.lower() == "player":
            continue
        key = normalize_name(name)
        line = merged.get(key)
        if line is None:
            line = FormLine(
                name=name,
                source="fbref",
                club=values.get("team") or values.get("squad") or None,
                position=canonical_position(values.get("pos")),
            )
            merged[key] = line
        for stat, target in _FBREF_STATS.items():
            if stat not in values:
                continue
            current = getattr(line, target)
            if current is not None and stat in {"tackles_won", "aerials_won"}:
                continue
            number = _as_float(values[stat])
            if number is not None and current is None:
                if target == "minutes_pct" and number > 1:
                    number = round(number / 100.0, 4)
                setattr(line, target, number)
    return list(merged.values())


def form_line_from_mapping(row: dict[str, Any]) -> FormLine | None:
    name = row.get("name")
    source = row.get("source")
    if not isinstance(name, str) or not name.strip() or not isinstance(source, str):
        return None
    line = FormLine(
        name=name.strip(),
        source=source,
        club=row.get("club") if isinstance(row.get("club"), str) else None,
        position=row.get("position") if isinstance(row.get("position"), str) else None,
        external_id=str(row["external_id"]) if row.get("external_id") is not None else None,
    )
    for key in _FORM_KEYS:
        if key not in row:
            continue
        value = row.get(key)
        if key == "jp_tip":
            if isinstance(value, str) and value.strip():
                line.jp_tip = value.strip()
            continue
        number = _as_float(value)
        if number is not None and getattr(line, key) is None:
            setattr(line, key, number)
    return line


def _sofascore_player(node: dict[str, Any]) -> FormLine | None:
    player = node.get("player") if isinstance(node.get("player"), dict) else node
    if not isinstance(player, dict):
        return None
    stats = node.get("statistics") if isinstance(node.get("statistics"), dict) else node
    if not isinstance(stats, dict):
        stats = {}
    name = player.get("name") or player.get("shortName")
    if not isinstance(name, str) or not name.strip():
        return None
    team = node.get("team") if isinstance(node.get("team"), dict) else {}
    minutes = _as_float(stats.get("minutesPlayed", stats.get("minutes", stats.get("totalPlayingTime"))))
    appearances = _as_float(stats.get("appearances", stats.get("games", stats.get("matches"))))
    starts = _as_float(stats.get("started", stats.get("starts", stats.get("gamesStarted"))))
    minutes_pct = None
    if minutes is not None and appearances and appearances > 0:
        minutes_pct = round(min(1.0, minutes / (90.0 * appearances)), 4)
    return FormLine(
        name=name.strip(),
        source="sofascore",
        club=team.get("name") if isinstance(team.get("name"), str) else None,
        position=canonical_position(str(player.get("position") or "")),
        external_id=str(player["id"]) if player.get("id") is not None else None,
        xg=_as_float(stats.get("expectedGoals", stats.get("xg"))),
        xa=_as_float(stats.get("expectedAssists", stats.get("xa"))),
        key_passes=_as_float(stats.get("keyPasses", stats.get("key_passes"))),
        duels_won=_as_float(stats.get("totalDuelsWon", stats.get("duelsWon", stats.get("duels_won")))),
        clearances=_as_float(stats.get("clearances")),
        saves=_as_float(stats.get("saves")),
        average_rating=_as_float(stats.get("rating", stats.get("averageRating"))),
        minutes=minutes,
        starts=starts,
        minutes_pct=minutes_pct,
    )


def parse_sofascore_payload(payload: Any) -> list[FormLine]:
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        found = None
        for key in ("results", "players", "statistics"):
            if isinstance(payload.get(key), list):
                found = payload[key]
                break
        if found is None:
            top = payload.get("topPlayers")
            if isinstance(top, dict):
                for bucket in top.values():
                    if isinstance(bucket, list) and bucket:
                        found = bucket
                        break
        if found is None and isinstance(payload.get("player"), dict):
            rows = [payload]
        else:
            rows = found or []
    else:
        return []
    lines: list[FormLine] = []
    for row in rows:
        if isinstance(row, dict):
            line = _sofascore_player(row)
            if line is not None:
                lines.append(line)
    return lines


def _club_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def parse_transfermarkt_search(payload: Any) -> list[RealValue]:
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        found = None
        for key in ("results", "players"):
            if isinstance(payload.get(key), list):
                found = payload[key]
                break
        rows = found or []
    else:
        return []
    values: list[RealValue] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        position = row.get("position")
        position_text = position.get("name") if isinstance(position, dict) else position
        record = ExternalRecord(
            source="transfermarkt",
            name=name.strip(),
            external_id=str(row["id"]) if row.get("id") is not None else None,
            club=_club_name(row.get("club")),
            position=canonical_position(str(position_text or "")),
        )
        values.append(RealValue(record=record, value_eur=parse_money(row.get("marketValue", row.get("market_value")))))
    return values


def _intel_key(name: str, club: str | None) -> tuple[str, str]:
    return normalize_name(name), normalize_club(club)


def merge_intel(*groups: list[IntelPlayer]) -> list[IntelPlayer]:
    merged: dict[tuple[str, str], IntelPlayer] = {}
    order: list[tuple[str, str]] = []
    for group in groups:
        for player in group:
            key = _intel_key(player.name, player.club)
            current = merged.get(key)
            if current is None:
                name_only = [
                    existing
                    for (existing_name, _club), existing in merged.items()
                    if existing_name == key[0]
                ]
                if len(name_only) == 1 and (not key[1] or not normalize_club(name_only[0].club)):
                    current = name_only[0]
                    key = _intel_key(current.name, current.club)
                else:
                    merged[key] = player
                    order.append(key)
                    continue
            _overlay(current, player)
    return [merged[key] for key in order]


def _overlay(target: IntelPlayer, incoming: IntelPlayer) -> None:
    if target.club is None:
        target.club = incoming.club
    if target.position is None:
        target.position = incoming.position
    if target.external_id is None:
        target.external_id = incoming.external_id
    if incoming.p_titular is not None and (target.p_titular is None or incoming.acceleration is not None):
        target.p_titular = incoming.p_titular
    if incoming.price_delta is not None:
        target.price_delta = incoming.price_delta
    if incoming.price_delta_2 is not None:
        target.price_delta_2 = incoming.price_delta_2
    if incoming.price_delta_3 is not None:
        target.price_delta_3 = incoming.price_delta_3
    if incoming.acceleration is not None:
        target.acceleration = incoming.acceleration
    if incoming.fitness is not None:
        target.fitness = incoming.fitness
    if incoming.fitness_detail is not None:
        target.fitness_detail = incoming.fitness_detail
    if incoming.yellow_cards is not None:
        target.yellow_cards = incoming.yellow_cards
    if incoming.on_verge and not target.suspended:
        target.on_verge = True
    if incoming.suspended:
        target.suspended = True
        target.on_verge = False


def _week_points_tuple(value: Any) -> tuple[float, ...]:
    """Serie oficial de jornadas para el fallback de titularidad (máx. 5)."""
    if not isinstance(value, list):
        return ()
    points: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        number = float(item)
        if number != number:
            continue
        points.append(number)
    return tuple(points[-5:])


def catalog_from_documents(market: dict[str, Any], squads: dict[str, Any]) -> list[CanonicalPlayer]:
    by_id: dict[str, CanonicalPlayer] = {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        for player in squad.get("players") or []:
            if not isinstance(player, dict) or player.get("player_id") is None:
                continue
            player_id = str(player["player_id"])
            price = player.get("market_value") if isinstance(player.get("market_value"), int) else None
            change = (
                player.get("market_value_change")
                if isinstance(player.get("market_value_change"), int)
                and not isinstance(player.get("market_value_change"), bool)
                else None
            )
            by_id[player_id] = CanonicalPlayer(
                player_id=player_id,
                name=player.get("name") if isinstance(player.get("name"), str) else None,
                nickname=player.get("nickname") if isinstance(player.get("nickname"), str) else None,
                club=player.get("club") if isinstance(player.get("club"), str) else None,
                position=player.get("position") if isinstance(player.get("position"), str) else None,
                fantasy_price=price,
                market_value_change=change,
                image_url=player.get("image_url") if isinstance(player.get("image_url"), str) else None,
                week_points=_week_points_tuple(player.get("week_points")),
            )
    for listing in market.get("listings") or []:
        if not isinstance(listing, dict) or listing.get("player_id") is None:
            continue
        player_id = str(listing["player_id"])
        price = listing.get("market_value") if isinstance(listing.get("market_value"), int) else None
        sale = listing.get("sale_price") if isinstance(listing.get("sale_price"), int) else None
        change = (
            listing.get("market_value_change")
            if isinstance(listing.get("market_value_change"), int)
            and not isinstance(listing.get("market_value_change"), bool)
            else None
        )
        current = by_id.get(player_id)
        if current is None:
            listing_image = listing.get("image_url") if isinstance(listing.get("image_url"), str) else None
            by_id[player_id] = CanonicalPlayer(
                player_id=player_id,
                name=listing.get("name") if isinstance(listing.get("name"), str) else None,
                nickname=listing.get("nickname") if isinstance(listing.get("nickname"), str) else None,
                club=listing.get("club") if isinstance(listing.get("club"), str) else None,
                position=listing.get("position") if isinstance(listing.get("position"), str) else None,
                fantasy_price=price if price is not None else sale,
                sale_price=sale,
                market_value_change=change,
                on_market=True,
                image_url=listing_image,
            )
            continue
        listing_image = listing.get("image_url") if isinstance(listing.get("image_url"), str) else None
        by_id[player_id] = replace(
            current,
            sale_price=sale,
            on_market=True,
            fantasy_price=current.fantasy_price if current.fantasy_price is not None else price or sale,
            market_value_change=change if change is not None else current.market_value_change,
            image_url=current.image_url or listing_image,
        )
    return sorted(by_id.values(), key=lambda player: player.player_id)


def _fetch_text(client: ExternalClient, url: str, *, ttl: float, fresh: bool) -> tuple[str | None, bool, str | None]:
    try:
        body, cached = client.get_text(url, ttl=ttl, fresh=fresh)
    except ExternalHttpError as exc:
        from toolbox.browser_scrape import render_with_browser

        if exc.code in {"forbidden", "blocked"}:
            rendered = render_with_browser(url)
            if rendered is not None and not _looks_blocked_html(rendered):
                client.store_page(url, rendered, ttl=ttl)
                return rendered, False, None
        return None, False, str(exc)
    return body, cached, None


def _fetch_json(client: ExternalClient, url: str, *, ttl: float, fresh: bool) -> tuple[Any, bool, str | None]:
    try:
        payload, cached = client.get_json(url, ttl=ttl, fresh=fresh)
    except ExternalHttpError as exc:
        from toolbox.browser_scrape import fetch_json_with_browser

        if exc.code in {"forbidden", "blocked"}:
            payload, _raw = fetch_json_with_browser(url)
            if payload is not None:
                client.store_json(url, payload, ttl=ttl)
                return payload, False, None
        return None, False, str(exc)
    return payload, cached, None


def _looks_blocked_html(body: str) -> bool:
    head = body[:2000].lower()
    return "just a moment" in head or "cf-browser-verification" in head or "attention required" in head


def _load_page(
    client: ExternalClient,
    url: str,
    parser: Callable[[str], list[Any]],
    *,
    ttl: float,
    fresh: bool,
) -> _SourceFetch:
    body, cached, error = _fetch_text(client, url, ttl=ttl, fresh=fresh)
    if error or body is None:
        return _SourceFetch(ok=False, error=error or "Sin cuerpo.")
    rows = parser(body)
    return _SourceFetch(ok=True, count=len(rows), from_cache=cached, rows=rows)


def _load_fbref(client: ExternalClient, *, ttl: float, fresh: bool) -> _SourceFetch:
    lines: list[FormLine] = []
    cached_flags: list[bool] = []
    error: str | None = None
    for url in FBREF_URLS:
        body, cached, fetch_error = _fetch_text(client, url, ttl=ttl, fresh=fresh)
        if fetch_error or body is None:
            error = fetch_error
            if fetch_error and any(token in fetch_error.lower() for token in ("403", "bloqueo", "deneg")):
                break
            continue
        lines.extend(parse_fbref_html(body))
        cached_flags.append(cached)
    merged = _merge_form_lines(lines)
    if not merged:
        return _SourceFetch(ok=False, error=error or "FBref no devolvió tablas.")
    return _SourceFetch(
        ok=True,
        count=len(merged),
        from_cache=all(cached_flags) if cached_flags else False,
        rows=merged,
    )


def _sofascore_url() -> str:
    explicit = os.getenv("SOFASCORE_STATS_URL", "").strip()
    if explicit:
        return explicit
    season = os.getenv("SOFASCORE_SEASON_ID", "").strip() or SOFASCORE_DEFAULT_SEASON
    return (
        f"https://api.sofascore.com/api/v1/unique-tournament/8/season/{season}/top-players/overall"
    )


def _load_sofascore(client: ExternalClient, *, ttl: float, fresh: bool) -> _SourceFetch:
    url = _sofascore_url()
    payload, cached, error = _fetch_json(client, url, ttl=ttl, fresh=fresh)
    if error or payload is None:
        return _SourceFetch(ok=False, error=error or "Sin JSON de Sofascore.")
    rows = parse_sofascore_payload(payload)
    if not rows:
        return _SourceFetch(
            ok=False,
            error="Sofascore no devolvió jugadores. Revisa SOFASCORE_STATS_URL (season id).",
            from_cache=cached,
        )
    return _SourceFetch(ok=True, count=len(rows), from_cache=cached, rows=rows)


def _snapshot_day(market: dict[str, Any] | None) -> str | None:
    """Día civil de la captura del precio, no el día en que corre el proceso.

    El documento de mercado lleva ``source_stored_at`` (epoch de la copia que se
    sirvió). Con la API viva es de hace segundos y coincide con hoy; en air-gap
    puede ser de hace días, y entonces el snapshot debe ir a *ese* día para no
    grabar un día plano inventado.
    """
    if not isinstance(market, dict):
        return None
    stored = market.get("source_stored_at")
    if not isinstance(stored, (int, float)):
        return None
    return madrid_day(float(stored))


def _search_transfermarkt(
    client: ExternalClient,
    name: str,
    *,
    ttl: float,
    fresh: bool,
) -> tuple[list[RealValue], bool]:
    base = transfermarkt_api_base().rstrip("/")
    quoted = urllib.parse.quote(name, safe="")
    url = f"{base}/players/search/{quoted}?page_number=1"
    payload, cached, error = _fetch_json(client, url, ttl=ttl, fresh=fresh)
    if error or payload is None:
        raise ExternalHttpError(error or "Sin JSON de Transfermarkt.", code="upstream")
    return parse_transfermarkt_search(payload), cached


def _signal(intel: IntelPlayer | None, player: CanonicalPlayer) -> int:
    if intel is not None and intel.acceleration is not None:
        return abs(intel.acceleration)
    if intel is not None and intel.price_delta is not None:
        return abs(intel.price_delta)
    return 1 if player.on_market else 0


def _direction(delta: int | None) -> str | None:
    if delta is None:
        return None
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _merge_form_lines(lines: list[FormLine]) -> list[FormLine]:
    merged: dict[str, FormLine] = {}
    order: list[str] = []
    for line in lines:
        key = line.external_id or normalize_name(line.name)
        current = merged.get(key)
        if current is None:
            merged[key] = line
            order.append(key)
            continue
        for attr in _FORM_KEYS:
            if getattr(current, attr) is None and getattr(line, attr) is not None:
                setattr(current, attr, getattr(line, attr))
        if current.club is None:
            current.club = line.club
        if current.position is None:
            current.position = line.position
    return [merged[key] for key in order]


def _apply_form(target: dict[str, Any], line: FormLine) -> None:
    for key in _FORM_KEYS:
        if target[key] is None:
            target[key] = getattr(line, key)
    sources = [part for part in (target["source"], line.source) if part]
    target["source"] = "+".join(dict.fromkeys(sources)) or None


def _stamp_fixture(form: dict[str, Any], fixture: Any | None) -> dict[str, Any] | None:
    if fixture is None:
        return None
    form["fdr"] = fixture.fdr
    form["home"] = fixture.home
    form["opponent"] = fixture.opponent
    form["opponent_xga"] = fixture.opponent_xga
    return {
        "opponent": fixture.opponent,
        "opponent_id": fixture.opponent_id,
        "home": fixture.home,
        "kickoff": fixture.kickoff,
        "fdr": fixture.fdr,
        "opponent_xga": fixture.opponent_xga,
        "opponent_xg": fixture.opponent_xg,
    }


def _player_payload(
    player: CanonicalPlayer,
    *,
    intel: IntelPlayer | None,
    form: dict[str, Any],
    transfermarkt_value: int | None,
    confidence: float | None,
    matches: dict[str, Any],
    fixture: Any | None = None,
) -> dict[str, Any]:
    price = player.fantasy_price
    gap = None
    ratio = None
    if transfermarkt_value is not None and isinstance(price, int) and price > 0:
        gap = transfermarkt_value - price
        ratio = round(transfermarkt_value / price, 4)
    sanction_cards = intel.yellow_cards if intel is not None else None
    ff_delta = intel.price_delta if intel is not None else None
    api_payload = {
        "market_value_change": player.market_value_change,
        "price_delta": ff_delta,
        "market_value": price,
        "fantasy_price": price,
        "sale_price": player.sale_price,
    }
    day_delta = official_price_delta(api_payload)
    from toolbox.normalize import reconcile_fitness

    fitness = intel.fitness if intel is not None else None
    if fitness is None and isinstance(form.get("fitness"), str):
        fitness = form.get("fitness")
    fixture_payload = _stamp_fixture(form, fixture)
    scraped = intel.p_titular if intel is not None else None
    if scraped is not None:
        p_titular = scraped
        p_titular_source = "scraper"
    else:
        p_titular = starter_fallback({"week_points": list(player.week_points)})
        p_titular_source = "week_points" if p_titular is not None else None
    lineup_status = intel.lineup_status if intel is not None else None
    fitness = reconcile_fitness(
        fitness if isinstance(fitness, str) else None,
        p_titular=p_titular,
        p_titular_source=p_titular_source,
        lineup_status=lineup_status,
    )
    return {
        "player_id": player.player_id,
        "name": player.name,
        "nickname": player.nickname,
        "club": player.club,
        "position": player.position,
        "image_url": player.image_url,
        "on_market": player.on_market,
        "fantasy_price": price,
        "sale_price": player.sale_price,
        "market_value_change": player.market_value_change,
        "ff_price_delta": ff_delta,
        "ff_price_delta_2": intel.price_delta_2 if intel is not None else None,
        "ff_price_delta_3": intel.price_delta_3 if intel is not None else None,
        "price_delta": day_delta,
        "price_direction": _direction(day_delta),
        "acceleration": intel.acceleration if intel is not None else None,
        "flip_candidate": False,
        "transfermarkt_value_eur": transfermarkt_value,
        "gap_eur": gap,
        "value_ratio": ratio,
        "p_titular": p_titular,
        "p_titular_source": p_titular_source,
        "lineup_status": lineup_status,
        "lineup_source": intel.lineup_source if intel is not None else None,
        "fitness": fitness,
        "fitness_detail": intel.fitness_detail if intel is not None else None,
        "sanction": {
            "yellow_cards": sanction_cards,
            "on_verge": bool(intel and intel.on_verge),
            "suspended": bool(intel and intel.suspended),
        },
        "fixture": fixture_payload,
        "form": form,
        "matching_confidence": confidence,
        "matches": matches,
    }


def _trends_partial(sources: dict[str, dict[str, Any]]) -> bool:
    for key, source in sources.items():
        if not isinstance(source, dict) or source.get("ok") is not False:
            continue
        if key in _OPTIONAL_TRENDS_SOURCES:
            continue
        return True
    return False


def _optional_sources_degraded(sources: dict[str, dict[str, Any]]) -> bool:
    degraded = False
    for key in _OPTIONAL_TRENDS_SOURCES:
        source = sources.get(key)
        if isinstance(source, dict) and source.get("ok") is False:
            degraded = True
    return degraded


def warm_optional_form_sources(
    client: ExternalClient | None = None,
    *,
    fresh: bool = True,
    ttl: ScrapeTTL | None = None,
) -> dict[str, Any]:
    """Precalienta FBref/Sofascore en caché local (útil con ``FANTASY_SCRAPER_BROWSER=1``)."""
    owns = client is None
    ext = client or ExternalClient()
    clocks = ttl or ScrapeTTL.from_env()
    try:
        fbref = _load_fbref(ext, ttl=clocks.stats, fresh=fresh)
        sofa = _load_sofascore(ext, ttl=clocks.stats, fresh=fresh)
        return {
            "ok": bool(fbref.ok or sofa.ok),
            "command": "warm-stats",
            "fbref": _status(fbref),
            "sofascore": _status(sofa),
        }
    finally:
        if owns:
            ext.close()


def _rank_key(player: dict[str, Any]) -> int | None:
    acceleration = player.get("acceleration")
    if isinstance(acceleration, int):
        return acceleration
    delta = player.get("price_delta")
    if isinstance(delta, int):
        return delta
    return None


def build_trends(
    *,
    league: str | None,
    fresh: bool,
    laliga: LeagueCatalog,
    external: ExternalClient | None = None,
    store: EntityStore | None = None,
    ttl: ScrapeTTL | None = None,
    transfermarkt_limit: int | None = None,
    fetched_at: str | None = None,
    market: dict[str, Any] | None = None,
    squads: dict[str, Any] | None = None,
) -> dict[str, Any]:
    owns_external = external is None
    client = external or ExternalClient()
    owns_store = store is None
    entity_store = store or EntityStore(client.root)
    clocks = ttl or ScrapeTTL.from_env()
    limit = _env_int("TRANSFERMARKT_LOOKUP_LIMIT", 8) if transfermarkt_limit is None else max(0, transfermarkt_limit)
    try:
        if not isinstance(market, dict):
            market = laliga.market_document(league, fresh=fresh)
        if not isinstance(squads, dict):
            squads = laliga.squads_document(league, fresh=fresh)
        catalog = catalog_from_documents(market, squads)
        resolver = EntityResolver(entity_store)
        (
            sources,
            intel_by_player,
            form_by_player,
            value_by_player,
            decisions,
            fixtures_by_club,
            understat_strengths,
            team_rolling,
            match_odds,
        ) = _cross(
            catalog,
            resolver,
            client,
            clocks,
            fresh=fresh,
            limit=limit,
        )
        players = _assemble(
            catalog,
            intel_by_player,
            form_by_player,
            value_by_player,
            decisions,
            fixtures_by_club=fixtures_by_club,
        )
        from toolbox.analitica_fantasy import apply_analitica_fantasy, load_analitica_fantasy

        af_summary: dict[str, Any] = {
            "prediction_rising": [],
            "prediction_falling": [],
            "oracle_points": [],
            "oracle_chollos": [],
            "in_form": [],
        }
        try:
            af_bundle = load_analitica_fantasy(client, ttl=clocks.market, fresh=False)
            sources.update(af_bundle.sources)
            af_decisions, af_summary = apply_analitica_fantasy(catalog, resolver, af_bundle, players)
            decisions.extend(af_decisions)
        except Exception as exc:  # noqa: BLE001 — AF es enriquecimiento; no tumba trends
            sources["analiticafantasy"] = {
                "ok": False,
                "count": 0,
                "error": str(exc),
                "from_cache": False,
            }
        own_summary: dict[str, Any] = {
            "prediction_rising": [],
            "prediction_falling": [],
            "sources": {},
        }
        try:
            from toolbox.own_intel import persist_and_apply_own_intel

            league_id = market.get("league_id") or squads.get("league_id")
            own_summary = persist_and_apply_own_intel(
                players,
                league_id=league_id if isinstance(league_id, str) else None,
                fixtures_by_club=fixtures_by_club,
                strengths=understat_strengths,
                team_rolling=team_rolling,
                match_odds=match_odds,
                day=_snapshot_day(market),
            )
            sources.update(own_summary.get("sources") or {})
        except Exception as exc:  # noqa: BLE001 — own intel no tumba trends
            sources["own_intel"] = {
                "ok": False,
                "count": 0,
                "error": str(exc),
                "from_cache": False,
            }
        image_lookup = getattr(laliga, "image_index", None)
        if callable(image_lookup):
            try:
                # Catálogo de fotos (TTL 6 h): no es info del día, no se fuerza.
                attach_image_urls(players, image_lookup(fresh=False))
            except FantasyHttpError:
                pass
        rising, falling = _split_acceleration(players)
        undervalued = _undervalued(players)
        availability = _availability(players)
        linked = [item for item in decisions if item.linked]
        audits = resolver.audit()
        partial = bool(squads.get("partial")) or _trends_partial(sources)
        optional_degraded = _optional_sources_degraded(sources)
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "command": "trends",
            "league_id": market.get("league_id") or squads.get("league_id"),
            "league_name": market.get("league_name") or squads.get("league_name"),
            "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
            "partial": partial,
            "optional_sources_degraded": optional_degraded,
            "catalog_count": len(players),
            "form_note": FORM_NOTE,
            "sources": sources,
            "matching": {
                "threshold": MATCH_THRESHOLD,
                "linked": len(linked),
                "manual": sum(1 for item in linked if item.manual),
                "low_confidence": len(audits),
                "audits": audits,
            },
            "rising": rising,
            "falling": falling,
            "undervalued": undervalued,
            "availability": availability,
            "af_prediction_rising": af_summary.get("prediction_rising") or [],
            "af_prediction_falling": af_summary.get("prediction_falling") or [],
            "af_oracle_points": af_summary.get("oracle_points") or [],
            "af_oracle_chollos": af_summary.get("oracle_chollos") or [],
            "af_in_form": af_summary.get("in_form") or [],
            "own_prediction_rising": own_summary.get("prediction_rising") or [],
            "own_prediction_falling": own_summary.get("prediction_falling") or [],
            "players": players,
        }
    finally:
        if owns_store:
            entity_store.close()
        if owns_external:
            client.close()


def _stamp_lineups(
    catalog: list[CanonicalPlayer],
    intel_by_player: dict[str, IntelPlayer],
    sightings: list[Any],
    decisions: list[Any],
) -> None:
    """El % del once probable pisa el del mercado: es el dato de la jornada."""
    from toolbox.fantasy_scraper import match_catalog

    for player_id, hit in match_catalog(catalog, sightings).items():
        player = next((item for item in catalog if item.player_id == player_id), None)
        intel = intel_by_player.get(player_id)
        if intel is None:
            label = player.name if player is not None and player.name else player_id
            intel = IntelPlayer(
                name=label,
                club=player.club if player is not None else None,
                position=player.position if player is not None else None,
            )
            intel_by_player[player_id] = intel
        if hit.start_probability is not None:
            intel.p_titular = hit.start_probability
        from toolbox.normalize import reconcile_fitness, stale_injury_overridden

        intel.lineup_status = hit.status
        if hit.fitness == "lesionado" or (hit.fitness and intel.fitness is None):
            intel.fitness = hit.fitness
        elif stale_injury_overridden(
            p_titular=intel.p_titular,
            p_titular_source="scraper",
            lineup_status=intel.lineup_status,
        ):
            intel.fitness = reconcile_fitness(
                intel.fitness,
                p_titular=intel.p_titular,
                p_titular_source="scraper",
                lineup_status=intel.lineup_status,
            )
        intel.lineup_source = hit.source
        for link in hit.links:
            decisions.append(
                MatchDecision(
                    player_id=player_id,
                    source=f"{link.source}_lineups",
                    external_name=link.external_name,
                    external_id=link.external_id,
                    confidence=link.confidence,
                    manual=False,
                    linked=True,
                )
            )


def _link_form_rows(
    catalog: list[CanonicalPlayer],
    resolver: EntityResolver,
    rows: list[FormLine],
    source: str,
    form_by_player: dict[str, dict[str, Any]],
) -> list[Any]:
    if not rows:
        return []
    records = [
        ExternalRecord(
            source=source,
            name=line.name,
            external_id=line.external_id,
            club=line.club,
            position=line.position,
        )
        for line in rows
    ]
    decisions = resolver.link_source(catalog, records, source)
    by_name = {normalize_name(line.name): line for line in rows}
    by_id = {line.external_id: line for line in rows if line.external_id}
    for decision in decisions:
        if not decision.linked:
            continue
        line = by_id.get(decision.external_id) if decision.external_id else None
        if line is None:
            line = by_name.get(normalize_name(decision.external_name))
        if line is None:
            continue
        bucket = form_by_player.setdefault(decision.player_id, _blank_form())
        _apply_form(bucket, line)
    return decisions


def _cross(
    catalog: list[CanonicalPlayer],
    resolver: EntityResolver,
    client: ExternalClient,
    clocks: ScrapeTTL,
    *,
    fresh: bool,
    limit: int,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, IntelPlayer],
    dict[str, dict[str, Any]],
    dict[str, int],
    list[Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    from toolbox.fantasy_scraper import load_lineups
    from toolbox.jornada_perfecta import load_jornada_perfecta
    from toolbox.understat import load_understat

    # Páginas independientes en paralelo: la primera carga en frío no las encadena.
    # Solo el mercado de FútbolFantasy y las alineaciones respetan ``fresh``:
    # estadística, cuotas, JP y el resto de fuentes pesadas van siempre a caché
    # con su TTL (horas o días), para no castigarlas con cada "Actualizar".
    with ThreadPoolExecutor(max_workers=8) as pool:
        market_future = pool.submit(
            inherited(_load_page), client, FF_MARKET_URL, parse_market_board, ttl=clocks.market, fresh=fresh
        )
        fitness_future = pool.submit(
            inherited(_load_page), client, FF_FITNESS_URL, parse_fitness_board, ttl=clocks.fitness, fresh=False
        )
        sanctions_future = pool.submit(
            inherited(_load_page), client, FF_SANCTIONS_URL, parse_sanction_board, ttl=clocks.sanctions, fresh=False
        )
        warnings_future = pool.submit(
            inherited(_load_page), client, FF_WARNINGS_URL, parse_warning_board, ttl=clocks.sanctions, fresh=False
        )
        lineups_future = pool.submit(inherited(load_lineups), client, ttl=clocks.market, fresh=fresh)
        fbref_future = pool.submit(inherited(_load_fbref), client, ttl=clocks.stats, fresh=False)
        sofa_future = pool.submit(inherited(_load_sofascore), client, ttl=clocks.stats, fresh=False)
        understat_future = pool.submit(inherited(load_understat), client, ttl=clocks.stats, fresh=False)
        jp_future = pool.submit(inherited(load_jornada_perfecta), client, ttl=clocks.market, fresh=False)
        market_fetch = market_future.result()
        fitness_fetch = fitness_future.result()
        sanctions_fetch = sanctions_future.result()
        warnings_fetch = warnings_future.result()
        lineup_sources, sightings = lineups_future.result()
        fbref_fetch = fbref_future.result()
        sofa_fetch = sofa_future.result()
        understat_rows, fixtures_by_club, understat_strengths, team_rolling, understat_status = understat_future.result()
        jp_rows, jp_status = jp_future.result()
    league_vals = [
        item.avg_xg
        for item in {id(v): v for v in understat_strengths.values()}.values()
        if getattr(item, "avg_xg", 0) > 0
    ]
    league_avg_xg = sum(league_vals) / len(league_vals) if league_vals else 1.32
    match_odds, odds_status = load_laliga_match_odds(
        client,
        fixtures_by_club=fixtures_by_club,
        strengths=understat_strengths,
        team_rolling=team_rolling,
        ttl=clocks.odds,
        fresh=False,
        league_avg_xg=league_avg_xg,
    )
    intel_rows = merge_intel(
        market_fetch.rows,
        fitness_fetch.rows,
        sanctions_fetch.rows,
        warnings_fetch.rows,
    )
    ff_records = [
        ExternalRecord(
            source="futbolfantasy",
            name=row.name,
            external_id=row.external_id,
            club=row.club,
            position=row.position,
        )
        for row in intel_rows
    ]
    ff_decisions = resolver.link_source(catalog, ff_records, "futbolfantasy")
    intel_index = {}
    for row in intel_rows:
        if row.external_id:
            intel_index["id:" + row.external_id] = row
        intel_index["name:" + normalize_name(row.name)] = row
    intel_by_player: dict[str, IntelPlayer] = {}
    for decision in ff_decisions:
        if not decision.linked:
            continue
        row = None
        if decision.external_id:
            row = intel_index.get("id:" + decision.external_id)
        if row is None:
            row = intel_index.get("name:" + normalize_name(decision.external_name))
        if row is not None:
            intel_by_player[decision.player_id] = row

    _stamp_lineups(catalog, intel_by_player, sightings, ff_decisions)
    form_by_player: dict[str, dict[str, Any]] = {}
    form_decisions: list[Any] = []
    # Understat primero: manda en xG/xA y minutos; el resto solo rellena huecos.
    understat_lines = [line for row in understat_rows if (line := form_line_from_mapping(row)) is not None]
    form_decisions.extend(_link_form_rows(catalog, resolver, understat_lines, "understat", form_by_player))
    form_decisions.extend(_link_form_rows(catalog, resolver, list(fbref_fetch.rows), "fbref", form_by_player))
    form_decisions.extend(_link_form_rows(catalog, resolver, list(sofa_fetch.rows), "sofascore", form_by_player))
    jp_lines = [line for row in jp_rows if (line := form_line_from_mapping(row)) is not None]
    form_decisions.extend(_link_form_rows(catalog, resolver, jp_lines, "jornadaperfecta", form_by_player))
    # Fitness JP solo si Fútbol Fantasy no traía parte.
    jp_fitness = {normalize_name(row["name"]): row.get("fitness") for row in jp_rows if row.get("fitness")}
    for player_id, intel in intel_by_player.items():
        if intel.fitness:
            continue
        form = form_by_player.get(player_id)
        name = None
        player = next((item for item in catalog if item.player_id == player_id), None)
        if player is not None:
            name = player.name or player.nickname
        if not name:
            continue
        fitness = jp_fitness.get(normalize_name(name))
        if isinstance(fitness, str):
            intel.fitness = fitness
            if form is not None:
                form["fitness"] = fitness

    value_by_player, tm_fetch, tm_decisions = _load_transfermarkt(
        catalog,
        intel_by_player,
        resolver,
        client,
        ttl=clocks.transfermarkt,
        fresh=False,
        limit=limit,
    )
    sources = {
        "futbolfantasy_market": _status(market_fetch),
        "futbolfantasy_fitness": _status(fitness_fetch),
        "futbolfantasy_sanctions": _status(sanctions_fetch),
        "futbolfantasy_warnings": _status(warnings_fetch),
        **lineup_sources,
        "fbref": _status(fbref_fetch),
        "sofascore": _status(sofa_fetch),
        "understat": {
            "ok": bool(understat_status.get("ok")),
            "count": int(understat_status.get("count") or 0),
            "error": understat_status.get("error"),
            "from_cache": bool(understat_status.get("from_cache")),
            "fixtures": understat_status.get("fixtures"),
        },
        "jornadaperfecta": {
            "ok": bool(jp_status.get("ok")),
            "count": int(jp_status.get("count") or 0),
            "error": jp_status.get("error"),
            "from_cache": bool(jp_status.get("from_cache")),
        },
        "transfermarkt": _status(tm_fetch),
        "laliga_odds": {
            "ok": bool(odds_status.get("ok")),
            "count": int(odds_status.get("count") or 0),
            "error": odds_status.get("error"),
            "from_cache": bool(odds_status.get("from_cache")),
            "source": odds_status.get("source"),
        },
    }
    return (
        sources,
        intel_by_player,
        form_by_player,
        value_by_player,
        [*ff_decisions, *form_decisions, *tm_decisions],
        fixtures_by_club,
        understat_strengths,
        team_rolling,
        match_odds,
    )


def _load_transfermarkt(
    catalog: list[CanonicalPlayer],
    intel_by_player: dict[str, IntelPlayer],
    resolver: EntityResolver,
    client: ExternalClient,
    *,
    ttl: float,
    fresh: bool,
    limit: int,
) -> tuple[dict[str, int], _SourceFetch, list[Any]]:
    if limit == 0 or not catalog:
        return {}, _SourceFetch(ok=True, count=0), []
    ordered = sorted(
        catalog,
        key=lambda player: (-_signal(intel_by_player.get(player.player_id), player), player.player_id),
    )
    targets = [player for player in ordered if _signal(intel_by_player.get(player.player_id), player) > 0][:limit]
    values: dict[str, int] = {}
    decisions: list[Any] = []
    errors: list[str] = []
    cached_flags: list[bool] = []
    found = 0
    for player in targets:
        query = player.name or player.nickname
        if not query:
            continue
        # Cortacircuitos: si Transfermarkt se ha caído, no se paga un timeout
        # por cada nombre restante. Se deja de buscar y se informa arriba.
        breaker = getattr(client, "transfermarkt_breaker_open", None)
        if callable(breaker):
            reason = breaker()
            if reason:
                errors.append(reason)
                break
        try:
            rows, cached = _search_transfermarkt(client, query, ttl=ttl, fresh=fresh)
        except ExternalHttpError as exc:
            errors.append(str(exc))
            continue
        cached_flags.append(cached)
        found += 1
        decision = resolver.link_player(player, [row.record for row in rows], "transfermarkt")
        if decision is None:
            continue
        decisions.append(decision)
        if not decision.linked:
            continue
        chosen = None
        for row in rows:
            if decision.external_id and row.record.external_id == decision.external_id:
                chosen = row
                break
            if normalize_name(row.record.name) == normalize_name(decision.external_name):
                chosen = row
        if chosen is not None and chosen.value_eur is not None:
            values[player.player_id] = chosen.value_eur
    if targets and found == 0:
        return values, _SourceFetch(ok=False, error=errors[0] if errors else "Sin búsquedas."), decisions
    return (
        values,
        _SourceFetch(
            ok=True,
            count=len(values),
            from_cache=bool(cached_flags) and all(cached_flags),
            error=errors[0] if errors else None,
        ),
        decisions,
    )


def _assemble(
    catalog: list[CanonicalPlayer],
    intel_by_player: dict[str, IntelPlayer],
    form_by_player: dict[str, dict[str, Any]],
    value_by_player: dict[str, int],
    decisions: list[Any],
    *,
    fixtures_by_club: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_player: dict[str, list[Any]] = {}
    for decision in decisions:
        by_player.setdefault(decision.player_id, []).append(decision)
    fixtures = fixtures_by_club or {}
    payloads: list[dict[str, Any]] = []
    for player in catalog:
        linked = [item for item in by_player.get(player.player_id, []) if item.linked]
        confidence = min((item.confidence for item in linked), default=None)
        if confidence is not None:
            confidence = round(float(confidence), 4)
        matches = {
            item.source: {
                "external_name": item.external_name,
                "external_id": item.external_id,
                "confidence": item.confidence,
                "manual": item.manual,
            }
            for item in linked
        }
        club_key = normalize_club(player.club) if player.club else ""
        fixture = fixtures.get(club_key) if club_key else None
        if fixture is None and player.club:
            fixture = fixtures.get(normalize_name(player.club))
        payloads.append(
            _player_payload(
                player,
                intel=intel_by_player.get(player.player_id),
                form=form_by_player.get(player.player_id, _blank_form()),
                transfermarkt_value=value_by_player.get(player.player_id),
                confidence=confidence,
                matches=matches,
                fixture=fixture,
            )
        )
    return payloads


def _split_acceleration(players: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = [player for player in players if isinstance(_rank_key(player), int) and _rank_key(player) != 0]
    rising = sorted(ranked, key=lambda player: (-int(_rank_key(player) or 0), player["player_id"]))
    falling = sorted(ranked, key=lambda player: (int(_rank_key(player) or 0), player["player_id"]))
    rising = [player for player in rising if int(_rank_key(player) or 0) > 0][:RANK_LIMIT]
    falling = [player for player in falling if int(_rank_key(player) or 0) < 0][:RANK_LIMIT]
    flagged = {player["player_id"] for player in rising + falling}
    for player in players:
        own_up = player.get("own_market_signal") == "up"
        af_up = player.get("af_market_signal") == "up"
        player["flip_candidate"] = player["player_id"] in flagged or own_up or af_up
    return rising, falling


def _undervalued(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valued = [player for player in players if isinstance(player.get("value_ratio"), float)]
    valued.sort(key=lambda player: (-float(player["value_ratio"]), player["player_id"]))
    return valued[:RANK_LIMIT]


def _availability(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def weight(player: dict[str, Any]) -> tuple[int, str]:
        sanction = player["sanction"]
        if sanction["suspended"]:
            rank = 0
        elif player.get("fitness") == "lesionado":
            rank = 1
        elif sanction["on_verge"]:
            rank = 2
        else:
            rank = 3
        return rank, player["player_id"]

    selected = []
    for player in players:
        sanction = player["sanction"]
        if player.get("fitness") in {"lesionado", "duda"} or sanction["suspended"] or sanction["on_verge"]:
            selected.append(player)
    selected.sort(key=weight)
    return selected


_LINEUP_SIGHTINGS_CACHE: tuple[float, list[Any]] | None = None
_LINEUP_SIGHTINGS_CACHE_TTL = 10 * 60


def _cached_lineup_sightings(
    client: Any,
    *,
    fresh: bool,
    ttl: float,
) -> list[Any]:
    global _LINEUP_SIGHTINGS_CACHE
    from toolbox.fantasy_scraper import load_lineups

    now = time.monotonic()
    if (
        not fresh
        and _LINEUP_SIGHTINGS_CACHE is not None
        and now - _LINEUP_SIGHTINGS_CACHE[0] < _LINEUP_SIGHTINGS_CACHE_TTL
    ):
        return _LINEUP_SIGHTINGS_CACHE[1]
    _sources, rows = load_lineups(client, ttl=ttl, fresh=fresh)
    _LINEUP_SIGHTINGS_CACHE = (now, rows)
    return rows


def _squad_needs_titular_refresh(
    squad: dict[str, Any],
    trend_index: dict[str, dict[str, Any]],
) -> bool:
    players = squad.get("players") if isinstance(squad.get("players"), list) else []
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            continue
        trend = trend_index.get(player_id) if isinstance(trend_index.get(player_id), dict) else {}
        p_titular = trend.get("p_titular")
        if p_titular is None:
            return True
        if isinstance(p_titular, (int, float)) and not isinstance(p_titular, bool):
            share = float(p_titular)
            if share > 1.0:
                share /= 100.0
            if share < 0.05:
                return True
    return False


def refresh_player_titularity(
    players: list[dict[str, Any]],
    *,
    fresh: bool = False,
    ttl: float = 30 * 60,
) -> None:
    """Relee titularidad desde caché HTTP (alineaciones + mercado FF).

    Las fotos ``full`` en disco pueden guardar ``p_titular`` obsoleto; el once
    la vuelve a cruzar al enriquecer sin repetir todo ``build_trends``.

    Va siempre dentro de ``no_network()``: esto es un refresco de lectura sobre
    una foto ya guardada, así que se sirve de ``.cache/`` y, si la fuente no
    tiene copia, se queda con la titularidad de la foto. Un ``GET /api/optimize``
    no debe abrir sockets hacia Transfermarkt ni FútbolFantasy.
    """
    if not players:
        return
    from toolbox.fantasy_scraper import LineupPlayer, match_catalog
    from toolbox.net import ExternalClient, no_network

    rows = [player for player in players if isinstance(player, dict) and player.get("player_id")]
    if not rows:
        return
    catalog = [
        CanonicalPlayer(
            player_id=str(player["player_id"]),
            name=player.get("name") if isinstance(player.get("name"), str) else None,
            nickname=player.get("nickname") if isinstance(player.get("nickname"), str) else None,
            club=player.get("club") if isinstance(player.get("club"), str) else None,
            position=player.get("position") if isinstance(player.get("position"), str) else None,
            fantasy_price=None,
        )
        for player in rows
    ]
    client = ExternalClient()
    try:
        with no_network():
            _apply_cached_titularity(client, rows, catalog, fresh=fresh, ttl=ttl)
    finally:
        client.close()


def _apply_cached_titularity(
    client: ExternalClient,
    rows: list[dict[str, Any]],
    catalog: list[Any],
    *,
    fresh: bool,
    ttl: float,
) -> None:
    """Cruza alineaciones y mercado FF **desde caché** sobre ``rows``."""
    from toolbox.fantasy_scraper import LineupPlayer, match_catalog

    lineup_rows = _cached_lineup_sightings(client, fresh=fresh, ttl=ttl)
    for player_id, hit in match_catalog(catalog, lineup_rows).items():
        if hit.start_probability is None:
            continue
        target = next((row for row in rows if str(row.get("player_id")) == player_id), None)
        if target is None:
            continue
        target["p_titular"] = hit.start_probability
        target["p_titular_source"] = "scraper"
        target["lineup_status"] = hit.status
    market = _load_page(client, FF_MARKET_URL, parse_market_board, ttl=ttl, fresh=fresh)
    if not market.ok:
        return
    market_rows = [
        LineupPlayer(
            name=row.name,
            source="futbolfantasy_market",
            club=row.club,
            position=row.position,
            external_id=row.external_id,
            start_probability=row.p_titular,
            status="titular" if isinstance(row.p_titular, float) and row.p_titular >= 0.5 else "suplente",
        )
        for row in market.rows
        if isinstance(row, IntelPlayer) and row.p_titular is not None
    ]
    for player_id, hit in match_catalog(catalog, market_rows).items():
        if hit.start_probability is None:
            continue
        target = next((row for row in rows if str(row.get("player_id")) == player_id), None)
        if target is None:
            continue
        current = target.get("p_titular")
        if isinstance(current, (int, float)) and not isinstance(current, bool) and float(current) >= 0.05:
            continue
        target["p_titular"] = hit.start_probability
        target["p_titular_source"] = "scraper"


def refresh_squad_titularity_in_index(
    squad: dict[str, Any],
    trend_index: dict[str, dict[str, Any]],
    *,
    fresh: bool = False,
) -> None:
    """Actualiza ``p_titular`` en el índice de trends para la plantilla propia.

    Es enriquecimiento opcional: si la fuente de alineaciones no está (sin
    red, sin caché, host caído), el once se resuelve con lo que ya trae la foto
    en lugar de romper el comando. Mismo criterio que AF y own-intel en
    ``build_trends``: un extra no tumba el resultado principal.
    """
    players = squad.get("players") if isinstance(squad.get("players"), list) else []
    rows: list[dict[str, Any]] = []
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            continue
        merged = dict(player)
        trend = trend_index.get(player_id)
        if isinstance(trend, dict):
            merged.update(trend)
        rows.append(merged)
    if not rows:
        return
    if not _squad_needs_titular_refresh(squad, trend_index):
        return
    try:
        refresh_player_titularity(rows, fresh=fresh)
    except Exception as exc:  # noqa: BLE001 — titularidad es enriquecimiento; no tumba el once
        logger.debug("Titularidad no disponible, el once usa la foto: %s", exc)
        return
    keys = ("p_titular", "p_titular_source", "lineup_status")
    for row in rows:
        player_id = row.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            continue
        patch = {key: row[key] for key in keys if key in row}
        if not patch:
            continue
        current = trend_index.get(player_id)
        trend_index[player_id] = {**(current if isinstance(current, dict) else {}), **patch}

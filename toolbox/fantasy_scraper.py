"""Alineaciones probables y % de titularidad de Fútbol Fantasy y Analítica Fantasy.

Fútbol Fantasy no publica el once en ``/laliga/alineaciones-probables`` (esa
ruta responde 404). El índice vivo es ``/laliga/posibles-alineaciones`` y cada
partido trae las fichas en HTML: ``data-onceFF`` (titular o suplente),
``data-probabilidad`` y ``span.truncate-name``.

Analítica Fantasy pinta el once en el cliente, pero el HTML del partido ya
trae ``lineupBlock`` (nombre, ``chance`` de 0 a 100 y ``esTitular``).

Un fallo de una fuente no inventa un porcentaje. El cruce con la plantilla
usa el mismo umbral de 0.85 que el resto de fuentes: un «E. Militão» casa con
«Éder Militão» si el club no lo contradice. Por debajo de ese umbral, o si
dos candidatos quedan demasiado cerca, el jugador local se queda sin dato.
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass

from toolbox.matching import (
    AMBIGUITY_GAP,
    MATCH_THRESHOLD,
    CanonicalPlayer,
    ExternalRecord,
    canonical_position,
    normalize_club,
    normalize_name,
    score_pair,
)
from toolbox.net import ExternalClient, ExternalHttpError

FF_LINEUPS_URL = "https://www.futbolfantasy.com/laliga/posibles-alineaciones"
AF_LINEUPS_URL = "https://www.analiticafantasy.com/la-liga/alineaciones-probables"
DOUBT_BELOW = 0.70
MAX_MATCHES = 10

_FF_MATCH_URL = re.compile(r"https://www\.futbolfantasy\.com/partidos/\d+-[a-z0-9-]+", re.I)
_AF_MATCH_URL = re.compile(
    r"(?:https://www\.analiticafantasy\.com)?/partido/(\d+)-([a-z0-9-]+)",
    re.I,
)
_FF_PLAYER = re.compile(r'<div class="jugador_(\d+)\b')
_FF_SIDE = re.compile(
    r"row-visitante|row-local|alineacion_superwrapper\b[^\"']*",
    re.I,
)
_FF_NAME = re.compile(r'class="nombre[^"]*"[^>]*>\s*([^<]+?)\s*</div>', re.I)
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)")
_AF_POSITION = {0: "POR", 1: "DEF", 2: "MC", 3: "DEL"}
_INJURY_TOKENS = ("baja", "lesion", "injured", "sancion", "sanction")
_DOUBT_TOKENS = ("duda", "molest", "doubt")


@dataclass(frozen=True)
class LineupPlayer:
    name: str
    source: str
    club: str | None = None
    position: str | None = None
    external_id: str | None = None
    start_probability: float | None = None
    status: str = "fuera"


@dataclass(frozen=True)
class LineupLink:
    source: str
    external_name: str
    external_id: str | None
    confidence: float


@dataclass(frozen=True)
class LineupHit:
    start_probability: float | None
    status: str
    source: str
    fitness: str | None
    links: tuple[LineupLink, ...]


def _probability(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = _PERCENT.search(str(value))
        if match is None:
            return None
        number = float(match.group(1).replace(",", "."))
    if number > 1:
        number /= 100.0
    if number < 0 or number > 1:
        return None
    return round(number, 4)


def classify_lineup(*, role: str | None, probability: float | None, note: str | None) -> str:
    """titular, suplente, duda, baja o fuera. No rellena un % que la web no dio."""
    folded = normalize_name(note)
    if any(token in folded for token in _INJURY_TOKENS):
        return "baja"
    if any(token in folded for token in _DOUBT_TOKENS):
        return "duda"
    if role == "baja":
        return "baja"
    if role == "titular":
        if probability is not None and probability < DOUBT_BELOW:
            return "duda"
        return "titular"
    if role == "suplente":
        if probability is not None and probability <= 0:
            return "fuera"
        return "suplente"
    if probability is not None and probability >= DOUBT_BELOW:
        return "titular"
    if probability is not None and probability > 0:
        return "suplente"
    return "fuera"


def _fitness_for(status: str) -> str | None:
    if status == "baja":
        return "lesionado"
    if status == "duda":
        return "duda"
    return None


def _unique(urls: list[str], *, limit: int = MAX_MATCHES) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
        if len(ordered) >= limit:
            break
    return ordered


def parse_ff_fixture_urls(page: str) -> list[str]:
    """Partidos de la jornada visible. El lateral de resultados ya jugados queda fuera."""
    main = re.split(r"<aside\b", page, maxsplit=1, flags=re.I)[0]
    return _unique(_FF_MATCH_URL.findall(main))


def _ff_teams(page: str) -> tuple[str | None, str | None]:
    names = [html.unescape(item).strip() for item in _FF_NAME.findall(page)]
    names = [item for item in names if item]
    local = names[0] if names else None
    away = names[1] if len(names) > 1 else None
    return local, away


def _ff_side(marker: str) -> str | None:
    lowered = marker.lower()
    if "visitante" in lowered:
        return "visitante"
    if "local" in lowered:
        return "local"
    return None


def _prefer_card(current: LineupPlayer, incoming: LineupPlayer) -> LineupPlayer:
    rank = {"titular": 4, "duda": 3, "suplente": 2, "baja": 3, "fuera": 0}
    if rank.get(incoming.status, 0) > rank.get(current.status, 0):
        return incoming
    if incoming.start_probability is not None and current.start_probability is None:
        return incoming
    return current


def parse_ff_match(page: str) -> list[LineupPlayer]:
    local_name, away_name = _ff_teams(page)
    clubs = {"local": local_name, "visitante": away_name}
    starts = list(_FF_PLAYER.finditer(page))
    side_marks = [(match.start(), _ff_side(match.group(0))) for match in _FF_SIDE.finditer(page)]
    by_id: dict[str, LineupPlayer] = {}
    order: list[str] = []
    side_cursor = 0
    current_side: str | None = None
    for index, match in enumerate(starts):
        while side_cursor < len(side_marks) and side_marks[side_cursor][0] < match.start():
            current_side = side_marks[side_cursor][1] or current_side
            side_cursor += 1
        end = starts[index + 1].start() if index + 1 < len(starts) else min(len(page), match.end() + 25000)
        chunk = page[match.start() : end]
        role_match = re.search(r'data-onceFF="(titular|suplente|duda)"', chunk, flags=re.I)
        if role_match is None:
            continue
        name_match = re.search(r'class="truncate-name[^"]*"[^>]*>\s*([^<]+?)\s*<', chunk, flags=re.I)
        if name_match is None:
            name_match = re.search(r'<img[^>]*\balt="([^"]+)"', chunk, flags=re.I)
        if name_match is None:
            continue
        name = html.unescape(name_match.group(1)).strip()
        if not name:
            continue
        probability = None
        prob_match = re.search(r'data-probabilidad="([^"]*)"', chunk, flags=re.I)
        if prob_match:
            probability = _probability(prob_match.group(1))
        note = None
        lesion = re.search(r'data-lesion="([^"]*)"', chunk, flags=re.I)
        if lesion and lesion.group(1).strip() not in {"", "-1"}:
            note = lesion.group(1)
        status = classify_lineup(role=role_match.group(1).lower(), probability=probability, note=note)
        slug = re.search(r"/jugadores/([a-z0-9-]+)", chunk, flags=re.I)
        player = LineupPlayer(
            name=name,
            source="futbolfantasy",
            club=clubs.get(current_side or ""),
            external_id=match.group(1) or (slug.group(1) if slug else None),
            start_probability=probability,
            status=status,
        )
        previous = by_id.get(player.external_id or "")
        key = player.external_id or normalize_name(name)
        if not key:
            continue
        if previous is None:
            by_id[key] = player
            order.append(key)
        else:
            by_id[key] = _prefer_card(previous, player)
    return [by_id[key] for key in order]


def _json_after(page: str, marker: str) -> object | None:
    at = page.find(marker)
    if at < 0:
        return None
    brace = page.find("[", at)
    curly = page.find("{", at)
    if brace < 0 and curly < 0:
        return None
    if curly >= 0 and (brace < 0 or curly < brace):
        start = curly
    else:
        start = brace
    raw = page[start:]
    if '\\"' in raw[:80]:
        raw = _unescape_js(raw)
    try:
        payload, _end = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError:
        return None
    return payload


def _af_fixture_ids(page: str) -> list[str]:
    payload = _json_after(page, '\\"fixtures\\":')
    if payload is None:
        payload = _json_after(page, '"fixtures":')
    if not isinstance(payload, list):
        return []
    ids: list[str] = []
    for item in payload:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.append(str(item["id"]))
    return ids


def parse_af_fixture_urls(page: str) -> list[str]:
    ids = _af_fixture_ids(page)
    if ids:
        found: list[str] = []
        for fixture_id in ids:
            match = re.search(
                rf"https://www\.analiticafantasy\.com/partido/{re.escape(fixture_id)}-[a-z0-9-]+",
                page,
                flags=re.I,
            )
            if match:
                found.append(match.group(0))
                continue
            relative = re.search(rf"/partido/{re.escape(fixture_id)}-[a-z0-9-]+", page, flags=re.I)
            if relative:
                found.append("https://www.analiticafantasy.com" + relative.group(0))
        if found:
            return _unique(found)
    found = []
    for match_id, slug in _AF_MATCH_URL.findall(page):
        found.append(f"https://www.analiticafantasy.com/partido/{match_id}-{slug}")
    return _unique(found)


def _unescape_js(text: str) -> str:
    """Quita un nivel de escape de comillas. Deja ``\\uXXXX`` para ``json.loads``."""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            if nxt in {'"', "\\", "/"}:
                out.append(nxt)
                index += 2
                continue
            if nxt == "n":
                out.append("\n")
                index += 2
                continue
            if nxt == "t":
                out.append("\t")
                index += 2
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _lineup_block(page: str) -> dict | None:
    marker = page.find("lineupBlock")
    if marker < 0:
        return None
    brace = page.find("{", marker)
    if brace < 0:
        return None
    raw = page[brace:]
    if '\\"' in raw[:120]:
        raw = _unescape_js(raw)
    try:
        payload, _end = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _af_team_names(page: str) -> dict[str, str]:
    """teamId -> nombre, tanto en JSON plano como en el payload escapado de Next."""
    names: dict[str, str] = {}
    patterns = (
        re.compile(
            r'homeTeamId\\?"\s*:\s*(\d+).*?awayTeamId\\?"\s*:\s*(\d+).*?'
            r'homeTeamName\\?"\s*:\s*\\?"([^"\\]+)\\?".*?awayTeamName\\?"\s*:\s*\\?"([^"\\]+)'
        ),
        re.compile(
            r'"homeTeamId"\s*:\s*(\d+).*?"awayTeamId"\s*:\s*(\d+).*?'
            r'"homeTeamName"\s*:\s*"([^"]+)".*?"awayTeamName"\s*:\s*"([^"]+)"'
        ),
    )
    for pattern in patterns:
        for home_id, away_id, home, away in pattern.findall(page):
            names.setdefault(home_id, html.unescape(home).strip())
            names.setdefault(away_id, html.unescape(away).strip())
    return names


def _af_note(raw: dict) -> str | None:
    extras = raw.get("playerExtras") if isinstance(raw.get("playerExtras"), dict) else {}
    parts = [
        extras.get("status"),
        extras.get("report"),
        extras.get("statusInfo"),
        raw.get("comentario"),
    ]
    text = " ".join(str(item).strip() for item in parts if isinstance(item, str) and item.strip())
    return text or None


def _af_players(block: dict, *, club: str | None) -> list[LineupPlayer]:
    rows = block.get("players") if isinstance(block.get("players"), list) else []
    parsed: list[LineupPlayer] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        probability = _probability(raw.get("chance"))
        role = "titular" if raw.get("esTitular") is True else "suplente"
        position_id = raw.get("positionId")
        position = _AF_POSITION.get(position_id) if isinstance(position_id, int) else None
        player_id = raw.get("playerId")
        parsed.append(
            LineupPlayer(
                name=name.strip(),
                source="analiticafantasy",
                club=club,
                position=canonical_position(position),
                external_id=str(player_id) if player_id is not None else None,
                start_probability=probability,
                status=classify_lineup(role=role, probability=probability, note=_af_note(raw)),
            )
        )
    return parsed


def parse_af_match(page: str) -> list[LineupPlayer]:
    block = _lineup_block(page)
    if not block:
        return []
    teams = _af_team_names(page)
    parsed: list[LineupPlayer] = []
    for side in ("home", "away"):
        squad = block.get(side)
        if not isinstance(squad, dict):
            continue
        team_id = squad.get("teamId")
        club = teams.get(str(team_id)) if team_id is not None else None
        parsed.extend(_af_players(squad, club=club))
    return parsed


def index_by_name(rows: list[LineupPlayer]) -> dict[str, dict]:
    """Índice por nombre normalizado. Dos clubes distintos bajo la misma clave no se pisan."""
    indexed: dict[str, dict] = {}
    for row in rows:
        key = normalize_name(row.name)
        if not key:
            continue
        payload = {
            "source_name": row.name,
            "club": row.club,
            "startProbability": row.start_probability,
            "lineupStatus": row.status,
            "source": row.source,
            "external_id": row.external_id,
        }
        current = indexed.get(key)
        if current is None:
            indexed[key] = payload
            continue
        same_club = normalize_club(current.get("club")) == normalize_club(row.club)
        if current.get("club") and row.club and not same_club:
            current["ambiguous"] = True
            continue
        current_prob = current.get("startProbability")
        if row.start_probability is not None and (current_prob is None or row.start_probability > current_prob):
            payload["ambiguous"] = current.get("ambiguous", False)
            indexed[key] = payload
    return indexed


def _merge_rows(rows: list[tuple[LineupPlayer, float]]) -> LineupHit:
    probabilities = [row.start_probability for row, _score in rows if row.start_probability is not None]
    probability = round(sum(probabilities) / len(probabilities), 4) if probabilities else None
    statuses = {row.status for row, _score in rows}
    if "baja" in statuses:
        status = "baja"
    elif "duda" in statuses or ("titular" in statuses and probability is not None and probability < DOUBT_BELOW):
        status = "duda"
    elif "titular" in statuses:
        status = "titular"
    elif "suplente" in statuses:
        status = "suplente"
    else:
        status = "fuera"
    sources = list(dict.fromkeys(row.source for row, _score in rows))
    links = tuple(
        LineupLink(
            source=row.source,
            external_name=row.name,
            external_id=row.external_id,
            confidence=round(score, 4),
        )
        for row, score in rows
    )
    return LineupHit(
        start_probability=probability,
        status=status,
        source="+".join(sources),
        fitness=_fitness_for(status),
        links=links,
    )


def match_catalog(players: list[CanonicalPlayer], sightings: list[LineupPlayer]) -> dict[str, LineupHit]:
    """Asigna cada ficha externa a un jugador canónico. Un empate corto no se fuerza."""
    if not players or not sightings:
        return {}
    grouped: dict[int, list[tuple[LineupPlayer, float]]] = {}
    for sighting in sightings:
        record = ExternalRecord(
            source=sighting.source,
            name=sighting.name,
            external_id=sighting.external_id,
            club=sighting.club,
            position=sighting.position,
        )
        ranking: list[tuple[float, int]] = []
        for index, player in enumerate(players):
            score = score_pair(player, record)
            if score >= MATCH_THRESHOLD:
                ranking.append((score, index))
        ranking.sort(reverse=True)
        if not ranking:
            continue
        if len(ranking) > 1 and ranking[0][0] - ranking[1][0] < AMBIGUITY_GAP:
            continue
        grouped.setdefault(ranking[0][1], []).append((sighting, ranking[0][0]))

    matched: dict[str, LineupHit] = {}
    for index, rows in grouped.items():
        clubs = {normalize_club(row.club) for row, _score in rows if row.club}
        if len(clubs) > 1:
            continue
        matched[players[index].player_id] = _merge_rows(rows)
    return matched


def _canonical(player: dict, fallback_id: str) -> CanonicalPlayer:
    def text(key: str) -> str | None:
        value = player.get(key)
        return value if isinstance(value, str) and value.strip() else None

    return CanonicalPlayer(
        player_id=str(player.get("player_id") or fallback_id),
        name=text("name"),
        nickname=text("nickname"),
        club=text("club"),
        position=text("position"),
        fantasy_price=None,
    )


def enrich_player_list(local_players: list, sightings: list[LineupPlayer]) -> list:
    """Copia la plantilla local e inyecta titularidad solo donde el cruce supera 0.85."""
    catalog = [_canonical(player, str(index)) for index, player in enumerate(local_players) if isinstance(player, dict)]
    hits = match_catalog(catalog, sightings)
    enriched: list = []
    cursor = 0
    for player in local_players:
        if not isinstance(player, dict):
            enriched.append(player)
            continue
        copy = dict(player)
        hit = hits.get(catalog[cursor].player_id)
        cursor += 1
        if hit is None:
            enriched.append(copy)
            continue
        if hit.start_probability is not None:
            copy["startProbability"] = hit.start_probability
            copy["p_titular"] = hit.start_probability
        copy["lineupStatus"] = hit.status
        copy["externalSource"] = hit.source
        if hit.links:
            copy["matchingConfidence"] = min(link.confidence for link in hit.links)
        enriched.append(copy)
    return enriched


def _status(*, ok: bool, count: int, error: str | None, from_cache: bool) -> dict:
    return {"ok": ok, "count": count, "error": error, "from_cache": from_cache}


def _get_text(client: ExternalClient, url: str, *, ttl: float, fresh: bool) -> tuple[str | None, bool, str | None]:
    try:
        body, cached = client.get_text(url, ttl=ttl, fresh=fresh)
    except ExternalHttpError as exc:
        if os.getenv("FANTASY_SCRAPER_BROWSER", "").strip() == "1" and exc.code in {"forbidden", "blocked"}:
            rendered = _render_with_browser(url)
            if rendered is not None:
                return rendered, False, None
        return None, False, str(exc)
    return body, cached, None


def _render_with_browser(url: str) -> str | None:
    """Solo con ``FANTASY_SCRAPER_BROWSER=1`` y un HTTP 403 o página de bloqueo."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                return page.content()
            finally:
                browser.close()
    except Exception:
        return None


def _load_source(
    client: ExternalClient,
    index_url: str,
    parse_index,
    parse_match,
    *,
    ttl: float,
    fresh: bool,
) -> tuple[dict, list[LineupPlayer]]:
    body, cached, error = _get_text(client, index_url, ttl=ttl, fresh=fresh)
    if error or body is None:
        return _status(ok=False, count=0, error=error or "Sin cuerpo.", from_cache=False), []
    urls = parse_index(body)
    rows: list[LineupPlayer] = []
    flags = [cached]
    errors: list[str] = []
    for url in urls:
        match_body, match_cached, match_error = _get_text(client, url, ttl=ttl, fresh=fresh)
        flags.append(match_cached)
        if match_error or match_body is None:
            errors.append(match_error or url)
            continue
        rows.extend(parse_match(match_body))
    if urls and not rows and errors:
        return _status(ok=False, count=0, error=errors[0], from_cache=False), []
    return (
        _status(
            ok=True,
            count=len(rows),
            error=errors[0] if errors else None,
            from_cache=all(flags),
        ),
        rows,
    )


def load_lineups(
    client: ExternalClient,
    *,
    ttl: float,
    fresh: bool,
) -> tuple[dict[str, dict], list[LineupPlayer]]:
    ff_status, ff_rows = _load_source(
        client,
        FF_LINEUPS_URL,
        parse_ff_fixture_urls,
        parse_ff_match,
        ttl=ttl,
        fresh=fresh,
    )
    af_status, af_rows = _load_source(
        client,
        AF_LINEUPS_URL,
        parse_af_fixture_urls,
        parse_af_match,
        ttl=ttl,
        fresh=fresh,
    )
    return {"futbolfantasy_lineups": ff_status, "analiticafantasy_lineups": af_status}, [*ff_rows, *af_rows]


class FantasyScraper:
    """Descarga los onces probables y los cruza con la plantilla de LaLiga Fantasy."""

    def __init__(
        self,
        client: ExternalClient | None = None,
        *,
        fresh: bool = False,
        ttl: float = 30 * 60,
    ) -> None:
        self._owns_client = client is None
        self.client = client or ExternalClient()
        self.fresh = fresh
        self.ttl = ttl
        self.last_sources: dict[str, dict] = {}

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> FantasyScraper:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_futbol_fantasy_data(self) -> dict:
        status, rows = _load_source(
            self.client,
            FF_LINEUPS_URL,
            parse_ff_fixture_urls,
            parse_ff_match,
            ttl=self.ttl,
            fresh=self.fresh,
        )
        self.last_sources["futbolfantasy_lineups"] = status
        return index_by_name(rows)

    def get_analitica_fantasy_data(self) -> dict:
        status, rows = _load_source(
            self.client,
            AF_LINEUPS_URL,
            parse_af_fixture_urls,
            parse_af_match,
            ttl=self.ttl,
            fresh=self.fresh,
        )
        self.last_sources["analiticafantasy_lineups"] = status
        return index_by_name(rows)

    def collect(self) -> list[LineupPlayer]:
        sources, rows = load_lineups(self.client, ttl=self.ttl, fresh=self.fresh)
        self.last_sources = sources
        return rows

    def enrich_player_list(self, local_players: list) -> list:
        return enrich_player_list(local_players, self.collect())

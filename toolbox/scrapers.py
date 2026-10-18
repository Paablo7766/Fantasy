"""Ingesta de Fútbol Fantasy, Sofascore, FBref y Transfermarkt.

Las páginas y los JSON pasan por ``ExternalClient``: caché en Supabase y, en
Transfermarkt, el tope de 2 peticiones cada 3 segundos. Un fallo de una fuente
no tira el cruce; queda anotado en ``sources`` y el documento sale parcial.

El bonus Relevo de 0 a 4 no se calcula aquí. Solo se guardan las métricas
(xG, xA, pases clave, duelos, despejes, paradas y nota) que sirven para proyectarlo.
"""

from __future__ import annotations

import html
import os
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from toolbox.cache import EntityStore
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
from toolbox.net import ExternalClient, ExternalHttpError, transfermarkt_api_base
from toolbox.normalize import SCHEMA_VERSION

FF_MARKET_URL = "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado"
FF_FITNESS_URL = "https://www.futbolfantasy.com/laliga/lesionados"
FF_SANCTIONS_URL = "https://www.futbolfantasy.com/laliga/sancionados"
FF_WARNINGS_URL = "https://www.futbolfantasy.com/laliga/apercibidos"
FBREF_URLS = (
    "https://fbref.com/en/comps/12/shooting/La-Liga-Stats",
    "https://fbref.com/en/comps/12/passing/La-Liga-Stats",
    "https://fbref.com/en/comps/12/defense/La-Liga-Stats",
    "https://fbref.com/en/comps/12/keepers/La-Liga-Stats",
)

RANK_LIMIT = 15
FORM_NOTE = (
    "Las métricas de forma alimentan el bonus Relevo de 0 a 4. "
    "Este documento no asigna ese bonus."
)
_FORM_KEYS = ("xg", "xa", "key_passes", "duels_won", "clearances", "saves", "average_rating")
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
    transfermarkt: float = 24 * 60 * 60

    @classmethod
    def from_env(cls) -> ScrapeTTL:
        return cls(
            market=_env_float("FANTASY_TTL_FUTBOLFANTASY_MARKET", 30 * 60),
            fitness=_env_float("FANTASY_TTL_FITNESS", 30 * 60),
            sanctions=_env_float("FANTASY_TTL_SANCTIONS", 6 * 60 * 60),
            stats=_env_float("FANTASY_TTL_STATS", 6 * 60 * 60),
            transfermarkt=_env_float("FANTASY_TTL_TRANSFERMARKT", 24 * 60 * 60),
        )


@dataclass
class IntelPlayer:
    name: str
    club: str | None = None
    position: str | None = None
    external_id: str | None = None
    p_titular: float | None = None
    price_delta: int | None = None
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


def _percent(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    if match is None:
        return None
    value = float(match.group(1).replace(",", "."))
    if value > 1:
        value /= 100.0
    if value < 0 or value > 1:
        return None
    return round(value, 4)


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
                setattr(line, target, number)
    return list(merged.values())


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
            by_id[player_id] = CanonicalPlayer(
                player_id=player_id,
                name=player.get("name") if isinstance(player.get("name"), str) else None,
                nickname=player.get("nickname") if isinstance(player.get("nickname"), str) else None,
                club=player.get("club") if isinstance(player.get("club"), str) else None,
                position=player.get("position") if isinstance(player.get("position"), str) else None,
                fantasy_price=price,
            )
    for listing in market.get("listings") or []:
        if not isinstance(listing, dict) or listing.get("player_id") is None:
            continue
        player_id = str(listing["player_id"])
        price = listing.get("market_value") if isinstance(listing.get("market_value"), int) else None
        sale = listing.get("sale_price") if isinstance(listing.get("sale_price"), int) else None
        current = by_id.get(player_id)
        if current is None:
            by_id[player_id] = CanonicalPlayer(
                player_id=player_id,
                name=listing.get("name") if isinstance(listing.get("name"), str) else None,
                nickname=listing.get("nickname") if isinstance(listing.get("nickname"), str) else None,
                club=listing.get("club") if isinstance(listing.get("club"), str) else None,
                position=listing.get("position") if isinstance(listing.get("position"), str) else None,
                fantasy_price=price if price is not None else sale,
                sale_price=sale,
                on_market=True,
            )
            continue
        by_id[player_id] = replace(
            current,
            sale_price=sale,
            on_market=True,
            fantasy_price=current.fantasy_price if current.fantasy_price is not None else price or sale,
        )
    return sorted(by_id.values(), key=lambda player: player.player_id)


def _fetch_text(client: ExternalClient, url: str, *, ttl: float, fresh: bool) -> tuple[str | None, bool, str | None]:
    try:
        body, cached = client.get_text(url, ttl=ttl, fresh=fresh)
    except ExternalHttpError as exc:
        return None, False, str(exc)
    return body, cached, None


def _fetch_json(client: ExternalClient, url: str, *, ttl: float, fresh: bool) -> tuple[Any, bool, str | None]:
    try:
        payload, cached = client.get_json(url, ttl=ttl, fresh=fresh)
    except ExternalHttpError as exc:
        return None, False, str(exc)
    return payload, cached, None


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


def _load_sofascore(client: ExternalClient, *, ttl: float, fresh: bool) -> _SourceFetch:
    url = os.getenv("SOFASCORE_STATS_URL", "").strip()
    if not url:
        return _SourceFetch(
            ok=False,
            error="SOFASCORE_STATS_URL no configurada. El parser queda listo para el JSON de estadísticas.",
        )
    payload, cached, error = _fetch_json(client, url, ttl=ttl, fresh=fresh)
    if error or payload is None:
        return _SourceFetch(ok=False, error=error or "Sin JSON de Sofascore.")
    rows = parse_sofascore_payload(payload)
    return _SourceFetch(ok=True, count=len(rows), from_cache=cached, rows=rows)


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


def _player_payload(
    player: CanonicalPlayer,
    *,
    intel: IntelPlayer | None,
    form: dict[str, Any],
    transfermarkt_value: int | None,
    confidence: float | None,
    matches: dict[str, Any],
) -> dict[str, Any]:
    price = player.fantasy_price
    gap = None
    ratio = None
    if transfermarkt_value is not None and isinstance(price, int) and price > 0:
        gap = transfermarkt_value - price
        ratio = round(transfermarkt_value / price, 4)
    sanction_cards = intel.yellow_cards if intel is not None else None
    return {
        "player_id": player.player_id,
        "name": player.name,
        "nickname": player.nickname,
        "club": player.club,
        "position": player.position,
        "on_market": player.on_market,
        "fantasy_price": price,
        "sale_price": player.sale_price,
        "price_delta": intel.price_delta if intel is not None else None,
        "price_direction": _direction(intel.price_delta if intel is not None else None),
        "acceleration": intel.acceleration if intel is not None else None,
        "flip_candidate": False,
        "transfermarkt_value_eur": transfermarkt_value,
        "gap_eur": gap,
        "value_ratio": ratio,
        "p_titular": intel.p_titular if intel is not None else None,
        "lineup_status": intel.lineup_status if intel is not None else None,
        "lineup_source": intel.lineup_source if intel is not None else None,
        "fitness": intel.fitness if intel is not None else None,
        "fitness_detail": intel.fitness_detail if intel is not None else None,
        "sanction": {
            "yellow_cards": sanction_cards,
            "on_verge": bool(intel and intel.on_verge),
            "suspended": bool(intel and intel.suspended),
        },
        "form": form,
        "matching_confidence": confidence,
        "matches": matches,
    }


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
) -> dict[str, Any]:
    owns_external = external is None
    client = external or ExternalClient()
    owns_store = store is None
    entity_store = store or EntityStore(client.root)
    clocks = ttl or ScrapeTTL.from_env()
    limit = _env_int("TRANSFERMARKT_LOOKUP_LIMIT", 24) if transfermarkt_limit is None else max(0, transfermarkt_limit)
    try:
        market = laliga.market_document(league, fresh=fresh)
        squads = laliga.squads_document(league, fresh=fresh)
        catalog = catalog_from_documents(market, squads)
        resolver = EntityResolver(entity_store)
        sources, intel_by_player, form_by_player, value_by_player, decisions = _cross(
            catalog,
            resolver,
            client,
            clocks,
            fresh=fresh,
            limit=limit,
        )
        players = _assemble(catalog, intel_by_player, form_by_player, value_by_player, decisions)
        rising, falling = _split_acceleration(players)
        undervalued = _undervalued(players)
        availability = _availability(players)
        linked = [item for item in decisions if item.linked]
        audits = resolver.audit()
        partial = bool(squads.get("partial")) or any(not source["ok"] for source in sources.values())
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "command": "trends",
            "league_id": market.get("league_id") or squads.get("league_id"),
            "league_name": market.get("league_name") or squads.get("league_name"),
            "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
            "partial": partial,
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
        if hit.fitness == "lesionado" or (hit.fitness and intel.fitness is None):
            intel.fitness = hit.fitness
        intel.lineup_status = hit.status
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
]:
    market_fetch = _load_page(client, FF_MARKET_URL, parse_market_board, ttl=clocks.market, fresh=fresh)
    fitness_fetch = _load_page(client, FF_FITNESS_URL, parse_fitness_board, ttl=clocks.fitness, fresh=fresh)
    sanctions_fetch = _load_page(client, FF_SANCTIONS_URL, parse_sanction_board, ttl=clocks.sanctions, fresh=fresh)
    warnings_fetch = _load_page(client, FF_WARNINGS_URL, parse_warning_board, ttl=clocks.sanctions, fresh=fresh)
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

    from toolbox.fantasy_scraper import load_lineups

    lineup_sources, sightings = load_lineups(client, ttl=clocks.market, fresh=fresh)
    _stamp_lineups(catalog, intel_by_player, sightings, ff_decisions)

    fbref_fetch = _load_fbref(client, ttl=clocks.stats, fresh=fresh)
    sofa_fetch = _load_sofascore(client, ttl=clocks.stats, fresh=fresh)
    form_by_player: dict[str, dict[str, Any]] = {}
    form_decisions: list[Any] = []
    for fetch, source in ((fbref_fetch, "fbref"), (sofa_fetch, "sofascore")):
        records = [
            ExternalRecord(
                source=source,
                name=line.name,
                external_id=line.external_id,
                club=line.club,
                position=line.position,
            )
            for line in fetch.rows
        ]
        decisions = resolver.link_source(catalog, records, source) if records else []
        form_decisions.extend(decisions)
        by_name = {normalize_name(line.name): line for line in fetch.rows}
        by_id = {line.external_id: line for line in fetch.rows if line.external_id}
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

    value_by_player, tm_fetch, tm_decisions = _load_transfermarkt(
        catalog,
        intel_by_player,
        resolver,
        client,
        ttl=clocks.transfermarkt,
        fresh=fresh,
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
        "transfermarkt": _status(tm_fetch),
    }
    return sources, intel_by_player, form_by_player, value_by_player, [*ff_decisions, *form_decisions, *tm_decisions]


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
) -> list[dict[str, Any]]:
    by_player: dict[str, list[Any]] = {}
    for decision in decisions:
        by_player.setdefault(decision.player_id, []).append(decision)
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
        payloads.append(
            _player_payload(
                player,
                intel=intel_by_player.get(player.player_id),
                form=form_by_player.get(player.player_id, _blank_form()),
                transfermarkt_value=value_by_player.get(player.player_id),
                confidence=confidence,
                matches=matches,
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
        player["flip_candidate"] = player["player_id"] in flagged
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

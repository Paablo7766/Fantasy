"""Menciones de DonQui, onces de El Bielsa y notas pegadas (Azteca).

No se lee X/Twitter. Un nombre solo se enlaza al catálogo de la liga si la
similitud es al menos 0,85 y no hay otro candidato pegado. No se inventan
puntos ni bonus Relevo.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from toolbox.matching import name_similarity

DONQUI_URL = "https://www.analiticafantasy.com/donqui"
AF_LINEUPS_URL = "https://www.analiticafantasy.com/alineaciones-probables"
BIELSA_INDEX_URL = "https://www.predicted11.com/es/laliga"
EXPERT_TTL_SECONDS = 6 * 60 * 60
MATCH_FLOOR = 0.85

_PLAYER_HREF = re.compile(
    r'href="(?:https://www\.analiticafantasy\.com)?(/jugadores/[^"#?]+)"[^>]*>([^<]{2,80})<',
    re.I,
)
_BIELSA_BLOCK = re.compile(
    r"Alineación probable del (.+?) según ElBielsaFantasy(.*?)(?=Alineación probable del |\Z)",
    re.I | re.S,
)
_LI = re.compile(r"<li[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,48})")
_NUM = re.compile(r"(?:^|\n)\s*\d+\.\s*([^\n<]{2,48})")
_ARTICLE = re.compile(r'href="(https://www\.predicted11\.com/es/laliga/noticias/[^"]*bielsa[^"]*)"', re.I)
_FADE = ("red flag", "evitar", "prohib", "no recomend", "fade", "bufon")
_BOOST = ("chollo", "apuesta", "recomend", "top ", "fijo", "imprescindible")


def _fold(text: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", text)).lower()


def _clean_name(raw: str) -> str | None:
    text = unescape(re.sub(r"\s+", " ", raw)).strip(" \t\r\n.:;-")
    if len(text) < 3 or len(text) > 48:
        return None
    if text.lower() in {"principal", "suplente", "lesionado"}:
        return None
    return text


def parse_donqui_mentions(page: str) -> list[dict[str, Any]]:
    """Nombres junto a un enlace de jugador. El tipo sale de las palabras del alrededor."""
    if not isinstance(page, str) or not page:
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _PLAYER_HREF.finditer(page):
        name = _clean_name(match.group(2))
        if name is None:
            continue
        window = _fold(page[max(0, match.start() - 220) : min(len(page), match.end() + 220)])
        kind = "probable"
        if any(token in window for token in _FADE):
            kind = "fade"
        elif any(token in window for token in _BOOST):
            kind = "boost"
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append({"name": name, "kind": kind, "source": "donqui"})
    return found


def parse_bielsa_lineups(page: str) -> list[dict[str, Any]]:
    """Onces numerados o en lista, agrupados por club, como los publica Predicted11."""
    if not isinstance(page, str) or not page:
        return []
    blocks = list(_BIELSA_BLOCK.finditer(page))
    if not blocks:
        return []
    lineups: list[dict[str, Any]] = []
    for match in blocks:
        club = _clean_name(re.sub(r"<[^>]+>", " ", match.group(1)))
        body = match.group(2)
        names: list[str] = []
        for raw in _LI.findall(body) or _NUM.findall(body):
            name = _clean_name(raw)
            if name is None:
                continue
            names.append(name)
            if len(names) == 11:
                break
        if club and names:
            lineups.append({"club": club, "players": names, "source": "bielsa"})
    return lineups


def parse_predicted11_article_urls(page: str) -> list[str]:
    if not isinstance(page, str):
        return []
    urls: list[str] = []
    for match in _ARTICLE.finditer(page):
        url = match.group(1)
        if url not in urls:
            urls.append(url)
        if len(urls) == 2:
            break
    return urls


def link_mentions(rows: list[dict[str, Any]], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enlaza cada nombre si un solo jugador del catálogo supera 0,85."""
    linked: list[dict[str, Any]] = []
    players = [row for row in catalog if isinstance(row, dict)]
    for row in rows:
        name = row.get("name") if isinstance(row.get("name"), str) else None
        if not name:
            continue
        best: dict[str, Any] | None = None
        best_score = 0.0
        second = 0.0
        for player in players:
            score = max(
                name_similarity(name, player.get("name") if isinstance(player.get("name"), str) else None),
                name_similarity(name, player.get("nickname") if isinstance(player.get("nickname"), str) else None),
            )
            if score > best_score:
                second = best_score
                best_score = score
                best = player
            elif score > second:
                second = score
        if best is None or best_score < MATCH_FLOOR or best_score - second < 0.03:
            continue
        player_id = best.get("player_id") if isinstance(best.get("player_id"), str) else None
        if not player_id:
            continue
        linked.append(
            {
                "player_id": player_id,
                "name": best.get("name") or name,
                "nickname": best.get("nickname"),
                "club": best.get("club"),
                "position": best.get("position"),
                "mention": name,
                "kind": row.get("kind") or "probable",
                "source": row.get("source") or "nota",
                "confidence": round(best_score, 4),
            }
        )
    return linked


def mentions_from_text(text: str, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nota pegada (Azteca u otra). Sin texto no hay señal."""
    if not isinstance(text, str) or not text.strip():
        return []
    raw_names: list[dict[str, Any]] = []
    seen: set[str] = set()
    for player in catalog:
        if not isinstance(player, dict):
            continue
        for key in ("nickname", "name"):
            label = player.get(key)
            if not isinstance(label, str) or len(label.strip()) < 4:
                continue
            if label.casefold() in seen:
                continue
            if re.search(rf"(?i)(?<!\w){re.escape(label.strip())}(?!\w)", text):
                seen.add(label.casefold())
                window_match = re.search(rf"(?i).{{0,80}}{re.escape(label.strip())}.{{0,80}}", text)
                window = (window_match.group(0) if window_match else text).lower()
                kind = "note"
                if any(token in window for token in _FADE):
                    kind = "fade"
                elif any(token in window for token in _BOOST):
                    kind = "boost"
                raw_names.append({"name": label.strip(), "kind": kind, "source": "azteca"})
                break
    return link_mentions(raw_names, catalog)


def lineup_agreement(
    *,
    ff: bool | None,
    af: bool | None,
    bielsa: bool | None,
) -> str | None:
    """``unanimous`` si todas las fuentes que publicaron once lo incluyen.

    ``None`` en una fuente significa que esa fuente no publicó once de ese
    club: no cuenta como voto. Con menos de dos votos no hay acuerdo.
    """
    known = [value for value in (ff, af, bielsa) if value is not None]
    if len(known) < 2:
        return None
    if all(known):
        return "unanimous"
    if any(known) and not all(known):
        return "split"
    return None


def agreement_for_trends(
    players: list[dict[str, Any]],
    bielsa_ids: set[str],
    *,
    bielsa_clubs: set[str],
) -> dict[str, str]:
    """Compara el once ya scrapeado (FF/AF) con los nombres de Bielsa enlazados."""
    from toolbox.matching import normalize_club

    clubs = {normalize_club(club) for club in bielsa_clubs if club}
    notes: dict[str, str] = {}
    if not clubs or not bielsa_ids:
        return notes
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else None
        club = normalize_club(player.get("club") if isinstance(player.get("club"), str) else None)
        if player_id is None or club not in clubs:
            continue
        source = player.get("lineup_source") if isinstance(player.get("lineup_source"), str) else ""
        probability = player.get("p_titular")
        probable = isinstance(probability, (int, float)) and not isinstance(probability, bool) and float(probability) >= 0.5
        ff: bool | None = None
        af: bool | None = None
        if "futbolfantasy" in source:
            ff = probable
        if "analitica" in source:
            af = probable
        bielsa: bool | None = player_id in bielsa_ids
        label = lineup_agreement(ff=ff, af=af, bielsa=bielsa)
        if label:
            notes[player_id] = label
    return notes


def load_expert_pages(client: Any, *, fresh: bool = False) -> dict[str, Any]:
    """Descarga DonQui y, si el índice de Predicted11 enlaza un artículo, el once de Bielsa."""
    sources: dict[str, Any] = {}
    mentions: list[dict[str, Any]] = []
    lineups: list[dict[str, Any]] = []

    def _fetch(url: str) -> tuple[str | None, str | None, bool]:
        try:
            body, cached = client.get_text(url, ttl=EXPERT_TTL_SECONDS, fresh=fresh)
        except Exception as exc:  # noqa: BLE001 — una fuente caída no inventa nombres
            return None, str(exc), False
        if not isinstance(body, str):
            return None, "respuesta_vacia", False
        return body, None, cached

    for key, url in (("donqui", DONQUI_URL), ("af_lineups", AF_LINEUPS_URL)):
        body, error, cached = _fetch(url)
        rows = parse_donqui_mentions(body or "")
        mentions.extend(rows)
        sources[key] = {"ok": error is None, "count": len(rows), "error": error, "from_cache": cached, "url": url}

    index, index_error, index_cached = _fetch(BIELSA_INDEX_URL)
    article_urls = parse_predicted11_article_urls(index or "")
    bielsa_error = index_error
    bielsa_count = 0
    fetched_article = False
    for url in article_urls:
        body, error, _cached = _fetch(url)
        fetched_article = True
        if error and bielsa_error is None:
            bielsa_error = error
        parsed = parse_bielsa_lineups(body or "")
        lineups.extend(parsed)
        bielsa_count += len(parsed)
    if not fetched_article and index:
        parsed = parse_bielsa_lineups(index)
        lineups.extend(parsed)
        bielsa_count += len(parsed)
    sources["bielsa"] = {
        "ok": bielsa_error is None,
        "count": bielsa_count,
        "error": bielsa_error,
        "from_cache": index_cached,
        "url": article_urls[0] if article_urls else BIELSA_INDEX_URL,
    }
    return {"mentions": mentions, "lineups": lineups, "sources": sources}

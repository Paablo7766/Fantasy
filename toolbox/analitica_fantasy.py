"""Señales de Analítica Fantasy: mercado, puja, predicción, puntos, bajas y extras.

Las páginas Next.js embeben JSON en el vuelo RSC (a veces escapado). Un fallo de
una fuente no inventa cifras: el status queda en ``sources`` y el jugador local
sigue sin ese campo.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from toolbox.fantasy_scraper import _json_after, _unescape_js
from toolbox.matching import (
    CanonicalPlayer,
    EntityResolver,
    ExternalRecord,
    canonical_position,
    normalize_club,
    normalize_name,
)
from toolbox.net import ExternalClient, ExternalHttpError, inherited

AF_MARKET_URL = "https://www.analiticafantasy.com/fantasy-la-liga/mercado"
AF_PREDICTION_URL = "https://www.analiticafantasy.com/fantasy-la-liga/prediccion-de-mercado"
AF_IDEAL_BID_URL = "https://www.analiticafantasy.com/fantasy-la-liga/puja-ideal"
AF_POINTS_URL = "https://www.analiticafantasy.com/fantasy-la-liga/predicciones"
AF_INJURED_URL = "https://www.analiticafantasy.com/la-liga/jugadores-lesionados"
AF_SUSPENDED_URL = "https://www.analiticafantasy.com/la-liga/jugadores-sancionados"
AF_ORACLE_URL = "https://www.analiticafantasy.com/oraculo-fantasy/la-liga"
AF_CALENDAR_URL = "https://www.analiticafantasy.com/la-liga/calendario-predictor"
AF_SETPIECE_URL = "https://www.analiticafantasy.com/la-liga/balon-parado"
AF_FORM_URL = "https://www.analiticafantasy.com/fantasy/la-liga-fantasy/jugadores-en-forma"
AF_FORM_JORNADA_URL = "https://www.analiticafantasy.com/fantasy/la-liga-fantasy/jugadores-en-forma/jornada-{n}"

# Mercado / puja usan 1=POR … 4=DEL.
_AF_POS = {1: "POR", 2: "DEF", 3: "MC", 4: "DEL"}
_LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S | re.I)
_MATCHDAY = re.compile(
    r'\\"matchday\\":(\d+),\\"round\\":\\"([^\\]*)\\",\\"fixtureId\\":(\d+),'
    r'\\"fixtureDate\\":\\"([^\\]*)\\",\\"opponentId\\":(\d+),\\"opponentName\\":\\"([^\\]*)\\",'
    r'\\"isHome\\":(true|false),\\"predictedScore\\":\\"([^\\]*)\\",'
    r'\\"predictedHome\\":(\d+),\\"predictedAway\\":(\d+),'
    r'\\"winProb\\":([0-9.]+),\\"drawProb\\":([0-9.]+),\\"lossProb\\":([0-9.]+),'
    r'\\"recommendationPct\\":(\d+),\\"difficulty\\":\\"([^\\]*)\\"'
)
_TEAM_WRAP = re.compile(r'\\"teamId\\":(\d+),\\"teamName\\":\\"([^\\]+)\\"')
_FORM_CARD = re.compile(
    r'href="/jugadores/([^"/]+)/fantasy/[^"]+"[^>]*>.*?'
    r"<h3[^>]*>([^<]+)</h3>.*?"
    r"Media reciente[^0-9]*([0-9]+(?:[.,][0-9]+)?).*?"
    r">(\d+)\s*<!--\s*-->\s*señales",
    re.S | re.I,
)
_FORM_TITLE = re.compile(r'title="([^"]+)"')
_SETPIECE_BLOCK = re.compile(
    r"(Directas|Indirectas|Córners|Penaltis)</[^>]+>.*?"
    r"Principal(?:#(\d+))?</[^>]+>.*?>\s*([A-Za-zÀ-ÿ0-9 .'\-]+)\s*<",
    re.S,
)


@dataclass
class AfMarketRow:
    name: str
    club: str | None = None
    position: str | None = None
    external_id: str | None = None
    market_value: int | None = None
    price_delta: int | None = None
    p_titular: float | None = None


@dataclass
class AfBidRow:
    name: str
    club: str | None = None
    position: str | None = None
    external_id: str | None = None
    market_value: int | None = None
    ideal_bid: int | None = None
    max_bid: int | None = None
    price_delta: int | None = None
    expected_points: float | None = None
    p_titular: float | None = None


@dataclass
class AfPredictionRow:
    name: str
    club: str | None = None
    external_id: str | None = None
    market_value: int | None = None
    predicted_delta: int | None = None
    signal_strength: float | None = None
    direction: str | None = None  # up | down


@dataclass
class AfPointsRow:
    name: str
    club: str | None = None
    position: str | None = None
    external_id: str | None = None
    predicted_points: float | None = None
    ceiling_points: float | None = None
    p_titular: float | None = None
    goal_probability: float | None = None
    assist_probability: float | None = None
    points_per_million: float | None = None
    market_value: int | None = None
    expected_points: float | None = None


@dataclass
class AfStatusRow:
    name: str
    club: str | None = None
    external_id: str | None = None
    status: str | None = None
    status_info: str | None = None
    report: str | None = None
    injury_start: str | None = None
    expected_return: str | None = None
    is_sanctioned: bool = False


@dataclass
class AfFormRow:
    name: str
    external_id: str | None = None
    recent_average: float | None = None
    signal_count: int | None = None
    signals: tuple[str, ...] = ()


@dataclass
class AfSetPieceRow:
    name: str
    club: str | None = None
    role: str | None = None  # penalties | corners | direct | indirect
    shirt: int | None = None


@dataclass
class AfCalendarCell:
    team_id: str
    team_name: str
    matchday: int
    opponent: str
    is_home: bool
    predicted_score: str
    recommendation_pct: int
    difficulty: str
    win_prob: float
    draw_prob: float
    loss_prob: float


@dataclass
class AfBundle:
    market: list[AfMarketRow] = field(default_factory=list)
    bids: list[AfBidRow] = field(default_factory=list)
    predictions: list[AfPredictionRow] = field(default_factory=list)
    points: list[AfPointsRow] = field(default_factory=list)
    injured: list[AfStatusRow] = field(default_factory=list)
    suspended: list[AfStatusRow] = field(default_factory=list)
    form: list[AfFormRow] = field(default_factory=list)
    set_pieces: list[AfSetPieceRow] = field(default_factory=list)
    calendar: list[AfCalendarCell] = field(default_factory=list)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value:
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d-]", "", value)
        if digits in {"", "-", "-0"}:
            return None
        try:
            return int(digits)
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number
    if isinstance(value, str):
        try:
            return float(value.replace(",", ".").strip())
        except ValueError:
            return None
    return None


def _chance(value: Any) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    if number > 1:
        number /= 100.0
    if number < 0 or number > 1:
        return None
    return round(number, 4)


def _position(value: Any) -> str | None:
    if isinstance(value, int):
        return canonical_position(_AF_POS.get(value))
    if isinstance(value, str):
        return canonical_position(value)
    return None


def _decode_list(page: str, markers: tuple[str, ...]) -> list[Any]:
    for marker in markers:
        payload = _json_after(page, marker)
        if isinstance(payload, list):
            return payload
        unescaped = _unescape_js(page)
        payload = _json_after(unescaped, marker.replace('\\"', '"'))
        if isinstance(payload, list):
            return payload
    return []


def _club_name(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        name = raw.get("name") or raw.get("teamName")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def parse_market_players(page: str) -> list[AfMarketRow]:
    rows: list[AfMarketRow] = []
    for raw in _decode_list(page, ('"initialPlayers":', '\\"initialPlayers\\":')):
        if not isinstance(raw, dict):
            continue
        name = raw.get("nickname") or raw.get("name") or raw.get("playerName")
        if not isinstance(name, str) or not name.strip():
            continue
        external = raw.get("masterPlayerId") or raw.get("playerId") or raw.get("id")
        rows.append(
            AfMarketRow(
                name=name.strip(),
                club=_club_name(raw.get("teamName") or raw.get("club")),
                position=_position(raw.get("positionId") or raw.get("position")),
                external_id=str(external) if external is not None else None,
                market_value=_as_int(raw.get("marketValue")),
                price_delta=_as_int(raw.get("subida")),
                p_titular=_chance(raw.get("titularityPercent") or raw.get("chance")),
            )
        )
    return rows


def parse_ideal_bids(page: str) -> list[AfBidRow]:
    rows: list[AfBidRow] = []
    for raw in _decode_list(page, ('"initialPlayers":', '\\"initialPlayers\\":')):
        if not isinstance(raw, dict):
            continue
        name = raw.get("name") or raw.get("nickname") or raw.get("playerName")
        if not isinstance(name, str) or not name.strip():
            continue
        club = _club_name(raw.get("club") or raw.get("teamName"))
        external = raw.get("id") or raw.get("masterPlayerId") or raw.get("playerId")
        rows.append(
            AfBidRow(
                name=name.strip(),
                club=club,
                position=_position(raw.get("positionId") or raw.get("position")),
                external_id=str(external) if external is not None else None,
                market_value=_as_int(raw.get("marketValue")),
                ideal_bid=_as_int(raw.get("pujaIdeal")),
                max_bid=_as_int(raw.get("pujaMaxima")),
                price_delta=_as_int(raw.get("subida")),
                expected_points=_as_float(raw.get("expectedPoints")),
                p_titular=_chance(raw.get("chance") or raw.get("titularityPercent")),
            )
        )
    return rows


def _ld_blocks(page: str) -> list[Any]:
    blocks: list[Any] = []
    for match in _LD_JSON.finditer(page):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            blocks.extend(payload)
        else:
            blocks.append(payload)
    return blocks


def _ld_props(item: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    extra = item.get("additionalProperty")
    if not isinstance(extra, list):
        return props
    for entry in extra:
        if not isinstance(entry, dict):
            continue
        key = entry.get("name")
        if isinstance(key, str) and key.strip():
            props[key.strip()] = entry.get("value")
    return props


def parse_market_predictions(page: str) -> list[AfPredictionRow]:
    rows: list[AfPredictionRow] = []
    for block in _ld_blocks(page):
        if not isinstance(block, dict) or block.get("@type") != "ItemList":
            continue
        name = str(block.get("name") or "")
        direction = "up" if "subida" in name.lower() else "down" if "bajada" in name.lower() else None
        elements = block.get("itemListElement")
        if not isinstance(elements, list):
            continue
        for entry in elements:
            if not isinstance(entry, dict):
                continue
            person = entry.get("item") if isinstance(entry.get("item"), dict) else entry
            if not isinstance(person, dict):
                continue
            player_name = person.get("name")
            if not isinstance(player_name, str) or not player_name.strip():
                continue
            props = _ld_props(person)
            strength = _as_float(props.get("Probabilidad"))
            if strength is not None and strength > 1:
                strength = strength / 100.0
            rows.append(
                AfPredictionRow(
                    name=player_name.strip(),
                    market_value=_as_int(props.get("Valor de mercado")),
                    predicted_delta=_as_int(props.get("Subida diaria")),
                    signal_strength=round(strength, 4) if strength is not None else None,
                    direction=direction,
                    external_id=None,
                    club=None,
                )
            )
    return rows


def parse_points_predictions(page: str) -> list[AfPointsRow]:
    rows: list[AfPointsRow] = []
    seen: set[str] = set()
    for raw in _decode_list(page, ('"players":', '\\"players\\":')):
        if not isinstance(raw, dict):
            continue
        name = raw.get("playerName") or raw.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        external = raw.get("playerId") or raw.get("id")
        key = str(external) if external is not None else normalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        team_id = raw.get("playerTeamId") or raw.get("teamId")
        club = raw.get("awayTeamName") if team_id == raw.get("awayTeamId") else raw.get("homeTeamName")
        if not isinstance(club, str):
            club = _club_name(raw.get("teamName"))
        rows.append(
            AfPointsRow(
                name=name.strip(),
                club=club if isinstance(club, str) else None,
                position=_position(raw.get("positionId") or raw.get("position")),
                external_id=str(external) if external is not None else None,
                predicted_points=_as_float(raw.get("predictedPoints")),
                ceiling_points=_as_float(raw.get("ceilingPoints")),
                p_titular=_chance(raw.get("chance")),
                goal_probability=_as_float(raw.get("goalProbability")),
                assist_probability=_as_float(raw.get("assistProbability")),
                points_per_million=_as_float(raw.get("pointsPerMillion")),
                market_value=_as_int(raw.get("marketValue")),
                expected_points=_as_float(raw.get("expectedPoints")),
            )
        )
    return rows


def parse_oracle_players(page: str) -> list[AfPointsRow]:
    """Recoge objetos con predictedPoints (tops, chollos, caps) sin inventar."""
    rows: list[AfPointsRow] = []
    seen: set[str] = set()
    unescaped = _unescape_js(page) if '\\"' in page else page
    needle = '"predictedPoints":'
    start = 0
    while True:
        idx = unescaped.find(needle, start)
        if idx < 0:
            break
        brace = unescaped.rfind("{", max(0, idx - 700), idx)
        start = idx + len(needle)
        if brace < 0:
            continue
        try:
            raw, _end = json.JSONDecoder().raw_decode(unescaped[brace:])
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        name = raw.get("playerName") or raw.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if raw.get("predictedPoints") is None:
            continue
        external = raw.get("playerId") or raw.get("id")
        key = str(external) if external is not None else normalize_name(name)
        if key in seen:
            # merge richer fields
            for row in rows:
                if (row.external_id and row.external_id == str(external)) or normalize_name(row.name) == normalize_name(
                    name
                ):
                    if row.goal_probability is None:
                        row.goal_probability = _as_float(raw.get("goalProbability"))
                    if row.assist_probability is None:
                        row.assist_probability = _as_float(raw.get("assistProbability"))
                    if row.points_per_million is None:
                        row.points_per_million = _as_float(raw.get("pointsPerMillion"))
                    if row.expected_points is None:
                        row.expected_points = _as_float(raw.get("expectedPoints"))
                    if row.market_value is None:
                        row.market_value = _as_int(raw.get("marketValue"))
                    break
            continue
        seen.add(key)
        rows.append(
            AfPointsRow(
                name=name.strip(),
                club=_club_name(raw.get("teamName")),
                position=_position(raw.get("positionId") or raw.get("position")),
                external_id=str(external) if external is not None else None,
                predicted_points=_as_float(raw.get("predictedPoints")),
                ceiling_points=_as_float(raw.get("ceilingPoints")),
                p_titular=_chance(raw.get("chance")),
                goal_probability=_as_float(raw.get("goalProbability")),
                assist_probability=_as_float(raw.get("assistProbability")),
                points_per_million=_as_float(raw.get("pointsPerMillion")),
                market_value=_as_int(raw.get("marketValue")),
                expected_points=_as_float(raw.get("expectedPoints")),
            )
        )
    return rows


def parse_status_players(page: str) -> list[AfStatusRow]:
    rows: list[AfStatusRow] = []
    for raw in _decode_list(page, ('"initialPlayers":', '\\"initialPlayers\\":', '"players":')):
        if not isinstance(raw, dict):
            continue
        name = raw.get("playerName") or raw.get("name") or raw.get("nickname")
        if not isinstance(name, str) or not name.strip():
            continue
        external = raw.get("playerId") or raw.get("id") or raw.get("masterPlayerId")
        rows.append(
            AfStatusRow(
                name=name.strip(),
                club=_club_name(raw.get("teamName")),
                external_id=str(external) if external is not None else None,
                status=str(raw.get("status")).strip() if isinstance(raw.get("status"), str) else None,
                status_info=str(raw["statusInfo"]).strip() if isinstance(raw.get("statusInfo"), str) else None,
                report=str(raw["report"]).strip() if isinstance(raw.get("report"), str) else None,
                injury_start=str(raw["injuryStartDate"]) if isinstance(raw.get("injuryStartDate"), str) else None,
                expected_return=str(raw["expectedReturnDate"])
                if isinstance(raw.get("expectedReturnDate"), str)
                else None,
                is_sanctioned=bool(raw.get("isSanctioned"))
                or (isinstance(raw.get("status"), str) and "sanction" in raw["status"].lower()),
            )
        )
    return rows


def parse_form_players(page: str) -> list[AfFormRow]:
    rows: list[AfFormRow] = []
    for slug, name, average, count in _FORM_CARD.findall(page):
        external = None
        if "-" in slug:
            tail = slug.rsplit("-", 1)[-1]
            if tail.isdigit():
                external = tail
        titles = _FORM_TITLE.findall(page[page.find(name) : page.find(name) + 2500]) if name in page else []
        rows.append(
            AfFormRow(
                name=name.strip(),
                external_id=external,
                recent_average=_as_float(average),
                signal_count=_as_int(count),
                signals=tuple(titles[:8]),
            )
        )
    return rows


def parse_set_pieces(page: str) -> list[AfSetPieceRow]:
    role_map = {
        "Directas": "direct",
        "Indirectas": "indirect",
        "Córners": "corners",
        "Penaltis": "penalties",
    }
    rows: list[AfSetPieceRow] = []
    for label, shirt, name in _SETPIECE_BLOCK.findall(page):
        role = role_map.get(label)
        if not role or not name.strip():
            continue
        rows.append(
            AfSetPieceRow(
                name=name.strip(),
                role=role,
                shirt=_as_int(shirt) if shirt else None,
            )
        )
    return rows


def parse_calendar(page: str) -> list[AfCalendarCell]:
    cells: list[AfCalendarCell] = []
    # Pair each matchday blob with the nearest following team wrapper in the RSC tree.
    for match in _MATCHDAY.finditer(page):
        end = match.end()
        team = _TEAM_WRAP.search(page, end, end + 200)
        if team is None:
            # try before
            window = page[max(0, match.start() - 120) : match.start()]
            prior = list(_TEAM_WRAP.finditer(window))
            if not prior:
                continue
            team_id, team_name = prior[-1].groups()
        else:
            team_id, team_name = team.groups()
        (
            matchday,
            _round,
            _fixture_id,
            _date,
            _opp_id,
            opponent,
            is_home,
            score,
            _ph,
            _pa,
            win,
            draw,
            loss,
            rec,
            difficulty,
        ) = match.groups()
        cells.append(
            AfCalendarCell(
                team_id=team_id,
                team_name=team_name,
                matchday=int(matchday),
                opponent=opponent,
                is_home=is_home == "true",
                predicted_score=score,
                recommendation_pct=int(rec),
                difficulty=difficulty,
                win_prob=float(win),
                draw_prob=float(draw),
                loss_prob=float(loss),
            )
        )
    return cells


def _fetch(
    client: ExternalClient,
    url: str,
    parser: Callable[[str], list[Any]],
    *,
    ttl: float,
    fresh: bool,
) -> tuple[dict[str, Any], list[Any]]:
    try:
        body, cached = client.get_text(url, ttl=ttl, fresh=fresh)
    except (ExternalHttpError, OSError, TimeoutError) as exc:
        return {"ok": False, "count": 0, "error": str(exc), "from_cache": False}, []
    except Exception as exc:  # noqa: BLE001 — una página AF no tumba trends
        return {"ok": False, "count": 0, "error": str(exc), "from_cache": False}, []
    try:
        rows = parser(body)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "count": 0, "error": f"parse: {exc}", "from_cache": cached}, []
    return {"ok": True, "count": len(rows), "error": None, "from_cache": cached}, rows


def _future_result(future: Any) -> tuple[dict[str, Any], list[Any]]:
    try:
        return future.result()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "count": 0, "error": str(exc), "from_cache": False}, []


def load_analitica_fantasy(
    client: ExternalClient,
    *,
    ttl: float,
    fresh: bool = False,
) -> AfBundle:
    """Carga en paralelo las páginas AF usadas por trends."""
    bundle = AfBundle()
    # Pocos workers: el caché local en Windows no tolera bien 8 writes a la vez.
    with ThreadPoolExecutor(max_workers=3) as pool:
        market_f = pool.submit(inherited(_fetch), client, AF_MARKET_URL, parse_market_players, ttl=ttl, fresh=fresh)
        bid_f = pool.submit(inherited(_fetch), client, AF_IDEAL_BID_URL, parse_ideal_bids, ttl=ttl, fresh=fresh)
        pred_f = pool.submit(inherited(_fetch), client, AF_PREDICTION_URL, parse_market_predictions, ttl=ttl, fresh=fresh)
        pts_f = pool.submit(inherited(_fetch), client, AF_POINTS_URL, parse_points_predictions, ttl=ttl, fresh=fresh)
        inj_f = pool.submit(inherited(_fetch), client, AF_INJURED_URL, parse_status_players, ttl=ttl, fresh=fresh)
        sus_f = pool.submit(inherited(_fetch), client, AF_SUSPENDED_URL, parse_status_players, ttl=ttl, fresh=fresh)
        ora_f = pool.submit(inherited(_fetch), client, AF_ORACLE_URL, parse_oracle_players, ttl=ttl, fresh=fresh)
        cal_f = pool.submit(inherited(_fetch), client, AF_CALENDAR_URL, parse_calendar, ttl=ttl, fresh=fresh)
        set_f = pool.submit(inherited(_fetch), client, AF_SETPIECE_URL, parse_set_pieces, ttl=ttl, fresh=fresh)
        market_s, market_rows = _future_result(market_f)
        bid_s, bid_rows = _future_result(bid_f)
        pred_s, pred_rows = _future_result(pred_f)
        pts_s, pts_rows = _future_result(pts_f)
        inj_s, inj_rows = _future_result(inj_f)
        sus_s, sus_rows = _future_result(sus_f)
        ora_s, ora_rows = _future_result(ora_f)
        cal_s, cal_rows = _future_result(cal_f)
        set_s, set_rows = _future_result(set_f)

    form_s, form_rows = _fetch(client, AF_FORM_URL, parse_form_players, ttl=ttl, fresh=fresh)
    if not form_rows:
        # La ruta viva suele llevar /jornada-N; si el índice está vacío, prueba la última del calendario.
        matchdays = [cell.matchday for cell in cal_rows]
        guess = max(matchdays) if matchdays else 8
        for jornada in (guess, max(1, guess - 1), guess + 1):
            form_s, form_rows = _fetch(
                client,
                AF_FORM_JORNADA_URL.format(n=jornada),
                parse_form_players,
                ttl=ttl,
                fresh=fresh,
            )
            if form_rows:
                break

    bundle.market = list(market_rows)
    bundle.bids = list(bid_rows)
    bundle.predictions = list(pred_rows)
    # Prefer dedicated points page; fill gaps from oracle objects.
    by_id = {row.external_id: row for row in pts_rows if row.external_id}
    by_name = {normalize_name(row.name): row for row in pts_rows}
    for row in ora_rows:
        current = by_id.get(row.external_id or "") if row.external_id else None
        if current is None:
            current = by_name.get(normalize_name(row.name))
        if current is None:
            pts_rows.append(row)
            continue
        if current.goal_probability is None:
            current.goal_probability = row.goal_probability
        if current.assist_probability is None:
            current.assist_probability = row.assist_probability
        if current.points_per_million is None:
            current.points_per_million = row.points_per_million
        if current.expected_points is None:
            current.expected_points = row.expected_points
    bundle.points = list(pts_rows)
    bundle.injured = list(inj_rows)
    bundle.suspended = list(sus_rows)
    bundle.form = list(form_rows)
    bundle.set_pieces = list(set_rows)
    bundle.calendar = list(cal_rows)
    bundle.sources = {
        "analiticafantasy_market": market_s,
        "analiticafantasy_prediction": pred_s,
        "analiticafantasy_ideal_bid": bid_s,
        "analiticafantasy_points": pts_s,
        "analiticafantasy_oracle": ora_s,
        "analiticafantasy_injured": inj_s,
        "analiticafantasy_suspended": sus_s,
        "analiticafantasy_form": form_s,
        "analiticafantasy_set_pieces": set_s,
        "analiticafantasy_calendar": cal_s,
    }
    return bundle


def _link_rows(
    catalog: list[CanonicalPlayer],
    resolver: EntityResolver,
    rows: list[Any],
    source: str,
    *,
    name_attr: str = "name",
    id_attr: str = "external_id",
    club_attr: str = "club",
    position_attr: str = "position",
) -> tuple[dict[str, Any], list[Any]]:
    if not rows:
        return {}, []
    records = []
    index: dict[str, Any] = {}
    for row in rows:
        name = getattr(row, name_attr, None)
        if not isinstance(name, str) or not name.strip():
            continue
        external_id = getattr(row, id_attr, None)
        club = getattr(row, club_attr, None) if hasattr(row, club_attr) else None
        position = getattr(row, position_attr, None) if hasattr(row, position_attr) else None
        record = ExternalRecord(
            source=source,
            name=name,
            external_id=str(external_id) if external_id is not None else None,
            club=club if isinstance(club, str) else None,
            position=position if isinstance(position, str) else None,
        )
        records.append(record)
        if record.external_id:
            index["id:" + record.external_id] = row
        index["name:" + normalize_name(name)] = row
    decisions = resolver.link_source(catalog, records, source)
    linked: dict[str, Any] = {}
    for decision in decisions:
        if not decision.linked:
            continue
        row = None
        if decision.external_id:
            row = index.get("id:" + decision.external_id)
        if row is None:
            row = index.get("name:" + normalize_name(decision.external_name))
        if row is not None:
            linked[decision.player_id] = row
    return linked, decisions


def apply_analitica_fantasy(
    catalog: list[CanonicalPlayer],
    resolver: EntityResolver,
    bundle: AfBundle,
    players: list[dict[str, Any]],
) -> tuple[list[Any], dict[str, Any]]:
    """Enriquece los payloads de trends y devuelve decisions + resumen AF."""
    market_map, d1 = _link_rows(catalog, resolver, bundle.market, "analiticafantasy_market")
    bid_map, d2 = _link_rows(catalog, resolver, bundle.bids, "analiticafantasy_ideal_bid")
    pred_map, d3 = _link_rows(catalog, resolver, bundle.predictions, "analiticafantasy_prediction")
    pts_map, d4 = _link_rows(catalog, resolver, bundle.points, "analiticafantasy_points")
    inj_map, d5 = _link_rows(catalog, resolver, bundle.injured, "analiticafantasy_injured")
    sus_map, d6 = _link_rows(catalog, resolver, bundle.suspended, "analiticafantasy_suspended")
    form_map, d7 = _link_rows(catalog, resolver, bundle.form, "analiticafantasy_form")
    # Agrupa roles de balón parado por nombre antes del matching.
    set_by_name: dict[str, list[AfSetPieceRow]] = {}
    for row in bundle.set_pieces:
        set_by_name.setdefault(normalize_name(row.name), []).append(row)
    set_reps = [rows[0] for rows in set_by_name.values() if rows]
    set_map, d8 = _link_rows(catalog, resolver, set_reps, "analiticafantasy_set_pieces")

    calendar_by_club: dict[str, list[AfCalendarCell]] = {}
    for cell in bundle.calendar:
        key = normalize_club(cell.team_name) or normalize_name(cell.team_name)
        calendar_by_club.setdefault(key, []).append(cell)

    for player in players:
        pid = player.get("player_id")
        if not isinstance(pid, str):
            continue
        market = market_map.get(pid)
        bid = bid_map.get(pid)
        pred = pred_map.get(pid)
        pts = pts_map.get(pid)
        injured = inj_map.get(pid)
        suspended = sus_map.get(pid)
        form = form_map.get(pid)
        set_piece = set_map.get(pid)

        if market is not None:
            player["af_price_delta"] = market.price_delta
            player["af_market_value"] = market.market_value
            if player.get("p_titular") is None and market.p_titular is not None:
                player["p_titular"] = market.p_titular
                player["p_titular_source"] = "analiticafantasy_market"
        if bid is not None:
            player["af_ideal_bid"] = bid.ideal_bid
            player["af_max_bid"] = bid.max_bid
            if bid.expected_points is not None:
                player["af_expected_points"] = bid.expected_points
            if market is None and bid.price_delta is not None:
                player["af_price_delta"] = bid.price_delta
        if pred is not None:
            player["af_market_signal"] = pred.direction
            player["af_signal_strength"] = pred.signal_strength
            player["af_predicted_delta"] = pred.predicted_delta
        if pts is not None:
            if pts.predicted_points is not None:
                player["af_expected_points"] = pts.predicted_points
            player["af_ceiling_points"] = pts.ceiling_points
            player["af_goal_probability"] = pts.goal_probability
            player["af_assist_probability"] = pts.assist_probability
            ppm = pts.points_per_million
            if ppm is None and pts.predicted_points is not None:
                value = pts.market_value or player.get("fantasy_price") or player.get("af_market_value")
                if isinstance(value, (int, float)) and value > 0:
                    ppm = round(float(pts.predicted_points) / (float(value) / 1_000_000.0), 4)
            player["af_points_per_million"] = ppm
        if injured is not None:
            from toolbox.normalize import titularity_overrides_injury

            if not titularity_overrides_injury(
                player.get("p_titular"),
                source=player.get("p_titular_source") if isinstance(player.get("p_titular_source"), str) else None,
                lineup_status=player.get("lineup_status") if isinstance(player.get("lineup_status"), str) else None,
            ):
                player["fitness"] = "lesionado"
                detail = injured.status_info or injured.report
                if detail:
                    player["fitness_detail"] = detail
            player["af_injury"] = {
                "status": injured.status,
                "info": injured.status_info,
                "report": injured.report,
                "start": injured.injury_start,
                "expected_return": injured.expected_return,
            }
        if suspended is not None:
            sanction = player.get("sanction") if isinstance(player.get("sanction"), dict) else {}
            sanction = {**sanction, "suspended": True}
            player["sanction"] = sanction
            if suspended.report or suspended.status_info:
                player["fitness_detail"] = suspended.report or suspended.status_info
            player["af_suspension"] = {
                "status": suspended.status,
                "info": suspended.status_info,
                "report": suspended.report,
            }
        if form is not None:
            player["af_form"] = {
                "recent_average": form.recent_average,
                "signal_count": form.signal_count,
                "signals": list(form.signals),
            }
        if set_piece is not None:
            grouped = set_by_name.get(normalize_name(set_piece.name)) or [set_piece]
            player["af_set_pieces"] = [
                {"role": item.role, "shirt": item.shirt} for item in grouped if item.role
            ]

        club = player.get("club")
        if isinstance(club, str) and club.strip():
            cells = calendar_by_club.get(normalize_club(club) or normalize_name(club)) or []
            if cells:
                upcoming = sorted(cells, key=lambda item: item.matchday)[:5]
                player["af_calendar"] = [
                    {
                        "matchday": cell.matchday,
                        "opponent": cell.opponent,
                        "is_home": cell.is_home,
                        "predicted_score": cell.predicted_score,
                        "recommendation_pct": cell.recommendation_pct,
                        "difficulty": cell.difficulty,
                    }
                    for cell in upcoming
                ]
                # Soft FDR proxy: 100 - recommendation for the next cell.
                nxt = upcoming[0]
                player["af_recommendation_pct"] = nxt.recommendation_pct

    # Radar: deltas de titularidad vs mercado AF (titularity) cuando el once scrapeado difiere.
    for player in players:
        af_delta = None
        market = market_map.get(player.get("player_id")) if isinstance(player.get("player_id"), str) else None
        if market is not None and market.p_titular is not None and isinstance(player.get("p_titular"), (int, float)):
            af_delta = round(float(player["p_titular"]) - float(market.p_titular), 4)
            if abs(af_delta) >= 0.05:
                player["af_titular_delta"] = af_delta

    prediction_rising = sorted(
        [p for p in players if p.get("af_market_signal") == "up"],
        key=lambda item: (-(item.get("af_signal_strength") or 0), item.get("player_id") or ""),
    )[:15]
    prediction_falling = sorted(
        [p for p in players if p.get("af_market_signal") == "down"],
        key=lambda item: (-(item.get("af_signal_strength") or 0), item.get("player_id") or ""),
    )[:15]
    # Si el matching deja pocas filas, el panel usa la lista AF cruda (sin player_id local).
    if len(prediction_rising) < 10:
        prediction_rising = _prediction_cards(bundle.predictions, "up", existing=prediction_rising)
    if len(prediction_falling) < 10:
        prediction_falling = _prediction_cards(bundle.predictions, "down", existing=prediction_falling)

    oracle_chollos = sorted(
        [p for p in players if isinstance(p.get("af_points_per_million"), (int, float))],
        key=lambda item: (-float(item["af_points_per_million"]), item.get("player_id") or ""),
    )[:15]
    oracle_points = sorted(
        [p for p in players if isinstance(p.get("af_expected_points"), (int, float))],
        key=lambda item: (-float(item["af_expected_points"]), item.get("player_id") or ""),
    )[:15]
    if len(oracle_points) < 10:
        oracle_points = _points_cards(bundle.points, existing=oracle_points)
    if len(oracle_chollos) < 10:
        oracle_chollos = _chollo_cards(bundle.points, existing=oracle_chollos)

    in_form = sorted(
        [p for p in players if isinstance((p.get("af_form") or {}).get("recent_average"), (int, float))],
        key=lambda item: (
            -int((item.get("af_form") or {}).get("signal_count") or 0),
            -float((item.get("af_form") or {}).get("recent_average") or 0),
        ),
    )[:15]
    if len(in_form) < 10:
        in_form = _form_cards(bundle.form, existing=in_form)

    summary = {
        "prediction_rising": prediction_rising,
        "prediction_falling": prediction_falling,
        "oracle_points": oracle_points,
        "oracle_chollos": oracle_chollos,
        "in_form": in_form,
    }
    return [*d1, *d2, *d3, *d4, *d5, *d6, *d7, *d8], summary


def _prediction_cards(
    rows: list[AfPredictionRow],
    direction: str,
    *,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    known = {normalize_name(str(item.get("name") or item.get("nickname") or "")) for item in existing}
    cards = list(existing)
    ranked = [row for row in rows if row.direction == direction]
    ranked.sort(key=lambda row: (-(row.signal_strength or 0), row.name))
    for row in ranked:
        key = normalize_name(row.name)
        if key in known:
            continue
        known.add(key)
        cards.append(
            {
                "player_id": f"af-pred-{key}",
                "name": row.name,
                "nickname": row.name,
                "af_market_signal": row.direction,
                "af_signal_strength": row.signal_strength,
                "af_predicted_delta": row.predicted_delta,
                "af_market_value": row.market_value,
            }
        )
        if len(cards) >= 15:
            break
    return cards


def _points_cards(rows: list[AfPointsRow], *, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {normalize_name(str(item.get("name") or item.get("nickname") or "")) for item in existing}
    cards = list(existing)
    ranked = [row for row in rows if row.predicted_points is not None]
    ranked.sort(key=lambda row: (-float(row.predicted_points or 0), row.name))
    for row in ranked:
        key = normalize_name(row.name)
        if key in known:
            continue
        known.add(key)
        cards.append(
            {
                "player_id": f"af-pts-{row.external_id or key}",
                "name": row.name,
                "nickname": row.name,
                "club": row.club,
                "position": row.position,
                "p_titular": row.p_titular,
                "af_expected_points": row.predicted_points,
                "af_ceiling_points": row.ceiling_points,
                "af_goal_probability": row.goal_probability,
                "af_assist_probability": row.assist_probability,
                "af_points_per_million": row.points_per_million,
                "af_market_value": row.market_value,
            }
        )
        if len(cards) >= 15:
            break
    return cards


def _chollo_cards(rows: list[AfPointsRow], *, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {normalize_name(str(item.get("name") or item.get("nickname") or "")) for item in existing}
    cards = list(existing)
    scored: list[tuple[float, AfPointsRow]] = []
    for row in rows:
        ppm = row.points_per_million
        if ppm is None and row.predicted_points is not None and row.market_value:
            ppm = float(row.predicted_points) / (float(row.market_value) / 1_000_000.0)
        if ppm is None:
            continue
        scored.append((ppm, row))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    for ppm, row in scored:
        key = normalize_name(row.name)
        if key in known:
            continue
        known.add(key)
        cards.append(
            {
                "player_id": f"af-chollo-{row.external_id or key}",
                "name": row.name,
                "nickname": row.name,
                "club": row.club,
                "position": row.position,
                "p_titular": row.p_titular,
                "af_expected_points": row.predicted_points,
                "af_points_per_million": round(ppm, 4),
                "af_market_value": row.market_value,
            }
        )
        if len(cards) >= 15:
            break
    return cards


def _form_cards(rows: list[AfFormRow], *, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {normalize_name(str(item.get("name") or item.get("nickname") or "")) for item in existing}
    cards = list(existing)
    ranked = sorted(
        rows,
        key=lambda row: (-(row.signal_count or 0), -(row.recent_average or 0), row.name),
    )
    for row in ranked:
        key = normalize_name(row.name)
        if key in known:
            continue
        known.add(key)
        cards.append(
            {
                "player_id": f"af-form-{row.external_id or key}",
                "name": row.name,
                "nickname": row.name,
                "af_form": {
                    "recent_average": row.recent_average,
                    "signal_count": row.signal_count,
                    "signals": list(row.signals),
                },
            }
        )
        if len(cards) >= 15:
            break
    return cards

"""Normaliza el JSON de la API a documentos estables para el modelo.

Los campos salen siempre, con ``null`` cuando la API no los trae. La marca de
tiempo de la cláusula conserva hora y minuto en Europe/Madrid: la interfaz del
juego no muestra el minuto, el JSON sí.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 1
MADRID_NAME = "Europe/Madrid"

_POSITIONS: dict[int, str] = {1: "POR", 2: "DEF", 3: "MC", 4: "DEL"}
_POSITION_NAMES = {
    "por": "POR",
    "gk": "POR",
    "portero": "POR",
    "def": "DEF",
    "df": "DEF",
    "defensa": "DEF",
    "mc": "MC",
    "mid": "MC",
    "centrocampista": "MC",
    "del": "DEL",
    "fw": "DEL",
    "delantero": "DEL",
}
_LOCK_KEYS = {
    "buyoutclauselockedendtime",
    "buyoutclauselockeduntil",
    "buyoutclauselockend",
    "buyoutclauselockendtime",
    "clauselockedendtime",
    "clauselockend",
    "clauselockeduntil",
    "lockeduntil",
    "lockedendtime",
    "lockexpiration",
    "lockexpiresat",
    "clauseunlockdate",
    "buyoutunlocktime",
}
_LISTING_EXPIRY_KEYS = (
    "expirationDate",
    "expiration",
    "expiresAt",
    "endDate",
    "marketExpiration",
    "finishDate",
)


def display_zone() -> tuple[str, tzinfo]:
    try:
        return MADRID_NAME, ZoneInfo(MADRID_NAME)
    except ZoneInfoNotFoundError:
        return "UTC", timezone.utc


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_real(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return int(number)
    return None


def _as_str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


_EXCLUDED_STATUS = {
    "injured": "lesionado",
    "lesionado": "lesionado",
    "out": "lesionado",
    "baja": "lesionado",
    "suspended": "sancionado",
    "sanctioned": "sancionado",
    "sancionado": "sancionado",
}


def fitness_from_status(status: str | None) -> str | None:
    """Traduce ``playerStatus`` de la API. Una duda no es una baja."""
    if not isinstance(status, str) or not status.strip():
        return None
    folded = status.strip().lower()
    excluded = _EXCLUDED_STATUS.get(folded)
    if excluded:
        return excluded
    if folded in {"doubtful", "duda"}:
        return "duda"
    if folded in {"ok", "available", "disponible"}:
        return "disponible"
    return None


def exclusion_from_status(status: str | None) -> str | None:
    if not isinstance(status, str):
        return None
    return _EXCLUDED_STATUS.get(status.strip().lower())


def _position(value: Any) -> tuple[int | None, str | None]:
    if isinstance(value, bool) or value is None:
        return None, None
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        number = int(value)
        return number, _POSITIONS.get(number)
    if isinstance(value, str):
        code = _POSITION_NAMES.get(value.strip().lower())
        if code is None:
            return None, None
        reverse = {name: number for number, name in _POSITIONS.items()}
        return reverse[code], code
    return None, None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none"}:
            return None
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            return _from_epoch(float(text))
        iso = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            _name, zone = display_zone()
            return parsed.replace(tzinfo=zone)
        return parsed
    return None


def _from_epoch(value: float) -> datetime | None:
    if value != value or abs(value) > 10_000_000_000_000:
        return None
    seconds = value / 1000.0 if abs(value) >= 10_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _clock(moment: datetime) -> dict[str, Any]:
    zone_name, zone = display_zone()
    local = moment.astimezone(zone)
    return {
        "expires_at": moment.astimezone(timezone.utc).isoformat(),
        "local_date": local.date().isoformat(),
        "local_time": local.strftime("%H:%M"),
        "local_clock": local.strftime("%H:%M:%S"),
        "timezone": zone_name,
        "epoch_ms": int(moment.timestamp() * 1000),
    }


def parse_clause_lock(value: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Convierte la marca cruda de la API en fecha, hora y minuto locales."""
    if isinstance(value, bool):
        value = None
    raw = _as_str(value) if not isinstance(value, (int, float)) else str(value)
    if isinstance(value, str):
        raw = value.strip()
    parsed = _parse_datetime(value)
    current = now or datetime.now(timezone.utc)
    if parsed is None:
        return {
            "present": raw is not None,
            "raw": raw,
            "expires_at": None,
            "local_date": None,
            "local_time": None,
            "local_clock": None,
            "timezone": display_zone()[0],
            "epoch_ms": None,
            "is_locked": None,
        }
    clock = _clock(parsed)
    clock.update(
        {
            "present": True,
            "raw": raw,
            "is_locked": parsed > current,
        }
    )
    return clock


def find_lock_raw(node: Any) -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            if _norm_key(str(key)) in _LOCK_KEYS and value not in (None, ""):
                return value
        for value in node.values():
            found = find_lock_raw(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_lock_raw(item)
            if found is not None:
                return found
    return None


def clause_lock_from(player: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    explicit = None
    for key, value in player.items():
        if _norm_key(str(key)) in _LOCK_KEYS and value not in (None, ""):
            explicit = value
            break
    raw = explicit if explicit is not None else find_lock_raw(player)
    if raw is None:
        zone_name, _zone = display_zone()
        return {
            "present": False,
            "raw": None,
            "expires_at": None,
            "local_date": None,
            "local_time": None,
            "local_clock": None,
            "timezone": zone_name,
            "epoch_ms": None,
            "is_locked": False,
        }
    return parse_clause_lock(raw, now=now)


def unwrap_collection(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _player_master(item: dict[str, Any]) -> dict[str, Any]:
    for key in ("playerMaster", "player", "footballPlayer"):
        value = item.get(key)
        if isinstance(value, dict):
            return value
    return item


def _club_name(master: dict[str, Any]) -> str | None:
    team = master.get("team")
    if isinstance(team, dict):
        return _as_str(_first(team, "name", "shortName", "slug"))
    if isinstance(team, str):
        return _as_str(team)
    return _as_str(_first(master, "teamName", "club"))


def _manager_name(node: dict[str, Any]) -> str | None:
    manager = node.get("manager")
    if isinstance(manager, dict):
        found = _as_str(_first(manager, "managerName", "name", "nickname"))
        if found:
            return found
    team = node.get("team")
    if isinstance(team, dict):
        nested = team.get("manager")
        if isinstance(nested, dict):
            found = _as_str(_first(nested, "managerName", "name"))
            if found:
                return found
        found = _as_str(_first(team, "managerName", "name"))
        if found and "playerMaster" not in node:
            return found
    return _as_str(_first(node, "managerName", "manager_name"))


def _normalize_bids(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    bids: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        team = item.get("team") if isinstance(item.get("team"), dict) else {}
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        manager = item.get("manager") if isinstance(item.get("manager"), dict) else {}
        bids.append(
            {
                "bid_id": _as_str(_first(item, "id", "bidId")),
                "amount": _as_int(_first(item, "money", "amount", "bid", "value")),
                "team_id": _as_str(_coalesce(_first(item, "teamId"), _first(team, "id", "teamId"))),
                "manager_name": _as_str(
                    _first(item, "managerName")
                    or _first(manager, "managerName", "name")
                    or _first(user, "managerName", "name")
                    or _first(team, "managerName", "name")
                ),
            }
        )
    return bids


def _listing_expiry(item: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = _first(item, *_LISTING_EXPIRY_KEYS)
    parsed = _parse_datetime(raw)
    if parsed is None:
        return None, None
    clock = _clock(parsed)
    return clock["expires_at"], clock["local_time"]


def normalize_listing(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    master = _player_master(item)
    position_id, position = _position(_first(master, "positionId", "position", "role"))
    if position is None:
        position_id, position = _position(_first(item, "positionId", "position"))
    seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
    seller_team = item.get("sellerTeam") if isinstance(item.get("sellerTeam"), dict) else {}
    bids = _normalize_bids(item.get("bids") or item.get("offers"))
    amounts = [bid["amount"] for bid in bids if isinstance(bid["amount"], int)]
    expires_at, expires_local = _listing_expiry(item)
    return {
        "market_id": _as_str(_first(item, "id", "marketId")),
        "player_id": _as_str(_first(master, "id", "playerId")),
        "name": _as_str(_first(master, "name", "fullname")),
        "nickname": _as_str(_first(master, "nickname", "shortName")),
        "position_id": position_id,
        "position": position,
        "club": _club_name(master),
        "market_value": _as_int(_first(master, "marketValue", "value")),
        "sale_price": _as_int(_first(item, "salePrice", "price", "money")),
        "seller_team_id": _as_str(_coalesce(_first(seller, "id", "teamId"), _first(seller_team, "id", "teamId"))),
        "seller_manager": _coalesce(_manager_name(seller), _manager_name(seller_team)),
        "bids": bids,
        "leading_bid": max(amounts) if amounts else None,
        "listing_expires_at": expires_at,
        "listing_expires_local_time": expires_local,
        "clause_lock": clause_lock_from(item, now=now),
    }


def build_market_document(
    *,
    league_id: str,
    league_name: str | None,
    source_url: str,
    payload: Any,
    fetched_at: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    rows = unwrap_collection(payload, ("elements", "items", "players", "market", "data", "content"))
    if not rows and isinstance(payload, dict) and ("playerMaster" in payload or "salePrice" in payload):
        rows = [payload]
    listings = [normalize_listing(row, now=now) for row in rows if isinstance(row, dict)]
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "market",
        "league_id": league_id,
        "league_name": league_name,
        "fetched_at": fetched_at,
        "source_url": source_url,
        "count": len(listings),
        "listings": listings,
    }


def _parse_week_series(raw: Any) -> list[float]:
    """Puntos de jornada. Acepta números o filas con ``weekPoints`` / ``totalPoints``."""
    if isinstance(raw, bool) or raw is None:
        return []
    if isinstance(raw, (int, float)):
        number = _as_real(raw)
        return [] if number is None else [number]
    if not isinstance(raw, list):
        return []
    numbered: list[tuple[int, int, float]] = []
    plain: list[float] = []
    saw_week = False
    for index, item in enumerate(raw):
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            number = _as_real(item)
            if number is not None:
                plain.append(number)
            continue
        if not isinstance(item, dict):
            continue
        number = _as_real(_first(item, "weekPoints", "totalPoints", "points"))
        if number is None:
            continue
        week = item.get("weekNumber", item.get("week"))
        if isinstance(week, int) and not isinstance(week, bool):
            saw_week = True
            numbered.append((week, index, number))
        else:
            numbered.append((index, index, number))
    if numbered and (saw_week or not plain):
        numbered.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in numbered]
    return plain


def official_week_points(player: dict[str, Any]) -> list[float]:
    """Últimas 5 jornadas oficiales. Cada valor es el ``weekPoints`` de esa jornada.

    La API viva guarda la serie en ``playerMaster.lastStats[].totalPoints``.
    """
    if not isinstance(player, dict):
        return []
    stored = _parse_week_series(player.get("week_points"))
    if stored:
        return stored[-5:]
    master = _player_master(player)
    for source in (player, master):
        if not isinstance(source, dict):
            continue
        for key in ("weekPoints", "week_points", "lastStats", "last_stats"):
            if key == "week_points" and source is player:
                continue
            series = _parse_week_series(source.get(key))
            if series:
                return series[-5:]
    return []


def normalize_player(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    master = _player_master(item)
    position_id, position = _position(_first(master, "positionId", "position", "role"))
    shielded = _as_bool(_first(item, "isShielded", "shielded", "blindado"))
    player_status = _as_str(_first(master, "playerStatus", "status"))
    if player_status:
        player_status = player_status.strip().lower()
    return {
        "player_team_id": _as_str(_first(item, "playerTeamId", "id")),
        "player_id": _as_str(_first(master, "id", "playerId")),
        "name": _as_str(_first(master, "name", "fullname")),
        "nickname": _as_str(_first(master, "nickname", "shortName")),
        "position_id": position_id,
        "position": position,
        "player_status": player_status,
        "fitness": fitness_from_status(player_status),
        "club": _club_name(master),
        "market_value": _as_int(_first(master, "marketValue", "value")),
        "average_points": _as_real(_first(master, "averagePoints", "average_points")),
        "week_points": official_week_points(item),
        "buyout_clause": _as_int(_first(item, "buyoutClause", "clause", "buyout")),
        "is_shielded": shielded,
        "clause_lock": clause_lock_from(item, now=now),
    }


def _team_id_from_row(row: dict[str, Any]) -> str | None:
    team = row.get("team") if isinstance(row.get("team"), dict) else {}
    found = _as_str(_coalesce(_first(row, "teamId", "team_id"), _first(team, "id", "teamId")))
    if found:
        return found
    if "playerMaster" in row:
        return None
    if isinstance(row.get("players"), list):
        return _as_str(_first(row, "id"))
    return _as_str(_first(row, "id"))


def team_seeds(payload: Any) -> list[dict[str, Any]]:
    rows = unwrap_collection(
        payload,
        ("elements", "teams", "ranking", "standing", "standings", "items", "data", "content"),
    )
    if not rows and isinstance(payload, dict) and isinstance(payload.get("players"), list):
        rows = [payload]
    seeds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        team_id = _team_id_from_row(row)
        if team_id is None or team_id in seen:
            continue
        seen.add(team_id)
        team = row.get("team") if isinstance(row.get("team"), dict) else {}
        seeds.append(
            {
                "team_id": team_id,
                "manager_name": _manager_name(row) or _manager_name(team),
                "fantasy_team_name": _as_str(_first(team, "name", "teamName") or _first(row, "teamName", "name")),
                "rank": _as_int(_first(row, "position", "rank", "ranking")),
                "points": _as_int(_first(row, "points", "totalPoints")),
                "embedded": row if isinstance(row.get("players"), list) else None,
            }
        )
    return seeds


def normalize_squad(
    payload: dict[str, Any],
    *,
    seed: dict[str, Any],
    own_team_id: str | None,
    source_url: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    players_raw = payload.get("players") if isinstance(payload.get("players"), list) else []
    team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
    cash = _as_int(_coalesce(_first(payload, "teamMoney", "money", "cash"), _first(team, "teamMoney", "money", "cash")))
    team_id = seed["team_id"]
    return {
        "team_id": team_id,
        "is_self": own_team_id is not None and team_id == own_team_id,
        "manager_name": _manager_name(payload) or seed.get("manager_name"),
        "fantasy_team_name": _as_str(_first(team, "name", "teamName")) or seed.get("fantasy_team_name"),
        "rank": seed.get("rank"),
        "points": seed.get("points"),
        "cash": cash,
        "players": [normalize_player(player, now=now) for player in players_raw if isinstance(player, dict)],
        "source_url": source_url,
        "error": None,
    }


_LINEUP_LINES = (
    ("goalkeeper", "POR"),
    ("defender", "DEF"),
    ("midfield", "MC"),
    ("striker", "DEL"),
)


def _saved_line_players(node: Any, position: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(node, list):
        source = node
    elif isinstance(node, dict):
        source = [item for value in node.values() for item in (value if isinstance(value, list) else [value])]
    else:
        return rows
    for item in source:
        if not isinstance(item, dict):
            continue
        master = item.get("playerMaster") if isinstance(item.get("playerMaster"), dict) else item
        status = _as_str(_first(master, "playerStatus", "status"))
        if status:
            status = status.strip().lower()
        rows.append(
            {
                "player_id": _as_str(_first(master, "id", "playerId")),
                "name": _as_str(_first(master, "name", "fullname")),
                "nickname": _as_str(_first(master, "nickname", "shortName")),
                "position": position,
                "player_status": status,
                "fitness": fitness_from_status(status),
            }
        )
    return rows


def normalize_saved_lineup(payload: dict[str, Any], *, source_url: str | None) -> dict[str, Any]:
    """Once que la app tiene guardado. No es el once que recomienda el solver."""
    formation = payload.get("formation") if isinstance(payload.get("formation"), dict) else {}
    xi: list[dict[str, Any]] = []
    for key, position in _LINEUP_LINES:
        xi.extend(_saved_line_players(formation.get(key), position))
    bench: list[dict[str, Any]] = []
    for key, position in _LINEUP_LINES:
        bench.extend(_saved_line_players((formation.get("bench") or {}).get(key) if isinstance(formation.get("bench"), dict) else None, position))
    tactical = formation.get("tacticalFormation")
    numbers = [int(item) for item in tactical if isinstance(item, int) and not isinstance(item, bool)] if isinstance(tactical, list) else []
    label = "-".join(str(number) for number in numbers) if len(numbers) == 3 else None
    return {
        "ok": bool(xi),
        "source_url": source_url,
        "formation": label,
        "updated_at": _as_str(payload.get("updatedAt")),
        "xi": xi,
        "bench": bench,
        "error": None if xi else "empty",
    }


def empty_squad(seed: dict[str, Any], *, own_team_id: str | None, message: str) -> dict[str, Any]:
    team_id = str(seed["team_id"])
    return {
        "team_id": team_id,
        "is_self": own_team_id is not None and team_id == own_team_id,
        "manager_name": seed.get("manager_name"),
        "fantasy_team_name": seed.get("fantasy_team_name"),
        "rank": seed.get("rank"),
        "points": seed.get("points"),
        "cash": None,
        "players": [],
        "source_url": None,
        "error": message,
    }


def build_squads_document(
    *,
    league_id: str,
    league_name: str | None,
    index_url: str,
    squads: list[dict[str, Any]],
    fetched_at: str,
) -> dict[str, Any]:
    partial = any(squad.get("error") for squad in squads)
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "squads",
        "league_id": league_id,
        "league_name": league_name,
        "fetched_at": fetched_at,
        "index_url": index_url,
        "includes_self": True,
        "partial": partial,
        "count": len(squads),
        "clause_lock_timezone": display_zone()[0],
        "clause_lock_note": (
            "local_time es hora y minuto en clause_lock_timezone. "
            "present=false significa que la API no envió marca de desbloqueo."
        ),
        "squads": squads,
    }


def leagues_from_payload(payload: Any) -> list[dict[str, Any]]:
    collection_keys = ("leagues", "elements", "items", "data", "content")
    rows = unwrap_collection(payload, collection_keys)
    if (
        not rows
        and isinstance(payload, dict)
        and not any(key in payload for key in collection_keys)
        and _as_str(_first(payload, "id", "leagueId"))
    ):
        rows = [payload]
    leagues: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        league_id = _as_str(_first(row, "id", "leagueId"))
        if league_id is None:
            continue
        team = row.get("team") if isinstance(row.get("team"), dict) else {}
        leagues.append(
            {
                "league_id": league_id,
                "name": _as_str(_first(row, "name")),
                "own_team_id": _as_str(_first(team, "id", "teamId")),
            }
        )
    return leagues

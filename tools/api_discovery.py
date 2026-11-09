"""Inventario offline de lo que la API de LaLiga Fantasy ya dejó en caché.

No abre sockets, no lee ``.env`` y no imprime nombres de mánager ni tokens.
Clasifica cada cuerpo de ``.cache/bodies`` y ``.cache/scraper_bodies``, une el
árbol de claves y cuenta los campos que las hipótesis de la auditoría necesitan.

Uso (desde la raíz del repo):

    python tools/api_discovery.py

El detalle va a ``.cache/scratchpad/api_discovery/`` (gitignored). Por stdout
sale solo el resumen, con ejemplos personales sustituidos por ``[redactado]``.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
OUT = CACHE / "scratchpad" / "api_discovery"

# Claves cuyo valor identifica a una persona de la liga (mánager), no a un
# futbolista público. El ejemplo se sustituye; la clave sí se publica.
_REDACT_KEYS = frozenset(
    {
        "managername",
        "avatar",
        "email",
        "user1id",
        "user2id",
        "managerid",
        "userid",
        "token",
        "authorization",
        "phone",
        "oid",
    }
)
_PERSON_PATH = frozenset({"manager", "user", "user1", "user2", "seller"})


def _norm_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def redact_example(path: tuple[str, ...], value: Any) -> Any:
    """Ejemplo publicable. Los identificadores de mánager no salen del disco."""
    key = _norm_key(path[-1]) if path else ""
    if key in _REDACT_KEYS or (path and path[-1] in {"name", "id", "nickname"} and any(part in _PERSON_PATH for part in path[:-1])):
        return "[redactado]"
    if isinstance(value, str) and (value.startswith("eyJ") or len(value) > 180):
        return value[:60] + "…" if not value.startswith("eyJ") else "[redactado]"
    if isinstance(value, float):
        return round(value, 4)
    return value


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


class Node:
    """Un camino del JSON, unido entre todos los cuerpos de la misma clase."""

    def __init__(self) -> None:
        self.present = 0
        self.nulls = 0
        self.types: Counter[str] = Counter()
        self.example: Any = None
        self.children: dict[str, Node] = {}
        self.item: Node | None = None
        self.list_len = Counter()

    def observe(self, value: Any, path: tuple[str, ...], *, depth: int) -> None:
        self.present += 1
        kind = _kind(value)
        self.types[kind] += 1
        if value is None:
            self.nulls += 1
            return
        if self.example is None and kind not in {"list", "object"}:
            self.example = redact_example(path, value)
        if depth <= 0:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                node = self.children.setdefault(key, Node())
                node.observe(child, path + (key,), depth=depth - 1)
            return
        if isinstance(value, list):
            self.list_len[min(len(value), 50)] += 1
            if self.item is None:
                self.item = Node()
            # Las listas de jugadores y de actividad se recorren enteras: si
            # no, un campo que solo trae el último elemento parece ausente.
            for child in value:
                self.item.observe(child, path + ("[]",), depth=depth - 1)

    def dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "present": self.present,
            "nulls": self.nulls,
            "types": dict(self.types),
        }
        if self.example is not None:
            out["example"] = self.example
        if self.children:
            out["fields"] = {key: node.dump() for key, node in sorted(self.children.items())}
        if self.item is not None:
            out["items"] = self.item.dump()
        return out


def unwrap(payload: Any) -> tuple[Any, str | None]:
    """Quita el sobre de la caché. Devuelve el JSON de la API y, si viene, la ruta."""
    source: str | None = None
    current = payload
    for _ in range(3):
        if not isinstance(current, dict):
            break
        url = current.get("source_url")
        if isinstance(url, str) and source is None:
            source = url.split("?", 1)[0]
        body = current.get("body")
        if isinstance(body, str) and ("kind" in current or body[:1] in "[{"):
            try:
                current = json.loads(body)
                continue
            except json.JSONDecodeError:
                return None, source
        if isinstance(body, (dict, list)):
            current = body
            continue
        inner = current.get("payload")
        if isinstance(inner, (dict, list)) and ("ok" in current or "source_url" in current):
            current = inner
            continue
        break
    return current, source


def classify(payload: Any) -> str:
    """Clase de endpoint a partir de la forma. No usa la URL: muchos cuerpos no la traen."""
    if isinstance(payload, dict):
        if isinstance(payload.get("formation"), dict):
            return "lineup"
        if isinstance(payload.get("players"), list) and any(
            key in payload for key in ("teamMoney", "teamValue", "loanedPlayers", "playersNumber")
        ):
            return "team"
        if isinstance(payload.get("leagues"), list):
            return "leagues"
        if "activityTypeId" in payload:
            return "activity"
        if any(key in payload for key in ("salePrice", "numberOfBids", "numberOfOffers", "expirationDate", "playerMarket")):
            return "market"
        keys = tuple(sorted(str(key) for key in payload.keys())[:8])
        return "dict:" + ",".join(keys)
    if isinstance(payload, list):
        if not payload:
            return "empty_list"
        sample = [row for row in payload[:12] if isinstance(row, dict)]
        if not sample:
            return "list:scalar"
        if any("activityTypeId" in row for row in sample):
            return "activity"
        if any("salePrice" in row or "numberOfBids" in row or "expirationDate" in row for row in sample):
            return "market"
        if any(isinstance(row.get("team"), dict) and ("position" in row or "points" in row) for row in sample):
            return "standing"
        if any("weekPoints" in row or "marketValue" in row for row in sample) and not any("buyoutClause" in row for row in sample):
            return "catalog"
        if any("buyoutClause" in row or "playerMaster" in row for row in sample):
            return "team_players"
        if any("name" in row and ("id" in row or "leagueId" in row) for row in sample) and not any("playerMaster" in row for row in sample):
            return "leagues"
        return "list:" + ",".join(sorted(sample[0].keys())[:6])
    return _kind(payload)


def _load(path: Path) -> Any | None:
    try:
        if path.stat().st_size > 40_000_000:
            return None
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _players_of(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("players"), list):
        return [row for row in payload["players"] if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and ("playerMaster" in payload or "salePrice" in payload or "playerMarket" in payload):
        return [payload]
    return []


def _master(row: dict[str, Any]) -> dict[str, Any]:
    master = row.get("playerMaster")
    return master if isinstance(master, dict) else row


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _walk_stats(node: Any, found: Counter[str]) -> None:
    if isinstance(node, dict):
        stats = node.get("stats")
        if isinstance(stats, dict) and any(isinstance(value, list) for value in stats.values()):
            for key in stats:
                found[str(key)] += 1
        for value in node.values():
            _walk_stats(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk_stats(value, found)


def _interesting_keys(node: Any, bag: set[str], prefix: str = "") -> None:
    """Nombres de clave que huelen a plazo, tendencia, puja o historial."""
    needles = ("expir", "lock", "trend", "change", "percent", "histor", "bid", "offer", "next", "rotat", "market", "clause", "injur", "sanction", "suspend", "lineup", "prob")
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                continue
            folded = key.lower()
            if any(needle in folded for needle in needles):
                bag.add(f"{prefix}{key}")
            _interesting_keys(value, bag, prefix + key + ".")
    elif isinstance(node, list) and node:
        _interesting_keys(node[0], bag, prefix + "[].")


def main() -> None:
    folders = [CACHE / "bodies", CACHE / "scraper_bodies"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = Counter()
    sources: Counter[str] = Counter()
    for folder in folders:
        if not folder.is_dir():
            skipped["missing_dir:" + folder.name] += 1
            continue
        for path in folder.iterdir():
            if not path.is_file():
                continue
            raw = _load(path)
            if raw is None:
                skipped["not_json:" + folder.name] += 1
                continue
            payload, source = unwrap(raw)
            if payload is None:
                skipped["empty_body"] += 1
                continue
            kind = classify(payload)
            stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            grouped[kind].append(
                {
                    "folder": folder.name,
                    "bytes": path.stat().st_size,
                    "mtime": stamp,
                    "source": source,
                    "payload": payload,
                }
            )
            if source:
                sources[source] += 1

    schemas: dict[str, Any] = {}
    hypothesis: dict[str, Any] = {}
    activity_report: dict[str, Any] = {}
    interesting: dict[str, list[str]] = {}

    for kind, rows in sorted(grouped.items()):
        root = Node()
        for row in rows:
            root.observe(row["payload"], (), depth=7)
        schemas[kind] = {
            "files": len(rows),
            "folders": dict(Counter(row["folder"] for row in rows)),
            "bytes": sum(row["bytes"] for row in rows),
            "newest": max(row["mtime"] for row in rows),
            "oldest": min(row["mtime"] for row in rows),
            "sources": sorted({row["source"] for row in rows if row["source"]})[:8],
            "schema": root.dump(),
        }
        names: set[str] = set()
        for row in rows[:3]:
            _interesting_keys(row["payload"], names)
        interesting[kind] = sorted(names)

    team_rows = grouped.get("team", [])
    market_rows = grouped.get("market", [])
    catalog_rows = grouped.get("catalog", [])
    activity_rows = grouped.get("activity", [])

    money_null = money_set = value_set = banned = loan_nonempty = 0
    status_counts: Counter[str] = Counter()
    ideal_true = ideal_false = 0
    season_points_set = 0
    lock_set = shielded_true = 0
    market_nested = 0
    direct_true = direct_false = 0
    stat_keys: Counter[str] = Counter()
    players_seen = 0
    change_keys: Counter[str] = Counter()
    for row in team_rows:
        payload = row["payload"]
        if isinstance(payload, dict):
            money_null += payload.get("teamMoney") is None
            money_set += _as_int(payload.get("teamMoney")) is not None
            value_set += _as_int(payload.get("teamValue")) is not None
            banned += bool(payload.get("banned"))
            loaned = payload.get("loanedPlayers")
            loan_nonempty += isinstance(loaned, list) and len(loaned) > 0
        for player in _players_of(payload):
            players_seen += 1
            master = _master(player)
            status = master.get("playerStatus")
            if isinstance(status, str):
                status_counts[status] += 1
            if master.get("lastSeasonPoints") not in (None, ""):
                season_points_set += 1
            if player.get("buyoutClauseLockedEndTime"):
                lock_set += 1
            if player.get("isShielded") is True:
                shielded_true += 1
            listing = player.get("playerMarket")
            if isinstance(listing, dict):
                market_nested += 1
                if listing.get("directOffer") is True:
                    direct_true += 1
                elif listing.get("directOffer") is False:
                    direct_false += 1
            for key in master:
                if "change" in str(key).lower() or "trend" in str(key).lower():
                    change_keys[str(key)] += 1
            for stat in master.get("lastStats") or []:
                if not isinstance(stat, dict):
                    continue
                flag = stat.get("isInIdealFormation")
                if flag is True:
                    ideal_true += 1
                elif flag is False:
                    ideal_false += 1
        _walk_stats(payload, stat_keys)

    bid_arrays = bid_counts = offer_counts = expiries = direct_market = 0
    sale_vs_value: list[float] = []
    market_change = 0
    listings = 0
    for row in market_rows:
        for item in _players_of(row["payload"]):
            listings += 1
            bids = item.get("bids") or item.get("offers")
            if isinstance(bids, list) and bids:
                bid_arrays += 1
            if "numberOfBids" in item:
                bid_counts += 1
            if "numberOfOffers" in item:
                offer_counts += 1
            if any(key in item for key in ("expirationDate", "expiresAt", "endDate")):
                expiries += 1
            if isinstance(item.get("directOffer"), bool):
                direct_market += 1
            master = _master(item)
            if any("change" in str(key).lower() for key in list(master) + list(item)):
                market_change += 1
            sale = _as_int(item.get("salePrice"))
            value = _as_int(master.get("marketValue"))
            if sale and value:
                sale_vs_value.append(sale / value)

    catalog_players = 0
    catalog_change = 0
    catalog_status: Counter[str] = Counter()
    for row in catalog_rows:
        for item in _players_of(row["payload"]):
            catalog_players += 1
            master = _master(item)
            if any("change" in str(key).lower() for key in master):
                catalog_change += 1
            status = master.get("playerStatus") or item.get("playerStatus")
            if isinstance(status, str):
                catalog_status[status] += 1
            _walk_stats(item, stat_keys)

    type_counts: Counter[int] = Counter()
    type_keys: dict[int, set[str]] = defaultdict(set)
    type_amounts: dict[int, list[int]] = defaultdict(list)
    user2_by_type: Counter[int] = Counter()
    player_by_type: Counter[int] = Counter()
    created: list[str] = []
    activity_events = 0
    activity_ids: set[str] = set()
    unknown_types: Counter[int] = Counter()
    known = {1, 6, 7, 8, 9, 12, 20, 21, 22, 23, 24, 31, 32, 33}
    for row in activity_rows:
        payload = row["payload"]
        events = payload if isinstance(payload, list) else []
        for event in events:
            if not isinstance(event, dict) or "activityTypeId" not in event:
                continue
            activity_events += 1
            type_id = event.get("activityTypeId")
            if not isinstance(type_id, int):
                continue
            type_counts[type_id] += 1
            type_keys[type_id].update(str(key) for key in event.keys())
            amount = _as_int(event.get("amount"))
            if amount is not None:
                type_amounts[type_id].append(amount)
            if event.get("user2Id") not in (None, ""):
                user2_by_type[type_id] += 1
            if event.get("playerMasterId") not in (None, ""):
                player_by_type[type_id] += 1
            stamp = event.get("createdAt")
            if isinstance(stamp, str):
                created.append(stamp)
            event_id = event.get("id")
            if event_id is not None:
                activity_ids.add(str(event_id))
            if type_id not in known:
                unknown_types[type_id] += 1

    def _amount_summary(values: list[int]) -> dict[str, int] | None:
        if not values:
            return None
        ordered = sorted(values)
        return {
            "n": len(ordered),
            "min": ordered[0],
            "p50": int(statistics.median(ordered)),
            "max": ordered[-1],
        }

    activity_report = {
        "files": len(activity_rows),
        "events": activity_events,
        "distinct_ids": len(activity_ids),
        "created_min": min(created) if created else None,
        "created_max": max(created) if created else None,
        "types": {
            str(type_id): {
                "count": type_counts[type_id],
                "keys": sorted(type_keys[type_id]),
                "with_user2": user2_by_type[type_id],
                "with_player": player_by_type[type_id],
                "amount": _amount_summary(type_amounts[type_id]),
            }
            for type_id in sorted(type_counts)
        },
        "unknown_types": {str(key): value for key, value in unknown_types.items()},
    }

    laliga_paths: Counter[str] = Counter()
    log_path = CACHE / "network_logs.jsonl"
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "llt-services.com" not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = entry.get("url")
            status = entry.get("status")
            if isinstance(url, str):
                laliga_paths[f"{status} {url}"] += 1

    hypothesis = {
        "team_files": len(team_rows),
        "players_in_team_files": players_seen,
        "teamMoney_null": money_null,
        "teamMoney_set": money_set,
        "teamValue_set": value_set,
        "banned_true": banned,
        "loanedPlayers_nonempty": loan_nonempty,
        "playerStatus": dict(status_counts),
        "lastSeasonPoints_set": season_points_set,
        "clause_lock_set": lock_set,
        "shielded_true": shielded_true,
        "playerMarket_nested": market_nested,
        "directOffer_nested_true": direct_true,
        "directOffer_nested_false": direct_false,
        "isInIdealFormation_true": ideal_true,
        "isInIdealFormation_false": ideal_false,
        "change_like_keys_on_master": dict(change_keys),
        "stat_keys": dict(stat_keys),
        "market_files": len(market_rows),
        "market_listings": listings,
        "market_bid_arrays_nonempty": bid_arrays,
        "market_with_numberOfBids": bid_counts,
        "market_with_numberOfOffers": offer_counts,
        "market_with_expiry": expiries,
        "market_with_directOffer": direct_market,
        "market_with_change_key": market_change,
        "sale_over_value_p50": round(statistics.median(sale_vs_value), 4) if sale_vs_value else None,
        "catalog_files": len(catalog_rows),
        "catalog_players": catalog_players,
        "catalog_with_change_key": catalog_change,
        "catalog_status": dict(catalog_status),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "schemas.json").write_text(json.dumps(schemas, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "hypothesis.json").write_text(
        json.dumps({"hypothesis": hypothesis, "activity": activity_report, "interesting_keys": interesting, "embedded_sources": sources.most_common(30)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "laliga_log_paths.json").write_text(
        json.dumps(laliga_paths.most_common(80), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("classes", {kind: len(rows) for kind, rows in sorted(grouped.items())})
    print("skipped", dict(skipped))
    print("hypothesis_keys", sorted(hypothesis))
    print("activity_types", sorted(type_counts))
    print("activity_events", activity_events, "span", activity_report["created_min"], activity_report["created_max"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()

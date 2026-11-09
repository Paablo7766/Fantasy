"""Estado oficial del jugador: gana la foto más nueva.

Mercado, plantilla y catálogo pueden decir cosas distintas. Se queda el
``playerStatus`` de la foto con marca de tiempo más reciente. Una foto sin
fecha no pisa a una fechada. No descarga nada: lee la caché de disco.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_VALID = frozenset({"ok", "injured", "doubtful", "suspended"})
_ALIASES = {
    "injury": "injured",
    "lesionado": "injured",
    "out": "injured",
    "baja": "injured",
    "duda": "doubtful",
    "doubt": "doubtful",
    "sancionado": "suspended",
    "sanctioned": "suspended",
}
# A igualdad de reloj, la foto de mercado es la del anuncio que se está viendo.
_SOURCE_RANK = {"market": 0, "squad": 1, "catalog": 2}

_INDEX: dict[str, list[dict[str, Any]]] | None = None
_STAMP: tuple[int, float] | None = None


def canonical_status(value: Any) -> str | None:
    """``ok`` / ``injured`` / ``doubtful`` / ``suspended``. El resto no es estado."""
    if not isinstance(value, str):
        return None
    folded = value.strip().lower()
    folded = _ALIASES.get(folded, folded)
    return folded if folded in _VALID else None


def _parse_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and value > 10_000_000:
        moment = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def resolve_status(observations: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Elige el estado de la observación más nueva.

    Cada observación trae ``status``, ``at`` (ISO, datetime o epoch) y
    ``source`` (``market``, ``squad`` o ``catalog``). Si hay alguna con fecha,
    las que no la tienen no participan. A la misma hora gana mercado, luego
    plantilla, luego catálogo.
    """
    ranked: list[tuple[datetime, int, str, str]] = []
    undated: list[tuple[int, str, str]] = []
    for obs in observations or []:
        if not isinstance(obs, dict):
            continue
        status = canonical_status(obs.get("status"))
        if status is None:
            continue
        source = obs.get("source") if isinstance(obs.get("source"), str) else ""
        rank = _SOURCE_RANK.get(source, 9)
        moment = _parse_at(obs.get("at"))
        if moment is None:
            undated.append((rank, source, status))
        else:
            ranked.append((moment, rank, source, status))
    if ranked:
        moment, _rank, source, status = min(ranked, key=lambda row: (-row[0].timestamp(), row[1]))
        return {"status": status, "at": moment.isoformat(), "source": source}
    if not undated:
        return None
    _rank, source, status = min(undated, key=lambda row: row[0])
    return {"status": status, "at": None, "source": source}


def apply_official_status(
    player: dict[str, Any],
    observations: list[dict[str, Any]] | None,
    *,
    photo_at: Any = None,
    source: str = "squad",
) -> None:
    """Escribe ``official_status`` solo cuando la foto nueva no coincide con la que ya hay.

    No sustituye ``player_status``: el once y el valorador siguen leyendo el
    campo con el que se calcularon.
    """
    if not isinstance(player, dict):
        return
    own = canonical_status(player.get("player_status"))
    extra = [dict(row) for row in observations or [] if isinstance(row, dict)]
    if own:
        extra.append({"status": own, "at": photo_at, "source": source})
    resolved = resolve_status(extra)
    if resolved is None:
        return
    status = resolved["status"]
    if status != own:
        player["official_status"] = status


def stamp_roster(
    players: Any,
    index: dict[str, list[dict[str, Any]]] | None,
    *,
    photo_at: Any = None,
    source: str = "squad",
) -> None:
    if not isinstance(players, list):
        return
    table = index or {}
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id")
        key = str(player_id) if player_id is not None else ""
        apply_official_status(player, table.get(key), photo_at=photo_at, source=source)


def _cache_root() -> Path:
    return Path(__file__).resolve().parents[1] / ".cache"


def _json_files() -> list[Path]:
    """Cuerpos de la caché. No llevan extensión: el nombre es el hash de la URL."""
    files: list[Path] = []
    root = _cache_root()
    for folder in ("bodies", "scraper_bodies"):
        base = root / folder
        if not base.is_dir():
            continue
        files.extend(path for path in base.iterdir() if path.is_file() and path.stat().st_size <= 40_000_000)
    return files


def _stamp() -> tuple[int, float]:
    files = _json_files()
    newest = 0.0
    for path in files:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return len(files), newest


def _photo_time(path: Path, envelope: Any) -> datetime:
    if isinstance(envelope, dict):
        for key in ("fetched_at", "saved_at", "stored_at"):
            moment = _parse_at(envelope.get(key))
            if moment is not None:
                return moment
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _unwrap(payload: Any) -> Any:
    current = payload
    for _ in range(3):
        if not isinstance(current, dict):
            break
        body = current.get("body")
        if isinstance(body, str) and body[:1] in "[{":
            try:
                current = json.loads(body)
                continue
            except json.JSONDecodeError:
                return None
        if isinstance(body, (dict, list)):
            current = body
            continue
        inner = current.get("payload")
        if isinstance(inner, (dict, list)) and ("source_url" in current or "ok" in current or "kind" in current):
            current = inner
            continue
        break
    return current


def _remember(bucket: dict[str, list[dict[str, Any]]], player_id: Any, status: Any, at: datetime, source: str) -> None:
    folded = canonical_status(status)
    if player_id is None or folded is None:
        return
    bucket.setdefault(str(player_id), []).append(
        {"status": folded, "at": at.isoformat(), "source": source}
    )


def _harvest(payload: Any, at: datetime, bucket: dict[str, list[dict[str, Any]]]) -> None:
    if isinstance(payload, dict):
        players = payload.get("players")
        if isinstance(players, list) and any(key in payload for key in ("teamMoney", "teamValue", "playersNumber")):
            for row in players:
                if not isinstance(row, dict):
                    continue
                master = row.get("playerMaster") if isinstance(row.get("playerMaster"), dict) else row
                _remember(bucket, master.get("id") or master.get("playerId"), master.get("playerStatus"), at, "squad")
            return
        if "activityTypeId" in payload or "salePrice" in payload:
            master = payload.get("playerMaster") if isinstance(payload.get("playerMaster"), dict) else {}
            if "salePrice" in payload:
                _remember(bucket, master.get("id"), master.get("playerStatus"), at, "market")
            return
        if "playerStatus" in payload and "id" in payload and "salePrice" not in payload:
            _remember(bucket, payload.get("id"), payload.get("playerStatus"), at, "catalog")
        return
    if not isinstance(payload, list) or not payload:
        return
    sample = next((row for row in payload if isinstance(row, dict)), None)
    if not isinstance(sample, dict):
        return
    if "activityTypeId" in sample:
        return
    if "salePrice" in sample or "expirationDate" in sample:
        for row in payload:
            if not isinstance(row, dict):
                continue
            master = row.get("playerMaster") if isinstance(row.get("playerMaster"), dict) else {}
            _remember(bucket, master.get("id"), master.get("playerStatus"), at, "market")
        return
    if "playerStatus" in sample and ("id" in sample or "playerId" in sample):
        for row in payload:
            if not isinstance(row, dict):
                continue
            _remember(bucket, row.get("id") or row.get("playerId"), row.get("playerStatus"), at, "catalog")


def cached_status_index() -> dict[str, list[dict[str, Any]]]:
    """Estados vistos en ``.cache/bodies`` y ``.cache/scraper_bodies``. Sin red."""
    global _INDEX, _STAMP
    try:
        stamp = _stamp()
    except OSError:
        return {}
    if _INDEX is not None and _STAMP == stamp:
        return _INDEX
    bucket: dict[str, list[dict[str, Any]]] = {}
    for path in _json_files():
        try:
            text = path.read_text(encoding="utf-8")
            if not text.lstrip()[:1] in "{[":
                continue
            payload = json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        at = _photo_time(path, payload)
        body = _unwrap(payload)
        if body is None:
            continue
        _harvest(body, at, bucket)
    _INDEX = bucket
    _STAMP = stamp
    return bucket

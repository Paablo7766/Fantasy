"""Jornada Perfecta: tip fantasy-native y racha desde el mercado embebido.

La página ``/mercado/`` inyecta ``const marketCaching=[...]``. El tip
(muyRecomendable, apuesta, …) actúa como contraste de proyección, no como
puntos OPTA.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from toolbox.matching import canonical_position
from toolbox.net import ExternalClient, ExternalHttpError

JP_MARKET_URL = "https://www.jornadaperfecta.com/mercado/?competition=laliga"
_MARKET_RE = re.compile(r"const\s+marketCaching\s*=\s*(\[.*?\]);", re.S)

# Escala 0–10 para contrastar expected_points sin mezclar unidades OPTA.
JP_TIP_SCORE = {
    "muyrecomendable": 8.0,
    "recomendable": 6.5,
    "apuesta": 5.5,
    "fondodearmario": 3.5,
    "parche": 2.5,
    "norecomendable": 1.5,
}

# Multiplicador suave sobre la proyección OPTA. Es una *variación relativa*
# (``JP_TIP_MULT - 1.0``) sobre el diferencial de nota, no un factor sobre la
# proyección: así una etiqueta de rol no puede destruir los puntos base de Opta.
JP_TIP_MULT = {
    "muyrecomendable": 1.06,
    "recomendable": 1.03,
    "apuesta": 1.0,
    "fondodearmario": 0.94,
    "parche": 0.9,
    "norecomendable": 0.85,
}

# Peso con el que el tip mueve la proyección: ±10 % de nota nunca baja del
# 90 % de los puntos Opta, que salen de minutos y acciones, no del rol.
JP_TIP_WEIGHT = 0.35
JP_TIP_MULT_FLOOR = 0.90


def jp_market_url() -> str:
    return os.getenv("JORNADA_PERFECTA_MARKET_URL", "").strip() or JP_MARKET_URL


def _fold_tip(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"[^a-z]", "", value.strip().lower())


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_market_caching(page: str) -> list[dict[str, Any]]:
    match = _MARKET_RE.search(page)
    if match is None:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("real_name") or item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        tip_raw = item.get("tip") if isinstance(item.get("tip"), str) else None
        tip_key = _fold_tip(tip_raw)
        score = JP_TIP_SCORE.get(tip_key) if tip_key else None
        mult = JP_TIP_MULT.get(tip_key) if tip_key else None
        racha = _as_float(item.get("racha"))
        rows.append(
            {
                "name": name.strip(),
                "source": "jornadaperfecta",
                "club": item.get("team") if isinstance(item.get("team"), str) else None,
                "position": canonical_position(str(item.get("position") or "")),
                "external_id": str(item["playerId"]) if item.get("playerId") is not None else None,
                "jp_tip": tip_raw,
                "jp_projected_points": score,
                "jp_multiplier": mult,
                "jp_racha": racha,
                "fitness": _fitness(item),
            }
        )
    return rows


def _fitness(item: dict[str, Any]) -> str | None:
    if str(item.get("injured") or "0") not in {"0", "false", "False", ""}:
        return "lesionado"
    if str(item.get("doubt") or "0") not in {"0", "false", "False", ""}:
        return "duda"
    status = item.get("status")
    if isinstance(status, str):
        folded = status.strip().lower()
        if folded in {"injured", "lesionado"}:
            return "lesionado"
        if folded in {"doubt", "duda"}:
            return "duda"
    return None


def tip_multiplier(tip: Any) -> float:
    """Factor de ajuste del tip sobre la proyección (1.0 si no hay tip)."""
    key = _fold_tip(tip)
    if not key:
        return 1.0
    return float(JP_TIP_MULT.get(key, 1.0))


def apply_tip_variation(base_points: float | None, tip: Any) -> float | None:
    """Aplica el tip como variación relativa acotada sobre los puntos Opta.

    ``fondodearmario``/``parche`` recortan el diferencial, no los puntos base:
    un suplente etiquetado no puede quedar con una proyección destrozada por
    una etiqueta de rol.
    """
    if base_points is None:
        return None
    mult = tip_multiplier(tip)
    if mult == 1.0:
        return base_points
    adjusted = float(base_points) * (1.0 + JP_TIP_WEIGHT * (mult - 1.0))
    floor = float(base_points) * JP_TIP_MULT_FLOOR
    return max(adjusted, floor)


def load_jornada_perfecta(
    client: ExternalClient,
    *,
    ttl: float,
    fresh: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = jp_market_url()
    try:
        body, cached = client.get_text(url, ttl=ttl, fresh=fresh)
    except ExternalHttpError as exc:
        return [], {"ok": False, "count": 0, "error": str(exc), "from_cache": False, "url": url}
    rows = parse_market_caching(body)
    return rows, {
        "ok": bool(rows),
        "count": len(rows),
        "error": None if rows else "Jornada Perfecta sin marketCaching.",
        "from_cache": cached,
        "url": url,
    }

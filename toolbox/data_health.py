"""Salud de datos por fuente y por campo, no por documento global.

El tablero ya devuelve ``sources`` con ``ok`` y ``count``. Lo que faltaba es
lo que el usuario necesita para decidir si puede confiar: cuándo se leyó
cada fuente, cuánto vive ese dato (TTL) y qué campo del motor queda cojo si
falla. Todo sale de la caché local, sin tocar la red.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root
from toolbox.scrapers import FF_FITNESS_URL, FF_MARKET_URL, FF_SANCTIONS_URL, FF_WARNINGS_URL, ScrapeTTL

# Cada fuente se agrupa por la decisión que rompe si falla. ``field`` es el
# campo del motor que queda sin dato; ``impact`` la frase que ve el usuario.
SOURCE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "laliga_market",
        "label": "Mercado LALIGA",
        "url": None,
        "ttl_key": "laliga_market",
        "field": "price_band / listings",
        "impact": "Sin mercado no hay pujas: la home se queda sin tarjetas de fichaje.",
        "critical": True,
    },
    {
        "id": "laliga_squads",
        "label": "Plantillas y caja",
        "url": None,
        "ttl_key": "laliga_squads",
        "field": "cash_eur / squads",
        "impact": "Sin caja ni plantillas no se puede comprobar la línea roja.",
        "critical": True,
    },
    {
        "id": "futbolfantasy_market",
        "label": "FF mercado",
        "url": FF_MARKET_URL,
        "ttl_key": "market",
        "field": "acceleration / p_titular",
        "impact": "Sin aceleración FF se pierde el motivo de revalorización.",
        "critical": False,
    },
    {
        "id": "futbolfantasy_lineups",
        "label": "FF alineaciones",
        "url": "https://www.futbolfantasy.com/laliga/posibles-alineaciones",
        "ttl_key": "market",
        "field": "p_titular / lineup_status",
        "impact": "Sin alineaciones el once se apoya en week_points (tope 55 %).",
        "critical": True,
    },
    {
        "id": "futbolfantasy_fitness",
        "label": "FF lesionados",
        "url": FF_FITNESS_URL,
        "ttl_key": "fitness",
        "field": "unavailable_reason",
        "impact": "Sin partes médicos no se veta a un lesionado.",
        "critical": False,
    },
    {
        "id": "futbolfantasy_sanctions",
        "label": "FF sanciones",
        "url": FF_SANCTIONS_URL,
        "ttl_key": "sanctions",
        "field": "unavailable_reason",
        "impact": "Sin sanciones puede entrar un jugador que no juega.",
        "critical": False,
    },
    {
        "id": "futbolfantasy_warnings",
        "label": "FF apercibidos",
        "url": FF_WARNINGS_URL,
        "ttl_key": "sanctions",
        "field": "warning",
        "impact": "Solo avisa de riesgo de sanción; no cambia la puja.",
        "critical": False,
    },
    {
        "id": "analiticafantasy_points",
        "label": "AF puntos / oráculo",
        "url": "https://www.analiticafantasy.com/fantasy-la-liga/predicciones",
        "ttl_key": "market",
        "field": "af_expected_points",
        "impact": "Sin AF el contraste de puntos queda solo en el motor propio.",
        "critical": True,
    },
    {
        "id": "analiticafantasy_ideal_bid",
        "label": "AF puja ideal",
        "url": "https://www.analiticafantasy.com/fantasy-la-liga/puja-ideal",
        "ttl_key": "market",
        "field": "af_max_bid",
        "impact": "Sin techo AF la puja se queda sin contraste externo.",
        "critical": False,
    },
    {
        "id": "own_intel_points",
        "label": "Motor propio (puntos)",
        "url": None,
        "ttl_key": "stats",
        "field": "own_expected_points",
        "impact": "Sin motor propio el once cae en OPTA base.",
        "critical": True,
    },
    {
        "id": "understat",
        "label": "Understat (xG)",
        "url": "https://understat.com/league/La_liga",
        "ttl_key": "stats",
        "field": "OPTA v2 / λ",
        "impact": "Sin xG la proyección pierde el componente de ataque.",
        "critical": True,
    },
    {
        "id": "fbref",
        "label": "FBref",
        "url": "https://fbref.com/en/comps/12/La-Liga-Stats",
        "ttl_key": "stats",
        "field": "OPTA v2 (duelos, pases)",
        "impact": "Enriquecimiento opcional: el motor sigue con Understat.",
        "critical": False,
    },
    {
        "id": "sofascore",
        "label": "Sofascore",
        "url": "https://api.sofascore.com/api/v1/unique-tournament/8/season/77559/top-players/overall",
        "ttl_key": "stats",
        "field": "nota media / forma",
        "impact": "Enriquecimiento opcional de forma.",
        "critical": False,
    },
    {
        "id": "jornadaperfecta",
        "label": "Jornada Perfecta",
        "url": "https://www.jornadaperfecta.com/mercado/?competition=laliga",
        "ttl_key": "market",
        "field": "multiplicador jp",
        "impact": "Sin JP se pierde el ajuste de recomendación.",
        "critical": False,
    },
)

# TTL del tablero de LALIGA, en segundos (toolbox/net.py).
_LALIGA_TTL = {"laliga_market": 2 * 60, "laliga_squads": 10 * 60}


def _ttl_for(key: str) -> float | None:
    if key in _LALIGA_TTL:
        return float(_LALIGA_TTL[key])
    clocks = ScrapeTTL.from_env()
    return float(getattr(clocks, key, 0.0)) or None


def _cache_hit(root: Path, url: str | None) -> dict[str, Any]:
    """Huella de la última lectura en caché local. Sin red.

    La caché guarda ``expires_at``, no el instante de escritura. Con el TTL
    declarado se deduce cuánto le queda al dato, que es lo que importa para
    decidir si sigue vivo.
    """
    if not url:
        return {"seconds_left": None}
    path = root / "scraper_bodies" / _sha(url)
    if not path.is_file():
        return {"seconds_left": None}
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seconds_left": None}
    if not isinstance(row, dict) or not isinstance(row.get("body"), str):
        return {"seconds_left": None}
    try:
        expires = float(row.get("expires_at"))
    except (TypeError, ValueError):
        return {"seconds_left": None}
    return {"seconds_left": round(max(0.0, expires - time.time()), 1)}


def _sha(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def build_field_health(
    sources: dict[str, Any] | None,
    *,
    fetched_at: str | None = None,
    root: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Une el estado que ya trae ``trends`` con la huella de la caché.

    ``sources`` es la fuente de verdad de ``ok``/``count``. La caché solo
    aporta el "hace cuánto". Una fuente que no viene en ``sources`` no se
    inventa: queda como ``no_leida``.

    ``extra`` cubre los bloques que no viven en ``trends.sources`` (mercado y
    plantillas de LALIGA). Sin ellos, dos fuentes críticas siempre saldrían
    vacías y el panel gritaría «no pujes» con el tablero entero leído.
    """
    repo = root or cache_root()
    raw = dict(sources) if isinstance(sources, dict) else {}
    for key, row in (extra or {}).items():
        if isinstance(row, dict) and key not in raw:
            raw[key] = row
    fields: list[dict[str, Any]] = []
    for spec in SOURCE_CATALOG:
        source_id = str(spec["id"])
        report = raw.get(source_id)
        report = report if isinstance(report, dict) else None
        ok = report.get("ok") if report is not None else None
        count = report.get("count") if isinstance(report, dict) else None
        error = report.get("error") if isinstance(report, dict) else None
        from_cache = report.get("from_cache") if isinstance(report, dict) else None
        cache_hit = _cache_hit(repo, spec.get("url"))
        seconds_left = cache_hit.get("seconds_left")
        if isinstance(report, dict) and isinstance(report.get("expires_in_seconds"), (int, float)):
            # Bloques del tablero (mercado/plantillas de LALIGA): no tienen
            # cuerpo en `scraper_bodies`, el que los lee declara su caducidad.
            seconds_left = report["expires_in_seconds"]
        remaining = seconds_left if isinstance(seconds_left, (int, float)) else None
        ttl = _ttl_for(str(spec["ttl_key"]))
        if isinstance(report, dict) and isinstance(report.get("ttl_seconds"), (int, float)):
            # Bloques del tablero: su vida real es la del snapshot que ve el
            # usuario, no el TTL de revalidación de red de la fuente.
            ttl = float(report["ttl_seconds"])
        if ok is None:
            status = "no_leida"
        elif ok is False:
            status = "error"
        elif remaining is not None and remaining <= 0:
            status = "caducada"
        else:
            status = "ok"
        fields.append(
            {
                "id": source_id,
                "label": spec["label"],
                "field": spec["field"],
                "impact": spec["impact"],
                "critical": bool(spec["critical"]),
                "status": status,
                "ok": ok,
                "count": count if isinstance(count, int) else None,
                "error": error if isinstance(error, str) and error.strip() else None,
                "from_cache": from_cache is True if isinstance(from_cache, bool) else None,
                "ttl_seconds": ttl,
                "ttl_label": _ttl_label(ttl),
                "expires_in_seconds": remaining,
                "expires_label": _expiry_label(remaining),
            }
        )
    broken = [row for row in fields if row["status"] in {"error", "caducada"}]
    missing = [row for row in fields if row["status"] == "no_leida"]
    # Caducada no es ceguera: el dato existe, solo pide refresco. Lo que anula
    # la confianza es un crítico con error o sin lectura.
    critical_broken = [row for row in fields if row["critical"] and row["status"] in {"error", "no_leida"}]
    stale_critical = [row for row in fields if row["critical"] and row["status"] == "caducada"]
    if critical_broken:
        status = "fail"
        headline = "Hay campos críticos sin dato: no pujes a ciegas"
    elif stale_critical:
        status = "warn"
        headline = "Datos completos pero caducados: refresca antes de mover caja"
    elif broken:
        status = "warn"
        headline = "Datos usables, con campos enriquecidos caídos"
    elif missing:
        status = "warn"
        headline = "Foto parcial: aún no se han leído todas las fuentes"
    else:
        status = "ok"
        headline = "Todas las fuentes leídas y dentro de TTL"
    return {
        "ok": True,
        "command": "data-health",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fetched_at": fetched_at if isinstance(fetched_at, str) else None,
        "status": status,
        "headline": headline,
        "fields": fields,
        "broken": [row["id"] for row in broken],
        "missing": [row["id"] for row in missing],
        "critical_broken": [row["id"] for row in critical_broken],
        "stale_critical": [row["id"] for row in stale_critical],
        "notes": [
            "Cada fuente declara su TTL y su campo. Un fallo de FBref no invalida la caja.",
            "La lectura se hace contra la caché local: este panel no gasta peticiones.",
        ],
    }


def _ttl_label(ttl: float | None) -> str:
    if ttl is None:
        return "—"
    if ttl < 3600:
        return f"{int(ttl // 60)} min"
    if ttl < 86400:
        return f"{int(ttl // 3600)} h"
    return f"{int(ttl // 86400)} d"


def _expiry_label(seconds: float | None) -> str:
    if seconds is None:
        return "sin lectura"
    if seconds <= 0:
        return "caducada"
    if seconds < 60:
        return f"caduca en {int(seconds)} s"
    if seconds < 3600:
        return f"caduca en {int(seconds // 60)} min"
    if seconds < 86400:
        return f"caduca en {int(seconds // 3600)} h"
    return f"caduca en {int(seconds // 86400)} d"

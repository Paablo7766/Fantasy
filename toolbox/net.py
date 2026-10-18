"""Cliente HTTP de LALIGA Fantasy.

Cada petición a la liga lleva las cabeceras del cliente web oficial y el bearer.
Un HTTP 429 espera ``Retry-After`` o una pausa exponencial y reintenta.
Un 401 renueva el access token una vez y repite la petición.

La API de Fantasy queda en solo lectura: este cliente solo envía GET. Un
POST, PUT, PATCH o DELETE hacia sus hosts se rechaza antes de salir.

La ruta de ligas del contrato es ``/api/v4/leagues``. El host histórico
``api-fantasy.llt-services.com`` devuelve 502; el mismo path responde en
``fantasy-api.llt-services.com``. El cliente prueba el host indicado y, si no
contesta, el host vivo y los paths de competición 2026/27, que son los que
traen mercado y ``buyoutClauseLockedEndTime``.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from toolbox.auth import league_id_from_env
from toolbox.cache import ResponseCache
from toolbox.normalize import (
    build_market_document,
    build_squads_document,
    empty_squad,
    leagues_from_payload,
    normalize_saved_lineup,
    normalize_squad,
    team_seeds,
)

LEAGUE_BASE = "https://api-fantasy.llt-services.com/api/v4/leagues"
LIVE_ORIGIN = "https://fantasy-api.llt-services.com"
LEGACY_ORIGIN = "https://api-fantasy.llt-services.com"
LIVE_LEAGUE_BASE = f"{LIVE_ORIGIN}/api/v4/leagues"
COMPETITION_BASE = f"{LIVE_ORIGIN}/api/v1/competition/1"

ALLOWED_NETLOCS = {
    "api-fantasy.llt-services.com",
    "fantasy-api.llt-services.com",
}
_READ_METHODS = frozenset({"GET", "HEAD"})

REQUIRED_HEADERS = {
    "Origin": "https://fantasy.laliga.com",
    "Referer": "https://fantasy.laliga.com/",
    "X-App": "Fantasy-web",
    "X-Lang": "es",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}

MAX_ATTEMPTS = 6
MAX_RETRY_AFTER_SECONDS = 180.0
MAX_SQUADS = 40
LEAGUE_TTL_SECONDS = 30 * 60
MARKET_TTL_SECONDS = 2 * 60
SQUAD_TTL_SECONDS = 10 * 60
ACTIVITY_TTL_SECONDS = 5 * 60
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_RETRY_UPSTREAM = {500, 502, 503, 504}


class FantasyHttpError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str = "http_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or {}


class TokenSource(Protocol):
    def authorization_value(self) -> str: ...

    def force_refresh(self) -> str: ...


def backoff_delay(attempt: int, retry_after: str | None, *, rng: random.Random | None = None) -> float:
    """Segundos a esperar tras un 429.

    Si llega ``Retry-After`` se respeta, con un techo. Si no, la espera es
    ``min(60, 2**attempt)`` más un jitter de hasta el 20 %.
    """
    parsed = _parse_retry_after(retry_after)
    if parsed is not None:
        return min(MAX_RETRY_AFTER_SECONDS, max(0.0, parsed))
    base = min(60.0, 2.0**attempt)
    roll = (rng or random).uniform(0.0, base * 0.2)
    return base + roll


def _parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0.0, (when - current).total_seconds())


def with_lang(url: str) -> str:
    if "x-lang=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}x-lang=es"


def refuse_fantasy_write(request: httpx.Request) -> None:
    """Corta cualquier escritura a la API de LALIGA Fantasy antes de enviarla."""
    host = (request.url.host or "").lower()
    if host not in ALLOWED_NETLOCS:
        return
    if request.method.upper() in _READ_METHODS:
        return
    raise FantasyHttpError(
        "Modo solo lectura: no se envían POST, PUT, PATCH ni DELETE a la API de LALIGA Fantasy.",
        code="read_only",
    )


def _install_read_only_guard(http: httpx.Client) -> None:
    hooks = http.event_hooks.setdefault("request", [])
    if refuse_fantasy_write not in hooks:
        hooks.append(refuse_fantasy_write)


def require_id(value: str, label: str) -> str:
    if not _ID.fullmatch(value):
        raise FantasyHttpError(f"{label} contiene caracteres no permitidos.", code="invalid_id")
    return urllib.parse.quote(value, safe="")


def league_list_urls() -> list[str]:
    """El path contractual es ``/api/v4/leagues``.

    Se prueba primero en ``fantasy-api``, que es el host que responde. La URL
    histórica ``api-fantasy.../api/v4/leagues`` queda de respaldo: hoy devuelve 502.
    """
    return [
        with_lang(LIVE_LEAGUE_BASE),
        with_lang(LEAGUE_BASE),
        with_lang(f"{COMPETITION_BASE}/leagues"),
    ]


def market_urls(league_id: str) -> list[str]:
    league = require_id(league_id, "league_id")
    return [
        with_lang(f"{COMPETITION_BASE}/league/{league}/market"),
        with_lang(f"{LIVE_ORIGIN}/api/v3/league/{league}/market"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/market"),
        with_lang(f"{LEGACY_ORIGIN}/api/v3/league/{league}/market"),
        with_lang(f"{LEAGUE_BASE}/{league}/market"),
    ]


def team_index_urls(league_id: str) -> list[str]:
    league = require_id(league_id, "league_id")
    return [
        with_lang(f"{COMPETITION_BASE}/leagues/{league}/standing"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/ranking"),
        with_lang(f"{LIVE_ORIGIN}/api/v5/leagues/{league}/ranking"),
        with_lang(f"{LEGACY_ORIGIN}/api/v4/leagues/{league}/ranking"),
        with_lang(f"{LEGACY_ORIGIN}/api/v5/leagues/{league}/ranking"),
        with_lang(f"{COMPETITION_BASE}/leagues/{league}/teams"),
    ]


def activity_urls(league_id: str) -> list[str]:
    """Historial de noticias y movimientos. El primero que responda gana.

    Si todos faltan, la caja reconstruida no se inventa: se queda en null.
    """
    league = require_id(league_id, "league_id")
    return [
        with_lang(f"{COMPETITION_BASE}/leagues/{league}/news"),
        with_lang(f"{COMPETITION_BASE}/league/{league}/news"),
        with_lang(f"{LIVE_ORIGIN}/api/v3/leagues/{league}/news"),
        with_lang(f"{LIVE_ORIGIN}/api/v3/league/{league}/activity"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/activity"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/news"),
        with_lang(f"{LEGACY_ORIGIN}/api/v3/leagues/{league}/news"),
        with_lang(f"{LEAGUE_BASE}/{league}/activity"),
    ]


def saved_lineup_urls(team_id: str) -> list[str]:
    """Once guardado en la app. No es el once que calcula el solver."""
    team = require_id(team_id, "team_id")
    return [with_lang(f"{COMPETITION_BASE}/teams/{team}/lineup")]


def team_urls(league_id: str, team_id: str) -> list[str]:
    league = require_id(league_id, "league_id")
    team = require_id(team_id, "team_id")
    return [
        with_lang(f"{COMPETITION_BASE}/leagues/{league}/teams/{team}"),
        with_lang(f"{LIVE_ORIGIN}/api/v3/leagues/{league}/teams/{team}"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/teams/{team}"),
        with_lang(f"{LEGACY_ORIGIN}/api/v3/leagues/{league}/teams/{team}"),
        with_lang(f"{LEAGUE_BASE}/{league}/teams/{team}"),
    ]


class LaligaClient:
    def __init__(
        self,
        tokens: TokenSource | None = None,
        cache: ResponseCache | None = None,
        http: httpx.Client | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if tokens is None:
            from toolbox.auth import TokenManager

            tokens = TokenManager()
        self._tokens = tokens
        self._owns_cache = cache is None
        self._cache = cache or ResponseCache()
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=False,
        )
        _install_read_only_guard(self._http)
        self._sleeper = sleeper or time.sleep

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
        if self._owns_cache:
            self._cache.close()

    def __enter__(self) -> LaligaClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def market_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]:
        ref, _leagues_url = self.resolve_league(league, fresh=fresh)
        source, payload = self._first_matching(
            market_urls(ref["league_id"]),
            ttl=MARKET_TTL_SECONDS,
            fresh=fresh,
            accept=_is_market,
        )
        return build_market_document(
            league_id=ref["league_id"],
            league_name=ref.get("name"),
            source_url=source,
            payload=payload,
            fetched_at=_now(),
        )

    def squads_document(self, league: str | None, *, fresh: bool) -> dict[str, Any]:
        ref, _leagues_url = self.resolve_league(league, fresh=fresh)
        index_url, index_payload = self._first_matching(
            team_index_urls(ref["league_id"]),
            ttl=SQUAD_TTL_SECONDS,
            fresh=fresh,
            accept=lambda payload: bool(team_seeds(payload)),
        )
        all_seeds = team_seeds(index_payload)
        seeds = all_seeds[:MAX_SQUADS]
        truncated = len(all_seeds) > MAX_SQUADS
        squads: list[dict[str, Any]] = []
        for seed in seeds:
            embedded = seed.get("embedded")
            if isinstance(embedded, dict):
                squads.append(
                    normalize_squad(
                        embedded,
                        seed=seed,
                        own_team_id=ref.get("own_team_id"),
                        source_url=index_url,
                    )
                )
                continue
            try:
                source, payload = self._first_matching(
                    team_urls(ref["league_id"], str(seed["team_id"])),
                    ttl=SQUAD_TTL_SECONDS,
                    fresh=fresh,
                    accept=lambda body: isinstance(body, dict) and isinstance(body.get("players"), list),
                )
            except FantasyHttpError as exc:
                squads.append(empty_squad(seed, own_team_id=ref.get("own_team_id"), message=str(exc)))
                continue
            if not isinstance(payload, dict):
                squads.append(empty_squad(seed, own_team_id=ref.get("own_team_id"), message="La plantilla no es un objeto."))
                continue
            squads.append(
                normalize_squad(
                    payload,
                    seed=seed,
                    own_team_id=ref.get("own_team_id"),
                    source_url=source,
                )
            )
        document = build_squads_document(
            league_id=ref["league_id"],
            league_name=ref.get("name"),
            index_url=index_url,
            squads=squads,
            fetched_at=_now(),
        )
        document["truncated"] = truncated
        document["index_empty"] = len(seeds) == 0
        return document

    def saved_lineup(self, team_id: str, *, fresh: bool) -> dict[str, Any]:
        """Lee por GET el once que la app móvil tiene guardado."""
        try:
            source, payload = self._first_matching(
                saved_lineup_urls(team_id),
                ttl=MARKET_TTL_SECONDS,
                fresh=fresh,
                accept=lambda body: isinstance(body, dict) and isinstance(body.get("formation"), dict),
            )
        except FantasyHttpError as exc:
            return {
                "ok": False,
                "source_url": None,
                "formation": None,
                "xi": [],
                "bench": [],
                "updated_at": None,
                "error": exc.code,
            }
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "source_url": source,
                "formation": None,
                "xi": [],
                "bench": [],
                "updated_at": None,
                "error": "unexpected_shape",
            }
        return normalize_saved_lineup(payload, source_url=source)

    def activity_payload(self, league_id: str, *, fresh: bool) -> dict[str, Any]:
        """Lee el historial de la liga. Un 404 prueba el siguiente path.

        Un 401 o un 429 se propagan: no se disfrazan de historial vacío.
        """
        try:
            source, payload = self._first_matching(
                activity_urls(league_id),
                ttl=ACTIVITY_TTL_SECONDS,
                fresh=fresh,
                accept=_is_activity,
            )
        except FantasyHttpError as exc:
            if exc.code in {"unauthorized", "auth_required", "rate_limited"}:
                raise
            return {
                "ok": False,
                "source_url": None,
                "payload": None,
                "error": exc.code,
                "attempts": (exc.details or {}).get("attempts") or [],
            }
        return {"ok": True, "source_url": source, "payload": payload, "error": None, "attempts": []}

    def resolve_league(self, explicit: str | None, *, fresh: bool) -> tuple[dict[str, Any], str]:
        requested = (explicit or league_id_from_env() or "").strip()
        if requested:
            require_id(requested, "league_id")
        source, leagues = self._load_leagues(fresh=fresh)
        if requested:
            for league in leagues:
                if league["league_id"] == requested:
                    return league, source
            if leagues:
                raise FantasyHttpError(
                    "Esa liga no está en la cuenta. Revisa LEAGUE_ID o --league.",
                    code="league_not_found",
                    details={"leagues": leagues},
                )
            return {"league_id": requested, "name": None, "own_team_id": None}, source or LEAGUE_BASE
        if len(leagues) == 1:
            return leagues[0], source
        if not leagues:
            raise FantasyHttpError("La cuenta no tiene ligas visibles.", code="league_not_found")
        raise FantasyHttpError(
            "Hay varias ligas. Define LEAGUE_ID en .env o pasa --league.",
            code="league_required",
            details={"leagues": leagues},
        )

    def get_json(
        self,
        url: str,
        *,
        ttl: float,
        fresh: bool,
        upstream_retries: int = 2,
    ) -> Any:
        self._ensure_allowed(url)
        if not fresh and ttl > 0:
            cached = self._cache.get_json(url)
            if cached is not None:
                return cached
        attempt = 0
        upstream_used = 0
        refreshed = False
        last_network: FantasyHttpError | None = None
        while attempt < MAX_ATTEMPTS:
            try:
                response = self._send(url)
            except httpx.TransportError as exc:
                last_network = FantasyHttpError(f"Error de red al llamar a la API: {exc.__class__.__name__}.", code="network")
                if attempt == MAX_ATTEMPTS - 1:
                    raise last_network from exc
                self._sleeper(backoff_delay(attempt, None))
                attempt += 1
                continue
            status = response.status_code
            if status in {301, 302, 303, 307, 308}:
                raise FantasyHttpError("Redirección no resuelta.", status=status, code="redirect")
            if status == 401 and not refreshed:
                self._tokens.force_refresh()
                refreshed = True
                continue
            if status == 401:
                raise FantasyHttpError(
                    "La API sigue respondiendo 401 después de renovar el token.",
                    status=401,
                    code="unauthorized",
                )
            if status == 429:
                if attempt == MAX_ATTEMPTS - 1:
                    raise FantasyHttpError(
                        "La API ha limitado las peticiones (HTTP 429) tras varios reintentos.",
                        status=429,
                        code="rate_limited",
                    )
                self._sleeper(backoff_delay(attempt, response.headers.get("Retry-After")))
                attempt += 1
                continue
            if status in _RETRY_UPSTREAM:
                if upstream_used >= upstream_retries:
                    raise FantasyHttpError(
                        f"El host de la API respondió HTTP {status}.",
                        status=status,
                        code="upstream",
                    )
                self._sleeper(min(2.0, backoff_delay(upstream_used, response.headers.get("Retry-After"))))
                upstream_used += 1
                continue
            if status in {404, 410}:
                raise FantasyHttpError("Recurso no encontrado.", status=status, code="not_found")
            if status >= 400:
                raise FantasyHttpError(
                    f"La API respondió HTTP {status}.",
                    status=status,
                    code="http_error",
                )
            payload = _decode_json(response)
            if ttl > 0 and payload is not None:
                self._cache.put_json(url, payload, ttl)
            return payload
        if last_network is not None:
            raise last_network
        raise FantasyHttpError("Sin respuesta de la API.", code="network")

    def _load_leagues(self, *, fresh: bool) -> tuple[str, list[dict[str, Any]]]:
        try:
            source, payload = self._first_matching(
                league_list_urls(),
                ttl=LEAGUE_TTL_SECONDS,
                fresh=fresh,
                accept=lambda body: len(leagues_from_payload(body)) > 0,
            )
        except FantasyHttpError as exc:
            if exc.code == "endpoint_not_found":
                return LEAGUE_BASE, []
            raise
        return source, leagues_from_payload(payload)

    def _first_matching(
        self,
        urls: list[str],
        *,
        ttl: float,
        fresh: bool,
        accept: Callable[[Any], bool],
    ) -> tuple[str, Any]:
        misses: list[dict[str, Any]] = []
        last_error: FantasyHttpError | None = None
        for url in urls:
            try:
                payload = self.get_json(url, ttl=ttl, fresh=fresh, upstream_retries=1)
            except FantasyHttpError as exc:
                if exc.status in {404, 410} or exc.code in {"network", "upstream", "invalid_json"}:
                    misses.append({"url": url, "status": exc.status, "code": exc.code})
                    last_error = exc
                    continue
                raise
            if accept(payload):
                return url, payload
            misses.append({"url": url, "status": 200, "code": "unexpected_shape"})
        if last_error is not None and all(item["code"] != "unexpected_shape" for item in misses):
            raise FantasyHttpError(
                str(last_error),
                status=last_error.status,
                code="endpoint_not_found",
                details={"attempts": misses},
            )
        raise FantasyHttpError(
            "Ningún endpoint devolvió el recurso esperado.",
            code="endpoint_not_found",
            details={"attempts": misses},
        )

    def _send(self, url: str) -> httpx.Response:
        self._ensure_allowed(url)
        headers = dict(REQUIRED_HEADERS)
        headers["Authorization"] = self._tokens.authorization_value()
        return self._http.get(url, headers=headers)

    @staticmethod
    def _ensure_allowed(url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in ALLOWED_NETLOCS:
            raise FantasyHttpError("URL fuera de los dominios de LALIGA Fantasy.", code="forbidden_url")


def _decode_json(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise FantasyHttpError("La API no devolvió JSON.", status=response.status_code, code="invalid_json") from exc


def _is_activity(payload: Any) -> bool:
    if isinstance(payload, list):
        return True
    if isinstance(payload, dict):
        for key in ("elements", "items", "news", "activity", "transactions", "data", "content", "events"):
            if isinstance(payload.get(key), list):
                return True
    return False


def _is_market(payload: Any) -> bool:
    if isinstance(payload, list):
        return True
    if isinstance(payload, dict):
        for key in ("elements", "items", "players", "market", "data", "content"):
            if isinstance(payload.get(key), list):
                return True
        if "playerMaster" in payload or "salePrice" in payload:
            return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Presupuesto del wrapper público de Transfermarkt: 2 peticiones / 3 segundos / IP.
TRANSFERMARKT_MAX_REQUESTS = 2
TRANSFERMARKT_WINDOW_SECONDS = 3.0
TRANSFERMARKT_API_BASE = "https://transfermarkt-api.fly.dev"

EXTERNAL_HOSTS = frozenset(
    {
        "www.futbolfantasy.com",
        "futbolfantasy.com",
        "www.analiticafantasy.com",
        "analiticafantasy.com",
        "fbref.com",
        "www.fbref.com",
        "api.sofascore.com",
        "www.sofascore.com",
        "sofascore.com",
        "tmapi.transfermarkt.technology",
        "tmapi-alpha.transfermarkt.technology",
        "transfermarkt-api.fly.dev",
    }
)

_LIMITERS: dict[str, "SlidingWindowLimiter"] = {}
_LIMITERS_GUARD = threading.Lock()


class ExternalHttpError(FantasyHttpError):
    """Fallo de una fuente externa. No lleva bearer ni cuerpo de la respuesta."""


class SlidingWindowLimiter:
    """Como mucho ``max_calls`` adquisiciones por identidad en cada ventana.

    La identidad es la IP de salida. El reloj tiene que avanzar cuando
    ``sleeper`` vuelve; si no, se aborta en lugar de quedar en un bucle.
    """

    def __init__(
        self,
        *,
        max_calls: int,
        window_seconds: float,
        sleeper: Callable[[float], None],
        clock: Callable[[], float],
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls tiene que ser positivo.")
        if window_seconds <= 0:
            raise ValueError("window_seconds tiene que ser positivo.")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._sleeper = sleeper
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, identity: str = "local") -> float:
        slept = 0.0
        with self._lock:
            while True:
                now = float(self._clock())
                hits = [stamp for stamp in self._hits.get(identity, []) if now - stamp < self.window_seconds]
                if len(hits) < self.max_calls:
                    hits.append(now)
                    self._hits[identity] = hits
                    return slept
                wait = self.window_seconds - (now - hits[0])
                if wait < 0:
                    wait = 0.0
                self._sleeper(wait)
                slept += wait
                if wait > 0 and float(self._clock()) <= now:
                    raise ExternalHttpError(
                        "El reloj del rate-limit no avanza.",
                        code="rate_limit",
                    )


def shared_transfermarkt_limiter(
    identity: str,
    *,
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> SlidingWindowLimiter:
    """Un presupuesto por IP, compartido por todos los clientes del proceso."""
    with _LIMITERS_GUARD:
        found = _LIMITERS.get(identity)
        if found is None:
            found = SlidingWindowLimiter(
                max_calls=TRANSFERMARKT_MAX_REQUESTS,
                window_seconds=TRANSFERMARKT_WINDOW_SECONDS,
                sleeper=sleeper,
                clock=clock,
            )
            _LIMITERS[identity] = found
        return found


def transfermarkt_api_base() -> str:
    raw = os.getenv("TRANSFERMARKT_API_BASE", "").strip()
    return raw or TRANSFERMARKT_API_BASE


def is_transfermarkt_host(netloc: str) -> bool:
    host = netloc.lower().split(":")[0]
    if host in {"transfermarkt-api.fly.dev", "tmapi.transfermarkt.technology", "tmapi-alpha.transfermarkt.technology"}:
        return True
    if host.endswith(".transfermarkt.technology"):
        return True
    configured = urllib.parse.urlparse(transfermarkt_api_base()).netloc.lower().split(":")[0]
    return bool(configured) and host == configured


class ExternalClient:
    """GET de HTML o JSON para fuentes de inteligencia, con caché y reintentos.

    No envía el bearer de LALIGA. Transfermarkt espera en la ventana de
    2 peticiones cada 3 segundos antes de salir a la red. Un acierto de
    caché no consume presupuesto.
    """

    def __init__(
        self,
        cache: ResponseCache | None = None,
        http: httpx.Client | None = None,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        transfermarkt_limiter: SlidingWindowLimiter | None = None,
        client_ip: str | None = None,
    ) -> None:
        self._owns_cache = cache is None
        self._cache = cache or ResponseCache()
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=True,
            headers={
                "User-Agent": REQUIRED_HEADERS["User-Agent"],
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self.client_ip = (client_ip or os.getenv("FANTASY_CLIENT_IP", "") or "local").strip() or "local"
        if transfermarkt_limiter is None:
            self._tm_limiter = shared_transfermarkt_limiter(
                self.client_ip,
                sleeper=self._sleeper,
                clock=self._clock,
            )
        else:
            self._tm_limiter = transfermarkt_limiter

    @property
    def root(self) -> Path:
        return self._cache.root

    @property
    def transfermarkt_budget(self) -> tuple[int, float]:
        return self._tm_limiter.max_calls, self._tm_limiter.window_seconds

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
        if self._owns_cache:
            self._cache.close()

    def __enter__(self) -> ExternalClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_text(self, url: str, *, ttl: float, fresh: bool) -> tuple[str, bool]:
        self._ensure_allowed(url)
        if not fresh and ttl > 0:
            cached = self._cache.get_page(url)
            if cached is not None:
                return cached, True
        body = self._request(url)
        if _looks_blocked(body):
            raise ExternalHttpError("La fuente ha servido una página de bloqueo.", code="blocked")
        if ttl > 0:
            self._cache.put_page(url, body, ttl)
        return body, False

    def get_json(self, url: str, *, ttl: float, fresh: bool) -> tuple[Any, bool]:
        self._ensure_allowed(url)
        if not fresh and ttl > 0:
            cached = self._cache.get_json(url)
            if cached is not None:
                return cached, True
        body = self._request(url)
        if _looks_blocked(body):
            raise ExternalHttpError("La fuente ha servido una página de bloqueo.", code="blocked")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ExternalHttpError("La fuente no devolvió JSON.", code="invalid_json") from exc
        if ttl > 0 and payload is not None:
            self._cache.put_json(url, payload, ttl)
        return payload, False

    def _request(self, url: str) -> str:
        attempt = 0
        last_network: ExternalHttpError | None = None
        while attempt < 4:
            self._acquire_if_needed(url)
            try:
                response = self._http.get(url)
            except httpx.TransportError as exc:
                last_network = ExternalHttpError(
                    f"Error de red al consultar la fuente: {exc.__class__.__name__}.",
                    code="network",
                )
                if attempt == 3:
                    raise last_network from exc
                self._sleeper(backoff_delay(attempt, None))
                attempt += 1
                continue
            status = response.status_code
            if status == 429:
                if attempt == 3:
                    raise ExternalHttpError(
                        "La fuente ha limitado las peticiones (HTTP 429).",
                        status=429,
                        code="rate_limited",
                    )
                self._sleeper(backoff_delay(attempt, response.headers.get("Retry-After")))
                attempt += 1
                continue
            if status in _RETRY_UPSTREAM:
                if attempt == 3:
                    raise ExternalHttpError(
                        f"La fuente respondió HTTP {status}.",
                        status=status,
                        code="upstream",
                    )
                self._sleeper(min(2.0, backoff_delay(attempt, None)))
                attempt += 1
                continue
            if status in {401, 403}:
                raise ExternalHttpError(
                    f"La fuente ha denegado la petición (HTTP {status}).",
                    status=status,
                    code="forbidden",
                )
            if status in {404, 410}:
                raise ExternalHttpError("Recurso no encontrado.", status=status, code="not_found")
            if status >= 400:
                raise ExternalHttpError(
                    f"La fuente respondió HTTP {status}.",
                    status=status,
                    code="http_error",
                )
            return response.text
        if last_network is not None:
            raise last_network
        raise ExternalHttpError("Sin respuesta de la fuente.", code="network")

    def _acquire_if_needed(self, url: str) -> None:
        host = urllib.parse.urlparse(url).netloc
        if is_transfermarkt_host(host):
            self._tm_limiter.acquire(self.client_ip)

    def _ensure_allowed(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower().split(":")[0]
        allowed = host in EXTERNAL_HOSTS or is_transfermarkt_host(host)
        if parsed.scheme != "https" or not allowed:
            raise ExternalHttpError("URL fuera de las fuentes de inteligencia.", code="forbidden_url")


def _looks_blocked(body: str) -> bool:
    head = body[:2000].lower()
    return "just a moment" in head or "cf-browser-verification" in head or "attention required" in head

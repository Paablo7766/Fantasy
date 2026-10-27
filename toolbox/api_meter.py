"""Ritmo real de llamadas salientes del proceso.

El tablero habla con LALIGA, con varios scrapers, con el wrapper de
Transfermarkt y con el proveedor de login. Este modulo no estima: apunta cada
peticion HTTP que sale de verdad, con su fuente, su codigo y su duracion, y
resume los ultimos minutos. Con eso la interfaz puede decir «ahora voy a 18
llamadas/min y el riesgo es bajo» sin inventarse el numero.

Las bandas de ``RATE_BANDS`` son heuristicas de presentacion, no un cupo
publicado por ninguna fuente: una pasada completa del tablero (mercado,
plantillas, historial y scrapers) ronda el centenar de llamadas, asi que
30/min es un ritmo normal de trabajo y mas de 100/min sostenido es un pico.
El riesgo de bloqueo se decide con evidencia —HTTP 429, reintentos y
concurrencia— y no con el volumen a secas.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from collections import deque
from datetime import datetime, timezone
from typing import Any

# Retencion de eventos en RAM. Una hora cubre cualquier ventana de decision;
# 20 000 eventos son unos pocos MB y evitan crecer sin techo.
MAX_EVENTS = 20_000
RETENTION_SECONDS = 3600.0
# (segundos, etiqueta)
WINDOWS: tuple[tuple[int, str], ...] = ((60, "1 min"), (600, "10 min"), (3600, "1 h"))
# Llamadas por minuto -> etiqueta de volumen. Solo orienta; no es un limite.
RATE_BANDS: tuple[tuple[float, str], ...] = (
    (30.0, "bajo"),
    (60.0, "normal"),
    (100.0, "alto"),
    (float("inf"), "muy alto"),
)
# Un pico de conexiones simultaneas es lo que mas se parece a un bot. El
# cliente de plantillas ya se limita a 3 hilos por este motivo.
CONCURRENCY_WARN = 6
RETRY_RATIO_WARN = 0.10
SUSTAINED_CALLS_WARN = 900  # 90/min durante 10 min
ERROR_RATIO_ALTO = 0.30
TIMELINE_MINUTES = 12
# Margen para considerar que un fallo se resolvio solo: net.py prueba varios
# hosts hasta acertar, asi que un 502 seguido de un 200 es el camino normal.
RECOVERY_GRACE_SECONDS = 20.0

# Cupos documentados. Solo Transfermarkt publica uno en este proyecto; el
# resto se mide, no se compara con una cifra inventada.
BUDGETS: dict[str, dict[str, float]] = {
    "transfermarkt": {"calls": 2, "window_seconds": 3.0, "per_minute": 40.0},
}

_SOURCE_LABELS: dict[str, str] = {
    "laliga": "LALIGA Fantasy",
    "auth": "Login LALIGA",
    "transfermarkt": "Transfermarkt",
    "fbref": "FBref",
    "sofascore": "Sofascore",
    "understat": "Understat",
    "futbolfantasy": "Futbol Fantasy",
    "analiticafantasy": "Analitica Fantasy",
    "jornadaperfecta": "Jornada Perfecta",
    "predicted11": "Predicted11",
    "odds": "The Odds API",
}

# Se compara por subcadena del host, en este orden.
_HOST_RULES: tuple[tuple[str, str], ...] = (
    ("llt-services.com", "laliga"),
    ("laliga.es", "auth"),
    ("transfermarkt", "transfermarkt"),
    ("fbref.com", "fbref"),
    ("sofascore.com", "sofascore"),
    ("understat.com", "understat"),
    ("futbolfantasy.com", "futbolfantasy"),
    ("analiticafantasy.com", "analiticafantasy"),
    ("jornadaperfecta.com", "jornadaperfecta"),
    ("predicted11.com", "predicted11"),
    ("the-odds-api.com", "odds"),
)

RISK_RULES: tuple[str, ...] = (
    "Un HTTP 429 en los ultimos 10 min ya es evidencia de que la fuente frena.",
    "Cada reintento cuenta como llamada: el cliente repite hasta 6 veces por peticion.",
    "Transfermarkt esta limitado a 2 peticiones cada 3 s (40/min); el resto no publica cupo.",
    "El volumen solo orienta: una pasada completa del tablero ronda el centenar de llamadas.",
)


class _Event:
    """Una llamada saliente. ``cached`` marca un acierto de cache, no una peticion."""

    __slots__ = ("ts", "source", "host", "status", "retry", "cached", "duration_ms", "via", "error")

    def __init__(
        self,
        *,
        ts: float,
        source: str,
        host: str,
        status: int | None,
        retry: bool,
        cached: bool,
        duration_ms: float,
        via: str,
        error: str | None,
    ) -> None:
        self.ts = ts
        self.source = source
        self.host = host
        self.status = status
        self.retry = retry
        self.cached = cached
        self.duration_ms = duration_ms
        self.via = via
        self.error = error


# Un 404 al probar un endpoint de respaldo es parte del contrato, no un fallo
# de la fuente. Un 401/403 es sesion o bloqueo de la fuente, y un 5xx o una
# caida de red es inestabilidad: ni uno ni otro son ritmo excesivo.
_NOT_FOUND_STATUSES = frozenset({404, 410})
_AUTH_STATUSES = frozenset({401, 403})


def _is_not_found_status(status: int | None) -> bool:
    return status in _NOT_FOUND_STATUSES


def _is_auth_status(status: int | None) -> bool:
    return status in _AUTH_STATUSES


def _is_server_failure(status: int | None) -> bool:
    if status is None:
        return True
    if status in _NOT_FOUND_STATUSES or status in _AUTH_STATUSES:
        return False
    return status >= 400


def _is_failure_status(status: int | None) -> bool:
    return _is_auth_status(status) or _is_server_failure(status)


def _empty_totals() -> dict[str, int]:
    return {
        "calls": 0,
        "cache_hits": 0,
        "errors": 0,
        "not_found": 0,
        "auth": 0,
        "rate_limited": 0,
        "retries": 0,
    }


def _status_mix(events: list[_Event]) -> dict[str, int]:
    """Códigos HTTP vistos, para explicar de dónde sale un error."""
    mix: dict[str, int] = {}
    for event in events:
        if event.cached:
            continue
        key = str(event.status) if event.status is not None else (event.error or "red")
        mix[key] = mix.get(key, 0) + 1
    return dict(sorted(mix.items(), key=lambda item: (-item[1], item[0])))


def _succeeded(event: _Event) -> bool:
    return event.status is not None and event.status < 400


def _recovered_ids(events: list[_Event]) -> set[int]:
    """``id`` de los fallos que la propia fuente arregló después, dentro del margen.

    ``net.py`` recorre varios hosts hasta que uno responde: un 502 seguido de
    un 200 en el mismo segundo es el camino normal, no una fuente rota.
    """
    by_source: dict[str, list[_Event]] = {}
    for event in events:
        if not event.cached:
            by_source.setdefault(event.source, []).append(event)
    recovered: set[int] = set()
    for group in by_source.values():
        successes = [event.ts for event in group if _succeeded(event)]
        if not successes:
            continue
        for event in group:
            if _succeeded(event) or event.status == 429 or _is_auth_status(event.status):
                continue
            if _is_not_found_status(event.status):
                continue
            if any(0.0 <= moment - event.ts <= RECOVERY_GRACE_SECONDS for moment in successes):
                recovered.add(id(event))
    return recovered


def _recovered_failures(events: list[_Event]) -> int:
    return len(_recovered_ids(events))


_lock = threading.RLock()
_events: deque[_Event] = deque(maxlen=MAX_EVENTS)
_in_flight: dict[str, int] = {}
_peaks: deque[tuple[float, int]] = deque()
_totals: dict[str, int] = _empty_totals()
_started_at = time.time()


def source_for_url(url: str) -> tuple[str, str]:
    """``(fuente, host)`` de una URL. Una fuente desconocida se etiqueta con su host."""
    host = (urllib.parse.urlparse(url).netloc or "").lower().split(":")[0]
    for needle, source in _HOST_RULES:
        if needle in host:
            return source, host
    return (host or "otros"), host


def source_label(source: str) -> str:
    return _SOURCE_LABELS.get(source, source.replace("_", " ").capitalize())


def _prune(now: float) -> None:
    floor = now - RETENTION_SECONDS
    while _events and _events[0].ts < floor:
        _events.popleft()
    while _peaks and _peaks[0][0] < floor:
        _peaks.popleft()


def _total_in_flight() -> int:
    return sum(_in_flight.values())


def _begin(source: str) -> None:
    now = time.time()
    with _lock:
        _in_flight[source] = _in_flight.get(source, 0) + 1
        _peaks.append((now, _total_in_flight()))


def _end(
    *,
    source: str,
    host: str,
    status: int | None,
    retry: bool,
    via: str,
    duration_ms: float,
    error: str | None,
    now: float | None = None,
) -> None:
    stamp = time.time() if now is None else now
    with _lock:
        if _in_flight.get(source):
            _in_flight[source] -= 1
            if _in_flight[source] <= 0:
                _in_flight.pop(source, None)
        _events.append(
            _Event(
                ts=stamp,
                source=source,
                host=host,
                status=status,
                retry=retry,
                cached=False,
                duration_ms=duration_ms,
                via=via,
                error=error,
            )
        )
        _totals["calls"] += 1
        if retry:
            _totals["retries"] += 1
        if _is_not_found_status(status):
            _totals["not_found"] += 1
        elif _is_auth_status(status):
            _totals["auth"] += 1
        elif _is_server_failure(status):
            _totals["errors"] += 1
        if status == 429:
            _totals["rate_limited"] += 1
        _prune(stamp)


def record_call(
    *,
    url: str | None = None,
    source: str | None = None,
    host: str = "",
    status: int | None = None,
    retry: bool = False,
    via: str = "http",
    duration_ms: float = 0.0,
    error: str | None = None,
    now: float | None = None,
) -> None:
    """Apunta una llamada ya terminada. Sin ``source`` se deduce de ``url``."""
    resolved_source, resolved_host = (source, host) if source else source_for_url(url or "")
    _end(
        source=resolved_source or "otros",
        host=resolved_host or host,
        status=status,
        retry=retry,
        via=via,
        duration_ms=duration_ms,
        error=error,
        now=now,
    )


def record_cache_hit(*, url: str | None = None, source: str | None = None, host: str = "") -> None:
    """Un acierto de cache no gasta peticion, pero interesa saber cuantas evita."""
    resolved_source, resolved_host = (source, host) if source else source_for_url(url or "")
    stamp = time.time()
    with _lock:
        _events.append(
            _Event(
                ts=stamp,
                source=resolved_source or "otros",
                host=resolved_host or host,
                status=None,
                retry=False,
                cached=True,
                duration_ms=0.0,
                via="cache",
                error=None,
            )
        )
        _totals["cache_hits"] += 1
        _prune(stamp)


class Call:
    """Context manager que mide una peticion y la apunta al salir.

    ``probe.status = response.status_code`` antes de salir del bloque. Si el
    bloque lanza, la llamada se apunta igual como error: una peticion que
    murio en la red tambien ha salido.
    """

    __slots__ = ("source", "host", "retry", "via", "status", "error", "_started")

    def __init__(self, source: str, host: str, *, retry: bool = False, via: str = "http") -> None:
        self.source = source
        self.host = host
        self.retry = retry
        self.via = via
        self.status: int | None = None
        self.error: str | None = None
        self._started = 0.0

    def __enter__(self) -> Call:
        self._started = time.monotonic()
        _begin(self.source)
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, _tb: Any) -> bool:
        if exc_type is not None and self.status is None:
            code = getattr(exc, "code", None)
            self.error = str(code) if code else getattr(exc_type, "__name__", "error")
        _end(
            source=self.source,
            host=self.host,
            status=self.status,
            retry=self.retry,
            via=self.via,
            duration_ms=max(0.0, (time.monotonic() - self._started) * 1000.0),
            error=self.error,
        )
        return False


def call(
    *,
    url: str | None = None,
    source: str | None = None,
    host: str = "",
    retry: bool = False,
    via: str = "http",
) -> Call:
    resolved_source, resolved_host = (source, host) if source else source_for_url(url or "")
    return Call(resolved_source or "otros", resolved_host or host, retry=retry, via=via)


def reset() -> None:
    """Vacia los contadores. Solo para pruebas y para cortes manuales."""
    global _started_at
    with _lock:
        _events.clear()
        _in_flight.clear()
        _peaks.clear()
        for key in _totals:
            _totals[key] = 0
        _started_at = time.time()


def calls_since(since_ts: float) -> dict[str, Any]:
    """Trabajo hecho desde un instante (epoch), separando red de caché.

    La usa el estado del refresco para decir «esta pasada lleva 37 llamadas y
    ahora está en LALIGA». Es la única prueba visible de que la descarga
    avanza: sin esto, un POST de media hora parece colgado. Solo lee RAM.

    ``calls`` cuenta **peticiones que salieron a la red** y ``cache_hits`` las
    que se resolvieron en disco o en memoria. La distinción no es cosmética: en
    ``development`` (air-gap) el cliente no abre un solo socket y todo el
    refresco son aciertos de caché. Si se sumaran, el panel diría «63 llamadas»
    en un proceso que no ha llamado a nadie; si solo se contaran las de red, el
    contador se quedaría clavado en 0 y parecería colgado. El panel necesita las
    dos cifras para explicar qué está pasando de verdad.
    """
    stamp = time.time()
    with _lock:
        _prune(stamp)
        window = [event for event in _events if event.ts >= since_ts]
        in_flight = {source: count for source, count in _in_flight.items() if count > 0}
    events = [event for event in window if not event.cached]
    cache_hits = len(window) - len(events)
    by_source: dict[str, int] = {}
    cached_by_source: dict[str, int] = {}
    last_source: tuple[float, str] | None = None
    for event in window:
        if event.cached:
            cached_by_source[event.source] = cached_by_source.get(event.source, 0) + 1
            # Un acierto de caché también es avance: si no hay red, es la única
            # señal de que el refresco sigue recorriendo documentos.
            if last_source is None or event.ts >= last_source[0]:
                last_source = (event.ts, event.source)
            continue
        by_source[event.source] = by_source.get(event.source, 0) + 1
        if last_source is None or event.ts >= last_source[0]:
            last_source = (event.ts, event.source)
    rows = [
        {
            "id": source,
            "label": source_label(source),
            "calls": calls,
            "cache_hits": cached_by_source.get(source, 0),
        }
        for source, calls in sorted(
            by_source.items(),
            key=lambda item: (-(item[1] + cached_by_source.get(item[0], 0)), item[0]),
        )
    ]
    # Una fuente que solo sirvió caché no está en ``by_source``: se añade para
    # que el desglose no oculte de dónde vino el trabajo en air-gap.
    for source, hits in sorted(cached_by_source.items(), key=lambda item: (-item[1], item[0])):
        if source not in by_source:
            rows.append(
                {
                    "id": source,
                    "label": source_label(source),
                    "calls": 0,
                    "cache_hits": hits,
                }
            )
    busiest = sorted(in_flight.items(), key=lambda item: (-item[1], item[0]))
    last_ts = last_source[0] if last_source is not None else None
    return {
        "calls": len(events),
        "cache_hits": cache_hits,
        "by_source": rows,
        # Lo que se está pidiendo ahora mismo es la mejor pista de «en qué
        # está»; si no hay nada en vuelo, la última fuente que respondió.
        "current": (busiest[0][0] if busiest else None) or (last_source[1] if last_source else None),
        "current_label": (source_label(busiest[0][0]) if busiest else None)
        or (source_label(last_source[1]) if last_source else None),
        "in_flight": sum(in_flight.values()),
        # Segundos desde el último documento resuelto. Una descarga real tiene
        # pausas largas (una fuente lenta, un reintento, la cadencia humana):
        # sin esta cifra la pausa y el cuelgue se ven idénticos en pantalla.
        "last_activity_seconds": round(max(0.0, stamp - last_ts), 1) if last_ts is not None else None,
    }


def _rate_band(per_minute: float) -> str:
    for ceiling, label in RATE_BANDS:
        if per_minute < ceiling:
            return label
    return RATE_BANDS[-1][1]


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _event_counts(events: list[_Event]) -> dict[str, int]:
    calls = errors = rate_limited = retries = cache_hits = not_found = auth = ok = 0
    for event in events:
        if event.cached:
            cache_hits += 1
            continue
        calls += 1
        if event.retry:
            retries += 1
        if _is_not_found_status(event.status):
            not_found += 1
        elif _is_auth_status(event.status):
            auth += 1
        elif _is_server_failure(event.status):
            errors += 1
        else:
            ok += 1
        if event.status == 429:
            rate_limited += 1
    return {
        "calls": calls,
        "ok": ok,
        "errors": errors,
        "not_found": not_found,
        "auth": auth,
        "rate_limited": rate_limited,
        "retries": retries,
        "cache_hits": cache_hits,
    }


def _risk(
    *,
    calls_1m: int,
    calls_10m: int,
    errors_10m: int,
    recovered_10m: int,
    auth_10m: int,
    rate_limited_10m: int,
    retries_10m: int,
    peak_1m: int,
) -> dict[str, Any]:
    """Riesgo de que la fuente te frene, no de que la fuente esté caída.

    Un 500/502 en un host de respaldo es parte del contrato de ``net.py``
    (prueba varios endpoints hasta que uno responde) y no dice nada del
    volumen. Por eso el nivel ``alto`` se reserva para un 429 real: es la
    unica respuesta que prueba que alguien está contando tus peticiones.
    Las caidas se informan en ``stability``, con su mezcla de códigos.
    """
    rate_1m = float(calls_1m)
    retry_ratio = (retries_10m / calls_10m) if calls_10m else 0.0
    # Solo pesan los fallos que nadie resolvio: un 502 seguido de un 200 es
    # el respaldo funcionando, no una fuente inestable.
    unresolved_10m = max(0, errors_10m - recovered_10m)
    error_ratio = (unresolved_10m / calls_10m) if calls_10m else 0.0
    reasons: list[str] = []

    if rate_limited_10m:
        level = "alto"
        reasons.append(f"{rate_limited_10m} respuesta(s) HTTP 429 en 10 min: la fuente ya esta frenando.")
    elif retry_ratio >= RETRY_RATIO_WARN or peak_1m >= CONCURRENCY_WARN or calls_10m >= SUSTAINED_CALLS_WARN:
        level = "medio"
        if retry_ratio >= RETRY_RATIO_WARN:
            reasons.append(f"{retries_10m} reintentos de {calls_10m} llamadas ({retry_ratio * 100:.0f} %).")
        if peak_1m >= CONCURRENCY_WARN:
            reasons.append(f"{peak_1m} peticiones simultaneas: un patron de rafaga.")
        if calls_10m >= SUSTAINED_CALLS_WARN:
            reasons.append(f"{calls_10m} llamadas en 10 min sostenidos (>= 90/min).")
    elif auth_10m:
        level = "medio"
        reasons.append(f"{auth_10m} respuesta(s) 401/403: sesion por renovar o fuente que pide calma.")
    else:
        level = "bajo"
        reasons.append(f"{calls_1m} llamada(s) en el ultimo minuto, sin 429 ni reintentos.")
    if errors_10m and not rate_limited_10m:
        if recovered_10m >= errors_10m:
            reasons.append(
                f"{errors_10m} respuesta(s) 5xx seguidas de un 200: el respaldo hizo su trabajo."
            )
        else:
            reasons.append(
                f"{unresolved_10m} respuesta(s) 5xx o de red sin resolver: inestabilidad de la fuente, no exceso de ritmo."
            )

    score = 100.0
    if rate_limited_10m:
        score -= 45 + 5 * (rate_limited_10m - 1)
    score -= min(25.0, retry_ratio * 60.0)
    if peak_1m >= CONCURRENCY_WARN:
        score -= 10
    if calls_10m >= SUSTAINED_CALLS_WARN:
        score -= 10
    if level != "alto" and auth_10m:
        score -= min(10.0, 4.0 * auth_10m)
    if level != "alto" and error_ratio >= ERROR_RATIO_ALTO and unresolved_10m >= 3:
        score -= 6
    score = int(max(0.0, min(100.0, round(score))))

    band = _rate_band(rate_1m)
    if level == "alto":
        headline = "La fuente te esta frenando: no fuerces otra actualizacion"
        advice = "Espera unos minutos antes de pulsar Actualizar. Los 429 no se arreglan reintentando."
    elif level == "medio":
        headline = "Ritmo alto, pero sin bloqueos todavia"
        advice = "Puedes seguir, aunque conviene no encadenar actualizaciones completas."
    elif unresolved_10m >= 3 and error_ratio >= ERROR_RATIO_ALTO:
        headline = f"Ritmo {band}, pero la fuente no responde"
        advice = "No es tu ritmo: las llamadas vuelven con 5xx. El panel sigue con lo ultimo guardado; reintenta mas tarde."
    else:
        headline = f"Ritmo {band}: el panel va sobrado"
        advice = "Puedes actualizar cuando quieras; este ritmo no parece un bot."

    return {
        "level": level,
        "score": score,
        "headline": headline,
        "advice": advice,
        "reasons": reasons,
        "rules": list(RISK_RULES),
    }


def _stability(
    *,
    calls_10m: int,
    errors_10m: int,
    recovered_10m: int,
    not_found_10m: int,
    status_mix: dict[str, int],
) -> dict[str, Any]:
    """Lectura aparte de los fallos: mezcla de códigos y veredicto en una frase."""
    unresolved = max(0, errors_10m - recovered_10m)
    error_ratio = (unresolved / calls_10m) if calls_10m else 0.0
    if not calls_10m:
        level = "ok"
        headline = "Sin llamadas en 10 min"
    elif not unresolved:
        level = "ok"
        headline = (
            f"Sin fallos pendientes: {recovered_10m} 5xx resueltos por el respaldo"
            if recovered_10m
            else "Ninguna llamada fallida en 10 min"
        )
    elif error_ratio >= ERROR_RATIO_ALTO:
        level = "warn"
        headline = f"{unresolved} de {calls_10m} llamadas no llegaron a buen puerto ({error_ratio * 100:.0f} %)"
    else:
        level = "ok"
        headline = f"{unresolved} fallo(s) suelto(s) de {calls_10m} llamadas"
    return {
        "level": level,
        "headline": headline,
        "errors_10m": unresolved,
        "recovered_10m": recovered_10m,
        "not_found_10m": not_found_10m,
        "status_mix": status_mix,
        "note": "Un 404 o un 5xx al probar endpoints de respaldo es normal: net.py prueba varios hosts hasta acertar.",
    }


def build_usage_report(*, now: float | None = None) -> dict[str, Any]:
    """Resumen de llamadas por ventana, fuente y minuto. Sin red y sin bloquear."""
    stamp = time.time() if now is None else now
    with _lock:
        _prune(stamp)
        events = list(_events)
        totals = dict(_totals)
        in_flight = {source: count for source, count in _in_flight.items() if count > 0}
        peaks = [value for ts, value in _peaks if ts >= stamp - 60.0]
        started = _started_at

    windows: list[dict[str, Any]] = []
    for seconds, label in WINDOWS:
        subset = [event for event in events if event.ts >= stamp - seconds]
        counts = _event_counts(subset)
        counts.update(
            {
                "seconds": seconds,
                "label": label,
                "rate_per_minute": round(counts["calls"] * 60.0 / seconds, 1),
            }
        )
        windows.append(counts)

    one_minute = windows[0]
    ten_minutes = windows[1]

    by_source: dict[str, dict[str, Any]] = {}
    recovered_ids = _recovered_ids(events)
    for event in events:
        row = by_source.setdefault(
            event.source,
            {
                "id": event.source,
                "label": source_label(event.source),
                "host": event.host or None,
                "calls_1m": 0,
                "calls_10m": 0,
                "calls": 0,
                "cache_hits": 0,
                "errors": 0,
                "not_found": 0,
                "auth": 0,
                "rate_limited": 0,
                "recovered": 0,
                "retries": 0,
                "last_at": None,
                "_duration": 0.0,
                "_timed": 0,
            },
        )
        if event.cached:
            row["cache_hits"] += 1
            continue
        row["calls"] += 1
        if event.ts >= stamp - 60.0:
            row["calls_1m"] += 1
        if event.ts >= stamp - 600.0:
            row["calls_10m"] += 1
        if event.retry:
            row["retries"] += 1
        if id(event) in recovered_ids:
            row["recovered"] += 1
        if _is_not_found_status(event.status):
            row["not_found"] += 1
        elif _is_auth_status(event.status):
            row["auth"] += 1
        elif _is_server_failure(event.status):
            row["errors"] += 1
        if event.status == 429:
            row["rate_limited"] += 1
        if event.duration_ms > 0:
            row["_duration"] += event.duration_ms
            row["_timed"] += 1
        if row["last_at"] is None or event.ts > row["last_at"]:
            row["last_at"] = event.ts

    total_calls = sum(row["calls"] for row in by_source.values())
    sources: list[dict[str, Any]] = []
    for row in by_source.values():
        timed = row.pop("_timed")
        duration = row.pop("_duration")
        row["avg_ms"] = round(duration / timed, 1) if timed else None
        row["errors_pending"] = max(0, row["errors"] - row["recovered"])
        row["last_at"] = _iso(row["last_at"])
        row["rate_per_minute"] = float(row["calls_1m"])
        row["share_pct"] = round(row["calls"] * 100.0 / total_calls, 1) if total_calls else None
        budget = BUDGETS.get(row["id"])
        row["budget_per_minute"] = budget["per_minute"] if budget else None
        row["utilization_pct"] = round(row["calls_1m"] * 100.0 / budget["per_minute"], 1) if budget else None
        sources.append(row)
    sources.sort(key=lambda row: (-row["calls_10m"], -row["calls"], row["label"]))

    timeline: list[dict[str, Any]] = []
    for minutes_ago in range(TIMELINE_MINUTES - 1, -1, -1):
        start = stamp - (minutes_ago + 1) * 60.0
        end = stamp - minutes_ago * 60.0
        calls = sum(1 for event in events if not event.cached and start <= event.ts < end)
        timeline.append(
            {
                "minutes_ago": minutes_ago,
                "label": "ahora" if minutes_ago == 0 else f"hace {minutes_ago} min",
                "calls": calls,
            }
        )

    peak_1m = max(peaks) if peaks else _total_in_flight()
    status_mix = _status_mix(events)
    ten_minute_events = [event for event in events if event.ts >= stamp - 600.0]
    recovered_10m = _recovered_failures(ten_minute_events)
    risk = _risk(
        calls_1m=one_minute["calls"],
        calls_10m=ten_minutes["calls"],
        errors_10m=ten_minutes["errors"],
        recovered_10m=recovered_10m,
        auth_10m=ten_minutes["auth"],
        rate_limited_10m=ten_minutes["rate_limited"],
        retries_10m=ten_minutes["retries"],
        peak_1m=peak_1m,
    )
    stability = _stability(
        calls_10m=ten_minutes["calls"],
        errors_10m=ten_minutes["errors"],
        recovered_10m=recovered_10m,
        not_found_10m=ten_minutes["not_found"],
        status_mix=status_mix,
    )

    return {
        "ok": True,
        "command": "api-usage",
        "generated_at": _iso(stamp),
        "process_started_at": _iso(started),
        "uptime_seconds": round(max(0.0, stamp - started), 1),
        "scope": "Solo este proceso: el tablero (uvicorn). Los comandos de la CLI van por su cuenta.",
        "rate": {
            "calls_1m": one_minute["calls"],
            "per_minute": one_minute["rate_per_minute"],
            "band": _rate_band(one_minute["rate_per_minute"]),
            "calls_10m": ten_minutes["calls"],
            "per_minute_10m": ten_minutes["rate_per_minute"],
        },
        "windows": windows,
        "sources": sources,
        "status_mix": status_mix,
        "timeline": timeline,
        "in_flight": {"now": _total_in_flight(), "by_source": in_flight, "peak_1m": peak_1m},
        "totals": {
            **totals,
            "seconds": round(max(0.0, stamp - started), 1),
        },
        "risk": risk,
        "stability": stability,
        "notes": [
            "Los aciertos de cache no gastan peticion: se cuentan aparte.",
            "Una llamada reintentada aparece varias veces porque cada intento sale a la red.",
            "Un 404 al probar un endpoint de respaldo no cuenta como error: es el contrato.",
            "Un 5xx en un host de respaldo es inestabilidad, no ritmo: no dispara la alarma de bloqueo.",
            "El contador vive en RAM: se reinicia al reiniciar uvicorn.",
        ],
    }

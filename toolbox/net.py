"""Cliente HTTP de LALIGA Fantasy: air-gap, cadencia ultralenta y kill switch.

Este módulo es la única puerta hacia la API oficial. El contrato está pensado
para que un error de programación **no** pueda convertirse en spam contra el
WAF de LaLiga. Cuatro capas, de fuera hacia dentro:

1. Air-gap por defecto (``LALIGA_ENV``)
   El entorno vale ``development`` si no se dice otra cosa. Solo con
   ``LALIGA_ENV=production`` se construye una sesión de red real. En
   ``development``/``test`` el cliente sirve exclusivamente la copia JSON de
   ``.cache/`` (``offline_miss`` si no existe) y **nunca** abre un socket.
   La última línea de defensa es ``official_session()``: fuera de producción no
   se puede ni instanciar la sesión de curl. La única excepción deliberada es
   inyectar un cliente HTTP explícito (``LaligaClient(http=...)``), que es como
   las pruebas usan un transporte simulado: no hay red real y el air-gap sigue
   vigente para cualquier cliente que se construya por su cuenta.

2. Cadencia de ultra-baja frecuencia (``HumanPacer``)
   Cada GET paga una espera uniforme de 12–25 s y, cada 3–4 peticiones, una
   «pausa de actividad» de 45–90 s (el móvil se queda en la mesa). La pausa
   sustituye a la espera de esa petición, no se suma: la media ronda los 33 s
   por GET. La concurrencia contra LaLiga es **1**: un lock de proceso envuelve
   la pausa y la petición, así que no existe un instante con dos sockets
   abiertos al dominio. La foto rápida (``core``, ~25–30 GET) tarda 14–18 min y
   la completa (``full``, ~60 GET) unos 32 min; no se corre, porque el refresco
   es nocturno y el presupuesto aceptado es de 15–20 min como mínimo, no como
   techo. ``FANTASY_NET_PACING=0`` solo se honra fuera de producción.

3. Mimicry con ``curl_cffi``
   La sesión de proceso usa ``impersonate="chrome110"`` (huella TLS/JA3 y
   HTTP/2 de Chrome) con keep-alive y cabeceras inmutables: User-Agent, idioma
   y codificación coherentes con el perfil. No se mezclan huellas.

4. Kill switch paranoico
   Un solo 401, 403, 429 o 5xx cierra el proceso con ``sys.exit(1)``. No hay
   reintento, ni backoff, ni segundo host: insistir ante el firewall es la
   forma más rápida de convertir una sospecha en un baneo de la IP. Antes de
   salir se cierra la sesión, se apunta el disparo en la bitácora de red y en
   ``.cache/kill_switch.json``.

El resto del módulo mantiene la separación de siempre:

* La API de Fantasy es de solo lectura: un POST, PUT, PATCH o DELETE hacia sus
  hosts se rechaza antes de salir.
* La ruta de ligas del contrato es ``/api/v4/leagues``. El host histórico
  ``api-fantasy.llt-services.com`` devuelve 502; el mismo path responde en
  ``fantasy-api.llt-services.com``. Se prueban los hosts del contrato, pero un
  5xx ya no se «sortea»: dispara el kill switch. Solo un 404/410 o una caída
  de red permiten pasar al siguiente host, y cada intento vuelve a pagar su
  pausa humana.
* ``FANTASY_OFFLINE=1`` sigue siendo el modo avión duro para todo (también
  para ``ExternalClient`` y Playwright): sirve la copia caducada e ignora
  ``fresh``/``ttl``. El air-gap de ``LALIGA_ENV`` es el valor por defecto de
  LaLiga; ``FANTASY_OFFLINE`` es el interruptor global explícito.
* Las fuentes externas (FútbolFantasy, FBref, …) conservan su concurrencia y
  sus reintentos: no comparten cuenta ni WAF con la API oficial.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import random
import re
import socket
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, Protocol

import httpx

# httpx no interrumpe un recv colgado en Windows. El timeout del socket sí,
# y tiene que estar puesto antes de abrir el cliente de LALIGA.
_DEFAULT_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
if socket.getdefaulttimeout() is None:
    socket.setdefaulttimeout(10.0)

from toolbox import api_meter
from toolbox.auth import league_id_from_env
from toolbox.cache import ResponseCache, cache_root
from toolbox.normalize import (
    attach_image_urls,
    build_market_document,
    build_squads_document,
    empty_squad,
    image_index_from_players,
    leagues_from_payload,
    normalize_saved_lineup,
    normalize_squad,
    team_seeds,
)

# --- Modo avión ------------------------------------------------------------
# ``FANTASY_OFFLINE=1`` corta toda salida a la red: solo se sirve lo que ya está
# en la caché de disco. Es el interruptor para desarrollar el frontend sin que un
# refresco del tablero mande una sola petición a LaLiga ni a las fuentes.
# Se lee al importar el módulo, pero ``offline_mode()`` vuelve a mirar el
# entorno y el ``.env`` porque el fichero se carga después de este import.
# Sirve para los dos clientes: LALIGA (``LaligaClient``) y las fuentes de
# inteligencia (``ExternalClient``).
OFFLINE_MODE = os.environ.get("FANTASY_OFFLINE") == "1"
# Código propio del 503 de modo avión: no hay copia en disco y no se sale a la red.
OFFLINE_MISS_CODE = "offline_miss"
# El ``.env`` se carga más tarde que este import (lo hace ``TokenManager``), así
# que la bandera del fichero se resuelve aparte, una sola vez y sin tocar el
# resto del entorno. Arrancar con ``FANTASY_OFFLINE=1`` en la shell manda igual.
_ENV_FILE_OFFLINE: bool | None = None


def _offline_from_env_file() -> bool:
    """``True`` si ``FANTASY_OFFLINE=1`` está escrito en el ``.env`` del proyecto."""
    global _ENV_FILE_OFFLINE
    if _ENV_FILE_OFFLINE is None:
        value = ""
        try:
            from toolbox import project_root

            path = project_root() / ".env"
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("FANTASY_OFFLINE="):
                        value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        except (OSError, UnicodeDecodeError):
            value = ""
        _ENV_FILE_OFFLINE = value == "1"
    return _ENV_FILE_OFFLINE


def offline_mode() -> bool:
    """``True`` si el proceso está en modo avión.

    ``OFFLINE_MODE`` se fija al importar el módulo, pero el ``.env`` del
    proyecto se carga más tarde (lo hace ``TokenManager``), así que aquí se
    vuelve a mirar el entorno y, si la variable no está, el ``.env``.

    Un ``FANTASY_OFFLINE=0`` **explícito** en el entorno gana al fichero: es la
    misma precedencia que ``LALIGA_ENV``. Importa en el VPS, donde el ``.env``
    montado es el de desarrollo (con ``FANTASY_OFFLINE=1``) y el contenedor
    declara ``0`` como variable de entorno; si el fichero mandara, el motor
    arrancaría sellado y ningún refresco tendría red.
    """
    if OFFLINE_MODE:
        return True
    raw = os.environ.get("FANTASY_OFFLINE", "").strip()
    if raw == "1":
        return True
    if raw == "0":
        return False
    return _offline_from_env_file()


# ---------------------------------------------------------------------------
# Entorno: aislamiento por defecto (air-gap) hacia la API de LALIGA
# ---------------------------------------------------------------------------
# ``LALIGA_ENV`` decide si este proceso puede abrir sockets hacia LaLiga. El
# valor por defecto es ``development``: el aislamiento es el estado natural, no
# algo que haya que recordar activar. Solo un ``LALIGA_ENV=production``
# explícito abre la puerta, y aun así el catálogo global solo se refresca a
# mano y pasado su TTL de 6 h.
LALIGA_ENV_VAR = "LALIGA_ENV"
DEVELOPMENT_ENV = "development"
PRODUCTION_ENV = "production"
# Host del contrato vivo: el que responde mercado, plantillas y catálogo.
GATED_NETLOC = "fantasy-api.llt-services.com"
# El ``.env`` se carga más tarde que este import (``TokenManager``), así que el
# valor del fichero se resuelve aparte y se recuerda. La variable de la shell
# manda siempre sobre el fichero.
_ENV_FILE_LALIGA_ENV: str | None = None


def _env_file_laliga_env() -> str | None:
    """``LALIGA_ENV`` escrito en el ``.env`` del proyecto, si lo hay."""
    global _ENV_FILE_LALIGA_ENV
    if _ENV_FILE_LALIGA_ENV is None:
        value = ""
        try:
            from toolbox import project_root

            path = project_root() / ".env"
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if stripped.startswith(f"{LALIGA_ENV_VAR}="):
                        value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        except (OSError, UnicodeDecodeError):
            value = ""
        _ENV_FILE_LALIGA_ENV = value
    return _ENV_FILE_LALIGA_ENV or None


def environment() -> str:
    """Entorno efectivo: ``LALIGA_ENV`` de la shell, del ``.env`` o ``development``."""
    for value in (os.environ.get(LALIGA_ENV_VAR), _env_file_laliga_env()):
        cleaned = (value or "").strip().lower()
        if cleaned:
            return cleaned
    return DEVELOPMENT_ENV


def is_production() -> bool:
    """``True`` solo con un ``LALIGA_ENV=production`` explícito."""
    return environment() == PRODUCTION_ENV


def air_gapped() -> bool:
    """``True`` si el proceso tiene prohibido abrir sockets hacia LaLiga.

    Es el modo por defecto. No depende de ``FANTASY_OFFLINE``: aquel apaga
    también las fuentes externas; este cierra solo el dominio de la liga, que
    es el que puede banear la cuenta.
    """
    return not is_production()


def network_sealed() -> bool:
    """``True`` si la API de LALIGA no admite tráfico saliente en este proceso."""
    return offline_mode() or air_gapped()


# ---------------------------------------------------------------------------
# Modo lectura del tablero: red prohibida en el hilo actual
# ---------------------------------------------------------------------------
# El tablero se organiza en dos caminos y solo uno puede tocar la red:
#
#   * ``GET /api/...``          → lee la foto guardada. Red prohibida.
#   * ``POST /api/plan/refresh`` → único sitio que llama a los scrapers.
#
# ``offline_mode()`` es global y apagaría también el refresco, así que el veto
# va por hilo con ``contextvars``: dentro de ``no_network()`` cualquier intento
# de salir a Internet levanta ``NetworkBlockedError`` en lugar de gastar una
# petición. Es un cinturón de seguridad, no el mecanismo normal: el camino de
# lectura ni siquiera debería llegar aquí.
_NETWORK_VETO: contextvars.ContextVar[bool] = contextvars.ContextVar("fantasy_network_veto", default=False)

# Código propio del veto: la lectura intentó salir a la red y no se permitió.
NETWORK_BLOCKED_CODE = "network_blocked"


def network_forbidden() -> bool:
    """``True`` si este hilo está dentro de ``no_network()``."""
    return _NETWORK_VETO.get()


@contextlib.contextmanager
def no_network() -> Iterator[None]:
    """Prohíbe cualquier salida a la red dentro del bloque y del hilo actual."""
    token = _NETWORK_VETO.set(True)
    try:
        yield
    finally:
        _NETWORK_VETO.reset(token)


def inherited(task: Callable[..., Any]) -> Callable[..., Any]:
    """Envuelve una tarea de pool para que herede el veto de red del padre.

    Se usa en cada ``pool.submit(...)`` que pueda alcanzar un cliente HTTP::

        pool.submit(inherited(load_lineups), client, ttl=..., fresh=...)

    ``contextvars`` **no** viaja solo a los hilos de un ``ThreadPoolExecutor``:
    cada worker arranca con el contexto por defecto, así que un ``GET`` metido
    en ``no_network()`` veía el veto a ``False`` en cuanto delegaba en un pool.
    Esa era la fuga por la que una lectura podía acabar descargando.

    El valor se lee **aquí**, en el hilo que llama a ``submit`` (el que sí tiene
    el veto), no dentro del worker: dentro ya sería siempre ``False``.
    """
    vetoed = _NETWORK_VETO.get()

    def run(*args: Any, **kwargs: Any) -> Any:
        if not vetoed:
            return task(*args, **kwargs)
        # El worker arranca limpio; se le pone el veto del padre mientras corre.
        token = _NETWORK_VETO.set(True)
        try:
            return task(*args, **kwargs)
        finally:
            _NETWORK_VETO.reset(token)

    return run


def _refuse_network(url: str) -> None:
    if _NETWORK_VETO.get():
        raise NetworkBlockedError(url)


def offline_cache_miss(url: str, *, external: bool = False) -> FantasyHttpError:
    """503 de modo avión / air-gap: ``url`` no tiene copia y no se toca la red.

    ``external=True`` devuelve un ``ExternalHttpError`` para que los scrapers lo
    capturen con el mismo ``except`` que ya usan en sus fallos de fuente.
    """
    error_type = ExternalHttpError if external else OfflineCacheError
    return error_type(
        "Offline mode: caché no encontrada",
        status=503,
        code=OFFLINE_MISS_CODE,
        details={"url": _loggable_url(url), "offline": True},
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
# Los dos hosts del contrato son el mismo firewall: la cadencia humana, el
# semáforo de un permiso y el cortacircuitos se aplican por igual a ambos.
LALIGA_NETLOCS = frozenset(ALLOWED_NETLOCS)
_READ_METHODS = frozenset({"GET", "HEAD"})

# Un único dispositivo, el mismo en todas las llamadas. Mezclar una huella de
# escritorio Linux con otra de Windows en la misma sesión es una firma de bot
# más fuerte que el propio volumen de peticiones. El perfil TLS que inyecta
# ``curl_cffi`` es Chrome 110, así que el ``User-Agent`` es el de ese mismo
# Chrome: un JA3 de Chrome con un UA de iPhone sería una incoherencia trivial
# de detectar.
TLS_IMPERSONATE = "chrome110"
LALIGA_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
)
LALIGA_ACCEPT_LANGUAGE = "es-ES,es;q=0.9"
# El perfil chrome110 negocia brotli; declararlo aquí mantiene la cabecera
# idéntica a la del navegador que se está imitando.
LALIGA_ACCEPT_ENCODING = "gzip, deflate, br"
# Cabeceras inmutables: se construyen una vez y se copian sin poder mutar el
# original. Un ``dict`` compartido que alguien toque a mitad de sesión rompe la
# coherencia de la huella, que es justo lo que este módulo protege.
REQUIRED_HEADERS: Mapping[str, str] = MappingProxyType(
    {
        "Origin": "https://fantasy.laliga.com",
        "Referer": "https://fantasy.laliga.com/",
        "X-App": "Fantasy-web",
        "X-Lang": "es",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": LALIGA_ACCEPT_LANGUAGE,
        "Accept-Encoding": LALIGA_ACCEPT_ENCODING,
        "User-Agent": LALIGA_USER_AGENT,
        # Los navegadores mandan estos metadatos en las llamadas XHR.
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
)

# Ya no hay reintentos contra LaLiga. Se conservan los nombres porque las
# funciones de backoff siguen usándose en las fuentes externas.
MAX_ATTEMPTS = 1
MAX_RETRY_AFTER_SECONDS = 180.0
MAX_SQUADS = 40

# --- Cadencia de ultra-baja frecuencia -------------------------------------
# El objetivo ya no es «parecer humano durante un refresco corto», es que una
# pasada completa (15–20 min como mínimo, sin techo) sea indistinguible de
# alguien que consulta la app a ratos. Cada GET paga 12–25 s de espera y, cada
# 3–4 peticiones, una pausa de actividad de 45–90 s (el móvil se queda en la
# mesa) que sustituye la espera de esa petición. No hay «primera petición
# gratis»: el patrón tiene que ser el mismo desde el primer socket.
HUMAN_DELAY_MIN_SECONDS = 12.0
HUMAN_DELAY_MAX_SECONDS = 25.0
ACTIVITY_PAUSE_EVERY_MIN = 3
ACTIVITY_PAUSE_EVERY_MAX = 4
ACTIVITY_PAUSE_MIN_SECONDS = 45.0
ACTIVITY_PAUSE_MAX_SECONDS = 90.0
# Alias históricos: las pruebas y la documentación antigua hablaban de jitter.
JITTER_MIN_SECONDS = HUMAN_DELAY_MIN_SECONDS
JITTER_MAX_SECONDS = HUMAN_DELAY_MAX_SECONDS
# Pasada completa estimada: mercado, plantillas (≈40 equipos), once guardado,
# actividad e imágenes. Es la base con la que el gatillo remoto reparte
# ``target_minutes``; no es un número de peticiones garantizado.
HUMAN_REQUESTS_PER_REFRESH = 60

# Un 5xx de una fuente externa se espera con ``base * 2**intento``. Esto NO se
# aplica a LaLiga: ahí un 5xx dispara el kill switch (ver ``kill_switch``).
UPSTREAM_BACKOFF_BASE_SECONDS = 1.0
UPSTREAM_BACKOFF_MAX_SECONDS = 8.0

# --- Kill switch paranoico -------------------------------------------------
# Un 401 (token caducado), 403, 429 o cualquier 5xx de LaLiga es una señal de
# alarma, no un fallo transitorio que se arregle insistiendo. El proceso muere
# en el acto: ni reintento, ni segundo host, ni espera. Un WAF que ve tres
# intentos seguidos marca la IP residencial durante días.
KILL_SWITCH_STATUSES = frozenset({401, 403, 429})
KILL_SWITCH_CODE = "kill_switch"
# Alias del contrato anterior: el tablero aún puede leer este código.
STEALTH_BREAKER_CODE = KILL_SWITCH_CODE
STEALTH_BREAKER_STATUSES = KILL_SWITCH_STATUSES
# Deja constancia en ``.cache/kill_switch.json`` antes de salir: sin esto, el
# proceso muere y nadie sabe qué host ni qué código lo mató.
KILL_SWITCH_MARKER_FILENAME = "kill_switch.json"

# --- Control de tráfico (thundering herd) ----------------------------------
# Un arranque en frío abre varios workers a la vez y todos piden al mismo host
# en el mismo segundo: la caché está vacía, así que los TTL no frenan nada y
# FútbolFantasy contesta 429. Estos cooldowns son un suelo duro entre dos GET al
# mismo dominio, compartido por todo el proceso (LALIGA y fuentes externas) y
# se suman a la cadencia humana de LaLiga. 2 s en FútbolFantasy son 30/min.
COOLDOWNS = {
    "fantasy-api.llt-services.com": 1.5,
    "api-fantasy.llt-services.com": 1.5,
    "www.futbolfantasy.com": 2.0,
    "default": 1.0,
}
# Último hueco reservado (en segundos del reloj del módulo) para cada dominio.
# Se lee y se escribe siempre bajo ``_rate_limit_lock``: el cerrojo hace que
# leer el último hueco y reservar el siguiente sean atómicos, así que N hilos
# no pueden colarse en el mismo hueco.
_last_request_time: dict[str, float] = {}
_rate_limit_lock = threading.Lock()
# Reloj de los cooldowns: monotónico, porque solo se restan instantes y un
# salto del reloj de pared (NTP, cambio de hora) no debe abrir ni cerrar el
# grifo. Las pruebas lo sustituyen para no esperar de verdad.
_PACING_CLOCK: Callable[[], float] = time.monotonic

LEAGUE_TTL_SECONDS = 30 * 60
MARKET_TTL_SECONDS = 2 * 60
SQUAD_TTL_SECONDS = 10 * 60
ACTIVITY_TTL_SECONDS = 5 * 60
ACTIVITY_CONCAT_TTL_SECONDS = 30 * 60
# Aunque llegue fresh=True, un concat de menos de 2 h se sirve tal cual:
# el historial no cambia al ritmo del mercado y repaginar son hasta 40 GET.
ACTIVITY_CONCAT_FRESH_MIN_AGE_SECONDS = 2 * 60 * 60
ACTIVITY_PAGE_BATCH = 5
ACTIVITY_MAX_PAGES = 40
PLAYERS_TTL_SECONDS = 6 * 60 * 60
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_RETRY_UPSTREAM = {500, 502, 503, 504}
_STALE_FALLBACK_CODES = frozenset(
    {"forbidden", "blocked", "upstream", "network", "rate_limited", "http_error"}
)
# Códigos que el cliente de LALIGA rescata con la copia en disco: un 5xx tras
# agotar reintentos, una caída de red o el cortacircuitos paranoico. Antes un
# 429 subía como error; ahora el 429/403 ni se reintenta: se sirve la copia en
# disco y se deja el firewall en paz.
_STALE_SURVIVAL_CODES = frozenset({"upstream", "network", STEALTH_BREAKER_CODE})
_TRANSFERMARKT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
# Cortacircuitos de Transfermarkt. Su API pública se cae a ratos y responde
# 504 tras 15 s. Con 6 intentos × 45 s por jugador, una pasada de ~90 nombres
# se iba a más de dos horas: el refresco del panel no terminaba nunca y el
# usuario veía «actualizando» para siempre. Aquí se corta la fuente en cuanto
# acumula fallos seguidos, en vez de pagar el timeout nombre a nombre.
# Un acierto rearma el contador: una caída puntual no cierra la fuente.
TRANSFERMARKT_MAX_CONSECUTIVE_FAILURES = 3
# Y un techo de reloj para toda la fuente dentro de una pasada, por si los
# fallos vienen espaciados y no llegan a ser consecutivos.
TRANSFERMARKT_WALL_BUDGET_SECONDS = 90.0

# Bitácora en disco de cada llamada que sale a la red (JSON Lines). El
# medidor de ``api_meter`` vive en RAM y se vacía al reiniciar; este fichero
# sobrevive al reinicio para poder auditar los 403/503 de ayer. Un acierto de
# caché no se apunta: no es una llamada.
NETWORK_LOG_FILENAME = "network_logs.jsonl"
NETWORK_LOG_METHOD = "GET"
# Techo del fichero. Al pasarse se rota a ``network_logs.jsonl.1`` para que
# la lista de 200 líneas no se coma un fichero de decenas de MB.
NETWORK_LOG_MAX_BYTES = 5 * 1024 * 1024
_NETWORK_LOG_LOCK = threading.Lock()

# El log del tablero es ``fantasy.dashboard``; este es el del cliente HTTP, para
# que un 5xx resuelto con caché se vea como warning suyo y no como fallo del
# tablero. Sin ``basicConfig`` no imprime nada: igual que el resto del proyecto.
logger = logging.getLogger("fantasy.net")


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


class OfflineCacheError(FantasyHttpError):
    """Air-gap: la URL pedida no tiene copia en ``.cache/`` y no se sale a la red.

    No es un fallo transitorio ni un bloqueo del tablero: es la respuesta
    correcta del modo aislado. Lleva ``offline_miss`` para que la capa de
    arriba lo distinga de un 503 real de la liga y no lo reintente.
    """

    def __init__(
        self,
        message: str = "Offline mode: caché no encontrada",
        *,
        status: int = 503,
        code: str = OFFLINE_MISS_CODE,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code, details=details)


class NetworkBlockedError(FantasyHttpError):
    """Salida a red dentro de una lectura de caché. Es un fallo de diseño."""

    def __init__(self, url: str) -> None:
        super().__init__(
            f"Modo lectura: prohibido salir a la red ({_loggable_url(url)}). Solo Actualizar puede descargar.",
            code=NETWORK_BLOCKED_CODE,
            details={"url": _loggable_url(url)},
        )


class StealthCircuitBreakerError(FantasyHttpError):
    """LALIGA respondió 429/403: se aborta la cadena y no se insiste.

    No hereda de ``NetworkBlockedError``: aquello es un veto interno del modo
    lectura; esto es el firewall de la liga. Lleva el ``status`` que lo disparó
    y el instante hasta el que el cortacircuitos de proceso estará abierto.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        url: str | None = None,
        open_until: float | None = None,
    ) -> None:
        super().__init__(
            message,
            status=status,
            code=STEALTH_BREAKER_CODE,
            details={
                "url": _loggable_url(url),
                "breaker": True,
                "open_until": open_until,
                "retry": False,
            },
        )


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


def upstream_backoff_delay(attempt: int, retry_after: str | None = None) -> float:
    """Segundos a esperar tras un 5xx: ``base * 2**intento``, con techo.

    Un host caído no se arregla insistiendo cada segundo: la espera se dobla
    en cada intento (1, 2, 4, 8 s) para no martillear y para dejar respirar a
    LaLiga si el 5xx es suyo. Un ``Retry-After`` explícito manda, pero un 502
    o un 503 rara vez lo traen. El techo evita que un respaldo muerto congele
    el tablero durante minutos.
    """
    parsed = _parse_retry_after(retry_after)
    if parsed is not None:
        return min(MAX_RETRY_AFTER_SECONDS, max(0.0, parsed))
    base = UPSTREAM_BACKOFF_BASE_SECONDS * (2.0 ** max(0, attempt))
    return min(UPSTREAM_BACKOFF_MAX_SECONDS, base)


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


def pacing_enabled() -> bool:
    """``True`` salvo ``FANTASY_NET_PACING=0`` fuera de producción.

    El interruptor existe para las pruebas y para diagnosticar, pero en
    producción **no se puede apagar**: aceptar ``FANTASY_NET_PACING=0`` con
    ``LALIGA_ENV=production`` sería una vía de escape para saltarse la única
    protección real que tiene la cuenta. En desarrollo el air-gap ya impide
    salir, así que apagarlo ahí no cambia nada.
    """
    if os.environ.get("FANTASY_NET_PACING", "").strip() != "0":
        return True
    return is_production()


def cooldown_for(netloc: str) -> float:
    """Segundos mínimos entre dos peticiones al dominio ``netloc``."""
    host = (netloc or "").lower().split(":")[0]
    return COOLDOWNS.get(host, COOLDOWNS["default"])


def is_laliga_netloc(netloc: str) -> bool:
    return (netloc or "").lower().split(":")[0] in LALIGA_NETLOCS


# --- Cadencia de ultra-baja frecuencia (solo LaLiga) -----------------------
# El estado es de proceso, no de cliente: cada ``LaligaClient`` se construye y
# se cierra por petición HTTP del panel, y una cadencia por instancia
# reiniciaría el contador cada vez (nunca llegaría la pausa de actividad). Lo
# que tiene que parecer humano es la sesión del móvil, y esa es una sola.
def expected_pass_seconds(expected_requests: int) -> float:
    """Duración media de una pasada con la cadencia de fábrica.

    No es ``peticiones × media(12, 25)``: cada 3–4 GET, la pausa de actividad
    (45–90 s) **sustituye** la espera normal de esa petición. Ignorarla dejaba
    la estimación en 18,5 s/GET cuando la real es ~33 s, y con ella el reparto
    del presupuesto remoto se quedaba corto por un factor de casi dos.
    """
    requests = max(1, int(expected_requests))
    mean_delay = (HUMAN_DELAY_MIN_SECONDS + HUMAN_DELAY_MAX_SECONDS) / 2.0
    mean_pause = (ACTIVITY_PAUSE_MIN_SECONDS + ACTIVITY_PAUSE_MAX_SECONDS) / 2.0
    mean_every = (ACTIVITY_PAUSE_EVERY_MIN + ACTIVITY_PAUSE_EVERY_MAX) / 2.0
    pauses = requests / mean_every
    normal = requests - pauses
    return normal * mean_delay + pauses * mean_pause


def pace_stretch_for(target_seconds: float, *, expected_requests: int) -> float:
    """Factor de estiramiento para un presupuesto. ``1.0`` si no hay margen.

    Es una función pura para que el gatillo remoto pueda informar del factor
    que va a aplicarse sin leer el estado del pacer (que otro hilo puede estar
    cambiando en ese instante).
    """
    default_seconds = expected_pass_seconds(expected_requests)
    if target_seconds <= 0 or default_seconds <= 0:
        return 1.0
    return max(1.0, float(target_seconds) / default_seconds)


class HumanPacer:
    """Espacia los GET como alguien que consulta la app a ratos.

    Dos decisiones deliberadas:

    * **La primera petición también espera.** El contrato anterior dejaba pasar
      el primer GET sin pausa («alguien que acaba de abrir la app»), pero eso
      convierte cada refresco en un disparo inmediato al arrancar. Con 12–25 s
      desde el primer socket, el patrón es el mismo siempre y un reinicio
      accidental no se traduce en una petición instantánea.
    * **La pausa de actividad es geométrica:** cada 3 o 4 peticiones, 45–90 s,
      y sustituye la espera de esa petición (no se suma). La media sale a ~33 s
      por GET: la foto rápida (~25–30 GET) cae en 14–18 min y la completa
      (~60 GET) ronda los 32 min. El presupuesto de 15–20 min es un suelo, no
      un techo: el refresco es nocturno y nadie lo espera en pantalla.

    El contador y el umbral de la próxima pausa viven bajo un lock, pero el
    ``sleep`` ocurre fuera: dormir con el cerrojo tomado convertiría la espera
    de un dominio en la de todos.
    """

    def __init__(
        self,
        *,
        minimum: float = HUMAN_DELAY_MIN_SECONDS,
        maximum: float = HUMAN_DELAY_MAX_SECONDS,
        pause_every: tuple[int, int] = (ACTIVITY_PAUSE_EVERY_MIN, ACTIVITY_PAUSE_EVERY_MAX),
        pause_seconds: tuple[float, float] = (ACTIVITY_PAUSE_MIN_SECONDS, ACTIVITY_PAUSE_MAX_SECONDS),
        rng: random.Random | None = None,
    ) -> None:
        self._min = minimum
        self._max = maximum
        self._pause_every = pause_every
        self._pause_seconds = pause_seconds
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._served = 0
        self._pause_at = self._draw_pause_at()
        # Factor de estiramiento del presupuesto remoto (>= 1.0). Solo alarga
        # las esperas: nunca las acorta por debajo del suelo anti-429.
        self._stretch = 1.0

    def _draw_pause_at(self) -> int:
        low, high = self._pause_every
        return self._rng.randint(max(1, low), max(low, high))

    def _normal_delay(self) -> float:
        return self._rng.uniform(self._min, self._max)

    def next_delay(self) -> tuple[float, bool]:
        """Segundos a esperar antes del próximo GET y si toca pausa de actividad.

        La espera es uniforme (no una normal truncada): con un rango de 12–25 s,
        una normal centrada en 18,5 s produciría huecos demasiado regulares.
        """
        with self._lock:
            self._served += 1
            if self._served >= self._pause_at:
                low, high = self._pause_seconds
                delay = self._rng.uniform(low, high)
                self._served = 0
                self._pause_at = self._draw_pause_at()
                return delay * self._stretch, True
            return self._normal_delay() * self._stretch, False

    def stretch_to(self, target_seconds: float, *, expected_requests: int) -> float:
        """Alarga la cadencia para que ``expected_requests`` quepan en ``target_seconds``.

        El gatillo remoto no «acelera» el scraper: cuando el presupuesto es más
        holgado que la cadencia por defecto, la pausa se estira en la misma
        proporción. Con ``target_minutes=60`` y ~60 GET, el toque de campana se
        reparte a lo largo de la hora en lugar de terminar en los ~32 min que
        dura la pasada de fábrica (18,5 s/GET era la cuenta sin las pausas de
        actividad, y por eso el reparto se quedaba corto).

        Devuelve el factor aplicado (``1.0`` = cadencia de fábrica). El suelo
        de 12–25 s y las pausas de 45–90 s no se tocan: un presupuesto corto
        **no** comprime la cadencia, porque el suelo existe para no despertar
        al WAF. Si no cabe, el refresco tardará lo que tarde.
        """
        requests = max(1, int(expected_requests))
        factor = pace_stretch_for(target_seconds, expected_requests=requests)
        with self._lock:
            self._stretch = factor
        return factor

    def reset_stretch(self) -> None:
        """Vuelve a la cadencia de fábrica tras un presupuesto remoto."""
        with self._lock:
            self._stretch = 1.0

    def reset(self) -> None:
        with self._lock:
            self._served = 0
            self._pause_at = self._draw_pause_at()
            self._stretch = 1.0

    @property
    def stretch_factor(self) -> float:
        """Factor de presupuesto vigente. ``1.0`` es la cadencia de fábrica."""
        with self._lock:
            return self._stretch


# Pacer compartido por todos los clientes del proceso.
HUMAN_PACER = HumanPacer()


def traffic_pacer() -> HumanPacer:
    """El pacer único del proceso.

    Existe como función, y no como acceso directo a ``HUMAN_PACER``, para que
    quede explícito en el código que **no** hay una cadencia por cliente: el
    contador de peticiones y el umbral de la próxima pausa son del proceso,
    igual que la sesión del móvil que se está imitando.
    """
    return HUMAN_PACER


def reset_human_pacer() -> None:
    """Vuelve a empezar el conteo de cadencia. Solo para pruebas."""
    HUMAN_PACER.reset()


# --- Kill switch paranoico (LaLiga) ----------------------------------------
# El módulo ya no «abre un cortacircuitos y sigue sirviendo caché»: si llega una
# señal de alarma, el proceso entero se apaga. El motivo no es dramatismo: un
# script que reintenta o que cambia de host después de un 403 es exactamente el
# patrón que un WAF usa para escalar de «sospecha» a «baneo de IP».
#
# El estado es de proceso y se escribe una sola vez (el primero que dispara
# manda), pero cualquier llamada posterior a ``trip_kill_switch`` vuelve a
# salir con ``sys.exit(1)``: no hay «ya lo apunté, sigo».
_kill_switch_lock = threading.Lock()
_kill_switch_state: dict[str, Any] | None = None
# Un ``SystemExit`` dentro de una prueba no debe dejar el proceso sin salida
# para siempre: ``reset_kill_switch()`` limpia la marca.
_KILL_SWITCH_EXIT_CODE = 1


class KillSwitchTripped(Exception):
    """El kill switch disparado, como excepción capturable. **Solo pruebas.**

    En producción ``trip_kill_switch()`` llama a ``sys.exit(1)`` y no hay nada
    que capturar. Bajo ``kill_switch_as_exception()`` el mismo disparo llega
    aquí para que la suite pueda comprobar el marcador y la bitácora sin matar
    el proceso de pytest, que es lo que hacía un ``assertRaises(SystemExit)``
    cuando el disparo venía de un hilo o de código que no lo envolvía.
    """

    def __init__(self, *, exit_code: int = _KILL_SWITCH_EXIT_CODE) -> None:
        super().__init__(f"Kill switch disparado (exit {exit_code}).")
        self.exit_code = exit_code
        snapshot = kill_switch_state()
        self.status = snapshot.get("status")
        self.url = snapshot.get("url")
        self.reason = snapshot.get("reason")


def _exit_with_kill_code(exit_code: int) -> NoReturn:
    """Salida por defecto del kill switch: la de producción, ``sys.exit``."""
    sys.exit(exit_code)


# Punto de inyección. Producción usa ``sys.exit``; solo ``kill_switch_as_exception``
# o un parche explícito lo cambian, y ambos viven en la suite de pruebas.
KILL_SWITCH_EXIT: Callable[[int], NoReturn] = _exit_with_kill_code


@contextlib.contextmanager
def kill_switch_as_exception() -> Iterator[None]:
    """Convierte el kill switch en ``KillSwitchTripped`` dentro del bloque.

    Solo para pruebas: deja el marcador y la bitácora intactos, así que se
    puede verificar *por qué* se disparó. Al salir restaura ``sys.exit``.
    """
    global KILL_SWITCH_EXIT

    def _raise(exit_code: int) -> NoReturn:
        raise KillSwitchTripped(exit_code=exit_code)

    previous = KILL_SWITCH_EXIT
    KILL_SWITCH_EXIT = _raise
    try:
        yield
    finally:
        KILL_SWITCH_EXIT = previous


def kill_switch_state() -> dict[str, Any]:
    """Foto del kill switch para diagnóstico y pruebas."""
    with _kill_switch_lock:
        if _kill_switch_state is None:
            return {"tripped": False, "status": None, "url": None, "reason": None, "at": None}
        return dict(_kill_switch_state)


def kill_switch_tripped() -> bool:
    with _kill_switch_lock:
        return _kill_switch_state is not None


def reset_kill_switch() -> None:
    """Borra la marca del kill switch. Solo para pruebas y diagnóstico."""
    global _kill_switch_state
    with _kill_switch_lock:
        _kill_switch_state = None
    try:
        marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def marker_path() -> Path:
    """Ruta del marcador del kill switch. Respeta ``FANTASY_CACHE_DIR``."""
    return cache_root() / KILL_SWITCH_MARKER_FILENAME


def _write_kill_switch_marker(payload: dict[str, Any]) -> None:
    """Deja constancia en disco antes de morir. Un fallo aquí no cambia la salida."""
    try:
        path = marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def trip_kill_switch(
    *,
    status: int | None,
    url: str | None = None,
    reason: str | None = None,
    detail: str | None = None,
) -> NoReturn:
    """Mata el proceso con ``sys.exit(1)``. No reintenta, no espera, no negocia.

    Se apunta el disparo (log, bitácora de red y ``.cache/kill_switch.json``) y
    se cierra cualquier sesión abierta antes de salir. El código de salida es
    siempre 1 para que el orquestador (``iniciar_todo.bat``, Render, cron) lo
    trate como fallo y no lo relance en bucle.
    """
    global _kill_switch_state
    payload = {
        "tripped": True,
        "status": status,
        "url": _loggable_url(url),
        "reason": reason or "API oficial respondió con una señal de bloqueo",
        "detail": detail,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with _kill_switch_lock:
        if _kill_switch_state is None:
            _kill_switch_state = payload
        snapshot = dict(_kill_switch_state)
    _write_kill_switch_marker(snapshot)
    logger.critical(
        "KILL SWITCH: %s (status=%s, url=%s). Se cierra el proceso sin reintentar.",
        snapshot["reason"],
        snapshot["status"],
        snapshot["url"],
    )
    # Se apunta también en la bitácora de red: es una llamada real y es la que
    # explica por qué el proceso ya no existe.
    log_network_call(url=url, status=status, duracion_ms=0.0)
    close_official_session()
    KILL_SWITCH_EXIT(_KILL_SWITCH_EXIT_CODE)


# Compatibilidad con el contrato anterior. El «cortacircuitos» ya no se abre
# para esperar 15 minutos: dispara el kill switch. Se mantienen los nombres
# porque el panel y los scripts antiguos aún los consultan.
def stealth_breaker_remaining() -> float:
    """Siempre ``0.0``: ya no hay ventana de espera, hay salida inmediata."""
    return 0.0


def stealth_breaker_state() -> dict[str, Any]:
    state = kill_switch_state()
    return {"open": state["tripped"], "remaining_seconds": 0.0, "reason": state}


def open_stealth_breaker(*, status: int, url: str | None = None) -> NoReturn:
    trip_kill_switch(status=status, url=url)


def close_stealth_breaker() -> None:
    """Cierra la marca a mano. Solo para pruebas y diagnóstico."""
    reset_kill_switch()


def stealth_breaker_error(*, status: int, url: str | None = None) -> StealthCircuitBreakerError:
    """Compatibilidad: construye la excepción sin disparar la salida."""
    return StealthCircuitBreakerError(
        f"LaLiga respondió HTTP {status}: kill switch. No se reintenta.",
        status=status,
        url=url,
    )


# --- Serialización total contra LaLiga -------------------------------------
# Un humano con el móvil no abre cuatro pantallas en el mismo milisegundo, y
# este cliente tampoco: el lock se toma alrededor de la pausa y de la petición,
# así que nunca hay dos sockets simultáneos ni dos esperas solapadas. Las
# fuentes externas no pasan por aquí y conservan su concurrencia.
_LALIGA_SEMAPHORE = threading.Lock()


@contextlib.contextmanager
def laliga_serialized() -> Iterator[None]:
    """Serializa un bloque de trabajo contra la API de LaLiga."""
    with _LALIGA_SEMAPHORE:
        yield


def pace_domain(
    url: str,
    *,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    minimum_wait: float = 0.0,
) -> float:
    """Reserva el siguiente hueco del dominio de ``url`` y espera lo que toque.

    Devuelve los segundos dormidos (0.0 si el hueco estaba libre).

    ``minimum_wait`` es la cadencia humana ya sorteada para esta petición: el
    hueco se reserva a ``max(ahora + minimum_wait, último + cooldown)``, así que
    el suelo anti-429 sigue mandando cuando la espera humana es corta y no se
    suman dos esperas que dirían lo mismo.

    El hueco se reserva dentro del lock y se duerme fuera. Si el ``sleep``
    ocurriera con el cerrojo tomado, un scraper esperando a FútbolFantasy
    pararía también las peticiones a LaLiga y a las demás fuentes: con 8
    workers, la espera de un dominio se convertiría en la de todos.

    La reserva (``max(ahora, último + cooldown)``) es lo que garantiza el
    espaciado: N hilos que entran a la vez se llevan N huecos consecutivos de
    la misma cola, nunca el mismo, así que sus GET salen separados por el
    cooldown aunque el ``sleep`` de cada uno se solape con el de los demás.
    """
    sleep = sleeper or time.sleep
    if not pacing_enabled():
        return 0.0
    domain = urllib.parse.urlparse(url).netloc.lower()
    cooldown = cooldown_for(domain)
    if cooldown <= 0 and minimum_wait <= 0:
        return 0.0
    now_fn = clock or _PACING_CLOCK
    with _rate_limit_lock:
        now = float(now_fn())
        last = _last_request_time.get(domain)
        start = now + max(0.0, minimum_wait)
        slot = start if last is None else max(start, last + cooldown)
        _last_request_time[domain] = slot
        wait = slot - now
    if wait > 0:
        sleep(wait)
    return wait


def reset_rate_limits() -> None:
    """Olvida los huecos reservados por dominio. Solo para pruebas."""
    with _rate_limit_lock:
        _last_request_time.clear()


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


# ---------------------------------------------------------------------------
# Sesión oficial: curl_cffi + air-gap en la fábrica
# ---------------------------------------------------------------------------
# La sesión es de proceso: keep-alive, cookies y huella TLS idénticos entre
# llamadas, como la app de un móvil que no se cierra. Se construye **solo** en
# producción; en cualquier otro entorno ``official_session()`` lanza y no hay
# objeto que pueda abrir un socket. Es la última línea del air-gap: aunque un
# helper nuevo se salte ``get_json``, no tiene sesión con la que salir.
OFFICIAL_TIMEOUT: tuple[float, float] = (10.0, 45.0)
_official_session: Any | None = None
_official_session_lock = threading.Lock()


class OfficialSession:
    """Vista mínima de la sesión de curl: ``get`` y ``close``, nada más.

    No expone ``post``/``put``/``delete``: la API oficial es de solo lectura y
    la forma más segura de garantizarlo es que los métodos no existan.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    def get(self, url: str, *, headers: Mapping[str, str]) -> Any:
        return self._session.get(url, headers=dict(headers), timeout=OFFICIAL_TIMEOUT)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


def _build_curl_session() -> Any:
    """Crea la sesión con huella de Chrome y cabeceras inmutables."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise FantasyHttpError(
            "Falta curl_cffi. Instálalo con `python -m pip install curl_cffi` "
            "antes de arrancar con LALIGA_ENV=production.",
            code="missing_dependency",
        ) from exc
    session = curl_requests.Session(
        impersonate=TLS_IMPERSONATE,
        headers=dict(REQUIRED_HEADERS),
        allow_redirects=False,
        timeout=OFFICIAL_TIMEOUT,
        # Sin reintentos internos de libcurl: el kill switch decide, no la
        # librería. Un retry automático aquí sería justo el efecto amplificador
        # que el contrato prohíbe.
        retry=0,
        default_headers=False,
    )
    return OfficialSession(session)


def official_session() -> Any:
    """Sesión de proceso contra LaLiga. Solo existe en producción."""
    global _official_session
    if not is_production():
        raise FantasyHttpError(
            "Air-gap: la sesión oficial solo se construye con LALIGA_ENV=production. "
            "En development/test se sirve exclusivamente la copia de .cache/.",
            code="air_gapped",
            details={"environment": environment()},
        )
    with _official_session_lock:
        if _official_session is None:
            _official_session = _build_curl_session()
        return _official_session


def close_official_session() -> None:
    """Cierra la sesión de proceso. Idempotente."""
    global _official_session
    with _official_session_lock:
        session = _official_session
        _official_session = None
    if session is not None:
        session.close()


def _assert_simulated_transport(http: Any) -> bool:
    """Valida un cliente inyectado y dice si es un transporte simulado.

    El único cliente inyectable legítimo es un ``httpx.Client`` con
    ``MockTransport`` (las pruebas): no puede abrir un socket real, así que la
    lógica de red se puede ejercitar sin romper el air-gap. Cualquier otro
    cliente se rechaza fuera de producción.
    """
    transport = getattr(http, "_transport", None)
    if isinstance(transport, httpx.MockTransport):
        return True
    if getattr(http, "__fantasy_simulated__", False) is True:
        return True
    if is_production():
        return False
    raise FantasyHttpError(
        "Air-gap: un cliente HTTP inyectado fuera de producción tiene que ser simulado "
        "(httpx.MockTransport). No se permite un cliente real sin LALIGA_ENV=production.",
        code="air_gapped",
        details={"environment": environment()},
    )


def _network_errors() -> tuple[type[BaseException], ...]:
    """Errores de transporte de httpx y, si está, de curl_cffi."""
    errors: list[type[BaseException]] = [httpx.TransportError]
    try:
        from curl_cffi import CurlError

        errors.append(CurlError)
    except ImportError:  # pragma: no cover - entorno sin curl_cffi
        pass
    return tuple(errors)


_NETWORK_ERRORS = _network_errors()


# --- Punto de inyección para pruebas ---------------------------------------
# ``ExternalClient()`` sin argumentos es el camino normal de los scrapers y en
# development no tiene sesión HTTP. Para poder ejercitar la lógica contra un
# transporte simulado sin abrir la puerta a uno real, la suite instala aquí una
# fábrica que **debe** devolver un ``httpx.Client`` con ``MockTransport``. Con
# la fábrica vacía (``None``) no hay atajo: es lo que corre en producción.
TRANSPORT_FACTORY: Callable[[], Any] | None = None


def _injected_transport() -> Any | None:
    """Cliente simulado instalado por la suite, si lo hay y es seguro."""
    factory = TRANSPORT_FACTORY
    if factory is None:
        return None
    http = factory()
    if http is None:
        return None
    if not _assert_simulated_transport(http):
        raise FantasyHttpError(
            "La fábrica de transporte solo puede devolver un MockTransport.",
            code="air_gapped",
        )
    return http


def require_id(value: str, label: str) -> str:
    if not _ID.fullmatch(value):
        raise FantasyHttpError(f"{label} contiene caracteres no permitidos.", code="invalid_id")
    return urllib.parse.quote(value, safe="")


def league_list_urls() -> list[str]:
    """Ligas de la cuenta. **Primero el endpoint que responde hoy.**

    ``/api/v4/leagues`` ya no existe en ninguno de los dos hosts: en
    ``fantasy-api`` contesta ``500`` y en ``api-fantasy`` ``502``. Eso importa
    mucho más de lo que parece, porque un 5xx **no** es un 404: ``_send``
    dispara el kill switch y mata la pasada entera. Con las rutas muertas
    delante, *todo* refresco moría en el primer GET de ``resolve_league`` —con
    la foto de ayer servida como si fuera de hoy—. La ruta viva de hoy es la
    de competición, que devuelve la misma lista con ``team.id``.

    Las variantes retiradas se quitan de la lista en lugar de dejarlas de
    respaldo: una URL que responde 5xx no es un respaldo, es una mina.
    """
    return [with_lang(f"{COMPETITION_BASE}/leagues")]


def market_urls(league_id: str) -> list[str]:
    """Ofertas de la liga. Solo las rutas vivas, y primero la que responde.

    ``/api/v3/.../market`` contesta ``500`` y ``api-fantasy`` entero está
    caído con ``502``. Como ``_first_matching`` solo salta de host ante un
    404/410 o una caída de red, esas entradas no eran un plan B: eran un
    kill switch esperando a que la primera URL fallara por cualquier motivo.
    """
    league = require_id(league_id, "league_id")
    return [
        with_lang(f"{COMPETITION_BASE}/league/{league}/market"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/market"),
    ]


def team_index_urls(league_id: str) -> list[str]:
    """Clasificación/índice de equipos. Sin las rutas que hoy dan 5xx.

    ``api-fantasy.llt-services.com`` está entero en ``502``, así que sus dos
    entradas ``/ranking`` no eran respaldo: eran un kill switch. Se quedan la
    ruta viva de competición y la de equipos del mismo host.
    """
    league = require_id(league_id, "league_id")
    return [
        with_lang(f"{COMPETITION_BASE}/leagues/{league}/standing"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/ranking"),
        with_lang(f"{COMPETITION_BASE}/leagues/{league}/teams"),
    ]


def activity_page_urls(league_id: str, page: int) -> list[str]:
    """Actividad paginada de la temporada actual. La página 0 es la más reciente."""
    league = require_id(league_id, "league_id")
    return [with_lang(f"{COMPETITION_BASE}/leagues/{league}/activity/{page}")]


def activity_concat_url(league_id: str) -> str:
    """Clave de caché del historial ya concatenado. No se pide a la API."""
    league = require_id(league_id, "league_id")
    return with_lang(f"{COMPETITION_BASE}/leagues/{league}/activity/concat")


def activity_urls(league_id: str) -> list[str]:
    """Historial de noticias y movimientos. El primero que responda gana.

    Si todos faltan, la caja reconstruida no se inventa: se queda en null.

    Se quitan las entradas de ``api-fantasy`` porque ese host responde
    ``502`` de forma sistemática: no era un respaldo, era un kill switch al
    final de la lista. El camino normal es ``_activity_pages`` (paginado, que
    sí responde 200); esto solo cubre el caso de que el paginado no dé nada.
    """
    league = require_id(league_id, "league_id")
    return [
        with_lang(f"{COMPETITION_BASE}/leagues/{league}/news"),
        with_lang(f"{COMPETITION_BASE}/league/{league}/news"),
        with_lang(f"{LIVE_ORIGIN}/api/v3/leagues/{league}/news"),
        with_lang(f"{LIVE_ORIGIN}/api/v3/league/{league}/activity"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/activity"),
        with_lang(f"{LIVE_LEAGUE_BASE}/{league}/news"),
    ]


def saved_lineup_urls(team_id: str) -> list[str]:
    """Once guardado en la app. No es el once que calcula el solver."""
    team = require_id(team_id, "team_id")
    return [with_lang(f"{COMPETITION_BASE}/teams/{team}/lineup")]


def players_urls() -> list[str]:
    """Catálogo de competición con URL de foto oficial por jugador."""
    return [with_lang(f"{COMPETITION_BASE}/players")]


def team_urls(league_id: str, team_id: str) -> list[str]:
    """Plantilla de un equipo. Solo la ruta viva.

    ``/api/v3/.../teams/{equipo}`` y ``/api/v4/leagues/{liga}/teams/{equipo}``
    devuelven ``500`` en ``fantasy-api``, y todo ``api-fantasy`` está en
    ``502``. Antes eran «respaldo»; en la práctica eran cuatro kill switches
    detrás de la única URL buena, y con 20 equipos por pasada bastaba un 404
    puntual para que la siguiente entrada matara el refresco entero.
    """
    league = require_id(league_id, "league_id")
    team = require_id(team_id, "team_id")
    return [with_lang(f"{COMPETITION_BASE}/leagues/{league}/teams/{team}")]


class LaligaClient:
    """Cliente de la API oficial. En desarrollo solo lee de ``.cache/``.

    ``http`` existe únicamente para inyectar un transporte de pruebas
    (``httpx.MockTransport``). En un proceso normal no se pasa: la sesión se
    construye aquí, y solo si ``LALIGA_ENV=production``.
    """

    def __init__(
        self,
        tokens: TokenSource | None = None,
        cache: ResponseCache | None = None,
        http: Any | None = None,
        sleeper: Callable[[float], None] | None = None,
        jitter: bool = True,
    ) -> None:
        if tokens is None:
            from toolbox.auth import TokenManager

            tokens = TokenManager()
        self._tokens = tokens
        self._owns_cache = cache is None
        self._cache = cache or ResponseCache()
        self._sleeper = sleeper or time.sleep
        # El jitter pasa por ``sleeper``, no por ``time.sleep`` directo: las
        # pruebas inyectan un sleeper nulo y siguen sin esperar.
        self._jitter = jitter
        self._owns_http = http is None
        self._simulated = False
        if http is not None:
            # Transporte inyectado (pruebas). Se exige que sea uno simulado si
            # el proceso no está en producción: así ni un descuido en una
            # prueba puede abrir un socket real.
            self._simulated = _assert_simulated_transport(http)
            self._http: Any | None = http
        elif is_production():
            self._http = official_session()
        else:
            # Air-gap: no se construye ni el objeto de sesión. Cualquier
            # llamada acabará en la caché o en ``offline_cache_miss``.
            self._http = None
        if self._http is not None and isinstance(self._http, httpx.Client):
            _install_read_only_guard(self._http)

    def _offline_only(self) -> bool:
        """``True`` si esta llamada tiene que resolverse solo con disco.

        Tres motivos, en orden de dureza:

        * ``FANTASY_OFFLINE=1``: modo avión global, manda siempre.
        * Veto de lectura del tablero (``no_network()``).
        * Air-gap de ``LALIGA_ENV``: en development/test no hay red real. La
          excepción es un transporte simulado inyectado, que es el mecanismo
          con el que la suite ejercita la lógica sin salir a Internet.
        """
        if offline_mode() or network_forbidden():
            return True
        return air_gapped() and not self._simulated

    def close(self) -> None:
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
        document = build_market_document(
            league_id=ref["league_id"],
            league_name=ref.get("name"),
            source_url=source,
            payload=payload,
            fetched_at=_now(),
        )
        # Edad real del cuerpo servido. Sin esto el documento se sellaba con la
        # hora del proceso y una copia de hace días pasaba por una foto de hoy:
        # el snapshot diario grababa el mismo precio con fecha nueva y el motor
        # leía un día plano que nunca existió.
        age = self._cache.age_seconds(source, kind="json")
        if age is not None:
            document["source_age_seconds"] = round(float(age), 3)
            document["source_stored_at"] = (time.time() - float(age))
        self._stamp_images(document.get("listings"), fresh=fresh)
        return document

    def players_document(self, *, fresh: bool = False) -> list[Any]:
        """Catálogo público de jugadores de la competición (incluye ``image``).

        Es el documento más caro de la API y el que más expone la cuenta: en
        air-gap ``fresh`` se ignora y siempre se sirve la copia de disco. El
        refresco real es manual (``catalog_refresh_document``) y solo si el TTL
        de 6 h ya venció.
        """
        _source, payload = self._first_matching(
            players_urls(),
            ttl=PLAYERS_TTL_SECONDS,
            fresh=fresh,
            accept=_is_players_catalog,
        )
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("players", "elements", "items", "data", "content"):
                rows = payload.get(key)
                if isinstance(rows, list):
                    return rows
        return []

    def players_age_seconds(self, *, now: float | None = None) -> float | None:
        """Edad de la copia del catálogo. ``None`` si no hay copia o sello."""
        for url in players_urls():
            age = self._cache.age_seconds(url, now=now)
            if age is not None:
                return age
        return None

    def catalog_refresh_due(self, *, now: float | None = None) -> bool:
        """``True`` si toca refrescar: no hay copia o ya pasó el TTL de 6 h."""
        age = self.players_age_seconds(now=now)
        return age is None or age >= PLAYERS_TTL_SECONDS

    def catalog_refresh_document(self, *, force: bool = False) -> list[Any]:
        """Refresco manual del catálogo, sujeto al TTL de 6 h.

        Es el único camino que puede abrir un socket para ``/players`` y aun
        así solo con ``LALIGA_ENV=production``. ``force=True`` salta el TTL,
        pero nunca el air-gap: en development sigue leyendo de disco.
        """
        if not force and not self.catalog_refresh_due():
            return self.players_document(fresh=False)
        return self.players_document(fresh=True)

    def image_index(self, *, fresh: bool = False) -> dict[str, str]:
        """Mapa ``player_id`` → URL CDN oficial."""
        return image_index_from_players(self.players_document(fresh=fresh))

    def _stamp_images(self, rows: Any, *, fresh: bool) -> None:
        if not isinstance(rows, list) or not rows:
            return
        try:
            index = self.image_index(fresh=fresh)
        except FantasyHttpError:
            return
        if index:
            attach_image_urls(rows, index)

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
        own_team_id = ref.get("own_team_id")
        league_key = ref["league_id"]

        def _one_squad(seed: dict[str, Any]) -> dict[str, Any]:
            embedded = seed.get("embedded")
            if isinstance(embedded, dict):
                return normalize_squad(
                    embedded,
                    seed=seed,
                    own_team_id=own_team_id,
                    source_url=index_url,
                )
            try:
                source, payload = self._first_matching(
                    team_urls(league_key, str(seed["team_id"])),
                    ttl=SQUAD_TTL_SECONDS,
                    fresh=fresh,
                    accept=lambda body: isinstance(body, dict) and isinstance(body.get("players"), list),
                )
            except FantasyHttpError as exc:
                return empty_squad(seed, own_team_id=own_team_id, message=str(exc))
            if not isinstance(payload, dict):
                return empty_squad(seed, own_team_id=own_team_id, message="La plantilla no es un objeto.")
            return normalize_squad(
                payload,
                seed=seed,
                own_team_id=own_team_id,
                source_url=source,
            )

        slots: list[dict[str, Any] | None] = [None] * len(seeds)
        # 3 conexiones como máximo: 8 peticiones simultáneas idénticas es un
        # patrón de bot y no aporta nada frente a TTLs de 10 min.
        workers = min(3, max(1, len(seeds)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(inherited(_one_squad), seed): index for index, seed in enumerate(seeds)}
            for future in as_completed(futures):
                slots[futures[future]] = future.result()
        squads = [row for row in slots if row is not None]
        document = build_squads_document(
            league_id=ref["league_id"],
            league_name=ref.get("name"),
            index_url=index_url,
            squads=squads,
            fetched_at=_now(),
        )
        document["truncated"] = truncated
        document["index_empty"] = len(seeds) == 0
        try:
            index = self.image_index(fresh=fresh)
        except FantasyHttpError:
            index = {}
        if index:
            for squad in document.get("squads") or []:
                if isinstance(squad, dict):
                    attach_image_urls(squad.get("players"), index)
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

    def _activity_page(
        self,
        league_id: str,
        page: int,
        *,
        fresh: bool,
        retry_429: bool,
    ) -> tuple[str, Any]:
        return self._first_matching(
            activity_page_urls(league_id, page),
            ttl=ACTIVITY_TTL_SECONDS,
            fresh=fresh,
            accept=_is_activity,
            retry_429=retry_429,
        )

    def _activity_pages(self, league_id: str, *, fresh: bool) -> dict[str, Any] | None:
        """Concatena páginas hasta una vacía. None si la página 0 no existe.

        Un 429 a mitad de historial no tira lo ya leído: Caja no puede quedarse
        10 minutos reintentando página 12. Las páginas posteriores van en lote.
        """
        collected: list[Any] = []
        source: str | None = None

        def _append(page: int, page_source: str, payload: Any) -> bool:
            nonlocal source
            if not isinstance(payload, list) or not payload:
                return False
            first = payload[0] if isinstance(payload[0], dict) else None
            previous = collected[0] if collected and isinstance(collected[0], dict) else None
            if page > 0 and first is not None and previous is not None and first.get("id") == previous.get("id"):
                return False
            collected.extend(payload)
            source = page_source
            return True

        try:
            page_source, payload = self._activity_page(league_id, 0, fresh=fresh, retry_429=True)
        except FantasyHttpError as exc:
            if exc.code in {"unauthorized", "auth_required"}:
                raise
            if exc.code == "rate_limited":
                raise
            return None
        if not _append(0, page_source, payload):
            return {"ok": True, "source_url": page_source, "payload": [], "error": None, "attempts": []}

        page = 1
        while page < ACTIVITY_MAX_PAGES:
            batch = list(range(page, min(ACTIVITY_MAX_PAGES, page + ACTIVITY_PAGE_BATCH)))
            slots: dict[int, tuple[str, Any] | str] = {}

            def _one(index: int) -> tuple[int, tuple[str, Any] | str]:
                try:
                    return index, self._activity_page(league_id, index, fresh=fresh, retry_429=False)
                except FantasyHttpError as exc:
                    if exc.code in {"unauthorized", "auth_required"}:
                        raise
                    if exc.code == "rate_limited":
                        return index, "rate_limited"
                    return index, "missing"

            if len(batch) == 1:
                index, result = _one(batch[0])
                slots[index] = result
            else:
                workers = min(len(batch), ACTIVITY_PAGE_BATCH)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(inherited(_one), index) for index in batch]
                    for future in as_completed(futures):
                        index, result = future.result()
                        slots[index] = result

            stop = False
            for index in batch:
                result = slots.get(index, "missing")
                if result == "rate_limited" or result == "missing":
                    stop = True
                    break
                if not isinstance(result, tuple) or not _append(index, result[0], result[1]):
                    stop = True
                    break
            if stop:
                break
            page += len(batch)

        if source is None:
            return None
        return {"ok": True, "source_url": source, "payload": collected, "error": None, "attempts": []}

    def _store_activity_concat(self, league_id: str, payload: dict[str, Any]) -> None:
        stored = dict(payload)
        # Sello propio: la guarda de 2 h necesita la edad real, y el TTL del
        # caché (30 min) no la dice una vez caducado.
        stored["cached_at"] = time.time()
        try:
            self._cache.put_json(activity_concat_url(league_id), stored, ACTIVITY_CONCAT_TTL_SECONDS)
        except Exception:
            return

    def _cached_activity_concat(self, league_id: str, *, allow_expired: bool) -> dict[str, Any] | None:
        try:
            cached = (
                self._cache.get_json_stale(activity_concat_url(league_id))
                if allow_expired
                else self._cache.get_json(activity_concat_url(league_id))
            )
        except Exception:
            return None
        if not isinstance(cached, dict) or cached.get("ok") is not True:
            return None
        payload = cached.get("payload")
        if not isinstance(payload, list) or not payload:
            return None
        return cached

    def _activity_concat_age(self, document: dict[str, Any]) -> float | None:
        stamp = document.get("cached_at")
        if not isinstance(stamp, (int, float)):
            return None
        return max(0.0, time.time() - float(stamp))

    def activity_payload(self, league_id: str, *, fresh: bool) -> dict[str, Any]:
        """Lee el historial de la liga. Primero las páginas nuevas; si faltan, el path viejo.

        Un 401 en la página 0 se propaga. Un 429 a mitad de historial conserva
        lo leído. El concatenado se reutiliza para que Actualizar no vuelva a
        pedir las 40 páginas: con menos de ``ACTIVITY_CONCAT_FRESH_MIN_AGE_SECONDS``
        se sirve aunque llegue ``fresh=True``.
        """
        cached = self._cached_activity_concat(league_id, allow_expired=fresh or offline_mode())
        if cached is not None:
            age = self._activity_concat_age(cached)
            # En modo avión no hay páginas nuevas que pedir: el concatenado en
            # disco es el historial, tenga la edad que tenga.
            if offline_mode() or not fresh or (age is not None and age < ACTIVITY_CONCAT_FRESH_MIN_AGE_SECONDS):
                return {
                    "ok": True,
                    "source_url": cached.get("source_url"),
                    "payload": cached.get("payload"),
                    "error": None,
                    "attempts": [],
                    "from_cache": True,
                }
        try:
            paged = self._activity_pages(league_id, fresh=fresh)
        except FantasyHttpError as exc:
            if exc.code in {"unauthorized", "auth_required", "rate_limited"}:
                raise
            paged = None
        if paged is not None:
            self._store_activity_concat(league_id, paged)
            return paged
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
        document = {"ok": True, "source_url": source, "payload": payload, "error": None, "attempts": []}
        self._store_activity_concat(league_id, document)
        return document

    def resolve_league(self, explicit: str | None, *, fresh: bool) -> tuple[dict[str, Any], str]:
        requested = (explicit or league_id_from_env() or "").strip()
        if requested:
            require_id(requested, "league_id")
        source, leagues = self._load_leagues(fresh=fresh)
        if requested:
            for league in leagues:
                if league["league_id"] == requested:
                    return league, source
            if len(leagues) == 1:
                return leagues[0], source
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
        upstream_retries: int = 0,
        retry_429: bool = False,
        stale_fallback: bool = True,
    ) -> Any:
        """Lee un JSON de LaLiga. En desarrollo, solo desde disco.

        ``upstream_retries`` y ``retry_429`` se aceptan por compatibilidad con
        las llamadas existentes, pero ya no hacen nada: contra la API oficial
        no hay reintentos de ningún tipo. Un 429 o un 5xx matan el proceso.
        """
        self._ensure_allowed(url)
        if self._offline_only():
            # Air-gap (development/test) o modo avión: ``fresh`` y ``ttl`` se
            # ignoran y no se toca ``_send``. Pero un 503 seco por caché vacía
            # no es aceptable en desarrollo: el requisito es leer ``.cache/``
            # y, si no hay fichero, explicarlo con claridad.
            cached = self._stale_json(url, offline=True)
            if cached is None:
                raise offline_cache_miss(url)
            api_meter.record_cache_hit(url=url)
            return cached
        if not fresh and ttl > 0:
            cached = self._cache.get_json(url)
            if cached is not None:
                api_meter.record_cache_hit(url=url)
                return cached
        try:
            return self._live_json(url, ttl=ttl)
        except FantasyHttpError as exc:
            # Solo una caída de red llega aquí: los 401/403/429/5xx ya han
            # matado el proceso en ``_send``. Una copia caducada es preferible
            # a romper el tablero, y no supone tráfico nuevo.
            if not stale_fallback or exc.code not in _STALE_SURVIVAL_CODES:
                raise
            stale = self._stale_json(url)
            if stale is None:
                raise
            return stale

    def _live_json(self, url: str, *, ttl: float) -> Any:
        """Una sola petición. Sin reintentos: el kill switch decide por error."""
        try:
            response, _token = self._send(url)
        except _NETWORK_ERRORS as exc:
            raise FantasyHttpError(
                f"Error de red al llamar a la API: {exc.__class__.__name__}.",
                code="network",
            ) from exc
        status = _status_code(response)
        if status in {301, 302, 303, 307, 308}:
            raise FantasyHttpError("Redirección no resuelta.", status=status, code="redirect")
        if status in KILL_SWITCH_STATUSES or status >= 500:
            # Defensa en profundidad: aunque ``_send`` ya dispara, una respuesta
            # construida a mano (pruebas) tampoco puede seguir el camino.
            trip_kill_switch(status=status, url=url)
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

    def _stale_json(self, url: str, *, offline: bool = False) -> Any | None:
        """Última copia válida en disco de ``url``, aunque esté caducada.

        Es el fallback de supervivencia: si LaLiga devuelve 5xx tras todos los
        reintentos, el tablero prefiere un mercado de hace tres horas a un error
        en pantalla. Un fallo al leer el caché nunca sustituye al error real.

        Con ``offline=True`` es la única fuente posible: no hay red de respaldo,
        así que la copia caducada se sirve sin el aviso de host caído.
        """
        try:
            stale = self._cache.get_json_stale(url)
        except Exception:
            return None
        if stale is None:
            return None
        if offline:
            logger.info("Modo avión: sirvo la copia en caché de %s.", _loggable_url(url))
        else:
            logger.warning(
                "La API de LALIGA no responde y se agotaron los reintentos. Sirvo la copia en caché de %s.",
                _loggable_url(url),
            )
        return stale

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
        retry_429: bool = True,
    ) -> tuple[str, Any]:
        misses: list[dict[str, Any]] = []
        last_error: FantasyHttpError | None = None
        for url in urls:
            try:
                payload = self.get_json(
                    url,
                    ttl=ttl,
                    fresh=fresh,
                    stale_fallback=False,
                )
            except FantasyHttpError as exc:
                if exc.code == OFFLINE_MISS_CODE:
                    # Air-gap / modo avión: este host no tiene copia, pero otro
                    # del contrato sí puede tenerla. Se sigue con el siguiente.
                    misses.append({"url": url, "status": exc.status, "code": exc.code})
                    last_error = exc
                    continue
                # Solo se prueba otro host ante un 404/410 o una caída de red.
                # Un 5xx, un 401, un 403 o un 429 ya han disparado el kill
                # switch dentro de ``_send`` y el proceso no sigue vivo.
                if exc.status in {404, 410} or exc.code in {"network", "invalid_json"}:
                    misses.append({"url": url, "status": exc.status, "code": exc.code})
                    last_error = exc
                    continue
                raise
            if accept(payload):
                return url, payload
            misses.append({"url": url, "status": 200, "code": "unexpected_shape"})
        if self._offline_only():
            # Air-gap de *este cliente*: ningún host «respondió» porque no se ha
            # salido a la red. Se busca la copia en disco de cualquiera de las
            # URLs del contrato y, si no hay ninguna, se aborta con 503.
            #
            # Se pregunta al cliente y no a ``network_sealed()``: aquel es un
            # predicado global del entorno, y con un transporte simulado
            # inyectado (``httpx.MockTransport``) el air-gap no aplica. Usando
            # el global, un 404 real del transporte simulado caía en esta rama
            # y resucitaba la copia caducada en lugar de propagar el 404.
            survived = self._first_stale(urls, accept=accept, offline=True)
            if survived is not None:
                return survived
            raise offline_cache_miss(urls[0] if urls else "")
        # Ningún host vivo sirvió el recurso: la copia en disco más reciente de
        # cualquiera de las URLs del contrato. Es el último recurso tras una
        # caída de red, no tras un bloqueo (eso ya mató el proceso).
        failed = [item["url"] for item in misses if item["code"] in _STALE_SURVIVAL_CODES]
        if failed:
            survivors = failed + [url for url in urls if url not in failed]
            survived = self._first_stale(survivors, accept=accept)
            if survived is not None:
                return survived
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

    def _first_stale(
        self,
        urls: list[str],
        *,
        accept: Callable[[Any], bool],
        offline: bool = False,
    ) -> tuple[str, Any] | None:
        """Primera copia caducada de ``urls`` que aún tenga forma válida."""
        for url in urls:
            try:
                stale = self._cache.get_json_stale(url)
            except Exception:
                continue
            if stale is None or not accept(stale):
                continue
            if offline:
                logger.info("Modo avión: sirvo la copia en caché de %s.", _loggable_url(url))
                return url, stale
            logger.warning(
                "Ningún host de LALIGA respondió. Sirvo la copia en caché de %s para no romper el tablero.",
                _loggable_url(url),
            )
            return url, stale
        return None

    def _human_pause(self) -> float:
        """Segundos que debe esperar la próxima petición. **No duerme.**

        La pausa la decide el ``HUMAN_PACER`` de proceso, no una instancia: con
        un rango de 12–25 s y una pausa de actividad cada 3–4 peticiones, la
        media ronda los 33 s por GET (la pausa sustituye a la espera de esa
        petición, no se suma).

        Devuelve lo sorteado para pasárselo a ``pace_domain`` como
        ``minimum_wait``, que es quien duerme una sola vez: así el suelo por
        dominio y la cadencia humana no se suman (serían dos esperas diciendo
        lo mismo) sino que se funden en una. Dormir aquí **y** reservar allí el
        hueco con la misma cifra pagaba la pausa dos veces por petición.

        ``FANTASY_NET_PACING=0`` apaga el controlador por dominio, pero no el
        jitter explícito del cliente (``jitter=True``): son dos protecciones
        distintas y el fixture de la suite apaga solo la primera. Por eso esta
        función sortea siempre y es ``_send`` quien decide dónde se duerme.
        """
        if not self._jitter:
            return 0.0
        delay, _pause = HUMAN_PACER.next_delay()
        return delay

    def _send(self, url: str, *, retry: bool = False) -> tuple[Any, str]:
        """Única salida real a LaLiga. Serializada, con pausa y con kill switch."""
        self._ensure_allowed(url)
        if self._offline_only():
            # Cinturón y tirantes: aunque alguien llame a ``_send`` sin pasar por
            # ``get_json``, en development/test o modo avión no sale nada.
            raise offline_cache_miss(url)
        _refuse_network(url)
        if self._http is None:
            raise FantasyHttpError(
                "Air-gap: el cliente no tiene sesión oficial. Arranca con LALIGA_ENV=production.",
                code="air_gapped",
            )
        headers = dict(REQUIRED_HEADERS)
        token = self._tokens.authorization_value()
        headers["Authorization"] = token
        # Concurrencia 1 de verdad: la espera y la petición ocurren dentro del
        # mismo cerrojo de proceso. Si la pausa quedara fuera, dos hilos podrían
        # dormir en paralelo y disparar dos GET casi simultáneos al despertar.
        with laliga_serialized():
            pause = self._human_pause()
            # El suelo duro por dominio y la cadencia humana se funden en una
            # sola espera: ``minimum_wait`` es la pausa ya sorteada, no una
            # espera extra, y ``pace_domain`` es quien duerme. Dormirla aquí
            # además pagaba 12–25 s dos veces por petición.
            waited = pace_domain(url, sleeper=self._sleeper, minimum_wait=pause)
            if pause > 0 and waited <= 0:
                # ``FANTASY_NET_PACING=0`` apaga el controlador por dominio (y
                # con él su ``sleep``), pero no el jitter del cliente. Sin esta
                # rama, apagar el controlador en las pruebas apagaría también la
                # cadencia humana que ``jitter=True`` promete.
                self._sleeper(pause)
            with api_meter.call(url=url, retry=retry) as probe:
                try:
                    response = self._http.get(url, headers=headers)
                    probe.status = _status_code(response)
                finally:
                    # Un 403, un 503, un 200 o una caída de red: todo queda en disco.
                    record_network_call(probe, url=url)
        status = _status_code(response)
        if status in KILL_SWITCH_STATUSES or status >= 500:
            trip_kill_switch(status=status, url=url)
        return response, token

    @staticmethod
    def _ensure_allowed(url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in ALLOWED_NETLOCS:
            raise FantasyHttpError("URL fuera de los dominios de LALIGA Fantasy.", code="forbidden_url")


def network_log_path() -> Path:
    """Ruta de la bitácora de red. Respeta ``FANTASY_CACHE_DIR``."""
    return cache_root() / NETWORK_LOG_FILENAME


def log_network_call(
    *,
    url: str | None = None,
    fuente: str | None = None,
    metodo: str = NETWORK_LOG_METHOD,
    status: int | None = None,
    duracion_ms: float = 0.0,
    now: float | None = None,
) -> None:
    """Apunta una llamada HTTP real en ``.cache/network_logs.jsonl``.

    Solo se llama desde el punto donde ya se tocó la red: un acierto de
    caché nunca llega aquí. Nunca lanza —una bitácora rota no puede tumbar
    una petición— y no guarda token ni cuerpo, solo lo que pide la auditoría.
    """
    stamp = time.time() if now is None else now
    source = fuente or api_meter.source_for_url(url or "")[0]
    if status is None:
        code = "red"
    elif status >= 400:
        code = "error"
    else:
        code = "ok"
    entry = {
        "timestamp": datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat(),
        "fuente": source,
        "metodo": metodo.upper(),
        "status": status,
        "duracion_ms": round(max(0.0, float(duracion_ms)), 1),
        "resultado": code,
        "url": _loggable_url(url),
    }
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    try:
        path = network_log_path()
        with _NETWORK_LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_network_log(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        return


def record_network_call(probe: api_meter.Call, *, url: str | None = None) -> None:
    """Cierra la línea de la bitácora con lo que midió el ``api_meter``."""
    started = getattr(probe, "_started", 0.0)
    duration = max(0.0, (time.monotonic() - started) * 1000.0) if started else 0.0
    log_network_call(
        url=url,
        fuente=probe.source,
        status=probe.status,
        duracion_ms=duration,
    )


def _loggable_url(url: str | None) -> str | None:
    """Ruta sin query: las URLs llevan ids y ``x-lang``, no credenciales."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    return f"{host}{parsed.path}"


def _rotate_network_log(path: Path) -> None:
    try:
        if path.stat().st_size < NETWORK_LOG_MAX_BYTES:
            return
    except OSError:
        return
    try:
        path.replace(path.with_name(path.name + ".1"))
    except OSError:
        return


def _status_code(response: Any) -> int:
    """``status_code`` de httpx o de curl_cffi. ``0`` si no hay respuesta."""
    value = getattr(response, "status_code", None)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _decode_json(response: Any) -> Any:
    """JSON de una respuesta de httpx o de curl_cffi."""
    status = _status_code(response)
    content = getattr(response, "content", b"")
    if status == 204 or not content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise FantasyHttpError("La API no devolvió JSON.", status=status, code="invalid_json") from exc


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


def _is_players_catalog(payload: Any) -> bool:
    """El catálogo de fotos trae ``image`` (o ``positionId``) en cada fila."""
    if isinstance(payload, list):
        if not payload:
            return False
        sample = [row for row in payload[:8] if isinstance(row, dict)]
        if not sample:
            return False
        return any("image" in row or "imageUrl" in row or "positionId" in row for row in sample)
    if isinstance(payload, dict):
        for key in ("players", "elements", "items", "data", "content"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return _is_players_catalog(rows)
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
        "understat.com",
        "www.understat.com",
        "www.jornadaperfecta.com",
        "jornadaperfecta.com",
        "www.predicted11.com",
        "predicted11.com",
        "tmapi.transfermarkt.technology",
        "tmapi-alpha.transfermarkt.technology",
        "transfermarkt-api.fly.dev",
        "api.the-odds-api.com",
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
        # Dormir FUERA del lock: si no, un scraper en espera bloquea a todos
        # los demás hilos que comparten el limiter (proxy de Next a 0 bytes).
        slept = 0.0
        while True:
            with self._lock:
                now = float(self._clock())
                hits = [stamp for stamp in self._hits.get(identity, []) if now - stamp < self.window_seconds]
                if len(hits) < self.max_calls:
                    hits.append(now)
                    self._hits[identity] = hits
                    return slept
                wait = self.window_seconds - (now - hits[0])
                if wait < 0:
                    wait = 0.0
                before = now
            if wait > 0:
                self._sleeper(wait)
                slept += wait
                if float(self._clock()) <= before:
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

    El air-gap de ``LALIGA_ENV`` cubre **también** estas fuentes. El
    aislamiento tiene que ser del proceso entero, no solo del dominio de la
    liga: una prueba que enriquece el once construye un ``ExternalClient()``
    por su cuenta (``scrapers.refresh_player_titularity``) y, si ese cliente
    pudiera salir, la suite estaría llamando a FútbolFantasy sin que nadie lo
    pidiera. Fuera de producción este cliente solo lee ``.cache/``; la única
    excepción es un transporte simulado inyectado (``httpx.MockTransport``).
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
        self._simulated = False
        if http is not None:
            self._simulated = _assert_simulated_transport(http)
            self._http: Any | None = http
        elif is_production():
            self._http = httpx.Client(
                timeout=_DEFAULT_HTTP_TIMEOUT,
                follow_redirects=True,
                headers={
                    "User-Agent": REQUIRED_HEADERS["User-Agent"],
                    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "es-ES,es;q=0.9",
                },
            )
        else:
            # Air-gap: no se construye el cliente HTTP. La única excepción es la
            # fábrica de transporte simulado que instala la suite: sin ella,
            # cualquier llamada acaba en la copia de disco o en ``offline_miss``.
            injected = _injected_transport()
            self._http = injected
            self._simulated = injected is not None
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
        # Estado del cortacircuitos de Transfermarkt: fallos seguidos y momento
        # del primer fallo del tramo. Se resetea con cada acierto, así que una
        # caída puntual no cierra la fuente para el resto de la pasada.
        self._tm_failures = 0
        self._tm_failure_started_at: float | None = None

    def _offline_only(self) -> bool:
        """``True`` si esta llamada tiene que resolverse solo con disco.

        ``FANTASY_OFFLINE=1`` y el veto de lectura del tablero mandan siempre.
        El air-gap de ``LALIGA_ENV`` es el valor por defecto: en
        ``development``/``test`` no se abre un socket ni a LaLiga ni a las
        fuentes, salvo con un transporte simulado inyectado.
        """
        if offline_mode() or network_forbidden():
            return True
        return air_gapped() and not self._simulated

    @property
    def root(self) -> Path:
        return self._cache.root

    @property
    def transfermarkt_budget(self) -> tuple[int, float]:
        return self._tm_limiter.max_calls, self._tm_limiter.window_seconds

    def transfermarkt_breaker_open(self) -> str | None:
        """Motivo por el que Transfermarkt está cortado, o ``None`` si sigue vivo.

        Existe porque su API pública devuelve 504 pasados 15 s y, sin freno,
        cada nombre costaba 6 intentos × 45 s. La pasada de tendencias se iba a
        horas y el panel no llegaba a pintar nunca la foto nueva.
        """
        if self._tm_failures >= TRANSFERMARKT_MAX_CONSECUTIVE_FAILURES:
            return (
                f"Transfermarkt encadenó {self._tm_failures} fallos: "
                "fuente cortada para no alargar el refresco."
            )
        started = self._tm_failure_started_at
        if started is not None:
            spent = self._clock() - started
            if spent >= TRANSFERMARKT_WALL_BUDGET_SECONDS:
                return (
                    f"Transfermarkt lleva {spent:.0f} s fallando: "
                    "fuente cortada para no alargar el refresco."
                )
        return None

    def _note_transfermarkt(self, *, ok: bool) -> None:
        if ok:
            # Un acierto rearma: la caída no era sistémica.
            self._tm_failures = 0
            self._tm_failure_started_at = None
            return
        self._tm_failures += 1
        if self._tm_failure_started_at is None:
            self._tm_failure_started_at = self._clock()

    def close(self) -> None:
        if self._owns_http and self._http is not None:
            self._http.close()
        if self._owns_cache:
            self._cache.close()

    def __enter__(self) -> ExternalClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def store_page(self, url: str, html: str, *, ttl: float) -> None:
        if ttl > 0:
            self._cache.put_page(url, html, ttl)

    def store_json(self, url: str, payload: Any, *, ttl: float) -> None:
        if ttl > 0:
            self._cache.put_json(url, payload, ttl)

    def get_text(self, url: str, *, ttl: float, fresh: bool) -> tuple[str, bool]:
        self._ensure_allowed(url)
        if self._offline_only():
            # Air-gap / modo avión / lectura del tablero: ``fresh`` y ``ttl`` se
            # ignoran y no se toca la red. Solo vale la copia en disco.
            stale = self._cache.get_page_stale(url)
            if stale is None:
                raise offline_cache_miss(url, external=True)
            api_meter.record_cache_hit(url=url)
            return stale, True
        if not fresh and ttl > 0:
            cached = self._cache.get_page(url)
            if cached is not None:
                api_meter.record_cache_hit(url=url)
                return cached, True
        try:
            body = self._request(url)
        except ExternalHttpError as exc:
            stale = self._cache.get_page_stale(url)
            if stale is not None and exc.code in _STALE_FALLBACK_CODES:
                return stale, True
            raise
        if _looks_blocked(body):
            stale = self._cache.get_page_stale(url)
            if stale is not None:
                return stale, True
            raise ExternalHttpError("La fuente ha servido una página de bloqueo.", code="blocked")
        if ttl > 0:
            self._cache.put_page(url, body, ttl)
        return body, False

    def get_json(self, url: str, *, ttl: float, fresh: bool) -> tuple[Any, bool]:
        self._ensure_allowed(url)
        if self._offline_only():
            # Air-gap / modo avión / lectura del tablero: ``fresh`` y ``ttl`` se
            # ignoran y no se toca la red. Solo vale la copia en disco.
            stale = self._cache.get_json_stale(url)
            if stale is None:
                raise offline_cache_miss(url, external=True)
            api_meter.record_cache_hit(url=url)
            return stale, True
        if not fresh and ttl > 0:
            cached = self._cache.get_json(url)
            if cached is not None:
                api_meter.record_cache_hit(url=url)
                return cached, True
        try:
            body = self._request(url)
        except ExternalHttpError as exc:
            stale = self._cache.get_json_stale(url)
            if stale is not None and exc.code in _STALE_FALLBACK_CODES:
                return stale, True
            raise
        if _looks_blocked(body):
            stale = self._cache.get_json_stale(url)
            if stale is not None:
                return stale, True
            raise ExternalHttpError("La fuente ha servido una página de bloqueo.", code="blocked")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ExternalHttpError("La fuente no devolvió JSON.", code="invalid_json") from exc
        if ttl > 0 and payload is not None:
            self._cache.put_json(url, payload, ttl)
        return payload, False

    def _request_headers(self, url: str) -> dict[str, str] | None:
        host = urllib.parse.urlparse(url).netloc.lower()
        if "understat.com" in host:
            return {
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://understat.com/league/La_liga",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
        if "fbref.com" in host:
            return {
                "Referer": "https://fbref.com/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        if "sofascore.com" in host:
            return {
                "Referer": "https://www.sofascore.com/",
                "Origin": "https://www.sofascore.com",
                "Accept": "application/json, text/plain, */*",
            }
        return None

    def _request(self, url: str) -> str:
        """GET con reintentos, y cortacircuitos propio si el host es Transfermarkt."""
        is_tm = is_transfermarkt_host(urllib.parse.urlparse(url).netloc)
        try:
            text = self._request_inner(url, is_transfermarkt=is_tm)
        except ExternalHttpError:
            if is_tm:
                self._note_transfermarkt(ok=False)
            raise
        if is_tm:
            self._note_transfermarkt(ok=True)
        return text

    def _request_inner(self, url: str, *, is_transfermarkt: bool) -> str:
        if self._offline_only():
            # Air-gap / modo avión / lectura del tablero: ninguna fuente
            # recibe tráfico. La caché ya se intentó en ``get_text``/``get_json``;
            # sin copia, se aborta con ``offline_miss``, que los scrapers tratan
            # como fuente caída y no como error del tablero.
            raise offline_cache_miss(url, external=True)
        if self._http is None:
            raise ExternalHttpError(
                "Air-gap: el cliente de fuentes no tiene sesión HTTP. "
                "Arranca con LALIGA_ENV=production para descargar.",
                code="air_gapped",
            )
        _refuse_network(url)
        if is_transfermarkt:
            # Antes de pagar otro timeout: si la fuente ya venía fallando en
            # serie, se corta aquí. El nombre se queda sin valor y la pasada
            # sigue, en vez de arrastrar horas de 504.
            broken = self.transfermarkt_breaker_open()
            if broken is not None:
                raise ExternalHttpError(broken, code="upstream")
        attempt = 0
        last_network: ExternalHttpError | None = None
        # Transfermarkt tenía 6 intentos de 45 s cada uno: 4,5 min por nombre.
        # Con el cortacircuitos por encima basta con 2: uno normal y un
        # reintento corto. La caché de 24 h sigue sirviendo lo que haya.
        max_attempts = 2 if is_transfermarkt else 4
        while attempt < max_attempts:
            self._acquire_if_needed(url)
            try:
                extra = self._request_headers(url)
                timeout = _TRANSFERMARKT_TIMEOUT if is_transfermarkt_host(urllib.parse.urlparse(url).netloc) else None
                response = self._get(url, extra=extra, timeout=timeout, retry=attempt > 0)
            except httpx.TransportError as exc:
                last_network = ExternalHttpError(
                    f"Error de red al consultar la fuente: {exc.__class__.__name__}.",
                    code="network",
                )
                if attempt >= max_attempts - 1:
                    raise last_network from exc
                self._sleeper(backoff_delay(attempt, None))
                attempt += 1
                continue
            status = response.status_code
            if status == 429:
                if attempt >= max_attempts - 1:
                    raise ExternalHttpError(
                        "La fuente ha limitado las peticiones (HTTP 429).",
                        status=429,
                        code="rate_limited",
                    )
                self._sleeper(backoff_delay(attempt, response.headers.get("Retry-After")))
                attempt += 1
                continue
            if status in _RETRY_UPSTREAM:
                if attempt >= max_attempts - 1:
                    raise ExternalHttpError(
                        f"La fuente respondió HTTP {status}.",
                        status=status,
                        code="upstream",
                    )
                # Mismo criterio que en LALIGA: 1, 2, 4, 8 s. Un scraper que
                # insiste cada segundo contra un 503 solo gana un baneo.
                self._sleeper(upstream_backoff_delay(attempt, response.headers.get("Retry-After")))
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

    def _get(
        self,
        url: str,
        *,
        extra: dict[str, str] | None,
        timeout: httpx.Timeout | None,
        retry: bool,
    ) -> httpx.Response:
        # El mismo controlador de tráfico que LALIGA: FútbolFantasy sale cada
        # 2 s como mínimo aunque ``scrapers`` lo abra desde 8 hilos a la vez.
        # El presupuesto de Transfermarkt (``_acquire_if_needed``) es otra
        # regla, por IP y por ventana, y sigue aplicándose antes.
        if self._http is None:
            raise ExternalHttpError(
                "Air-gap: el cliente de fuentes no tiene sesión HTTP.",
                code="air_gapped",
            )
        pace_domain(url, sleeper=self._sleeper)
        with api_meter.call(url=url, retry=retry) as probe:
            try:
                if extra and timeout is not None:
                    response = self._http.get(url, headers=extra, timeout=timeout)
                elif extra:
                    response = self._http.get(url, headers=extra)
                elif timeout is not None:
                    response = self._http.get(url, timeout=timeout)
                else:
                    response = self._http.get(url)
                probe.status = response.status_code
            finally:
                record_network_call(probe, url=url)
        return response

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

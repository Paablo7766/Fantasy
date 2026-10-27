"""Aislamiento de la suite: ni red real, ni esperas, ni estado compartido.

Tres garantías, en orden de dureza:

1. **Ni un socket real.** ``_no_real_sockets`` parchea ``socket.socket.connect``
   y ``socket.create_connection``: cualquier conexión a una dirección que no
   sea loopback levanta ``AssertionError`` en el acto. La suite puede usar
   ``httpx.MockTransport``, ``TestClient`` (ASGI en proceso) o el loopback de
   un servidor local, pero no puede llamar a Transfermarkt, FútbolFantasy ni,
   por supuesto, a LaLiga. Si una prueba «se cuelga», en realidad estaba
   saliendo a Internet: este cerrojo lo convierte en un fallo inmediato.
2. **Ni esperas reales.** ``FANTASY_NET_PACING=0`` apaga el espaciado por
   dominio (1,5 s en LALIGA, 2 s en FútbolFantasy). Las pruebas que sí quieren
   probar el controlador lo reactivan con
   ``patch.dict(os.environ, {"FANTASY_NET_PACING": "1"})`` e inyectan un reloj
   falso.
3. **Estado de proceso limpio.** La cola de huecos por dominio y el kill switch
   viven en ``toolbox/net.py`` a nivel de módulo: se reinician entre pruebas
   para que un disparo deliberado no contamine a la siguiente.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from toolbox import net

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", ""})
# Caché temporal de la sesión. Se crea en ``pytest_configure`` y se borra al
# terminar: ninguna prueba debe escribir en el ``.cache/`` real del proyecto.
_SESSION_CACHE: Path | None = None


def pytest_configure(config: pytest.Config) -> None:
    global _SESSION_CACHE
    # ``setdefault``: una ejecución manual con FANTASY_NET_PACING=1 puede
    # comprobar que la suite sigue pasando con el espaciado encendido.
    os.environ.setdefault("FANTASY_NET_PACING", "0")
    # El air-gap es el valor por defecto del módulo, pero se fija aquí de forma
    # explícita: una shell con LALIGA_ENV=production no debe convertir la suite
    # en un cliente real de la API.
    os.environ.setdefault("LALIGA_ENV", "development")
    # Cuarta garantía: **ni un byte en la caché real**. Varias pruebas
    # ejercitan caminos que escriben de verdad (``refresh_board`` guarda la
    # foto, el motor de precios hace upsert de snapshots, el kill switch deja
    # su marcador). Sin este desvío escribían en ``.cache/`` del usuario: la
    # foto del panel se sobrescribía con el tablero de juguete de una prueba
    # (``market: {}``, ``dashboard_at`` del fixture) y el registro de red se
    # llenaba de 429/503 simulados a 0 ms. El panel se quedaba sin once y
    # parecía servir «datos de ayer».
    if not os.environ.get("FANTASY_CACHE_DIR", "").strip():
        _SESSION_CACHE = Path(tempfile.mkdtemp(prefix="fantasy-suite-cache-"))
        os.environ["FANTASY_CACHE_DIR"] = str(_SESSION_CACHE)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _SESSION_CACHE is None:
        return
    os.environ.pop("FANTASY_CACHE_DIR", None)
    shutil.rmtree(_SESSION_CACHE, ignore_errors=True)


def _is_loopback(address: object) -> bool:
    host: object = address
    if isinstance(address, tuple) and address:
        host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    return isinstance(host, str) and host.lower() in _LOOPBACK_HOSTS


@pytest.fixture(autouse=True)
def _no_real_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prohíbe abrir sockets fuera del loopback durante toda la prueba.

    Es el cerrojo que hace imposible el «spam accidental»: si un camino de
    código olvida el air-gap, la prueba falla aquí en milisegundos en vez de
    mandar una petición real y quedarse esperando un timeout.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    def guard_connect(self: socket.socket, address: object) -> None:
        if _is_loopback(address):
            return real_connect(self, address)
        raise AssertionError(
            f"La suite no puede abrir un socket real a {address!r}. "
            "Usa httpx.MockTransport o un cliente inyectado; el air-gap de "
            "LALIGA_ENV=development solo cubre LaLiga."
        )

    def guard_connect_ex(self: socket.socket, address: object) -> int:
        if _is_loopback(address):
            return real_connect_ex(self, address)
        raise AssertionError(f"La suite no puede abrir un socket real a {address!r}.")

    def guard_create(address: object, *args: object, **kwargs: object) -> socket.socket:
        if _is_loopback(address):
            return real_create(address, *args, **kwargs)
        raise AssertionError(f"La suite no puede abrir un socket real a {address!r}.")

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guard_create)


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> None:
    """Cada prueba arranca con la cola de huecos por dominio vacía.

    Sin esto, un hueco reservado por una prueba se arrastraría a la siguiente
    y el espaciado dependería del orden de ejecución. El ``HUMAN_PACER`` se
    reinicia por el mismo motivo: su contador decide cuándo toca la pausa de
    actividad de 45–90 s y, compartido entre pruebas, una espera cambiaría de
    rango según lo que hubiera corrido antes.
    """
    net.reset_rate_limits()
    net.reset_human_pacer()
    yield
    net.reset_rate_limits()
    net.reset_human_pacer()


@pytest.fixture(autouse=True)
def _fresh_kill_switch() -> None:
    """El kill switch es de proceso, no de prueba.

    Una prueba que verifica el 429/401 lo dispara a propósito y, sin este
    reset, el marcador quedaría vivo y todas las pruebas siguientes de red
    fallarían por un estado que no provocaron.
    """
    net.reset_kill_switch()
    yield
    net.reset_kill_switch()


@pytest.fixture(autouse=True)
def _fresh_human_pacer() -> None:
    """El contador de cadencia humana también es de proceso.

    ``HUMAN_PACER`` cuenta peticiones servidas y cada 3–4 dispara una pausa de
    actividad de 45–90 s. Sin reiniciarlo, el contador se arrastra entre
    pruebas y una que espera un jitter de 12–25 s recibe la pausa de actividad
    acumulada de todas las anteriores (87 s en la suite completa).
    """
    net.reset_human_pacer()
    yield
    net.reset_human_pacer()

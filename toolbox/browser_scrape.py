"""Renderizado con navegador para fuentes que bloquean httpx (Cloudflare, etc.).

Activo solo con ``FANTASY_SCRAPER_BROWSER=1`` y Playwright instalado.
Cada navegación se apunta en el medidor de llamadas como una petición más.
En modo avión (``FANTASY_OFFLINE=1``) no se abre el navegador: devuelve ``None``
y el scraper se queda con lo que haya en caché.
"""

from __future__ import annotations

import json
import logging
import threading
import os
import urllib.parse
from typing import Any

from toolbox import api_meter
from toolbox.net import REQUIRED_HEADERS, offline_mode


# Un solo Chromium a la vez: cada uno pesa 300-500 MB y varias peticiones
# simultáneas (refresco + web) acumulaban procesos hasta pasar el límite de Render.
logger = logging.getLogger(__name__)
_BROWSER_LOCK = threading.Lock()
_CHROMIUM_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--no-zygote", "--disable-extensions"]


def browser_scrape_enabled() -> bool:
    return os.getenv("FANTASY_SCRAPER_BROWSER", "").strip() == "1"


# Chromium suma 300-500 MB sobre el proceso de uvicorn (~200-280 MB medidos). Con
# menos hueco que esto no se abre: en el plan gratuito de Render (512 MB) un solo
# navegador mata el servicio por límite de memoria y el panel se reinicia.
_MIN_HEADROOM_BYTES = 900 * 1024 * 1024
_CGROUP_PAIRS = (
    ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),  # cgroup v2
    ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),  # v1
)
_warned_low_memory = False


def memory_headroom_bytes() -> int | None:
    """Memoria libre hasta el límite del contenedor, o ``None`` si no hay límite legible."""
    for limit_path, usage_path in _CGROUP_PAIRS:
        try:
            with open(limit_path, encoding="utf-8") as handle:
                raw_limit = handle.read().strip()
            with open(usage_path, encoding="utf-8") as handle:
                usage = int(handle.read().strip())
        except (OSError, ValueError):
            continue
        if not raw_limit.isdigit():
            return None  # «max»: sin límite
        limit = int(raw_limit)
        if limit >= 1 << 60:  # v1 sin límite devuelve un número enorme
            return None
        return limit - usage
    return None


def _enough_memory_for_browser() -> bool:
    global _warned_low_memory
    headroom = memory_headroom_bytes()
    if headroom is None or headroom >= _MIN_HEADROOM_BYTES:
        return True
    if not _warned_low_memory:
        _warned_low_memory = True
        logger.warning(
            "Chromium omitido: solo quedan %d MB hasta el límite de memoria (hacen falta %d MB).",
            headroom // (1024 * 1024),
            _MIN_HEADROOM_BYTES // (1024 * 1024),
        )
    return False


def _browser_allowed() -> bool:
    """El navegador es otra salida a la red: el modo avión también lo corta."""
    return browser_scrape_enabled() and not offline_mode() and _enough_memory_for_browser()


def _sofascore_headers(url: str) -> dict[str, str]:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "sofascore.com" not in host:
        return {}
    return {
        "Referer": "https://www.sofascore.com/",
        "Origin": "https://www.sofascore.com",
        "Accept": "application/json, text/plain, */*",
    }


def render_with_browser(url: str) -> str | None:
    if not _browser_allowed():
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with _BROWSER_LOCK, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
            try:
                page = browser.new_page()
                with api_meter.call(url=url, via="browser") as probe:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    probe.status = response.status if response is not None else None
                return page.content()
            finally:
                browser.close()
    except Exception:
        return None


def fetch_json_with_browser(url: str) -> tuple[Any | None, str | None]:
    """GET JSON vía Chromium (p. ej. API Sofascore con 403 en httpx)."""
    if not _browser_allowed():
        return None, None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, None
    extra = _sofascore_headers(url)
    headers = {
        "User-Agent": REQUIRED_HEADERS["User-Agent"],
        "Accept-Language": "es-ES,es;q=0.9",
        **extra,
    }
    try:
        with _BROWSER_LOCK, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
            try:
                context = browser.new_context(extra_http_headers=headers)
                with api_meter.call(url=url, via="browser") as probe:
                    response = context.request.get(url, timeout=20000)
                    probe.status = response.status
                if response.status >= 400:
                    return None, None
                body = response.text()
            finally:
                browser.close()
    except Exception:
        return None, None
    try:
        return json.loads(body), body
    except json.JSONDecodeError:
        return None, None

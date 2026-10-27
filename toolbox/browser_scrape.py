"""Renderizado con navegador para fuentes que bloquean httpx (Cloudflare, etc.).

Activo solo con ``FANTASY_SCRAPER_BROWSER=1`` y Playwright instalado.
Cada navegación se apunta en el medidor de llamadas como una petición más.
En modo avión (``FANTASY_OFFLINE=1``) no se abre el navegador: devuelve ``None``
y el scraper se queda con lo que haya en caché.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any

from toolbox import api_meter
from toolbox.net import REQUIRED_HEADERS, offline_mode


def browser_scrape_enabled() -> bool:
    return os.getenv("FANTASY_SCRAPER_BROWSER", "").strip() == "1"


def _browser_allowed() -> bool:
    """El navegador es otra salida a la red: el modo avión también lo corta."""
    return browser_scrape_enabled() and not offline_mode()


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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
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

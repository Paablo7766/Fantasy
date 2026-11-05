"""Descarga desde tu PC las fuentes que bloquean a Render y las deja en Supabase.

Render recibe 403 de analiticafantasy, FBref, Sofascore y Jornada Perfecta
(Cloudflare bloquea las IPs de centros de datos). Desde una conexión de casa sí
responden. Este script las descarga aquí y guarda el cuerpo en la caché de
Supabase (tabla ``scraper_cache``); cuando Render recibe un 403 sirve esa copia.

Solo toca esas fuentes externas: **no usa LaLiga ni sus tokens**, así que no puede
invalidar los de Render.

Uso (desde la carpeta del proyecto):

    python scripts/calentar_fuentes.py

Necesita en ``.env`` (o en el entorno) ``SUPABASE_URL`` y ``SUPABASE_KEY``, los
mismos valores que tiene Render. Sin ellos la copia se quedaría en tu PC y no
serviría de nada, y el script lo dice y se detiene.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _fail(message: str) -> int:
    print(f"\n✗ {message}\n")
    return 1


def main() -> int:
    if not (os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_KEY", "").strip()):
        return _fail(
            "Faltan SUPABASE_URL y SUPABASE_KEY. Cópialos de Render (Environment) a un archivo .env "
            "en esta carpeta. Sin ellos la copia se queda en tu PC y Render no la ve."
        )
    if os.getenv("FANTASY_CACHE_DIR", "").strip():
        return _fail("FANTASY_CACHE_DIR está definido: eso desactiva Supabase. Quítalo del entorno o del .env.")
    if os.getenv("FANTASY_OFFLINE", "").strip():
        return _fail("FANTASY_OFFLINE está activo: no puede descargar. Quítalo del entorno o del .env.")

    # Solo fuentes externas: se abre la puerta de red para ellas, nunca se pide nada a LaLiga.
    os.environ["LALIGA_ENV"] = "production"
    os.environ.setdefault("FANTASY_SCRAPER_BROWSER", "1")

    from toolbox.analitica_fantasy import load_analitica_fantasy
    from toolbox.net import ExternalClient
    from toolbox.scrapers import ScrapeTTL, warm_optional_form_sources

    ttl = ScrapeTTL.from_env()
    client = ExternalClient()
    results: list[tuple[str, bool, str]] = []
    try:
        print("Descargando analiticafantasy…")
        bundle = load_analitica_fantasy(client, ttl=ttl.stats, fresh=True)
        for name, status in sorted(bundle.sources.items()):
            results.append((f"analiticafantasy · {name}", bool(status.get("ok")), str(status.get("error") or "")))
        print("Descargando FBref y Sofascore…")
        warm = warm_optional_form_sources(client, fresh=True, ttl=ttl)
        for name in ("fbref", "sofascore"):
            status = warm.get(name) or {}
            results.append((name, bool(status.get("ok")), str(status.get("error") or "")))
    finally:
        client.close()

    print()
    for name, ok, error in results:
        print(f"  {'✓' if ok else '✗'} {name}" + (f"  ({error})" if error and not ok else ""))
    good = sum(1 for _name, ok, _error in results if ok)
    print(f"\n{good} de {len(results)} fuentes guardadas en Supabase.")
    if good == 0:
        return _fail("Ninguna fuente respondió. Prueba con otra red (datos del móvil) o más tarde.")
    print("Ya puedes pulsar la gota en la app: Render usará estas copias cuando le den 403.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

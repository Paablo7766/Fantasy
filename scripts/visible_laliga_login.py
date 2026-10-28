#!/usr/bin/env python3
"""Login visible de LALIGA Fantasy: ventana Chromium, Google manual, tokens en ``.env``.

Uso::

    python scripts/visible_laliga_login.py

No hace falta F12: inicia sesión en la ventana que se abre; al detectar
``authredirect://`` canjea el código, cierra el navegador y guarda
``LALIGA_ACCESS_TOKEN``, ``LALIGA_REFRESH_TOKEN`` y ``LEAGUE_ID`` si aplica.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.auth import AuthError, login_with_browser  # noqa: E402


def main() -> int:
    print("Se abrirá Chromium. Inicia sesión con Google y elige tu cuenta.", flush=True)
    print("Cuando termine, los tokens quedarán en .env (no se imprimen).", flush=True)
    try:
        result = login_with_browser(headless=False)
    except AuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    safe = {
        "ok": result.get("ok"),
        "persisted_to": result.get("persisted_to"),
        "access_token_expires_at": result.get("access_token_expires_at"),
        "refresh_token_present": result.get("refresh_token_present"),
        "league_id": result.get("league_id"),
        "league_name": result.get("league_name"),
        "league_saved": result.get("league_saved"),
    }
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

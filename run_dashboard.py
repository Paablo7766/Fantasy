"""Arranca el tablero local de LALIGA Fantasy.

Desde la raíz del proyecto:

    python run_dashboard.py

El mismo servidor, con recarga al guardar:

    uvicorn server:app --reload --port 8000

Abre http://127.0.0.1:8000
Una liga concreta: http://127.0.0.1:8000/?league=ID
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import uvicorn

    sys.stdout.write("Tablero local: http://127.0.0.1:8000\n")
    sys.stdout.write("Comando equivalente: uvicorn server:app --reload --port 8000\n")
    sys.stdout.flush()
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(ROOT)],
        reload_excludes=[".venv/*", ".git/*"],
    )


if __name__ == "__main__":
    main()

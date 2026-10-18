"""Caja de herramientas determinista de LALIGA Fantasy.

La salida hacia el modelo de lenguaje sale solo por ``cli.py`` en JSON.
Este paquete no imprime.
"""

from pathlib import Path

__version__ = "0.1.0"


def project_root() -> Path:
    """Directorio del proyecto, padre del paquete ``toolbox``."""
    return Path(__file__).resolve().parent.parent

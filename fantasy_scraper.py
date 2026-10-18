"""Acceso corto al scraper de alineaciones.

La implementación vive en ``toolbox.fantasy_scraper``: caché, umbral de
nombres y el cruce que alimenta ``trends``.
"""

from toolbox.fantasy_scraper import (
    FantasyScraper,
    enrich_player_list,
    normalize_name,
)

__all__ = ["FantasyScraper", "enrich_player_list", "normalize_name"]

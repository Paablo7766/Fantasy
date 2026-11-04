"""Construye el mapa ``player_id`` de Fantasy → foto de pecho oficial de LaLiga.

Las fotos de Fantasy (assets-fantasy) son solo cara y cuello. La web oficial de
LaLiga sirve otra foto del mismo jugador, de pecho y con la camiseta del club,
pero con otro id de jugador. Este script lo empareja visitando la ficha pública
de cada jugador (``laliga.com/en-GB/player/<slug>``), sin usar la API interna.

Reglas de seguridad del emparejamiento:
  * El club debe coincidir (los ids de club ``tNNN`` son los mismos en ambas webs).
  * La ficha debe traer la foto de pecho de ese mismo club (LaLiga titula la ficha
    con el nombre legal, así que no se compara el título).
Lo que no cumple se deja fuera: la app mantiene su foto de cara.

Uso (desde la raíz del repo)::

    python scripts/build_bust_photos.py            # solo jugadores nuevos
    python scripts/build_bust_photos.py --retry    # reintenta también los fallidos

Salida: ``frontend/lib/data/bust-photos.json`` → ``{"2426": "t186/p60772"}``.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "lib" / "data" / "bust-photos.json"
MISSES = ROOT / ".cache" / "bust_photos_misses.json"
PAGE = "https://www.laliga.com/en-GB/player/{slug}"
PHOTO = re.compile(r"squad/2026/(t\d+)/(p\d+)/\d+x\d+/p\d+_t\d+_2026_1_001_000\.png")
PAUSE = 1.0
SITEMAP = "https://assets.laliga.com/sitemap/sitemap-players.xml"
SLUGS = ROOT / ".cache" / "laliga_player_slugs.txt"
WORKERS = 4
# Clubes de LaLiga 2026/27 (mismos ids en Fantasy y en laliga.com).
LALIGA_TEAMS = {
    "t173", "t174", "t175", "t176", "t177", "t178", "t179", "t180", "t182", "t184",
    "t185", "t186", "t188", "t189", "t191", "t449", "t450", "t855", "t954", "t1450",
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slugify(text: str) -> str:
    return fold(text).replace(" ", "-")


def collect_players() -> dict[str, dict[str, str]]:
    """Todos los jugadores con foto de Fantasy que haya en la caché local."""
    rows: dict[str, dict[str, str]] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            image = node.get("image_url") or node.get("image")
            match = re.search(r"/(t\d+)/p(\d+)/", image) if isinstance(image, str) else None
            name = node.get("name") or node.get("nickname")
            if match and name:
                rows[match.group(2)] = {
                    "name": str(name),
                    "nickname": str(node.get("nickname") or ""),
                    "team": match.group(1),
                }
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    # Catálogo completo de la competición, solo lectura de disco (air-gap): no abre red.
    try:
        sys.path.insert(0, str(ROOT))
        from toolbox.net import LaligaClient

        with LaligaClient() as client:
            walk(client.players_document(fresh=False))
    except Exception as error:  # sin catálogo se sigue con la caché del tablero
        print(f"Aviso: catálogo no disponible ({error}); solo caché del tablero")

    patterns = [".cache/dashboard/*/*.json", ".cache/bodies/*", ".cache/scraper_bodies/*"]
    for pattern in patterns:
        for path in glob.glob(str(ROOT / pattern)):
            try:
                walk(json.loads(Path(path).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return rows


def load_slugs() -> dict[str, set[str]]:
    """Slugs reales de laliga.com (sitemap público de jugadores) → índice por palabra."""
    if not SLUGS.exists():
        request = lambda url: urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: E731
        with urllib.request.urlopen(request(SITEMAP), timeout=30) as response:
            parts = re.findall(r"<loc>([^<]+)</loc>", response.read().decode("utf-8", "ignore"))
        found: set[str] = set()
        for part in parts:
            time.sleep(1)
            with urllib.request.urlopen(request(part), timeout=60) as response:
                text = response.read().decode("utf-8", "ignore")
            found.update(re.findall(r"/en-[A-Z]{2}/player/([a-z0-9-]+)", text))
        SLUGS.parent.mkdir(parents=True, exist_ok=True)
        SLUGS.write_text(chr(10).join(sorted(found)), encoding="utf-8")
    index: dict[str, set[str]] = {}
    for slug in SLUGS.read_text(encoding="utf-8").split():
        for token in slug.split("-"):
            index.setdefault(token, set()).add(slug)
    return index


def candidate_slugs(player: dict[str, str], index: dict[str, set[str]]) -> list[str]:
    """Slugs que existen en laliga.com y contienen palabras del jugador, mejores primero."""
    tokens = [t for t in dict.fromkeys(fold(f"{player['nickname']} {player['name']}").split()) if len(t) >= 3]
    exact = slugify(player["nickname"])
    scored: dict[str, int] = {}
    for token in tokens:
        for slug in index.get(token, ()):
            scored[slug] = scored.get(slug, 0) + 1
    ranked = sorted(scored, key=lambda slug: (slug != exact, -scored[slug], len(slug)))
    return ranked[:6]


def fetch(slug: str) -> str | None:
    request = urllib.request.Request(PAGE.format(slug=slug), headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            time.sleep(5 * (attempt + 1))  # 429 / 5xx: esperar y reintentar
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(5 * (attempt + 1))
    return None


def resolve(player: dict[str, str], index: dict[str, set[str]]) -> tuple[str, str] | None:
    for slug in candidate_slugs(player, index):
        html = fetch(slug)
        time.sleep(PAUSE)
        if not html:
            continue
        for team, pid in dict.fromkeys(PHOTO.findall(html)):
            if team == player["team"]:
                return team, pid
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry", action="store_true", help="reintenta los que fallaron antes")
    args = parser.parse_args()

    mapping: dict[str, str] = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    misses: dict[str, str] = json.loads(MISSES.read_text(encoding="utf-8")) if MISSES.exists() else {}
    players = collect_players()
    players = {pid: row for pid, row in players.items() if row["team"] in LALIGA_TEAMS}
    todo = [pid for pid in players if pid not in mapping and (args.retry or pid not in misses)]
    print(f"{len(players)} jugadores · {len(mapping)} ya mapeados · {len(todo)} por resolver")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    MISSES.parent.mkdir(parents=True, exist_ok=True)
    slug_index = load_slugs()

    def work(pid: str) -> tuple[str, tuple[str, str] | None]:
        return pid, resolve(players[pid], slug_index)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for index, (pid, found) in enumerate(pool.map(work, todo), 1):
            if found:
                mapping[pid] = f"{found[0]}/{found[1]}"
                misses.pop(pid, None)
            else:
                misses[pid] = players[pid]["name"]
            if index % 10 == 0 or index == len(todo):
                OUT.write_text(json.dumps(dict(sorted(mapping.items())), indent=0), encoding="utf-8")
                MISSES.write_text(json.dumps(misses, ensure_ascii=False, indent=0), encoding="utf-8")
                print(f"  {index}/{len(todo)} · ok {len(mapping)} · sin foto {len(misses)}", flush=True)

    print(f"Listo: {len(mapping)} con foto de pecho. Sin emparejar: {sorted(misses.values())}")


if __name__ == "__main__":
    main()

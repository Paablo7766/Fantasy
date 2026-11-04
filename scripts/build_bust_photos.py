"""Construye el mapa ``player_id`` de Fantasy → foto de pecho oficial de LaLiga.

Las fotos de Fantasy (assets-fantasy) son solo cara y cuello. La web oficial de
LaLiga sirve otra foto del mismo jugador, de pecho y con la camiseta del club,
pero con otro id de jugador. Este script lo empareja visitando la ficha pública
de cada jugador (``laliga.com/en-GB/player/<slug>``), sin usar la API interna.

Reglas de seguridad del emparejamiento:
  * El club debe coincidir (los ids de club ``tNNN`` son los mismos en ambas webs).
  * El título de la ficha debe compartir algún apellido o nombre con el jugador.
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
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "lib" / "data" / "bust-photos.json"
MISSES = ROOT / ".cache" / "bust_photos_misses.json"
PAGE = "https://www.laliga.com/en-GB/player/{slug}"
PHOTO = re.compile(r"squad/2026/(t\d+)/(p\d+)/256x278/p\d+_t\d+_2026_1_001_000\.png")
PAUSE = 1.0


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

    patterns = [".cache/dashboard/*/*.json", ".cache/bodies/*", ".cache/scraper_bodies/*"]
    for pattern in patterns:
        for path in glob.glob(str(ROOT / pattern)):
            try:
                walk(json.loads(Path(path).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return rows


def candidate_slugs(player: dict[str, str]) -> list[str]:
    seen: list[str] = []

    def add(value: str) -> None:
        slug = slugify(value)
        if slug and slug not in seen:
            seen.append(slug)

    nick, name = player["nickname"], player["name"]
    tokens = fold(name).split()
    add(nick)
    add(name)
    nick_tokens = fold(nick).split()
    if len(tokens) >= 2:
        add(f"{tokens[0]} {tokens[-1]}")
        add(f"{tokens[0]} {tokens[1]}")
        add(f"{tokens[-2]} {tokens[-1]}")
    for token in nick_tokens[::-1] + tokens[::-1] + tokens:
        if len(token) >= 3:
            add(token)
    base = list(seen)
    for slug in base:
        seen.append(f"{slug}-1")
    return seen[:24]


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


def title_of(html: str) -> str:
    found = re.search(r"<title>(.*?)</title>", html, re.S)
    return fold(found.group(1)) if found else ""


def resolve(player: dict[str, str]) -> tuple[str, str] | None:
    wanted = {token for token in fold(f"{player['name']} {player['nickname']}").split() if len(token) >= 4}
    for slug in candidate_slugs(player):
        html = fetch(slug)
        time.sleep(PAUSE)
        if not html:
            continue
        title = title_of(html)
        if wanted and not any(token in title.split() for token in wanted):
            continue
        for team, pid in PHOTO.findall(html):
            if team == player["team"]:
                return team, pid
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry", action="store_true", help="reintenta los que fallaron antes")
    args = parser.parse_args()

    mapping: dict[str, str] = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    misses: dict[str, str] = json.loads(MISSES.read_text(encoding="utf-8")) if MISSES.exists() else {}
    players = collect_players()
    todo = [pid for pid in players if pid not in mapping and (args.retry or pid not in misses)]
    print(f"{len(players)} jugadores · {len(mapping)} ya mapeados · {len(todo)} por resolver")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    MISSES.parent.mkdir(parents=True, exist_ok=True)
    for index, pid in enumerate(todo, 1):
        player = players[pid]
        found = resolve(player)
        if found:
            mapping[pid] = f"{found[0]}/{found[1]}"
            misses.pop(pid, None)
        else:
            misses[pid] = player["name"]
        if index % 10 == 0 or index == len(todo):
            OUT.write_text(json.dumps(dict(sorted(mapping.items())), indent=0), encoding="utf-8")
            MISSES.write_text(json.dumps(misses, ensure_ascii=False, indent=0), encoding="utf-8")
            print(f"  {index}/{len(todo)} · ok {len(mapping)} · sin foto {len(misses)}", flush=True)

    print(f"Listo: {len(mapping)} con foto de pecho. Sin emparejar: {sorted(misses.values())}")


if __name__ == "__main__":
    main()

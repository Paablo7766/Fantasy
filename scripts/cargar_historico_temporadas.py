"""Descarga el histórico de temporadas pasadas de las plantillas de LaLiga.

    python scripts/cargar_historico_temporadas.py            # todo lo que falte
    python scripts/cargar_historico_temporadas.py --equipos barcelona real-madrid
    python scripts/cargar_historico_temporadas.py --limite 20

Reanuda donde se quedó: lo ya guardado en ``.cache/historico_temporadas.json``
no se vuelve a pedir. Una petición cada ``--pausa`` segundos. Cada ficha pesa
~2 MB, pero solo se guarda el resumen por jornada (unos KB por jugador).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.season_history import (  # noqa: E402
    TEMPORADAS,
    _limpia,
    leer_almacen,
    parse_plantilla,
    parse_temporada,
    ruta_almacen,
    temporada_coherente,
)

BASE = "https://www.futbolfantasy.com"
UA = "Mozilla/5.0 (compatible; fantasy-historico/1.0)"
EQUIPOS = [
    "alaves", "athletic", "atletico", "barcelona", "betis", "celta", "deportivo", "elche", "espanyol",
    "getafe", "levante", "malaga", "osasuna", "racing", "rayo-vallecano", "real-madrid", "real-sociedad",
    "sevilla", "valencia", "villarreal",
]
POSICIONES = {"Portero": "PT", "Defensa": "DF", "Centrocampista": "MC", "Delantero": "DL"}


def bajar(url: str) -> str | None:
    pedido = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    for intento in range(3):
        try:
            with urllib.request.urlopen(pedido, timeout=45) as respuesta:
                return respuesta.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            time.sleep(5 * (intento + 1))
        except OSError:
            time.sleep(5 * (intento + 1))
    return None


def ficha(page: str) -> dict[str, str | None]:
    titulo = re.search(r"<title>\s*([^<]+?)\s+-\s+Perfil Fantasy", page)
    cabecera = _limpia(page[:250_000])
    posicion = re.search(r"Posici[oó]n\s+(Portero|Defensa|Centrocampista|Delantero)", cabecera)
    return {
        "nombre": titulo.group(1).strip() if titulo else None,
        "posicion": POSICIONES.get(posicion.group(1)) if posicion else None,
    }


def guardar(ruta: Path, almacen: dict[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(almacen, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporal.replace(ruta)


def descargar_jugador(slug: str, equipo: str, previo: dict[str, Any], pausa: float) -> dict[str, Any]:
    """Temporadas que falten de un jugador. Devuelve su entrada completa."""
    entrada = {"equipo": equipo, "temporadas": dict(previo.get("temporadas", {}))}
    entrada.update({k: v for k, v in previo.items() if k in {"nombre", "posicion"}})
    for temporada in TEMPORADAS:
        if temporada in entrada["temporadas"]:
            continue
        time.sleep(pausa)
        pagina = bajar(f"{BASE}/jugadores/{slug}/{temporada}")
        if pagina is None:
            continue
        datos = parse_temporada(pagina)
        datos["coherente"] = temporada_coherente(datos, temporada)
        if not datos["coherente"]:
            datos = {"filas": [], "total_web": datos.get("total_web"), "coherente": False}
        entrada["temporadas"][temporada] = datos
        if not entrada.get("nombre"):
            entrada.update({k: v for k, v in ficha(pagina).items() if v})
    return entrada


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--equipos", nargs="*", default=EQUIPOS)
    parser.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones de un mismo hilo")
    parser.add_argument("--hilos", type=int, default=3)
    parser.add_argument("--limite", type=int, default=0, help="máximo de jugadores nuevos (0 = todos)")
    args = parser.parse_args()

    ruta = ruta_almacen()
    almacen = leer_almacen()
    pendientes: list[tuple[str, str]] = []
    for equipo in args.equipos:
        pagina = bajar(f"{BASE}/laliga/equipos/{equipo}")
        if not pagina:
            print(f"[{equipo}] sin página de equipo", flush=True)
            continue
        slugs = parse_plantilla(pagina)
        faltan = [s for s in slugs if not all(t in almacen.get(s, {}).get("temporadas", {}) for t in TEMPORADAS)]
        print(f"[{equipo}] {len(slugs)} jugadores, {len(faltan)} por bajar", flush=True)
        pendientes.extend((s, equipo) for s in faltan)
        time.sleep(args.pausa)
    if args.limite:
        pendientes = pendientes[: args.limite]

    bloqueo = threading.Lock()
    hechos = 0
    with ThreadPoolExecutor(max_workers=args.hilos) as pool:
        futuros = {pool.submit(descargar_jugador, s, e, almacen.get(s, {}), args.pausa): s for s, e in pendientes}
        for futuro in as_completed(futuros):
            slug = futuros[futuro]
            try:
                entrada = futuro.result()
            except Exception as exc:  # noqa: BLE001 - un jugador roto no para la carga
                print(f"  {slug}: {exc}", flush=True)
                continue
            with bloqueo:
                almacen[slug] = entrada
                hechos += 1
                if hechos % 10 == 0:
                    guardar(ruta, almacen)
                    print(f"  {hechos}/{len(pendientes)} (almacén {len(almacen)})", flush=True)
    guardar(ruta, almacen)
    print(f"Listo: {len(almacen)} jugadores en {ruta}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

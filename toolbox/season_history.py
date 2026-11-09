"""Histórico de temporadas pasadas por jugador (fichas de FútbolFantasy).

Cada ficha ``/jugadores/<slug>/laliga-24-25`` trae las 38 jornadas de esa
temporada con los puntos oficiales de LaLiga Fantasy, los cambios (entrada y
salida) y, en el desglose, los goles y asistencias. Este módulo solo **lee y
resume**: la descarga vive en ``scripts/cargar_historico_temporadas.py`` y deja
un JSON en ``.cache/historico_temporadas.json``. En ejecución no sale a la red.

El resumen por jugador (``resumen_historico``) es lo que usa xP 2.0 como punto
de partida cuando este año hay pocas jornadas: en vez de la media del puesto,
la media del propio jugador, encogida hacia el puesto según los partidos que
lo respaldan.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import Any

ALMACEN_HISTORICO = "historico_temporadas.json"
TEMPORADAS = ("laliga-25-26", "laliga-24-25")

_FILA = re.compile(r'(?=<tr class="plegado)')
_JORNADA = re.compile(r'jorn-td">(\d+)')
_MARCADOR = re.compile(r'class="score[^"]*">\s*(\d+-\d+)')
_EQUIPOS = re.compile(r'<span class="d-none d-md-inline-block">\s*([A-Z]{2,4})\s*</span>')
_PUNTOS_LF = re.compile(r'columna_puntos[^"]*laliga-fantasy[^"]*"[^>]*>\s*(-?\d+)\s*<')
_CAMBIO = re.compile(r'title="(Entrada|Salida)"[^>]*>\s*(\d+)\'')
_BLOQUE_FANTASY = re.compile(r'<div class="desg fantasy">(.*?)(?=<div class="desg |</td>)', re.S)
_BLOQUE_OFICIAL = re.compile(r'<div class="desg laliga-fantasy">(.*?)(?=<div class="desg |</td>)', re.S)
# «2 Goles 14 p»: pegado a sus puntos, para no leer «Goles encajados» ni «Asistencias sin gol».
_ESTADISTICA = re.compile(r"(\d+)\s+(Goles|Asistencias)\s+-?\d+(?:\.\d+)?\s*p\b")
_PUNTOS_ESTAD = re.compile(r"Puntos estad[^<]*?(-?\d+)\s*p")
_PUNTOS_RELEVO = re.compile(r"Puntos Relevo[^<]*?(-?\d+)\s*p")
_TITULO_TEMPORADA = re.compile(r"<title>[^<]*?LaLiga\s+(\d{4})/(\d{2})")
_TOTAL = re.compile(r"Total de puntos</strong>.*?(\d+)", re.S)
_ESTADOS = ("Lesionado", "Convocado, no jugó", "Sancionado", "No convocado")


def _limpia(texto: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", texto))).strip()


def _minutos(main: str) -> float | None:
    """Minutos estimados: de la entrada (o 0) a la salida (o 90)."""
    cambios = _CAMBIO.findall(main)
    entrada = 0
    salida = 90
    for tipo, minuto in cambios:
        if tipo == "Entrada":
            entrada = int(minuto)
        else:
            salida = int(minuto)
    return float(max(0, min(90, salida) - entrada))


def parse_temporada(page: str) -> dict[str, Any]:
    """Filas de una temporada. Una fila sin ``puntos`` es un partido sin jugar."""
    filas: list[dict[str, Any]] = []
    for trozo in _FILA.split(page)[1:]:
        main, _, resto = trozo.partition('<tr class="desglose"')
        jornada = _JORNADA.search(main)
        if not jornada:
            continue
        puntos = _PUNTOS_LF.search(main)
        texto = _limpia(main)
        estado = next((e for e in _ESTADOS if e in texto), None)
        desglose = resto.split("</tr>")[0]
        goles = 0
        asistencias = 0
        bloque = _BLOQUE_FANTASY.search(desglose)
        if bloque:
            for cantidad, nombre in _ESTADISTICA.findall(_limpia(bloque.group(1))):
                if nombre == "Goles":
                    goles += int(cantidad)
                else:
                    asistencias += int(cantidad)
        oficial = _BLOQUE_OFICIAL.search(desglose)
        texto_oficial = _limpia(oficial.group(1)) if oficial else ""
        estad = _PUNTOS_ESTAD.search(texto_oficial)
        relevo = _PUNTOS_RELEVO.search(texto_oficial)
        jugo = puntos is not None
        filas.append(
            {
                "j": int(jornada.group(1)),
                "equipos": _EQUIPOS.findall(main)[:2],
                "marcador": (_MARCADOR.search(main) or [None, None])[1],
                "puntos": int(puntos.group(1)) if puntos else None,
                "minutos": _minutos(main) if jugo else 0.0,
                "estado": estado,
                "goles": goles,
                "asistencias": asistencias,
                "estadisticos": int(estad.group(1)) if estad else None,
                "relevo": int(relevo.group(1)) if relevo else None,
            }
        )
    total = _TOTAL.search(page)
    titulo = _TITULO_TEMPORADA.search(page)
    filas.sort(key=lambda f: f["j"])
    return {
        "total_web": int(total.group(1)) if total else None,
        "temporada_pagina": f"laliga-{titulo.group(1)[2:]}-{titulo.group(2)}" if titulo else None,
        "filas": filas,
    }


#: Una temporada de verdad tiene casi todas las jornadas (38). La web, cuando el
#: jugador no estuvo en LaLiga ese año, devuelve la temporada en curso (12 filas).
MIN_FILAS_TEMPORADA = 15


def temporada_coherente(temporada: dict[str, Any], esperada: str | None = None) -> bool:
    """La temporada es la pedida, está completa y su suma cuadra con el total de la web.

    Sin esto, un jugador sin LaLiga previa se llevaría los datos de este año como
    si fueran del pasado (la web redirige a la temporada en curso).
    """
    filas = temporada.get("filas") or []
    total = temporada.get("total_web")
    if len(filas) < MIN_FILAS_TEMPORADA or total is None:
        return False
    pagina = temporada.get("temporada_pagina")
    if esperada and pagina and pagina != esperada:
        return False
    return sum(f["puntos"] for f in filas if f["puntos"] is not None) == total


def parse_plantilla(page: str) -> list[str]:
    """Slugs de jugadores de la página de un equipo, sin repetir y en orden."""
    vistos: dict[str, None] = {}
    for slug in re.findall(r'/jugadores/([a-z0-9-]+)', page):
        if slug != "ficha":
            vistos.setdefault(slug, None)
    return list(vistos)


# --- Almacén ---------------------------------------------------------------


def ruta_almacen(cache: Path | None = None) -> Path:
    if cache is None:
        from toolbox.cache import cache_root

        cache = cache_root()
    return cache / ALMACEN_HISTORICO


def leer_almacen(cache: Path | None = None) -> dict[str, Any]:
    ruta = ruta_almacen(cache)
    if not ruta.is_file():
        return {}
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return crudo if isinstance(crudo, dict) else {}


# --- Copia en Supabase ---------------------------------------------------------
# Render borra su disco en cada despliegue y `.cache/` no se sube a git: sin copia
# remota, producción no tendría el histórico. Se reutiliza la tabla
# `dashboard_snapshots` de ``toolbox.snapshot_remote`` (ver ``history_remote``).
KIND_REMOTO = "historico_temporadas"
KEY_REMOTA = "plantillas"
_CAMPOS_FILA = ("j", "puntos", "minutos", "goles", "asistencias")


def compactar(almacen: dict[str, Any]) -> dict[str, Any]:
    """Almacén reducido a lo que usa el modelo: solo temporadas válidas y cinco campos por jornada."""
    salida: dict[str, Any] = {}
    for slug, entrada in almacen.items():
        temporadas: dict[str, Any] = {}
        for nombre, temporada in (entrada.get("temporadas") or {}).items():
            if not temporada_coherente(temporada, nombre):
                continue
            temporadas[nombre] = {
                "total_web": temporada["total_web"],
                "temporada_pagina": temporada.get("temporada_pagina"),
                "filas": [{c: f.get(c) for c in _CAMPOS_FILA} for f in temporada["filas"]],
            }
        if temporadas:
            salida[slug] = {
                "nombre": entrada.get("nombre"),
                "posicion": entrada.get("posicion"),
                "equipo": entrada.get("equipo"),
                "temporadas": temporadas,
            }
    return salida


def subir_a_supabase(almacen: dict[str, Any]) -> bool:
    """Sube la copia compacta. ``False`` sin Supabase o si falla (nunca lanza)."""
    import time

    from toolbox import snapshot_remote

    if not snapshot_remote.enabled():
        return False
    return snapshot_remote.save(KIND_REMOTO, KEY_REMOTA, {"saved_unix": time.time(), "value": compactar(almacen)})


def traer_de_supabase(cache: Path | None = None) -> bool:
    """Si no hay fichero local, baja la copia remota y la guarda. Nunca lanza."""
    from toolbox import snapshot_remote

    if not snapshot_remote.enabled():
        return False
    try:
        sobre = snapshot_remote.load(KIND_REMOTO, KEY_REMOTA)
        valor = sobre.get("value") if sobre else None
        if not isinstance(valor, dict) or not valor:
            return False
        ruta = ruta_almacen(cache)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(valor, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporal.replace(ruta)
        return True
    except Exception:  # noqa: BLE001 — sin histórico el modelo usa el puesto
        return False


# --- Resumen por jugador ---------------------------------------------------

#: Minutos desde los que un partido cuenta como de titular.
MINUTOS_TITULAR = 45.0
PUNTOS_POR_GOL = {"PT": 6.0, "DF": 6.0, "MC": 5.0, "DL": 4.0}
PUNTOS_POR_ASISTENCIA = 3.0
#: Cuánto pesa el pasado de otra temporada frente a la actual: una jornada de
#: hace un año vale esto de una de este año.
PESO_TEMPORADA_PASADA = {"laliga-25-26": 1.0, "laliga-24-25": 0.6}


def resumen_historico(temporadas: dict[str, Any], slot: str) -> dict[str, Any] | None:
    """Tasas por partido de titular a partir de las temporadas pasadas.

    ``suelo`` es lo que queda de los puntos al quitar goles y asistencias (esos
    se contraen aparte). Devuelve ``None`` si no hay partidos de titular.
    """
    n_pesado = 0.0
    n_bruto = 0
    acum_suelo = 0.0
    acum_goles = 0.0
    acum_asist = 0.0
    n_banquillo = 0
    acum_banquillo = 0.0
    partidos_posibles = 0
    jugados = 0
    for nombre, temporada in (temporadas or {}).items():
        if not temporada_coherente(temporada, nombre):
            continue
        peso = PESO_TEMPORADA_PASADA.get(nombre, 0.5)
        for fila in temporada["filas"]:
            partidos_posibles += 1
            if fila["puntos"] is None:
                continue
            jugados += 1
            if fila["minutos"] < MINUTOS_TITULAR:
                n_banquillo += 1
                acum_banquillo += fila["puntos"]
                continue
            n_bruto += 1
            n_pesado += peso
            acum_suelo += peso * (
                fila["puntos"] - fila["goles"] * PUNTOS_POR_GOL[slot] - fila["asistencias"] * PUNTOS_POR_ASISTENCIA
            )
            acum_goles += peso * fila["goles"]
            acum_asist += peso * fila["asistencias"] * PUNTOS_POR_ASISTENCIA
    if n_bruto == 0 or n_pesado <= 0:
        return None
    return {
        "n_titular": n_bruto,
        "n_pesado": round(n_pesado, 2),
        "suelo": acum_suelo / n_pesado,
        "goles": acum_goles / n_pesado,
        "asistencia": acum_asist / n_pesado,
        "revulsivo": (acum_banquillo / n_banquillo) if n_banquillo else None,
        "n_revulsivo": n_banquillo,
        "participacion": jugados / partidos_posibles if partidos_posibles else None,
    }


#: Mínimo de partidos de titular para que un jugador cuente en la media de su puesto.
MIN_TITULAR_REFERENCIA = 10


def resumenes_del_almacen(almacen: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Resumen de cada jugador del almacén con su puesto (``posicion``)."""
    salida: dict[str, dict[str, Any]] = {}
    for slug, entrada in almacen.items():
        slot = entrada.get("posicion")
        if slot not in PUNTOS_POR_GOL:
            continue
        resumen = resumen_historico(entrada.get("temporadas") or {}, slot)
        if resumen:
            resumen["slot"] = slot
            salida[slug] = resumen
    return salida


def medias_por_puesto(resumenes: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Media de suelo, goles y asistencia por puesto, pesada por partidos de titular.

    Sirve de referencia: lo que importa de un jugador es su distancia a esta
    media medida con el mismo método, no su valor absoluto.
    """
    acum: dict[str, dict[str, float]] = {}
    for resumen in resumenes.values():
        if resumen["n_titular"] < MIN_TITULAR_REFERENCIA:
            continue
        a = acum.setdefault(resumen["slot"], {"w": 0.0, "suelo": 0.0, "goles": 0.0, "asistencia": 0.0})
        peso = resumen["n_pesado"]
        a["w"] += peso
        for clave in ("suelo", "goles", "asistencia"):
            a[clave] += peso * resumen[clave]
    return {
        slot: {clave: a[clave] / a["w"] for clave in ("suelo", "goles", "asistencia")}
        for slot, a in acum.items()
        if a["w"] > 0
    }


def hist_prior(resumen: dict[str, Any], medias: dict[str, dict[str, float]]) -> dict[str, float] | None:
    """Distancia del jugador a la media de su puesto, para ``xp2.prior_con_historico``."""
    referencia = medias.get(resumen.get("slot", ""))
    if not referencia:
        return None
    return {
        "n": float(resumen["n_pesado"]),
        "suelo": float(resumen["suelo"] - referencia["suelo"]),
        "goles": float(resumen["goles"] - referencia["goles"]),
        "asistencia": float(resumen["asistencia"] - referencia["asistencia"]),
    }


# --- Cruce con nuestros jugadores --------------------------------------------
UMBRAL_NOMBRE = 0.72


def indice_por_club(almacen: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """``club normalizado -> [(slug, nombre)]`` del almacén."""
    from toolbox.matching import normalize_club

    indice: dict[str, list[tuple[str, str]]] = {}
    for slug, entrada in almacen.items():
        nombre = entrada.get("nombre")
        if nombre:
            indice.setdefault(normalize_club(entrada.get("equipo")), []).append((slug, nombre))
    return indice


def emparejar(nombre: str | None, club: str | None, indice: dict[str, list[tuple[str, str]]]) -> str | None:
    """Slug del jugador del mismo club con el nombre más parecido (o ``None``).

    Exige un parecido claro y que el segundo mejor quede por debajo: ante la duda
    mejor sin histórico que con el de otro jugador.
    """
    from toolbox.matching import name_similarity, normalize_club

    candidatos = indice.get(normalize_club(club)) or []
    puntuados = sorted(((name_similarity(nombre, n), slug) for slug, n in candidatos), reverse=True)
    if not puntuados or puntuados[0][0] < UMBRAL_NOMBRE:
        return None
    if len(puntuados) > 1 and puntuados[1][0] >= puntuados[0][0] - 0.1:
        return None
    return puntuados[0][1]


# --- Búsqueda en ejecución (solo lee el JSON local) ----------------------------
_ESTADO: dict[str, Any] = {"marca": None, "resumenes": {}, "medias": {}, "indice": {}, "cruces": {}}


def _cargar_estado() -> None:
    ruta = ruta_almacen()
    if not ruta.is_file():
        traer_de_supabase()
    try:
        marca = (str(ruta), ruta.stat().st_mtime_ns)
    except OSError:
        marca = (str(ruta), None)
    if _ESTADO["marca"] == marca:
        return
    almacen = leer_almacen() if marca[1] is not None else {}
    resumenes = resumenes_del_almacen(almacen)
    _ESTADO.update(
        marca=marca,
        resumenes=resumenes,
        medias=medias_por_puesto(resumenes),
        indice=indice_por_club(almacen),
        cruces={},
    )


def hist_prior_de(player: dict[str, Any]) -> dict[str, float] | None:
    """``hist_prior`` del jugador desde el almacén local, o ``None`` si no hay cruce claro.

    Cruza por nombre dentro del mismo club y exige que el puesto coincida. Sin
    almacén (o sin el jugador) devuelve ``None`` y xP 2.0 usa el puesto.
    """
    nombre = player.get("name") or player.get("nickname")
    club = player.get("club") or player.get("team")
    if not nombre or not club:
        return None
    _cargar_estado()
    if not _ESTADO["resumenes"]:
        return None
    clave = (str(nombre), str(club))
    cruces = _ESTADO["cruces"]
    if clave not in cruces:
        cruces[clave] = emparejar(str(nombre), str(club), _ESTADO["indice"])
    slug = cruces[clave]
    resumen = _ESTADO["resumenes"].get(slug) if slug else None
    if not resumen:
        return None
    from toolbox.engine.xp_calculator import canonical_slot

    if canonical_slot(str(player.get("position") or "")) != resumen["slot"]:
        return None
    return hist_prior(resumen, _ESTADO["medias"])

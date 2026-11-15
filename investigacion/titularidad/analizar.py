"""Investigación de titularidad: acierto, techo, causas, señales y fuentes.

Solo lee la caché (``.cache``). No llama a la red, no reajusta pesos y no
escribe en ``toolbox/`` ni en ``scripts/``. Escribe ``resultados.json`` e
``INFORME.md`` junto a este fichero. El informe solo lleva números del JSON.

    python investigacion/titularidad/analizar.py
"""

from __future__ import annotations

import csv
import html
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

AQUI = Path(__file__).resolve().parent
ROOT = AQUI.parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ablacion_xp as ax  # noqa: E402
import linea_base_titularidad as lb  # noqa: E402
from toolbox import fantasy_scraper as fs  # noqa: E402
from toolbox.cache import cache_root  # noqa: E402
from toolbox.engine import p_titular_model as ptm  # noqa: E402
from toolbox.engine import xp2  # noqa: E402
from toolbox.engine.xp_calculator import canonical_slot  # noqa: E402
from toolbox.matching import CanonicalPlayer  # noqa: E402
from toolbox.opta_points_v2 import GOAL_PTS  # noqa: E402
from toolbox.rival_posicional import ajuste_rival_posicional  # noqa: E402
from toolbox.understat import parse_openfootball_matchdays  # noqa: E402

MADRID = ZoneInfo("Europe/Madrid")
SEED = 15
B = 2000
CORTE = 0.50
CORTE_DUDA = 0.70
CORTE_BAJO = 0.20
VENTANA_PESOS = {9, 10, 11}
TRAMOS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
RECORTES = [0.03, 0.05, 0.95]
MIN_TRAMO = 30
MIN_CLUB = 20
MIN_FUENTES_FILAS = 200
MIN_FUENTES_PARTIDOS = 4
L2_SENAL = 1.0
ANTELACION = [(">48 h", 48.0, 1e9), ("24–48 h", 24.0, 48.0), ("6–24 h", 6.0, 24.0), ("<6 h", 0.0, 6.0)]
FD_COD = {
    "ALA": "Alaves", "ATH": "Ath Bilbao", "ATM": "Ath Madrid", "BAR": "Barcelona", "BET": "Betis",
    "CEL": "Celta", "ELC": "Elche", "ESP": "Espanol", "GET": "Getafe", "GIR": "Girona",
    "LEG": "Leganes", "LEV": "Levante", "LPA": "Las Palmas", "MAL": "Mallorca", "OSA": "Osasuna",
    "RAY": "Vallecano", "RMD": "Real Madrid", "ROV": "Oviedo", "RSO": "Sociedad", "SEV": "Sevilla",
    "VAL": "Valencia", "VIL": "Villarreal", "VLD": "Valladolid",
}
FD_FICHERO = {"laliga-24-25": "SP1_2425.csv", "laliga-25-26": "SP1_2526.csv"}
ORDEN = {"laliga-24-25": 0, "laliga-25-26": 1, "26/27": 2}
INICIO_ACTAS = 1  # se fija en construir_casos con la primera jornada que tiene actas de la mayoría


def semana_recien_medible() -> int:
    """Desde qué jornada «menos de 3 partidos previos» no es solo el inicio del registro."""
    return INICIO_ACTAS + 3


# ---------------------------------------------------------------------------
# Estadística
# ---------------------------------------------------------------------------


def r(x: Any, d: int = 4) -> Any:
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return None if not math.isfinite(float(x)) else round(float(x), d)
    return x


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    ph = k / n
    den = 1 + z * z / n
    c = ph + z * z / (2 * n)
    rad = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return [r(max(0.0, (c - rad) / den)), r(min(1.0, (c + rad) / den))]


def ic(d: Any, jug: list[str], par: list[str]) -> dict[str, Any] | None:
    """Media e IC 95 % por remuestreo de jugadores y de partidos (2.000 cada uno, semilla 15)."""
    d = np.asarray(d, dtype=float)
    if len(d) == 0:
        return None
    lo_j, hi_j = ax._cluster_boot(d, list(jug), np.random.default_rng(SEED), B)
    lo_p, hi_p = ax._cluster_boot(d, list(par), np.random.default_rng(SEED), B)
    return {
        "media": r(d.mean()),
        "n": int(len(d)),
        "ic_jugador": [r(lo_j), r(hi_j)],
        "ic_partido": [r(lo_p), r(hi_p)],
        "cruza_cero": bool(lo_j <= 0 <= hi_j or lo_p <= 0 <= hi_p),
        "discrepan": bool((hi_j < 0) != (hi_p < 0) or (lo_j > 0) != (lo_p > 0)),
    }


def sig(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def beta_offset(off: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    """Un coeficiente en el log-odds con offset fijo (Newton, L2 = 1)."""
    b = 0.0
    for _ in range(30):
        p = sig(off + b * x)
        g = float(np.sum((y - p) * x)) - L2_SENAL * b
        h = float(np.sum(p * (1 - p) * x * x)) + L2_SENAL
        paso = g / h
        b += paso
        if abs(paso) < 1e-8:
            break
    return b


def jornadas_necesarias(res: dict[str, Any] | None, filas_por_jornada: float) -> int | None:
    """Jornadas para que un efecto del tamaño visto deje de cruzar cero (escala 1/√n)."""
    if not res or res["media"] is None or res["media"] >= 0 or filas_por_jornada <= 0:
        return None
    half = max(
        (res["ic_jugador"][1] - res["ic_jugador"][0]) / 2,
        (res["ic_partido"][1] - res["ic_partido"][0]) / 2,
    )
    delta = abs(res["media"])
    if delta <= 0:
        return None
    n_need = res["n"] * (half / delta) ** 2
    return min(TOPE_JORNADAS, int(math.ceil(n_need / filas_por_jornada)))


def jornadas_para_proporciones(p1: float, n1: int, p2: float, filas_por_jornada_1: float) -> int | None:
    """Tamaño por grupo para separar dos tasas al 5 % con potencia 80 %, en jornadas del grupo pequeño."""
    if p1 is None or p2 is None or abs(p1 - p2) < 1e-9 or filas_por_jornada_1 <= 0:
        return None
    n = (1.96 + 0.84) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p1 - p2) ** 2
    return min(TOPE_JORNADAS, int(math.ceil(n / filas_por_jornada_1)))


TOPE_JORNADAS = 101  # «más de 100»: no se distingue en un horizonte útil


def acierto(p: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {"n": int(len(y)), "tasa_titular": r(float(y.mean())) if len(y) else None}
    for corte in (CORTE, CORTE_DUDA, CORTE_BAJO):
        pred = p >= corte
        tp = int(np.sum(pred & (y == 1)))
        npred = int(pred.sum())
        npos = int(np.sum(y == 1))
        tn = int(np.sum(~pred & (y == 0)))
        out[f"corte_{corte:.2f}"] = {
            "previstos_titular": npred,
            "precision": r(tp / npred) if npred else None,
            "precision_ic": wilson(tp, npred),
            "sensibilidad": r(tp / npos) if npos else None,
            "sensibilidad_ic": wilson(tp, npos),
            "exactitud": r((tp + tn) / len(y)) if len(y) else None,
        }
    return out


def calibracion(p: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    tramos = []
    for lo, hi in TRAMOS:
        m = (p >= lo) & (p < hi)
        n = int(m.sum())
        k = int(y[m].sum()) if n else 0
        tramos.append(
            {
                "tramo": f"[{lo:.1f}, {min(hi, 1.0):.1f}{']' if hi > 1 else ')'}".replace(".", ","),
                "n": n,
                "p_media": r(float(p[m].mean())) if n else None,
                "frecuencia": r(k / n) if n else None,
                "ic": wilson(k, n),
                "se_lee": n >= MIN_TRAMO,
            }
        )
    recortes = []
    for v in RECORTES:
        m = np.abs(p - v) < 1e-6
        n = int(m.sum())
        k = int(y[m].sum()) if n else 0
        recortes.append({"valor": v, "n": n, "frecuencia": r(k / n) if n else None, "ic": wilson(k, n), "se_lee": n >= MIN_TRAMO})
    return {"tramos": tramos, "recortes": recortes}


def bloque_prob(p: np.ndarray, y: np.ndarray, jug: list[str], par: list[str]) -> dict[str, Any]:
    if len(y) == 0:
        return {"n": 0}
    return {
        "acierto": acierto(p, y),
        "brier": ic((p - y) ** 2, jug, par),
        "calibracion": calibracion(p, y),
    }


# ---------------------------------------------------------------------------
# Calendario, saques y contexto
# ---------------------------------------------------------------------------


def saques(cache: Path) -> tuple[dict[tuple[str, int], datetime], dict[str, Any], dict]:
    texto = (cache / "laliga_2026_27.txt").read_text(encoding="utf-8")
    md = parse_openfootball_matchdays(texto)
    fuentes = [
        ("football-data", lb._saques_csv(cache, md)),
        ("calendario", lb._saques_calendario(texto)),
        ("cuotas", lb._saques_cuotas(cache, md)[0]),
    ]
    mejor: dict[tuple[int, str, str], datetime] = {}
    origen: Counter = Counter()
    choques = []
    for nombre, filas in fuentes:
        for j, h, a, dt in filas:
            k = (j, h, a)
            dtm = dt.astimezone(MADRID)
            if k in mejor:
                if abs((mejor[k] - dtm).total_seconds()) > 7200:
                    choques.append({"jornada": j, "partido": f"{h}-{a}", "queda": mejor[k].isoformat(), "descartado": dtm.isoformat(), "fuente_descartada": nombre})
                continue
            mejor[k] = dtm
            origen[nombre] += 1
    usos: Counter = Counter()
    for j, h, a in mejor:
        usos[(h, j)] += 1
        usos[(a, j)] += 1
    ambiguos = sorted(f"{c}@J{j}" for (c, j), v in usos.items() if v > 1)
    por_club: dict[tuple[str, int], datetime] = {}
    for (j, h, a), dt in mejor.items():
        for club in (h, a):
            if usos[(club, j)] == 1:
                por_club[(club, j)] = dt
    # football-data sin jornada en el calendario: se cuentan, no se adivinan.
    fd_sin = 0
    with (cache / "football_data_raw_2627" / "SP1_2627.csv").open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if md.get((ax._club(row["HomeTeam"]), ax._club(row["AwayTeam"]))) is None:
                fd_sin += 1
    por_jornada = Counter(j for j, _, _ in mejor)
    control = {
        "partidos_con_hora_por_jornada": {str(j): por_jornada[j] for j in sorted(por_jornada) if j <= 14},
        "jornadas_sin_10_partidos": [j for j in sorted(por_jornada) if j <= 13 and por_jornada[j] != 10],
        "origen_de_la_hora": dict(origen),
        "choques_mayores_de_2h": choques,
        "clubes_con_dos_partidos_en_una_jornada_descartados": ambiguos,
        "filas_football_data_sin_jornada": fd_sin,
        "nota": "football-data trae hora de Londres y el calendario la de Madrid; las dos se pasan a Europe/Madrid antes de restar.",
    }
    return por_club, control, md


def calendario_clubes(cache: Path) -> dict[str, list[tuple[date, str]]]:
    datos = json.loads((cache / "calendario_competiciones_2627.json").read_text(encoding="utf-8"))
    out: dict[str, list[tuple[date, str]]] = {}
    for club, filas in datos.items():
        lista = [(date.fromisoformat(x["fecha"]), str(x["comp"])) for x in filas if x.get("comp") != "Amistoso" and x.get("fecha")]
        out[ax._club(club)] = sorted(lista)
    return out


def descanso_y_europa(cal: dict[str, list[tuple[date, str]]], club: str, kd: date) -> tuple[int | None, bool | None]:
    lista = cal.get(club)
    if not lista:
        return None, None
    previos = [d for d, _ in lista if d < kd]
    descanso = (kd - max(previos)).days if previos else None
    europa = any(c != "LaLiga" and kd - timedelta(days=4) <= d < kd for d, c in lista)
    return descanso, europa


# ---------------------------------------------------------------------------
# Onces guardados
# ---------------------------------------------------------------------------


@dataclass
class Captura:
    pid: str
    week: int | None
    fuente: str  # ff | af | final
    ts: float
    p: float
    status: str | None
    origen: str  # pagina_stored_at | pagina_mtime | registro
    oficial: bool = False  # página de AF con el once oficial: chance 0 para todos y esTitular en los 22


def html_unescape(s: str) -> str:
    return html.unescape(s).strip()


def _frac(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x > 1.0:
        x /= 100.0
    return x if 0.0 <= x <= 1.0 else None


def catalogo(cache: Path, actas: dict) -> dict[str, list[CanonicalPlayer]]:
    nombres_ff: dict[str, str] = {}
    try:
        conn = sqlite3.connect(cache / "entities.sqlite")
        for pid, nombre in conn.execute("select player_id, external_name from player_links where source='futbolfantasy'"):
            if nombre:
                nombres_ff[str(pid)] = str(nombre)
        conn.close()
    except sqlite3.Error:
        pass
    por_club: dict[str, list[CanonicalPlayer]] = defaultdict(list)
    for pid, e in actas.items():
        por_club[ax._club(e.get("team"))].append(
            CanonicalPlayer(
                player_id=str(pid),
                name=nombres_ff.get(str(pid)) or e.get("name"),
                nickname=e.get("name"),
                club=e.get("team"),
                position=e.get("position"),
                fantasy_price=None,
            )
        )
    return por_club


def capturas_paginas(cache: Path, md: dict, cat: dict[str, list[CanonicalPlayer]]) -> tuple[list[Captura], list[dict]]:
    caps: list[Captura] = []
    inventario: list[dict] = []
    for f in sorted((cache / "scraper_bodies").iterdir()):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        body = e.get("body") if isinstance(e, dict) else None
        if not isinstance(body, str):
            continue
        if "data-onceFF" in body and "data-probabilidad" in body:
            fuente = "ff"
            filas = fs.parse_ff_match(body)
            loc, vis = fs._ff_teams(body)
        elif "lineupBlock" in body:
            fuente = "af"
            filas = fs.parse_af_match(body)
            clubs = list(dict.fromkeys(x.club for x in filas if x.club))
            loc, vis = (clubs + [None, None])[:2]
            if not loc or not vis:
                # El JSON escapado no siempre trae los nombres: el título sí («Alineaciones probables A - B, …»).
                t = re.search(r"<title>\s*Alineaciones probables\s+(.+?)\s+-\s+(.+?)(?:,|\s[–—\-]\s|\s*</title>|\s+hoy)", body, re.I)
                block = fs._lineup_block(body)
                if t and block:
                    loc = html_unescape(t.group(1))
                    vis = re.split(r"\s*\S?\s*la liga\b", html_unescape(t.group(2)), maxsplit=1, flags=re.I)[0].strip(" -–—,")
                    filas = []
                    of = fs._af_official_xi(block)
                    for lado, nombre_club in (("home", loc), ("away", vis)):
                        if isinstance(block.get(lado), dict):
                            filas.extend(fs._af_players(block[lado], club=nombre_club, official=of))
        else:
            continue
        ts = e.get("stored_at")
        origen = "pagina_stored_at"
        if not isinstance(ts, (int, float)):
            ts = f.stat().st_mtime  # cota superior: el fichero se escribe al bajarlo o después
            origen = "pagina_mtime"
        if not loc or not vis:
            inventario.append({"fuente": fuente, "partido": None, "jornada": None, "motivo": "sin equipos"})
            continue
        h, a = ax._club(loc), ax._club(vis)
        j = md.get((h, a))
        if j is None and md.get((a, h)) is not None:
            j = md[(a, h)]
            h, a = a, h
        if j is None:
            inventario.append({"fuente": fuente, "partido": f"{h}-{a}", "jornada": None, "motivo": "partido fuera del calendario"})
            continue
        bloque_af = fs._lineup_block(body) if fuente == "af" else None
        oficial = bool(bloque_af) and fs._af_official_xi(bloque_af)
        hits = fs.match_catalog(cat.get(h, []) + cat.get(a, []), filas)
        n0 = 0
        for pid, hit in hits.items():
            p = _frac(hit.start_probability)
            if p is None:
                continue
            n0 += 1
            caps.append(Captura(pid, j, fuente, float(ts), p, hit.status, origen, oficial))
        inventario.append(
            {
                "fuente": fuente,
                "partido": f"{h}-{a}",
                "jornada": j,
                "guardado_madrid": datetime.fromtimestamp(float(ts), MADRID).strftime("%Y-%m-%d %H:%M"),
                "hora_de": origen,
                "jugadores_en_pagina": len(filas),
                "cruzados_con_actas": n0,
                "once_oficial_af": oficial,
            }
        )
    return caps, inventario


def p_af_antigua(cp: Captura) -> tuple[float, str]:
    """Cómo leía producción el once oficial antes del arreglo: p = 0, «duda» si salía de inicio."""
    return (0.0, "duda") if cp.status in ("titular", "duda") else (0.0, "fuera")


def medicion_once_oficial(casos: list[Caso]) -> dict[str, Any]:
    """Filas cuya p salió de una página de AF con el once oficial publicado: lectura antigua contra la actual."""
    sel = [c for c in casos if c.once_de == "paginas" and "af" in c.pre and c.pre["af"].oficial]
    out: dict[str, Any] = {
        "paginas_explicacion": (
            "AF, ~1 h antes del saque, publica el once oficial: chance = 0 para todos y esTitular verdadero en los 22. "
            "Antes del arreglo el parser lo leía como p = 0 y estado «duda»; ahora lee esTitular como 1/0 (`_af_official_xi`)."
        ),
        "n": len(sel),
        "partidos": len({c.match_id for c in sel}),
        "jornadas": sorted({c.week for c in sel}),
    }
    if not sel:
        return out
    y = arr(sel, "y")
    jug, par = grupos(sel)
    # p_fix: lo que lee producción hoy. p_prod: la lectura antigua, reconstruida.
    p_fix = arr(sel, "p_used")
    p_prod = []
    for c in sel:
        ff = c.pre.get("ff")
        p = mezcla((ff.p, ff.status) if ff else None, p_af_antigua(c.pre["af"]))
        p_prod.append(portero(c.slot, c.mins_prev, c.weeks_prev, p, externa=True))
    p_prod = np.array(p_prod)
    tit = np.array([c.pre["af"].status in ("titular", "duda") for c in sel])
    out["titulares_oficiales"] = int(tit.sum())
    out["produccion"] = {"brier": r(float(np.mean((p_prod - y) ** 2))), "acierto_0_50": acierto(p_prod, y)["corte_0.50"], "p_media_titulares_oficiales": r(float(p_prod[tit].mean())) if tit.any() else None}
    out["leido_como_once"] = {"brier": r(float(np.mean((p_fix - y) ** 2))), "acierto_0_50": acierto(p_fix, y)["corte_0.50"]}
    out["delta_brier"] = ic((p_fix - y) ** 2 - (p_prod - y) ** 2, jug, par)
    cx = [(c, pa) for c, pa in zip(sel, p_prod) if c.tiene_xp2]
    if cx:
        d = [abs(xp_prod(c, c.p_used) - c.pts) - abs(xp_prod(c, pa) - c.pts) for c, pa in cx]
        out["delta_mae_xp"] = ic(d, [c.pid for c, _ in cx], [c.match_id for c, _ in cx])
        out["n_xp2"] = len(cx)
    out["nota"] = (
        "Producción descarta solo los partidos ya empezados; entre la publicación del once oficial y el saque lee estas páginas. "
        "La alineación se bloquea en el primer partido de la jornada, así que pesa sobre todo en ese partido y en el mercado de esas horas."
    )
    return out


def capturas_registro(cache: Path) -> tuple[list[Captura], list[tuple[str, float, float, str]]]:
    conn = sqlite3.connect(cache / "responses.sqlite")
    try:
        filas = conn.execute(
            "select player_id, stored_at, p_titular_ff, p_titular_af, p_titular_final, p_titular_fuente, "
            "lineup_status, own_expected_points from player_signal_log"
        ).fetchall()
        snap = conn.execute(
            "select player_id, stored_at, expected_points, jornada_id from matchday_snapshot_log where expected_points is not null"
        ).fetchall()
    finally:
        conn.close()
    caps: list[Captura] = []
    xp_guardado: list[tuple[str, float, float, str]] = []
    for pid, ts, ff, af, final, fuente, estado, oxp in filas:
        pid = str(pid)
        ts = float(ts)
        for nombre, v in (("ff", ff), ("af", af)):
            p = _frac(v)
            if p is not None:
                caps.append(Captura(pid, None, nombre, ts, p, fs.classify_lineup(role=None, probability=p, note=None), "registro"))
        pf = _frac(final)
        if pf is not None and fuente == "scraper":
            caps.append(Captura(pid, None, "final", ts, pf, estado, "registro"))
        if oxp is not None:
            xp_guardado.append((pid, ts, float(oxp), "player_signal_log"))
    for pid, ts, xp_v, jid in snap:
        xp_guardado.append((str(pid), float(ts), float(xp_v), f"matchday_snapshot_log:J{jid}"))
    return caps, xp_guardado


def mezcla(ff: tuple[float, str | None] | None, af: tuple[float, str | None] | None) -> float | None:
    """La mezcla de producción: media, o pico si alguna dice titular con ≥ 0,70; filtros de AF 0,50 y consenso bajo."""
    filas = []
    if ff is not None:
        filas.append(fs.LineupPlayer(name="x", source="futbolfantasy", start_probability=ff[0], status=ff[1] or fs.classify_lineup(role=None, probability=ff[0], note=None)))
    af_vale = af is not None and not (ff is not None and abs(af[0] - 0.50) < 1e-9 and (ff[0] >= 0.75 or ff[0] <= 0.25))
    if af_vale:
        filas.append(fs.LineupPlayer(name="x", source="analiticafantasy", start_probability=af[0], status=af[1] or fs.classify_lineup(role=None, probability=af[0], note=None)))
    if not filas:
        return None
    p = fs._merge_rows([(x, 1.0) for x in filas]).start_probability
    if ff is not None and af is not None and ff[0] <= CORTE_BAJO and af[0] <= CORTE_BAJO:
        p = min(ff[0], af[0])
    return None if p is None else float(p)


# ---------------------------------------------------------------------------
# Casos de 26/27
# ---------------------------------------------------------------------------


@dataclass
class Caso:
    f: ax.Fila
    pid: str
    week: int
    slot: str
    club: str
    match_id: str
    minutes: float
    y: float
    pts: float
    mins_prev: list[float]
    weeks_prev: list[int]
    p_log: float
    p_log_gk: float
    kickoff: datetime | None
    kickoff_prev: datetime | None
    kickoff_next: datetime | None
    fin_jornada: datetime | None = None
    pre: dict[str, Captura] = field(default_factory=dict)
    post: dict[str, Captura] = field(default_factory=dict)
    capturas_pre: list[Captura] = field(default_factory=list)
    p_once: float | None = None
    ts_once: float | None = None
    p_used: float = 0.0
    fuente_p: str = "logistica"
    once_de: str | None = None
    cond: float | None = None
    banq: float | None = None
    roja_prev: bool = False
    descanso: int | None = None
    europa4: bool | None = None

    @property
    def banda(self) -> bool:
        return 0 < self.minutes < ptm.STARTER_MINUTES

    @property
    def tiene_xp2(self) -> bool:
        return self.cond is not None


def portero(slot: str, mins: list[float], weeks: list[int], p: float, externa: bool) -> float:
    if slot != "PT":
        return p
    player: dict[str, Any] = {
        "position": "POR",
        "p_titular": p,
        "historial": [
            {"jornada": j, "minutos": m, "puntos": 0, "desglose": {"puntos": {}, "cantidades": {}}}
            for m, j in zip(mins, weeks)
        ],
    }
    if externa:
        player["p_titular_source"] = "scraper"
    return float(xp2.prob_titular_portero(player, p))


def piezas_xp(fila: ax.Fila) -> tuple[float, float] | None:
    """xP condicional de producción y término de banquillo (F × media de revulsivo)."""
    player = ax.jugador(fila, ax.Config("base"), 1.0)
    pos = str(player.get("position") or "MC").upper()
    if pos not in GOAL_PTS:
        pos = "MC"
    if fila.partido.lam_f is not None:
        lam_f, lam_c, pcs = fila.partido.lam_f, fila.partido.lam_c, fila.partido.p_cs
    else:
        lam_f, lam_c, pcs = 1.32, 1.32, None
    det = xp2.prediccion_xp2(
        player,
        prob_titular=1.0,
        lambda_favor=lam_f,
        lambda_contra=lam_c,
        prob_porteria_cero=pcs,
        ajuste_rival=ajuste_rival_posicional(player.get("rival"), pos),
    )
    if det is None:
        return None
    slot = canonical_slot(str(player.get("position") or "MC"))
    actas = xp2.actas_del_jugador(player)
    rev = [a.puntos for a in actas if 0 < a.minutos < 45]
    banq = xp2.FACTOR_BANQUILLO[slot] * xp2._contrae(rev, xp2.REVULSIVO_PUESTO[slot], 3.0)
    return float(det["xp_condicional"]), float(banq)


def xp_prod(c: Caso, p: float) -> float:
    """Lo que publica producción: con p ≤ 0,01 el código devuelve 0."""
    if p <= 0.01:
        return 0.0
    return max(0.0, p * c.cond + (1 - p) * c.banq)


def xp_oraculo(c: Caso, y: float) -> float:
    return max(0.0, y * c.cond + (1 - y) * c.banq)


def construir_casos(cache: Path) -> tuple[list[Caso], dict[str, Any]]:
    filas, actas, _ = ax.construir_filas([8, 9, 10, 11, 12], min_prior=1)
    sin_previa = Counter()
    for pid, e in actas.items():
        weeks = sorted(int(k) for k in (e.get("weeks") or {}))
        for i, w in enumerate(weeks):
            if i == 0:
                sin_previa[w] += 1
    por_club, control, md = saques(cache)
    cal = calendario_clubes(cache)
    saques_club: dict[str, list[datetime]] = defaultdict(list)
    por_semana: dict[int, list[datetime]] = defaultdict(list)
    for (club, j), dt in por_club.items():
        saques_club[club].append(dt)
        por_semana[j].append(dt)
    for v in saques_club.values():
        v.sort()
    # Fin de jornada: último saque a menos de 5 días del primero (un aplazado no la alarga) + 2 h.
    fin: dict[int, datetime] = {}
    for j, ks in por_semana.items():
        primero = min(ks)
        fin[j] = max(k for k in ks if k <= primero + timedelta(days=5)) + timedelta(hours=2)
    # Primera jornada con actas de la mayoría: antes de ella no hay historial guardado.
    cuenta = Counter(int(w) for e in actas.values() for w in (e.get("weeks") or {}))
    tope = max(cuenta.values()) if cuenta else 0
    global INICIO_ACTAS
    INICIO_ACTAS = min((w for w, v in cuenta.items() if v >= 0.5 * tope), default=1)
    casos: list[Caso] = []
    for f in filas:
        mins = [float(h["minutos"]) for h in f.historial]
        weeks = [int(h["jornada"]) for h in f.historial]
        p_log = lb._prob_historial(mins, weeks)
        k = por_club.get((f.club, f.week))
        lista = saques_club.get(f.club, [])
        k_prev = max((d for d in lista if k is not None and d < k), default=None)
        k_next = min((d for d in lista if k is not None and d > k), default=None)
        c = Caso(
            f=f, pid=f.pid, week=f.week, slot=f.slot, club=f.club, match_id=f.match_id,
            minutes=f.minutes, y=1.0 if f.minutes >= ptm.STARTER_MINUTES else 0.0, pts=f.actual,
            mins_prev=mins, weeks_prev=weeks, p_log=p_log,
            p_log_gk=portero(f.slot, mins, weeks, p_log, externa=False),
            kickoff=k, kickoff_prev=k_prev, kickoff_next=k_next, fin_jornada=fin.get(f.week),
        )
        ult = f.historial[-1]
        if int(ult["jornada"]) == f.week - 1:
            cant = (ult.get("desglose") or {}).get("cantidades") or {}
            c.roja_prev = bool((cant.get("red_card") or 0) > 0 or (cant.get("second_yellow_card") or 0) > 0)
        if k is not None:
            c.descanso, c.europa4 = descanso_y_europa(cal, f.club, k.date())
        piezas = piezas_xp(f)
        if piezas is not None:
            c.cond, c.banq = piezas
        casos.append(c)
    notas = {
        "control_saques": control,
        "actas_sin_acta_previa_por_jornada": {str(w): n for w, n in sorted(sin_previa.items())},
        "casos_sin_hora_de_saque": sum(1 for c in casos if c.kickoff is None),
        "casos_sin_calendario_de_club": sum(1 for c in casos if c.descanso is None),
        "inicio_actas": INICIO_ACTAS,
        "huecos": huecos(actas, por_club),
    }
    return casos, notas, md  # type: ignore[return-value]


def huecos(actas: dict, por_club: dict) -> list[dict[str, Any]]:
    """Jornadas sin acta entre dos actas del mismo jugador: no convocado, lesión o sanción.

    No están en la cohorte del plan (solo quien tiene acta). Se guardan para medir
    cuánto cambia la precisión si se cuentan como «no fue titular».
    """
    out = []
    for pid, e in actas.items():
        weeks = {int(k): v for k, v in (e.get("weeks") or {}).items()}
        if not weeks:
            continue
        orden = sorted(weeks)
        club = ax._club(e.get("team"))
        slot = canonical_slot(e.get("position") or "MC")
        for t in range(max(orden[0] + 1, 8), orden[-1]):
            if t in weeks or (club, t) not in por_club:
                continue
            previos = [w for w in orden if w < t]
            mins = [float(weeks[w][1]) for w in previos]
            p = lb._prob_historial(mins, previos)
            out.append({"pid": str(pid), "week": t, "club": club, "p_log_gk": portero(slot, mins, previos, p, externa=False)})
    return out


def asignar_onces(casos: list[Caso], caps: list[Captura]) -> None:
    por_pid: dict[str, list[Captura]] = defaultdict(list)
    for cp in caps:
        por_pid[cp.pid].append(cp)
    for c in casos:
        if c.kickoff is None:
            continue
        k = c.kickoff.timestamp()
        lo = c.kickoff_prev.timestamp() + 3 * 3600 if c.kickoff_prev else -1e18
        # Fuga: guardado tras el saque de ese partido y antes de que acabe su jornada
        # (después ya es la previa de la siguiente).
        hi_post = min(k + 72 * 3600, c.fin_jornada.timestamp() if c.fin_jornada else k + 72 * 3600)
        pre, post = [], []
        for cp in por_pid.get(c.pid, []):
            if cp.week is not None:
                if cp.week != c.week:
                    continue
                (pre if cp.ts < k else post).append(cp)
            else:
                if lo < cp.ts < k:
                    pre.append(cp)
                elif k <= cp.ts < hi_post:
                    post.append(cp)
        c.capturas_pre = pre
        for dest, lista in ((c.pre, pre), (c.post, post)):
            for cp in lista:
                if cp.fuente not in dest or cp.ts > dest[cp.fuente].ts:
                    dest[cp.fuente] = cp
        # Lo que habría entrado: la captura de once más reciente antes del saque.
        ff, af, fin = c.pre.get("ff"), c.pre.get("af"), c.pre.get("final")
        t_paginas = max([x.ts for x in (ff, af) if x is not None], default=-1e18)
        if fin is not None and fin.ts >= t_paginas:
            c.p_once, c.ts_once, c.once_de = fin.p, fin.ts, "registro"
        elif ff is not None or af is not None:
            c.p_once = mezcla((ff.p, ff.status) if ff else None, (af.p, af.status) if af else None)
            c.ts_once, c.once_de = t_paginas, "paginas"
        if c.p_once is not None:
            c.p_used = portero(c.slot, c.mins_prev, c.weeks_prev, c.p_once, externa=True)
            c.fuente_p = "once"
        else:
            c.p_used = c.p_log_gk
    for c in casos:
        if c.kickoff is None:
            c.p_used = c.p_log_gk


# ---------------------------------------------------------------------------
# Histórico 24/25 y 25/26
# ---------------------------------------------------------------------------


@dataclass
class Hist:
    pid: str
    season: str
    orden: int
    week: int
    slot: str
    y: float
    banda: bool
    p_log: float
    p_prod: float
    p_prev: float
    n_prev: int
    match_id: str
    descanso: int | None
    estado: str | None


def _fechas_fd(cache: Path) -> dict[str, dict[tuple[str, str], date]]:
    out: dict[str, dict[tuple[str, str], date]] = {}
    for temp, fichero in FD_FICHERO.items():
        ruta = cache / "football_data_raw" / fichero
        d: dict[tuple[str, str], date] = {}
        with ruta.open(encoding="utf-8-sig", errors="replace") as fh:
            for row in csv.DictReader(fh):
                raw = row.get("Date") or ""
                for fmt in ("%d/%m/%Y", "%d/%m/%y"):
                    try:
                        d[(row["HomeTeam"].strip(), row["AwayTeam"].strip())] = datetime.strptime(raw, fmt).date()
                        break
                    except ValueError:
                        continue
        out[temp] = d
    return out


def filas_historicas(cache: Path) -> tuple[list[Hist], dict[str, Any]]:
    fd = _fechas_fd(cache)
    calendario_equipo: dict[str, dict[str, list[date]]] = {}
    for temp, d in fd.items():
        cal: dict[str, list[date]] = defaultdict(list)
        for (h, a), dt in d.items():
            cal[h].append(dt)
            cal[a].append(dt)
        calendario_equipo[temp] = {k: sorted(v) for k, v in cal.items()}
    filas: list[Hist] = []
    estados: Counter = Counter()
    sin_fecha = 0
    for slug, entrada in lb.leer_almacen().items():
        slot = lb._slot(entrada.get("posicion"))
        for nombre, temp in (entrada.get("temporadas") or {}).items():
            if nombre not in FD_FICHERO or not lb.temporada_coherente(temp, nombre):
                continue
            crudas = [x for x in (temp.get("filas") or []) if x.get("minutos") is not None and x.get("j") is not None]
            crudas.sort(key=lambda x: int(x["j"]))
            codigos = Counter(c for x in crudas for c in (x.get("equipos") or []))
            # El club del jugador es el código que más se repite en sus partidos de la temporada.
            propio = None
            if crudas:
                cuenta_partidos = Counter()
                for x in crudas:
                    for c in set(x.get("equipos") or []):
                        cuenta_partidos[c] += 1
                propio = cuenta_partidos.most_common(1)[0][0] if cuenta_partidos else None
            _ = codigos
            for i, x in enumerate(crudas):
                estados[x.get("estado")] += 1
                if i == 0:
                    continue
                prev = crudas[:i]
                mins = [float(z["minutos"]) for z in prev]
                js = [int(z["j"]) for z in prev]
                p_log = lb._prob_historial(mins, js)
                eqs = list(x.get("equipos") or [])
                week = int(x["j"])
                fecha = None
                if len(eqs) >= 2:
                    a, b = FD_COD.get(eqs[0]), FD_COD.get(eqs[1])
                    fecha = fd[nombre].get((a, b)) or fd[nombre].get((b, a))
                descanso = None
                if fecha is not None and propio in FD_COD:
                    seq = calendario_equipo[nombre].get(FD_COD[propio], [])
                    previas = [d for d in seq if d < fecha]
                    if previas:
                        descanso = (fecha - max(previas)).days
                if fecha is None:
                    sin_fecha += 1
                ms = [lb.normalize_club(e) for e in eqs[:2] if e]
                match = f"{nombre}:{week}:{'|'.join(sorted(ms))}" if len(ms) == 2 else f"{nombre}:{week}:{slug}"
                m = float(x["minutos"])
                filas.append(
                    Hist(
                        pid=slug, season=nombre, orden=ORDEN[nombre], week=week, slot=slot,
                        y=1.0 if m >= ptm.STARTER_MINUTES else 0.0, banda=0 < m < ptm.STARTER_MINUTES,
                        p_log=p_log, p_prod=lb._prob_portero(slot, mins, js, p_log),
                        p_prev=1.0 if mins[-1] >= ptm.STARTER_MINUTES else 0.0, n_prev=len(prev),
                        match_id=match, descanso=descanso, estado=x.get("estado"),
                    )
                )
    notas = {
        "filas": len(filas),
        "jugadores": len({h.pid for h in filas}),
        "sin_fecha_de_partido": sin_fecha,
        "estado_relleno": {str(k): v for k, v in estados.most_common()},
        "nota_descanso": "En 24/25 y 25/26 el descanso sale de las fechas de LaLiga en football-data: no ve Europa ni Copa.",
    }
    return filas, notas


# ---------------------------------------------------------------------------
# Mediciones
# ---------------------------------------------------------------------------


def arr(casos: list, attr: str) -> np.ndarray:
    return np.array([getattr(c, attr) for c in casos], dtype=float)


def grupos(casos: list) -> tuple[list[str], list[str]]:
    return [c.pid for c in casos], [c.match_id for c in casos]


def medicion_1(casos: list[Caso], filas_base: list, base_xp: np.ndarray, xp_guardado: list, huecos_l: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # Sensibilidad: quien no tiene acta esa jornada (entre dos suyas) no fue titular.
    p_c = arr(casos, "p_used")
    y_c = arr(casos, "y")
    p_h = np.array([h["p_log_gk"] for h in huecos_l])
    pred_c = p_c >= CORTE
    pred_h = p_h >= CORTE
    tp = int(np.sum(pred_c & (y_c == 1)))
    npred = int(pred_c.sum() + pred_h.sum())
    out["huecos_sensibilidad"] = {
        "n_huecos": len(huecos_l),
        "huecos_con_p_0_50_o_mas": int(pred_h.sum()),
        "precision_contando_huecos": r(tp / npred) if npred else None,
        "precision_contando_huecos_ic": wilson(tp, npred),
        "nota": (
            "Jornadas sin acta entre dos actas del mismo jugador (no convocado, lesión, sanción). La cohorte del plan no las ve. "
            "Su p es la logística con regla de portero; no se busca su once."
        ),
    }
    # MAE base recalculado sobre las actas de hoy.
    y_pts = np.array([f.actual for f in filas_base])
    err = np.abs(base_xp - y_pts)
    por_sem = {}
    for w in sorted({f.week for f in filas_base}):
        m = np.array([f.week == w for f in filas_base])
        por_sem[str(w)] = {"n": int(m.sum()), "mae": r(float(err[m].mean()))}
    out["mae_base"] = {
        "n": int(len(filas_base)),
        "mae": r(float(err.mean())),
        "por_jornada": por_sem,
        "referencia_anterior": 2.70,
        "j8_entra": any(f.week == 8 for f in filas_base),
    }
    # Comprobación de la reconstrucción del xP: con la logística debe coincidir con la base.
    idx = {(f.pid, f.week): i for i, f in enumerate(filas_base)}
    difs = [abs(xp_prod(c, c.p_log_gk) - base_xp[idx[(c.pid, c.week)]]) for c in casos if c.tiene_xp2 and (c.pid, c.week) in idx]
    out["reconstruccion_vs_base"] = {"n": len(difs), "max_abs": r(max(difs) if difs else None), "media_abs": r(float(np.mean(difs)) if difs else None)}

    y = arr(casos, "y")
    jug, par = grupos(casos)
    p_used = arr(casos, "p_used")
    out["lo_que_entro"] = bloque_prob(p_used, y, jug, par)
    out["origen_de_p"] = dict(Counter(c.fuente_p for c in casos))
    out["logistica_sola"] = bloque_prob(arr(casos, "p_log_gk"), y, jug, par)
    con_once = [c for c in casos if c.p_once is not None]
    out["once_solo"] = bloque_prob(np.array([c.p_used for c in con_once]), arr(con_once, "y"), *grupos(con_once))
    out["logistica_en_filas_con_once"] = bloque_prob(arr(con_once, "p_log_gk"), arr(con_once, "y"), *grupos(con_once))
    limpio = [c for c in casos if not (c.once_de == "paginas" and "af" in c.pre and c.pre["af"].oficial)]
    out["sin_paginas_oficiales_af"] = {
        "n": len(limpio),
        "brier_lo_que_entro": r(float(np.mean((arr(limpio, "p_used") - arr(limpio, "y")) ** 2))),
        "brier_logistica": r(float(np.mean((arr(limpio, "p_log_gk") - arr(limpio, "y")) ** 2))),
        "delta": ic((arr(limpio, "p_used") - arr(limpio, "y")) ** 2 - (arr(limpio, "p_log_gk") - arr(limpio, "y")) ** 2, *grupos(limpio)),
    }
    fuera = [c for c in casos if c.week not in VENTANA_PESOS]
    out["sin_J9_J11"] = {
        "jornadas": sorted({c.week for c in fuera}),
        "lo_que_entro": bloque_prob(arr(fuera, "p_used"), arr(fuera, "y"), *grupos(fuera)),
        "logistica_sola": bloque_prob(arr(fuera, "p_log_gk"), arr(fuera, "y"), *grupos(fuera)),
    }
    alto = [c for c in casos if c.p_used >= 0.8]
    out["tramo_alto_0_80"] = {
        "n": len(alto),
        "frecuencia_titular": r(float(np.mean([c.y for c in alto]))) if alto else None,
        "ic": wilson(int(sum(c.y for c in alto)), len(alto)),
        "jugo_1_44": sum(1 for c in alto if c.banda),
        "jugo_0": sum(1 for c in alto if c.minutes == 0),
    }

    def tabla(clave) -> dict[str, Any]:
        g: dict[str, list[Caso]] = defaultdict(list)
        for c in casos:
            g[str(clave(c))].append(c)
        res = {}
        for k, lista in sorted(g.items(), key=lambda kv: (0, int(kv[0]), "") if kv[0].isdigit() else (1, 0, kv[0])):
            p = arr(lista, "p_used")
            yy = arr(lista, "y")
            pred = p >= CORTE
            tp = int(np.sum(pred & (yy == 1)))
            res[k] = {
                "n": len(lista),
                "tasa_titular": r(float(yy.mean())),
                "previstos_titular": int(pred.sum()),
                "precision": r(tp / pred.sum()) if pred.sum() else None,
                "precision_ic": wilson(tp, int(pred.sum())),
                "brier": r(float(np.mean((p - yy) ** 2))),
                "se_comenta": len(lista) >= MIN_CLUB,
            }
        return res

    out["por_jornada"] = tabla(lambda c: c.week)
    out["por_puesto"] = tabla(lambda c: c.slot)
    out["por_club"] = tabla(lambda c: c.club)
    out["nota_club"] = "Descriptivo, por el club del partido. Un club con n < 20 no se comenta. No entra en ninguna recomendación."
    out["nota_antelacion_logistica"] = (
        "La logística solo usa minutos de jornadas ya jugadas: no cambia entre el cierre de la jornada anterior y el saque. "
        "Partirla por 48 h / 24 h / pocas horas no aplica."
    )

    # Antelación de las fuentes de once, solo capturas anteriores al saque.
    ant: dict[str, Any] = {}
    for fuente in ("ff", "af", "mezcla"):
        ant[fuente] = {}
        for nombre, lo, hi in ANTELACION:
            ps, ys, js, ms = [], [], [], []
            for c in casos:
                if c.kickoff is None:
                    continue
                k = c.kickoff.timestamp()
                en = [cp for cp in c.capturas_pre if lo <= (k - cp.ts) / 3600 < hi]
                ult: dict[str, Captura] = {}
                for cp in en:
                    if cp.fuente not in ult or cp.ts > ult[cp.fuente].ts:
                        ult[cp.fuente] = cp
                if fuente == "mezcla":
                    ff, af = ult.get("ff"), ult.get("af")
                    if ff is None and af is None:
                        continue
                    p = mezcla((ff.p, ff.status) if ff else None, (af.p, af.status) if af else None)
                else:
                    cp = ult.get(fuente)
                    p = cp.p if cp else None
                if p is None:
                    continue
                ps.append(portero(c.slot, c.mins_prev, c.weeks_prev, p, externa=True))
                ys.append(c.y)
                js.append(c.pid)
                ms.append(c.match_id)
            pa, ya = np.array(ps), np.array(ys)
            ant[fuente][nombre] = {
                "n": len(ps),
                "partidos": len(set(ms)),
                "brier": r(float(np.mean((pa - ya) ** 2))) if ps else None,
                "acierto_0_50": acierto(pa, ya)["corte_0.50"] if ps else None,
            }
    out["antelacion_onces"] = ant

    # Fuga: el mismo cálculo con capturas posteriores al saque de ese partido.
    fuga = [c for c in casos if c.post]
    ps = []
    for c in fuga:
        fin = c.post.get("final")
        ff, af = c.post.get("ff"), c.post.get("af")
        p = fin.p if fin is not None else mezcla((ff.p, ff.status) if ff else None, (af.p, af.status) if af else None)
        ps.append(p)
    fuga2 = [(c, p) for c, p in zip(fuga, ps) if p is not None]
    if fuga2:
        pa = np.array([portero(c.slot, c.mins_prev, c.weeks_prev, p, externa=True) for c, p in fuga2])
        ya = np.array([c.y for c, _ in fuga2])
        out["fuga_post_saque"] = {
            "aviso": "FUGA: capturas guardadas después del saque de ese partido. No se usan para elegir fuente.",
            "jornadas": sorted({c.week for c, _ in fuga2}),
            "partidos": len({c.match_id for c, _ in fuga2}),
            "origen": dict(Counter(("registro" if "final" in c.post else "pagina") + ("_af_oficial" if "af" in c.post and c.post["af"].oficial else "") for c, _ in fuga2)),
            "p_media_de_quien_fue_titular": r(float(np.mean([pp for (c, _), pp in zip(fuga2, pa) if c.y == 1]))) if any(c.y == 1 for c, _ in fuga2) else None,
            **bloque_prob(pa, ya, [c.pid for c, _ in fuga2], [c.match_id for c, _ in fuga2]),
        }
    else:
        out["fuga_post_saque"] = {"n": 0}

    # xP guardado antes del saque contra el recalculado.
    guard: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    for pid, ts, v, origen in xp_guardado:
        guard[pid].append((ts, v, origen))
    comp = []
    for c in casos:
        if not c.tiene_xp2 or c.kickoff is None:
            continue
        k = c.kickoff.timestamp()
        lo = c.kickoff_prev.timestamp() + 3 * 3600 if c.kickoff_prev else -1e18
        cand = [g for g in guard.get(c.pid, []) if lo < g[0] < k and (not g[2].startswith("matchday") or g[2].endswith(f"J{c.week}"))]
        if not cand:
            continue
        ts, v, origen = max(cand)
        comp.append((v, xp_prod(c, c.p_used), c.week, origen))
    if comp:
        g = np.array([x[0] for x in comp])
        rc = np.array([x[1] for x in comp])
        out["xp_guardado_vs_recalculado"] = {
            "n": len(comp),
            "jornadas": sorted({x[2] for x in comp}),
            "origen": dict(Counter(x[3].split(":")[0] for x in comp)),
            "media_abs": r(float(np.mean(np.abs(g - rc)))),
            "media_dif_guardado_menos_recalculado": r(float(np.mean(g - rc))),
            "correlacion": r(float(np.corrcoef(g, rc)[0, 1])) if len(comp) > 2 else None,
            "pct_dif_mayor_0_5": r(float(np.mean(np.abs(g - rc) > 0.5))),
        }
    else:
        out["xp_guardado_vs_recalculado"] = {"n": 0}
    return out


def medicion_2(casos: list[Caso]) -> dict[str, Any]:
    cx = [c for c in casos if c.tiene_xp2]
    out: dict[str, Any] = {"n_con_xp2": len(cx), "n_sin_xp2_fuera_del_techo": len(casos) - len(cx)}
    jug, par = grupos(cx)
    xp_p = np.array([xp_prod(c, c.p_used) for c in cx])
    xp_y = np.array([xp_oraculo(c, c.y) for c in cx])
    pts = arr(cx, "pts")
    estr = np.abs(xp_p - xp_y)
    out["estructural"] = ic(estr, jug, par)
    out["mae_xp_p"] = r(float(np.mean(np.abs(xp_p - pts))))
    xp_l = np.array([xp_prod(c, c.p_log_gk) for c in cx])
    out["mae_xp_logistica_mismas_filas"] = r(float(np.mean(np.abs(xp_l - pts))))
    out["delta_mae_lo_que_entro_menos_logistica"] = ic(np.abs(xp_p - pts) - np.abs(xp_l - pts), jug, par)
    out["mae_xp_oraculo"] = r(float(np.mean(np.abs(xp_y - pts))))
    out["realizada"] = ic(np.abs(xp_p - pts) - np.abs(xp_y - pts), jug, par)
    p = arr(cx, "p_used")
    y = arr(cx, "y")
    ok = (p >= CORTE) == (y == 1)
    out["por_acierto_del_corte"] = {
        "acierta": {"n": int(ok.sum()), "mae_xp": r(float(np.mean(np.abs(xp_p - pts)[ok]))), "estructural_media": r(float(estr[ok].mean())), "estructural_suma": r(float(estr[ok].sum()), 2)},
        "falla": {"n": int((~ok).sum()), "mae_xp": r(float(np.mean(np.abs(xp_p - pts)[~ok]))) if (~ok).any() else None, "estructural_media": r(float(estr[~ok].mean())) if (~ok).any() else None, "estructural_suma": r(float(estr[~ok].sum()), 2)},
    }
    mins = arr(cx, "minutes")
    tipos = {
        "previsto_titular_y_jugo_0": (p >= CORTE) & (mins == 0),
        "previsto_titular_y_jugo_1_44": (p >= CORTE) & (mins > 0) & (mins < 45),
        "previsto_suplente_y_jugo_45_o_mas": (p < CORTE) & (mins >= 45),
    }
    total = float(estr.sum())
    out["fallos_en_tres"] = {
        k: {"n": int(m.sum()), "puntos_estructurales": r(float(estr[m].sum()), 2), "cuota_del_total": r(float(estr[m].sum()) / total) if total else None, "media": r(float(estr[m].mean())) if m.any() else None}
        for k, m in tipos.items()
    }
    rec = tipos["previsto_titular_y_jugo_0"] | tipos["previsto_suplente_y_jugo_45_o_mas"]
    out["recuperable_con_once_perfecto"] = {
        "puntos": r(float(estr[rec].sum()), 2),
        "cuota": r(float(estr[rec].sum()) / total) if total else None,
        "por_fila_del_total": r(float(estr[rec].sum()) / len(cx)) if cx else None,
        "nota": "Solo el fallo «titular y 0'» y el «suplente y ≥ 45'» los recupera un once perfecto; la banda 1–44' es error de minutos.",
    }
    out["puntos_estructurales_total"] = r(total, 2)
    out["nota"] = (
        "Las dos llamadas usan el mismo xP condicional (actas anteriores, λ de cierre, precio, ajuste rival y de club) y solo cambia p. "
        "El oráculo con y = 0 usa el término de banquillo; producción con p ≤ 0,01 publica 0."
    )
    return out


CAUSAS = [
    ("roja_o_doble_amarilla_anterior", "roja o doble amarilla en el acta anterior"),
    ("quinta_amarilla", "5.ª/10.ª/15.ª amarilla cerrada en la jornada anterior"),
    ("portero_no_jugo_anterior", "portero que no jugó la anterior"),
    ("recien_llegado", "recién llegado (menos de 3 partidos previos)"),
    ("vuelta_tras_0", "vuelta tras un 0' siendo titular en al menos la mitad de lo anterior"),
    ("europa_o_copa_4_dias", "Europa o Copa en los 4 días previos"),
    ("descanso_3_o_menos", "descanso de 3 días o menos"),
    ("descanso_10_o_mas", "descanso de 10 días o más (vuelta de parón)"),
    ("sin_causa_conocida", "sin causa conocida"),
]


def tiene_causa(c: Caso, clave: str) -> bool | None:
    if clave == "roja_o_doble_amarilla_anterior":
        return c.roja_prev
    if clave == "quinta_amarilla":
        return None  # no medible: las tarjetas solo están desde el inicio de las actas
    if clave == "portero_no_jugo_anterior":
        return c.slot == "PT" and c.mins_prev[-1] == 0
    if clave == "recien_llegado":
        return (len(c.mins_prev) < 3) if c.week >= semana_recien_medible() else None
    if clave == "vuelta_tras_0":
        if len(c.mins_prev) < 2:
            return False
        antes = c.mins_prev[:-1]
        return c.mins_prev[-1] == 0 and np.mean([m >= 45 for m in antes]) >= 0.5
    if clave == "europa_o_copa_4_dias":
        return c.europa4
    if clave == "descanso_3_o_menos":
        return None if c.descanso is None else c.descanso <= 3
    if clave == "descanso_10_o_mas":
        return None if c.descanso is None else c.descanso >= 10
    return True


def medicion_3(casos: list[Caso]) -> dict[str, Any]:
    cx = [c for c in casos if c.tiene_xp2 and not c.banda]
    jornadas = len({c.week for c in cx}) or 1
    fallos = [c for c in cx if (c.p_used >= CORTE) != (c.y == 1)]
    asign: dict[str, list[Caso]] = defaultdict(list)
    for c in fallos:
        for clave, _ in CAUSAS:
            if tiene_causa(c, clave):
                asign[clave].append(c)
                break
    total = sum(abs(xp_prod(c, c.p_used) - xp_oraculo(c, c.y)) for c in fallos)
    tabla = []
    for clave, texto in CAUSAS:
        lista = asign.get(clave, [])
        pts = sum(abs(xp_prod(c, c.p_used) - xp_oraculo(c, c.y)) for c in lista)
        medible = [c for c in cx if tiene_causa(c, clave) is not None]
        con = [c for c in medible if tiene_causa(c, clave)]
        sin = [c for c in medible if not tiene_causa(c, clave)]
        k_con = sum(1 for c in con if (c.p_used >= CORTE) != (c.y == 1))
        k_sin = sum(1 for c in sin if (c.p_used >= CORTE) != (c.y == 1))
        t_con = k_con / len(con) if con else None
        t_sin = k_sin / len(sin) if sin else None
        ic_con, ic_sin = wilson(k_con, len(con)), wilson(k_sin, len(sin))
        separa = None
        if ic_con and ic_sin and clave != "sin_causa_conocida":
            separa = ic_con[0] > ic_sin[1] or ic_con[1] < ic_sin[0]
        fila = {
            "causa": clave,
            "texto": texto,
            "fallos": len(lista),
            "puntos_estructurales": r(pts, 2),
            "cuota": r(pts / total) if total else None,
            "medible": clave == "sin_causa_conocida" or bool(medible),
            "filas_con_causa": len(con),
            "tasa_fallo_con": r(t_con),
            "tasa_fallo_con_ic": ic_con,
            "tasa_fallo_sin": r(t_sin),
            "tasa_fallo_sin_ic": ic_sin,
            "se_separa_del_ruido": separa,
        }
        if separa is False and t_con is not None and t_sin is not None:
            fila["jornadas_necesarias"] = jornadas_para_proporciones(t_con, len(con), t_sin, len(con) / jornadas)
        tabla.append(fila)
    orden = sorted([t for t in tabla if t["causa"] != "sin_causa_conocida"], key=lambda t: -(t["puntos_estructurales"] or 0))
    return {
        "n_filas": len(cx),
        "n_fallos": len(fallos),
        "puntos_estructurales_de_fallos": r(total, 2),
        "banda_1_44_excluida": sum(1 for c in casos if c.tiene_xp2 and c.banda),
        "tabla": tabla,
        "top3": [t["causa"] for t in orden[:3] if t["fallos"] > 0],
        "notas": {
            "quinta_amarilla": f"No medible: las actas guardadas empiezan en la J{INICIO_ACTAS} y no se puede contar la amarilla acumulada desde la J1.",
            "recien_llegado": (
                f"En 26/27 las actas de la mayoría empiezan en la J{INICIO_ACTAS}: antes de la J{semana_recien_medible()} todo jugador "
                f"tiene menos de 3 partidos previos. Solo se mide desde la J{semana_recien_medible()}."
            ),
            "vuelta_de_lesion": "Las actas de 26/27 no traen «estado»: la vuelta de lesión no está en los datos (0 filas).",
            "cambio_de_entrenador": "Cambio de entrenador: no hay dato.",
            "club": "El club es el del partido (actas), no el actual.",
        },
    }


def medicion_4(casos: list[Caso], hist: list[Hist]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    yh = arr(hist, "y")
    ph = arr(hist, "p_prod")
    jh, mh = [h.pid for h in hist], [h.match_id for h in hist]
    out["historico"] = {
        "poblacion": "24/25 y 25/26, minutos de la ficha; otra población que la de actas",
        "n": len(hist),
        "jugadores": len(set(jh)),
        **bloque_prob(ph, yh, jh, mh),
    }
    # Regla ingenua: 1 si el partido anterior tuvo ≥ 45'.
    for nombre, pobl, p_ref, p_prev, y, jug, par in (
        ("historico", hist, ph, arr(hist, "p_prev"), yh, jh, mh),
        ("26_27", casos, arr(casos, "p_used"), np.array([1.0 if c.mins_prev[-1] >= 45 else 0.0 for c in casos]), arr(casos, "y"), *grupos(casos)),
    ):
        out[f"ingenua_{nombre}"] = {
            "brier_referencia": r(float(np.mean((p_ref - y) ** 2))),
            "brier_ingenua_0_1": r(float(np.mean((p_prev - y) ** 2))),
            "brier_ingenua_recortada": r(float(np.mean((np.clip(p_prev, 0.05, 0.95) - y) ** 2))),
            "delta_0_1_menos_ref": ic((p_prev - y) ** 2 - (p_ref - y) ** 2, jug, par),
            "delta_recortada_menos_ref": ic((np.clip(p_prev, 0.05, 0.95) - y) ** 2 - (p_ref - y) ** 2, jug, par),
        }
    # Aporte de la regla del portero, fuera de J9–J11.
    pt = [h for h in hist if h.slot == "PT"]
    out["regla_portero"] = {
        "historico_porteros": ic((arr(pt, "p_prod") - arr(pt, "y")) ** 2 - (arr(pt, "p_log") - arr(pt, "y")) ** 2, [h.pid for h in pt], [h.match_id for h in pt]),
    }
    pt26 = [c for c in casos if c.slot == "PT" and c.week not in VENTANA_PESOS and c.fuente_p == "logistica"]
    out["regla_portero"]["26_27_fuera_J9_J11_porteros"] = ic(
        (arr(pt26, "p_log_gk") - arr(pt26, "y")) ** 2 - (arr(pt26, "p_log") - arr(pt26, "y")) ** 2, *grupos(pt26)
    ) if pt26 else None
    out["regla_portero"]["nota"] = "Δ Brier con regla menos sin regla; negativo = la regla ayuda. Ya está en la referencia: no es señal nueva."

    # Señales nuevas, una forma fija cada una.
    cx = [c for c in casos if c.tiene_xp2]
    filas_por_jornada_26 = len(cx) / max(1, len({c.week for c in cx}))
    senales: dict[str, Any] = {}

    def mae_26(nuevo: dict[int, float], filas: list[Caso]) -> dict[str, Any] | None:
        sel = [c for c in filas if c.tiene_xp2 and id(c) in nuevo]
        if not sel:
            return None
        d = [abs(xp_prod(c, nuevo[id(c)]) - c.pts) - abs(xp_prod(c, c.p_used) - c.pts) for c in sel]
        return ic(d, *grupos(sel))

    def con_offset(x_hist: np.ndarray, x26: dict[int, float]) -> dict[str, Any]:
        off = logit(ph)
        keys = np.array([h.orden * 100 + h.week for h in hist])
        pred = np.full(len(hist), np.nan)
        for k in sorted(set(keys.tolist())):
            tr = keys < k
            if (x_hist[tr] > 0).sum() < 30:
                continue
            b = beta_offset(off[tr], x_hist[tr], yh[tr])
            te = keys == k
            pred[te] = sig(off[te] + b * x_hist[te])
        ev = ~np.isnan(pred)
        d_brier = (pred[ev] - yh[ev]) ** 2 - (ph[ev] - yh[ev]) ** 2
        res_b = ic(d_brier, [jh[i] for i in np.where(ev)[0]], [mh[i] for i in np.where(ev)[0]])
        b_final = beta_offset(off, x_hist, yh)
        nuevo = {}
        for c in casos:
            x = x26.get(id(c))
            if x is None:
                continue
            nuevo[id(c)] = float(sig(logit(np.array([c.p_used])) + b_final * x)[0])
        p26 = np.array([nuevo.get(id(c), c.p_used) for c in casos])
        y26 = arr(casos, "y")
        return {
            "n_activa_historico": int((x_hist > 0).sum()),
            "n_evaluado_historico": int(ev.sum()),
            "brier_historico": res_b,
            "coeficiente_congelado": r(b_final),
            "n_activa_26_27": int(sum(1 for c in casos if x26.get(id(c)))),
            "brier_26_27": ic((p26 - y26) ** 2 - (arr(casos, "p_used") - y26) ** 2, *grupos(casos)),
            "mae_xp_26_27": mae_26(nuevo, casos),
        }

    x_desc = np.array([1.0 if (h.descanso is not None and h.descanso <= 3) else 0.0 for h in hist])
    senales["descanso_3_o_menos"] = con_offset(x_desc, {id(c): (1.0 if c.descanso <= 3 else 0.0) for c in casos if c.descanso is not None})
    senales["descanso_3_o_menos"]["nota"] = "Histórico: descanso entre partidos de LaLiga. 26/27: calendario con Europa y Copa."
    x_rec = np.array([1.0 if h.n_prev < 3 else 0.0 for h in hist])
    senales["recien_llegado"] = con_offset(x_rec, {id(c): (1.0 if len(c.mins_prev) < 3 else 0.0) for c in casos if c.week >= semana_recien_medible()})
    senales["recien_llegado"]["nota"] = (
        "Histórico: menos de 3 filas previas en la temporada, que incluye el arranque de liga (J2–J3) además de fichajes. "
        f"26/27: solo desde la J{semana_recien_medible()}, porque las actas de la mayoría empiezan en la J{INICIO_ACTAS}."
    )
    # Sanción conocida: regla fija a 0. Solo hay tarjetas en las actas de 26/27.
    nuevo_s = {id(c): 0.0 for c in casos if c.roja_prev}
    p26 = np.array([nuevo_s.get(id(c), c.p_used) for c in casos])
    y26 = arr(casos, "y")
    senales["sancion_conocida"] = {
        "n_activa_26_27": len(nuevo_s),
        "titulares_entre_ellos": int(sum(c.y for c in casos if c.roja_prev)),
        "brier_26_27": ic((p26 - y26) ** 2 - (arr(casos, "p_used") - y26) ** 2, *grupos(casos)) if nuevo_s else None,
        "mae_xp_26_27": mae_26(nuevo_s, casos) if nuevo_s else None,
        "nota": (
            f"Solo roja o doble amarilla del acta anterior; la 5.ª/10.ª/15.ª amarilla no es medible (tarjetas desde la J{INICIO_ACTAS}). "
            "Sin muestra histórica. El sancionado no tiene acta la jornada siguiente, así que la cohorte casi nunca lo ve: ver «huecos»."
        ),
    }
    # Europa o Copa en 4 días: solo 26/27, jornada a jornada.
    sel = [c for c in casos if c.europa4 is not None]
    semanas = sorted({c.week for c in sel})
    nuevo_e: dict[int, float] = {}
    for w in semanas:
        tr = [c for c in sel if c.week < w]
        te = [c for c in sel if c.week == w]
        if sum(1 for c in tr if c.europa4) < 10:
            continue
        b = beta_offset(logit(arr(tr, "p_used")), np.array([1.0 if c.europa4 else 0.0 for c in tr]), arr(tr, "y"))
        for c in te:
            nuevo_e[id(c)] = float(sig(logit(np.array([c.p_used])) + b * (1.0 if c.europa4 else 0.0))[0])
    ev = [c for c in sel if id(c) in nuevo_e]
    senales["europa_o_copa_4_dias"] = {
        "n_activa_26_27": int(sum(1 for c in sel if c.europa4)),
        "jornadas_evaluadas": sorted({c.week for c in ev}),
        "n_evaluado": len(ev),
        "brier_26_27": ic([(nuevo_e[id(c)] - c.y) ** 2 - (c.p_used - c.y) ** 2 for c in ev], *grupos(ev)) if ev else None,
        "mae_xp_26_27": mae_26(nuevo_e, ev) if ev else None,
        "coeficiente_ultimo": None,
        "nota": "Solo hay calendario de 26/27: se ajusta con jornadas anteriores de 26/27 y la muestra es corta.",
    }
    if ev:
        tr = [c for c in sel if c.week < max(semanas)]
        senales["europa_o_copa_4_dias"]["coeficiente_ultimo"] = r(beta_offset(logit(arr(tr, "p_used")), np.array([1.0 if c.europa4 else 0.0 for c in tr]), arr(tr, "y")))

    filas_por_jornada_hist = len(hist) / max(1, len({(h.season, h.week) for h in hist}))
    for nombre, s in senales.items():
        grande = s.get("brier_historico") or s.get("brier_26_27")
        mae = s.get("mae_xp_26_27")
        gana_brier = bool(grande and grande["media"] is not None and grande["ic_jugador"][1] < 0 and grande["ic_partido"][1] < 0)
        baja_mae = bool(mae and mae["ic_jugador"][1] < 0 and mae["ic_partido"][1] < 0)
        s["mejora"] = gana_brier and baja_mae
        s["gana_brier"] = gana_brier
        s["baja_mae"] = baja_mae
        fpj = filas_por_jornada_hist if s.get("brier_historico") else len(casos) / max(1, len({c.week for c in casos}))
        s["jornadas_para_brier"] = None if gana_brier else jornadas_necesarias(grande, fpj)
        s["jornadas_para_mae"] = None if baja_mae else jornadas_necesarias(mae, filas_por_jornada_26)
    out["senales"] = senales
    out["citadas_11_nov"] = citar_11_nov()
    return out


def citar_11_nov() -> dict[str, Any]:
    ruta = cache_root() / "reajuste_titularidad.txt"
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return {"disponible": False}
    pat = re.compile(r"Brier\s+Δ ([+-]\d\.\d+)\s+jugador \[([^\]]+)\]\s+partido \[([^\]]+)\]")
    hall = pat.findall(texto)
    if len(hall) < 6:
        return {"disponible": False}

    def f(t):
        return {"delta": float(t[0]), "ic_jugador": [float(x) for x in t[1].split(",")], "ic_partido": [float(x) for x in t[2].split(",")]}

    return {
        "disponible": True,
        "fuente": ".cache/reajuste_titularidad.txt",
        "que": "racha, minutos recientes, k=5, J−1, hueco (+ rotación y reemplazo probados aparte): modelo walk-forward contra producción",
        "historico_24_25_25_26": f(hall[3]),
        "26_27_congelado": f(hall[5]),
        "veredicto": "ganó en 24/25+25/26 y perdió en 26/27; no se reajusta aquí",
        "otras_descartadas": "eventos/xG, Gradient FC, minutos dado titular y la ablación del 10 de noviembre: descartadas antes, no se repiten",
    }


def medicion_5(casos: list[Caso]) -> dict[str, Any]:
    sel = [c for c in casos if "ff" in c.pre and "af" in c.pre]
    out: dict[str, Any] = {"n_filas_con_ff_y_af": len(sel), "partidos": len({c.match_id for c in sel}), "jornadas": sorted({c.week for c in sel})}
    solo_ff = [c for c in casos if "ff" in c.pre]
    out["n_filas_con_ff"] = len(solo_ff)
    out["n_filas_con_af"] = sum(1 for c in casos if "af" in c.pre)
    if not sel:
        out["ganador"] = None
        return out
    y = arr(sel, "y")
    jug, par = grupos(sel)

    def gk(c: Caso, p: float, externa: bool = True) -> float:
        return portero(c.slot, c.mins_prev, c.weeks_prev, p, externa)

    ff = np.array([gk(c, c.pre["ff"].p) for c in sel])
    af = np.array([gk(c, c.pre["af"].p) for c in sel])
    media = np.array([gk(c, (c.pre["ff"].p + c.pre["af"].p) / 2) for c in sel])
    prod = np.array([gk(c, mezcla((c.pre["ff"].p, c.pre["ff"].status), (c.pre["af"].p, c.pre["af"].status))) for c in sel])
    logi = arr(sel, "p_log_gk")

    def regla(c: Caso) -> float:
        a, b = c.pre["ff"].p, c.pre["af"].p
        fuera = not (0.40 <= a <= 0.60) and not (0.40 <= b <= 0.60)
        if fuera and abs(a - b) < 0.15:
            return gk(c, mezcla((a, c.pre["ff"].status), (b, c.pre["af"].status)))
        return c.p_log_gk

    comb = np.array([regla(c) for c in sel])
    candidatos = {"ff_sola": ff, "af_sola": af, "media": media, "pico_si_titular_produccion": prod, "logistica": logi, "combinacion_preescrita": comb}
    tabla = {}
    for k, p in candidatos.items():
        tabla[k] = {
            "brier": r(float(np.mean((p - y) ** 2))),
            "acierto_0_50": acierto(p, y)["corte_0.50"],
            "delta_brier_vs_logistica": None if k == "logistica" else ic((p - y) ** 2 - (logi - y) ** 2, jug, par),
        }
    out["tabla"] = tabla
    # Diagnóstico, no candidato: AF con la lectura antigua del once oficial (0 para todos).
    af_old = np.array([gk(c, 0.0) if c.pre["af"].oficial else gk(c, c.pre["af"].p) for c in sel])
    out["diagnostico_af_lectura_antigua"] = {
        "filas_con_pagina_oficial": int(sum(1 for c in sel if c.pre["af"].oficial)),
        "brier": r(float(np.mean((af_old - y) ** 2))),
        "acierto_0_50": acierto(af_old, y)["corte_0.50"],
        "delta_brier_vs_logistica": ic((af_old - y) ** 2 - (logi - y) ** 2, jug, par),
        "nota": "No entra en la elección: es AF con el fallo de lectura de antes del arreglo.",
    }
    out["combinacion_usa_once_en"] = int(sum(1 for c in sel if not (0.40 <= c.pre["ff"].p <= 0.60) and not (0.40 <= c.pre["af"].p <= 0.60) and abs(c.pre["ff"].p - c.pre["af"].p) < 0.15))
    suficiente = len(sel) >= MIN_FUENTES_FILAS and out["partidos"] >= MIN_FUENTES_PARTIDOS
    out["muestra_suficiente"] = suficiente
    filas_por_jornada = len(sel) / max(1, len(out["jornadas"]))
    out["jornadas_para_200_filas"] = int(math.ceil(MIN_FUENTES_FILAS / filas_por_jornada)) if filas_por_jornada else None
    ganador = None
    if suficiente:
        mejores = [(v["brier"], k) for k, v in tabla.items()]
        b, k = min(mejores)
        d = tabla[k]["delta_brier_vs_logistica"]
        if k == "logistica" or (d and not d["cruza_cero"]):
            ganador = k
    out["ganador"] = ganador
    out["nota"] = "Todas pasan por la regla del portero, como en producción. Solo capturas anteriores al saque."
    return out


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------


def n(x: Any, d: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "sí" if x else "no"
    if isinstance(x, int):
        return f"{x:,}".replace(",", ".")
    return f"{x:.{d}f}".replace(".", ",")


def pct(x: Any, d: int = 1) -> str:
    return "—" if x is None else f"{100 * x:.{d}f} %".replace(".", ",")


def jtxt(j: int | None) -> str:
    if j is None:
        return "—"
    return "más de 100" if j >= TOPE_JORNADAS else f"~{j}"


def icx(res: dict | None, d: int = 3) -> str:
    if not res:
        return "—"
    s = f"{n(res['media'], d)} [jugador {n(res['ic_jugador'][0], d)}, {n(res['ic_jugador'][1], d)}; partido {n(res['ic_partido'][0], d)}, {n(res['ic_partido'][1], d)}]"
    return s


def informe(R: dict[str, Any]) -> str:
    L: list[str] = []
    C = R["como_se_estima"]
    m1, m2, m3, m4, m5 = R["medicion_1"], R["medicion_2"], R["medicion_3"], R["medicion_4"], R["medicion_5"]
    inv = R["inventario"]
    L.append("# Titularidad: cuánto acierta, cuánto cuesta y qué tocar\n")
    L.append(f"_Generado por `analizar.py` el {R['generado']}. Cada número sale de `resultados.json`._\n")
    L.append("## Cómo se estima hoy\n")
    w = C["pesos_logistica"]
    L.append(
        f"1. **Once probable.** FútbolFantasy (`data-probabilidad`) y Analítica Fantasy (`chance`). Se promedian; si alguna dice titular con pico ≥ {n(C['corte_duda'], 2)}, manda el pico. "
        f"El {n(C['af_sin_opinion'], 2)} exacto de AF se tira si FF está en ≤ {n(C['ff_definida_baja'], 2)} o ≥ {n(C['ff_definida_alta'], 2)}; si las dos dan ≤ {n(C['consenso_bajo'], 2)}, manda la menor."
    )
    L.append(
        f"2. **Sin once.** Logística de minutos: sesgo {n(w['bias'])}, temporada {n(w['season'])}, minutos {n(w['minutes'])}, recortada a [{n(C['recorte'][0], 2)}, {n(C['recorte'][1], 2)}]."
    )
    L.append(f"3. **Portero.** 0' en la última → {n(C['portero'][0], 2)}; ≥ 45' → {n(C['portero'][1], 2)}, salvo que el once diga claramente lo contrario.")
    L.append("4. **xP.** `p × xP_si_titular + (1 − p) × factor_banquillo × media_revulsivo`. El descuento de Copa/Europa no se aplica (`has_midweek_cup` llega en falso).\n")

    L.append("## Qué datos hay\n")
    sin_prev = sum(v for k, v in inv["actas_sin_previa"].items() if int(k) >= 8)
    L.append(
        f"- Actas con desglose: {n(inv['actas_jugadores'])} jugadores, jornadas "
        + ", ".join(f"J{j} ({v})" for j, v in inv["actas_por_jornada"].items())
        + f". La mayoría empieza en la J{inv['inicio_actas']}. Se mide J8–J12; {n(sin_prev)} filas de esas jornadas no tienen acta previa y quedan fuera. "
        f"Cohorte medible: {n(m1['lo_que_entro']['acierto']['n'])} jugador-partido."
    )
    cs = inv["control_saques"]
    if cs["jornadas_sin_10_partidos"]:
        L.append(
            f"- Hora de saque: jornadas con menos de 10 partidos con hora: {', '.join('J' + str(j) for j in cs['jornadas_sin_10_partidos'])}. "
            f"{n(inv['casos_sin_hora_de_saque'])} filas sin hora de saque usan la logística (no se les busca once)."
        )
    L.append(
        f"- **Onces guardados antes del saque**: la caché del scraper conserva {n(inv['paginas_ff'])} previas de FútbolFantasy y {n(inv['paginas_af'])} de Analítica Fantasy "
        f"(jornadas {', '.join('J' + str(j) for j in inv['jornadas_con_paginas'])}), además del registro diario desde el 7 de noviembre. "
        f"La probabilidad que entró sale del once en {n(m1['origen_de_p'].get('once', 0))} filas y de la logística en {n(m1['origen_de_p'].get('logistica', 0))}."
    )
    L.append(f"- Histórico 24/25 y 25/26: {n(m4['historico']['n'])} filas, {n(m4['historico']['jugadores'])} jugadores. Otra población: no se mezcla en las cifras de 26/27.")
    L.append(
        f"- Etiqueta: titular si jugó ≥ 45'. La logística reconstruida solo ve minutos desde la J{inv['inicio_actas']} (producción veía la temporada entera desde LaLiga); "
        "en las primeras jornadas medidas es una aproximación de lo que vio la app.\n"
    )
    mb = m1["mae_base"]
    L.append(
        f"MAE base del xP recalculado hoy: **{n(mb['mae'])}** en {n(mb['n'])} filas (referencia anterior {n(mb['referencia_anterior'], 2)}; la J8 {'entra' if mb['j8_entra'] else 'no entra'}). "
        f"La reconstrucción del xP coincide con la base: diferencia máxima {n(m1['reconstruccion_vs_base']['max_abs'])} en {n(m1['reconstruccion_vs_base']['n'])} filas."
    )
    xg = m1["xp_guardado_vs_recalculado"]
    if xg.get("n"):
        L.append(
            f"Contra el xP que la app guardó antes del saque ({n(xg['n'])} filas, J{', J'.join(str(j) for j in xg['jornadas'])}): diferencia media absoluta {n(xg['media_abs'])}, "
            f"correlación {n(xg['correlacion'])}, {pct(xg['pct_dif_mayor_0_5'])} con más de 0,5 puntos de diferencia. "
            + ("El recálculo no reproduce lo publicado: el techo se refiere al xP recalculado." if (xg["media_abs"] or 0) > 0.25 else "El recálculo reproduce lo publicado.")
            + "\n"
        )

    L.append("## 1. Precisión actual\n")
    a = m1["lo_que_entro"]["acierto"]
    c50 = a["corte_0.50"]
    L.append(
        f"De quienes tenían p ≥ 0,50, **{pct(c50['precision'])}** jugaron ≥ 45' (IC {pct(c50['precision_ic'][0])}–{pct(c50['precision_ic'][1])}, {n(c50['previstos_titular'])} previstos). "
        f"Al revés, de quienes jugaron ≥ 45', {pct(c50['sensibilidad'])} tenían p ≥ 0,50. Brier {icx(m1['lo_que_entro']['brier'])}.\n"
    )
    hs = m1["huecos_sensibilidad"]
    L.append(
        f"La cohorte solo ve a quien tiene acta. Hay {n(hs['n_huecos'])} jornadas sin acta entre dos actas del mismo jugador (no convocado, lesión, sanción); "
        f"{n(hs['huecos_con_p_0_50_o_mas'])} tenían p ≥ 0,50 por la logística. Contándolas como no titulares, la precisión baja a {pct(hs['precision_contando_huecos'])}.\n"
    )
    L.append("| Probabilidad | n | Precisión ≥ 0,50 | Sensibilidad | Precisión ≥ 0,70 | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for nombre, clave in (("Lo que entró (once o logística)", "lo_que_entro"), ("Logística sola", "logistica_sola"), ("Once solo (filas con once)", "once_solo"), ("Logística en esas mismas filas", "logistica_en_filas_con_once")):
        b = m1[clave]
        if not b.get("acierto"):
            continue
        aa = b["acierto"]
        L.append(f"| {nombre} | {n(aa['n'])} | {pct(aa['corte_0.50']['precision'])} | {pct(aa['corte_0.50']['sensibilidad'])} | {pct(aa['corte_0.70']['precision'])} | {n(b['brier']['media'])} |")
    sl = m1["sin_paginas_oficiales_af"]
    L.append(
        f"\nEn el conjunto, lo que entró da Brier {n(m1['lo_que_entro']['brier']['media'])} frente a {n(m1['logistica_sola']['brier']['media'])} de la logística sola "
        f"(con la lectura actual del once oficial de AF, ver «Hallazgo»). Sin las filas de once oficial ({n(sl['n'])}): {n(sl['brier_lo_que_entro'])} frente a {n(sl['brier_logistica'])}, "
        f"Δ {icx(sl['delta'], 4)}"
        + (", sin separarse del ruido. El once se separa de la logística cuando están FF y AF a la vez (sección 5)." if sl["delta"]["cruza_cero"] else ".")
    )
    s = m1["sin_J9_J11"]
    if s["lo_que_entro"].get("acierto"):
        L.append(
            f"\nSin las jornadas con que se ajustaron los pesos (queda {', '.join('J' + str(j) for j in s['jornadas'])}): precisión {pct(s['lo_que_entro']['acierto']['corte_0.50']['precision'])}, "
            f"Brier {n(s['lo_que_entro']['brier']['media'])} (logística sola {n(s['logistica_sola']['brier']['media'])})."
        )
    t = m1["tramo_alto_0_80"]
    L.append(
        f"\nTramo alto (p ≥ 0,80, el que entra en el once): {n(t['n'])} filas, {pct(t['frecuencia_titular'])} titulares (IC {pct(t['ic'][0]) if t['ic'] else '—'}–{pct(t['ic'][1]) if t['ic'] else '—'}); "
        f"{n(t['jugo_0'])} no jugaron y {n(t['jugo_1_44'])} jugaron 1–44'.\n"
    )
    L.append("Calibración de lo que entró (tramos con n < 30 no se leen):\n")
    L.append("| Tramo | n | p media | Frecuencia | IC |")
    L.append("|---|---:|---:|---:|---|")
    for tr in m1["lo_que_entro"]["calibracion"]["tramos"]:
        nota = "" if tr["se_lee"] else " (no se lee)"
        L.append(f"| {tr['tramo']} | {n(tr['n'])} | {n(tr['p_media'], 2)} | {pct(tr['frecuencia'])}{nota} | {pct(tr['ic'][0]) + '–' + pct(tr['ic'][1]) if tr['ic'] else '—'} |")
    L.append("\nPor puesto:\n")
    L.append("| Puesto | n | Precisión ≥ 0,50 | Brier |")
    L.append("|---|---:|---:|---:|")
    for k, v in m1["por_puesto"].items():
        L.append(f"| {k} | {n(v['n'])} | {pct(v['precision'])} | {n(v['brier'])} |")
    L.append("\nPor jornada:\n")
    L.append("| Jornada | n | Precisión ≥ 0,50 | Brier |")
    L.append("|---|---:|---:|---:|")
    for k, v in m1["por_jornada"].items():
        L.append(f"| J{k} | {n(v['n'])} | {pct(v['precision'])} | {n(v['brier'])} |")
    fu = m1["fuga_post_saque"]
    if fu.get("acierto"):
        L.append(
            f"\n**Fuga medida** (capturas guardadas después del saque de ese partido, {n(fu['acierto']['n'])} filas, jornadas {', '.join('J' + str(j) for j in fu['jornadas'])}): "
            f"precisión {pct(fu['acierto']['corte_0.50']['precision'])}, sensibilidad {pct(fu['acierto']['corte_0.50']['sensibilidad'])}, Brier {n(fu['brier']['media'])}; "
            f"quien fue titular tenía de media p = {n(fu['p_media_de_quien_fue_titular'], 2)}. Tras el saque las fuentes no suben a los titulares: los hunden. "
            "Es el mecanismo del fallo del 46 %. Clubes, tramos y antelación están en el JSON.\n"
        )

    L.append("## 2. Los dos techos\n")
    e, rz = m2["estructural"], m2["realizada"]
    L.append(
        f"Mismo xP condicional, solo cambia p ({n(m2['n_con_xp2'])} filas con xP 2.0; {n(m2['n_sin_xp2_fuera_del_techo'])} sin acta de titular previa quedan fuera, sin imputar).\n"
    )
    L.append(f"- **Estructural** (media de |xP(p) − xP(realidad)|, no depende de si marcó): **{icx(e)}** puntos por jugador y partido.")
    L.append(
        f"- **Realizada** (MAE con p menos MAE con la realidad): {icx(rz)}. MAE con p {n(m2['mae_xp_p'])}, con el oráculo {n(m2['mae_xp_oraculo'])}."
        + (" El intervalo cruza cero." if rz and rz["cruza_cero"] else "")
    )
    L.append(
        f"- Contra la logística sola en las mismas filas: MAE {n(m2['mae_xp_logistica_mismas_filas'])}; Δ (lo que entró − logística) {icx(m2['delta_mae_lo_que_entro_menos_logistica'])}."
    )
    pa = m2["por_acierto_del_corte"]
    L.append(
        f"- Filas en que el corte 0,50 acierta: {n(pa['acierta']['n'])}, MAE {n(pa['acierta']['mae_xp'])}. Falla: {n(pa['falla']['n'])}, MAE {n(pa['falla']['mae_xp'])}."
    )
    L.append("\n| Fallo | n | Puntos estructurales | Cuota del total |")
    L.append("|---|---:|---:|---:|")
    nombres = {
        "previsto_titular_y_jugo_0": "Previsto titular, jugó 0'",
        "previsto_titular_y_jugo_1_44": "Previsto titular, jugó 1–44' (minutos, no once)",
        "previsto_suplente_y_jugo_45_o_mas": "Previsto suplente, jugó ≥ 45'",
    }
    for k, v in m2["fallos_en_tres"].items():
        L.append(f"| {nombres[k]} | {n(v['n'])} | {n(v['puntos_estructurales'], 1)} | {pct(v['cuota_del_total'])} |")
    rec = m2["recuperable_con_once_perfecto"]
    L.append(
        f"\nUn once perfecto recuperaría {n(rec['puntos'], 1)} de {n(m2['puntos_estructurales_total'], 1)} puntos estructurales ({pct(rec['cuota'])}), "
        f"{n(rec['por_fila_del_total'])} por jugador y partido. El resto es la probabilidad intermedia de los aciertos y la banda de 1–44'.\n"
    )

    L.append("## 3. Las causas que más puntos cuestan\n")
    L.append(f"{n(m3['n_fallos'])} fallos del corte 0,50 en {n(m3['n_filas'])} filas (banda 1–44' aparte: {n(m3['banda_1_44_excluida'])}). Una causa por fallo, en orden.\n")
    L.append("| Causa | Fallos | Puntos | Cuota | Tasa de fallo con / sin | ¿Se separa del ruido? |")
    L.append("|---|---:|---:|---:|---|---|")
    for t in m3["tabla"]:
        if not t["medible"]:
            L.append(f"| {t['texto']} | — | — | — | no medible | — |")
            continue
        sep = "—" if t["se_separa_del_ruido"] is None else ("sí" if t["se_separa_del_ruido"] else (f"no (harían falta {jtxt(t['jornadas_necesarias'])} jornadas)" if t.get("jornadas_necesarias") else "no"))
        L.append(
            f"| {t['texto']} | {n(t['fallos'])} | {n(t['puntos_estructurales'], 1)} | {pct(t['cuota'])} | {pct(t['tasa_fallo_con'])} / {pct(t['tasa_fallo_sin'])} | {sep} |"
        )
    L.append("\nTres primeras por puntos: " + (", ".join(next(x["texto"] for x in m3["tabla"] if x["causa"] == k) for k in m3["top3"]) or "ninguna con fallos") + ".")
    for k, v in m3["notas"].items():
        L.append(f"- {v}")
    L.append("")

    L.append("## 4. Señales: qué mejora y qué no\n")
    L.append("Referencia: la probabilidad de producción. Una señal solo mejora si el Brier baja con intervalo fuera de cero en la muestra grande **y**, congelada, baja el MAE del xP en 26/27.\n")
    L.append("| Señal | Activa (hist. / 26/27) | Δ Brier muestra grande | Δ MAE xP 26/27 | ¿Mejora? |")
    L.append("|---|---|---|---|---|")
    for k, sg in m4["senales"].items():
        grande = sg.get("brier_historico") or sg.get("brier_26_27")
        act = f"{n(sg.get('n_activa_historico'))} / {n(sg.get('n_activa_26_27'))}"
        extra = ""
        if not sg["mejora"]:
            js = [x for x in (sg.get("jornadas_para_brier"), sg.get("jornadas_para_mae")) if x]
            extra = f" ({jtxt(max(js))} jornadas para salir del ruido)" if js else ""
        L.append(f"| {k.replace('_', ' ')} | {act} | {icx(grande, 4)} | {icx(sg.get('mae_xp_26_27'))} | {'sí' if sg['mejora'] else 'no'}{extra} |")
    ci = m4["citadas_11_nov"]
    if ci.get("disponible"):
        L.append(
            f"| racha, k=5, J−1, hueco, rotación, reemplazo (11 nov, citado) | — | {n(ci['historico_24_25_25_26']['delta'], 4)} en 24/25+25/26 | "
            f"{n(ci['26_27_congelado']['delta'], 4)} de Brier en 26/27 | no |"
        )
        L.append(f"| {ci['otras_descartadas']} | — | — | — | no |")
    ih, i26 = m4["ingenua_historico"], m4["ingenua_26_27"]
    L.append(
        f"\nRegla ingenua (1 si el anterior tuvo ≥ 45'): en el histórico Brier {n(ih['brier_ingenua_0_1'])} (0/1) y {n(ih['brier_ingenua_recortada'])} (recortada) frente a {n(ih['brier_referencia'])}; "
        f"en 26/27 {n(i26['brier_ingenua_0_1'])} y {n(i26['brier_ingenua_recortada'])} frente a {n(i26['brier_referencia'])}."
    )
    rp = m4["regla_portero"]
    L.append(
        f"Regla del portero (Δ Brier con regla menos sin ella): histórico {icx(rp['historico_porteros'], 4)}; 26/27 fuera de J9–J11 {icx(rp.get('26_27_fuera_J9_J11_porteros'), 4)}.\n"
    )
    for k, sg in m4["senales"].items():
        if sg.get("nota"):
            L.append(f"- {k.replace('_', ' ')}: {sg['nota']}")
    L.append("")

    L.append("## 5. Fuentes de once\n")
    if m5.get("tabla"):
        L.append(
            f"Filas con FF y AF antes del saque: {n(m5['n_filas_con_ff_y_af'])}, {n(m5['partidos'])} partidos, jornadas {', '.join('J' + str(j) for j in m5['jornadas'])}. "
            f"Mínimo para declarar ganador: {MIN_FUENTES_FILAS} filas y {MIN_FUENTES_PARTIDOS} partidos.\n"
        )
        L.append("| Fuente | Brier | Precisión ≥ 0,50 | Δ Brier vs logística |")
        L.append("|---|---:|---:|---|")
        for k, v in m5["tabla"].items():
            L.append(f"| {k.replace('_', ' ')} | {n(v['brier'])} | {pct(v['acierto_0_50']['precision'])} | {icx(v['delta_brier_vs_logistica'], 4)} |")
        if m5["ganador"]:
            L.append(f"\nGanador: **{m5['ganador'].replace('_', ' ')}**.")
        elif not m5["muestra_suficiente"]:
            L.append(
                f"\nSin ganador: muestra corta. Harían falta unas {m5['jornadas_para_200_filas']} jornadas con FF y AF guardados antes del saque "
                f"para llegar a 200 filas (hoy hay {len(m5['jornadas'])})."
            )
        else:
            L.append("\nSin ganador: ninguna se separa de la logística con intervalo fuera de cero.")
        dg = m5.get("diagnostico_af_lectura_antigua")
        if dg:
            L.append(
                f"\nDiagnóstico, fuera de la elección: AF sola con la lectura de antes del arreglo ({n(dg['filas_con_pagina_oficial'])} filas de página con once oficial) "
                f"daba Brier {n(dg['brier'])}; con la lectura actual, {n(m5['tabla']['af_sola']['brier'])}."
            )
    else:
        L.append("No hay filas con las dos fuentes antes del saque.")
    L.append("")

    oo = R["once_oficial_af"]
    L.append("## Hallazgo (arreglado): el once oficial de AF entraba como p = 0\n")
    L.append(oo["paginas_explicacion"] + "\n")
    if oo.get("produccion"):
        L.append(
            f"Filas cuya p salió de una de esas páginas: {n(oo['n'])} ({n(oo['partidos'])} partidos, jornadas {', '.join('J' + str(j) for j in oo['jornadas'])}); "
            f"{n(oo['titulares_oficiales'])} eran titulares oficiales y la lectura antigua les daba de media p = {n(oo['produccion']['p_media_titulares_oficiales'], 2)}.\n"
        )
        L.append("| Lectura | Brier | Precisión ≥ 0,50 | Sensibilidad |")
        L.append("|---|---:|---:|---:|")
        L.append(f"| Antes del arreglo (chance = 0) | {n(oo['produccion']['brier'])} | {pct(oo['produccion']['acierto_0_50']['precision'])} | {pct(oo['produccion']['acierto_0_50']['sensibilidad'])} |")
        L.append(f"| Ahora (esTitular como 1/0) | {n(oo['leido_como_once']['brier'])} | {pct(oo['leido_como_once']['acierto_0_50']['precision'])} | {pct(oo['leido_como_once']['acierto_0_50']['sensibilidad'])} |")
        L.append(f"\nΔ Brier (ahora − antes) {icx(oo['delta_brier'], 4)}. Δ MAE del xP {icx(oo.get('delta_mae_xp'))} en {n(oo.get('n_xp2'))} filas con xP 2.0.")
        L.append(oo["nota"] + "\n")
    else:
        L.append("Ninguna fila de la cohorte tomó su p de una de esas páginas.\n")

    L.append("## Qué implementar, con qué ganancia y qué no tocar\n")
    for linea in R["recomendacion"]:
        L.append(f"- {linea}")
    L.append("")
    return "\n".join(L)


def recomendar(R: dict[str, Any]) -> list[str]:
    m1, m2, m3, m4, m5 = (R[k] for k in ("medicion_1", "medicion_2", "medicion_3", "medicion_4", "medicion_5"))
    out = []
    oo = R["once_oficial_af"]
    if oo.get("delta_brier"):
        d = oo["delta_brier"]
        claro = d["ic_jugador"][1] < 0 and d["ic_partido"][1] < 0
        out.append(
            ("Arreglado:" if claro else "Arreglado, sin efecto claro:")
            + " la lectura del once oficial de AF (chance = 0 con esTitular) pasa a leer esTitular como 1/0. "
            f"Δ Brier {n(d['media'], 4)} en {n(oo['n'])} filas"
            + (f", Δ MAE del xP {n(oo['delta_mae_xp']['media'])}" if oo.get("delta_mae_xp") else "")
            + ("." if claro else "; el intervalo cruza cero.")
            + " Es un fallo de lectura, no una señal nueva."
        )
    buenas = [k for k, s in m4["senales"].items() if s["mejora"]]
    if buenas:
        for k in buenas:
            s = m4["senales"][k]
            out.append(f"Implementar «{k.replace('_', ' ')}»: Δ MAE {n(s['mae_xp_26_27']['media'])} puntos por jugador y partido en 26/27.")
    else:
        out.append("Ninguna señal nueva pasa los dos filtros (Brier en la muestra grande y MAE del xP en 26/27). No se implementa ninguna.")
    rec = m2["recuperable_con_once_perfecto"]
    out.append(
        f"Techo disponible: un once perfecto ahorraría {n(rec['por_fila_del_total'])} puntos estructurales por jugador y partido "
        f"(de {n(m2['estructural']['media'])} totales). Es el margen máximo de cualquier mejora de titularidad."
    )
    if m5.get("ganador") == "pico_si_titular_produccion":
        out.append("Fuente: la mezcla de producción (pico si titular) es la que mejor puntúa y se separa de la logística. No cambiarla.")
    elif m5.get("ganador"):
        out.append(f"Fuente: {m5['ganador'].replace('_', ' ')} puntúa mejor que la mezcla de producción y se separa de la logística; revisar la mezcla.")
    elif not m5.get("muestra_suficiente"):
        out.append(f"Fuentes: no cambiar la mezcla hasta tener ~{m5.get('jornadas_para_200_filas')} jornadas de onces guardados antes del saque.")
    else:
        out.append("Fuentes: no cambiar la mezcla; ninguna variante se separa de forma clara.")
    js = R["inventario"]["jornadas_con_paginas"]
    out.append(
        "Guardar el once antes de cada saque (FF y AF por partido, con hora) es lo que hace medible todo lo anterior: "
        f"hoy solo hay {len(js)} jornadas reconstruibles desde la caché ({', '.join('J' + str(j) for j in js)})."
    )
    out.append("No tocar: pesos de la logística, regla del portero, ajustes por club y las señales del 11 de noviembre.")
    return out


def main() -> int:
    cache = cache_root()
    casos, notas, md = construir_casos(cache)
    actas = ax.actas_en_cache()
    cat = catalogo(cache, actas)
    caps_pag, inv_pag = capturas_paginas(cache, md, cat)
    caps_reg, xp_guardado = capturas_registro(cache)
    asignar_onces(casos, caps_pag + caps_reg)
    filas_base, _, _ = ax.construir_filas([8, 9, 10, 11, 12], min_prior=1)
    base_xp, _ = ax.correr(filas_base, ax.Config("base"))
    hist, notas_hist = filas_historicas(cache)

    pesos = ptm.DEFAULT_WEIGHTS
    try:
        pesos = json.loads((cache / "p_titular_pesos.json").read_text(encoding="utf-8"))["weights"]
    except (OSError, ValueError, KeyError):
        pass
    actas_semana = Counter(int(w) for e in actas.values() for w in (e.get("weeks") or {}))
    R: dict[str, Any] = {
        "generado": datetime.now(MADRID).strftime("%Y-%m-%d %H:%M"),
        "como_se_estima": {
            "pesos_logistica": pesos,
            "recorte": [0.05, 0.95],
            "portero": [0.03, 0.95],
            "corte_duda": fs.DOUBT_BELOW,
            "af_sin_opinion": 0.50,
            "ff_definida_baja": 0.25,
            "ff_definida_alta": 0.75,
            "consenso_bajo": 0.20,
            "factor_banquillo": xp2.FACTOR_BANQUILLO,
        },
        "inventario": {
            "actas_jugadores": len(actas),
            "actas_por_jornada": {str(k): v for k, v in sorted(actas_semana.items())},
            "actas_sin_previa": notas["actas_sin_acta_previa_por_jornada"],
            "paginas_ff": sum(1 for x in inv_pag if x["fuente"] == "ff" and x.get("jornada")),
            "paginas_af": sum(1 for x in inv_pag if x["fuente"] == "af" and x.get("jornada")),
            "paginas_sin_partido_reconocido": sum(1 for x in inv_pag if not x.get("jornada")),
            "jornadas_con_paginas": sorted({x["jornada"] for x in inv_pag if x.get("jornada") and x["jornada"] >= 8}),
            "jornadas_con_paginas_fuera_de_la_medicion": sorted({x["jornada"] for x in inv_pag if x.get("jornada") and x["jornada"] < 8}),
            "paginas": inv_pag,
            "capturas_registro": dict(Counter(c.fuente for c in caps_reg)),
            "otras_tablas": "pre_lock_snapshots: solo J13 (sin jugar); previa_snapshots y top4_forecasts: 3 y 1 filas; responses: sin onces.",
            "control_saques": notas["control_saques"],
            "casos_sin_hora_de_saque": notas["casos_sin_hora_de_saque"],
            "casos_sin_calendario_de_club": notas["casos_sin_calendario_de_club"],
            "inicio_actas": notas["inicio_actas"],
            "historico": notas_hist,
            "estado_en_actas_26_27": 0,
        },
    }
    R["medicion_1"] = medicion_1(casos, filas_base, base_xp, xp_guardado, notas["huecos"])
    R["medicion_2"] = medicion_2(casos)
    R["medicion_3"] = medicion_3(casos)
    R["medicion_4"] = medicion_4(casos, hist)
    R["medicion_5"] = medicion_5(casos)
    R["once_oficial_af"] = medicion_once_oficial(casos)
    R["recomendacion"] = recomendar(R)
    (AQUI / "resultados.json").write_text(json.dumps(R, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (AQUI / "INFORME.md").write_text(informe(R), encoding="utf-8")
    print(f"casos {len(casos)}  histórico {len(hist)}  capturas página {len(caps_pag)}  registro {len(caps_reg)}")
    print(f"escrito {AQUI / 'resultados.json'} y INFORME.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

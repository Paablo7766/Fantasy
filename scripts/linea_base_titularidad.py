"""Línea base de P(titular): lo que hoy entra en el xP, contra dos reglas ingenuas.

Reutiliza el bootstrap pareado por bloques de ``scripts/ablacion_xp.py``.
No ajusta nada. La etiqueta es la de producción: titular si jugó ≥ 45 minutos.

    python scripts/linea_base_titularidad.py
"""

from __future__ import annotations

import csv
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ablacion_xp as ax  # noqa: E402
from toolbox.cache import cache_root  # noqa: E402
from toolbox.engine import p_titular_model as ptm  # noqa: E402
from toolbox.engine.xp2 import prob_titular_portero  # noqa: E402
from toolbox.engine.xp_calculator import FantasyXPEngine, PartidoHistorico, canonical_slot  # noqa: E402
from toolbox.matching import canonical_position, normalize_club  # noqa: E402
from toolbox.player_history import actas_en_cache  # noqa: E402
from toolbox.season_history import leer_almacen, temporada_coherente  # noqa: E402
from toolbox.understat import parse_openfootball_matchdays  # noqa: E402

MADRID = ZoneInfo("Europe/Madrid")
LONDON = ZoneInfo("Europe/London")
EPS = 1e-6
# Pesos vigentes salen de J9–J11 de 26/27. Esas jornadas no son fuera de muestra.
VENTANA_AJUSTE = {9, 10, 11}
TEMPORADA_ACTUAL = "26/27"
MESES = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}
_FECHA = re.compile(
    r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Za-z]{3})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$"
)
_HORA = re.compile(r"^\s+(\d{1,2}):(\d{2})\s+(.+)$")
_MARCADOR = re.compile(r"\s+\d+\s*-\s*\d+.*$")


@dataclass
class Caso:
    pid: str
    season: str
    week: int
    slot: str
    y: float
    p_logit: float
    p_prod: float
    p_prev: float
    p_k5: float
    n_prev: int
    match_id: str


def _slot(posicion: str | None) -> str:
    canon = canonical_position(posicion) or posicion
    return canonical_slot(canon)


def _prob_historial(minutos: list[float], jornadas: list[int]) -> float:
    """La logística de producción, con el mismo recorte [0,05, 0,95]."""
    historial = [
        PartidoHistorico(puntos=0.0, minutos=int(m), jornada=j)
        for m, j in zip(minutos, jornadas)
    ]
    p = FantasyXPEngine.prob_titular_heuristica(historial)
    if p is None:
        raise RuntimeError("la heurística no devolvió probabilidad con historial no vacío")
    return float(p)


def _prob_portero(slot: str, minutos: list[float], jornadas: list[int], p_logit: float) -> float:
    """Regla de portero de producción. Sin ``player_id``: no relee actas futuras."""
    if slot != "PT":
        return p_logit
    player = {
        "position": "POR",
        "p_titular": p_logit,
        "historial": [
            {
                "jornada": j,
                "minutos": m,
                "puntos": 0,
                "desglose": {"puntos": {}, "cantidades": {}},
            }
            for m, j in zip(minutos, jornadas)
        ],
    }
    return float(prob_titular_portero(player, p_logit))


def _caso(
    pid: str,
    season: str,
    week: int,
    slot: str,
    minutos_prev: list[float],
    jornadas_prev: list[int],
    y: float,
    match_id: str,
) -> Caso:
    p_logit = _prob_historial(minutos_prev, jornadas_prev)
    arr = [1.0 if m >= ptm.STARTER_MINUTES else 0.0 for m in minutos_prev]
    return Caso(
        pid=pid,
        season=season,
        week=week,
        slot=slot,
        y=y,
        p_logit=p_logit,
        p_prod=_prob_portero(slot, minutos_prev, jornadas_prev, p_logit),
        p_prev=arr[-1],
        p_k5=float(np.mean(arr[-5:])),
        n_prev=len(arr),
        match_id=match_id,
    )


def casos_temporada_actual(partidos: dict) -> tuple[list[Caso], dict[str, int]]:
    """Cada jugador-jornada con al menos un acta anterior. Minutos oficiales."""
    casos: list[Caso] = []
    notas = {"sin_partido": 0, "jugadores": 0}
    for pid, entry in actas_en_cache().items():
        weeks = {int(k): v for k, v in (entry.get("weeks") or {}).items()}
        if not weeks:
            continue
        notas["jugadores"] += 1
        slot = _slot(entry.get("position"))
        club = ax._club(entry.get("team"))
        orden = sorted(weeks)
        for i, t in enumerate(orden):
            if i == 0:
                continue
            previos = orden[:i]
            minutos = [float(weeks[w][1]) for w in previos]
            y = 1.0 if float(weeks[t][1]) >= ptm.STARTER_MINUTES else 0.0
            partido = partidos.get((club, t))
            if partido is None:
                notas["sin_partido"] += 1
                rival = "?"
            else:
                rival = partido.rival
            a, b = sorted((club, rival))
            casos.append(_caso(pid, TEMPORADA_ACTUAL, t, slot, minutos, previos, y, f"{t}:{a}|{b}"))
    return casos, notas


def casos_historicos() -> tuple[list[Caso], dict[str, int]]:
    """24/25 y 25/26, solo temporadas coherentes. Minutos estimados de la ficha."""
    casos: list[Caso] = []
    notas = {"slugs": 0, "temporadas": 0, "sin_partido": 0, "posicion_vacia": 0}
    for slug, entrada in leer_almacen().items():
        notas["slugs"] += 1
        slot = _slot(entrada.get("posicion"))
        if not entrada.get("posicion"):
            notas["posicion_vacia"] += 1
        for nombre, temp in (entrada.get("temporadas") or {}).items():
            if not temporada_coherente(temp, nombre):
                continue
            notas["temporadas"] += 1
            filas = [f for f in (temp.get("filas") or []) if f.get("minutos") is not None and f.get("j") is not None]
            filas.sort(key=lambda f: int(f["j"]))
            for i, fila in enumerate(filas):
                if i == 0:
                    continue
                previos = filas[:i]
                minutos = [float(f["minutos"]) for f in previos]
                jornadas = [int(f["j"]) for f in previos]
                y = 1.0 if float(fila["minutos"]) >= ptm.STARTER_MINUTES else 0.0
                eqs = [normalize_club(x) for x in (fila.get("equipos") or []) if x]
                if len(eqs) >= 2:
                    match = f"{nombre}:{int(fila['j'])}:{'|'.join(sorted(eqs[:2]))}"
                else:
                    notas["sin_partido"] += 1
                    match = f"{nombre}:{int(fila['j'])}:{slug}"
                casos.append(_caso(slug, nombre, int(fila["j"]), slot, minutos, jornadas, y, match))
    return casos, notas


def _clip(p: np.ndarray) -> np.ndarray:
    return np.clip(p, EPS, 1.0 - EPS)


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    pc = _clip(p)
    return float(-np.mean(y * np.log(pc) + (1.0 - y) * np.log(1.0 - pc)))


def suavizar_duro(p: np.ndarray) -> np.ndarray:
    """La regla 0/1, recortada al mismo rango que la logística de producción."""
    return np.where(p >= 0.5, 0.95, 0.05)


def resumen(casos: list[Caso]) -> dict[str, float]:
    y = np.array([c.y for c in casos])
    cols = {
        "prod": np.array([c.p_prod for c in casos]),
        "logit": np.array([c.p_logit for c in casos]),
        "prev": np.array([c.p_prev for c in casos]),
        "k5": np.array([c.p_k5 for c in casos]),
    }
    out: dict[str, float] = {
        "n": float(len(casos)),
        "tasa": float(y.mean()) if len(casos) else float("nan"),
        "n_k5": float(sum(1 for c in casos if c.n_prev >= 5)),
        "n_pt": float(sum(1 for c in casos if c.slot == "PT")),
    }
    for nombre, p in cols.items():
        out[f"brier_{nombre}"] = brier(p, y)
        out[f"ll_{nombre}"] = logloss(p, y)
    out["ll_prev_suave"] = logloss(suavizar_duro(cols["prev"]), y)
    out["brier_prev_suave"] = brier(suavizar_duro(cols["prev"]), y)
    # Moneda con la tasa de la propia muestra: solo para leer el Brier, no es un modelo.
    out["brier_tasa"] = float(y.mean() * (1.0 - y.mean())) if len(casos) else float("nan")
    return out


def _delta_boot(casos: list[Caso], loss_a: np.ndarray, loss_b: np.ndarray) -> dict[str, float]:
    """IC 95 % de media(loss_a − loss_b). Negativo: A mejor que B."""
    d = loss_a - loss_b
    rng_j = np.random.default_rng(ax.SEED)
    rng_p = np.random.default_rng(ax.SEED)
    ic_j = ax._cluster_boot(d, [c.pid for c in casos], rng_j)
    ic_p = ax._cluster_boot(d, [c.match_id for c in casos], rng_p)
    return {
        "delta": float(d.mean()),
        "ic_jug_lo": ic_j[0],
        "ic_jug_hi": ic_j[1],
        "ic_par_lo": ic_p[0],
        "ic_par_hi": ic_p[1],
    }


def perdidas(casos: list[Caso]) -> dict[str, dict[str, np.ndarray]]:
    y = np.array([c.y for c in casos])
    bruta = {
        "prod": np.array([c.p_prod for c in casos]),
        "logit": np.array([c.p_logit for c in casos]),
        "prev": np.array([c.p_prev for c in casos]),
        "k5": np.array([c.p_k5 for c in casos]),
        "prev_suave": suavizar_duro(np.array([c.p_prev for c in casos])),
    }
    out: dict[str, dict[str, np.ndarray]] = {}
    for nombre, p in bruta.items():
        out[nombre] = {
            "brier": (p - y) ** 2,
            "ll": -(y * np.log(_clip(p)) + (1.0 - y) * np.log(1.0 - _clip(p))),
        }
    return out


def comparar(casos: list[Caso]) -> list[tuple[str, str, dict[str, float]]]:
    loss = perdidas(casos)
    pares = (
        ("prod", "prev", "producción − titular en J-1"),
        ("prod", "k5", "producción − fracción últimos 5"),
        ("logit", "prev", "logística − titular en J-1"),
        ("logit", "k5", "logística − fracción últimos 5"),
        ("prod", "logit", "producción − logística (la regla de portero)"),
        ("logit", "prev_suave", "logística − J-1 recortada a [0,05, 0,95]"),
    )
    filas = []
    for a, b, etiqueta in pares:
        for metrica in ("brier", "ll"):
            filas.append((etiqueta, metrica, _delta_boot(casos, loss[a][metrica], loss[b][metrica])))
    return filas


def calibracion(p: np.ndarray, y: np.ndarray, cortes: list[float] | None = None) -> list[tuple[str, int, float, float]]:
    """Filas (etiqueta, n, media predicha, frecuencia observada)."""
    if cortes is None:
        bordes = [i / 10 for i in range(11)]
        filas = []
        for i in range(10):
            lo, hi = bordes[i], bordes[i + 1]
            if i < 9:
                m = (p >= lo) & (p < hi)
            else:
                m = (p >= lo) & (p <= hi)
            n = int(m.sum())
            if n == 0:
                filas.append((f"{lo:.1f}–{hi:.1f}", 0, float("nan"), float("nan")))
                continue
            filas.append((f"{lo:.1f}–{hi:.1f}", n, float(p[m].mean()), float(y[m].mean())))
        return filas
    filas = []
    for valor in cortes:
        m = np.isclose(p, valor)
        n = int(m.sum())
        if n == 0:
            continue
        filas.append((f"{valor:.2f}", n, float(p[m].mean()), float(y[m].mean())))
    return filas


def masa(p: np.ndarray, y: np.ndarray, valor: float, tol: float = 1e-9) -> tuple[int, float]:
    m = np.abs(p - valor) <= tol
    n = int(m.sum())
    return n, float(y[m].mean()) if n else float("nan")


def ece(filas: list[tuple[str, int, float, float]]) -> float:
    total = sum(n for _, n, _, _ in filas)
    if total == 0:
        return float("nan")
    return sum(n * abs(obs - pred) for _, n, pred, obs in filas if n and pred == pred) / total


# --- Cierres de jornada -------------------------------------------------------


def _saques_calendario(texto: str) -> list[tuple[int, str, str, datetime]]:
    """Partidos con hora explícita. La hora del fichero es la de Madrid."""
    jornada: int | None = None
    year: int | None = None
    month_prev = 0
    fecha: datetime | None = None
    salida: list[tuple[int, str, str, datetime]] = []
    for raw in texto.splitlines():
        cab = re.search(r"Matchday\s+(\d+)", raw, re.IGNORECASE)
        if cab:
            jornada = int(cab.group(1))
            fecha = None
            continue
        fecha_m = _FECHA.match(raw)
        if fecha_m:
            mes = MESES[fecha_m.group(1)]
            dia = int(fecha_m.group(2))
            if fecha_m.group(3):
                year = int(fecha_m.group(3))
            elif year is not None and mes < month_prev:
                year += 1
            month_prev = mes
            if year is None:
                continue
            fecha = datetime(year, mes, dia, tzinfo=MADRID)
            continue
        hora_m = _HORA.match(raw)
        if hora_m and jornada is not None and fecha is not None:
            cuerpo = _MARCADOR.sub("", hora_m.group(3))
            if " v " not in cuerpo:
                continue
            local, visita = cuerpo.split(" v ", 1)
            instante = fecha.replace(
                hour=int(hora_m.group(1)), minute=int(hora_m.group(2)), tzinfo=MADRID
            )
            salida.append((jornada, ax._club(local), ax._club(visita), instante))
    return salida


def _saques_csv(cache: Path, jornadas: dict[tuple[str, str], int]) -> list[tuple[int, str, str, datetime]]:
    """football-data.co.uk publica la hora de Londres, no la de Madrid."""
    ruta = cache / "football_data_raw_2627" / "SP1_2627.csv"
    salida: list[tuple[int, str, str, datetime]] = []
    with ruta.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            local, visita = ax._club(row["HomeTeam"]), ax._club(row["AwayTeam"])
            jornada = jornadas.get((local, visita))
            if jornada is None:
                continue
            reloj = datetime.strptime(f"{row['Date']} {row['Time']}", "%d/%m/%Y %H:%M").replace(tzinfo=LONDON)
            salida.append((jornada, local, visita, reloj))
    return salida


def _saques_cuotas(cache: Path, jornadas: dict[tuple[str, str], int]) -> tuple[list[tuple[int, str, str, datetime]], int]:
    """Hora del partido que trae la casa. Cierra la J12, que el calendario deja sin reloj."""
    conn = sqlite3.connect(cache / "responses.sqlite")
    sin_jornada = 0
    salida: list[tuple[int, str, str, datetime]] = []
    try:
        filas = conn.execute(
            "select match_key, kickoff from odds_snapshots where kickoff is not null"
        ).fetchall()
    finally:
        conn.close()
    vistos: set[tuple[int, str, str]] = set()
    for clave, kickoff in filas:
        local, _, visita = str(clave).partition("|")
        home, away = ax._club(local), ax._club(visita)
        jornada = jornadas.get((home, away))
        if jornada is None:
            sin_jornada += 1
            continue
        if (jornada, home, away) in vistos:
            continue
        vistos.add((jornada, home, away))
        salida.append((jornada, home, away, datetime.fromisoformat(str(kickoff))))
    return salida, sin_jornada


def cierres(cache: Path) -> tuple[dict[int, datetime], list[str]]:
    """Primer saque UTC de cada jornada, y un control de que Londres y Madrid coinciden."""
    texto = (cache / "laliga_2026_27.txt").read_text(encoding="utf-8")
    jornadas = parse_openfootball_matchdays(texto)
    cal = _saques_calendario(texto)
    csv_rows = _saques_csv(cache, jornadas)
    cuotas, cuotas_sueltas = _saques_cuotas(cache, jornadas)
    por_par_cal = {(j, h, a): dt for j, h, a, dt in cal}
    notas: list[str] = []
    deltas: list[float] = []
    for j, h, a, dt in csv_rows:
        otro = por_par_cal.get((j, h, a))
        if otro is None:
            continue
        deltas.append(abs((dt.astimezone(MADRID) - otro).total_seconds()))
    if deltas:
        peor = max(deltas)
        notas.append(
            f"Control de hora: {len(deltas)} partidos están en el calendario y en football-data; "
            f"la mayor diferencia Madrid−Londres es {peor / 60:.1f} min."
        )
        if peor > 120:
            raise SystemExit("La hora de cierre no cuadra entre fuentes. No mido señales contra un cierre dudoso.")
    else:
        notas.append("Control de hora: ningún partido coincidió entre calendario y football-data.")

    # football-data cubre lo ya jugado. El calendario, los partidos con hora escrita.
    # Las cuotas guardadas cierran la J12: el calendario la lista el domingo y sin reloj,
    # pero el primer partido (Sevilla–Alavés) fue el viernes.
    mejor: dict[tuple[int, str, str], datetime] = {}
    for j, h, a, dt in csv_rows:
        mejor[(j, h, a)] = dt
    for j, h, a, dt in cal:
        mejor.setdefault((j, h, a), dt)
    for j, h, a, dt in cuotas:
        mejor.setdefault((j, h, a), dt)
    primero: dict[int, datetime] = {}
    for (j, _, _), dt in mejor.items():
        utc = dt.astimezone(ZoneInfo("UTC"))
        if j not in primero or utc < primero[j]:
            primero[j] = utc
    if cuotas_sueltas:
        notas.append(f"Cuotas sin jornada reconocida: {cuotas_sueltas} partidos.")
    notas.append(
        "Cierres (primer saque, hora Madrid): "
        + ", ".join(
            f"J{j} {dt.astimezone(MADRID):%Y-%m-%d %H:%M}" for j, dt in sorted(primero.items()) if j <= 14
        )
    )
    return primero, notas


def cobertura(cache: Path, primero: dict[int, datetime]) -> list[str]:
    """Cuántas jornadas tienen cada señal guardada antes de su primer saque."""
    # Por reloj, no por número: la J6 arrancó el 3 de septiembre, antes que la J4 y la J5.
    orden = sorted(primero, key=lambda j: primero[j])
    jugadas = [j for j in orden if j <= 12]
    lineas = [
        "Una señal cuenta para la jornada cuyo primer saque es el siguiente. "
        "El corte es ese saque, no el número de jornada: hay jornadas que se solapan."
    ]

    def ventana(j: int) -> tuple[float, float]:
        anteriores = [primero[k] for k in orden if primero[k] < primero[j]]
        inicio = max(anteriores).timestamp() if anteriores else 0.0
        return inicio, primero[j].timestamp()

    conn = sqlite3.connect(cache / "responses.sqlite")
    try:
        consultas = {
            "Alineación FútbolFantasy (p_titular_ff)": (
                "select stored_at from player_signal_log where p_titular_ff is not null"
            ),
            "Alineación Analítica Fantasy (p_titular_af)": (
                "select stored_at from player_signal_log where p_titular_af is not null"
            ),
            "p_titular que vio la app (p_titular_final)": (
                "select stored_at from player_signal_log where p_titular_final is not null"
            ),
            "Cuotas de partido (odds_snapshots)": "select stored_at from odds_snapshots",
            "Cuotas de goleador (scorer_odds_snapshots)": "select stored_at from scorer_odds_snapshots",
            "Precios (price_snapshots)": "select stored_at from price_snapshots",
        }
        for nombre, sql in consultas.items():
            marcas = [float(r[0]) for r in conn.execute(sql)]
            con_dato: list[str] = []
            for j in jugadas:
                lo, hi = ventana(j)
                n = sum(1 for t in marcas if lo <= t < hi)
                if n:
                    con_dato.append(f"J{j} ({n} filas)")
            futuras = []
            for j in sorted(primero):
                if j in jugadas or j > 16:
                    continue
                lo, hi = ventana(j)
                n = sum(1 for t in marcas if lo <= t < hi)
                if n:
                    futuras.append(f"J{j} ({n} filas, aún sin jugar)")
            lineas.append(
                f"{nombre}: {len(con_dato)} jornadas ya jugadas"
                + (f" — {', '.join(con_dato)}" if con_dato else " — ninguna")
                + (f". Además {', '.join(futuras)}" if futuras else "")
            )
        span = conn.execute("select min(day), max(day), count(*) from player_signal_log").fetchone()
        lineas.append(
            f"El registro de señales va del {span[0]} al {span[1]} ({span[2]} filas). "
            "Antes de esa fecha la app no guardó la titularidad con hora."
        )
        if 12 in primero:
            primera = conn.execute(
                "select min(stored_at) from player_signal_log where p_titular_ff is not null"
            ).fetchone()[0]
            cierre = primero[12]
            if primera is not None:
                cuando = datetime.fromtimestamp(float(primera), ZoneInfo("UTC")).astimezone(MADRID)
                lineas.append(
                    f"La primera alineación de FútbolFantasy guardada es del {cuando:%Y-%m-%d %H:%M} hora Madrid. "
                    f"El primer partido de la J12 fue el {cierre.astimezone(MADRID):%Y-%m-%d %H:%M}. "
                    + (
                        "Esa captura es posterior al cierre: no vale para puntuar la J12."
                        if float(primera) >= cierre.timestamp()
                        else "Esa captura es anterior al cierre."
                    )
                )
            posteriores = conn.execute(
                "select count(*) from player_signal_log where p_titular_ff is not null and stored_at >= ?",
                (cierre.timestamp(),),
            ).fetchone()[0]
            lineas.append(
                f"Filas de alineación posteriores al cierre de la J12: {posteriores}. "
                "La J13 figura en el calendario el domingo 22 de noviembre, sin hora publicada: "
                "las capturas del 10 y el 11 de noviembre son anteriores a ese fin de semana y aún no tienen resultado."
            )
    finally:
        conn.close()
    return lineas


# --- Informe ------------------------------------------------------------------


def _fmt(fila: dict[str, float]) -> str:
    return (
        f"{int(fila['n']):6d}  {fila['tasa']:5.3f}  "
        f"{fila['brier_prod']:7.4f}  {fila['ll_prod']:7.4f}  "
        f"{fila['brier_logit']:7.4f}  {fila['ll_logit']:7.4f}  "
        f"{fila['brier_prev']:7.4f}  {fila['ll_prev']:7.4f}  "
        f"{fila['brier_k5']:7.4f}  {fila['ll_k5']:7.4f}  "
        f"{fila['brier_tasa']:7.4f}"
    )


CABECERA = (
    f"{'universo':<28}{'n':>6}  {'tasa':>5}  "
    f"{'BrierP':>7}  {'llP':>7}  {'BrierL':>7}  {'llL':>7}  "
    f"{'BrierJ1':>7}  {'llJ1':>7}  {'BrierK5':>7}  {'llK5':>7}  {'BrierT':>7}"
)


def _veredicto(ic_lo: float, ic_hi: float) -> str:
    if ic_hi < 0:
        return "el primero es mejor"
    if ic_lo > 0:
        return "el segundo es mejor"
    return "el intervalo cruza el cero"


def bloque_comparacion(titulo: str, casos: list[Caso], lineas: list[str]) -> None:
    lineas.append("")
    lineas.append(titulo)
    lineas.append(
        f"{'contraste':<52}{'metrica':<8}{'Δ':>8}  {'IC95 jugador':<22}{'IC95 partido':<22}lectura"
    )
    for etiqueta, metrica, d in comparar(casos):
        jug = _veredicto(d["ic_jug_lo"], d["ic_jug_hi"])
        par = _veredicto(d["ic_par_lo"], d["ic_par_hi"])
        lectura = jug if jug == par else f"jugador: {jug}; partido: {par}"
        lineas.append(
            f"{etiqueta:<52}{metrica:<8}{d['delta']:+8.4f}  "
            f"[{d['ic_jug_lo']:+.4f},{d['ic_jug_hi']:+.4f}]  "
            f"[{d['ic_par_lo']:+.4f},{d['ic_par_hi']:+.4f}]  {lectura}"
        )


def bloque_calibracion(titulo: str, p: np.ndarray, y: np.ndarray, lineas: list[str]) -> None:
    filas = calibracion(p, y)
    lineas.append("")
    lineas.append(titulo + f"   error de calibración {ece(filas):.4f}")
    lineas.append(f"{'tramo':<10}{'n':>7}{'predicho':>10}{'observado':>11}{'hueco':>8}")
    for etiqueta, n, pred, obs in filas:
        if n == 0:
            lineas.append(f"{etiqueta:<10}{n:7d}{'-':>10}{'-':>11}")
            continue
        lineas.append(f"{etiqueta:<10}{n:7d}{pred:10.3f}{obs:11.3f}{obs - pred:+8.3f}")
    for valor in (0.03, 0.05, 0.95):
        n, tasa = masa(p, y, valor)
        if n:
            lineas.append(f"  masa exacta en {valor:.2f}: n={n}, sale titular el {tasa:.3f}")


def main() -> int:
    cache = cache_root()
    lineas: list[str] = []
    pesos = ptm.current_weights()
    lineas.append(
        "Pesos vigentes de la logística: "
        + ", ".join(f"{k}={pesos[k]:.3f}" for k in ("bias", "season", "minutes"))
        + ". Son los de defecto; el reajuste automático no los ha movido."
    )
    lineas.append(
        "P(titular) de producción, cuando no hay un once publicado: logística con la fracción "
        "de partidos ≥45' de la temporada y los minutos medios de las 3 últimas jornadas sobre 90', "
        "recortada a [0,05, 0,95]. Al portero se le aplica después la regla del último partido "
        "(0' → 0,03; titular → 0,95), salvo que una fuente de once diga lo contrario."
    )
    lineas.append(
        "Etiqueta: minutos ≥ 45. Las actas guardadas no traen un bit de «salió de inicio» distinto "
        "de los minutos. Quien sale y lo cambian antes del 45' cuenta como no titular."
    )

    primero, notas_hora = cierres(cache)
    lineas.extend(notas_hora)
    lineas.append("")
    lineas.append("=== Jornadas con señales guardadas antes del cierre ===")
    lineas.extend(cobertura(cache, primero))

    print("Cargando casos de 26/27…", flush=True)
    partidos = ax.cargar_partidos(cache)
    actual, notas_a = casos_temporada_actual(partidos)
    print(f"Cargando histórico ({notas_a['jugadores']} jugadores esta temporada)…", flush=True)
    historico, notas_h = casos_historicos()
    lineas.append("")
    lineas.append(
        f"26/27: {notas_a['jugadores']} jugadores en actas, {len(actual)} filas con pasado, "
        f"{notas_a['sin_partido']} sin partido localizado en el calendario."
    )
    lineas.append(
        f"Histórico coherente: {notas_h['temporadas']} temporadas de jugador, {len(historico)} filas, "
        f"{notas_h['sin_partido']} sin los dos equipos en la ficha, "
        f"{notas_h['posicion_vacia']} sin puesto."
    )

    def tomar(casos: list[Caso], pred) -> list[Caso]:
        return [c for c in casos if pred(c)]

    universos: list[tuple[str, list[Caso]]] = [
        ("26/27 todas", actual),
        ("26/27 fuera de J9–J11", tomar(actual, lambda c: c.week not in VENTANA_AJUSTE)),
        ("26/27 solo J9–J11 (ajuste)", tomar(actual, lambda c: c.week in VENTANA_AJUSTE)),
        ("26/27 con 5 previos", tomar(actual, lambda c: c.n_prev >= 5)),
        ("24/25", tomar(historico, lambda c: c.season == "laliga-24-25")),
        ("25/26", tomar(historico, lambda c: c.season == "laliga-25-26")),
        ("24/25+25/26", historico),
        ("24/25+25/26 con 5 previos", tomar(historico, lambda c: c.n_prev >= 5)),
        ("24/25+25/26 fuera de J8–J12", tomar(historico, lambda c: c.week < 8 or c.week > 12)),
    ]
    lineas.append("")
    lineas.append("=== Puntuación ===")
    lineas.append(
        "BrierP/llP = lo que entra en el xP (logística + regla de portero). "
        "BrierL/llL = logística sola. J1 = titular si lo fue en el partido anterior (0 o 1). "
        "K5 = fracción de titularidades en los últimos 5 (o en los que haya). "
        "BrierT = acertar siempre la tasa de esa muestra, solo como referencia. "
        "El log-loss recorta las probabilidades a [1e-6, 1-1e-6]: por eso el 0/1 queda muy penalizado."
    )
    lineas.append(CABECERA)
    for nombre, casos in universos:
        if len(casos) < 30:
            lineas.append(f"{nombre:<28}n={len(casos)} (demasiado pocas)")
            continue
        lineas.append(f"{nombre:<28}{_fmt(resumen(casos))}")

    lineas.append("")
    lineas.append("26/27 por jornada (la logística se ajustó con J9–J11):")
    lineas.append(CABECERA)
    for semana in sorted({c.week for c in actual}):
        sub = [c for c in actual if c.week == semana]
        marca = "  ajuste" if semana in VENTANA_AJUSTE else ""
        if len(sub) < 20:
            lineas.append(f"J{semana:<26}n={len(sub)}{marca}")
            continue
        lineas.append(f"{('J' + str(semana) + marca):<28}{_fmt(resumen(sub))}")

    # Contrastes donde hay muestra de verdad. El de J9–J11 se enseña aparte y no decide.
    bloque_comparacion("=== Bootstrap pareado: 24/25 + 25/26 (los pesos no vieron estas temporadas) ===", historico, lineas)
    fuera = tomar(actual, lambda c: c.week not in VENTANA_AJUSTE)
    if len(fuera) >= 50:
        bloque_comparacion("=== Bootstrap pareado: 26/27 fuera de J9–J11 ===", fuera, lineas)
    bloque_comparacion("=== Bootstrap pareado: 26/27 completa (J9–J11 son la muestra de ajuste) ===", actual, lineas)

    def vectores(casos: list[Caso]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return (
            np.array([c.p_prod for c in casos]),
            np.array([c.p_logit for c in casos]),
            np.array([c.y for c in casos]),
        )

    for nombre in ("24/25+25/26", "26/27 todas", "26/27 fuera de J9–J11"):
        casos = dict(universos)[nombre]
        p_prod, p_logit, y = vectores(casos)
        bloque_calibracion(f"Calibración de lo que entra en el xP — {nombre}", p_prod, y, lineas)
        bloque_calibracion(f"Calibración de la logística sola — {nombre}", p_logit, y, lineas)
        lineas.append("")
        lineas.append(f"Calibración de la fracción de los últimos 5 — {nombre} (solo quien ya tiene 5 partidos)")
        lineas.append(f"{'predicho':<10}{'n':>7}{'observado':>11}{'hueco':>8}")
        con5 = [c for c in casos if c.n_prev >= 5]
        y5 = np.array([c.y for c in con5])
        for etiqueta, n, pred, obs in calibracion(np.array([c.p_k5 for c in con5]), y5, [i / 5 for i in range(6)]):
            lineas.append(f"{etiqueta:<10}{n:7d}{obs:11.3f}{obs - pred:+8.3f}")
        lineas.append(f"Calibración de «titular en el partido anterior» — {nombre}")
        for etiqueta, n, pred, obs in calibracion(np.array([c.p_prev for c in casos]), y, [0.0, 1.0]):
            lineas.append(f"  dijo {etiqueta}: n={n}, salió el {obs:.3f}")

    # Comprobación: la regla de portero que puntúo es la función de producción.
    porteros = [c for c in actual if c.slot == "PT"][:8]
    if porteros:
        lineas.append("")
        lineas.append(
            f"Porteros en 26/27: {sum(1 for c in actual if c.slot == 'PT')} filas. "
            "La probabilidad de producción sale de prob_titular_portero, no de una copia."
        )

    destino = cache / "linea_base_titularidad.txt"
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lineas))
    print(f"\nInforme escrito en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

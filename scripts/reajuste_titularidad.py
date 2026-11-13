"""Reajuste de P(titular) con 24/25 y 25/26, y una sola lectura de 26/27.

No toca los pesos de producción. El bootstrap es el de ``scripts/ablacion_xp.py``.

    python scripts/reajuste_titularidad.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ablacion_xp as ax  # noqa: E402
from linea_base_titularidad import (  # noqa: E402
    EPS,
    TEMPORADA_ACTUAL,
    _prob_historial,
    _prob_portero,
    _slot,
    brier,
    calibracion,
    ece,
    logloss,
)
from toolbox.engine import p_titular_model as ptm  # noqa: E402
from toolbox.matching import normalize_club  # noqa: E402
from toolbox.player_history import actas_en_cache  # noqa: E402
from toolbox.season_history import leer_almacen, temporada_coherente  # noqa: E402

ORDEN = {"laliga-24-25": 0, "laliga-25-26": 1}
AUSENCIA_PREVIA = {"lesionado", "sancionado"}
GAP_TOPE = 12.0
L2 = 1.0


@dataclass
class Fila:
    pid: str
    season: str
    orden: int
    week: int
    slot: str
    club: str
    y: float
    match_id: str
    p_prod: float
    last_min: float
    # season, minutes, k5, j1, gap/12, pt, df, dl, rot, repl
    x: np.ndarray


def _minmax(z: np.ndarray) -> np.ndarray:
    return np.clip(z, -30.0, 30.0)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-_minmax(z)))


def fit_logit(x: np.ndarray, y: np.ndarray, *, l2: float = L2) -> np.ndarray:
    """Newton–Raphson. El ridge no toca el sesgo (columna 0)."""
    beta = np.zeros(x.shape[1])
    pen = np.full(x.shape[1], l2)
    pen[0] = 0.0
    for _ in range(30):
        p = _sigmoid(x @ beta)
        w = np.clip(p * (1.0 - p), 1e-6, None)
        hess = (x * w[:, None]).T @ x
        hess.flat[:: x.shape[1] + 1] += pen + 1e-6
        grad = x.T @ (p - y) + pen * beta
        step = np.linalg.solve(hess, grad)
        beta = beta - step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return beta


def _rasgos(jornadas: list[int], minutos: list[float], week: int, slot: str) -> np.ndarray:
    arr = np.array([1.0 if m >= ptm.STARTER_MINUTES else 0.0 for m in minutos], dtype=float)
    season = float(arr.mean()) if len(arr) else 0.0
    recent = minutos[-ptm.RECENT_GAMES :]
    minutes = float(np.mean([min(max(m, 0.0), 90.0) / 90.0 for m in recent])) if recent else 0.0
    k5 = float(arr[-5:].mean()) if len(arr) else 0.0
    j1 = 1.0 if any(j == week - 1 and m >= ptm.STARTER_MINUTES for j, m in zip(jornadas, minutos)) else 0.0
    previos = [j for j, m in zip(jornadas, minutos) if m >= ptm.STARTER_MINUTES and j < week]
    gap = GAP_TOPE if not previos else min(GAP_TOPE, float(week - max(previos)))
    pt = 1.0 if slot == "PT" else 0.0
    df = 1.0 if slot == "DF" else 0.0
    dl = 1.0 if slot == "DL" else 0.0
    return np.array([season, minutes, k5, j1, gap / GAP_TOPE, pt, df, dl, 0.0, 0.0])


def _prod(slot: str, minutos: list[float], jornadas: list[int]) -> float:
    p = _prob_historial(minutos, jornadas)
    return _prob_portero(slot, minutos, jornadas, p)


def _filas_historicas() -> list[Fila]:
    filas: list[Fila] = []
    for slug, entrada in leer_almacen().items():
        slot = _slot(entrada.get("posicion"))
        club = normalize_club(str(entrada.get("equipo") or ""))
        for nombre, temp in (entrada.get("temporadas") or {}).items():
            orden = ORDEN.get(nombre)
            if orden is None or not temporada_coherente(temp, nombre):
                continue
            crudas = [f for f in (temp.get("filas") or []) if f.get("j") is not None and f.get("minutos") is not None]
            crudas.sort(key=lambda f: int(f["j"]))
            for i, fila in enumerate(crudas):
                if i == 0:
                    continue
                previos = crudas[:i]
                minutos = [float(f["minutos"]) for f in previos]
                jornadas = [int(f["j"]) for f in previos]
                week = int(fila["j"])
                eqs = [normalize_club(x) for x in (fila.get("equipos") or []) if x]
                match = (
                    f"{nombre}:{week}:{'|'.join(sorted(eqs[:2]))}"
                    if len(eqs) >= 2
                    else f"{nombre}:{week}:{slug}"
                )
                filas.append(
                    Fila(
                        pid=slug,
                        season=nombre,
                        orden=orden,
                        week=week,
                        slot=slot,
                        club=club,
                        y=1.0 if float(fila["minutos"]) >= ptm.STARTER_MINUTES else 0.0,
                        match_id=match,
                        p_prod=_prod(slot, minutos, jornadas),
                        last_min=minutos[-1],
                        x=_rasgos(jornadas, minutos, week, slot),
                    )
                )
    filas.sort(key=lambda f: (f.orden, f.week, f.pid))
    return filas


def _aplicar_contexto(filas: list[Fila], apariciones: list[dict]) -> None:
    """Rotación del club y reemplazo, solo con jornadas ya jugadas.

    La rotación es el cambio del once entre los dos partidos anteriores.
    El reemplazo solo sube si el habitual de ese puesto está lesionado o
    sancionado en la ficha de esta jornada (se sabe antes del partido) y,
    en ausencias pasadas, este jugador fue quien ocupó el puesto.
    """
    por_club: dict[tuple[str, str, int], set[str]] = {}
    por_puesto: dict[tuple[str, str, str], list[dict]] = {}
    for a in apariciones:
        if a["minutos"] >= ptm.STARTER_MINUTES:
            por_club.setdefault((a["season"], a["club"], a["week"]), set()).add(a["pid"])
        por_puesto.setdefault((a["season"], a["club"], a["slot"]), []).append(a)

    rotacion: dict[tuple[str, str, int], float] = {}
    semanas: dict[tuple[str, str], list[int]] = {}
    for season, club, week in por_club:
        semanas.setdefault((season, club), []).append(week)
    for clave, ws in semanas.items():
        ws = sorted(set(ws))
        cambios: list[tuple[int, float]] = []
        for anterior, siguiente in zip(ws, ws[1:]):
            prev = por_club[(clave[0], clave[1], anterior)]
            nxt = por_club[(clave[0], clave[1], siguiente)]
            if len(prev) < 5:
                continue
            cambios.append((siguiente, 1.0 - len(prev & nxt) / len(prev)))
        for week, _rate in cambios:
            # El cambio que termina en una jornada se conoce al acabarla.
            # Para predecir esa misma jornada solo valen los cambios anteriores.
            previos = [rate for fin, rate in cambios if fin < week][-3:]
            if previos:
                rotacion[(clave[0], clave[1], week)] = float(np.mean(previos))

    reemplazo: dict[tuple[str, str, int], float] = {}
    for (season, club, slot), grupo in por_puesto.items():
        grupo.sort(key=lambda a: (a["week"], a["pid"]))
        semanas_puesto = sorted({a["week"] for a in grupo})
        por_semana: dict[int, list[dict]] = {}
        for a in grupo:
            por_semana.setdefault(a["week"], []).append(a)
        starts: dict[str, int] = {}
        ultimo: dict[str, int] = {}
        ausencias: dict[str, int] = {}
        habitual: str | None = None
        for week in semanas_puesto:
            presentes = por_semana[week]
            if habitual is not None:
                ficha = next((a for a in presentes if a["pid"] == habitual), None)
                estado = (ficha.get("estado") or "").strip().lower() if ficha else ""
                if estado in AUSENCIA_PREVIA and ausencias:
                    total = sum(ausencias.values()) or 1
                    for a in presentes:
                        if a["pid"] == habitual:
                            continue
                        reemplazo[(a["pid"], season, week)] = ausencias.get(a["pid"], 0) / total
                if ficha is None or ficha["minutos"] < ptm.STARTER_MINUTES:
                    for a in presentes:
                        if a["pid"] != habitual and a["minutos"] >= ptm.STARTER_MINUTES:
                            ausencias[a["pid"]] = ausencias.get(a["pid"], 0) + 1
            for a in presentes:
                if a["minutos"] >= ptm.STARTER_MINUTES:
                    starts[a["pid"]] = starts.get(a["pid"], 0) + 1
                    ultimo[a["pid"]] = week
            if starts:
                habitual = max(starts, key=lambda pid: (starts[pid], ultimo.get(pid, 0)))
    for fila in filas:
        fila.x[8] = rotacion.get((fila.season, fila.club, fila.week), 0.0)
        fila.x[9] = reemplazo.get((fila.pid, fila.season, fila.week), 0.0)


def _apariciones_historicas() -> list[dict]:
    apariciones = []
    for slug, entrada in leer_almacen().items():
        slot = _slot(entrada.get("posicion"))
        club = normalize_club(str(entrada.get("equipo") or ""))
        if not club:
            continue
        for nombre, temp in (entrada.get("temporadas") or {}).items():
            if nombre not in ORDEN or not temporada_coherente(temp, nombre):
                continue
            for fila in temp.get("filas") or []:
                if fila.get("j") is None or fila.get("minutos") is None:
                    continue
                apariciones.append(
                    {
                        "pid": slug,
                        "season": nombre,
                        "club": club,
                        "slot": slot,
                        "week": int(fila["j"]),
                        "minutos": float(fila["minutos"]),
                        "estado": fila.get("estado"),
                    }
                )
    return apariciones


_PARTIDOS_2627: dict = {}


def _filas_2627() -> list[Fila]:
    filas = []
    for pid, entry in actas_en_cache().items():
        weeks = {int(k): v for k, v in (entry.get("weeks") or {}).items()}
        if not weeks:
            continue
        slot = _slot(entry.get("position"))
        club = ax._club(entry.get("team"))
        ordenadas = sorted(weeks)
        for i, week in enumerate(ordenadas):
            if i == 0:
                continue
            previos = ordenadas[:i]
            minutos = [float(weeks[w][1]) for w in previos]
            partido = _PARTIDOS_2627.get((club, week))
            if partido is not None:
                a, b = sorted((club, partido.rival))
                match = f"{week}:{a}|{b}"
            else:
                match = f"26/27:{week}:{club}"
            filas.append(
                Fila(
                    pid=str(pid),
                    season=TEMPORADA_ACTUAL,
                    orden=2,
                    week=week,
                    slot=slot,
                    club=club,
                    y=1.0 if float(weeks[week][1]) >= ptm.STARTER_MINUTES else 0.0,
                    match_id=match,
                    p_prod=_prod(slot, minutos, previos),
                    last_min=minutos[-1],
                    x=_rasgos(previos, minutos, week, slot),
                )
            )
    return filas


def _matriz(filas: list[Fila], cols: list[int]) -> np.ndarray:
    datos = np.vstack([f.x for f in filas])
    return np.column_stack([np.ones(len(filas)), datos[:, cols]])


def walk_forward(filas: list[Fila], cols: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Predicción de cada jornada con los pesos ajustados solo en las anteriores."""
    x = _matriz(filas, cols)
    y = np.array([f.y for f in filas])
    clave = [(f.orden, f.week) for f in filas]
    oof_z = np.full(len(filas), np.nan)
    cortes = [0]
    for i in range(1, len(filas)):
        if clave[i] != clave[i - 1]:
            cortes.append(i)
    cortes.append(len(filas))
    # Las ocho primeras jornadas de 24/25 solo entrenan.
    for a, b in zip(cortes, cortes[1:]):
        if filas[a].orden == 0 and filas[a].week <= 8:
            continue
        if a < 500:
            continue
        beta = fit_logit(x[:a], y[:a])
        oof_z[a:b] = x[a:b] @ beta
    return oof_z, _sigmoid(oof_z)


def _delta(loss_a: np.ndarray, loss_b: np.ndarray, filas: list[Fila]) -> dict[str, float]:
    d = loss_a - loss_b
    rng_j = np.random.default_rng(ax.SEED)
    rng_p = np.random.default_rng(ax.SEED)
    ic_j = ax._cluster_boot(d, [f.pid for f in filas], rng_j)
    ic_p = ax._cluster_boot(d, [f.match_id for f in filas], rng_p)
    return {
        "delta": float(d.mean()),
        "jug_lo": ic_j[0],
        "jug_hi": ic_j[1],
        "par_lo": ic_p[0],
        "par_hi": ic_p[1],
    }


def _entra(res: dict[str, float]) -> bool:
    return res["jug_hi"] < 0 and res["par_hi"] < 0


def _perdida(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pc = np.clip(p, EPS, 1.0 - EPS)
    return (p - y) ** 2, -(y * np.log(pc) + (1.0 - y) * np.log(1.0 - pc))


def _regla_portero(filas: list[Fila], p: np.ndarray) -> np.ndarray:
    out = p.copy()
    for i, fila in enumerate(filas):
        if fila.slot != "PT":
            continue
        if fila.last_min == 0:
            out[i] = min(out[i], 0.03)
        elif fila.last_min >= ptm.STARTER_MINUTES:
            out[i] = max(out[i], 0.95)
    return out


def _fmt(res: dict[str, float]) -> str:
    return (
        f"Δ {res['delta']:+.4f}  jugador [{res['jug_lo']:+.4f}, {res['jug_hi']:+.4f}]"
        f"  partido [{res['par_lo']:+.4f}, {res['par_hi']:+.4f}]"
        f"  {'entra' if _entra(res) else 'no entra'}"
    )


def _catalogo_con_minutos() -> tuple[list[Fila], str]:
    """Segunda universo: el catálogo de la competición, si trae minutos."""
    try:
        from toolbox.net import LaligaClient, no_network

        with no_network():
            client = LaligaClient()
            try:
                crudo = client.players_document(fresh=False)
            finally:
                client.close()
    except Exception as exc:  # noqa: BLE001 — sin catálogo se dice y se sigue
        return [], f"catálogo no disponible ({exc.__class__.__name__})"
    if not crudo:
        return [], "el catálogo en caché está vacío"
    muestra = next((r for r in crudo if isinstance(r, dict)), {})
    master = muestra.get("playerMaster") if isinstance(muestra.get("playerMaster"), dict) else muestra
    stats = None
    for nodo in (master.get("lastStats") or []) if isinstance(master, dict) else []:
        if isinstance(nodo, dict) and isinstance(nodo.get("stats"), dict):
            stats = nodo["stats"]
            break
    if not isinstance(stats, dict) or "mins_played" not in stats:
        return [], (
            f"el catálogo tiene {len(crudo)} fichas y no trae minutos "
            "(solo puntos), así que no hay etiqueta de titular"
        )
    filas: list[Fila] = []
    for row in crudo:
        if not isinstance(row, dict):
            continue
        master = row.get("playerMaster") if isinstance(row.get("playerMaster"), dict) else row
        pid = str(master.get("id") or "")
        serie = master.get("lastStats")
        if not pid or not isinstance(serie, list):
            continue
        weeks: dict[int, float] = {}
        for nodo in serie:
            if not isinstance(nodo, dict) or not isinstance(nodo.get("weekNumber"), int):
                continue
            mins = (nodo.get("stats") or {}).get("mins_played") or [0]
            weeks[int(nodo["weekNumber"])] = float(mins[0] or 0) if isinstance(mins, list) else float(mins or 0)
        ordenadas = sorted(weeks)
        if len(ordenadas) < 2:
            continue
        slot = _slot({1: "POR", 2: "DEF", 3: "MC", 4: "DEL"}.get(master.get("positionId")))
        team = master.get("team") if isinstance(master.get("team"), dict) else {}
        club = ax._club(team.get("name") or master.get("teamId"))
        for i, week in enumerate(ordenadas):
            if i == 0:
                continue
            previos = ordenadas[:i]
            minutos = [weeks[w] for w in previos]
            filas.append(
                Fila(
                    pid=pid,
                    season=TEMPORADA_ACTUAL,
                    orden=2,
                    week=week,
                    slot=slot,
                    club=str(club),
                    y=1.0 if weeks[week] >= ptm.STARTER_MINUTES else 0.0,
                    match_id=f"26/27:{week}:{club}",
                    p_prod=_prod(slot, minutos, previos),
                    last_min=minutos[-1],
                    x=_rasgos(previos, minutos, week, slot),
                )
            )
    return filas, f"catálogo con minutos: {len({f.pid for f in filas})} jugadores, {len(filas)} filas"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    lineas: list[str] = []

    def out(texto: str = "") -> None:
        print(texto, flush=True)
        lineas.append(texto)

    from toolbox.cache import cache_root

    global _PARTIDOS_2627
    _PARTIDOS_2627 = ax.cargar_partidos(cache_root())
    out("Cargando 24/25 y 25/26…")
    filas = _filas_historicas()
    _aplicar_contexto(filas, _apariciones_historicas())
    out(f"filas {len(filas)}  jugadores {len({f.pid for f in filas})}  tasa {np.mean([f.y for f in filas]):.3f}")
    n_rot = sum(1 for f in filas if f.x[8] > 0)
    n_rep = sum(1 for f in filas if f.x[9] > 0)
    out(f"rotación conocida en {n_rot} filas · reemplazo (lesión o sanción del habitual) en {n_rep}")

    base = [0, 1, 2, 3, 4]
    out("Walk-forward del modelo con los cinco rasgos…")
    z_base, p_base = walk_forward(filas, base)
    mascara = ~np.isnan(z_base)
    visto = [f for f, m in zip(filas, mascara) if m]
    yv = np.array([f.y for f in visto])
    out(f"fuera de muestra {len(visto)}  Brier {brier(p_base[mascara], yv):.4f}  log-loss {logloss(p_base[mascara], yv):.4f}")

    def probar(nombre: str, cols: list[int], referencia: np.ndarray) -> tuple[bool, np.ndarray, np.ndarray]:
        out(f"Walk-forward con {nombre}…")
        z, p = walk_forward(filas, cols)
        m = ~np.isnan(z) & mascara
        sub = [f for f, flag in zip(filas, m) if flag]
        yy = np.array([f.y for f in sub])
        brier_d = _delta(_perdida(p[m], yy)[0], _perdida(referencia[m], yy)[0], sub)
        ll_d = _delta(_perdida(p[m], yy)[1], _perdida(referencia[m], yy)[1], sub)
        out(f"  Brier    {_fmt(brier_d)}")
        out(f"  log-loss {_fmt(ll_d)}")
        return _entra(ll_d), z, p

    entra_pos, z_pos, p_pos = probar("puesto", base + [5, 6, 7], p_base)
    cols = base + ([5, 6, 7] if entra_pos else [])
    ref_p = p_pos if entra_pos else p_base
    ref_z = z_pos if entra_pos else z_base
    entra_rot, z_rot, p_rot = probar("rotación del club", cols + [8], ref_p)
    if entra_rot:
        cols = cols + [8]
        ref_p, ref_z = p_rot, z_rot
    entra_rep, z_rep, p_rep = probar("grafo de reemplazos", cols + [9], ref_p)
    if entra_rep:
        cols = cols + [9]
        ref_p, ref_z = p_rep, z_rep
    out(f"rasgos congelados (columnas): {cols}")

    m = ~np.isnan(ref_z)
    oof = [f for f, flag in zip(filas, m) if flag]
    z_oof = ref_z[m]
    y_oof = np.array([f.y for f in oof])
    platt = fit_logit(np.column_stack([np.ones(len(z_oof)), z_oof]), y_oof, l2=0.0)
    p_cal = _sigmoid(platt[0] + platt[1] * z_oof)
    p_gk = _regla_portero(oof, p_cal)
    prod_oof = np.array([f.p_prod for f in oof])
    out("El modelo calibrado contra producción, en las mismas filas de 24/25+25/26:")
    out(f"  Brier modelo {brier(p_cal, y_oof):.4f}  producción {brier(prod_oof, y_oof):.4f}")
    out(f"  log-loss modelo {logloss(p_cal, y_oof):.4f}  producción {logloss(prod_oof, y_oof):.4f}")
    out(f"  Brier    {_fmt(_delta(_perdida(p_cal, y_oof)[0], _perdida(prod_oof, y_oof)[0], oof))}")
    out(f"  log-loss {_fmt(_delta(_perdida(p_cal, y_oof)[1], _perdida(prod_oof, y_oof)[1], oof))}")
    ll_gk = _delta(_perdida(p_gk, y_oof)[1], _perdida(p_cal, y_oof)[1], oof)
    br_gk = _delta(_perdida(p_gk, y_oof)[0], _perdida(p_cal, y_oof)[0], oof)
    out("Regla del portero sobre el modelo ya calibrado, en 24/25+25/26:")
    out(f"  Brier    {_fmt(br_gk)}")
    out(f"  log-loss {_fmt(ll_gk)}")
    usa_regla = _entra(ll_gk)
    out(f"la regla {'se mantiene' if usa_regla else 'no mejora al modelo'}")

    x_all = _matriz(filas, cols)
    y_all = np.array([f.y for f in filas])
    beta = fit_logit(x_all, y_all)
    etiquetas = ["sesgo", "temporada", "minutos", "k5", "j-1", "hueco", "pt", "df", "dl", "rot", "reemplazo"]
    etiquetas = [etiquetas[0]] + [etiquetas[c + 1] for c in cols]
    out("pesos " + ", ".join(f"{n}={v:+.3f}" for n, v in zip(etiquetas, beta)))
    out(f"calibración logit {platt[0]:+.3f} {platt[1]:+.3f}·z")

    def puntuar(nombre: str, universo: list[Fila], *, regla: bool) -> np.ndarray | None:
        if not universo:
            out(f"{nombre}: sin filas")
            return None
        x = _matriz(universo, cols)
        z = x @ beta
        p = _sigmoid(platt[0] + platt[1] * z)
        if regla:
            p = _regla_portero(universo, p)
        y = np.array([f.y for f in universo])
        prod = np.array([f.p_prod for f in universo])
        out(f"\n{nombre}  n={len(universo)}  jugadores={len({f.pid for f in universo})}  tasa={y.mean():.3f}")
        out(f"  P rango {p.min():.3f}–{p.max():.3f}  (producción {prod.min():.3f}–{prod.max():.3f})")
        out(f"  Brier modelo {brier(p, y):.4f}  producción {brier(prod, y):.4f}")
        out(f"  log-loss modelo {logloss(p, y):.4f}  producción {logloss(prod, y):.4f}")
        out(f"  Brier    {_fmt(_delta(_perdida(p, y)[0], _perdida(prod, y)[0], universo))}")
        out(f"  log-loss {_fmt(_delta(_perdida(p, y)[1], _perdida(prod, y)[1], universo))}")
        out("  calibración del modelo (tramo, n, dice, ocurre)")
        for etiqueta, n, pred, obs in calibracion(p, y):
            if n:
                out(f"    {etiqueta}  n={n:<5}  dice {pred:.3f}  ocurre {obs:.3f}")
        out(f"  ECE modelo {ece(calibracion(p, y)):.4f}  producción {ece(calibracion(prod, y)):.4f}")
        return p

    out("\nValidación 26/27, pesos congelados. Las dos variantes; la regla no se elige aquí.")
    plantilla = _filas_2627()
    sin_regla = puntuar("Plantillas, el modelo aprende al portero", plantilla, regla=False)
    con_regla = puntuar("Plantillas, el modelo más la regla del portero", plantilla, regla=True)
    catalogo, nota = _catalogo_con_minutos()
    out(nota)
    if catalogo:
        puntuar("Catálogo completo, sin la regla", catalogo, regla=False)
        puntuar("Catálogo completo, con la regla", catalogo, regla=True)
    mejora = False
    elegido = sin_regla if not usa_regla else con_regla
    if elegido is not None:
        y = np.array([f.y for f in plantilla])
        prod = np.array([f.p_prod for f in plantilla])
        veredicto_ll = _delta(_perdida(elegido, y)[1], _perdida(prod, y)[1], plantilla)
        veredicto_br = _delta(_perdida(elegido, y)[0], _perdida(prod, y)[0], plantilla)
        mejora = _entra(veredicto_ll) and _entra(veredicto_br)
    out(
        "\nVeredicto en las plantillas de 26/27: "
        + ("mejora" if mejora else "no mejora")
        + " a producción. La variante es la que ganó en 24/25+25/26"
        + (" (con la regla)." if usa_regla else " (sin la regla).")
    )

    destino = ROOT / ".cache" / "reajuste_titularidad.txt"
    destino.write_text("\n".join(lineas), encoding="utf-8")
    receta = {
        "cols": cols,
        "beta": beta.tolist(),
        "platt": platt.tolist(),
        "usa_regla_portero": usa_regla,
        "mejora": mejora,
        "nombres": etiquetas,
    }
    (ROOT / ".cache" / "reajuste_receta.json").write_text(json.dumps(receta), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

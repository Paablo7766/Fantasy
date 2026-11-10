"""Experimentos de ablación (pasos 1–3) sobre ``scripts/ablacion_xp.py``.

Todo parámetro que se ajusta con datos se elige en walk-forward anidado: para
la jornada ``t`` solo se miran las filas de jornadas ``< t`` (J8 se queda con el
valor de producción, porque antes no hay filas de test).

    python scripts/ablacion_xp_experimentos.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ablacion_xp as ax  # noqa: E402
from toolbox.cache import cache_root  # noqa: E402
from toolbox.engine import p_titular_model as ptm  # noqa: E402
from toolbox.engine import xp2  # noqa: E402
from toolbox.matching import normalize_club, normalize_name  # noqa: E402
from toolbox import rival_posicional as rp  # noqa: E402

SLOTS = ("PT", "DF", "MC", "DL")
RESULTADOS: list[ax.Resultado] = []
TEST = [8, 9, 10, 11, 12]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def y_de(filas: list[ax.Fila]) -> np.ndarray:
    return np.array([f.actual for f in filas])


def wf_elegir(filas: list[ax.Fila], preds: dict[Any, np.ndarray], defecto: Any) -> tuple[np.ndarray, dict[int, Any]]:
    """Para cada jornada t elige el valor con menor MAE en jornadas < t."""
    y = y_de(filas)
    semanas = np.array([f.week for f in filas])
    out = np.zeros(len(filas))
    elegido: dict[int, Any] = {}
    for t in sorted(set(semanas)):
        train = semanas < t
        if train.sum() < 50:
            v = defecto
        else:
            v = min(preds, key=lambda k: float(np.mean(np.abs(preds[k][train] - y[train]))))
        elegido[int(t)] = v
        out[semanas == t] = preds[v][semanas == t]
    return out, elegido


def registrar(nombre: str, filas: list[ax.Fila], base: np.ndarray, nueva: np.ndarray, nota: str = "") -> ax.Resultado:
    res = ax.comparar(nombre, filas, base, nueva, nota)
    RESULTADOS.append(res)
    ax.imprimir([res], ax.mae(base, filas))
    return res


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


# --------------------------------------------------------------------------
# Balón parado (AF, página guardada en .cache/af_balon_parado.html)
# --------------------------------------------------------------------------


def cargar_balon_parado(actas: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    from toolbox.analitica_fantasy import parse_set_pieces

    ruta = cache_root() / "af_balon_parado.html"
    if not ruta.is_file():
        return {}
    filas = parse_set_pieces(ruta.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in filas:
        club = ax._club(row.club or "")
        if club == "athletic club":
            club = "athletic"
        nombre = normalize_name(row.name)
        toks = set(nombre.split())
        for pid, e in actas.items():
            if ax._club(e.get("team")) != club:
                continue
            n2 = normalize_name(str(e.get("name") or ""))
            t2 = set(n2.replace(".", " ").split())
            if nombre == n2 or (toks and nombre.split()[-1] in t2) or (t2 and n2.split()[-1] in toks):
                out[pid].append({"role": row.role})
                break
    return dict(out)


# --------------------------------------------------------------------------
# PASO 1 — Auditoría del error de la base
# --------------------------------------------------------------------------


def paso1(filas: list[ax.Fila], base: np.ndarray, sal: list[dict]) -> None:
    y = y_de(filas)
    e = base - y
    tot = np.abs(e).sum()
    p = np.array([s["p"] for s in sal])
    mins = np.array([f.minutes for f in filas])
    slot = np.array([f.slot for f in filas])
    print("\n=== PASO 1: de dónde sale el MAE de la base ===")
    print(f"MAE {np.abs(e).mean():.3f}  n={len(filas)}  sesgo {e.mean():+.3f}")
    cats = {
        "Falsos titulares (p>=0,65 y <30')": (p >= 0.65) & (mins < 30),
        "Falsos suplentes (p<=0,35 y >=45')": (p <= 0.35) & (mins >= 45),
        "Titular acertado (p>=0,65 y >=60')": (p >= 0.65) & (mins >= 60),
        "Zona dudosa (0,35<p<0,65)": (p > 0.35) & (p < 0.65),
    }
    resto = np.ones(len(filas), bool)
    for m in cats.values():
        resto &= ~m
    cats["Resto"] = resto
    print(f"  {'categoría':<38}{'n':>5}{'MAE':>7}{'sesgo':>8}{'% del error':>12}")
    for k, m in cats.items():
        if m.sum():
            print(f"  {k:<38}{m.sum():5d}{np.abs(e[m]).mean():7.2f}{e[m].mean():+8.2f}{100 * np.abs(e[m]).sum() / tot:11.1f}%")
    print("  Titulares acertados (>=60') por puesto:")
    m60 = (p >= 0.65) & (mins >= 60)
    for s in SLOTS:
        m = m60 & (slot == s)
        if m.sum():
            print(
                f"    {s}: n={m.sum():3d} MAE {np.abs(e[m]).mean():.2f} sesgo {e[m].mean():+.2f} "
                f"(pred media {base[m].mean():.2f} real media {y[m].mean():.2f} mediana real {np.median(y[m]):.2f})"
            )
    # Oráculo: titularidad conocida.
    cond = np.array([s["cond"] for s in sal])
    banq = np.array([max(0.0, (s["xp"] - s["p"] * s["cond"]) / (1 - s["p"])) if s["p"] < 0.99 else 0.0 for s in sal])
    started = mins >= 45
    oraculo = np.where(started, cond, banq)
    oraculo = np.where(np.array([s["modelo"] == "2.0" for s in sal]), oraculo, base)
    print(f"  Oráculo (once conocido, mismo motor): MAE {np.abs(oraculo - y).mean():.3f}  → margen de titularidad {np.abs(e).mean() - np.abs(oraculo - y).mean():.3f}")
    # Media vs mediana: desplazamiento por puesto en muestra (cota) y en walk-forward.
    print("  Media → mediana (desplazamiento constante por puesto):")
    insample = base.copy()
    for s in SLOTS:
        m = slot == s
        insample[m] = base[m] + np.median(y[m] - base[m])
    print(f"    cota en muestra (no válida, usa el futuro): MAE {np.abs(insample - y).mean():.3f}")
    for s in SLOTS:
        m = slot == s
        r = y[m] - base[m]
        print(f"    {s}: media del residuo {r.mean():+.2f}  mediana {np.median(r):+.2f}  asimetría {float(np.mean(((r - r.mean()) / r.std()) ** 3)):+.2f}")


# --------------------------------------------------------------------------
# PASO 2 — Titularidad
# --------------------------------------------------------------------------


def filas_titularidad(actas: dict[str, dict[str, Any]], extra: Callable | None = None) -> list[tuple[int, list[float], float, str]]:
    """(semana, features, etiqueta, pid) para todo jugador-jornada con historia previa."""
    out = []
    for pid, e in actas.items():
        weeks = {int(k): v for k, v in (e.get("weeks") or {}).items()}
        orden = sorted(weeks)
        for i, w in enumerate(orden):
            if i == 0:
                continue
            mins = [float(weeks[x][1]) for x in orden[:i]]
            f = ptm.features_from_minutes(mins)
            if f is None:
                continue
            feats = list(f)
            if extra is not None:
                feats += extra(e, orden[:i], weeks)
            out.append((w, feats, 1.0 if float(weeks[w][1]) >= 45 else 0.0, pid))
    return out


def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    Xb = np.hstack([np.ones((len(X), 1)), X])
    beta = np.zeros(Xb.shape[1])
    R = np.eye(len(beta)) * l2
    R[0, 0] = 0
    for _ in range(50):
        z = np.clip(Xb @ beta, -30, 30)
        pr = 1 / (1 + np.exp(-z))
        g = Xb.T @ (pr - y) + R @ beta
        H = (Xb * (pr * (1 - pr))[:, None]).T @ Xb + R
        beta -= np.linalg.solve(H, g)
    return beta


def p_wf(actas, extra=None, defecto=None) -> dict[tuple[str, int], float]:
    """p_titular walk-forward: pesos ajustados solo con jornadas < t."""
    filas = filas_titularidad(actas, extra)
    out: dict[tuple[str, int], float] = {}
    for t in TEST:
        train = [(f, l) for w, f, l, _ in filas if w < t]
        test = [(pid, f) for w, f, l, pid in filas if w == t]
        if len(train) < 100:
            if defecto is None:
                continue
            beta = defecto
        else:
            beta = fit_logit(np.array([f for f, _ in train]), np.array([l for _, l in train]))
        for pid, f in test:
            z = beta[0] + float(np.dot(beta[1:], f))
            out[(pid, t)] = min(0.95, max(0.05, 1 / (1 + math.exp(-max(-30, min(30, z))))))
    return out


def paso2(filas, base, sal, actas) -> dict[str, Any]:
    print("\n=== PASO 2: titularidad ===")
    y_st = np.array([1.0 if f.minutes >= 45 else 0.0 for f in filas])
    p_base = np.array([s["p"] for s in sal])
    print(f"Brier base (heurística + regla de portero): {brier(p_base, y_st):.4f}")
    ganadores: dict[str, Any] = {}

    # 2.1a Pesos del logístico en walk-forward (higiene: los de producción salen de J9–J11).
    dflt = np.array([ptm.DEFAULT_WEIGHTS["bias"], ptm.DEFAULT_WEIGHTS["season"], ptm.DEFAULT_WEIGHTS["minutes"]])
    pw = p_wf(actas, defecto=dflt)
    cfg = ax.Config("p_titular pesos WF", p_titular=lambda f: pw.get((f.pid, f.week), ax.p_titular_heuristica(f)))
    nueva, s2 = ax.correr(filas, cfg)
    print(f"  Brier pesos WF: {brier(np.array([s['p'] for s in s2]), y_st):.4f}")
    registrar("2.1a Logístico de titularidad reajustado WF", filas, base, nueva, "higiene: base usa pesos J9–J11")

    # 2.1b Tasa base últimas k + titular en la última.
    def extra_ult(e, prev, weeks):
        ult = float(weeks[prev[-1]][1])
        k5 = [float(weeks[x][1]) for x in prev[-5:]]
        return [1.0 if ult >= 45 else 0.0, 1.0 if ult == 0 else 0.0, sum(1 for m in k5 if m >= 45) / len(k5)]

    pw2 = p_wf(actas, extra_ult, defecto=None)
    cfg = ax.Config("p_tit + última/k5", p_titular=lambda f: pw2.get((f.pid, f.week), ax.p_titular_heuristica(f)))
    nueva, s3 = ax.correr(filas, cfg)
    print(f"  Brier + última jornada y tasa k=5: {brier(np.array([s['p'] for s in s3]), y_st):.4f}")
    registrar("2.1b Titularidad + titular/0' en J-1 + tasa k=5", filas, base, nueva)

    # 2.1c Roja en J-1 → sancionado.
    def roja(f: ax.Fila) -> bool:
        if not f.historial or f.historial[-1]["jornada"] != f.week - 1:
            return False
        c = f.historial[-1]["desglose"].get("cantidades") or {}
        return (c.get("red_card", 0) or 0) + (c.get("second_yellow_card", 0) or 0) > 0

    n_roja = sum(1 for f in filas if roja(f))
    cfg = ax.Config("roja", p_titular=lambda f: 0.0 if roja(f) else ax.p_titular_heuristica(f))
    nueva, _ = ax.correr(filas, cfg)
    registrar("2.1c Roja en J-1 → p_titular 0", filas, base, nueva, f"{n_roja} casos")

    # 2.1d FF + AF (solo J12: player_signal_log empieza el 7-nov).
    senales = ax.cargar_senales(cache_root())
    j12 = [i for i, f in enumerate(filas) if f.week == 12]
    reg = []
    for i in j12:
        f = filas[i]
        # Solo señales guardadas al menos 1 h antes del saque (UTC). Con el filtro
        # por día se colaban fotos del mismo día tomadas con el partido empezado,
        # cuando FF/AF enseñaban 0 % a los ya jugados: Brier FF 0,217 falso.
        from datetime import datetime, timezone

        ko = datetime.fromisoformat(f.partido.kickoff).replace(tzinfo=timezone.utc).timestamp()
        cand = [
            r for r in senales.get(f.pid, [])
            if r["stored_at"] < ko - 3600 and (r["p_titular_ff"] is not None or r["p_titular_af"] is not None)
        ]
        if not cand:
            continue
        r = max(cand, key=lambda r: r["stored_at"])
        def pc(v):
            if v is None:
                return None
            v = float(v)
            return v / 100 if v > 1 else v
        reg.append((i, pc(r["p_titular_ff"]), pc(r["p_titular_af"]), pc(r["p_titular_final"])))
    print(f"\n  J12 con señal FF/AF previa al saque: {len(reg)} de {len(j12)} filas")
    if len(reg) >= 40:  # J12: 77 filas con señal previa
        idx = [i for i, *_ in reg]
        yy = y_st[idx]
        ph = p_base[idx]
        ff = np.array([v if v is not None else np.nan for _, v, _, _ in reg])
        af = np.array([v if v is not None else np.nan for _, _, v, _ in reg])
        fin = np.array([v if v is not None else np.nan for *_, v in reg])
        af_n = af.copy()
        neutro = (np.abs(af - 0.5) < 1e-9) & ((ff >= 0.70) | (ff <= 0.30))
        af_n[neutro] = np.nan
        print(f"  AF con 0,50 exacto y FF con señal clara: {int(neutro.sum())}")

        def fill(a, b):
            return np.where(np.isnan(a), b, a)

        fuentes = {
            "heurística": ph,
            "FF": fill(ff, ph),
            "AF": fill(af, ph),
            "AF sin 0,50": fill(af_n, fill(ff, ph)),
            "p_titular_final (prod. en vivo)": fill(fin, ph),
            "media FF/AF": fill(np.nanmean(np.vstack([ff, af]), axis=0), ph),
            "media FF/AF sin 0,50": fill(np.nanmean(np.vstack([ff, af_n]), axis=0), ph),
        }
        for k, v in fuentes.items():
            print(f"    Brier {k:<32}{brier(v, yy):.4f}")
        # Pesos w_FF, w_AF, w_heur por validación cruzada dejando un partido fuera (no hay jornada previa).
        partidos = [filas[i].match_id for i in idx]
        X = np.vstack([fill(ff, ph), fill(af_n, fill(ff, ph)), ph]).T
        p_cv = np.zeros(len(idx))
        for mk in set(partidos):
            te = np.array([pp == mk for pp in partidos])
            mejor, best = None, 9.0
            for wf in np.linspace(0, 1, 11):
                for wa in np.linspace(0, 1 - wf, int(round((1 - wf) * 10)) + 1):
                    pr = X[~te] @ np.array([wf, wa, 1 - wf - wa])
                    b = brier(pr, yy[~te])
                    if b < best:
                        best, mejor = b, (wf, wa)
            p_cv[te] = X[te] @ np.array([mejor[0], mejor[1], 1 - sum(mejor)])
        print(f"    Brier mezcla w_FF/w_AF/w_heur (CV por partido): {brier(p_cv, yy):.4f}")
        mapa = {filas[i].pid: v for i, v in zip(idx, fill(fin, ph))}
        mapa_mix = {filas[i].pid: v for i, v in zip(idx, p_cv)}
        sub = [filas[i] for i in idx]
        b_sub = base[idx]
        n1, _ = ax.correr(sub, ax.Config("fin", p_titular=lambda f: mapa[f.pid]))
        registrar("2.1d J12: p_titular de producción (FF/AF)", sub, b_sub, n1, "solo J12; base = heurística")
        n2, _ = ax.correr(sub, ax.Config("mix", p_titular=lambda f: mapa_mix[f.pid]))
        registrar("2.1d J12: mezcla FF/AF sin 0,50 (CV partido)", sub, b_sub, n2, "solo J12")

    # 2.2 Banquillo: P(entra | no titular) y puntos al entrar, por puesto y jugador.
    hist_sub = sub_rates_historico(actas)
    preds = {}
    for k_j in (0.0, 3.0, 8.0):
        for usa_hist in (False, True):
            def banq(f: ax.Fila, s: dict, k_j=k_j, usa_hist=usa_hist) -> float:
                return banquillo_wf(f, actas, k_j, hist_sub if usa_hist else None)
            preds[(k_j, usa_hist)] = ax.correr(filas, ax.Config("banq", banquillo=banq))[0]
    nueva, eleg = wf_elegir(filas, preds, (0.0, False))
    registrar("2.2 P(entra|suplente) y pts por puesto/jugador WF", filas, base, nueva, f"elegido {eleg}")
    for k, v in preds.items():
        print(f"    variante k_jugador={k[0]} histórico={k[1]}: MAE {ax.mae(v, filas):.3f}")
    ganadores["banquillo_preds"] = preds
    return ganadores


def sub_rates_historico(actas) -> dict[str, tuple[int, int]]:
    """(entradas, no-titularidades) del jugador en 24/25 y 25/26 (FútbolFantasy)."""
    from toolbox.season_history import emparejar, indice_por_club, leer_almacen

    almacen = leer_almacen()
    indice = indice_por_club(almacen)
    out: dict[str, tuple[int, int]] = {}
    for pid, e in actas.items():
        slug = emparejar(str(e.get("name") or ""), str(e.get("team") or ""), indice)
        if not slug or slug not in almacen:
            continue
        n_ns = n_in = 0
        for clave, temp in (almacen[slug].get("temporadas") or {}).items():
            if clave not in ("laliga-24-25", "laliga-25-26"):
                continue
            filas = temp.get("filas") or []
            if len(filas) < 15:
                continue
            for r in filas:
                m = r.get("minutos")
                if m is None:
                    continue
                if m < 45:
                    n_ns += 1
                    n_in += 1 if m > 0 else 0
        if n_ns:
            out[pid] = (n_in, n_ns)
    return out


_TASAS_CACHE: dict[int, dict[str, tuple[float, float]]] = {}


def tasas_puesto(actas, t: int) -> dict[str, tuple[float, float]]:
    """P(entra | no titular) y pts medios al entrar, por puesto, con jornadas < t."""
    if t in _TASAS_CACHE:
        return _TASAS_CACHE[t]
    acc: dict[str, list[float]] = defaultdict(list)
    pts: dict[str, list[float]] = defaultdict(list)
    from toolbox.engine.xp_calculator import canonical_slot

    for e in actas.values():
        s = canonical_slot(e.get("position") or "MC")
        for w, (p, m) in ((int(k), v) for k, v in (e.get("weeks") or {}).items()):
            if w >= t or float(m) >= 45:
                continue
            acc[s].append(1.0 if float(m) > 0 else 0.0)
            if float(m) > 0:
                pts[s].append(float(p))
    out = {}
    for s in SLOTS:
        rate = float(np.mean(acc[s])) if len(acc[s]) >= 10 else xp2.FACTOR_BANQUILLO[s]
        media = float(np.mean(pts[s])) if len(pts[s]) >= 5 else xp2.REVULSIVO_PUESTO[s]
        out[s] = (rate, media)
    _TASAS_CACHE[t] = out
    return out


def banquillo_wf(f: ax.Fila, actas, k_j: float, hist: dict | None) -> float:
    rate_pos, pts_pos = tasas_puesto(actas, f.week)[f.slot]
    ns = [h for h in f.historial if h["minutos"] < 45]
    entra = sum(1 for h in ns if h["minutos"] > 0)
    prior_n, prior_in = 0.0, 0.0
    if hist and f.pid in hist:
        hin, hns = hist[f.pid]
        w = min(1.0, 10.0 / hns)  # el pasado pesa como 10 partidos como mucho
        prior_n, prior_in = hns * w, hin * w
    k = 3.0
    rate = (entra + prior_in + k * rate_pos) / (len(ns) + prior_n + k) if (k_j > 0 or hist) else rate_pos
    if k_j > 0:
        rate = (entra + prior_in + k_j * rate_pos) / (len(ns) + prior_n + k_j)
    sub_pts = [h["puntos"] for h in ns if h["minutos"] > 0]
    media = (sum(sub_pts) + 3.0 * pts_pos) / (len(sub_pts) + 3.0)
    return rate * media


# --------------------------------------------------------------------------
# PASO 3 — Suelo, cuotas, balón parado, L1
# --------------------------------------------------------------------------


def paso3(filas, base, sal, actas) -> None:
    print("\n=== PASO 3: puntos que no son goles ===")
    # 3.1a Prior multi-temporada del suelo: kappa (K_HIST_SUELO) y K_SUELO.
    preds = {}
    for kh in (6.0, 12.0, 24.0, 1e9):
        for ks in (3.0, 5.0, 8.0):
            preds[(kh, ks)] = ax.correr(filas, ax.Config("k", parches={"K_HIST_SUELO": kh, "K_SUELO": ks}))[0]
    nueva, eleg = wf_elegir(filas, preds, (12.0, 5.0))
    registrar("3.1a Suelo: κ histórico y K del puesto (WF)", filas, base, nueva, f"elegido {eleg}")
    sin_hist = preds[(1e9, 5.0)]
    registrar("3.1a' Ablación: sin histórico 24/25–25/26", filas, base, sin_hist, "quita el prior multi-temporada")

    # 3.1b Offset de club: fuera / walk-forward con |t|>=3.
    sin_club_cfg = ax.Config("sinclub", parches={"_OFFSET_CLUB_VALORACION": {}})
    sin_club, s_sc = ax.correr(filas, sin_club_cfg)
    registrar("3.1b' Ablación: sin offset de club (en muestra)", filas, base, sin_club)
    offs = offsets_club_wf(filas, s_sc)
    nueva = np.array([sin_club[i] + s_sc[i]["p"] * offs.get((f.week, f.club), 0.0) for i, f in enumerate(filas)])
    activos = sorted({(w, c, round(v, 2)) for (w, c), v in offs.items() if v})
    registrar("3.1b Offset de club WF (|t|>=3, n/(n+12))", filas, base, nueva, f"{len(activos)} club-jornada activos")
    print("    offsets WF activos:", activos)

    # 3.1c Higiene: rival posicional con tabla walk-forward (la de producción ve todas las actas).
    tablas = {}
    md = {}
    from toolbox.understat import parse_openfootball_matchdays

    for (h, a), j in parse_openfootball_matchdays((cache_root() / "laliga_2026_27.txt").read_text(encoding="utf-8")).items():
        md[(h, j)] = a
        md[(a, j)] = h
    for t in TEST:
        trunc = {pid: {**e, "weeks": {k: v for k, v in e["weeks"].items() if int(k) < t}, "desglose": {k: v for k, v in (e.get("desglose") or {}).items() if int(k) < t}} for pid, e in actas.items()}
        tablas[t] = rp.construir_tabla(trunc, md, normalize_club)
    orig = rp.tabla_en_cache
    sin_rival, _ = ax.correr(filas, ax.Config("sinrival", usar_rival_posicional=False))
    registrar("3.1c' Ablación: sin rival posicional", filas, base, sin_rival)
    out = []
    for f in filas:
        rp.tabla_en_cache = lambda t=f.week: tablas[t]
        out.append(ax.predecir(f, ax.Config("rivalwf"))["xp"])
    rp.tabla_en_cache = orig
    registrar("3.1c Rival posicional con tabla WF", filas, base, np.array(out), "higiene de fuga")

    # 3.2 Cuotas: ablación y recalibración WF de P(victoria) y portería.
    neutro, _ = ax.correr(filas, ax.Config("neutro", usar_cuotas=False))
    registrar("3.2' Ablación: sin cuotas (λ neutro)", filas, base, neutro)
    preds = {b: ax.correr(filas, ax.Config("bv", parches={"BONO_VICTORIA": b}))[0] for b in (0.0, 1.5, 3.0, 4.5, 6.0)}
    nueva, eleg = wf_elegir(filas, preds, 3.0)
    registrar("3.2a Peso de P(victoria) recalibrado WF", filas, base, nueva, f"elegido {eleg}")
    tabla = xp2.TABLA_PORTERIA
    preds = {}
    for esc in (0.5, 0.75, 1.0, 1.25, 1.5):
        nt = {k: tuple(v * esc for v in vals) for k, vals in tabla.items()}
        preds[esc] = ax.correr(filas, ax.Config("cs", parches={"TABLA_PORTERIA": nt}))[0]
    nueva, eleg = wf_elegir(filas, preds, 1.0)
    registrar("3.2b Escala de portería (P(CS) de cuotas) WF", filas, base, nueva, f"elegido {eleg}")

    # 3.3 Balón parado.
    roles = cargar_balon_parado(actas)
    ax.ROLES_BALON_PARADO.clear()
    ax.ROLES_BALON_PARADO.update(roles)
    con_bp, _ = ax.correr(filas, ax.Config("bp"))
    ax.ROLES_BALON_PARADO.clear()
    n_bp = sum(1 for f in filas if f.pid in roles)
    registrar("3.3 Balón parado AF (penaltis/córners/faltas)", filas, base, con_bp, f"{len(roles)} lanzadores, {n_bp} filas; roles de hoy")
    pens = [i for i, f in enumerate(filas) if any(r["role"] == "penalties" for r in roles.get(f.pid, []))]
    if pens:
        print(f"    lanzadores de penalti: n={len(pens)} MAE base {ax.mae(base[pens], [filas[i] for i in pens]):.3f} con rol {ax.mae(con_bp[pens], [filas[i] for i in pens]):.3f}")

    # 3.4 Calibración L1.
    y = y_de(filas)
    slot = np.array([f.slot for f in filas])
    semanas = np.array([f.week for f in filas])
    out_shift = base.copy()
    out_qr = base.copy()
    for t in TEST:
        tr = semanas < t
        for s in SLOTS:
            m_tr = tr & (slot == s)
            m_te = (semanas == t) & (slot == s)
            if m_tr.sum() < 20:
                continue
            out_shift[m_te] = np.maximum(0, base[m_te] + np.median(y[m_tr] - base[m_tr]))
            a, b = l1_lineal(base[m_tr], y[m_tr])
            out_qr[m_te] = np.maximum(0, a + b * base[m_te])
    registrar("3.4a Desplazamiento a la mediana por puesto WF", filas, base, out_shift)
    registrar("3.4b Regresión mediana y~a+b·xP por puesto WF", filas, base, out_qr)
    ataque = np.array([s["p"] * (s["desglose"].get("gol", 0.0) + s["desglose"].get("asistencia", 0.0)) for s in sal])
    preds = {a: np.maximum(0, base - a * ataque) for a in (0.0, 0.25, 0.5, 0.75, 1.0)}
    nueva, eleg = wf_elegir(filas, preds, 0.0)
    registrar("3.4c Contracción de gol+asist. hacia la mediana WF", filas, base, nueva, f"elegido {eleg}")


def l1_lineal(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    from scipy.optimize import linprog

    n = len(x)
    # min sum(u+v) s.a. a + b x + u - v = y
    c = np.concatenate([[0, 0], np.ones(2 * n)])
    A = np.hstack([np.ones((n, 1)), x[:, None], np.eye(n), -np.eye(n)])
    bounds = [(None, None), (None, None)] + [(0, None)] * (2 * n)
    res = linprog(c, A_eq=A, b_eq=y, bounds=bounds, method="highs")
    return float(res.x[0]), float(res.x[1])


def offsets_club_wf(filas: list[ax.Fila], sal: list[dict]) -> dict[tuple[int, str], float]:
    """Residuo de suelo (sin gol ni asistencia) por club con jornadas < t; entra si |t|>=3."""
    out = {}
    for t in TEST:
        acc: dict[str, list[float]] = defaultdict(list)
        for f, s in zip(filas, sal):
            if f.week >= t or f.minutes < 45 or s["modelo"] != "2.0":
                continue
            pred = s["cond"] - s["desglose"].get("gol", 0.0) - s["desglose"].get("asistencia", 0.0)
            real = f.actual - f.gol_real - f.ast_real
            acc[f.club].append(real - pred)
        for club, r in acc.items():
            if len(r) < 8:
                continue
            m, sd = float(np.mean(r)), float(np.std(r, ddof=1))
            tt = m / (sd / math.sqrt(len(r))) if sd > 0 else 0
            if abs(tt) >= 3:
                out[(t, club)] = m * len(r) / (len(r) + 12)
    return out


def main() -> int:
    filas, actas, _ = ax.construir_filas(TEST, 1)
    base, sal = ax.correr(filas, ax.Config("base"))
    print(f"Base de producción: n={len(filas)} MAE {ax.mae(base, filas):.3f}")
    j811 = [i for i, f in enumerate(filas) if f.week <= 11]
    print(f"  J8–J11: n={len(j811)} MAE {ax.mae(base[j811], [filas[i] for i in j811]):.3f}  (referencia oficial 2,70 del commit 0ed701f)")
    fuga = [i for i, f in enumerate(filas) if not f.precio_fuga]
    print(f"  Filas con precio sin fuga: {len(fuga)}; MAE {ax.mae(base[fuga], [filas[i] for i in fuga]):.3f}")
    sin_precio, _ = ax.correr(filas, ax.Config("sp", parches={"PESO_PRECIO": 0.0}))
    registrar("0. Ablación: sin término de precio", filas, base, sin_precio, "precio J8–J10 posterior al saque")

    paso1(filas, base, sal)
    paso2(filas, base, sal, actas)
    paso3(filas, base, sal, actas)

    print("\n\n=================== TABLA DE ABLACIÓN ===================")
    ax.imprimir(RESULTADOS, ax.mae(base, filas))
    salida = [
        {
            "componente": r.nombre, "n": r.n, "mae": r.mae, "delta": r.delta, "ic_jugador": r.ic_jug, "ic_partido": r.ic_part,
            "p_wilcoxon": r.p_wilcoxon, "p_dm": r.p_dm, "r": r.r, "por_semana": r.por_semana, "veredicto": r.veredicto, "nota": r.nota,
        }
        for r in RESULTADOS
    ]
    (cache_root() / "ablacion_xp_resultados.json").write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

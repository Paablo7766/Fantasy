"""Parte 2: cuánto paga de más el ganador y probabilidad de ganar fuera de muestra.

Uso: ``python investigacion/caja_pujas/pujas.py`` (después de ``caja.py``).
Escribe ``pujas_resultados.json`` en esta carpeta y nada más.

* Valor previo: la última foto de valor guardada antes del cierre de las 14:08
  del día de la compra y con menos de 36 h. Las fotos se guardan por la tarde, así
  que casi siempre es la de la víspera. Una foto del mismo día guardada después
  del cierre no se usa.
* Prima = precio ganador / valor previo − 1.
* ``bid_count`` sale de ``market_listing_log`` del anuncio que cerraba ese día,
  guardado antes del cierre: es un mínimo (pudo haber pujas después).
* Probabilidad de ganar con prima x = parte de precios ganadores con prima <= x.
  Entrena con compras que cierran hasta el 2-nov y evalúa desde el 3-nov.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datos import (  # noqa: E402
    MADRID,
    NOMBRE,
    OUT,
    PROPIO,
    actividad,
    cambios_valor,
    cierre_de,
    fotos_valor,
    listados,
    m,
    mis_pujas,
    posiciones,
    señales,
    valor_antes,
    wilson,
)
from toolbox.engine.auction_intel import (  # noqa: E402
    CURVA_PRIMAS_PRIOR,
    PRIMA_PUJA,
    curva_para_jugador,
    curva_primas,
    prob_ganar_prima,
    tramo_valor,
)
from toolbox.engine.sales_audit import SOBREPRECIO_RIVAL_PCT  # noqa: E402

CORTE_ENTRENO = date(2026, 11, 2)
MIN_PERFIL = 8
MIN_CUBO = 8
REJILLA = [0.0, 0.02, 0.047, 0.05, 0.10, 0.12, 0.15, 0.20, 0.30, 0.40, 0.50, 0.75, 1.00]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def q(values: list[float], f: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * f
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def resumen(primas: list[float]) -> dict[str, Any]:
    n = len(primas)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "p25": round(q(primas, 0.25), 3),
        "mediana": round(q(primas, 0.5), 3),
        "p75": round(q(primas, 0.75), 3),
        "media": round(statistics.mean(primas), 3),
        "parte_al_valor": round(sum(1 for p in primas if p <= 0.005) / n, 3),
        "parte_mas_10": round(sum(1 for p in primas if p > 0.10) / n, 3),
        "parte_mas_50": round(sum(1 for p in primas if p > 0.50) / n, 3),
    }


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 5:
        return None

    def rank(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(num / den, 3) if den else None


# --- Compras con valor previo -------------------------------------------------

def compras(eventos: list[dict[str, Any]], caja: dict[str, Any]) -> list[dict[str, Any]]:
    fotos = fotos_valor()
    cambios = cambios_valor()
    pos = posiciones()
    sen = señales()
    lst = listados()
    por_compra = caja["caja_por_compra"]
    cajas_cierre = caja.get("cajas_en_cierre", {})
    clausulas_pagadas = defaultdict(int)
    for e in eventos:
        if e["kind"] == "clause_paid":
            clausulas_pagadas[e["team_id"]] += 1
    lotes: dict[tuple[str, datetime], int] = defaultdict(int)
    for e in eventos:
        if e["kind"] == "buy":
            lotes[(e["team_id"], e["at"].replace(second=0))] += e["amount"]
    out = []
    for e in eventos:
        if e["kind"] != "buy":
            continue
        dia = e["at"].astimezone(MADRID).date()
        cierre = cierre_de(dia)
        ref = valor_antes(fotos, e["player_id"], cierre)
        # Variación reciente: la del día que publica la propia foto previa (ya conocida al pujar).
        var3 = None
        if ref:
            ch = cambios.get((e["player_id"], ref["dia_foto"]))
            if isinstance(ch, int) and ref["valor"] - ch > 0:
                var3 = ch / (ref["valor"] - ch)
        s_prev = [s for s in sen.get(e["player_id"], []) if s["stored"] < cierre and (cierre - s["stored"]).days < 2]
        sp = s_prev[-1] if s_prev else None
        anuncio = [
            a for a in lst
            if a["player_id"] == e["player_id"] and a["expires"] is not None
            and a["expires"].astimezone(MADRID).date() == dia and a["stored"] < cierre
        ]
        anuncio = max(anuncio, key=lambda a: a["stored"]) if anuncio else None
        cc = cajas_cierre.get(cierre.isoformat(), {})
        prima = e["amount"] / ref["valor"] - 1 if ref else None
        rivales_con_caja = None
        if cc:
            rivales_con_caja = sum(
                1 for t, v in cc.items() if t != e["team_id"] and v["prob"] is not None and v["prob"] >= e["amount"]
            )
        cj = por_compra.get(e["id"], {})
        lote = lotes[(e["team_id"], e["at"].replace(second=0))]
        out.append(
            {
                "id": e["id"],
                "team_id": e["team_id"],
                "equipo": NOMBRE[e["team_id"]],
                "propia": e["team_id"] == PROPIO,
                "player_id": e["player_id"],
                "posicion": pos.get(e["player_id"]),
                "dia": dia.isoformat(),
                "dia_semana": DIAS[dia.weekday()],
                "precio": e["amount"],
                "valor_previo": ref["valor"] if ref else None,
                "edad_foto_h": ref["edad_h"] if ref else None,
                "foto_mismo_dia": (ref["dia_foto"] == dia.isoformat()) if ref else None,
                "fuente_valor": ref["fuente"] if ref else None,
                "prima": round(prima, 4) if prima is not None else None,
                "tramo": tramo_valor(ref["valor"]) if ref else None,
                "var_dia": round(var3, 4) if var3 is not None else None,
                "subiendo": (var3 > 0) if var3 is not None else None,
                "puntos_recientes": sp["last_points"] if sp else None,
                "xp_previo": sp["xp"] if sp else None,
                "bid_count": anuncio["bid_count"] if anuncio else None,
                "anuncio_guardado": anuncio["stored"].isoformat() if anuncio else None,
                "caja_prob_antes": cj.get("prob"),
                "caja_min_antes": cj.get("min"),
                "caja_max_antes": cj.get("max"),
                "lote_total": lote,
                "rivales_con_caja": rivales_con_caja,
                "clausulazos_pagados_equipo": clausulas_pagadas[e["team_id"]],
            }
        )
    return out


def anuncios_sin_venta(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    """Anuncios de LaLiga que cerraron sin compra en el feed (la parte que la curva no ve)."""
    lst = listados()
    vendidos = {(e["player_id"], e["at"].astimezone(MADRID).date()) for e in eventos if e["kind"] == "buy"}
    cerrados: dict[tuple[str, date], dict[str, Any]] = {}
    for a in lst:
        if a["expires"] is None or a["seller"] is not None or a["player_id"] is None:
            continue
        dia = a["expires"].astimezone(MADRID).date()
        if a["stored"] >= cierre_de(dia):
            continue
        clave = (a["player_id"], dia)
        if clave not in cerrados or a["stored"] > cerrados[clave]["stored"]:
            cerrados[clave] = a
    filas = []
    ultimo = max(e["at"] for e in eventos)
    for (pid, dia), a in cerrados.items():
        if cierre_de(dia) > ultimo:  # el feed aún no trae ese cierre
            continue
        filas.append({"player_id": pid, "dia": dia.isoformat(), "bid_count": a["bid_count"], "vendido": (pid, dia) in vendidos})
    por_pujas: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in filas:
        clave = "0" if not f["bid_count"] else ("1" if f["bid_count"] == 1 else "2+")
        por_pujas[clave][0] += 1
        por_pujas[clave][1] += int(f["vendido"])
    return {
        "anuncios_laliga_cerrados": len(filas),
        "vendidos": sum(f["vendido"] for f in filas),
        "por_pujas_vistas": {k: {"anuncios": v[0], "vendidos": v[1]} for k, v in sorted(por_pujas.items())},
        "dias": sorted({f["dia"] for f in filas}),
    }


# --- Probabilidad de ganar -----------------------------------------------------

def curva_global(primas: list[float]) -> tuple[tuple[float, float], ...] | None:
    return curva_primas(primas)


def evaluar(test: list[dict[str, Any]], modelo) -> dict[str, Any]:
    pares = []
    for c in test:
        for x in REJILLA:
            p = modelo(c, x)
            y = 1 if x >= c["prima"] - 1e-9 else 0
            pares.append((c["id"], x, p, y))
    brier = statistics.mean((p - y) ** 2 for _, _, p, y in pares)
    cubos = []
    for lo, hi in [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]:
        sel = [(p, y) for _, _, p, y in pares if lo <= p < hi]
        n = len(sel)
        k = sum(y for _, y in sel)
        subastas = len({cid for cid, _, p, _ in pares if lo <= p < hi})
        w = wilson(k, n) if n else None
        cubos.append(
            {
                "cubo": f"{lo:.1f}-{min(hi, 1.0):.1f}",
                "pares": n,
                "subastas": subastas,
                "p_media": round(statistics.mean(p for p, _ in sel), 3) if n else None,
                "frecuencia_real": round(k / n, 3) if n else None,
                "ic95": [round(w[0], 3), round(w[1], 3)] if w else None,
                "calibrado": None if subastas < MIN_CUBO else (w[0] <= statistics.mean(p for p, _ in sel) <= w[1]),
            }
        )
    return {"brier": round(brier, 4), "pares": len(pares), "subastas": len(test), "cubos": cubos, "_pares": pares}


def bootstrap_dif(a: list[tuple], b: list[tuple], rondas: int = 2000, semilla: int = 7) -> dict[str, float]:
    """IC del 95 % de Brier(a) − Brier(b) remuestreando subastas (no pares)."""
    por_a: dict[str, list[float]] = defaultdict(list)
    por_b: dict[str, list[float]] = defaultdict(list)
    for cid, _, p, y in a:
        por_a[cid].append((p - y) ** 2)
    for cid, _, p, y in b:
        por_b[cid].append((p - y) ** 2)
    ids = sorted(por_a)
    rng = random.Random(semilla)
    difs = []
    for _ in range(rondas):
        muestra = [rng.choice(ids) for _ in ids]
        sa = [v for i in muestra for v in por_a[i]]
        sb = [v for i in muestra for v in por_b[i]]
        difs.append(statistics.mean(sa) - statistics.mean(sb))
    difs.sort()
    return {"dif": round(statistics.mean(v for i in ids for v in por_a[i]) - statistics.mean(v for i in ids for v in por_b[i]), 4),
            "ic95": [round(difs[int(0.025 * rondas)], 4), round(difs[int(0.975 * rondas)], 4)]}


def probabilidad(con_valor: list[dict[str, Any]]) -> dict[str, Any]:
    train = [c for c in con_valor if date.fromisoformat(c["dia"]) <= CORTE_ENTRENO]
    test = [c for c in con_valor if date.fromisoformat(c["dia"]) > CORTE_ENTRENO]
    muestras = [
        {"prima": max(0.0, c["prima"]), "valor": c["valor_previo"], "subiendo": c["subiendo"], "pujas": c["bid_count"]}
        for c in train
    ]
    global_tr = curva_global([m_["prima"] for m_ in muestras])

    modelos = {
        "ingenua_4_7": lambda c, x: 1.0 if x >= PRIMA_PUJA - 1 - 1e-9 else 0.0,
        "ingenua_12": lambda c, x: 1.0 if x >= SOBREPRECIO_RIVAL_PCT / 100 - 1e-9 else 0.0,
        "app_global_reajustada": lambda c, x: prob_ganar_prima(x, global_tr),
        "nueva_por_tramo": lambda c, x: prob_ganar_prima(x, curva_para_jugador(muestras, valor=c["valor_previo"])[0]),
        "app_cadena_completa": lambda c, x: prob_ganar_prima(
            x, curva_para_jugador(muestras, valor=c["valor_previo"], subiendo=c["subiendo"])[0]
        ),
        "codigo_global_14nov_dentro_de_muestra": lambda c, x: prob_ganar_prima(x, CURVA_PRIMAS_PRIOR),
        "codigo_tramo_14nov_dentro_de_muestra": lambda c, x: prob_ganar_prima(x, curva_para_jugador(None, valor=c["valor_previo"])[0]),
    }
    res = {k: evaluar(test, f) for k, f in modelos.items()}
    base = res["app_global_reajustada"]["_pares"]
    comparaciones = {
        k: bootstrap_dif(v["_pares"], base) for k, v in res.items() if k != "app_global_reajustada"
    }
    fijas = {}
    for nombre, x in (("+4,7 %", PRIMA_PUJA - 1), ("+12 %", SOBREPRECIO_RIVAL_PCT / 100)):
        k = sum(1 for c in test if x >= c["prima"] - 1e-9)
        w = wilson(k, len(test))
        fijas[nombre] = {
            "ganadas_test": k,
            "n_test": len(test),
            "frecuencia": round(k / len(test), 3),
            "ic95": [round(w[0], 3), round(w[1], 3)],
            "curva_reajustada_decia": round(prob_ganar_prima(x, global_tr), 3),
            "curva_codigo_decia": round(prob_ganar_prima(x, CURVA_PRIMAS_PRIOR), 3),
        }
    tramos_train = defaultdict(int)
    tramos_test = defaultdict(int)
    for c in train:
        tramos_train[c["tramo"]] += 1
    for c in test:
        tramos_test[c["tramo"]] += 1
    for v in res.values():
        v.pop("_pares", None)
    return {
        "n_train": len(train),
        "n_test": len(test),
        "train_por_tramo": dict(tramos_train),
        "test_por_tramo": dict(tramos_test),
        "train_con_bid_count": sum(1 for c in train if c["bid_count"] is not None),
        "test_con_bid_count": sum(1 for c in test if c["bid_count"] is not None),
        "curva_global_train": global_tr,
        "modelos": res,
        "brier_menos_app_global": comparaciones,
        "pujas_fijas": fijas,
    }


# --- Perfiles -----------------------------------------------------------------

def perfiles(todas: list[dict[str, Any]], eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cobradas = defaultdict(int)
    pagadas = defaultdict(int)
    for e in eventos:
        if e["kind"] == "clause_paid":
            pagadas[e["team_id"]] += 1
        elif e["kind"] == "clause_cobrada":
            cobradas[e["team_id"]] += 1
    out = []
    for team in NOMBRE:
        mias = [c for c in todas if c["team_id"] == team]
        con = [c for c in mias if c["prima"] is not None]
        primas = [c["prima"] for c in con]
        fila: dict[str, Any] = {
            "team_id": team,
            "equipo": NOMBRE[team],
            "compras": len(mias),
            "con_valor": len(con),
            "clausulazos_pagados": pagadas[team],
            "clausulazos_sufridos": cobradas[team],
            "gasto_compras": sum(c["precio"] for c in mias),
        }
        if primas:
            mediana = q(primas, 0.5)
            fila["prima"] = resumen(primas)
            # IC de la mediana por remuestreo, para que la muestra pequeña se vea ancha.
            rng = random.Random(11)
            meds = sorted(q([rng.choice(primas) for _ in primas], 0.5) for _ in range(2000))
            fila["mediana_ic95"] = [round(meds[50], 3), round(meds[1949], 3)]
            fila["mediana"] = round(mediana, 3)
        fila["perfil"] = len(con) >= MIN_PERFIL
        if fila["perfil"]:
            por_pos: dict[str, list[float]] = defaultdict(list)
            por_tramo: dict[str, list[float]] = defaultdict(list)
            for c in con:
                por_pos[c["posicion"] or "?"].append(c["prima"])
                por_tramo[c["tramo"]].append(c["prima"])
            fila["por_posicion"] = {k: {"n": len(v), "mediana": round(q(v, 0.5), 3)} for k, v in por_pos.items()}
            fila["por_tramo"] = {k: {"n": len(v), "mediana": round(q(v, 0.5), 3)} for k, v in por_tramo.items()}
            justas = [c for c in con if c["caja_prob_antes"] is not None and c["caja_prob_antes"] - c["lote_total"] < 0]
            holgadas = [c for c in con if c["caja_prob_antes"] is not None and c["caja_prob_antes"] - c["lote_total"] >= 0]
            fila["prima_con_credito"] = resumen([c["prima"] for c in justas])
            fila["prima_sin_credito"] = resumen([c["prima"] for c in holgadas])
        fila["compras_sobre_caja_prob"] = sum(
            1 for c in mias if c["caja_prob_antes"] is not None and c["lote_total"] > c["caja_prob_antes"]
        )
        out.append(fila)
    return out


def explicar(con_valor: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for campo in ("valor_previo", "var_dia", "puntos_recientes", "xp_previo", "rivales_con_caja", "bid_count"):
        filas = [c for c in con_valor if c[campo] is not None]
        xs = [float(c[campo]) for c in filas]
        ys = [c["prima"] for c in filas]
        terc = {}
        if len(filas) >= 9:
            corte1, corte2 = q(xs, 1 / 3), q(xs, 2 / 3)
            grupos = {"bajo": [], "medio": [], "alto": []}
            for x, y in zip(xs, ys):
                grupos["bajo" if x <= corte1 else ("medio" if x <= corte2 else "alto")].append(y)
            terc = {k: {"n": len(v), "mediana_prima": round(q(v, 0.5), 3) if v else None} for k, v in grupos.items()}
        out[campo] = {"n": len(filas), "spearman": spearman(xs, ys), "terciles": terc}
    return out


def main() -> dict[str, Any]:
    eventos = actividad()
    with open(OUT / "caja_resultados.json", encoding="utf-8") as fh:
        caja = json.load(fh)
    caja["cajas_en_cierre"] = cajas_en_cierre(eventos, caja)
    todas = compras(eventos, caja)
    con_valor = [c for c in todas if c["prima"] is not None]
    rivales = [c for c in con_valor if not c["propia"]]
    justas = [c for c in rivales if c["caja_prob_antes"] is not None and c["caja_prob_antes"] < c["lote_total"]]
    holgadas = [c for c in rivales if c["caja_prob_antes"] is not None and c["caja_prob_antes"] >= c["lote_total"]]
    credito = {"con_credito": resumen([c["prima"] for c in justas]), "sin_credito": resumen([c["prima"] for c in holgadas])}
    sesgo = {
        "una_puja": resumen([c["prima"] for c in con_valor if c["bid_count"] == 1]),
        "varias_pujas": resumen([c["prima"] for c in con_valor if c["bid_count"] is not None and c["bid_count"] >= 2]),
        "cero_vistas": resumen([c["prima"] for c in con_valor if c["bid_count"] == 0]),
    }
    agrupado = {}
    for campo in ("equipo", "posicion", "tramo", "dia_semana"):
        g: dict[str, list[float]] = defaultdict(list)
        for c in con_valor:
            g[str(c[campo])].append(c["prima"])
        agrupado[campo] = {k: resumen(v) for k, v in sorted(g.items())}
    res = {
        "compras": len(todas),
        "con_valor_previo": len(con_valor),
        "sin_valor_previo": len(todas) - len(con_valor),
        "foto_mismo_dia_antes_del_cierre": sum(1 for c in con_valor if c["foto_mismo_dia"]),
        "edad_foto_h": resumen([c["edad_foto_h"] for c in con_valor]),
        "sin_valor_por_dia": _contar([c["dia"] for c in todas if c["prima"] is None]),
        "con_valor_por_dia": _contar([c["dia"] for c in con_valor]),
        "prima_todas": resumen([c["prima"] for c in con_valor]),
        "prima_rivales": resumen([c["prima"] for c in rivales]),
        "prima_propias": resumen([c["prima"] for c in con_valor if c["propia"]]),
        "con_bid_count": sum(1 for c in con_valor if c["bid_count"] is not None),
        "sesgo_ganador": sesgo,
        "prima_segun_caja_rivales": credito,
        "anuncios": anuncios_sin_venta(eventos),
        "agrupado": agrupado,
        "perfiles": perfiles(todas, eventos),
        "explicacion": explicar(con_valor),
        "probabilidad": probabilidad(con_valor),
        "probabilidad_solo_rivales": probabilidad(rivales),
        "mis_pujas": mis_pujas(),
        "detalle": todas,
    }
    with open(OUT / "pujas_resultados.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    return res


def _contar(xs: list[str]) -> dict[str, int]:
    d: dict[str, int] = defaultdict(int)
    for x in xs:
        d[x] += 1
    return dict(sorted(d.items()))


def cajas_en_cierre(eventos: list[dict[str, Any]], caja: dict[str, Any]) -> dict[str, dict[str, dict[str, int]]]:
    """Caja probable/mín/máx de cada equipo justo antes de cada cierre con compras."""
    import caja as cj

    cierres = sorted({cierre_de(e["at"].astimezone(MADRID).date()) - timedelta(seconds=1) for e in eventos if e["kind"] == "buy"})
    subidas = caja["subidas_detalle"]
    tasa = caja["video"]["tasa"]
    bloqueos = cj.bloqueos_con_premio(eventos)
    out: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
    for team in NOMBRE:
        c_prob = [
            (datetime.fromisoformat(s["day"]).replace(hour=12, tzinfo=MADRID), s["coste"])
            for s in subidas if s["team_id"] == team and s["tipo"].startswith("manual")
        ]
        r = cj.simular(team, eventos, c_prob, tasa, bloqueos.get(team, []), cj.AHORA, con_suelos=True, marcas=cierres)
        for i, t in enumerate(cierres):
            out[(t + timedelta(seconds=1)).isoformat()][team] = {"prob": r["marcas"].get(i)}
    return out


def imprimir(r: dict[str, Any]) -> None:
    print("compras", r["compras"], "con valor previo", r["con_valor_previo"], "mismo día antes del cierre", r["foto_mismo_dia_antes_del_cierre"])
    print("edad foto", r["edad_foto_h"])
    print("sin valor por día", r["sin_valor_por_dia"])
    print("prima todas", r["prima_todas"])
    print("prima rivales", r["prima_rivales"])
    print("prima propias", r["prima_propias"])
    print("con bid_count", r["con_bid_count"], r["sesgo_ganador"])
    print("anuncios", r["anuncios"])
    for campo, g in r["agrupado"].items():
        print(campo)
        for k, v in g.items():
            print("   ", k, v)
    for p in r["perfiles"]:
        print(p["equipo"], p["compras"], p["con_valor"], p.get("mediana"), p.get("mediana_ic95"), "claus", p["clausulazos_pagados"], "sobre caja", p["compras_sobre_caja_prob"])
        if p["perfil"]:
            print("    pos", p["por_posicion"], "\n    tramo", p["por_tramo"])
            print("    credito", p["prima_con_credito"], "\n    sin", p["prima_sin_credito"])
            print("    resumen", p["prima"])
    print("explicación", json.dumps(r["explicacion"], ensure_ascii=False))
    for clave in ("probabilidad", "probabilidad_solo_rivales"):
        pr = r[clave]
        print(clave, "train", pr["n_train"], pr["train_por_tramo"], "test", pr["n_test"], pr["test_por_tramo"], "bid_count", pr["train_con_bid_count"], pr["test_con_bid_count"])
        print("  curva train", pr["curva_global_train"])
        for k, v in pr["modelos"].items():
            print("  ", k, v["brier"], [(c["cubo"], c["subastas"], c["p_media"], c["frecuencia_real"], c["ic95"], c["calibrado"]) for c in v["cubos"]])
        print("  vs app global", pr["brier_menos_app_global"])
        print("  fijas", pr["pujas_fijas"])
    print("mis pujas", [x for x in r["mis_pujas"] if x["own_bid"] or x["paid_eur"]])


if __name__ == "__main__":
    imprimir(main())
    _ = m

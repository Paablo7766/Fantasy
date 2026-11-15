"""Parte 1: caja de cada equipo desde 100 M con mínimo, probable y máximo.

Uso: ``python investigacion/caja_pujas/caja.py``. Escribe ``caja_resultados.json``
en esta carpeta y nada más.

Asientos:
* feed: compras (31), ventas (33), premios (6) y clausulazos (1) con pago del
  comprador y cobro del vendedor, una vez cada uno;
* subidas de cláusula detectadas en las fotos diarias de cláusulas. Una subida
  que deja la cláusula exactamente en el valor de mercado del día es el suelo
  automático (cláusula >= valor) y no cuesta; una que la deja por encima cuesta
  la mitad del aumento (regla 1:2);
* vídeos: 100.000 € por día, ni uno (mínimo), a la tasa que calibra la caja
  propia (probable) o todos (máximo).

Suelos legales (solo suben la caja): antes de pagar una cláusula la caja era al
menos el importe, y al empezar una jornada que dio premio la caja era >= 0.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datos import (  # noqa: E402
    CACHE,
    CREDITO,
    INICIAL,
    LOCAL,
    MADRID,
    MULT_CLAUSULA,
    NOMBRE,
    OUT,
    PROPIO,
    VIDEO_DIA,
    actividad,
    cajas_propias,
    fotos_clausulas,
    fotos_valor,
    from_ts,
    load_json,
    m,
    parse_at,
    subidas_registradas,
)

INICIO_LIGA = date(2026, 10, 13)  # altas (tipo 9) del 13-oct
AHORA = parse_at("2026-11-15T14:45:14+01:00")  # última caja propia observada
CORTE_TABLA = parse_at("2026-11-09T11:03:32+01:00")  # último asiento de cash_ledgers
TOLERANCIA_AUTO = 1_000  # € entre cláusula y valor del día para llamarla automática


# --- Subidas de cláusula -----------------------------------------------------

def _valor_del_dia(fotos: dict[str, list], pid: str, day: str) -> int | None:
    same = [f for f in fotos.get(pid, []) if f[1] == day]
    if same:
        return same[-1][2]
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    same = [f for f in fotos.get(pid, []) if f[1] == prev]
    return same[-1][2] if same else None


def detectar_subidas(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Subidas a partir de las fotos de cláusulas, equipo a equipo.

    Base de cada jugador en una foto:
    * estaba en la foto anterior del mismo equipo y no cambió de dueño: esa cláusula;
    * llegó por compra o clausulazo desde la foto anterior: el precio pagado
      (la cláusula nace en el precio; lo confirman los clausulazos posteriores);
    * aparece en la primera foto sin compra en el feed: es del reparto inicial y
      su base no se conoce. El exceso sobre el valor del día solo cuenta en el mínimo.
    """
    fotos = fotos_clausulas()
    valores = fotos_valor()
    adquisiciones: dict[tuple[str, str], list[tuple[datetime, int]]] = defaultdict(list)
    for e in eventos:
        if e["kind"] in ("buy", "clause_paid") and e["player_id"]:
            adquisiciones[(e["team_id"], e["player_id"])].append((e["at"], e["amount"]))
    dias = []
    for day in sorted(fotos):
        # Una foto idéntica, equipo a equipo, a otra anterior es una copia de caché
        # (el 25-oct y el 3-nov repiten el 24-oct). Con ella, una subida ya medida
        # parecía deshacerse y volver a cobrarse.
        if any(all(fotos[prev].get(t) == v for t, v in fotos[day].items()) for prev in dias):
            continue
        dias.append(day)
    out: list[dict[str, Any]] = []
    previa: dict[str, tuple[str, dict[str, int]]] = {}
    techo: dict[tuple[str, str], int] = {}
    for day in dias:
        instante = datetime.fromisoformat(day).replace(hour=23, minute=59, tzinfo=MADRID)
        for team, jugadores in fotos[day].items():
            antes_dia, antes = previa.get(team, (None, {}))
            antes_inst = (
                datetime.fromisoformat(antes_dia).replace(hour=23, minute=59, tzinfo=MADRID) if antes_dia else None
            )
            for pid, clausula in jugadores.items():
                valor = _valor_del_dia(valores, pid, day)
                compras = [a for a in adquisiciones.get((team, pid), []) if a[0] <= instante]
                nueva = [a for a in compras if antes_inst is None or a[0] > antes_inst]
                if nueva:
                    techo.pop((team, pid), None)
                if pid in antes and not nueva:
                    base, origen = max(antes[pid], techo.get((team, pid), 0)), "foto_anterior"
                elif compras:
                    base, origen = max(compras[-1][1], techo.get((team, pid), 0)), "precio_pagado"
                elif antes_dia is None:
                    base, origen = None, "reparto"
                else:
                    # Aparece sin compra en el feed después de la primera foto: hueco de fotos.
                    base, origen = None, "sin_base"
                fila = {
                    "team_id": team,
                    "player_id": pid,
                    "day": day,
                    "from_day": antes_dia,
                    "clausula": clausula,
                    "base": base,
                    "origen_base": origen,
                    "valor_dia": valor,
                }
                if base is not None:
                    techo[(team, pid)] = max(techo.get((team, pid), 0), clausula)
                if base is None:
                    exceso = clausula - valor if valor else None
                    if exceso and exceso > TOLERANCIA_AUTO:
                        out.append({**fila, "tipo": "ambigua", "aumento": exceso, "coste": int(exceso * MULT_CLAUSULA)})
                    continue
                if clausula <= base:
                    continue
                if valor is not None and abs(clausula - valor) <= TOLERANCIA_AUTO:
                    out.append({**fila, "tipo": "automatica", "aumento": clausula - base, "coste": 0})
                    continue
                piso = max(base, valor or 0)
                aumento = clausula - piso
                if aumento <= TOLERANCIA_AUTO:
                    continue
                out.append(
                    {
                        **fila,
                        "tipo": "manual" if valor is not None else "manual_sin_valor",
                        "aumento": aumento,
                        "coste": int(aumento * MULT_CLAUSULA),
                        "aumento_alto": clausula - base,
                        "coste_alto": int((clausula - base) * MULT_CLAUSULA),
                    }
                )
            previa[team] = (day, dict(jugadores))
    return out


def comparar_con_registro(detectadas: list[dict[str, Any]]) -> dict[str, Any]:
    reg = subidas_registradas()
    valores = fotos_valor()
    auto = manual = 0
    coste_reg_guardado = defaultdict(int)
    for r in reg:
        v = _valor_del_dia(valores, r["player_id"], r["day"])
        if v is not None and abs(r["clause_after_eur"] - v) <= TOLERANCIA_AUTO:
            auto += 1
        else:
            manual += 1
        coste_reg_guardado[r["team_id"]] += int(r.get("cost_eur") or 0)
    claves_reg = {(r["team_id"], r["player_id"], r["day"]) for r in reg}
    claves_det = {(d["team_id"], d["player_id"], d["day"]) for d in detectadas if d["tipo"] in ("manual", "automatica")}
    return {
        "filas_registro": len(reg),
        "registro_automaticas": auto,
        "registro_manuales": manual,
        "coincidentes": len(claves_reg & claves_det),
        "solo_registro": len(claves_reg - claves_det),
        "solo_fotos": len(claves_det - claves_reg),
        "coste_guardado_por_equipo": dict(coste_reg_guardado),
    }


# --- Libro con suelos ---------------------------------------------------------

def bloqueos_con_premio(eventos: list[dict[str, Any]]) -> dict[str, list[datetime]]:
    """Inicio de cada jornada que dio premio al equipo (premio > 0 => puntuó => caja >= 0).

    ``calendario_competiciones_2627.json`` no vale aquí: pone la J13 el 10-nov y
    empezó el 20. La J12 empezó el sábado 7-nov a las 14:00 (``matchday_snapshot_log``).
    De J9 a J11 no hay saque guardado: se usa el sábado a las 14:00 anterior al
    premio. Si empezó el viernes, el suelo real es más estricto que este; así el
    mínimo no se exagera.
    """
    saque = {
        9: datetime(2026, 10, 17, 14, 0, tzinfo=MADRID),
        10: datetime(2026, 10, 24, 14, 0, tzinfo=MADRID),
        11: datetime(2026, 10, 31, 14, 0, tzinfo=MADRID),
        12: datetime(2026, 11, 7, 14, 0, tzinfo=MADRID),
    }
    out: dict[str, list[datetime]] = defaultdict(list)
    for e in eventos:
        if e["kind"] == "prize" and e["amount"] > 0 and e.get("week") in saque:
            out[e["team_id"]].append(saque[e["week"]])
    return out


def videos_hasta(t: datetime) -> int:
    dias = (t.astimezone(MADRID).date() - INICIO_LIGA).days + 1
    return max(0, dias) * VIDEO_DIA


def simular(
    team: str,
    eventos: list[dict[str, Any]],
    costes: list[tuple[datetime, int]],
    tasa_video: float,
    bloqueos: list[datetime],
    hasta: datetime,
    *,
    con_suelos: bool,
    marcas: list[datetime] | None = None,
) -> dict[str, Any]:
    """Recorre el libro del equipo hasta ``hasta``. Devuelve caja, alzas y cajas en ``marcas``."""
    linea: list[tuple[datetime, int, str, int, dict[str, Any]]] = []
    for e in eventos:
        if e["team_id"] == team and e["at"] <= hasta:
            linea.append((e["at"], 1, e["kind"], e["signed"], e))
    for at, coste in costes:
        if at <= hasta:
            linea.append((at, 1, "subida", -coste, {}))
    if tasa_video > 0:
        d = INICIO_LIGA
        while d <= hasta.date():
            at = datetime(d.year, d.month, d.day, 0, 1, tzinfo=MADRID)
            if at <= hasta:
                linea.append((at, 0, "video", int(round(VIDEO_DIA * tasa_video)), {}))
            d += timedelta(days=1)
    for b in bloqueos:
        if b <= hasta:
            linea.append((b, 2, "bloqueo", 0, {}))
    for i, mk in enumerate(marcas or []):
        linea.append((mk, 3, "marca", i, {}))
    linea.sort(key=lambda x: (x[0], x[1]))
    caja = INICIAL
    alzas: list[dict[str, Any]] = []
    en_marca: dict[int, int] = {}
    antes_de: dict[str, int] = {}
    for at, _o, kind, signed, ev in linea:
        if kind == "marca":
            en_marca[signed] = caja
            continue
        if kind == "bloqueo":
            if con_suelos and caja < 0:
                alzas.append({"at": at.isoformat(), "motivo": "jornada con premio", "alza": -caja})
                caja = 0
            continue
        if kind == "clause_paid" and con_suelos and caja < ev["amount"]:
            alzas.append({"at": at.isoformat(), "motivo": "clausulazo pagado", "alza": ev["amount"] - caja})
            caja = ev["amount"]
        if ev.get("id") and kind in ("buy", "clause_paid"):
            antes_de[f"{ev['id']}"] = caja
        caja += signed
    return {"caja": caja, "alzas": alzas, "alzado": sum(a["alza"] for a in alzas), "marcas": en_marca, "antes_de": antes_de}


# --- Calibración del vídeo con la caja propia -------------------------------

def libro_propio(eventos: list[dict[str, Any]], t: datetime) -> int:
    return INICIAL + sum(e["signed"] for e in eventos if e["team_id"] == PROPIO and e["at"] <= t)


def fechar_cajas_propias(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cada saldo propio con el instante del libro al que mejor encaja.

    La caja de ``auditoria_lunes`` sale de la ficha cacheada: puede ser de horas
    o días antes de ``guardado_en``. Se prueba el libro en cada asiento propio de
    los cuatro días previos y se queda el que deja el residual más cerca del de
    la última foto aceptada. Si no es el instante de guardado, se marca cacheada.
    """
    obs = cajas_propias()
    propios = sorted({e["at"] for e in eventos if e["team_id"] == PROPIO})
    ref = None
    out = []
    for o in obs:
        t = o["at"]
        candidatos = [t] + [a - timedelta(seconds=1) for a in propios if t - timedelta(days=4) < a <= t]
        filas = [(c, o["caja"] - libro_propio(eventos, c)) for c in candidatos]
        if ref is None:
            elegido = filas[0]
        else:
            elegido = min(filas, key=lambda f: (abs(f[1] - ref), f[0] != t))
        cacheada = elegido[0] != t
        ref = elegido[1]
        out.append(
            {
                "guardado": t.isoformat(),
                "fuente": o["fuente"],
                "caja": o["caja"],
                "libro_en_guardado": libro_propio(eventos, t),
                "residual_en_guardado": o["caja"] - libro_propio(eventos, t),
                "instante_libro": elegido[0].isoformat(),
                "residual": elegido[1],
                "cacheada": cacheada,
            }
        )
    return out


def calibrar_video(fechadas: list[dict[str, Any]], subidas: list[dict[str, Any]]) -> dict[str, Any]:
    """Tasa de vídeo = (variación del residual + subidas manuales propias) / vídeos posibles.

    Solo vale una ventana donde el registro de cláusulas ya cubre el equipo
    propio (fotos desde el 24-oct, pero sin filas propias hasta el 3-nov) y con
    las dos puntas frescas. Se usa la más larga: 6-nov 22:52 → 15-nov 14:45.
    """
    frescas = [f for f in fechadas if not f["cacheada"]]
    a = next(f for f in frescas if f["guardado"].startswith("2026-11-06"))
    b = frescas[-1]
    ta, tb = datetime.fromisoformat(a["instante_libro"]), datetime.fromisoformat(b["instante_libro"])
    manual = sum(
        s["coste"]
        for s in subidas
        if s["team_id"] == PROPIO and s["tipo"].startswith("manual") and ta.date() < date.fromisoformat(s["day"]) <= tb.date()
    )
    auto = sum(
        int(s["aumento"] * MULT_CLAUSULA)
        for s in subidas
        if s["team_id"] == PROPIO and s["tipo"] == "automatica" and ta.date() < date.fromisoformat(s["day"]) <= tb.date()
    )
    dias = (tb - ta).total_seconds() / 86400.0
    delta = b["residual"] - a["residual"]
    bruta = (delta + manual) / (dias * VIDEO_DIA)
    return {
        "desde": a["guardado"],
        "hasta": b["guardado"],
        "dias": round(dias, 2),
        "delta_residual": delta,
        "subidas_manuales_propias": manual,
        "tasa_bruta": round(bruta, 3),
        "tasa": round(min(1.0, max(0.0, bruta)), 3),
        "tasa_si_las_automaticas_costaran": round((delta + manual + auto) / (dias * VIDEO_DIA), 2),
    }


# --- Chequeo de pujas ganadas -------------------------------------------------

def chequeo_pujas(eventos, sims) -> list[dict[str, Any]]:
    """Compras del mismo equipo al mismo cierre: la suma tuvo que caber en caja + crédito."""
    lotes: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for e in eventos:
        if e["kind"] == "buy":
            lotes[(e["team_id"], e["at"].replace(second=0))].append(e)
    out = []
    for (team, at), compras in sorted(lotes.items(), key=lambda x: x[0][1]):
        total = sum(c["amount"] for c in compras)
        primero = min(compras, key=lambda c: (c["at"], c["id"]))
        caja = {k: sims[k][team]["antes_de"].get(primero["id"]) for k in ("min", "prob", "max")}
        if caja["min"] is not None and caja["min"] >= total:
            veredicto = "cubierta sin crédito"
        elif caja["prob"] is not None and caja["prob"] >= total:
            veredicto = "cubierta en el probable"
        elif caja["max"] is not None and caja["max"] >= total:
            veredicto = "solo cubierta en el máximo"
        else:
            veredicto = "usó crédito o falta un ingreso"
        out.append(
            {
                "team_id": team,
                "equipo": NOMBRE[team],
                "at": at.isoformat(),
                "compras": len(compras),
                "total": total,
                "caja_min": caja["min"],
                "caja_prob": caja["prob"],
                "caja_max": caja["max"],
                "falta_prob": max(0, total - caja["prob"]) if caja["prob"] is not None else None,
                "credito_necesario_sobre_max": max(0, total - caja["max"]) if caja["max"] is not None else None,
                "veredicto": veredicto,
            }
        )
    return out


# --- Comparación con la app -------------------------------------------------

def tabla_guardada() -> dict[str, dict[str, Any]]:
    return {r["team_id"]: r for r in load_json(LOCAL / "cash_ledgers.json")}


def calculo_vivo(own_cash: int) -> dict[str, dict[str, Any]]:
    """``books_from_activity`` en memoria, como lo llamaría hoy ``needs_from_documents``.

    Las plantillas son mínimas (id de equipo, de mánager, y la caja propia): con
    plantillas vacías ``shared_initial_is_plausible`` no descarta el residual y
    cada rival parte de 100 M, igual que con las reales (no publican caja).
    No se pasa ``snapshots``: aquí solo interesa la caja.
    """
    from datos import EQUIPOS
    from toolbox.league_history import books_from_activity, hidden_costs_from_log, parse_activity_row

    raw = load_json(CACHE / "activity_raw_log.json")
    events = [ev for ev in (parse_activity_row(r) for r in raw.values()) if ev is not None]
    squads = [
        {
            "team_id": v["team_id"],
            "manager_id": k,
            "is_self": v["team_id"] == PROPIO,
            "cash": own_cash if v["team_id"] == PROPIO else None,
            "players": [],
        }
        for k, v in EQUIPOS.items()
    ]
    ledgers, _hist = books_from_activity(squads, events, {}, hidden_costs=hidden_costs_from_log())
    return {led["team_id"]: led for led in ledgers}


def main() -> dict[str, Any]:
    eventos = actividad()
    subidas = detectar_subidas(eventos)
    registro = comparar_con_registro(subidas)
    fechadas = fechar_cajas_propias(eventos)
    video = calibrar_video(fechadas, subidas)
    bloqueos = bloqueos_con_premio(eventos)
    tasa = video["tasa"]

    def costes(team: str, tipos: tuple[str, ...], alto: bool = False) -> list[tuple[datetime, int]]:
        return [
            (
                datetime.fromisoformat(s["day"]).replace(hour=12, tzinfo=MADRID),
                s.get("coste_alto", s["coste"]) if alto else s["coste"],
            )
            for s in subidas
            if s["team_id"] == team and s["tipo"] in tipos
        ]

    # Gasto que las fotos no ven, medido en la caja propia: libro menos subidas
    # detectadas (sin vídeos, sin suelos) contra el último saldo real. Las fotos de
    # cláusulas empiezan el 24-oct y tienen un hueco del 26-oct al 1-nov; lo que se
    # subió antes, o se subió y se vendió dentro del hueco, no aparece.
    propio_sin_video = simular(
        PROPIO, eventos, costes(PROPIO, ("manual", "manual_sin_valor")), 0.0, [], AHORA, con_suelos=False
    )["caja"]
    invisible = max(0, propio_sin_video - fechadas[-1]["caja"])
    invisible_at = datetime(2026, 10, 20, 12, 0, tzinfo=MADRID)

    variantes = {
        # mínimo: subidas manuales al coste alto (aumento sobre la base, no sobre el valor),
        # más un gasto invisible como el tuyo, sin vídeos, con suelos.
        "min": dict(tipos=("manual", "manual_sin_valor"), alto=True, tasa=0.0, invisible=invisible),
        "prob": dict(tipos=("manual", "manual_sin_valor"), alto=False, tasa=tasa, invisible=0),
        "max": dict(tipos=("manual",), alto=False, tasa=1.0, invisible=0),
    }
    marcas = [CORTE_TABLA, AHORA]
    sims: dict[str, dict[str, Any]] = {k: {} for k in variantes}
    sims_sin_suelo: dict[str, dict[str, Any]] = {k: {} for k in variantes}
    for team in NOMBRE:
        for k, cfg in variantes.items():
            c = costes(team, cfg["tipos"], cfg["alto"])
            if cfg["invisible"] and team != PROPIO:
                c = [*c, (invisible_at, cfg["invisible"])]
            sims[k][team] = simular(team, eventos, c, cfg["tasa"], bloqueos.get(team, []), AHORA, con_suelos=True, marcas=marcas)
            sims_sin_suelo[k][team] = simular(team, eventos, c, cfg["tasa"], [], AHORA, con_suelos=False, marcas=marcas)

    tabla = tabla_guardada()
    propio_obs = fechadas[-1]["caja"]
    vivo = calculo_vivo(propio_obs)

    filas = []
    for team in NOMBRE:
        libro_ahora = INICIAL + sum(e["signed"] for e in eventos if e["team_id"] == team and e["at"] <= AHORA)
        libro_corte = INICIAL + sum(e["signed"] for e in eventos if e["team_id"] == team and e["at"] <= CORTE_TABLA)
        s = {k: sims[k][team] for k in variantes}
        manual_corte = sum(
            c for at, c in costes(team, ("manual", "manual_sin_valor")) if at <= CORTE_TABLA
        )
        manual_ahora = sum(c for at, c in costes(team, ("manual", "manual_sin_valor")) if at <= AHORA)
        ambigua = sum(c for _, c in costes(team, ("ambigua",), True))
        alto_extra = sum(c for _, c in costes(team, ("manual", "manual_sin_valor"), True)) - manual_ahora
        prob_corte = s["prob"]["marcas"][0]
        t_row = tabla.get(team, {})
        tabla_caja = t_row.get("reconstructed_cash_eur")
        tabla_libro_ok = None
        if t_row:
            tabla_libro_ok = (
                t_row["initial_budget_eur"] + t_row["premiums_eur"] + t_row["sales_eur"] - t_row["purchases_eur"] - t_row["clauses_eur"]
            ) - (libro_corte - INICIAL + t_row["initial_budget_eur"])
        videos_corte_prob = int(round(tasa * videos_hasta(CORTE_TABLA)))
        alzado_corte = s["prob"]["marcas"][0] - sims_sin_suelo["prob"][team]["marcas"][0]
        dif_tabla = (tabla_caja - prob_corte) if tabla_caja is not None else None
        atrib_tabla = {
            "inicial_contaminado": (t_row.get("initial_budget_eur", INICIAL) - INICIAL) if t_row else None,
            "asientos_distintos": tabla_libro_ok,
            "subidas_no_restadas": manual_corte,
            "videos": -videos_corte_prob,
            "suelos_no_aplicados": -alzado_corte,
        }
        if dif_tabla is not None:
            atrib_tabla["sin_explicar"] = dif_tabla - sum(v for v in atrib_tabla.values() if v is not None)
        dif_tabla_ahora = (tabla_caja - s["prob"]["caja"]) if tabla_caja is not None else None

        led = vivo.get(team, {})
        vivo_caja = led.get("observed_cash_eur") if isinstance(led.get("observed_cash_eur"), int) else led.get("reconstructed_cash_eur")
        anch = led.get("anchored") or {}
        vivo_libro = led.get("raw_reconstructed_cash_eur") if "raw_reconstructed_cash_eur" in led else vivo_caja
        atrib_vivo = None
        if team != PROPIO and vivo_caja is not None:
            alzado_ahora = s["prob"]["caja"] - sims_sin_suelo["prob"][team]["caja"]
            atrib_vivo = {
                "asientos_distintos": (vivo_libro - libro_ahora) if isinstance(vivo_libro, int) else None,
                "subidas_registro_vs_detectadas": -(anch.get("clause_raise_cost_eur", 0) - manual_ahora),
                "videos": -int(round(tasa * videos_hasta(AHORA))),
                "suelos": anch.get("lifted_eur", 0) - alzado_ahora,
            }
            atrib_vivo["sin_explicar"] = (vivo_caja - s["prob"]["caja"]) - sum(v for v in atrib_vivo.values() if v is not None)
        filas.append(
            {
                "team_id": team,
                "equipo": NOMBRE[team],
                "libro_ahora": libro_ahora,
                "min": s["min"]["caja"],
                "prob": s["prob"]["caja"],
                "max": s["max"]["caja"],
                "ancho": s["max"]["caja"] - s["min"]["caja"],
                "ancho_por": {
                    "videos": int(round((1.0 - 0.0) * videos_hasta(AHORA))),
                    "gasto_invisible": invisible if team != PROPIO else 0,
                    "reparto_ambiguo_no_usado": ambigua,
                    "coste_alto_vs_sobre_valor": alto_extra,
                    "suelos_en_min": s["min"]["alzado"],
                },
                "subidas_manuales": manual_ahora,
                "alzas_min": s["min"]["alzas"],
                "alzas_prob": s["prob"]["alzas"],
                "prob_en_corte_tabla": prob_corte,
                "tabla_9nov": tabla_caja,
                "dif_tabla_vs_prob_corte": dif_tabla,
                "atribucion_tabla": atrib_tabla,
                "dif_tabla_vs_prob_ahora": dif_tabla_ahora,
                "movimientos_tras_corte": libro_ahora - libro_corte,
                "vivo_hoy": vivo_caja,
                "vivo_inicial": led.get("initial_budget_eur"),
                "vivo_subidas_registro": anch.get("clause_raise_cost_eur"),
                "vivo_alzado": anch.get("lifted_eur"),
                "dif_vivo_vs_prob": (vivo_caja - s["prob"]["caja"]) if vivo_caja is not None else None,
                "atribucion_vivo": atrib_vivo,
            }
        )
    pujas = chequeo_pujas(eventos, sims)
    # Cajas por compra para la Parte 2.
    caja_por_compra = {
        e["id"]: {k: sims[k][e["team_id"]]["antes_de"].get(e["id"]) for k in variantes}
        for e in eventos
        if e["kind"] == "buy"
    }
    res = {
        "ahora": AHORA.isoformat(),
        "corte_tabla": CORTE_TABLA.isoformat(),
        "conteo_feed": {k: sum(1 for e in eventos if e["kind"] == k) for k in ("buy", "sell", "clause_paid", "prize")},
        "ultimo_movimiento": max(e["at"] for e in eventos).isoformat(),
        "subidas": {
            "detectadas": {t: sum(1 for s in subidas if s["tipo"] == t) for t in ("manual", "manual_sin_valor", "automatica", "ambigua")},
            "coste_manual_por_equipo": {
                NOMBRE[t]: sum(s["coste"] for s in subidas if s["team_id"] == t and s["tipo"].startswith("manual")) for t in NOMBRE
            },
            "registro": registro,
        },
        "cajas_propias": fechadas,
        "video": video,
        "gasto_invisible_propio": invisible,
        "propio_libro_menos_subidas": propio_sin_video,
        "equipos": filas,
        "pujas_ganadas": pujas,
        "caja_por_compra": caja_por_compra,
        "subidas_detalle": subidas,
    }
    with open(OUT / "caja_resultados.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    return res


def imprimir(res: dict[str, Any]) -> None:
    print("feed", res["conteo_feed"], "último", res["ultimo_movimiento"])
    print("subidas", res["subidas"]["detectadas"])
    print("registro", {k: v for k, v in res["subidas"]["registro"].items() if k != "coste_guardado_por_equipo"})
    for f in res["cajas_propias"]:
        print(
            " propia", f["guardado"][:16], f["fuente"], m(f["caja"]), "resid", m(f["residual"]),
            "cacheada" if f["cacheada"] else "", f["instante_libro"][:16] if f["cacheada"] else "",
        )
    print("video", res["video"])
    print(f"{'equipo':18} {'libro':>7} {'min':>7} {'prob':>7} {'max':>7} {'ancho':>6} {'tabla':>7} {'dT':>6} {'vivo':>7} {'dV':>6}")
    for f in res["equipos"]:
        print(
            f"{f['equipo'][:18]:18} {m(f['libro_ahora']):>7} {m(f['min']):>7} {m(f['prob']):>7} {m(f['max']):>7} "
            f"{m(f['ancho']):>6} {m(f['tabla_9nov']):>7} {m(f['dif_tabla_vs_prob_corte']):>6} {m(f['vivo_hoy']):>7} {m(f['dif_vivo_vs_prob']):>6}"
        )
        print("    ancho:", {k: m(v) for k, v in f["ancho_por"].items()})
        print("    tabla:", {k: m(v) for k, v in f["atribucion_tabla"].items()})
        if f["atribucion_vivo"]:
            print("    vivo :", {k: m(v) for k, v in f["atribucion_vivo"].items()})
    from collections import Counter

    print("pujas", Counter(p["veredicto"] for p in res["pujas_ganadas"]))
    for p in res["pujas_ganadas"]:
        if p["veredicto"] in ("usó crédito o falta un ingreso", "solo cubierta en el máximo"):
            print("  ", p["equipo"], p["at"][:16], p["compras"], m(p["total"]), "min", m(p["caja_min"]), "prob", m(p["caja_prob"]), "max", m(p["caja_max"]), p["veredicto"])


if __name__ == "__main__":
    imprimir(main())
    _ = (CREDITO, from_ts)

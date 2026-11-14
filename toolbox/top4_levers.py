"""Decisiones medidas en probabilidad de top 4, no en euros.

Cuelga del plan ya calculado y no toca el solver: lee el once esperado y las
mejoras de xP que el plan ya publica y las traduce a «cuánto sube (o baja) la
probabilidad de quedar entre los 4 primeros de la jornada».

* ``acciones``: cada fichaje del plan.
* ``ventas``: cada venta posible (lo que pierde el once sin ese jugador).
* ``plantilla_minima``: la regla que hay que cumplir antes de comprar para revender.
* ``postura``: seguro si llegas por encima del corte, techo si llegas por debajo.
* ``blindaje``: a quién proteger primero según lo que baja la probabilidad si te lo quitan.
"""

from __future__ import annotations

from itertools import product
from typing import Any

from toolbox.analyzer import FORMATIONS
from toolbox.top4 import MIN_PLAYERS, TOP_N, _number, model_from_race

# Plantilla mínima para poder comprar con ánimo de revender.
MIN_PLANTILLA = 13
MAX_PLANTILLA = 14
MIN_DELANTEROS_TITULARES = 2
P_TITULAR_FIABLE = 0.5
P_TITULAR_TITULAR = 0.6
LINEAS = ("POR", "DEF", "MC", "DEL")
# Esqueleto mínimo del once por línea (el de 5-3-2 / 3-4-3 más ajustado).
SLOTS_MINIMOS = {"POR": 1, "DEF": 3, "MC": 3, "DEL": 1}
# Margen en puntos esperados (en desviaciones) para pasar de postura neutra a
# una de las dos: dentro de ±0,25 σ del corte no se apuesta a ningún lado.
MARGEN_POSTURA_SIGMA = 0.25
# Compra que cuenta como titular a efectos de la plantilla mínima.
MEJORA_TITULAR = 0.5


def plantilla_minima(
    players: list[dict[str, Any]],
    compras: list[dict[str, Any]] | None = None,
    ventas: int = 0,
) -> dict[str, Any]:
    """¿Se puede comprar para revender? 13-14 jugadores, 2 DEL titulares y recambio por línea.

    ``players``: plantilla actual con ``position`` y ``p_titular``. ``compras``:
    fichajes que el plan ya ejecuta para jugar (cuentan como titulares fiables).
    """
    pool = [
        {"position": p.get("position"), "p": _number(p.get("p_titular")) if _number(p.get("p_titular")) is not None else 0.0}
        for p in players
        if isinstance(p, dict)
    ]
    for compra in compras or []:
        pool.append({"position": compra.get("posicion") or compra.get("position"), "p": 0.8})
    total = max(0, len(pool) - max(0, ventas))
    faltan: list[str] = []
    if total < MIN_PLANTILLA:
        faltan.append(f"Tienes {total} jugadores: hacen falta {MIN_PLANTILLA}-{MAX_PLANTILLA} antes de comprar para revender.")
    delanteros = sum(1 for p in pool if p["position"] == "DEL" and p["p"] >= P_TITULAR_TITULAR)
    if delanteros < MIN_DELANTEROS_TITULARES:
        faltan.append(f"Solo {delanteros} delantero(s) titular(es) fiable(s): hacen falta {MIN_DELANTEROS_TITULARES}.")
    lineas: dict[str, dict[str, int]] = {}
    for linea in LINEAS:
        fiables = sum(1 for p in pool if p["position"] == linea and p["p"] >= P_TITULAR_FIABLE)
        necesarios = SLOTS_MINIMOS[linea] + 1
        lineas[linea] = {"fiables": fiables, "necesarios": necesarios}
        if fiables < necesarios:
            faltan.append(f"{linea}: {fiables} fiable(s), hace falta {necesarios} para tener recambio.")
    return {
        "cumple": not faltan,
        "jugadores": total,
        "delanteros_titulares": delanteros,
        "lineas": lineas,
        "faltan": faltan,
    }


PROB_DESCONOCIDA = 0.5
MAX_PUJAS_ENUMERADAS = 8


def _prob_ganar(plan: dict[str, Any]) -> dict[str, float]:
    """``win_probability`` de la puja que se recomienda, por jugador (mercado + bid_war)."""
    out: dict[str, float] = {}
    for row in plan.get("decisions") or []:
        if isinstance(row, dict) and isinstance(row.get("player_id"), str):
            p = _number(row.get("win_probability"))
            if p is not None:
                out[row["player_id"]] = max(0.0, min(1.0, p))
    return out


def completa_once(players: list[dict[str, Any]], posicion: str | None) -> bool:
    """¿Con este fichaje la plantilla puede formar un once legal de 11?"""
    counts: dict[Any, int] = {}
    for p in players:
        counts[p.get("position")] = counts.get(p.get("position"), 0) + 1
    if posicion:
        counts[posicion] = counts.get(posicion, 0) + 1
    return any(all(counts.get(pos, 0) >= need for pos, need in slots.items()) for slots in FORMATIONS.values())


def _producto(valores: Any) -> float:
    total = 1.0
    for v in valores:
        total *= v
    return total


def escenarios_pujas(
    model: Any,
    pujas: list[dict[str, Any]],
    puntos_once: float,
    mejora_total: float,
    jugadores_base: int,
) -> dict[str, Any]:
    """Probabilidad de top 4 repartida entre ganar o perder cada puja.

    Las subastas se resuelven a la vez y son independientes. Con cada subconjunto
    ganado S, el once suma ``puntos_once`` menos la parte de las mejoras que no
    llegan (reescalada para que ganarlas todas dé ``puntos_once``). Si tras S no
    hay 11 jugadores, la jornada vale 0.
    """
    pujas = pujas[:MAX_PUJAS_ENUMERADAS]
    suma = sum(p["mejora"] for p in pujas) or 1.0
    escala = mejora_total / suma if mejora_total else 1.0
    esperado = 0.0
    for gana in product((False, True), repeat=len(pujas)):
        prob = 1.0
        perdidas = 0.0
        ganadas = 0
        for won, p in zip(gana, pujas):
            prob *= p["prob"] if won else 1.0 - p["prob"]
            if won:
                ganadas += 1
            else:
                perdidas += p["mejora"]
        esperado += prob * model.p(puntos_once - escala * perdidas, void=jugadores_base + ganadas < MIN_PLAYERS)
    mejor = max(pujas, key=lambda p: p["prob"]) if pujas else None
    solo_mejor = None
    if mejor is not None:
        perdidas = sum(p["mejora"] for p in pujas if p is not mejor)
        solo_mejor = {
            "nombre": mejor["nombre"],
            "prob_ganar": round(mejor["prob"], 4),
            "p_top4": round(model.p(puntos_once - escala * perdidas, void=jugadores_base + 1 < MIN_PLAYERS), 4),
        }
    return {
        "p_esperado": round(esperado, 4),
        "p_si_ganas_todas": round(model.p(puntos_once, void=jugadores_base + len(pujas) < MIN_PLAYERS), 4),
        "prob_ganar_todas": round(_producto(p["prob"] for p in pujas), 4),
        "prob_ganar_ninguna": round(_producto(1.0 - p["prob"] for p in pujas), 4),
        "solo_mas_probable": solo_mejor,
    }


def postura(mu: float, cutoff: float, sigma: float) -> dict[str, Any]:
    """Seguro por encima del corte, techo por debajo, equilibrado entre medias."""
    margen = MARGEN_POSTURA_SIGMA * sigma
    gap = mu - cutoff
    if gap > margen:
        nombre, texto = "seguro", "Llegas por encima del corte: once de titulares seguros, capitán de suelo alto."
    elif gap < -margen:
        nombre, texto = "techo", "Llegas por debajo del corte: jugadores de techo alto y capitán de remontada."
    else:
        nombre, texto = "neutro", "Estás en el corte: equilibra suelo y techo."
    return {"nombre": nombre, "texto": texto, "gap_xp": round(gap, 2), "margen_xp": round(margen, 2)}


def build_overlay(
    plan: dict[str, Any],
    race: dict[str, Any] | None,
    rounds: dict[int, dict[str, int]] | None,
    players: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    ctx = model_from_race(race, rounds)
    if ctx is None:
        return {"ok": False, "reason": "sin_tabla"}
    model, mu, count = ctx["model"], ctx["mu"], ctx["players"]
    void = count < MIN_PLAYERS
    faltan = max(0, MIN_PLAYERS - count)
    xi = ctx["xi"]
    values = [v for v in (_number(r.get("expected_points")) for r in xi) if v is not None]
    fill = min(values) if values else 0.0
    base_completo = mu + faltan * fill
    p_real = model.p(mu, void=void)
    p_completo = model.p(base_completo)

    fichajes = plan.get("plan_fichajes") if isinstance(plan.get("plan_fichajes"), dict) else {}
    acciones = []
    ganar = _prob_ganar(plan)
    for a in fichajes.get("acciones") or []:
        if not isinstance(a, dict):
            continue
        mejora = _number(a.get("mejora_neta"))
        if mejora is None:
            continue
        despues = model.p(base_completo + mejora)
        es_puja = a.get("tipo") == "PUJA"
        prob = ganar.get(a.get("player_id"), PROB_DESCONOCIDA) if es_puja else 1.0
        acciones.append(
            {
                "prob_ganar": round(prob, 4),
                "prob_conocida": (not es_puja) or a.get("player_id") in ganar,
                "delta_p_si_ganas": round(despues - p_completo, 4),
                "delta_p_ponderado": round(prob * (despues - p_completo), 4),
                "player_id": a.get("player_id"),
                "nombre": a.get("nombre"),
                "tipo": a.get("tipo"),
                "mejora_xp": round(mejora, 2),
                "p_antes": round(p_completo, 4),
                "p_despues": round(despues, 4),
                "delta_p": round(despues - p_completo, 4),
                "euros": a.get("euros"),
            }
        )
    acciones.sort(key=lambda r: -r["delta_p_ponderado"])

    puntos_once = _number(fichajes.get("puntos_once"))
    compras_hoy = [a for a in fichajes.get("acciones") or [] if isinstance(a, dict) and a.get("tipo") in ("PUJA", "CLAUSULAZO")]
    ventas_hoy = [a for a in fichajes.get("acciones") or [] if isinstance(a, dict) and a.get("tipo") in ("VENDE", "VENDER HOY", "VENTA")]
    despues_jugadores = count + len(compras_hoy) - len(ventas_hoy)
    plan_total = None
    if puntos_once is not None:
        pujas = [
            {
                "nombre": x.get("nombre"),
                "mejora": _number(x.get("mejora_neta")) or 0.0,
                "prob": ganar.get(x.get("player_id"), PROB_DESCONOCIDA),
            }
            for x in compras_hoy
            if x.get("tipo") == "PUJA"
        ]
        seguras = len(compras_hoy) - len(pujas)
        # Las ``mejora_neta`` se miden contra ``puntos_once_referencia``. Con
        # plantilla incompleta ``puntos_once_actual`` es 0 y «mejora_puntos_jornada»
        # vale el once entero: escalar con ella triplicaba lo que resta cada puja perdida.
        referencia = _number(fichajes.get("puntos_once_referencia"))
        if referencia is not None:
            mejora_total = max(0.0, puntos_once - referencia)
        elif void:
            mejora_total = 0.0
        else:
            mejora_total = _number(fichajes.get("mejora_puntos_jornada")) or 0.0
        esc = escenarios_pujas(model, pujas, puntos_once, mejora_total, count - len(ventas_hoy) + seguras)
        plan_total = {
            "puntos_once": round(puntos_once, 2),
            "jugadores_despues": despues_jugadores,
            "p_antes": round(p_real, 4),
            # Ponderado por la probabilidad de ganar cada puja.
            "p_despues": esc["p_esperado"],
            "delta_p": round(esc["p_esperado"] - p_real, 4),
            "p_si_ganas_todas": esc["p_si_ganas_todas"],
            "prob_ganar_todas": esc["prob_ganar_todas"],
            "prob_ganar_ninguna": esc["prob_ganar_ninguna"],
            "solo_mas_probable": esc["solo_mas_probable"],
        }

    paso_1 = None
    if void:
        candidatas = [
            x
            for x in compras_hoy
            if x.get("tipo") == "PUJA" and completa_once(players or [], x.get("posicion") or x.get("position"))
        ]
        candidatas.sort(key=lambda x: -ganar.get(x.get("player_id"), PROB_DESCONOCIDA))
        if candidatas:
            primera = candidatas[0]
            respaldo = candidatas[1] if len(candidatas) > 1 else None
            paso_1 = {
                "player_id": primera.get("player_id"),
                "nombre": primera.get("nombre"),
                "prob_ganar": round(ganar.get(primera.get("player_id"), PROB_DESCONOCIDA), 4),
                "respaldo": respaldo.get("nombre") if respaldo else None,
                "texto": (
                    f"Tienes {count} jugadores y con menos de {MIN_PLAYERS} la jornada puntúa 0. "
                    f"Primero asegura al n.º {MIN_PLAYERS}: puja por {primera.get('nombre')}, la que más probabilidad tiene de ganarse."
                ),
            }
            for x in fichajes.get("acciones") or []:
                if x.get("player_id") == primera.get("player_id"):
                    x["paso"] = 1
                    x["asegura_jugador_11"] = True
            fichajes["acciones"] = sorted(
                fichajes.get("acciones") or [], key=lambda x: 0 if x.get("player_id") == primera.get("player_id") else 1
            )
        else:
            paso_1 = {"player_id": None, "texto": f"Ninguna puja del plan completa un once legal: con {count} jugadores la jornada puntúa 0."}

    ventas = []
    for row in plan.get("auditoria_ventas") or []:
        if not isinstance(row, dict):
            continue
        pierde = _number(row.get("tu_once_pierde_sin_el"))
        if pierde is None:
            continue
        sin = model.p(base_completo - pierde)
        ventas.append(
            {
                "player_id": row.get("player_id"),
                "nombre": row.get("nombre"),
                "pierde_xp": round(pierde, 2),
                "p_si_vendes": round(sin, 4),
                "delta_p": round(sin - p_completo, 4),
            }
        )
    ventas.sort(key=lambda r: r["delta_p"])

    blindaje = []
    asesor = plan.get("asesor_clausulas") if isinstance(plan.get("asesor_clausulas"), dict) else {}
    vistos: set[str] = set()
    for grupo in ("proteger", "preparar"):
        for row in asesor.get(grupo) or []:
            if not isinstance(row, dict) or str(row.get("player_id")) in vistos:
                continue
            pierde = _number(row.get("tu_once_pierde_sin_el")) or 0.0
            falta = _number(row.get("falta_xp_sustituto")) or 0.0
            if not row.get("en_xi") or pierde <= 0:
                continue
            vistos.add(str(row.get("player_id")))
            # Si te lo quitan se repone con lo mejor disponible: el hueco cuesta lo
            # que su xP supera al recambio. Sin otro de su línea, además, el once
            # queda sin esqueleto legal hasta reponerlo (``deja_sin_linea``).
            posicion = row.get("posicion")
            en_linea = sum(1 for p in players or [] if p.get("position") == posicion)
            sin_linea = en_linea - 1 < SLOTS_MINIMOS.get(str(posicion), 0)
            perdida = max(falta, pierde - fill) if sin_linea else falta
            sin = model.p(base_completo - perdida)
            anula = sin_linea
            blindaje.append(
                {
                    "player_id": row.get("player_id"),
                    "nombre": row.get("nombre"),
                    "posicion": row.get("posicion"),
                    "multiplo_clausula": row.get("multiplo_clausula"),
                    "clausula": row.get("clausula_actual"),
                    "rivales_que_pueden_pagar": row.get("rivales_que_pueden_pagar"),
                    "pierde_xp": round(perdida, 2),
                    "deja_sin_linea": anula,
                    "delta_p": round(sin - p_completo, 4),
                    "veredicto": row.get("veredicto_codigo"),
                }
            )
    blindaje.sort(key=lambda r: r["delta_p"])

    minima = plantilla_minima(players or [], compras_hoy, len(ventas_hoy))
    cutoff = ctx["cutoff_median"]
    return {
        "ok": True,
        "p_real": round(p_real, 4),
        "p_con_once_completo": round(p_completo, 4),
        "void": void,
        "jugadores": count,
        "base_xp": round(base_completo, 2),
        "corte_xp": round(cutoff, 2),
        "paso_1": paso_1,
        "acciones": acciones,
        "plan": plan_total,
        "ventas": ventas,
        "blindaje": blindaje,
        "plantilla_minima": minima,
        "postura": postura(base_completo, cutoff, float(ctx["calibration"]["sigma"])),
        "top_n": TOP_N,
        "nota": "Δ medidos contra el once completo; el plan ya cuenta el hueco de la 11.ª plaza.",
    }


def apply_overlay(
    document: dict[str, Any],
    rounds: dict[int, dict[str, int]] | None,
    players: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Estampa ``document["top4"]`` y aplica la regla de plantilla mínima.

    Con la plantilla por debajo del mínimo se vacían las compras para revender
    (``trading.operaciones`` y ``paron.especular``): hasta cumplirla solo se
    compra para jugar.
    """
    overlay = build_overlay(document, document.get("league_race"), rounds, players)
    document["top4"] = overlay
    if not overlay.get("ok") or overlay["plantilla_minima"]["cumple"]:
        return overlay
    bloqueadas = 0
    fichajes = document.get("plan_fichajes")
    trading = fichajes.get("trading") if isinstance(fichajes, dict) else None
    if isinstance(trading, dict) and trading.get("operaciones"):
        bloqueadas += len(trading["operaciones"])
        trading["operaciones"] = []
        trading["bloqueado_por_plantilla"] = True
    paron = document.get("paron") if isinstance(document.get("paron"), dict) else (fichajes or {}).get("paron")
    if isinstance(paron, dict) and paron.get("especular"):
        bloqueadas += len(paron["especular"])
        paron["especular"] = []
        paron["bloqueado_por_plantilla"] = True
    overlay["reventa_bloqueada"] = bloqueadas
    return overlay

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

from typing import Any

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
    for a in fichajes.get("acciones") or []:
        if not isinstance(a, dict):
            continue
        mejora = _number(a.get("mejora_neta"))
        if mejora is None:
            continue
        despues = model.p(base_completo + mejora)
        acciones.append(
            {
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
    acciones.sort(key=lambda r: -r["delta_p"])

    puntos_once = _number(fichajes.get("puntos_once"))
    compras_hoy = [a for a in fichajes.get("acciones") or [] if isinstance(a, dict) and a.get("tipo") in ("PUJA", "CLAUSULAZO")]
    ventas_hoy = [a for a in fichajes.get("acciones") or [] if isinstance(a, dict) and a.get("tipo") == "VENTA"]
    despues_jugadores = count + len(compras_hoy) - len(ventas_hoy)
    plan_total = None
    if puntos_once is not None:
        p_plan = model.p(puntos_once, void=despues_jugadores < MIN_PLAYERS)
        plan_total = {
            "puntos_once": round(puntos_once, 2),
            "jugadores_despues": despues_jugadores,
            "p_antes": round(p_real, 4),
            "p_despues": round(p_plan, 4),
            "delta_p": round(p_plan - p_real, 4),
        }

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

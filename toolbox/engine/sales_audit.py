"""Auditor de ventas: cada oferta o venta posible de mi plantilla, con veredicto.

Cruza la oferta, el precio proyectado, el rol en el once y el plan de fichajes.
No toca la red ni envía nada: devuelve filas listas para pintar.
"""

from __future__ import annotations

from typing import Any

from toolbox.engine.lineup_math import solve_best_xi

LALIGA = "LaLiga"

EXCELENTE_PCT = 2.5
BAJA_PCT = -1.0
ESPERAR_SPREAD_PCT = -1.2
SUBE_FUERTE_PCT = 5.0
CAE_PCT = -3.0
SOBREPRECIO_RIVAL_PCT = 12.0
XP_REFUERZO_RIVAL = 3.5
PIERDE_INTOCABLE = 1.8
SOBREVALORADO = 1.35
MIN_DIAS_ESPERA = 2.0

TITULOS = {
    "ACEPTAR_YA": "ACEPTA YA",
    "RECHAZAR_ESPERAR": "RECHAZA Y ESPERA",
    "RECHAZAR_RIVAL": "NO VENDER A RIVAL",
    "PONER_ESCAPARATE": "PON EN VENTA",
    "MANTENER_INTOCABLE": "NO VENDER",
}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _eur_txt(value: float) -> str:
    return f"{value / 1_000_000:.1f}".replace(".", ",") + "M"


def _pct_txt(value: float) -> str:
    texto = f"{abs(value):.1f}".replace(".", ",")
    return f"{'+' if value >= 0 else '-'}{texto}%"


def _pts_txt(value: float) -> str:
    return f"{abs(value):.1f}".replace(".", ",")


def calidad_oferta(spread_pct: float | None) -> str | None:
    if spread_pct is None:
        return None
    if spread_pct >= EXCELENTE_PCT:
        return "Excelente"
    if spread_pct >= BAJA_PCT:
        return "Justa"
    return "Baja"


def _mejor_oferta(ofertas: list[dict[str, Any]]) -> dict[str, Any] | None:
    """La de más importe; a igualdad manda LaLiga. Una oferta sin importe solo vale si no hay otra."""
    if not ofertas:
        return None
    con_importe = [oferta for oferta in ofertas if _num(oferta.get("importe")) is not None]
    if not con_importe:
        return ofertas[0]
    return max(
        con_importe,
        key=lambda oferta: (float(oferta["importe"]), 1 if oferta.get("comprador") == LALIGA else 0),
    )


def _relevo(jugadores: list[dict[str, Any]], player_id: str) -> tuple[float, dict[str, Any] | None]:
    """Puntos que pierde el mejor once sin él y quién entra por él."""
    elegibles = [row for row in jugadores if row.get("elegible") is True and row.get("position")]
    actual = solve_best_xi(elegibles)
    if not actual["ok"] or player_id not in actual["player_ids"]:
        return 0.0, None
    sin_el = solve_best_xi([row for row in elegibles if row["player_id"] != player_id])
    if not sin_el["ok"]:
        return round(float(actual["puntos"]), 2), None
    perdida = round(max(0.0, float(actual["puntos"]) - float(sin_el["puntos"])), 2)
    entran = [pid for pid in sin_el["player_ids"] if pid not in actual["player_ids"]]
    relevo = None
    if entran:
        fila = next((row for row in elegibles if row["player_id"] == entran[0]), None)
        if fila is not None:
            relevo = {
                "player_id": fila["player_id"],
                "nombre": fila.get("nombre"),
                "jornada": _num(fila.get("jornada")),
            }
    return perdida, relevo


def _clasificar(
    *,
    oferta: dict[str, Any] | None,
    spread: float | None,
    calidad: str | None,
    es_laliga: bool,
    rival_suficiente: bool,
    pct: float | None,
    dias: float | None,
    perdida: float,
    manda_vender: bool,
    escaparate_plan: bool,
    sobrevalorado: bool,
    obligada: bool,
    en_mercado: bool,
    importe: float | None,
    proyectado_jueves: float | None,
) -> tuple[str, str] | None:
    """Devuelve (código, razón corta) o None si el jugador no merece fila."""
    puede_esperar = dias is not None and dias >= MIN_DIAS_ESPERA
    if oferta is None:
        if manda_vender or escaparate_plan or sobrevalorado or obligada:
            return "PONER_ESCAPARATE", "sobrevalorado" if sobrevalorado and not (manda_vender or escaparate_plan) else "plan"
        if en_mercado and perdida >= PIERDE_INTOCABLE:
            return "MANTENER_INTOCABLE", "sin_relevo"
        return None
    if not es_laliga and not rival_suficiente:
        return "RECHAZAR_RIVAL", "sin_sobreprecio"
    if obligada:
        return "ACEPTAR_YA", "obligada"
    if perdida >= PIERDE_INTOCABLE:
        return "MANTENER_INTOCABLE", "sin_relevo"
    if pct is not None and pct < CAE_PCT:
        return "ACEPTAR_YA", "cae"
    vendible = manda_vender or escaparate_plan or en_mercado
    if es_laliga and vendible and puede_esperar:
        if spread is not None and spread < ESPERAR_SPREAD_PCT:
            return "RECHAZAR_ESPERAR", "oferta_baja"
        if pct is not None and pct > SUBE_FUERTE_PCT:
            return "RECHAZAR_ESPERAR", "sube"
    if es_laliga and manda_vender and calidad in {"Excelente", "Justa"}:
        return "ACEPTAR_YA", "plan"
    if not es_laliga and rival_suficiente:
        return "ACEPTAR_YA", "sobreprecio_rival"
    if (
        puede_esperar
        and importe is not None
        and proyectado_jueves is not None
        and importe < proyectado_jueves
    ):
        return "RECHAZAR_ESPERAR", "bajo_jueves"
    if importe is None:
        return ("ACEPTAR_YA", "sin_cifra") if manda_vender else ("RECHAZAR_ESPERAR", "sin_cifra")
    if calidad in {"Excelente", "Justa"}:
        return "ACEPTAR_YA", "oferta_buena"
    if manda_vender and not puede_esperar:
        return "ACEPTAR_YA", "sin_tiempo"
    if puede_esperar:
        return "RECHAZAR_ESPERAR", "oferta_baja"
    return "MANTENER_INTOCABLE", "oferta_baja_sin_tiempo"


def _motivo(
    codigo: str,
    razon: str,
    *,
    nombre: str,
    comprador: str | None,
    importe: float | None,
    spread: float | None,
    valor: float,
    justo: float | None,
    pct: float | None,
    perdida: float,
    relevo: dict[str, Any] | None,
    obligada_por: str | None,
    xp: float | None,
    alerta_rival: bool,
    jueves_pct: float | None,
) -> str:
    quien = comprador or LALIGA
    oferta_txt = ""
    if importe is not None:
        oferta_txt = f"{quien} te ofrece {_eur_txt(importe)}"
        if spread is not None:
            oferta_txt += f" ({_pct_txt(spread)} sobre su valor)"
        oferta_txt += ". "
    entra = f" entrando {relevo['nombre']}" if relevo and relevo.get("nombre") else ""
    if perdida < 0.05:
        impacto = "tu once no se resiente"
    else:
        impacto = f"tu once pierde -{_pts_txt(perdida)} pts{entra}"
    if razon == "sin_cifra":
        if codigo == "ACEPTAR_YA":
            return (
                f"LaLiga tiene una oferta por {nombre} pero no se ha leído el importe. El Plan lo manda vender: "
                f"acéptala si no baja de {_eur_txt(valor)}; {impacto}."
            )
        return f"LaLiga tiene una oferta por {nombre} sin importe visible y no hay que vender hoy. Espera a ver la cifra."
    if codigo == "ACEPTAR_YA":
        if razon == "sin_tiempo":
            return f"{oferta_txt}Es una oferta baja, pero el Plan necesita vender y ya no queda margen: {impacto}."
        if razon == "obligada":
            return f"{oferta_txt}Hay que vender hoy: {obligada_por}. Con la venta {impacto}."
        if razon == "cae":
            return f"{oferta_txt}Conviene aceptar hoy: baja un {_pct_txt(pct or 0.0)} esta semana y {impacto}."
        if razon == "sobreprecio_rival":
            return f"{oferta_txt}Es un sobreprecio que merece la pena: aceptar hoy y {impacto}."
        cola = f"el Plan lo manda vender, liberas caja y {impacto}." if razon == "plan" else f"es una oferta sólida y {impacto}."
        subida = ""
        if pct is not None and pct < 0:
            subida = f"baja un {_pct_txt(pct)} esta semana, "
        return f"{oferta_txt}Conviene aceptar hoy: {subida}{cola}"
    if codigo == "RECHAZAR_ESPERAR":
        if importe is not None and spread is not None and spread < ESPERAR_SPREAD_PCT:
            base = f"{quien} te da {_eur_txt(importe)} ({_pct_txt(spread)} por debajo de sus {_eur_txt(valor)})"
            if pct is not None and pct > 0:
                base += f" y encima sube {_pct_txt(pct)} a 7d"
            return f"{base}. No malvendas hoy: espera oferta al alza el jueves."
        if pct is not None and pct > SUBE_FUERTE_PCT:
            extra = f" (≈{_pct_txt(jueves_pct)} hasta el jueves)" if jueves_pct is not None else ""
            return f"{oferta_txt}Sube {_pct_txt(pct)} a 7d{extra}. No hay urgencia: espera una oferta mejor el jueves."
        return f"{oferta_txt}Hoy no compensa: el precio apunta al alza hasta el jueves y no necesitas la caja hoy."
    if codigo == "RECHAZAR_RIVAL":
        refuerzo = f" Rinde {_pts_txt(xp or 0.0)} xP y le sumaría puntos a un rival." if alerta_rival else ""
        return (
            f"{oferta_txt}Un rival tiene que pagar al menos un {_pct_txt(SOBREPRECIO_RIVAL_PCT)} sobre su valor "
            f"y no llega.{refuerzo} Véndelo siempre a LaLiga."
        )
    if codigo == "PONER_ESCAPARATE":
        if razon == "sobrevalorado" and justo:
            motivo = f"Está sobrevalorado: vale {_eur_txt(valor)} y su valor justo es {_eur_txt(justo)}."
        else:
            motivo = f"El Plan recomienda vender a {nombre} esta semana."
        return f"Hoy no tiene oferta. {motivo} Ponlo en el mercado hoy para tener oferta de LaLiga mañana."
    if razon == "oferta_baja_sin_tiempo":
        return f"{oferta_txt}Es una oferta baja y ya no hay margen para esperar. No necesitas vender: rechaza y quédatelo."
    return (
        f"{oferta_txt}Sin {nombre} tu once pierde -{_pts_txt(perdida)} pts y nadie de la plantilla "
        "lo sustituye en el once. Rechaza la oferta y quédatelo."
    )


def evaluar_ventas_y_ofertas(
    jugadores: list[dict[str, Any]],
    *,
    plan: dict[str, Any] | None,
    saldo: int | None,
    dias_al_cierre: float | None,
) -> dict[str, Any]:
    """Una ``auditoria_venta`` por jugador susceptible de venta, más el resumen.

    Cada jugador trae ``player_id``, ``nombre``, ``position``, ``valor``,
    ``valor_justo``, ``jornada`` (xP), ``pct`` (previsión a 7 días en %),
    ``elegible``, ``en_mercado`` y ``ofertas`` (lista de ``comprador``/``importe``).
    """
    acciones = plan.get("acciones") if isinstance(plan, dict) and isinstance(plan.get("acciones"), list) else []
    vende_hoy = {
        accion.get("player_id")
        for accion in acciones
        if isinstance(accion, dict) and accion.get("tipo") in {"VENDE", "VENDER HOY"} and accion.get("momento") != "condicional"
    }
    escaparate = {
        accion.get("player_id")
        for accion in acciones
        if isinstance(accion, dict) and accion.get("tipo") == "ESCAPARATE"
    }
    must_buy = sum(
        int(accion.get("euros") or 0)
        for accion in acciones
        if isinstance(accion, dict) and accion.get("impulso") == "MUST-BUY" and accion.get("momento") == "hoy"
    )
    negativo = saldo is not None and saldo < 0
    falta_caja = must_buy > 0 and (saldo is None or saldo < must_buy)
    dias_jueves = max(0.0, dias_al_cierre - 1.0) if dias_al_cierre is not None else None

    filas: list[dict[str, Any]] = []
    for jugador in jugadores:
        player_id = jugador.get("player_id")
        valor = _num(jugador.get("valor"))
        if not isinstance(player_id, str) or valor is None or valor <= 0:
            continue
        justo = _num(jugador.get("valor_justo"))
        pct = _num(jugador.get("pct"))
        xp = _num(jugador.get("jornada"))
        mejor = _mejor_oferta(
            [oferta for oferta in jugador.get("ofertas") or [] if isinstance(oferta, dict)]
        )
        importe = _num(mejor.get("importe")) if mejor else None
        comprador = (mejor.get("comprador") or LALIGA) if mejor else None
        es_laliga = comprador == LALIGA
        spread = (importe - valor) / valor * 100.0 if importe is not None else None
        calidad = calidad_oferta(spread)

        calculada, relevo = _relevo(jugadores, player_id)
        publicada = _num(jugador.get("tu_once_pierde_sin_el"))
        perdida = publicada if publicada is not None else calculada
        manda_vender = player_id in vende_hoy
        financia = manda_vender and falta_caja
        obligada = manda_vender and (negativo or falta_caja)
        obligada_por = (
            "tu caja está en negativo y la jornada puntúa cero"
            if negativo
            else "financia un must-buy que hay que pujar hoy"
        )
        base_rival = min(valor, justo) if justo else valor
        rival_suficiente = importe is not None and importe >= base_rival * (1 + SOBREPRECIO_RIVAL_PCT / 100.0)
        alerta = (
            mejor is not None
            and not es_laliga
            and xp is not None
            and xp >= XP_REFUERZO_RIVAL
            and not rival_suficiente
        )
        jueves_pct = pct / 7.0 * dias_jueves if pct is not None and dias_jueves is not None else None
        jueves_eur = valor * jueves_pct / 100.0 if jueves_pct is not None else None
        proyectado = valor + jueves_eur if jueves_eur is not None else None
        sobrevalorado = justo is not None and justo > 0 and valor > justo * SOBREVALORADO

        veredicto = _clasificar(
            oferta=mejor,
            spread=spread,
            calidad=calidad,
            es_laliga=es_laliga,
            rival_suficiente=rival_suficiente,
            pct=pct,
            dias=dias_al_cierre,
            perdida=perdida,
            manda_vender=manda_vender,
            escaparate_plan=player_id in escaparate,
            sobrevalorado=sobrevalorado,
            obligada=obligada,
            en_mercado=jugador.get("en_mercado") is True,
            importe=importe,
            proyectado_jueves=proyectado,
        )
        if veredicto is None:
            continue
        codigo, razon = veredicto
        nombre = str(jugador.get("nombre") or player_id)
        motivo = _motivo(
            codigo,
            razon,
            nombre=nombre,
            comprador=comprador,
            importe=importe,
            spread=spread,
            valor=valor,
            justo=justo,
            pct=pct,
            perdida=perdida,
            relevo=relevo,
            obligada_por=obligada_por,
            xp=xp,
            alerta_rival=alerta,
            jueves_pct=jueves_pct,
        )
        if codigo == "MANTENER_INTOCABLE":
            grupo = 2
        elif mejor is not None:
            grupo = 0
        else:
            grupo = 1
        filas.append(
            {
                "player_id": player_id,
                "nombre": nombre,
                "posicion": jugador.get("position"),
                "valor_mercado": int(valor),
                "valor_justo": int(justo) if justo else None,
                "xp_jornada": round(xp, 2) if xp is not None else None,
                "prevision_7d_pct": round(pct, 2) if pct is not None else None,
                "tu_once_pierde_sin_el": perdida,
                "relevo_banquillo": relevo,
                "financia_must_buy_hoy": financia,
                "plan_vende_hoy": manda_vender,
                "en_mercado": jugador.get("en_mercado") is True,
                "dias_al_cierre": dias_al_cierre,
                "oferta_activa": {
                    "comprador": comprador,
                    "importe_oferta": int(importe) if importe is not None else None,
                    "spread_pct": round(spread, 2) if spread is not None else None,
                    "calidad_oferta": calidad,
                },
                "ganancia_esperar_jueves": {
                    "pct": round(jueves_pct, 2) if jueves_pct is not None else None,
                    "eur": int(round(jueves_eur)) if jueves_eur is not None else None,
                    "valor_proyectado_jueves": int(round(proyectado)) if proyectado is not None else None,
                },
                "alerta_refuerzo_rival": bool(alerta),
                "veredicto_codigo": codigo,
                "veredicto_titulo": TITULOS[codigo],
                "motivo_detallado": motivo,
                "prioridad": grupo,
            }
        )

    filas.sort(
        key=lambda fila: (
            fila["prioridad"],
            -(fila["oferta_activa"]["importe_oferta"] or 0),
            fila["nombre"],
        )
    )
    con_oferta = [fila for fila in filas if fila["oferta_activa"]["comprador"] is not None]
    importes = [fila["oferta_activa"]["importe_oferta"] for fila in con_oferta if fila["oferta_activa"]["importe_oferta"]]
    laliga = [
        fila["oferta_activa"]["spread_pct"]
        for fila in con_oferta
        if fila["oferta_activa"]["comprador"] == LALIGA and fila["oferta_activa"]["spread_pct"] is not None
    ]
    resumen = {
        "ofertas_activas": len(con_oferta),
        "total_ofertas_eur": int(sum(importes)),
        "spread_medio_laliga_pct": round(sum(laliga) / len(laliga), 2) if laliga else None,
        "ventas_recomendadas_hoy": sum(1 for fila in filas if fila["veredicto_codigo"] == "ACEPTAR_YA"),
        "jugadores": len(filas),
    }
    return {"resumen": resumen, "filas": filas}

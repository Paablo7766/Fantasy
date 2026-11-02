"""Comparador real de liga: jugador que sale contra jugador que entra.

El coste no es el valor de mercado genérico. La venta usa la oferta de LaLiga
de hoy si existe, y la compra usa la puja smart, la cláusula del rival o el
mínimo entre el precio de su anuncio y esa cláusula.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from toolbox.analyzer import own_squad
from toolbox.engine.auction_intel import calcular_pujas, prevision_a_puntos
from toolbox.engine.clause_advisor import _cuando, _estado_lock
from toolbox.engine.market_predictor import proyectar_7d, ratio_mercado_liga, valor_justo_jugador
from toolbox.engine.strategy_layer import (
    _TITULAR_RATIO,
    _cash_map,
    _collect,
    _en_forma,
    _int,
    _nombre,
    _num,
    _ofertas_propias,
    _pid,
    _prob,
    _rivals,
)

# Una cláusula a partir de 2× el valor ya está inflada: 60 M€ por un jugador
# de 25 M€ no se paga con una mejora modesta de puntos.
_MULTIPLO_INFLADO = 2.0
_XP_QUE_JUSTIFICA_CLAUSULA = 1.5
_XP_OBLIGATORIO = 1.5
_XP_CLARO = 0.7
_XP_CAMBIO = 1.2
_XP_AJUSTADO = 0.3
_NETO_HOLGADO = 8_000_000
_EURO_POR_PUNTO_CARO = 15_000_000
_EURO_POR_PUNTO_MUY_CARO = 20_000_000

# El xP de la jornada ya trae el próximo rival. El resto de la ventana se
# reescala respecto a esa dificultad para no contar el partido dos veces.
_FACTOR_DIFICULTAD = {
    "muy_facil": 1.12,
    "muyfacil": 1.12,
    "very_easy": 1.12,
    "facil": 1.06,
    "easy": 1.06,
    "medio": 1.0,
    "media": 1.0,
    "normal": 1.0,
    "average": 1.0,
    "dificil": 0.92,
    "hard": 0.92,
    "muy_dificil": 0.84,
    "muydificil": 0.84,
    "very_hard": 0.84,
}


def _m(value: float) -> str:
    return f"{abs(value) / 1_000_000:.1f}".replace(".", ",") + "M"


def _clave(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return (
        value.strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace(" ", "_")
        .replace("-", "_")
    )


def _es_laliga(value: Any) -> bool:
    return _clave(value) in {"laliga", "la_liga", "liga", "mercado", "sistema"}


def _redondear(value: float | None, digitos: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digitos)


def _euros(value: float | None) -> int | None:
    if value is None or not math.isfinite(value):
        return None
    return int(round(value))


def _factor(dificultad: Any) -> float:
    return _FACTOR_DIFICULTAD.get(_clave(dificultad), 1.0)


def _calendario(jugador: dict[str, Any]) -> list[Any]:
    for key in ("calendario", "own_calendar", "af_calendar"):
        raw = jugador.get(key)
        if isinstance(raw, list) and raw:
            return raw[:4]
    return []


def _xp_j1(jugador: dict[str, Any]) -> float | None:
    for key in ("xp_j1", "jornada", "jornada_ev", "own_expected_points", "expected_points"):
        number = _num(jugador.get(key))
        if number is not None:
            return number
    return None


def xp_4_jornadas(jugador: dict[str, Any]) -> float | None:
    """Puntos esperados por jornada en las próximas 4, ponderados por rival.

    El partido inmediato conserva ``xp_j1``. Cada uno de los tres siguientes
    se escala por su dificultad respecto a la del primero.
    """
    base = _xp_j1(jugador)
    if base is None:
        return None
    fechas = _calendario(jugador)
    if len(fechas) < 2:
        return base
    factores: list[float] = []
    for fecha in fechas:
        if isinstance(fecha, dict):
            factores.append(_factor(fecha.get("difficulty") or fecha.get("dificultad")))
        else:
            factores.append(_factor(fecha))
    while len(factores) < 4:
        factores.append(factores[-1])
    origen = factores[0] or 1.0
    ajustados = [base * (factor / origen) for factor in factores[:4]]
    return sum(ajustados) / len(ajustados)


def _titularidad(jugador: dict[str, Any]) -> float | None:
    for key in ("prob_titular", "p_titular"):
        number = _prob(jugador.get(key))
        if number is not None:
            return number
    return None


def _techo(jugador: dict[str, Any]) -> float | None:
    for key in ("techo", "ceiling_points", "own_ceiling_points", "af_ceiling_points"):
        number = _num(jugador.get(key))
        if number is not None:
            return number
    return None


def _valor(jugador: dict[str, Any]) -> int | None:
    for key in ("valor", "market_value", "fantasy_price"):
        number = _int(jugador.get(key))
        if number is not None and number > 0:
            return number
    return None


def _clausula(jugador: dict[str, Any]) -> int | None:
    for key in ("clausula", "buyout_clause", "buyout_clause_eur", "clause"):
        number = _int(jugador.get(key))
        if number is not None and number > 0:
            return number
    return None


def _estado_clausula(jugador: dict[str, Any], ahora: datetime) -> tuple[bool | None, str | None]:
    marca = jugador.get("clausula_abierta")
    abre = jugador.get("clausulaAbre") or jugador.get("clausula_abre")
    abre_txt = abre.strip() if isinstance(abre, str) and abre.strip() else None
    if marca is True:
        return True, abre_txt
    if marca is False:
        return False, abre_txt
    lock = jugador.get("clause_lock") or jugador.get("bloqueo")
    bloqueada, momento = _estado_lock(lock, ahora)
    if bloqueada is None:
        return None, abre_txt
    cuando = _cuando(momento, ahora) if momento is not None else abre_txt
    return (not bloqueada), cuando


def _oferta_laliga(jugador: dict[str, Any]) -> int | None:
    for key in ("oferta_laliga", "offer_eur", "oferta_sistema", "system_offer"):
        number = _int(jugador.get(key))
        if number is not None and number > 0:
            return number
    for oferta in jugador.get("ofertas_directas") or []:
        if not isinstance(oferta, dict):
            continue
        if _es_laliga(oferta.get("comprador")):
            number = _int(oferta.get("importe"))
            if number is not None and number > 0:
                return number
    return None


def _en_plantilla(jugador: dict[str, Any]) -> bool:
    if jugador.get("is_self") is True or jugador.get("en_plantilla") is True:
        return True
    return False


def ingreso_venta(jugador: dict[str, Any]) -> dict[str, Any]:
    """Lo que entra en caja si sale A. La oferta de hoy manda sobre el valor."""
    valor = _valor(jugador)
    oferta = _oferta_laliga(jugador)
    activa = _en_plantilla(jugador) and (
        oferta is not None or jugador.get("tiene_oferta_laliga") is True
    )
    if activa and oferta is not None:
        return {
            "importe": oferta,
            "fuente": "oferta_laliga",
            "esperar_24h": False,
            "valor_mercado": valor,
        }
    return {
        "importe": valor,
        "fuente": "valor_mercado",
        "esperar_24h": True,
        "valor_mercado": valor,
    }


def _nombre_rival(jugador: dict[str, Any]) -> str | None:
    if jugador.get("is_self") is True and not jugador.get("propietario"):
        return None
    for key in ("propietario", "fantasy_team_name", "manager", "vendedor"):
        value = jugador.get(key)
        if isinstance(value, str) and value.strip() and not _es_laliga(value):
            return value.strip()
    return None


def _canal(jugador: dict[str, Any]) -> str:
    """``laliga``, ``venta_rival``, ``clausula`` o ``desconocido``."""
    if jugador.get("is_self") is True and jugador.get("en_mercado") is not True and jugador.get("on_market") is not True:
        return "propio"
    offer = _clave(jugador.get("offer_source"))
    en_mercado = (
        jugador.get("en_mercado") is True
        or jugador.get("on_market") is True
        or offer in {"liga", "rival"}
    )
    vendedor = jugador.get("vendedor")
    seller_id = _pid(jugador.get("seller_team_id"))
    rival_en_anuncio = offer == "rival" or (isinstance(vendedor, str) and vendedor.strip() and not _es_laliga(vendedor))
    if seller_id and jugador.get("is_self") is not True:
        rival_en_anuncio = True
    if en_mercado and rival_en_anuncio and not _es_laliga(vendedor) and offer != "liga":
        return "venta_rival"
    if en_mercado and (_es_laliga(vendedor) or offer == "liga" or not rival_en_anuncio):
        return "laliga"
    if _nombre_rival(jugador) or _clausula(jugador):
        return "clausula" if jugador.get("is_self") is not True else "propio"
    return "laliga" if en_mercado else "desconocido"


def coste_adquisicion(jugador: dict[str, Any], ahora: datetime) -> dict[str, Any]:
    """Lo que se paga por B dentro de esta liga, nunca el valor genérico de un rival."""
    canal = _canal(jugador)
    valor = _valor(jugador)
    clausula = _clausula(jugador)
    abierta, abre = _estado_clausula(jugador, ahora)
    rival = _nombre_rival(jugador)
    puja_smart = _int(jugador.get("puja_smart"))
    puja_recomendada = _int(jugador.get("puja_recomendada"))
    puja_maxima = _int(jugador.get("puja_maxima"))
    smart = puja_smart if puja_smart is not None and puja_smart > 0 else puja_recomendada
    base = {
        "canal": canal,
        "valor_mercado": valor,
        "clausula": clausula,
        "clausula_abierta": abierta,
        "clausula_abre": abre,
        "rival": rival,
        "puja_smart": smart,
        "puja_maxima": puja_maxima if puja_maxima is not None and puja_maxima > 0 else None,
        "precio_venta_rival": _int(jugador.get("precio_venta_rival") or jugador.get("sale_price")),
    }
    if canal == "laliga":
        base.update(
            {
                "importe": smart,
                "fuente": "puja_smart",
                "etiqueta": None if smart is None else f"Puja Smart: {_m(smart)}",
            }
        )
        return base
    if canal == "venta_rival":
        precio = base["precio_venta_rival"]
        if precio is not None and precio > 0 and clausula is not None:
            importe = min(precio, clausula)
            fuente = "clausula" if clausula <= precio else "venta_rival"
        elif precio is not None and precio > 0:
            importe = precio
            fuente = "venta_rival"
        else:
            importe = clausula
            fuente = "clausula"
        nombre = rival or "el rival"
        if fuente == "clausula" and importe is not None:
            etiqueta = f"Cláusula de {nombre}: {_m(importe)}"
        elif importe is not None:
            etiqueta = f"Venta de {nombre}: {_m(importe)}"
        else:
            etiqueta = None
        base.update({"importe": importe, "fuente": fuente, "etiqueta": etiqueta})
        return base
    if canal == "clausula":
        nombre = rival or "el rival"
        base.update(
            {
                "importe": clausula,
                "fuente": "clausula",
                "etiqueta": None if clausula is None else f"Cláusula de {nombre}: {_m(clausula)}",
            }
        )
        return base
    base.update({"importe": None, "fuente": canal, "etiqueta": None})
    return base


def _subida_7d(valor: int | None, pct: float) -> int:
    if valor is None:
        return 0
    return int(round(valor * pct / 100.0))


def _veredicto(
    *,
    nombre_a: str,
    nombre_b: str,
    delta_xp_4j: float | None,
    delta_titularidad: float | None,
    coste_neto: int | None,
    coste_por_punto: float | None,
    multiplo: float | None,
    fuente: str,
    sin_precio: bool,
) -> tuple[str, str]:
    """Etiqueta y ganador (``A`` o ``B``)."""
    if sin_precio:
        return f"MEJOR QUEDARSE A {nombre_a}", "A"
    xp = delta_xp_4j if delta_xp_4j is not None else 0.0
    inflada = fuente == "clausula" and multiplo is not None and multiplo >= _MULTIPLO_INFLADO
    muy_cara = (
        fuente == "clausula"
        and multiplo is not None
        and multiplo >= 1.8
        and coste_por_punto is not None
        and coste_por_punto > _EURO_POR_PUNTO_MUY_CARO
        and xp < _XP_QUE_JUSTIFICA_CLAUSULA
    )
    if (inflada and xp < _XP_QUE_JUSTIFICA_CLAUSULA) or muy_cara:
        return "NO COMPENSA (CLÁUSULA INFLADA)", "A"

    titularidad_ok = delta_titularidad is None or delta_titularidad >= -0.05
    neto_ok = coste_neto is None or coste_neto <= _NETO_HOLGADO
    punto_ok = coste_por_punto is None or coste_por_punto <= _EURO_POR_PUNTO_CARO
    if xp >= _XP_CAMBIO and titularidad_ok and neto_ok and punto_ok:
        if xp >= _XP_OBLIGATORIO:
            return "CAMBIO OBLIGATORIO", "B"
        return f"CLARAMENTE {nombre_b}", "B"
    if xp >= _XP_CLARO and punto_ok and (delta_titularidad is None or delta_titularidad >= -0.2):
        return f"CLARAMENTE {nombre_b}", "B"
    if xp >= _XP_AJUSTADO and (coste_por_punto is None or coste_por_punto <= _EURO_POR_PUNTO_MUY_CARO):
        return f"AJUSTADA · POR POCO {nombre_b}", "B"
    return f"MEJOR QUEDARSE A {nombre_a}", "A"


def _pill(fuente: str, multiplo: float | None, coste_neto: int | None, inflada: bool) -> str | None:
    if inflada or (fuente == "clausula" and multiplo is not None and multiplo >= 1.8):
        return "CLÁUSULA CARA"
    if coste_neto is not None and coste_neto <= 0:
        return "RENTABLE EN 7D"
    return None


def comparar_fichas(
    actual: dict[str, Any],
    objetivo: dict[str, Any],
    *,
    saldo: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Enfrenta la ficha de A (sale) con la de B (entra)."""
    ahora = now or datetime.now(timezone.utc)
    if ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=timezone.utc)
    nombre_a = _nombre(actual)
    nombre_b = _nombre(objetivo)
    ingreso = ingreso_venta(actual)
    coste = coste_adquisicion(objetivo, ahora)
    venta = ingreso["importe"]
    compra = coste["importe"]
    delta_caja = None if venta is None or compra is None else int(compra - venta)
    saldo_final = None if saldo is None or delta_caja is None else int(saldo - delta_caja)

    xp_a = _xp_j1(actual)
    xp_b = _xp_j1(objetivo)
    xp4_a = xp_4_jornadas(actual)
    xp4_b = xp_4_jornadas(objetivo)
    tit_a = _titularidad(actual)
    tit_b = _titularidad(objetivo)
    techo_a = _techo(actual)
    techo_b = _techo(objetivo)
    delta_xp_j1 = None if xp_a is None or xp_b is None else xp_b - xp_a
    delta_xp_4j = None if xp4_a is None or xp4_b is None else xp4_b - xp4_a
    delta_titularidad = None if tit_a is None or tit_b is None else tit_b - tit_a
    delta_techo = None if techo_a is None or techo_b is None else techo_b - techo_a

    pct_a = prevision_a_puntos(actual.get("prevision_7d_pct") if actual.get("prevision_7d_pct") is not None else actual.get("pct"))
    pct_b = prevision_a_puntos(objetivo.get("prevision_7d_pct") if objetivo.get("prevision_7d_pct") is not None else objetivo.get("pct"))
    valor_a = _valor(actual)
    valor_b = _valor(objetivo)
    subida_a = _subida_7d(valor_a, pct_a)
    subida_b = _subida_7d(valor_b, pct_b)
    delta_subida = subida_b - subida_a
    coste_neto = None if delta_caja is None else int(delta_caja - delta_subida)
    coste_por_punto = None
    if delta_xp_4j is not None and delta_xp_4j > 0 and coste_neto is not None:
        coste_por_punto = 0.0 if coste_neto <= 0 else coste_neto / delta_xp_4j

    dias = None
    diaria_a = subida_a / 7.0
    diaria_b = subida_b / 7.0
    extra_diaria = diaria_b - diaria_a
    if delta_caja is not None and delta_caja > 0 and extra_diaria > 0:
        dias = delta_caja / extra_diaria

    multiplo = None
    if coste["fuente"] == "clausula" and coste["clausula"] and valor_b:
        multiplo = coste["clausula"] / valor_b
    etiqueta, ganador = _veredicto(
        nombre_a=nombre_a,
        nombre_b=nombre_b,
        delta_xp_4j=delta_xp_4j,
        delta_titularidad=delta_titularidad,
        coste_neto=coste_neto,
        coste_por_punto=coste_por_punto,
        multiplo=multiplo,
        fuente=coste["fuente"],
        sin_precio=compra is None,
    )
    inflada = etiqueta == "NO COMPENSA (CLÁUSULA INFLADA)"
    pill = _pill(coste["fuente"], multiplo, coste_neto, inflada)

    impacto = None
    if coste["fuente"] in {"clausula", "venta_rival"} and coste["rival"] and compra is not None:
        impacto = {
            "rival": coste["rival"],
            "posicion_liga": _int(objetivo.get("posicion_liga") if objetivo.get("posicion_liga") is not None else objetivo.get("rank")),
            "importe_eur": int(compra),
            "aviso": f"Cuidado: le inyectas +{_m(compra)} de caja a {coste['rival']}",
        }

    maxima = coste["puja_maxima"]
    saldo_maxima = None
    if maxima is not None and venta is not None and saldo is not None and coste["canal"] == "laliga":
        saldo_maxima = int(saldo - (maxima - venta))

    def precio(jugador: dict[str, Any]) -> dict[str, Any]:
        """Lo que cuesta cada lado en esta liga: puja, venta de rival o cláusula."""
        if jugador.get("is_self") is True or _canal(jugador) == "propio":
            venta_propia = ingreso_venta(jugador)
            return {"importe": venta_propia["importe"], "tipo": "propio", "etiqueta": "Tu jugador · venta"}
        datos = coste_adquisicion(jugador, ahora)
        tipo = {"puja_smart": "mercado", "venta_rival": "venta_rival", "clausula": "clausula"}.get(datos["fuente"], "desconocido")
        return {
            "importe": datos["importe"],
            "tipo": tipo,
            "etiqueta": datos["etiqueta"],
            "clausula_abierta": datos["clausula_abierta"] if tipo == "clausula" else None,
            "clausula_abre": datos["clausula_abre"] if tipo == "clausula" else None,
            "rival": datos["rival"],
        }

    def proximos(jugador: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for fecha in _calendario(jugador):
            if isinstance(fecha, dict) and fecha.get("opponent"):
                out.append(
                    {
                        "rival": fecha.get("opponent"),
                        "casa": fecha.get("is_home") if isinstance(fecha.get("is_home"), bool) else None,
                        "dificultad": fecha.get("difficulty") or fecha.get("dificultad"),
                    }
                )
        return out[:3]

    def ficha(jugador: dict[str, Any], xp: float | None, xp4: float | None, tit: float | None, techo: float | None, subida: int, pct: float) -> dict[str, Any]:
        media = _num(jugador.get("average_points") if jugador.get("average_points") is not None else jugador.get("media"))
        return {
            "club": jugador.get("club"),
            "media": _redondear(media),
            "precio": precio(jugador),
            "proximos": proximos(jugador),
            "player_id": _pid(jugador.get("player_id")),
            "nombre": _nombre(jugador),
            "posicion": jugador.get("position") or jugador.get("posicion"),
            "foto": jugador.get("image_url") or jugador.get("foto"),
            "xp_j1": _redondear(xp),
            "xp_4j": _redondear(xp4),
            "prob_titular": _redondear(tit, 3) if tit is not None else None,
            "techo": _redondear(techo),
            "valor": _valor(jugador),
            "prevision_7d_pct": round(pct, 2),
            "subida_7d_euros": subida,
        }

    nota = None
    if ingreso["esperar_24h"]:
        nota = "Hay que esperar 24 h a una oferta de LaLiga: hoy la venta se cuenta a valor de mercado."
    elif coste["clausula_abierta"] is False and coste["fuente"] == "clausula":
        cuando = coste["clausula_abre"] or "más adelante"
        nota = f"La cláusula sigue cerrada. Se abre {cuando}."

    return {
        "ok": True,
        "jugador_a": ficha(actual, xp_a, xp4_a, tit_a, techo_a, subida_a, pct_a),
        "jugador_b": ficha(objetivo, xp_b, xp4_b, tit_b, techo_b, subida_b, pct_b),
        "ingreso_venta_a": venta,
        "ingreso_fuente": ingreso["fuente"],
        "esperar_oferta_24h": ingreso["esperar_24h"] is True,
        "coste_adquisicion_b": compra,
        "coste_fuente": coste["fuente"],
        "coste_etiqueta": coste["etiqueta"],
        "puja_maxima": maxima if coste["canal"] == "laliga" else None,
        "saldo_escenario_maxima": saldo_maxima,
        "clausula": coste["clausula"],
        "clausula_abierta": coste["clausula_abierta"],
        "clausula_abre": coste["clausula_abre"],
        "delta_caja": delta_caja,
        "saldo_actual": saldo,
        "saldo_final_tras_cambio": saldo_final,
        "delta_xp_j1": _redondear(delta_xp_j1),
        "delta_xp_4j": _redondear(delta_xp_4j),
        "delta_titularidad": _redondear(delta_titularidad, 3),
        "delta_techo": _redondear(delta_techo),
        "delta_subida_7d_euros": delta_subida,
        "subida_7d_a": subida_a,
        "subida_7d_b": subida_b,
        "coste_neto_a_7_dias": coste_neto,
        "coste_por_punto_extra": _redondear(coste_por_punto, 0) if coste_por_punto is not None else None,
        "dias_amortizacion": _redondear(dias, 1),
        "impacto_rival": impacto,
        "veredicto_etiqueta": etiqueta,
        "ganador": ganador,
        "ganador_nombre": nombre_b if ganador == "B" else nombre_a,
        "pill": pill,
        "nota_ejecucion": nota,
        "multiplo_clausula": _redondear(multiplo, 2),
    }


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _ranks(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        team_id = _pid(squad.get("team_id"))
        if not team_id:
            continue
        found[team_id] = {
            "rank": _int(squad.get("rank")),
            "manager": squad.get("manager_name") if isinstance(squad.get("manager_name"), str) else None,
            "fantasy_team_name": squad.get("fantasy_team_name") if isinstance(squad.get("fantasy_team_name"), str) else None,
        }
    return found


def _crudo(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Junta calendario y foto sin pisar un dato ya encontrado."""
    index: dict[str, dict[str, Any]] = {}

    def take(player: dict[str, Any]) -> None:
        player_id = _pid(player.get("player_id"))
        if player_id is None:
            return
        bucket = index.setdefault(player_id, {})
        for key, value in player.items():
            if value is None or key in bucket:
                continue
            bucket[key] = value

    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    for player in trends.get("players") or []:
        if isinstance(player, dict):
            take(player)
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        for player in squad.get("players") or []:
            if isinstance(player, dict):
                take(player)
    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    for listing in market.get("listings") or []:
        if isinstance(listing, dict):
            take(listing)
    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else {}
    for key in ("xi", "benched", "excluded"):
        for player in optimize.get(key) or []:
            if isinstance(player, dict):
                take(player)
    return index


def _ficha_tablero(
    record: dict[str, Any],
    raw: dict[str, Any],
    *,
    previsto: dict[str, Any],
    puja: dict[str, Any],
    ranks: dict[str, dict[str, Any]],
    own_id: str | None,
    nombres: dict[str, str],
) -> dict[str, Any]:
    team_id = _pid(record.get("team_id"))
    seller = _pid(record.get("seller_team_id"))
    meta = ranks.get(team_id or "", {})
    meta_seller = ranks.get(seller or "", {})
    is_self = record.get("is_self") is True
    on_market = record.get("on_market") is True
    rival_id = seller if on_market and seller and seller != own_id else None
    if rival_id is None and not is_self:
        rival_id = team_id
    rival_meta = ranks.get(rival_id or "", {})
    rival_nombre = rival_meta.get("fantasy_team_name") or rival_meta.get("manager") or record.get("manager")
    ficha = dict(record)
    for key, value in raw.items():
        actual = ficha.get(key)
        if key not in ficha or actual is None or actual == "" or actual == []:
            ficha[key] = value
    ficha["nombre"] = record.get("nombre") or _nombre(raw)
    ficha["is_self"] = is_self
    ficha["en_mercado"] = on_market
    ficha["image_url"] = raw.get("image_url") or record.get("image_url")
    pct = previsto.get("pct")
    if pct is not None:
        ficha["prevision_7d_pct"] = pct
    ficha["puja_smart"] = puja.get("puja_smart")
    ficha["puja_recomendada"] = puja.get("puja_recomendada")
    ficha["puja_maxima"] = puja.get("puja_maxima")
    if record.get("clause"):
        ficha["clausula"] = record.get("clause")
    ofertas = _ofertas_propias(record, own_id, nombres)
    if ofertas:
        ficha["ofertas_directas"] = ofertas
    if on_market and rival_id:
        ficha["vendedor"] = rival_nombre or "Rival"
        ficha["propietario"] = rival_nombre
        ficha["offer_source"] = "rival"
        ficha["rank"] = meta_seller.get("rank") if meta_seller else meta.get("rank")
    elif on_market:
        ficha["vendedor"] = "LaLiga"
        ficha["offer_source"] = "liga"
        ficha["propietario"] = None
    elif not is_self and rival_nombre:
        ficha["propietario"] = rival_nombre
        ficha["rank"] = meta.get("rank")
    ficha["posicion_liga"] = ficha.get("rank")
    return ficha


def comparar_jugadores_liga(
    jugador_actual_id: str,
    jugador_objetivo_id: str,
    board: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resuelve los dos ids en la foto de la liga y devuelve la comparativa."""
    actual_id = _pid(jugador_actual_id)
    objetivo_id = _pid(jugador_objetivo_id)
    if actual_id is None or objetivo_id is None:
        return _error("bad_request", "Faltan los dos jugadores del cara a cara.")
    if actual_id == objetivo_id:
        return _error("same_player", "Elige otro jugador de tu plantilla para enfrentarlos.")
    if not isinstance(board, dict):
        return _error("no_board", "No hay foto de la liga para comparar.")

    ahora = now or datetime.now(timezone.utc)
    if ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=timezone.utc)
    records = _collect(board, ahora)
    if actual_id not in records or objetivo_id not in records:
        return _error("not_found", "Uno de los dos jugadores no está en la foto de la liga.")

    titulares = [
        (float(row["valor"]), float(row["jornada"]))
        for row in records.values()
        if isinstance(row.get("valor"), int)
        and row["valor"] > 0
        and isinstance(row.get("jornada"), (int, float))
        and not isinstance(row.get("jornada"), bool)
        and float(row["jornada"]) > 0
        and isinstance(row.get("p_titular"), (int, float))
        and not isinstance(row.get("p_titular"), bool)
        and float(row["p_titular"]) >= _TITULAR_RATIO
    ]
    ratio = float(ratio_mercado_liga(titulares)["ratio_mercado"])
    previsiones: dict[str, dict[str, Any]] = {}
    for player_id in (actual_id, objetivo_id):
        row = records[player_id]
        valor = row.get("valor")
        jornada = row.get("jornada")
        if not isinstance(valor, int) or valor <= 0:
            continue
        if not isinstance(jornada, (int, float)) or isinstance(jornada, bool):
            continue
        try:
            previsiones[player_id] = proyectar_7d(
                valor,
                float(row.get("delta_hoy") or 0.0),
                float(row.get("delta_ayer") or 0.0),
                float(jornada),
                ratio,
                en_forma=_en_forma(row),
            )
        except (TypeError, ValueError):
            continue

    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    propio = own_squad(squads)
    own_id = _pid(propio.get("team_id")) if isinstance(propio, dict) else None
    cajas = _cash_map(board)
    saldo = None
    if own_id and own_id in cajas:
        saldo = cajas[own_id]
    elif isinstance(propio, dict) and isinstance(propio.get("cash"), int) and not isinstance(propio.get("cash"), bool):
        saldo = propio["cash"]
    rivales = _rivals(records, cajas)
    ranks = _ranks(board)
    nombres = {
        team_id: (meta.get("manager") or meta.get("fantasy_team_name") or team_id)
        for team_id, meta in ranks.items()
        if team_id != own_id
    }
    crudo = _crudo(board)
    fichas: dict[str, dict[str, Any]] = {}
    for player_id in (actual_id, objetivo_id):
        row = records[player_id]
        previsto = previsiones.get(player_id) if isinstance(previsiones.get(player_id), dict) else {}
        justo = previsto.get("valor_justo") if isinstance(previsto, dict) else None
        if not isinstance(justo, int):
            jornada = row.get("jornada")
            justo = valor_justo_jugador(float(jornada), ratio) if isinstance(jornada, (int, float)) and not isinstance(jornada, bool) else 0
        valor = row.get("valor") if isinstance(row.get("valor"), int) else 0
        puja = calcular_pujas(
            valor,
            float(row.get("delta_hoy") or 0.0),
            int(justo or 0),
            tu_saldo=saldo,
            rivales=rivales,
            posicion=row.get("position") if isinstance(row.get("position"), str) else None,
            prevision_7d_pct=previsto.get("pct") if isinstance(previsto, dict) else None,
            dificultad=row.get("dificultad") if isinstance(row.get("dificultad"), str) else None,
        )
        fichas[player_id] = _ficha_tablero(
            row,
            crudo.get(player_id) or {},
            previsto=previsto if isinstance(previsto, dict) else {},
            puja=puja,
            ranks=ranks,
            own_id=own_id,
            nombres=nombres,
        )
    return comparar_fichas(fichas[actual_id], fichas[objetivo_id], saldo=saldo, now=ahora)

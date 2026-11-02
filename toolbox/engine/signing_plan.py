"""Plan de fichajes: once de más puntos, sin vaciar la caja a ciegas.

El solver junta ventas, pujas y cláusulas. Un jugador aún por encontrar solo
tapa un hueco que ya existe: no sirve para justificar una venta. El dinero que
se gasta hoy no vuelve a estar el jueves, y el sobreprecio de un clausulazo
tampoco vuelve al vender al jugador.
"""

from __future__ import annotations

import math
from typing import Any

import pulp

from toolbox.analyzer import FORMATIONS, POSITIONS, XI_SIZE
from toolbox.engine.auction_intel import nota_y_veredicto
from toolbox.engine.lineup_math import solve_best_xi

# Un suplente buscado a ciegas rinde como un titular medio de esa posición.
BUSCA_PUNTOS = 4.7
# Por debajo de esto el once no cambia de verdad.
MEJORA_MINIMA = 0.1
# Jueves y viernes: se apaga el filtro y se optimiza solo por puntos.
UMBRAL_ALL_IN_DIAS = 2.0
# Mejora neta del once por encima de esto se ejecuta hoy, caiga el día que caiga.
UMBRAL_MUST_XP = 2.0
# Por debajo de esto, y si el fichaje es caro, se deja en el radar a principios de semana.
UMBRAL_HOLD_XP = 0.8
# Subida prevista a 7 días que convierte el fichaje en chollo.
UMBRAL_CHOLLO_PCT = 15.0
# Bajada prevista a 7 días que autoriza vender antes del jueves.
UMBRAL_CAIDA_PCT = -3.0
# Por debajo de un millón la mejora marginal no bloquea la caja.
UMBRAL_MUCHO_DINERO = 1_000_000
# Un lunes (4 días) cada millón tiene que rendir 0,20 puntos de más.
# Penalizacion = (dias_al_cierre / 7) * FACTOR_AJUSTE, en puntos por millón.
XP_POR_MILLON_LUNES = 0.2
DIAS_REFERENCIA_LUNES = 4.0
FACTOR_AJUSTE = XP_POR_MILLON_LUNES * 7.0 / DIAS_REFERENCIA_LUNES
# Un chollo de banquillo no suma xP. Este extra solo desempata contra no gastarlo.
BONUS_CHOLLO = 0.02
# Cláusula / valor de mercado. Por encima, solo pasa si la subida a 7 días
# cubre al menos el 60 % del sobreprecio.
RATIO_CLAUSULA_MAX = 1.35
COBERTURA_SOBREPRECIO = 0.60
# Sobreprecio que LaLiga no devuelve. Por encima, el clausulazo de un jugador
# de valor medio o bajo se descarta antes del solver.
PRIMA_QUEMADA_MAX = 3_500_000
VALOR_MEDIO_BAJO = 15_000_000
# Puntos que se restan por cada millón de prima quemada que sí entra al solver.
PENALIZACION_PRIMA_POR_MILLON = 0.45
# Ventas de titulares sanos en un mismo plan. Lesionados y sancionados no cuentan.
MAX_VENTAS_TITULARES_SANOS = 2
# Por debajo de esto el jugador no es titular: hay que reemplazarlo y no entra en el tope.
UMBRAL_BAJA = 0.20
# Desempata a favor de sacar a un lesionado cuando al once le da igual.
BONUS_REEMPLAZO_BAJA = 0.05
_MILLON = 1_000_000
_SEQ = 0


def _prefix() -> str:
    global _SEQ
    _SEQ += 1
    return f"p{_SEQ}"


def dias_al_cierre(dias_para_jornada: float | None) -> float | None:
    """Días desde hoy hasta el ``inicioJornada`` (primer partido del viernes).

    Quien llama ya midió el reloj. Si el saque pasó, el coste de la caja es nulo.
    """
    if isinstance(dias_para_jornada, bool) or not isinstance(dias_para_jornada, (int, float)):
        return None
    dias = float(dias_para_jornada)
    if not math.isfinite(dias):
        return None
    return max(0.0, dias)


def modo_liquidez(dias: float | None) -> str:
    """``VENTANA`` guarda caja. ``ALL-IN`` es jueves o viernes. ``SIN_RELOJ`` no penaliza."""
    if dias is None:
        return "SIN_RELOJ"
    if dias < UMBRAL_ALL_IN_DIAS:
        return "ALL-IN"
    return "VENTANA"


def penalizacion_por_millon(dias: float | None) -> float:
    """Puntos extra que debe rendir cada millón gastado.

    ``(dias_al_cierre / 7) * factor_ajuste``. Con 4 días sale 0,20. Con menos
    de 2 días, o sin reloj, sale 0: el solver gasta lo que el once necesite.
    """
    if dias is None or dias < UMBRAL_ALL_IN_DIAS:
        return 0.0
    return (dias / 7.0) * FACTOR_AJUSTE


def clasificar_impulso(
    *,
    mejora_neta: float,
    pct: float | None,
    euros: int,
    ventana: bool,
    all_in: bool,
) -> str:
    """MUST-BUY, CHOLLO, HOLD, ALL-IN o NORMAL.

    El must se ejecuta cualquier día. El chollo que entra en el once también.
    El de banquillo solo cabe con dos días o más: hay que poder revenderlo.
    El hold solo existe en esa misma ventana.
    """
    chollo = pct is not None and pct > UMBRAL_CHOLLO_PCT
    if mejora_neta > UMBRAL_MUST_XP:
        return "MUST-BUY"
    if chollo:
        return "CHOLLO"
    if (
        ventana
        and mejora_neta < UMBRAL_HOLD_XP
        and mejora_neta >= MEJORA_MINIMA
        and euros >= UMBRAL_MUCHO_DINERO
    ):
        return "HOLD"
    if all_in:
        return "ALL-IN"
    return "NORMAL"


def _meta(dias_crudos: float | None) -> dict[str, Any]:
    dias = dias_al_cierre(dias_crudos)
    return {
        "dias_al_cierre": None if dias is None else round(dias, 3),
        "penalizacion_liquidez": round(penalizacion_por_millon(dias), 4),
        "factor_ajuste": round(FACTOR_AJUSTE, 4),
        "modo_liquidez": modo_liquidez(dias),
    }


def _vacio(cash: int | None, ratio: float, baseline: float, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "mejora_puntos_jornada": 0.0,
        "saldo_al_final": cash,
        "nota": 0,
        "veredicto": "Opcional",
        "acciones": [],
        "formacion": None,
        "puntos_once": round(baseline, 2),
        "puntos_once_actual": round(baseline, 2),
        "ratio_mercado": round(ratio, 2) if ratio else None,
        "once": [],
        "en_radar": [],
        **meta,
    }


def _accion(
    tipo: str,
    momento: str,
    *,
    player_id: str | None,
    nombre: str,
    posicion: str | None,
    jornada: float | None,
    euros: int | None,
    detalle: str,
    impulso: str | None = None,
    mejora_neta: float | None = None,
    prevision_7d_pct: float | None = None,
) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "momento": momento,
        "impulso": impulso,
        "player_id": player_id,
        "nombre": nombre,
        "posicion": posicion,
        "jornada": jornada,
        "euros": euros,
        "mejora_neta": None if mejora_neta is None else round(mejora_neta, 2),
        "prevision_7d_pct": None if prevision_7d_pct is None else round(prevision_7d_pct, 2),
        "detalle": detalle,
    }


def _leer_pct(row: dict[str, Any]) -> float | None:
    for key in ("pct", "prevision_7d_pct"):
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            number = float(value)
            return number if math.isfinite(number) else None
        if isinstance(value, str):
            text = value.strip().replace("%", "").replace(",", ".")
            if text.startswith("+"):
                text = text[1:]
            try:
                number = float(text)
            except ValueError:
                continue
            return number if math.isfinite(number) else None
    return None


def _dias_texto(dias: float) -> str:
    if abs(dias - round(dias)) < 0.05:
        entero = int(round(dias))
        return "1 día" if entero == 1 else f"{entero} días"
    return f"{dias:.1f} días"


def _mejora_neta(row: dict[str, Any], elegibles: list[dict[str, Any]], base: float, base_ok: bool) -> float:
    fantasma = {
        "player_id": f"nuevo:{row.get('player_id')}",
        "position": row.get("position"),
        "jornada": float(row.get("jornada") or 0.0),
    }
    con = solve_best_xi([*elegibles, fantasma])
    if not con["ok"]:
        return 0.0
    origen = base if base_ok else 0.0
    return round(max(0.0, float(con["puntos"]) - origen), 4)


def _tiene_oferta(row: dict[str, Any]) -> bool:
    return row.get("tiene_oferta_laliga") is True


def _valor_jugador(row: dict[str, Any]) -> int:
    for key in ("valor", "market_value", "euros", "venta_eur"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            continue
        return value
    return 0


def _entero_positivo(row: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            continue
        return int(number)
    return None


def _prob_titular(row: dict[str, Any]) -> float | None:
    """Probabilidad de titularidad en 0–1. Acepta también un porcentaje 0–100."""
    for key in ("prob_titular", "p_titular"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if not math.isfinite(number) or number < 0:
            continue
        if number > 1.0:
            number /= 100.0
        return number
    return None


def _es_baja(row: dict[str, Any]) -> bool:
    """Lesionado o sancionado: no cuenta como titular sano y hay que reemplazarlo."""
    prob = _prob_titular(row)
    return prob is not None and prob < UMBRAL_BAJA


def _valor_mercado(row: dict[str, Any]) -> int | None:
    """Valor de mercado del jugador. El precio de la cláusula no cuenta como valor."""
    return _entero_positivo(row, "valor_mercado", "valor", "market_value")


def evaluar_patrimonio_clausula(row: dict[str, Any]) -> dict[str, Any]:
    """Sobreprecio de un clausulazo y si destruye patrimonio.

    Sin valor de mercado no se puede demostrar el destrozo: el candidato sigue
    y la prima quemada queda en cero. Con valor, se descarta si la cláusula
    pasa del +35 % y la subida a 7 días no cubre el 60 % de ese sobreprecio,
    o si la prima quemada supera 3,5 M€ en un jugador de menos de 15 M€.
    """
    clausula = _entero_positivo(row, "euros", "clausula", "clause")
    valor = _valor_mercado(row)
    pct = _leer_pct(row) or 0.0
    if clausula is None or valor is None:
        return {
            "clausula": clausula,
            "valor_mercado": valor,
            "sobreprecio_bruto": None,
            "ratio_clausula": None,
            "subida_7d_euros": 0.0,
            "prima_quemada_neta": 0.0,
            "descartar": False,
        }
    sobreprecio = float(clausula - valor)
    ratio = clausula / max(float(valor), 0.1)
    subida = float(valor) * (pct / 100.0)
    prima = max(0.0, float(clausula) - (float(valor) + subida))
    descartar = False
    if ratio > RATIO_CLAUSULA_MAX and subida < COBERTURA_SOBREPRECIO * max(sobreprecio, 0.0):
        descartar = True
    if valor < VALOR_MEDIO_BAJO and prima > PRIMA_QUEMADA_MAX:
        descartar = True
    return {
        "clausula": clausula,
        "valor_mercado": valor,
        "sobreprecio_bruto": sobreprecio,
        "ratio_clausula": ratio,
        "subida_7d_euros": subida,
        "prima_quemada_neta": prima,
        "descartar": descartar,
    }


def _es_suplente(player_id: str, plantilla: list[dict[str, Any]], xi_ids: set[str]) -> bool:
    """Sobran cuerpos y este jugador no está en el once: venderlo deja 11 reales."""
    reales = [row for row in plantilla if isinstance(row.get("player_id"), str)]
    return len(reales) >= 12 and player_id not in xi_ids


def _detalle_venta_directa(
    row: dict[str, Any],
    *,
    saldo: int,
    ventana: bool,
    financia_clausula: bool,
    baja: bool,
) -> str:
    pct = _leer_pct(row)
    if saldo < 0:
        return "Vender hoy: el saldo ya está en negativo y hay que cubrir la deuda antes del viernes."
    if financia_clausula:
        return "Vender hoy: la caja financia un clausulazo, que entra al momento y no depende de una subasta."
    if baja:
        return (
            "Vender hoy: está lesionado o sancionado (titularidad por debajo del 20 %) "
            "y el once sigue completo sin él."
        )
    if ventana and pct is not None and pct < UMBRAL_CAIDA_PCT:
        return "Vender hoy: ya hay oferta de LaLiga y el precio cae más de un 3 % a siete días."
    if ventana:
        return (
            "Vender hoy: es suplente, el once sigue con 11 titulares reales "
            "y hay oferta de LaLiga o el precio está bajando."
        )
    return "Venta para financiar el once. Conviene hacerla hoy: la caja tiene que estar lista antes de pujar."


def _emparejar_ventas(
    ventas: list[dict[str, Any]],
    pujas: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Cada venta condicional se ata a la puja que la pagaría, a ser posible del mismo puesto."""
    libres = list(pujas)
    pares: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for venta in ventas:
        mismo = next((puja for puja in libres if puja.get("position") == venta.get("position")), None)
        if mismo is None and libres:
            mismo = libres[0]
        if mismo is None:
            mismo = pujas[0]
        else:
            libres.remove(mismo)
        pares.append((venta, mismo))
    return pares


def _partir_ventas(
    *,
    saldo: int,
    ventas: list[dict[str, Any]],
    pujas: list[dict[str, Any]],
    clausulas_hechas: list[dict[str, Any]],
    plantilla: list[dict[str, Any]],
    xi_ids: set[str],
    bajas: set[str],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]], set[str], set[str]]:
    """Separa «vender hoy» de «vender solo si ganas la puja».

    Vender hoy solo cubre deuda, paga un clausulazo o saca a un suplente que
    baja o ya tiene oferta. El resto, si financia una puja, espera a ganarla.
    """
    directos: set[str] = set()
    por_deuda: set[str] = set()
    por_clausula: set[str] = set()
    if saldo < 0:
        caja = saldo
        for row in sorted(ventas, key=lambda item: int(item.get("venta_eur") or 0)):
            if caja >= 0:
                break
            directos.add(row["player_id"])
            por_deuda.add(row["player_id"])
            caja += int(row.get("venta_eur") or 0)
    gasto_clausulas = sum(int(row.get("euros") or 0) for row in clausulas_hechas)
    caja = saldo + sum(int(row.get("venta_eur") or 0) for row in ventas if row["player_id"] in directos)
    if clausulas_hechas and caja < gasto_clausulas:
        faltan = gasto_clausulas - caja
        for row in sorted(ventas, key=lambda item: -int(item.get("venta_eur") or 0)):
            if faltan <= 0:
                break
            if row["player_id"] in directos:
                continue
            directos.add(row["player_id"])
            por_clausula.add(row["player_id"])
            faltan -= int(row.get("venta_eur") or 0)
    for row in ventas:
        player_id = row["player_id"]
        if player_id in directos:
            continue
        pct = _leer_pct(row)
        bajando = pct is not None and pct < 0
        if _es_suplente(player_id, plantilla, xi_ids) and (bajando or _tiene_oferta(row) or player_id in bajas):
            directos.add(player_id)
    if not pujas:
        directos.update(row["player_id"] for row in ventas)

    def _reales_hoy(ids: set[str]) -> int:
        return len(plantilla) - len(ids) + len(clausulas_hechas)

    limite = min(XI_SIZE, len(plantilla))
    while pujas and _reales_hoy(directos) < limite:
        movibles = [
            row for row in ventas if row["player_id"] in directos and row["player_id"] not in por_clausula
        ]
        if not movibles:
            break
        # Primero se aplaza al titular: es quien dejaría el once cojo si la puja se pierde.
        movibles.sort(key=lambda row: (row["player_id"] not in xi_ids, -int(row.get("venta_eur") or 0)))
        directos.discard(movibles[0]["player_id"])
        por_deuda.discard(movibles[0]["player_id"])

    hoy = [row for row in ventas if row["player_id"] in directos]
    esperar = [row for row in ventas if row["player_id"] not in directos]
    pares = _emparejar_ventas(esperar, pujas) if esperar and pujas else []
    return hoy, pares, por_deuda, por_clausula


def _revalorizacion_hasta_viernes(row: dict[str, Any], dias: float) -> float:
    """Euros que el jugador recupera antes del saque si el precio sube.

    ``valor * (prevision_7d_pct / 100) * (dias_al_cierre / 7)``. Una bajada no
    resta: el peaje ya mira el dinero que sale, no el que se pierde después.
    """
    pct = _leer_pct(row)
    if pct is None or pct <= 0 or dias <= 0:
        return 0.0
    return _valor_jugador(row) * (pct / 100.0) * (dias / 7.0)


def _reserva_para_el_once(
    *,
    actual_ok: bool,
    elegibles: list[dict[str, Any]],
    fichas: dict[str, dict[str, Any]],
    permite_busca: bool,
    coste_busca: int,
) -> int:
    """Caja que hay que guardar para poder alinear 11 el viernes."""
    if actual_ok:
        return 0
    opciones: list[int] = []
    if permite_busca and coste_busca > 0:
        opciones.append(coste_busca)
    for ficha in fichas.values():
        if ficha.get("especulativo"):
            continue
        fantasma = {
            "player_id": f"nuevo:{ficha['row'].get('player_id')}",
            "position": ficha["row"].get("position"),
            "jornada": float(ficha["row"].get("jornada") or 0.0),
        }
        if solve_best_xi([*elegibles, fantasma])["ok"]:
            opciones.append(int(ficha["euros"]))
    return min(opciones) if opciones else 0


def build_plan_fichajes(
    *,
    cash: int | None,
    owned: list[dict[str, Any]],
    mercado: list[dict[str, Any]],
    clausulas: list[dict[str, Any]],
    ratio: float,
    dias_para_jornada: float | None,
    baseline_puntos: float,
    preparar_escaparate: bool = True,
) -> dict[str, Any]:
    """Maximiza ``xP - peaje × drenaje neto``. No envía órdenes.

    El peaje no mira el precio bruto. Mira el dinero que de verdad sale de la
    caja, ``max(0, compras no urgentes - ventas - revalorización hasta el
    viernes)``. Una rotación que se paga sola, o un jugador que sube, no
    arrastra el mismo castigo que vaciar el saldo.

    Con dos días o más, un fichaje marginal y caro va a ``en_radar``. Una venta
    que solo financia una puja no se acepta hoy: se puja, se pone al jugador
    en el escaparate y se vende mañana únicamente si la puja se gana. Vender
    hoy queda para tapar deuda, pagar un clausulazo o sacar a un suplente que
    ya tiene oferta o está bajando. Un chollo de banquillo solo entra si quedan
    al menos dos días y sobra caja para el once.
    """
    meta = _meta(dias_para_jornada)
    dias = dias_al_cierre(dias_para_jornada)
    ventana = meta["modo_liquidez"] == "VENTANA"
    all_in = meta["modo_liquidez"] == "ALL-IN"
    penalizacion = float(meta["penalizacion_liquidez"])
    saldo = cash if isinstance(cash, int) and not isinstance(cash, bool) else None
    plantilla = [row for row in owned if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    compras = [row for row in mercado if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    raids = [row for row in clausulas if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    primas: dict[str, float] = {}
    raids_ok: list[dict[str, Any]] = []
    for row in raids:
        info = evaluar_patrimonio_clausula(row)
        if info["descartar"]:
            continue
        primas[row["player_id"]] = float(info["prima_quemada_neta"])
        raids_ok.append(row)
    raids = raids_ok
    permite_busca = ventana
    coste_busca = int(round(BUSCA_PUNTOS * ratio)) if ratio and ratio > 0 else 0
    if saldo is None:
        return _vacio(None, ratio, baseline_puntos, meta)

    ventas_viernes: set[str] = set()
    if ventana and preparar_escaparate:
        # El viernes, sin peaje, dice a quién venderíamos. Hay que listarlo hoy:
        # LaLiga tarda un día en ofrecer y el jueves ya no llegaría la oferta.
        sombra = build_plan_fichajes(
            cash=saldo,
            owned=owned,
            mercado=mercado,
            clausulas=clausulas,
            ratio=ratio,
            dias_para_jornada=0,
            baseline_puntos=baseline_puntos,
            preparar_escaparate=False,
        )
        ventas_viernes = {
            accion["player_id"]
            for accion in sombra.get("acciones") or []
            if accion.get("tipo") == "VENDE" and isinstance(accion.get("player_id"), str)
        }

    elegibles = [
        row
        for row in plantilla
        if row.get("elegible") is not False
        and row.get("position") in POSITIONS
        and isinstance(row.get("jornada"), (int, float))
        and not isinstance(row.get("jornada"), bool)
    ]
    actual = solve_best_xi(elegibles)
    base_puntos = float(actual["puntos"]) if actual["ok"] else 0.0
    xi_ids = set(actual["player_ids"]) if actual["ok"] else set()
    bajas = {row["player_id"] for row in plantilla if _es_baja(row)}

    ficha_compra: dict[str, dict[str, Any]] = {}
    radar: list[dict[str, Any]] = []

    def _registrar(origen: str, row: dict[str, Any]) -> None:
        if row.get("position") not in POSITIONS:
            return
        euros = row.get("euros")
        if not isinstance(euros, int) or isinstance(euros, bool) or euros <= 0:
            return
        player_id = row["player_id"]
        clave = f"{origen}:{player_id}"
        mejora = _mejora_neta(row, elegibles, base_puntos, actual["ok"])
        pct = _leer_pct(row)
        impulso = clasificar_impulso(
            mejora_neta=mejora,
            pct=pct,
            euros=euros,
            ventana=ventana,
            all_in=all_in,
        )
        # Chollo de banquillo: no entra en el once. Sin dos días no da tiempo a revenderlo.
        especulativo = impulso == "CHOLLO" and mejora < MEJORA_MINIMA
        if especulativo and not ventana:
            return
        ficha = {
            "row": row,
            "euros": euros,
            "mejora": mejora,
            "pct": pct,
            "impulso": impulso,
            "origen": origen,
            "especulativo": especulativo,
        }
        if impulso == "HOLD":
            dias_txt = _dias_texto(dias or 0.0)
            radar.append(
                _accion(
                    "CLAUSULAZO" if origen == "clause" else "PUJA",
                    "radar",
                    player_id=player_id,
                    nombre=_nombre(row),
                    posicion=row.get("position"),
                    jornada=_jornada(row),
                    euros=euros,
                    impulso="HOLD",
                    mejora_neta=mejora,
                    prevision_7d_pct=pct,
                    detalle=(
                        f"En el radar - No pujar hoy. Mejora el once +{mejora:.1f} xP "
                        f"y el precio es alto, con {dias_txt} por delante."
                    ),
                )
            )
            return
        ficha_compra[clave] = ficha

    for row in compras:
        _registrar("bid", row)
    for row in raids:
        _registrar("clause", row)
    radar.sort(key=lambda accion: (-(accion.get("mejora_neta") or 0.0), accion.get("euros") or 0))

    prefix = _prefix()
    problem = pulp.LpProblem(f"plan_{prefix}", pulp.LpMaximize)
    en_once: dict[str, pulp.LpVariable] = {}
    vende: dict[str, pulp.LpVariable] = {}
    puja: dict[str, pulp.LpVariable] = {}
    clausula: dict[str, pulp.LpVariable] = {}
    pct_propio: dict[str, float | None] = {}

    for index, row in enumerate(plantilla):
        player_id = row["player_id"]
        pct_propio[player_id] = _leer_pct(row)
        juega = pulp.LpVariable(f"{prefix}_o{index}", cat=pulp.LpBinary)
        en_once[f"own:{player_id}"] = juega
        if row.get("elegible") is False or row.get("position") not in POSITIONS:
            problem += juega == 0
        venta = row.get("venta_eur")
        if isinstance(venta, int) and not isinstance(venta, bool) and venta > 0:
            venta_var = pulp.LpVariable(f"{prefix}_v{index}", cat=pulp.LpBinary)
            vende[player_id] = venta_var
            problem += juega + venta_var <= 1
        else:
            problem += juega <= 1

    sanos = [player_id for player_id in vende if player_id in xi_ids and player_id not in bajas]
    if sanos:
        # Tope de rotación: un lesionado no gasta plaza de este cupo.
        problem += pulp.lpSum(vende[player_id] for player_id in sanos) <= MAX_VENTAS_TITULARES_SANOS

    def _alta_compra(
        origen: str,
        row: dict[str, Any],
        index: int,
        destino: dict[str, pulp.LpVariable],
        modelo: pulp.LpProblem,
    ) -> None:
        clave = f"{origen}:{row['player_id']}"
        ficha = ficha_compra.get(clave)
        if ficha is None:
            return
        compra = pulp.LpVariable(f"{prefix}_{origen[0]}{index}", cat=pulp.LpBinary)
        alineado = pulp.LpVariable(f"{prefix}_{origen[0]}x{index}", cat=pulp.LpBinary)
        destino[row["player_id"]] = compra
        en_once[clave] = alineado
        if ficha.get("especulativo"):
            # Banquillo: se compra por el precio, no para alinearlo hoy.
            modelo += alineado <= compra
        elif ficha["impulso"] == "CHOLLO":
            modelo += alineado <= compra
        else:
            modelo += alineado == compra

    for index, row in enumerate(compras):
        _alta_compra("bid", row, index, puja, problem)
    for index, row in enumerate(raids):
        _alta_compra("clause", row, index, clausula, problem)

    # Una venta no puede dejar menos de 11 jugadores con nombre. El «busca un DEF»
    # no cuenta como sustituto: si ya hay once real, ni siquiera se ofrece.
    fichajes_con_nombre = list(puja.values()) + list(clausula.values())
    if vende or fichajes_con_nombre:
        problem += pulp.lpSum(list(vende.values()) or [0]) <= pulp.lpSum(fichajes_con_nombre or [0]) + max(
            0, len(plantilla) - XI_SIZE
        )

    busca = {position: pulp.LpVariable(f"{prefix}_b{position}", cat=pulp.LpBinary) for position in POSITIONS}
    if len(elegibles) < XI_SIZE and permite_busca and coste_busca > 0:
        problem += pulp.lpSum(busca.values()) <= 1
    else:
        for variable in busca.values():
            problem += variable == 0

    formacion = {
        name: pulp.LpVariable(f"{prefix}_f{name.replace('-', '_')}", cat=pulp.LpBinary) for name in FORMATIONS
    }
    problem += pulp.lpSum(formacion.values()) == 1

    def _de(prefijo: str, posicion: str) -> list[pulp.LpVariable]:
        origen = {"own": plantilla, "bid": compras, "clause": raids}[prefijo]
        claves = {"own": "own:", "bid": "bid:", "clause": "clause:"}[prefijo]
        salida = []
        for row in origen:
            if row.get("position") != posicion:
                continue
            variable = en_once.get(f"{claves}{row['player_id']}")
            if variable is not None:
                salida.append(variable)
        return salida

    todos = list(en_once.values()) + list(busca.values())
    problem += pulp.lpSum(todos) == XI_SIZE
    for position in POSITIONS:
        ocupantes = _de("own", position) + _de("bid", position) + _de("clause", position) + [busca[position]]
        problem += pulp.lpSum(ocupantes) == pulp.lpSum(
            FORMATIONS[name][position] * formacion[name] for name in FORMATIONS
        )

    def _euros_de(clave: str) -> int:
        return int(ficha_compra[clave]["euros"])

    ingresos = pulp.lpSum(
        int(row["venta_eur"]) * vende[row["player_id"]]
        for row in plantilla
        if row["player_id"] in vende and isinstance(row.get("venta_eur"), int)
    )
    gastos_puja = pulp.lpSum(
        _euros_de(f"bid:{row['player_id']}") * puja[row["player_id"]] for row in compras if row["player_id"] in puja
    )
    gastos_clausula = pulp.lpSum(
        _euros_de(f"clause:{row['player_id']}") * clausula[row["player_id"]]
        for row in raids
        if row["player_id"] in clausula
    )
    gastos_busca = pulp.lpSum(coste_busca * busca[position] for position in POSITIONS)
    problem += saldo + ingresos - gastos_puja - gastos_clausula - gastos_busca >= 0

    def _exento_peaje(clave: str) -> bool:
        return ficha_compra[clave]["impulso"] in {"MUST-BUY", "CHOLLO"}

    def _es_prioritario(clave: str) -> bool:
        ficha = ficha_compra[clave]
        # El chollo de banquillo no autoriza a malvender a nadie para pagarlo.
        return ficha["impulso"] in {"MUST-BUY", "CHOLLO"} and not ficha.get("especulativo")

    gastos_prioritarios = pulp.lpSum(
        [
            *(_euros_de(f"bid:{pid}") * variable for pid, variable in puja.items() if _es_prioritario(f"bid:{pid}")),
            *(
                _euros_de(f"clause:{pid}") * variable
                for pid, variable in clausula.items()
                if _es_prioritario(f"clause:{pid}")
            ),
        ]
    )
    gastos_resto = pulp.lpSum(
        [
            *(_euros_de(f"bid:{pid}") * variable for pid, variable in puja.items() if not _exento_peaje(f"bid:{pid}")),
            *(
                _euros_de(f"clause:{pid}") * variable
                for pid, variable in clausula.items()
                if not _exento_peaje(f"clause:{pid}")
            ),
            *(coste_busca * busca[position] for position in POSITIONS),
        ]
    )
    oferta_firme = {row["player_id"]: _tiene_oferta(row) for row in plantilla}
    # Sin oferta de LaLiga no se puede aceptar hoy, salvo para tapar un saldo ya negativo.
    if ventana and saldo >= 0:
        for player_id in list(vende):
            if not oferta_firme.get(player_id):
                problem += vende[player_id] == 0

    def _venta_libre(player_id: str) -> bool:
        if not ventana or saldo < 0:
            return True
        if not oferta_firme.get(player_id):
            return False
        pct = pct_propio.get(player_id)
        return player_id in bajas or (pct is not None and pct < UMBRAL_CAIDA_PCT)

    vende_libre = [player_id for player_id in vende if _venta_libre(player_id)]
    vende_cond = [player_id for player_id in vende if player_id not in set(vende_libre)]
    ingresos_libres = pulp.lpSum(
        int(row["venta_eur"]) * vende[row["player_id"]]
        for row in plantilla
        if row["player_id"] in vende_libre and isinstance(row.get("venta_eur"), int)
    )
    if ventana:
        # La caja de una venta anticipada solo puede tapar un must-buy que no cabe.
        problem += gastos_resto <= saldo + ingresos_libres
        prioritarios = [
            *(puja[pid] for pid in puja if _es_prioritario(f"bid:{pid}")),
            *(clausula[pid] for pid in clausula if _es_prioritario(f"clause:{pid}")),
        ]
        if vende_cond and not prioritarios:
            for player_id in vende_cond:
                problem += vende[player_id] == 0
        elif vende_cond and prioritarios:
            need = pulp.LpVariable(f"{prefix}_need", cat=pulp.LpBinary)
            techo = sum(
                _euros_de(clave)
                for clave in list(ficha_compra)
                if _es_prioritario(clave)
            ) + saldo + 1
            problem += gastos_prioritarios <= saldo + techo * need
            problem += gastos_prioritarios >= (saldo + 1) - techo * (1 - need)
            problem += pulp.lpSum(vende[player_id] for player_id in vende_cond) <= len(vende_cond) * need

    especulativos = [
        *(puja[pid] * _euros_de(f"bid:{pid}") for pid in puja if ficha_compra[f"bid:{pid}"].get("especulativo")),
        *(
            clausula[pid] * _euros_de(f"clause:{pid}")
            for pid in clausula
            if ficha_compra[f"clause:{pid}"].get("especulativo")
        ),
    ]
    if especulativos:
        reserva = _reserva_para_el_once(
            actual_ok=actual["ok"],
            elegibles=elegibles,
            fichas=ficha_compra,
            permite_busca=permite_busca,
            coste_busca=coste_busca,
        )
        holgura = max(0, saldo - reserva)
        # El chollo de banquillo solo gasta la caja que sobra después de poder alinear 11.
        problem += pulp.lpSum(especulativos) <= holgura

    puntos = pulp.lpSum(float(row.get("jornada") or 0.0) * en_once[f"own:{row['player_id']}"] for row in plantilla)
    puntos += pulp.lpSum(
        float(row.get("jornada") or 0.0) * en_once[f"bid:{row['player_id']}"]
        for row in compras
        if f"bid:{row['player_id']}" in en_once
    )
    puntos += pulp.lpSum(
        float(row.get("jornada") or 0.0) * en_once[f"clause:{row['player_id']}"]
        for row in raids
        if f"clause:{row['player_id']}" in en_once
    )
    puntos += pulp.lpSum(BUSCA_PUNTOS * busca[position] for position in POSITIONS)
    bonus = pulp.lpSum(
        [
            *(
                (BONUS_CHOLLO + max(ficha_compra[f"bid:{pid}"].get("pct") or 0.0, 0.0) * 1e-5) * variable
                for pid, variable in puja.items()
                if ficha_compra[f"bid:{pid}"]["impulso"] == "CHOLLO"
            ),
            *(
                (BONUS_CHOLLO + max(ficha_compra[f"clause:{pid}"].get("pct") or 0.0, 0.0) * 1e-5) * variable
                for pid, variable in clausula.items()
                if ficha_compra[f"clause:{pid}"]["impulso"] == "CHOLLO"
            ),
        ]
    )
    revalorizacion = pulp.lpSum(
        [
            *(
                _revalorizacion_hasta_viernes(ficha_compra[f"bid:{pid}"]["row"], dias or 0.0) * variable
                for pid, variable in puja.items()
                if not _exento_peaje(f"bid:{pid}")
            ),
            *(
                _revalorizacion_hasta_viernes(ficha_compra[f"clause:{pid}"]["row"], dias or 0.0) * variable
                for pid, variable in clausula.items()
                if not _exento_peaje(f"clause:{pid}")
            ),
        ]
    )
    # drenaje_neto = max(0, compras no urgentes - ventas - subida hasta el viernes).
    # Una rotación que se paga sola, o un +8 % semanal, no pagan el precio bruto.
    if penalizacion > 0:
        drenaje = pulp.LpVariable(f"{prefix}_drenaje", lowBound=0)
        problem += drenaje >= gastos_resto - ingresos - revalorizacion
        peaje = (penalizacion / _MILLON) * drenaje
    else:
        peaje = 0
    # La prima quemada es dinero que no vuelve. Se resta aunque el peaje de liquidez esté apagado.
    castigo_patrimonio = pulp.lpSum(
        (primas.get(player_id, 0.0) / _MILLON) * PENALIZACION_PRIMA_POR_MILLON * variable
        for player_id, variable in clausula.items()
    )
    bonus_baja = pulp.lpSum(BONUS_REEMPLAZO_BAJA * vende[player_id] for player_id in bajas if player_id in vende)
    problem += (
        puntos
        + bonus
        + bonus_baja
        - peaje
        - castigo_patrimonio
        - 0.0001 * pulp.lpSum(list(vende.values()) or [0])
        - 1e-12 * (gastos_puja + gastos_clausula + gastos_busca + ingresos)
    )

    def _escaparate(vendidos: set[str]) -> list[dict[str, Any]]:
        if not ventana:
            return []
        salida: list[dict[str, Any]] = []
        for row in plantilla:
            player_id = row["player_id"]
            if player_id not in ventas_viernes or player_id in vendidos:
                continue
            venta = row.get("venta_eur")
            if isinstance(venta, bool) or not isinstance(venta, int) or venta <= 0:
                continue
            pct = pct_propio.get(player_id)
            if pct is not None and pct > 0:
                detalle = (
                    "Ponlo en mercado para tener oferta de LaLiga, pero no aceptes "
                    "hasta el jueves/viernes mientras sube"
                )
            elif not oferta_firme.get(player_id):
                detalle = (
                    "Ponlo en mercado para tener oferta de LaLiga antes del jueves. "
                    "Hoy no hay oferta que aceptar, y el viernes ya no llegaría a tiempo."
                )
            else:
                detalle = "Ya hay oferta de LaLiga. No la aceptes hasta el jueves o el viernes."
            salida.append(
                _accion(
                    "ESCAPARATE",
                    "hoy",
                    player_id=player_id,
                    nombre=_nombre(row),
                    posicion=row.get("position"),
                    jornada=_jornada(row),
                    euros=venta,
                    detalle=detalle,
                    impulso="ESCAPARATE",
                    prevision_7d_pct=pct,
                )
            )
        return salida

    status = problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=5))
    if pulp.LpStatus.get(status, "") != "Optimal":
        vacio = _vacio(saldo, ratio, baseline_puntos, meta)
        vacio["en_radar"] = radar
        vacio["acciones"] = _escaparate(set())
        return vacio

    def _on(variable: pulp.LpVariable | None) -> bool:
        return variable is not None and (variable.value() or 0.0) > 0.5

    chosen_form = next((name for name, variable in formacion.items() if _on(variable)), None)
    once: list[dict[str, Any]] = []
    puntos_once = 0.0
    for row in plantilla:
        if _on(en_once.get(f"own:{row['player_id']}")):
            puntos_once += float(row.get("jornada") or 0.0)
            once.append(_ficha(row, "plantilla"))
    acciones: list[dict[str, Any]] = []
    ingreso = 0
    gasto = 0
    ventas_sel = [row for row in plantilla if row["player_id"] in vende and _on(vende[row["player_id"]])]
    pujas_sel = [row for row in compras if row["player_id"] in puja and _on(puja[row["player_id"]])]
    clausulas_sel = [row for row in raids if row["player_id"] in clausula and _on(clausula[row["player_id"]])]
    ventas_hoy, pares, por_deuda, por_clausula = _partir_ventas(
        saldo=saldo,
        ventas=ventas_sel,
        pujas=pujas_sel,
        clausulas_hechas=clausulas_sel,
        plantilla=plantilla,
        xi_ids=xi_ids,
        bajas=bajas,
    )
    # El viernes ya no hay «mañana» antes del saque: la venta que financia el plan se acepta hoy.
    if dias is not None and dias < 1.0 and pares:
        ventas_hoy.extend(venta for venta, _puja in pares)
        pares = []
    pujas_protegidas = {puja_row["player_id"] for _venta, puja_row in pares}
    ya_en_secuencia = {venta["player_id"] for venta, _puja in pares}
    for row in ventas_sel:
        ingreso += int(row["venta_eur"])
    for row in ventas_hoy:
        pct = pct_propio.get(row["player_id"])
        acciones.append(
            _accion(
                "VENDER HOY" if ventana else "VENDE",
                "hoy",
                player_id=row["player_id"],
                nombre=_nombre(row),
                posicion=row.get("position"),
                jornada=_jornada(row),
                euros=int(row["venta_eur"]),
                detalle=_detalle_venta_directa(
                    row,
                    saldo=saldo if row["player_id"] in por_deuda else 0,
                    ventana=ventana,
                    financia_clausula=row["player_id"] in por_clausula,
                    baja=row["player_id"] in bajas,
                ),
                impulso="VENTA",
                prevision_7d_pct=pct,
            )
        )
    for venta, puja_row in pares:
        nombre_venta = _nombre(venta)
        nombre_puja = _nombre(puja_row)
        pct = pct_propio.get(venta["player_id"])
        acciones.append(
            _accion(
                "ESCAPARATE",
                "hoy",
                player_id=venta["player_id"],
                nombre=nombre_venta,
                posicion=venta.get("position"),
                jornada=_jornada(venta),
                euros=int(venta["venta_eur"]),
                detalle=f"PONER EN ESCAPARATE a {nombre_venta} (Para tener oferta de LaLiga mañana)",
                impulso="ESCAPARATE",
                prevision_7d_pct=pct,
            )
        )
        acciones.append(
            _accion(
                "VENDE",
                "condicional",
                player_id=venta["player_id"],
                nombre=nombre_venta,
                posicion=venta.get("position"),
                jornada=_jornada(venta),
                euros=int(venta["venta_eur"]),
                detalle=f"VENDER A {nombre_venta} SOLO SI GANAS LA PUJA DE {nombre_puja}",
                impulso="VENTA",
                prevision_7d_pct=pct,
            )
        )

    def _momento_y_detalle(ficha: dict[str, Any]) -> tuple[str, str]:
        row = ficha["row"]
        impulso = ficha["impulso"]
        mejora = float(ficha["mejora"])
        if impulso == "CHOLLO":
            return (
                "hoy",
                "Chollo: la previsión a 7 días supera el 15 %. Ejecutar hoy, aunque quede semana por delante.",
            )
        if impulso == "MUST-BUY" and ventana:
            texto = f"Must-buy: mejora el once en +{mejora:.1f} xP. Ejecutar hoy."
            if row.get("caduca_hoy") is True:
                texto += " La puja caduca hoy."
            return "hoy", texto
        if impulso == "MUST-BUY":
            texto = f"Must-buy: mejora el once en +{mejora:.1f} xP."
            if row.get("caduca_hoy") is True:
                return "hoy", texto + " La puja caduca hoy."
            return "luego", texto
        if row.get("caduca_hoy") is True:
            return "hoy", "La puja de LaLiga caduca hoy. Si encaja, hay que entrarla antes del cierre."
        if ficha["origen"] == "clause":
            return "luego", "La cláusula está abierta y sus puntos por euro superan al mercado."
        return "luego", "Puja del mercado de LaLiga al precio recomendado."

    for row in compras:
        if row["player_id"] not in puja or not _on(puja[row["player_id"]]):
            continue
        ficha = ficha_compra[f"bid:{row['player_id']}"]
        euros = int(ficha["euros"])
        gasto += euros
        if _on(en_once.get(f"bid:{row['player_id']}")):
            puntos_once += float(row.get("jornada") or 0.0)
            once.append(_ficha(row, "puja"))
        momento, detalle = _momento_y_detalle(ficha)
        if row["player_id"] in pujas_protegidas:
            # La puja va hoy; la venta que la paga espera a saber si se gana.
            momento = "hoy"
            detalle = f"PUJAR POR {_nombre(row)}. {detalle}"
        acciones.append(
            _accion(
                "PUJA",
                momento,
                player_id=row["player_id"],
                nombre=_nombre(row),
                posicion=row.get("position"),
                jornada=_jornada(row),
                euros=euros,
                detalle=detalle,
                impulso=ficha["impulso"],
                mejora_neta=ficha["mejora"],
                prevision_7d_pct=ficha["pct"],
            )
        )
    for row in raids:
        if row["player_id"] not in clausula or not _on(clausula[row["player_id"]]):
            continue
        ficha = ficha_compra[f"clause:{row['player_id']}"]
        euros = int(ficha["euros"])
        gasto += euros
        if _on(en_once.get(f"clause:{row['player_id']}")):
            puntos_once += float(row.get("jornada") or 0.0)
            once.append(_ficha(row, "clausulazo"))
        momento, detalle = _momento_y_detalle(ficha)
        prima = primas.get(row["player_id"], 0.0)
        if prima > 0:
            detalle += f" Prima quemada de {prima / _MILLON:.2f} M€: ese sobreprecio no vuelve al venderlo."
        acciones.append(
            _accion(
                "CLAUSULAZO",
                momento,
                player_id=row["player_id"],
                nombre=_nombre(row),
                posicion=row.get("position"),
                jornada=_jornada(row),
                euros=euros,
                detalle=detalle,
                impulso=ficha["impulso"],
                mejora_neta=ficha["mejora"],
                prevision_7d_pct=ficha["pct"],
            )
        )
    for position, variable in busca.items():
        if _on(variable):
            gasto += coste_busca
            puntos_once += BUSCA_PUNTOS
            nombre = f"BUSCA un {position} de ~{BUSCA_PUNTOS} pts"
            once.append(
                {
                    "player_id": None,
                    "nombre": nombre,
                    "posicion": position,
                    "jornada": BUSCA_PUNTOS,
                    "origen": "busca",
                }
            )
            acciones.append(
                _accion(
                    "BUSCA",
                    "luego",
                    player_id=None,
                    nombre=nombre,
                    posicion=position,
                    jornada=BUSCA_PUNTOS,
                    euros=coste_busca,
                    detalle=f"{nombre}. Coste estimado con el ratio de la liga, para tapar el hueco antes del saque.",
                    impulso="NORMAL",
                )
            )

    mejora = round(puntos_once - float(baseline_puntos), 2)
    hay_urgente = any(accion.get("impulso") in {"MUST-BUY", "CHOLLO"} for accion in acciones)
    vende_baja = any(row["player_id"] in bajas for row in ventas_sel)
    cubre_deuda = saldo < 0 and bool(ventas_hoy)
    if mejora < MEJORA_MINIMA and not hay_urgente and not vende_baja and not cubre_deuda:
        vacio = _vacio(saldo, ratio, baseline_puntos, meta)
        vacio["en_radar"] = radar
        vacio["acciones"] = _escaparate(set())
        return vacio
    saldo_final = int(saldo + ingreso - gasto)
    nota, veredicto = nota_y_veredicto(mejora, acciones)
    if hay_urgente:
        veredicto = "Hazlo ya"
        nota = max(nota, 8)
    manejados = {row["player_id"] for row in ventas_hoy} | ya_en_secuencia
    acciones.extend(_escaparate(manejados))
    orden = {"hoy": 0, "condicional": 1, "luego": 2}
    tipo_orden = {"PUJA": 0, "ESCAPARATE": 1, "VENDER HOY": 2, "VENDE": 3, "CLAUSULAZO": 4, "BUSCA": 5}
    acciones.sort(key=lambda accion: (orden.get(str(accion["momento"]), 9), tipo_orden.get(str(accion["tipo"]), 9)))
    return {
        "ok": True,
        "mejora_puntos_jornada": mejora,
        "saldo_al_final": saldo_final,
        "nota": nota,
        "veredicto": veredicto,
        "acciones": acciones,
        "formacion": chosen_form,
        "puntos_once": round(puntos_once, 2),
        "puntos_once_actual": round(float(baseline_puntos), 2),
        "ratio_mercado": round(ratio, 2) if ratio else None,
        "once": once,
        "en_radar": radar,
        **meta,
    }


def _nombre(row: dict[str, Any]) -> str:
    for key in ("nombre", "nickname", "name", "player_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "jugador"


def _jornada(row: dict[str, Any]) -> float | None:
    value = row.get("jornada")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 2)


def _ficha(row: dict[str, Any], origen: str) -> dict[str, Any]:
    return {
        "player_id": row.get("player_id"),
        "nombre": _nombre(row),
        "posicion": row.get("position"),
        "jornada": _jornada(row),
        "origen": origen,
    }

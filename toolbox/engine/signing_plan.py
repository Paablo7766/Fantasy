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
from toolbox.engine.auction_intel import nota_y_veredicto, prima_quemada_mercado
from toolbox.engine.lineup_math import HUECO_OBLIGATORIO, penalizacion_varianza, solve_best_xi
from toolbox.engine.paron import dias_de_prevision
from toolbox.engine.trading_desk import DEUDA_PCT_EQUIPO, build_trading_desk

# Un suplente buscado a ciegas rinde como un titular medio de esa posición.
BUSCA_PUNTOS = 4.7
# Por debajo de esto el once no cambia de verdad.
MEJORA_MINIMA = 0.1
# Mejora mínima del once para cambiar de plan. Con xP ruidosos, un +0,2 es
# ruido, y seguirlo hace que el plan salte de un jugador a otro cada mañana.
# Seguir con los objetivos de ayer solo exige MEJORA_MINIMA. Valor inicial,
# pendiente de calibrar con plan_snapshots y los puntos reales.
UMBRAL_CAMBIO_XP = 0.5
# Peso de cada una de las tres jornadas siguientes (campo ``futuro``, su suma)
# frente a la próxima, que pesa 1. La mitad: el once de dentro de dos semanas no
# es seguro (rotaciones, lesiones, otro mercado) y la proyección de J2-J4 es más
# gruesa. Con 0,5 la próxima jornada pesa el 40 % y las otras tres el 60 %.
PESO_FUTURO = 0.5
# Prima en el objetivo por fichar a quien ya recomendó el plan anterior. Un
# objetivo nuevo tiene que ganarle por más que esto para desplazarlo.
CONTINUIDAD_XP = 0.4
# Jueves y viernes: se apaga el filtro y se optimiza solo por puntos.
UMBRAL_ALL_IN_DIAS = 2.0
# Mejora neta del once por encima de esto se ejecuta hoy, caiga el día que caiga.
UMBRAL_MUST_XP = 2.0
# El peaje no se apaga de golpe en UMBRAL_MUST_XP: se descuenta con una curva
# logística. psi(0,4)=0,98 · psi(1,6)=0,50 · psi(2,0)=0,20 · psi(2,5)=0,04.
PSI_CENTRO_XP = 1.6
PSI_PENDIENTE = 3.5
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
# Cláusula / valor de mercado. Por encima, solo pasa si la subida a 7 días
# cubre al menos el 60 % del sobreprecio.
# Frente 20: las cláusulas por encima de 1,25× perdieron en 6/6 (−4,91 M€). Techo duro.
RATIO_CLAUSULA_MAX = 1.25
PARCHE_SUPERVIVENCIA_EUR = 1_500_000
COBERTURA_SOBREPRECIO = 0.60
# Sobreprecio que LaLiga no devuelve. Por encima, el clausulazo de un jugador
# de valor medio o bajo se descarta antes del solver.
PRIMA_QUEMADA_MAX = 3_500_000
VALOR_MEDIO_BAJO = 15_000_000
# Puntos que se restan por cada millón de prima quemada que sí entra al solver.
PENALIZACION_PRIMA_POR_MILLON = 0.45
# Ventas de titulares sanos en un mismo plan. Lesionados y sancionados no cuentan.
MAX_VENTAS_TITULARES_SANOS = 2
# Vender a un titular consolidado (en el once, sano y con p_titular >= 60 %)
# cuesta esto en el objetivo, en puntos por jornada del horizonte. El plan solo
# lo vende si, ya descontadas primas y peaje, el once gana al menos esto por
# cada uno: evita el vaivén de vender hoy a Isco y recomprar mañana.
UMBRAL_VENTA_TITULAR_XP = 1.5
P_TITULAR_CONSOLIDADO = 0.60
# Por debajo de esto el jugador no es titular: hay que reemplazarlo y no entra en el tope.
UMBRAL_BAJA = 0.20
# Una compra para el once exige que el jugador sea titular probable: con menos
# de la mitad de opciones de jugar, su xP sale de un once que no se va a dar.
P_TITULAR_COMPRA = 0.50
# Desempata a favor de sacar a un lesionado cuando al once le da igual.
BONUS_REEMPLAZO_BAJA = 0.05
_MILLON = 1_000_000
# Escaparate solo en la semana del cierre (un lunes normal son ~4 días). Un
# anuncio dura como mucho 3 días y LaLiga renueva su oferta a diario: listar a
# 13 días del cierre (parón) solo hace que caduque antes de necesitarla.
DIAS_ESCAPARATE = 4.5
# Parón (más de DIAS_ESCAPARATE al cierre): el saldo puede estar en negativo,
# dentro del 20 % de deuda, hasta el saque sin ninguna sanción. Dejar ese cupo
# parado es perder la subida del mercado. Solo lo usan las pujas que lo
# merecen: una subida prevista a 7 días de este porcentaje o más, o una mejora
# clara del once. Las ventas para cuadrar la caja se deciden a DIAS_DECIDIR_VENTAS
# del cierre, con el fichaje ya revalorizado.
CREDITO_PARON_PCT = 12.0
CREDITO_PARON_MEJORA = 2.0
DIAS_DECIDIR_VENTAS = 3.0
_SEQ = 0
ETIQUETA_COMPRA = {"PUJA": "PUJAR", "CLAUSULAZO": "CLAUSULAR"}
# Fichajes fuertes que no caben en la caja de hoy y se enseñan como alternativa.
MAX_ALTERNATIVAS = 5
# Esqueleto que tiene que quedar en propiedad, sin contar pujas. Por debajo de
# esto no hay formación legal (el mínimo real lo marca FORMATIONS).
ESQUELETO_MINIMO = {"POR": 1, "DEF": 3, "MC": 3, "DEL": 1}


def _presupuesto(
    *,
    saldo: int,
    ventas_hoy: list[dict[str, Any]],
    pares: list[tuple[dict[str, Any], dict[str, Any]]],
    gasto_pujas: int,
    gasto_clausulas: int,
    tope_deuda: int | None,
    credito_paron: int = 0,
) -> dict[str, Any]:
    """De dónde sale cada euro del plan. Lo garantiza el solver; aquí se publica y se comprueba.

    Cláusula: solo caja positiva más ventas aceptadas hoy (LaLiga no da crédito).
    Puja: además, las ventas que se hacen solo si se gana. El crédito del 20 %
    se publica pero el plan no lo gasta: el saldo tiene que acabar en cero o más
    antes del saque o la jornada puntúa 0. Única excepción, el parón: hasta el
    saque no hay sanción, así que ``credito_paron`` suma a lo disponible para
    pujas (nunca para cláusulas) y hay que saldarlo vendiendo antes del cierre.
    """
    ingresos_hoy = sum(int(row["venta_eur"]) for row in ventas_hoy)
    condicionales = sum(int(venta["venta_eur"]) for venta, _puja in pares)
    para_clausulas = max(0, saldo) + ingresos_hoy
    para_pujas = saldo + ingresos_hoy + condicionales - gasto_clausulas + credito_paron
    return {
        "caja": saldo,
        "ventas_hoy": ingresos_hoy,
        "ventas_si_ganas": condicionales,
        "credito_20pct": tope_deuda,
        "credito_paron": credito_paron,
        "disponible_clausulas": para_clausulas,
        "disponible_pujas": para_pujas,
        "gasto_clausulas": gasto_clausulas,
        "gasto_pujas": gasto_pujas,
        "holgura": para_pujas - gasto_pujas,
        "cumple": gasto_clausulas <= para_clausulas and gasto_pujas <= para_pujas,
    }


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


def factor_peaje(mejora_neta: float | None) -> float:
    """Fracción del peaje que paga un fichaje según lo que mejora el once.

    Logística continua: dos fichajes casi iguales en xP pagan casi lo mismo,
    sin el salto de 0 a 100 % en UMBRAL_MUST_XP.
    """
    if mejora_neta is None or isinstance(mejora_neta, bool) or not math.isfinite(mejora_neta):
        return 1.0
    exponente = PSI_PENDIENTE * (float(mejora_neta) - PSI_CENTRO_XP)
    if exponente > 60.0:
        return 0.0
    if exponente < -60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(exponente))


# Caja que debe sobrar DESPUÉS de pagar un fichaje para que su peaje de liquidez
# se apague del todo. Por debajo se descuenta en línea recta.
COLCHON_SIN_PEAJE_EUR = 10_000_000


def escasez_de_caja(caja: int | float | None, euros: int | float) -> float:
    """Fracción del peaje que sigue vigente para un fichaje según lo que sobra de caja.

    El peaje guarda liquidez. Si pagar este fichaje deja al menos
    ``COLCHON_SIN_PEAJE_EUR`` en caja, guardarla no tiene ningún uso mejor y no
    debe frenar una compra que mejora el once. Sin sobrante, paga entero.
    """
    if caja is None:
        return 1.0
    sobra = float(caja) - float(euros)
    return max(0.0, min(1.0, 1.0 - sobra / COLCHON_SIN_PEAJE_EUR))


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


def _cambio_hoy_pct(row: dict[str, Any]) -> float | None:
    """Cambio de hoy en % (el delta ya está dentro del valor). ``None`` sin dato."""
    delta = row.get("delta_hoy")
    valor = _valor_jugador(row)
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or valor <= 0:
        return None
    base = valor - float(delta)
    if base <= 0:
        return None
    return float(delta) / base * 100.0


def merece_credito_paron(
    *,
    origen: str,
    pct: float | None,
    mejora: float,
    cambio_hoy_pct: float | None = None,
) -> bool:
    """Puja que puede pagarse con el crédito del parón: sube mucho o mejora el once de verdad.

    Las cláusulas se pagan siempre con caja: LaLiga no da crédito para ellas.
    Quien mejora el once pero se prevé que baje no entra. En el parón tampoco
    entra quien sigue cayendo hoy (J12: 12 de 13 titulares en dip siguieron
    bajando el lunes aunque hubieran puntuado).
    """
    if origen != "bid":
        return False
    if (
        cambio_hoy_pct is not None
        and not isinstance(cambio_hoy_pct, bool)
        and isinstance(cambio_hoy_pct, (int, float))
        and float(cambio_hoy_pct) < 0
    ):
        return False
    if pct is not None and pct >= CREDITO_PARON_PCT:
        return True
    return mejora >= CREDITO_PARON_MEJORA and (pct is None or pct >= 0)


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
        "huecos_obligatorios": [],
        "presupuesto": None,
        "alternativas_liquidez": [],
        # «sin_cambios»: el cálculo terminó y nada mejora el once. Los fallos lo sobrescriben.
        "estado_calculo": "sin_cambios",
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
        # Qué botón hay que pulsar: pujar en el mercado o pagar la cláusula a un rival.
        "etiqueta": ETIQUETA_COMPRA.get(tipo),
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


def _futuro(row: dict[str, Any]) -> float:
    value = row.get("futuro")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _futuro_efectivo(row: dict[str, Any]) -> float:
    """xP sumado de J2-J4. Sin calendario, la próxima jornada repetida tres veces."""
    futuro = _futuro(row)
    if futuro > 0:
        return futuro
    return 3.0 * float(row.get("jornada") or 0.0)


def _horizonte(puntos_j1: float, puntos_futuro: float) -> float:
    """Media ponderada por jornada: la próxima pesa 1 y cada una de las tres siguientes, PESO_FUTURO.

    Queda en puntos de una jornada, la escala en la que están el peaje, la
    prima de continuidad y el umbral.
    """
    return (puntos_j1 + PESO_FUTURO * puntos_futuro) / (1.0 + 3.0 * PESO_FUTURO)


def _mejor_once_futuro(plantilla: list[dict[str, Any]]) -> float:
    """Puntos de J2-J4 del mejor once que sale de la plantilla, sin mirar quién juega la próxima."""
    filas = [
        {**row, "jornada": _futuro_efectivo(row)}
        for row in plantilla
        if row.get("position") in POSITIONS
    ]
    once = solve_best_xi(filas)
    return float(once["puntos"]) if once["ok"] else 0.0


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


def _texto_credito_paron(ficha: dict[str, Any], dias: float, credito: int) -> str:
    """Por qué se puja hoy con deuda y cuándo hay que decidir las ventas."""
    mejora = float(ficha["mejora"])
    pct = ficha.get("pct")
    motivos: list[str] = []
    if mejora >= CREDITO_PARON_MEJORA:
        motivos.append(f"mejora el once +{mejora:.1f} xP")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool) and pct >= CREDITO_PARON_PCT:
        motivos.append(f"se prevé una subida del {pct:.0f} % a 7 días")
    decidir = max(0.0, dias - DIAS_DECIDIR_VENTAS)
    return (
        f"Parón: {' y '.join(motivos)}. Se puja hoy aunque el saldo quede en negativo "
        f"(el plan usa {credito / _MILLON:.1f} M€ de crédito, dentro del 20 %): hasta el saque no hay sanción. "
        f"No vendas hoy. Decide a quién vender dentro de {_dias_texto(decidir)}, "
        f"con el fichaje ya revalorizado, y deja el saldo en cero o más antes del saque (en {_dias_texto(dias)})."
    )


def _mejora_neta(row: dict[str, Any], elegibles: list[dict[str, Any]], base: float, base_ok: bool) -> float:
    fantasma = {
        "player_id": f"nuevo:{row.get('player_id')}",
        "position": row.get("position"),
        "jornada": float(row.get("jornada") or 0.0),
    }
    if base_ok:
        con = solve_best_xi([*elegibles, fantasma])
        if not con["ok"]:
            return 0.0
        return round(max(0.0, float(con["puntos"]) - base), 4)
    # Plantilla sin once legal (por ejemplo 10 jugadores): el hueco vale 0 puntos.
    # Se compara contra el mejor once con un suplente de 0 por puesto, para que
    # la mejora sea lo que aporta el fichaje y no el once entero.
    antes = solve_best_xi([*elegibles, *_huecos_a_cero()])
    con = solve_best_xi([*elegibles, *_huecos_a_cero(), fantasma])
    if not antes["ok"] or not con["ok"]:
        return 0.0
    return round(max(0.0, float(con["puntos"]) - float(antes["puntos"])), 4)


def _huecos_a_cero() -> list[dict[str, Any]]:
    return [
        {"player_id": f"hueco:{posicion}", "position": posicion, "jornada": 0.0}
        for posicion in POSITIONS
    ]


def puntos_referencia_mejoras(elegibles: list[dict[str, Any]], actual: dict[str, Any]) -> float:
    """Base contra la que se mide cada ``mejora_neta``.

    Con once legal es el once actual. Sin él (10 jugadores) es el mejor once con
    los huecos a 0 puntos, no 0: si no, «once del plan − base» vale el once
    entero y no la suma de lo que aporta cada fichaje.
    """
    if actual.get("ok"):
        return float(actual["puntos"])
    con_huecos = solve_best_xi([*elegibles, *_huecos_a_cero()])
    return float(con_huecos["puntos"]) if con_huecos["ok"] else 0.0


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
    """Lesionado o sancionado: no cuenta como titular sano y hay que reemplazarlo.

    Una sanción que solo cubre la próxima jornada no es baja: vuelve en J2.
    """
    if row.get("sancion_temporal") is True:
        return False
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
    parche = valor < PARCHE_SUPERVIVENCIA_EUR and row.get("supervivencia") is True
    if ratio > RATIO_CLAUSULA_MAX and not parche:
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


def _cuenta_en_esqueleto(row: dict[str, Any]) -> bool:
    return row.get("elegible") is not False and row.get("position") in POSITIONS and isinstance(row.get("player_id"), str)


def conserva_esqueleto(plantilla: list[dict[str, Any]], ventas_ids: set[str]) -> bool:
    """Tras esas ventas, y sin contar ningún fichaje, sigue habiendo once legal.

    El mínimo de línea (1 portero, 3 defensas, 3 medios, 1 delantero) es el
    suelo. Además tiene que caber una formación real: si vender a un defensa
    deja el once pendiente de ganar una puja ciega, el plan no vale.
    """
    quedan = [row for row in plantilla if _cuenta_en_esqueleto(row) and row["player_id"] not in ventas_ids]
    conteo = {position: 0 for position in POSITIONS}
    for row in quedan:
        conteo[row["position"]] += 1
    if any(conteo[position] < minimo for position, minimo in ESQUELETO_MINIMO.items()):
        return False
    pool = [
        {
            "player_id": row["player_id"],
            "position": row["position"],
            "jornada": float(row.get("jornada") or 0.0),
            "p_titular": row.get("p_titular"),
        }
        for row in quedan
    ]
    return solve_best_xi(pool)["ok"]


def _bloquear_ventas_sin_esqueleto(
    problem: pulp.LpProblem,
    plantilla: list[dict[str, Any]],
    vende: dict[str, pulp.LpVariable],
    prefix: str,
    *,
    solo_sin_once: bool = False,
) -> None:
    """Ningún plan puede vender el último cuerpo de una línea ni bajar de 11.

    Con once legal hoy, las ventas tienen que dejarlo legal sin contar pujas.
    Sin él, no se vende. Vender cero siempre es factible: la restricción recorta
    ventas, no obliga a fichar.
    """
    cuerpos = [row for row in plantilla if _cuenta_en_esqueleto(row)]
    if not conserva_esqueleto(cuerpos, set()):
        # Hoy no hay once legal (por ejemplo, 10 jugadores): cualquier venta lo
        # empeora. No se vende nada hasta tener al sustituto en la plantilla.
        if vende:
            problem += pulp.lpSum(vende.values()) == 0
        return
    if solo_sin_once:
        return
    for position, minimo in ESQUELETO_MINIMO.items():
        ids = [row["player_id"] for row in cuerpos if row["position"] == position and row["player_id"] in vende]
        fijos = sum(1 for row in cuerpos if row["position"] == position and row["player_id"] not in vende)
        if ids:
            problem += pulp.lpSum(vende[player_id] for player_id in ids) <= max(0, fijos + len(ids) - minimo)
    cubre = {
        name: pulp.LpVariable(f"{prefix}_sk{name.replace('-', '_')}", cat=pulp.LpBinary) for name in FORMATIONS
    }
    problem += pulp.lpSum(cubre.values()) >= 1
    for name, slots in FORMATIONS.items():
        for position, need in slots.items():
            ids = [row["player_id"] for row in cuerpos if row["position"] == position and row["player_id"] in vende]
            fijos = sum(1 for row in cuerpos if row["position"] == position and row["player_id"] not in vende)
            if not ids:
                if fijos < need:
                    problem += cubre[name] == 0
                continue
            problem += pulp.lpSum(vende[player_id] for player_id in ids) <= (fijos + len(ids) - need) + need * (1 - cubre[name])


def titulares_consolidados(
    plantilla: list[dict[str, Any]],
    xi_ids: set[str],
    excluidos: set[str],
) -> set[str]:
    """Titulares del once actual, sanos y con ``p_titular >= P_TITULAR_CONSOLIDADO``."""
    salida: set[str] = set()
    for row in plantilla:
        player_id = row.get("player_id")
        if player_id not in xi_ids or player_id in excluidos:
            continue
        p = _prob_titular(row)
        if p is not None and p >= P_TITULAR_CONSOLIDADO:
            salida.add(player_id)
    return salida


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
    asignacion: dict[str, str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Cada venta condicional con la puja que la dispara.

    El reparto sale del solver (``asignacion``: venta → puja) y no del puesto.
    Cada puja queda cubierta por su parte de la caja de hoy más las ventas que
    se le atan, así que cualquier combinación de pujas ganadas deja el saldo
    en cero o por encima.
    """
    por_id = {row["player_id"]: row for row in pujas}
    return [
        (venta, por_id[asignacion[venta["player_id"]]])
        for venta in ventas
        if asignacion.get(venta["player_id"]) in por_id
    ]


def _partir_ventas(
    *,
    saldo: int,
    ventas: list[dict[str, Any]],
    pujas: list[dict[str, Any]],
    asignacion: dict[str, str],
    clausulas_hechas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]], set[str], set[str]]:
    """Separa «vender hoy» de «vender solo si ganas la puja».

    Lo decide el solver: una venta atada a una puja espera a ganarla; el resto
    se hace hoy. Aquí solo se etiqueta por qué va hoy (deuda o clausulazo).
    """
    pares = _emparejar_ventas(ventas, pujas, asignacion)
    condicionales = {venta["player_id"] for venta, _puja in pares}
    hoy = [row for row in ventas if row["player_id"] not in condicionales]
    por_deuda: set[str] = set()
    por_clausula: set[str] = set()
    caja = saldo
    if saldo < 0:
        for row in sorted(hoy, key=lambda item: int(item.get("venta_eur") or 0)):
            if caja >= 0:
                break
            por_deuda.add(row["player_id"])
            caja += int(row.get("venta_eur") or 0)
    gasto_clausulas = sum(int(row.get("euros") or 0) for row in clausulas_hechas)
    if clausulas_hechas and caja < gasto_clausulas:
        faltan = gasto_clausulas - caja
        for row in sorted(hoy, key=lambda item: -int(item.get("venta_eur") or 0)):
            if faltan <= 0:
                break
            if row["player_id"] in por_deuda:
                continue
            por_clausula.add(row["player_id"])
            faltan -= int(row.get("venta_eur") or 0)
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
        fantasma = {
            "player_id": f"nuevo:{ficha['row'].get('player_id')}",
            "position": ficha["row"].get("position"),
            "jornada": float(ficha["row"].get("jornada") or 0.0),
        }
        if solve_best_xi([*elegibles, fantasma])["ok"]:
            opciones.append(int(ficha["euros"]))
    return min(opciones) if opciones else 0


def build_plan_fichajes(**kwargs: Any) -> dict[str, Any]:
    """Plan del once más, aparte, el trading desk con lo que sobra.

    Los chollos de banquillo no entran en el solver del once: se recogen y los
    reparte ``build_trading_desk`` con la caja sobrante y parte de la deuda.
    """
    trading: list[dict[str, Any]] = []
    plan = _plan_once(**kwargs, trading_out=trading)
    saldo = plan.get("saldo_al_final")
    owned = kwargs.get("owned") or []
    valor_equipo = sum(_valor_jugador(row) for row in owned if isinstance(row, dict))
    sobrante = saldo if isinstance(saldo, int) and not isinstance(saldo, bool) else None
    credito: int | None = None
    cobertura = plan.get("cobertura_pujas")
    if isinstance(cobertura, dict):
        # El trading puja a la vez que el once: solo usa la caja que ninguna
        # puja del once tiene reservada y el crédito que esas pujas no gastan.
        reservada = sum(int(item["caja"]) for item in cobertura["pujas"])
        libre = int(cobertura["caja_al_pujar"]) - reservada
        sobrante = libre if sobrante is None else min(sobrante, libre)
        if isinstance(cobertura.get("tope_deuda"), int):
            credito = max(0, int(cobertura["tope_deuda"]) - int(cobertura["deuda_al_pujar"]))
    plan["trading"] = build_trading_desk(
        trading,
        saldo_sobrante=sobrante,
        valor_equipo=valor_equipo,
        dias_para_jornada=dias_al_cierre(kwargs.get("dias_para_jornada")),
        credito_disponible=credito,
    )
    return plan


def _plan_once(
    *,
    cash: int | None,
    owned: list[dict[str, Any]],
    mercado: list[dict[str, Any]],
    clausulas: list[dict[str, Any]],
    ratio: float,
    dias_para_jornada: float | None,
    baseline_puntos: float,
    preparar_escaparate: bool = True,
    objetivos_previos: list[str] | set[str] | None = None,
    trading_out: list[dict[str, Any]] | None = None,
    permitir_condicionales: bool = True,
    bonus_posicional: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Maximiza ``xP - peaje × drenaje neto``. No envía órdenes.

    ``objetivos_previos`` son los fichajes que recomendó el plan anterior. Si
    siguen disponibles, el solver los premia con ``CONTINUIDAD_XP`` y el plan
    solo exige ``MEJORA_MINIMA`` para mantenerlos. Un plan con objetivos
    nuevos tiene que mejorar el once en ``UMBRAL_CAMBIO_XP``.

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
    previos = {str(item) for item in objetivos_previos or [] if item}
    ventana = meta["modo_liquidez"] == "VENTANA"
    all_in = meta["modo_liquidez"] == "ALL-IN"
    # Parón: lejos del cierre el saldo negativo no cuesta nada hasta el saque.
    # El plan prudente es «solo caja y ventas de hoy»: tampoco usa el crédito del parón.
    paron_credito = ventana and dias is not None and dias > DIAS_ESCAPARATE and permitir_condicionales
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
        vacio = _vacio(None, ratio, baseline_puntos, meta)
        vacio["estado_calculo"] = "sin_caja"
        vacio["estado_detalle"] = "No se pudo leer tu saldo: el plan no puede decidir compras ni ventas."
        return vacio

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
            objetivos_previos=previos,
            permitir_condicionales=permitir_condicionales,
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
    referencia_mejoras = puntos_referencia_mejoras(elegibles, actual)
    xi_ids = set(actual["player_ids"]) if actual["ok"] else set()
    bajas = {row["player_id"] for row in plantilla if _es_baja(row)}
    huecos = set(actual.get("huecos_obligatorios") or [])

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
        if (
            paron_credito
            and origen == "bid"
            and pct is not None
            and pct >= CREDITO_PARON_PCT
            and mejora < UMBRAL_HOLD_XP
        ):
            # En el parón una subida alta sin mejora del once es pura especulación:
            # la reparte el trading desk, que sí sabe cuánto crédito le queda.
            especulativo = True
        if especulativo:
            # Fuera del solver del once: lo reparte el trading desk.
            if ventana and trading_out is not None:
                candidato = {
                    "player_id": player_id,
                    "nombre": _nombre(row),
                    "origen": origen,
                    "euros": euros,
                    "valor": _valor_jugador(row) or euros,
                    "pct": pct,
                }
                if row.get("af_alerta_bajada") is True:
                    candidato["af_alerta_bajada"] = True
                trading_out.append(candidato)
            return
        p_compra = _prob_titular(row)
        if p_compra is not None and p_compra < P_TITULAR_COMPRA:
            # No es titular probable: no se recomienda para el once, aunque el
            # solver le atribuya puntos.
            return
        if (_jornada(row) or 0.0) <= 0.0:
            return
        ficha = {
            "row": row,
            "euros": euros,
            "mejora": mejora,
            "pct": pct,
            "impulso": impulso,
            "origen": origen,
            "prima": prima_quemada_mercado(euros, _valor_mercado(row), pct) if origen == "bid" else 0.0,
            "credito_paron": paron_credito and merece_credito_paron(
                origen=origen,
                pct=pct,
                mejora=mejora,
                cambio_hoy_pct=_cambio_hoy_pct(row),
            ),
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

    # Un titular con p <= 30 % es hueco obligatorio: no gasta el cupo de sanos.
    sanos = [
        player_id
        for player_id in vende
        if player_id in xi_ids and player_id not in bajas and player_id not in huecos
    ]
    if sanos:
        # Tope de rotación: un lesionado no gasta plaza de este cupo.
        problem += pulp.lpSum(vende[player_id] for player_id in sanos) <= MAX_VENTAS_TITULARES_SANOS
    # Regla dura, en todos los planes: sin once legal hoy (10 jugadores, una línea
    # vacía) no se vende a nadie hasta tener al sustituto en la plantilla; una
    # puja pendiente o un clausulazo (que además cierra 24 h antes de la jornada)
    # no cuentan. Con once legal, el plan prudente exige que las ventas de hoy lo
    # dejen legal sin ninguna puja.
    _bloquear_ventas_sin_esqueleto(problem, plantilla, vende, prefix, solo_sin_once=permitir_condicionales)

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
        if ficha["impulso"] == "CHOLLO":
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
    # Crédito del parón: solo cubre pujas que lo merecen y nunca pasa del 20 % del
    # valor del equipo. Sin el valor de toda la plantilla no se conoce el tope y
    # no se usa. El resto del gasto (cláusulas, pujas normales, busca) sigue
    # saliendo de caja.
    valores_propios = {row["player_id"]: _valor_jugador(row) for row in plantilla}
    tope_deuda_conocido = bool(plantilla) and all(valor > 0 for valor in valores_propios.values())
    pujas_credito = [pid for pid in puja if ficha_compra[f"bid:{pid}"]["credito_paron"]]
    credito_usado: Any = 0
    if paron_credito and tope_deuda_conocido and pujas_credito:
        credito_usado = pulp.LpVariable(f"{prefix}_credito", lowBound=0)
        problem += credito_usado <= pulp.lpSum(_euros_de(f"bid:{pid}") * puja[pid] for pid in pujas_credito)
    problem += saldo + ingresos - gastos_puja - gastos_clausula - gastos_busca + credito_usado >= 0

    # Cobertura de cada puja. Las subastas se resuelven a la vez y puedes ganar
    # cualquier combinación: cada puja tiene su parte de la caja de hoy más las
    # ventas que se le atan (y que solo se hacen si se gana). La venta que no se
    # ata a ninguna puja se hace hoy y suma a esa caja.
    def _vender_ya(player_id: str) -> bool:
        row = next(item for item in plantilla if item["player_id"] == player_id)
        pct = _leer_pct(row)
        bajando = pct is not None and pct < 0
        return _es_suplente(player_id, plantilla, xi_ids) and (
            bajando or _tiene_oferta(row) or player_id in bajas
        )

    venta_de = {
        row["player_id"]: int(row["venta_eur"])
        for row in plantilla
        if row["player_id"] in vende and isinstance(row.get("venta_eur"), int)
    }
    asigna: dict[tuple[str, str], pulp.LpVariable] = {}
    for s_index, vendido in enumerate(vende):
        for b_index, pujado in enumerate(puja):
            variable = pulp.LpVariable(f"{prefix}_a{s_index}_{b_index}", cat=pulp.LpBinary)
            asigna[(vendido, pujado)] = variable
            problem += variable <= puja[pujado]
            if not permitir_condicionales:
                # Modo prudente: solo caja y ventas de hoy, nada que dependa de ganar.
                problem += variable == 0
        problem += pulp.lpSum(asigna[(vendido, pujado)] for pujado in puja) <= vende[vendido]
    caja_puja = {pujado: pulp.LpVariable(f"{prefix}_cp{index}", lowBound=0) for index, pujado in enumerate(puja)}
    for pujado, variable in puja.items():
        problem += _euros_de(f"bid:{pujado}") * variable <= caja_puja[pujado] + pulp.lpSum(
            venta_de.get(vendido, 0) * asigna[(vendido, pujado)] for vendido in vende
        )

    def _hoy(vendido: str) -> Any:
        return vende[vendido] - pulp.lpSum(asigna[(vendido, pujado)] for pujado in puja)

    ingresos_hoy = pulp.lpSum(venta_de.get(vendido, 0) * _hoy(vendido) for vendido in vende)
    caja_hoy = saldo + ingresos_hoy - gastos_clausula
    problem += pulp.lpSum(caja_puja.values()) <= caja_hoy - gastos_busca + credito_usado
    # Perder todas las pujas, o ganar solo las que se pagan con varias ventas,
    # no puede dejar menos de 11 jugadores.
    exceso = {pujado: pulp.LpVariable(f"{prefix}_e{index}", lowBound=0) for index, pujado in enumerate(puja)}
    for pujado, variable in exceso.items():
        problem += variable >= pulp.lpSum(asigna[(vendido, pujado)] for vendido in vende) - puja[pujado]
    if vende:
        problem += pulp.lpSum(_hoy(vendido) for vendido in vende) + pulp.lpSum(exceso.values()) <= max(
            0, len(plantilla) - XI_SIZE
        ) + pulp.lpSum(list(clausula.values()) or [0])
    # LaLiga no acepta pujas que te endeuden más del 20 % del valor del equipo.
    # Solo se aplica si se conoce el valor de toda la plantilla.
    if tope_deuda_conocido and puja:
        valor_equipo_hoy = (
            sum(valores_propios.values())
            - pulp.lpSum(valores_propios[vendido] * _hoy(vendido) for vendido in vende)
            + pulp.lpSum((_valor_mercado(row) or 0) * clausula[row["player_id"]] for row in raids if row["player_id"] in clausula)
        )
        problem += gastos_puja + gastos_busca - caja_hoy <= DEUDA_PCT_EQUIPO * valor_equipo_hoy
    # Desempate: el suplente que baja o ya tiene oferta se vende hoy; el resto,
    # mejor solo si se gana la puja.
    preferencia_condicional = pulp.lpSum(
        (-1e-6 if _vender_ya(vendido) else 1e-6) * variable for (vendido, _pujado), variable in asigna.items()
    )

    def _exento_peaje(clave: str) -> bool:
        ficha = ficha_compra[clave]
        return ficha["impulso"] in {"MUST-BUY", "CHOLLO"} or ficha["credito_paron"]

    def _es_prioritario(clave: str) -> bool:
        ficha = ficha_compra[clave]
        return ficha["impulso"] in {"MUST-BUY", "CHOLLO"}

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

    # Dos onces: el de la próxima jornada (``en_once``) y el de J2-J4
    # (``en_futuro``), que sale de la plantilla que queda tras el plan. Un
    # sancionado que no juega la próxima no ocupa sitio en el primero, pero
    # sigue valiendo en el segundo y no se vende por un solo partido.
    # Busca no tiene calendario: cuenta como BUSCA_PUNTOS en cada jornada.
    en_futuro: dict[str, pulp.LpVariable] = {}
    for index, row in enumerate(plantilla):
        player_id = row["player_id"]
        variable = pulp.LpVariable(f"{prefix}_fo{index}", cat=pulp.LpBinary)
        en_futuro[f"own:{player_id}"] = variable
        if row.get("position") not in POSITIONS:
            problem += variable == 0
        elif player_id in vende:
            problem += variable + vende[player_id] <= 1
    for origen, filas, compra_de in (("bid", compras, puja), ("clause", raids, clausula)):
        for index, row in enumerate(filas):
            if row["player_id"] not in compra_de:
                continue
            variable = pulp.LpVariable(f"{prefix}_f{origen[0]}{index}", cat=pulp.LpBinary)
            en_futuro[f"{origen}:{row['player_id']}"] = variable
            problem += variable <= compra_de[row["player_id"]]
    busca_futuro = {
        position: pulp.LpVariable(f"{prefix}_fb{position}", cat=pulp.LpBinary) for position in POSITIONS
    }
    for position in POSITIONS:
        problem += busca_futuro[position] <= busca[position]
    formacion_futuro = {
        name: pulp.LpVariable(f"{prefix}_ff{name.replace('-', '_')}", cat=pulp.LpBinary) for name in FORMATIONS
    }
    problem += pulp.lpSum(formacion_futuro.values()) == 1
    problem += pulp.lpSum(list(en_futuro.values()) + list(busca_futuro.values())) == XI_SIZE
    for position in POSITIONS:
        ocupantes_futuro = [
            en_futuro[f"{origen}:{row['player_id']}"]
            for origen, filas in (("own", plantilla), ("bid", compras), ("clause", raids))
            for row in filas
            if row.get("position") == position and f"{origen}:{row['player_id']}" in en_futuro
        ] + [busca_futuro[position]]
        problem += pulp.lpSum(ocupantes_futuro) == pulp.lpSum(
            FORMATIONS[name][position] * formacion_futuro[name] for name in FORMATIONS
        )

    def _filas_con(variables: dict[str, pulp.LpVariable]) -> list[tuple[dict[str, Any], pulp.LpVariable]]:
        return [
            (row, variables[f"{origen}:{row['player_id']}"])
            for origen, filas in (("own", plantilla), ("bid", compras), ("clause", raids))
            for row in filas
            if f"{origen}:{row['player_id']}" in variables
        ]

    puntos_j1 = pulp.lpSum(
        (float(row.get("jornada") or 0.0) - penalizacion_varianza(row)) * variable
        for row, variable in _filas_con(en_once)
    )
    puntos_j1 += pulp.lpSum(BUSCA_PUNTOS * busca[position] for position in POSITIONS)
    puntos_futuro = pulp.lpSum(_futuro_efectivo(row) * variable for row, variable in _filas_con(en_futuro))
    puntos_futuro += pulp.lpSum(3.0 * BUSCA_PUNTOS * busca_futuro[position] for position in POSITIONS)
    puntos = _horizonte(puntos_j1, puntos_futuro)
    # Brecha posicional: un fichaje que juega en el puesto donde más puntos faltan
    # frente al líder suma un extra pequeño de xP. Solo desempata entre fichajes parecidos.
    extra_posicional = {
        str(position): float(valor)
        for position, valor in (bonus_posicional or {}).items()
        if isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor > 0
    }
    prioridad_posicional = pulp.lpSum(
        extra_posicional.get(str(row.get("position")), 0.0) * en_once[f"{origen}:{row['player_id']}"]
        for origen, filas in (("bid", compras), ("clause", raids))
        for row in filas
        if f"{origen}:{row['player_id']}" in en_once
    )
    bonus = pulp.lpSum(
        [
            *(
                max(ficha_compra[f"bid:{pid}"].get("pct") or 0.0, 0.0) * 1e-5 * variable
                for pid, variable in puja.items()
                if ficha_compra[f"bid:{pid}"]["impulso"] == "CHOLLO"
            ),
            *(
                max(ficha_compra[f"clause:{pid}"].get("pct") or 0.0, 0.0) * 1e-5 * variable
                for pid, variable in clausula.items()
                if ficha_compra[f"clause:{pid}"]["impulso"] == "CHOLLO"
            ),
        ]
    )
    def _psi(clave: str) -> float:
        # El chollo no paga peaje, ni la puja que va con el crédito del parón: ese
        # dinero no sale de la caja, es deuda sin coste hasta el saque. El resto lo
        # paga en proporción a lo poco que mejora el once.
        ficha = ficha_compra[clave]
        if ficha["impulso"] == "CHOLLO" or ficha["credito_paron"]:
            return 0.0
        return factor_peaje(ficha["mejora"]) * escasez_de_caja(saldo, ficha["euros"])

    gastos_peaje = pulp.lpSum(
        [
            *(_psi(f"bid:{pid}") * _euros_de(f"bid:{pid}") * variable for pid, variable in puja.items()),
            *(_psi(f"clause:{pid}") * _euros_de(f"clause:{pid}") * variable for pid, variable in clausula.items()),
            *(coste_busca * busca[position] for position in POSITIONS),
        ]
    )
    revalorizacion = pulp.lpSum(
        [
            *(
                _psi(f"bid:{pid}") * _revalorizacion_hasta_viernes(ficha_compra[f"bid:{pid}"]["row"], dias or 0.0) * variable
                for pid, variable in puja.items()
            ),
            *(
                _psi(f"clause:{pid}")
                * _revalorizacion_hasta_viernes(ficha_compra[f"clause:{pid}"]["row"], dias or 0.0)
                * variable
                for pid, variable in clausula.items()
            ),
        ]
    )
    # drenaje_neto = max(0, compras ponderadas por psi - ventas - subida hasta el viernes).
    # Una rotación que se paga sola, o un +8 % semanal, no pagan el precio bruto.
    if penalizacion > 0:
        drenaje = pulp.LpVariable(f"{prefix}_drenaje", lowBound=0)
        problem += drenaje >= gastos_peaje - ingresos - revalorizacion
        peaje = (penalizacion / _MILLON) * drenaje
    else:
        peaje = 0
    # La prima quemada es dinero que no vuelve. Se resta aunque el peaje de liquidez esté apagado.
    # En el mercado es el mismo castigo que en un clausulazo: el sobreprecio que
    # la subida a 7 días no cubre. Un jugador que va a bajar lo agranda.
    castigo_patrimonio = pulp.lpSum(
        [
            *(
                (primas.get(player_id, 0.0) / _MILLON) * PENALIZACION_PRIMA_POR_MILLON * variable
                for player_id, variable in clausula.items()
            ),
            *(
                (float(ficha_compra[f"bid:{player_id}"].get("prima") or 0.0) / _MILLON)
                * PENALIZACION_PRIMA_POR_MILLON
                * variable
                for player_id, variable in puja.items()
            ),
        ]
    )
    bonus_baja = pulp.lpSum(BONUS_REEMPLAZO_BAJA * vende[player_id] for player_id in bajas | huecos if player_id in vende)
    consolidados = titulares_consolidados(plantilla, xi_ids, bajas | huecos)
    freno_venta = pulp.lpSum(
        UMBRAL_VENTA_TITULAR_XP * vende[player_id] for player_id in consolidados if player_id in vende
    )
    continuidad = pulp.lpSum(
        [
            *(CONTINUIDAD_XP * variable for pid, variable in puja.items() if pid in previos),
            *(CONTINUIDAD_XP * variable for pid, variable in clausula.items() if pid in previos),
        ]
    )
    problem += (
        puntos
        + prioridad_posicional
        + bonus
        + bonus_baja
        + continuidad
        - peaje
        - castigo_patrimonio
        - freno_venta
        + preferencia_condicional
        - 0.0001 * pulp.lpSum(list(vende.values()) or [0])
        - 1e-12 * (gastos_puja + gastos_clausula + gastos_busca + ingresos)
    )

    def _escaparate(vendidos: set[str]) -> list[dict[str, Any]]:
        if not ventana:
            return []
        if dias is not None and dias > DIAS_ESCAPARATE:
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
    estado_solver = pulp.LpStatus.get(status, "")
    if estado_solver != "Optimal":
        vacio = _vacio(saldo, ratio, baseline_puntos, meta)
        # No es «nada que hacer»: el solver no dio un plan válido (tiempo agotado o sin solución).
        vacio["estado_calculo"] = "fallo_solver"
        vacio["estado_detalle"] = (
            f"El optimizador no encontró un plan válido (estado: {estado_solver or 'desconocido'}). "
            "Pulsa Actualizar; si se repite, revisa el registro del servidor."
        )
        vacio["en_radar"] = radar
        vacio["acciones"] = _escaparate(set())
        vacio["huecos_obligatorios"] = _publicar_huecos(plantilla, huecos)
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
    asignacion = {vendido: pujado for (vendido, pujado), variable in asigna.items() if _on(variable)}
    ventas_hoy, pares, por_deuda, por_clausula = _partir_ventas(
        saldo=saldo,
        ventas=ventas_sel,
        pujas=pujas_sel,
        asignacion=asignacion,
        clausulas_hechas=clausulas_sel,
    )
    # El viernes ya no hay «mañana» antes del saque: la venta que financia el plan
    # se acepta hoy. Solo si, perdiendo todas las pujas, quedan 11 jugadores.
    quedan_si_pierdes = len(plantilla) - len(ventas_sel) + len(clausulas_sel)
    if dias is not None and dias < 1.0 and pares and quedan_si_pierdes >= min(XI_SIZE, len(plantilla)):
        ventas_hoy.extend(venta for venta, _puja in pares)
        pares = []
    caja_al_pujar = int(
        saldo
        + sum(int(row["venta_eur"]) for row in ventas_hoy)
        - sum(int(ficha_compra[f"clause:{row['player_id']}"]["euros"]) for row in clausulas_sel)
    )
    total_pujas = sum(int(ficha_compra[f"bid:{row['player_id']}"]["euros"]) for row in pujas_sel)
    # Lo que el plan gasta por encima de la caja y de todas sus ventas: crédito del parón.
    gasto_total = (
        total_pujas
        + sum(int(ficha_compra[f"clause:{row['player_id']}"]["euros"]) for row in clausulas_sel)
        + sum(coste_busca for variable in busca.values() if _on(variable))
    )
    credito_paron_eur = (
        max(0, gasto_total - saldo - sum(int(row["venta_eur"]) for row in ventas_sel)) if paron_credito else 0
    )
    ventas_de_puja: dict[str, list[dict[str, Any]]] = {}
    for venta, puja_row in pares:
        ventas_de_puja.setdefault(puja_row["player_id"], []).append(
            {"player_id": venta["player_id"], "euros": int(venta["venta_eur"])}
        )
    cobertura_pujas = {
        "caja_al_pujar": caja_al_pujar,
        "deuda_al_pujar": max(0, total_pujas - caja_al_pujar),
        "tope_deuda": (
            int(
                DEUDA_PCT_EQUIPO
                * (
                    sum(valores_propios.values())
                    - sum(valores_propios[row["player_id"]] for row in ventas_hoy)
                    + sum(_valor_mercado(row) or 0 for row in clausulas_sel)
                )
            )
            if tope_deuda_conocido
            else None
        ),
        "pujas": [
            {
                "player_id": row["player_id"],
                "euros": int(ficha_compra[f"bid:{row['player_id']}"]["euros"]),
                # Lo que la puja necesita de la caja de hoy: su precio menos sus ventas.
                "caja": max(
                    0,
                    int(ficha_compra[f"bid:{row['player_id']}"]["euros"])
                    - sum(item["euros"] for item in ventas_de_puja.get(row["player_id"], [])),
                ),
                "ventas": ventas_de_puja.get(row["player_id"], []),
            }
            for row in pujas_sel
        ],
    }
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
        if credito_paron_eur > 0 and ficha["credito_paron"]:
            return "hoy", _texto_credito_paron(ficha, dias or 0.0, credito_paron_eur)
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
        prima = float(ficha.get("prima") or 0.0)
        if prima > 0:
            detalle += f" Prima quemada de {prima / _MILLON:.2f} M€: ese sobreprecio no vuelve al venderlo."
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
        if credito_paron_eur > 0 and ficha["credito_paron"]:
            acciones[-1]["financia_con_credito"] = True
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
    # La misma mejora, medida en la media ponderada de las cuatro jornadas.
    horizonte_once = float(pulp.value(puntos) or 0.0)
    horizonte_base = _horizonte(base_puntos, _mejor_once_futuro(plantilla))
    mejora_horizonte = round(horizonte_once - horizonte_base, 2)
    hay_urgente = any(accion.get("impulso") in {"MUST-BUY", "CHOLLO"} for accion in acciones)
    vende_baja = any(row["player_id"] in bajas for row in ventas_sel)
    cubre_deuda = saldo < 0 and bool(ventas_hoy)
    fichados = [row["player_id"] for row in pujas_sel + clausulas_sel]
    for accion in acciones:
        if accion.get("tipo") in {"PUJA", "CLAUSULAZO"}:
            accion["sigue_plan"] = accion.get("player_id") in previos
    # Mantener lo de ayer es barato; cambiar de objetivo tiene que merecer la pena.
    solo_continua = bool(fichados) and all(player_id in previos for player_id in fichados)
    umbral = MEJORA_MINIMA if solo_continua else UMBRAL_CAMBIO_XP
    if mejora_horizonte < umbral and not hay_urgente and not vende_baja and not cubre_deuda:
        vacio = _vacio(saldo, ratio, baseline_puntos, meta)
        vacio["en_radar"] = radar
        vacio["acciones"] = _escaparate(set())
        vacio["huecos_obligatorios"] = _publicar_huecos(plantilla, huecos)
        return vacio
    presupuesto = _presupuesto(
        saldo=saldo,
        ventas_hoy=ventas_hoy,
        pares=pares,
        gasto_pujas=total_pujas,
        gasto_clausulas=sum(int(ficha_compra[f"clause:{row['player_id']}"]["euros"]) for row in clausulas_sel),
        tope_deuda=cobertura_pujas["tope_deuda"],
        credito_paron=credito_paron_eur,
    )
    # Fichajes fuertes que no entran: el plan los enseña aparte, ordenados por
    # mejora por millón, con lo que falta para pagarlos.
    elegidos = {f"bid:{row['player_id']}" for row in pujas_sel} | {f"clause:{row['player_id']}" for row in clausulas_sel}
    alternativas = []
    for clave, ficha in ficha_compra.items():
        if clave in elegidos or ficha["impulso"] != "MUST-BUY":
            continue
        euros = int(ficha["euros"])
        tipo = "CLAUSULAZO" if ficha["origen"] == "clause" else "PUJA"
        disponible = presupuesto["disponible_clausulas"] - presupuesto["gasto_clausulas"] if tipo == "CLAUSULAZO" else presupuesto["holgura"]
        accion = _accion(
            tipo,
            "alternativa",
            player_id=ficha["row"]["player_id"],
            nombre=_nombre(ficha["row"]),
            posicion=ficha["row"].get("position"),
            jornada=_jornada(ficha["row"]),
            euros=euros,
            impulso=ficha["impulso"],
            mejora_neta=ficha["mejora"],
            prevision_7d_pct=ficha["pct"],
            detalle=f"Mejora el once +{float(ficha['mejora']):.1f} xP, pero no cabe en la caja de hoy junto al resto del plan.",
        )
        accion["roi_xp_por_millon"] = round(float(ficha["mejora"]) / (euros / _MILLON), 3)
        accion["falta_eur"] = max(0, euros - int(disponible))
        alternativas.append(accion)
    alternativas.sort(key=lambda accion: -accion["roi_xp_por_millon"])
    alternativas = alternativas[:MAX_ALTERNATIVAS]
    if not presupuesto["cumple"]:
        # No debería pasar (el solver lo impide), pero un plan impagable no se publica.
        vacio = _vacio(saldo, ratio, baseline_puntos, meta)
        vacio["estado_calculo"] = "impagable"
        vacio["estado_detalle"] = "El plan calculado no se podía pagar con tu caja y tu crédito: no se publica."
        vacio["en_radar"] = radar
        vacio["acciones"] = _escaparate(set())
        vacio["presupuesto"] = presupuesto
        vacio["alternativas_liquidez"] = alternativas
        return vacio
    saldo_final = int(saldo + ingreso - gasto)
    # El encabezado es el once de HOY: plantilla menos ventas ya aceptadas, más
    # los fichajes con momento «hoy». «Después» y las alternativas no suman.
    hoy = _xi_ejecutable_hoy(plantilla, compras, raids, acciones)
    if hoy["ok"]:
        puntos_once = hoy["puntos"]
        once = hoy["once"]
    else:
        puntos_once = 0.0
        once = []
    mejora = round(puntos_once - float(baseline_puntos), 2)
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
        # Base de las ``mejora_neta`` de cada acción (con 10 jugadores, el once con
        # huecos a 0): «puntos_once − esto» es comparable con su suma.
        "puntos_once_referencia": round(referencia_mejoras, 2),
        "huecos_obligatorios": _publicar_huecos(plantilla, huecos),
        "ratio_mercado": round(ratio, 2) if ratio else None,
        "once": once,
        "en_radar": radar,
        "mejora_horizonte": mejora_horizonte,
        "cobertura_pujas": cobertura_pujas,
        "presupuesto": presupuesto,
        "deuda_paron": _deuda_paron(
            credito_paron_eur,
            dias,
            plantilla,
            {row["player_id"] for row in ventas_sel},
            {row["player_id"] for row in plantilla if _on(en_once.get(f"own:{row['player_id']}"))},
            sum(
                _revalorizacion_hasta_viernes(ficha_compra[f"bid:{row['player_id']}"]["row"], dias_de_prevision(dias) or 0.0)
                for row in pujas_sel
                if ficha_compra[f"bid:{row['player_id']}"]["credito_paron"]
            ),
        ),
        "alternativas_liquidez": alternativas,
        "objetivos_previos": sorted(previos),
        "umbral_cambio_xp": umbral,
        **meta,
    }


def _deuda_paron(
    credito: int,
    dias: float | None,
    plantilla: list[dict[str, Any]],
    vendidos: set[str],
    en_once: set[str],
    revalorizacion: float = 0.0,
) -> dict[str, Any] | None:
    """Deuda que deja el plan en el parón y con qué se puede saldar sin tocar el once resultante."""
    if credito <= 0 or dias is None:
        return None
    vendible = sum(
        int(row["venta_eur"])
        for row in plantilla
        if row["player_id"] not in vendidos
        and row["player_id"] not in en_once
        and isinstance(row.get("venta_eur"), int)
        and not isinstance(row.get("venta_eur"), bool)
    )
    cubierta = vendible >= credito
    aviso = None
    if not cubierta:
        aviso = (
            f"El banquillo (con los desplazados por los fichajes) cubre {vendible / _MILLON:.1f} M€ de "
            f"{credito / _MILLON:.1f} M€. El resto tendría que salir de la subida de los fichajes "
            f"({revalorizacion / _MILLON:.1f} M€ previstos) o de un titular."
        )
    return {
        "eur": int(credito),
        "saldar_antes_de_dias": round(dias, 2),
        "decidir_ventas_en_dias": round(max(0.0, dias - DIAS_DECIDIR_VENTAS), 2),
        "vendible_sin_tocar_el_once": int(vendible),
        "revalorizacion_prevista": int(revalorizacion),
        "cubierta_con_banquillo": cubierta,
        "aviso": aviso,
    }


def _publicar_huecos(plantilla: list[dict[str, Any]], huecos: set[str]) -> list[dict[str, Any]]:
    """Titulares con ``p_titular <= 30 %``: el solver ya los trata como hueco."""
    return [
        {
            "player_id": row["player_id"],
            "nombre": _nombre(row),
            "posicion": row.get("position"),
            "p_titular": _prob_titular(row),
            "etiqueta": HUECO_OBLIGATORIO,
        }
        for row in plantilla
        if row["player_id"] in huecos
    ]


def _xi_ejecutable_hoy(
    plantilla: list[dict[str, Any]],
    compras: list[dict[str, Any]],
    raids: list[dict[str, Any]],
    acciones: list[dict[str, Any]],
) -> dict[str, Any]:
    """``solve_best_xi`` con lo que es tuyo al cerrar el día, sin «Después».

    Una venta condicional sigue en la plantilla: solo se va si ganas la puja.
    Un fichaje de momento ``luego`` o ``alternativa`` no entra en la suma.
    """
    ventas_hoy = {
        accion["player_id"]
        for accion in acciones
        if accion.get("tipo") in {"VENDE", "VENDER HOY"}
        and accion.get("momento") == "hoy"
        and isinstance(accion.get("player_id"), str)
    }
    fichajes_hoy = {
        accion["player_id"]
        for accion in acciones
        if accion.get("tipo") in {"PUJA", "CLAUSULAZO"}
        and accion.get("momento") == "hoy"
        and isinstance(accion.get("player_id"), str)
    }
    pool: list[dict[str, Any]] = []
    ficha: dict[str, tuple[dict[str, Any], str]] = {}
    for row in plantilla:
        if row["player_id"] in ventas_hoy or not _cuenta_en_esqueleto(row):
            continue
        pool.append(
            {
                "player_id": row["player_id"],
                "position": row["position"],
                "jornada": float(row.get("jornada") or 0.0),
                "p_titular": row.get("p_titular"),
                "si_titular": row.get("si_titular"),
            }
        )
        ficha[row["player_id"]] = (row, "plantilla")
    origen = {row["player_id"]: ("puja", row) for row in compras}
    origen.update({row["player_id"]: ("clausulazo", row) for row in raids})
    for player_id in fichajes_hoy:
        par = origen.get(player_id)
        if par is None:
            continue
        etiqueta, row = par
        if row.get("position") not in POSITIONS:
            continue
        pool.append(
            {
                "player_id": player_id,
                "position": row["position"],
                "jornada": float(row.get("jornada") or 0.0),
                "p_titular": row.get("p_titular"),
                "si_titular": row.get("si_titular"),
            }
        )
        ficha[player_id] = (row, etiqueta)
    resultado = solve_best_xi(pool)
    if not resultado["ok"]:
        return {"ok": False, "puntos": 0.0, "once": []}
    once = []
    for player_id in resultado["player_ids"]:
        row, etiqueta = ficha[player_id]
        once.append(_ficha(row, etiqueta))
    return {"ok": True, "puntos": float(resultado["puntos"]), "once": once}


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

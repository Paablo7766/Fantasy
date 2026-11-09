"""Modo Parón autónomo: trading + once de la jornada que reabre la liga.

En un parón de selecciones (12-13 días sin liga) el plan normal se queda corto:
el saldo puede estar en negativo sin sanción hasta el primer saque, el mercado
se mueve dos semanas y todo lo que hoy compras o vendes tiene tiempo de
revalorizarse o de desangrarse. Este módulo no sustituye al solver del once:
cuelga de su resultado y añade la capa de calendario.

Tres fases, medidas en días hasta el cierre:

* **Fase 1 · caza de plusvalías (más de 6 días)**: corta-hemorragias (vender lo
  que baja o no va a jugar), fichajes que mejoran el once y suben (hold) y
  especulación pura con el crédito del 20 % que sobra.
* **Fase 2 · recogida de beneficios (de 6 a 3,5 días)**: el flip que frena se
  pone en escaparate; solo se compra nuevo lo que sube muy fuerte.
* **Fase 3 · aterrizaje (últimos 3,5 días)**: se apaga la especulación y la
  ruta de salida se ejecuta: saldo en cero o más con el mejor once posible.

La ruta de salida se calcula siempre. Vende a valor proyectado (lo que se
espera que valga el jugador el día de la venta, si es menor que el de hoy).
El suelo de estrés es el mínimo observado de la máquina (0,93×), no el 0,90×
legal. La ventana de escaparate es martes o miércoles.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pulp

from toolbox.analyzer import POSITIONS
from toolbox.engine.lineup_math import solve_best_xi
from toolbox.engine.market_predictor import cambio_pct_desde_delta, proyectar_inercia, vender_en_pico_prohibido
from toolbox.engine.paron import HORIZONTE_PREVISION_DIAS, es_paron
from toolbox.engine.signing_plan import (
    CREDITO_PARON_PCT,
    MEJORA_MINIMA,
    UMBRAL_CAIDA_PCT,
    _es_baja,
    _leer_pct,
    _nombre,
    _valor_jugador,
    conserva_esqueleto,
)
from toolbox.engine.reglamento import (
    OFERTA_ESPERADA_VENTANA,
    OFERTA_LALIGA_MIN,
    OFERTA_MAQUINA_MEDIANA_VIERNES,
    OFERTA_MAQUINA_MINIMO_HISTORICO,
)
from toolbox.engine.trading_desk import DEUDA_PCT_EQUIPO

_MADRID = ZoneInfo("Europe/Madrid")
_MILLON = 1_000_000

#: Frontera entre fases, en días hasta el cierre.
DIAS_FASE_1 = 6.0
DIAS_FASE_3 = 3.5
#: Se vende dos días antes del saque: LaLiga tarda en ofrecer y el último día no hay margen.
DIAS_VENTA_ANTES_CIERRE = 2.0
#: LaLiga ofrece entre −10 % y +10 % del valor (regla oficial): se cuenta el peor caso.
MARGEN_OFERTA = OFERTA_LALIGA_MIN
#: Colchón sobre la deuda en la ruta de salida: absorbe que el precio baje en vez de
#: subir y el redondeo de las ofertas, para no llegar al saque en negativo.
HOLGURA_RUTA_EUR = 500_000
#: Beneficio neto mínimo para especular con crédito.
BENEFICIO_MIN_ESPECULAR = 500_000
#: Un banquillo por debajo de esta subida semanal ya no merece esperar.
FRENO_PCT = 3.0
#: Vender a quien no juega solo si el once no pierde más que esto.
PERDIDA_XP_TOLERADA = 0.3
MAX_ESPECULACIONES = 6
#: xP mínimos del fichaje barato que tapa un hueco en la ruta de salida.
REPOSICION_XP_MIN = 3.0

ETIQUETA_HOLD = "🟢 Titular + Subida (Hold J13)"
ETIQUETA_CORTA = "🩸 Corta-hemorragias"
ETIQUETA_RECOGER = "💵 Recoger beneficios"

_DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def fase_paron(dias: float | None, ciclo_paron: bool = False) -> int | None:
    """1, 2 o 3 si el ciclo es un parón; ``None`` en una semana normal.

    Un ciclo es parón si faltan más de 7,5 días, o si el calendario dice que el
    parón empezó (``ciclo_paron``): así las fases 2 y 3 siguen activas cuando el
    reloj ya baja de 7,5 días.
    """
    if dias is None or isinstance(dias, bool) or not math.isfinite(float(dias)) or dias <= 0:
        return None
    if not (es_paron(dias) or ciclo_paron):
        return None
    if dias > DIAS_FASE_1:
        return 1
    if dias > DIAS_FASE_3:
        return 2
    return 3


NOMBRE_FASE = {
    1: "Fase 1 · Caza de plusvalías y limpieza",
    2: "Fase 2 · Recogida de beneficios y rotación",
    3: "Fase 3 · Aterrizaje al once de gala",
}


def _dia_texto(momento: datetime) -> str:
    """``miércoles 18-nov``: día de la semana, día y mes, en hora de Madrid."""
    local = momento.astimezone(_MADRID)
    return f"{_DIAS_SEMANA[local.weekday()]} {local.day}-{_MESES[local.month - 1]}"


def _horizonte_dias(dias: float) -> float:
    """Días de previsión de precio hasta el día de venta, topados en los 7 de la previsión."""
    return min(HORIZONTE_PREVISION_DIAS, max(0.0, dias - DIAS_VENTA_ANTES_CIERRE))


def valor_proyectado(row: dict[str, Any], dias_hasta_venta: float, *, hoy: date | None = None) -> int:
    """Valor esperado el día de la venta.

    Con el cambio de hoy conocido (``delta_hoy``) se proyecta con la ley por
    régimen (0,951 si sube, 0,932 si baja; domingos planos) y, tras una
    jornada con puntos altos de quien no llegaba cayendo, con el impulso de
    +1,78 %. Sin delta, la previsión a 7 días va en lineal.
    """
    valor = _valor_jugador(row)
    delta = row.get("delta_hoy")
    if valor > 0 and isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta != 0:
        return int(
            proyectar_inercia(
                valor,
                cambio_pct_desde_delta(valor, delta),
                dias_hasta_venta,
                desde=hoy,
                puntos_jornada=row.get("puntos_ultima"),
                post_jornada=_post_jornada(hoy),
            )["valor"]
        )
    pct = _leer_pct(row)
    if valor <= 0 or pct is None:
        return valor
    return int(round(valor * (1.0 + (pct / 100.0) * (dias_hasta_venta / 7.0))))


def dia_de_venta(cierre: datetime, dias: float) -> datetime:
    """Cuándo se pone el escaparate: martes o miércoles antes del cierre, nunca el viernes.

    Entre lunes y miércoles la máquina de LaLiga pagó una mediana de 1,034× el
    valor (viernes: 0,974×). Se parte de ``cierre - 2 días``; si cae fuera de
    martes/miércoles se retrocede al miércoles anterior. Si ese miércoles ya
    pasó, se vende hoy mismo.
    """
    candidato = cierre - timedelta(days=DIAS_VENTA_ANTES_CIERRE)
    local = candidato.astimezone(_MADRID)
    if local.weekday() not in (1, 2):
        atras = (local.weekday() - 2) % 7
        candidato = candidato - timedelta(days=atras if atras else 7)
    ahora = cierre - timedelta(days=float(dias))
    return max(candidato, ahora)


def ofertas_de_ruta(dia_venta: datetime) -> dict[str, Any]:
    """Los dos escenarios de oferta de la máquina según el día de la venta."""
    en_ventana = dia_venta.astimezone(_MADRID).weekday() in (0, 1, 2)
    if en_ventana:
        return {
            "en_ventana": True,
            "esperado": OFERTA_ESPERADA_VENTANA,
            "estres": OFERTA_MAQUINA_MINIMO_HISTORICO,
        }
    return {"en_ventana": False, "esperado": OFERTA_MAQUINA_MEDIANA_VIERNES, "estres": OFERTA_MAQUINA_MINIMO_HISTORICO}


def _ventana_texto(dia_venta: datetime) -> str:
    local = dia_venta.astimezone(_MADRID)
    if local.weekday() == 2:
        martes = local - timedelta(days=1)
        return f"{_dia_texto(martes)} / {_dia_texto(local)}"
    return _dia_texto(local)


def _post_jornada(hoy: date | None) -> bool:
    """Lunes o martes: el salto de precio tras la jornada recién jugada."""
    dia = hoy or datetime.now(_MADRID).date()
    return dia.weekday() in (0, 1)


def venta_prematura(row: dict[str, Any], *, dia_limite_caja: bool) -> bool:
    """No se recomienda vender en el pico a quien hoy sube con claridad, salvo el dia limite de caja."""
    delta = row.get("delta_hoy")
    valor = _valor_jugador(row)
    if valor <= 0 or isinstance(delta, bool) or not isinstance(delta, (int, float)):
        return False
    return vender_en_pico_prohibido(cambio_pct_desde_delta(valor, delta), dia_limite_caja=dia_limite_caja)


def beneficio_especulacion(
    *,
    valor: int,
    puja: int,
    pct: float,
    dias_hasta_venta: float,
) -> int:
    """Euros netos de comprar hoy a ``puja`` y vender el día de venta al suelo de estrés (0,93×)."""
    final = valor * (1.0 + (pct / 100.0) * (dias_hasta_venta / 7.0))
    return int(round(final * OFERTA_MAQUINA_MINIMO_HISTORICO - puja))


def _pool_xi(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "player_id": row["player_id"],
            "position": row["position"],
            "jornada": float(row.get("jornada") or 0.0),
            "p_titular": row.get("p_titular"),
            "si_titular": row.get("si_titular"),
        }
        for row in filas
        if row.get("elegible") is not False and row.get("position") in POSITIONS
    ]


def _puntos(filas: list[dict[str, Any]]) -> tuple[float, set[str]]:
    resultado = solve_best_xi(_pool_xi(filas))
    if not resultado["ok"]:
        return 0.0, set()
    return float(resultado["puntos"]), set(resultado["player_ids"])


def _fila_compra(accion: dict[str, Any], mercado: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    row = mercado.get(str(accion.get("player_id")))
    if row is None:
        return None
    return {
        "player_id": row["player_id"],
        "nombre": row.get("nombre"),
        "position": row.get("position"),
        "jornada": float(row.get("jornada") or 0.0),
        "valor": row.get("valor") or accion.get("euros"),
        "pct": row.get("pct"),
        "p_titular": row.get("p_titular"),
        "si_titular": row.get("si_titular"),
        "elegible": True,
        "venta_eur": int((row.get("valor") or accion.get("euros") or 0) * MARGEN_OFERTA) or None,
        "origen": "fichaje",
    }


def _accion_paron(
    tipo: str,
    rol: str,
    etiqueta: str,
    row: dict[str, Any],
    *,
    euros: int | None,
    detalle: str,
    momento: str = "hoy",
    ganancia: int | None = None,
) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "momento": momento,
        "impulso": "PARON",
        "paron_rol": rol,
        "etiqueta_paron": etiqueta,
        "player_id": row.get("player_id"),
        "nombre": _nombre(row),
        "posicion": row.get("position") or row.get("posicion"),
        "jornada": row.get("jornada"),
        "euros": euros,
        "prevision_7d_pct": _leer_pct(row),
        "ganancia_esperada_eur": ganancia,
        "detalle": detalle,
    }


def _corta_hemorragias(
    *,
    owned: list[dict[str, Any]],
    compras: list[dict[str, Any]],
    ya_vendidos: set[str],
    dias_venta: float,
) -> list[dict[str, Any]]:
    """Vender ya lo que se desangra o no juega, si el once de la J13 no lo echa en falta."""
    candidatos: list[tuple[float, dict[str, Any]]] = []
    for row in owned:
        player_id = row["player_id"]
        if player_id in ya_vendidos:
            continue
        pct = _leer_pct(row)
        baja = _es_baja(row)
        bajando = pct is not None and pct < UMBRAL_CAIDA_PCT
        if not (bajando or baja):
            continue
        venta = row.get("venta_eur")
        if isinstance(venta, bool) or not isinstance(venta, int) or venta <= 0:
            continue
        candidatos.append((pct if pct is not None else 0.0, row))
    candidatos.sort(key=lambda item: item[0])
    salida: list[dict[str, Any]] = []
    vendidos = set(ya_vendidos)
    for pct, row in candidatos:
        probados = vendidos | {row["player_id"]}
        quedan = [item for item in owned if item["player_id"] not in probados]
        if not conserva_esqueleto(owned, probados):
            continue
        con, _ = _puntos([*owned_sin(owned, vendidos), *compras])
        sin, _ = _puntos([*quedan, *compras])
        if con - sin > PERDIDA_XP_TOLERADA:
            continue
        vendidos.add(row["player_id"])
        valor = _valor_jugador(row)
        evitado = int(round(valor * abs(min(pct, 0.0)) / 100.0 * (max(dias_venta, 1.0) / 7.0)))
        salida.append({"row": row, "evitado": evitado, "baja": _es_baja(row), "pct": pct})
    return salida


def owned_sin(owned: list[dict[str, Any]], ids: set[str]) -> list[dict[str, Any]]:
    return [row for row in owned if row["player_id"] not in ids]


def _capital_especulacion(plan: dict[str, Any], saldo: int, valor_equipo: int, ingresos_extra: int) -> dict[str, int]:
    """Caja y crédito que ninguna puja del once tiene reservados."""
    cobertura = plan.get("cobertura_pujas")
    if isinstance(cobertura, dict):
        reservada = sum(int(item.get("caja") or 0) for item in cobertura.get("pujas") or [])
        caja = max(0, int(cobertura.get("caja_al_pujar") or 0) - reservada)
        tope = cobertura.get("tope_deuda")
        tope = int(tope) if isinstance(tope, int) else int(valor_equipo * DEUDA_PCT_EQUIPO)
        credito = max(0, tope - int(cobertura.get("deuda_al_pujar") or 0))
    else:
        caja = max(0, saldo)
        credito = int(valor_equipo * DEUDA_PCT_EQUIPO) + min(0, saldo)
        credito = max(0, credito)
    return {"caja": caja + max(0, ingresos_extra), "credito": credito}


def _especular(
    *,
    mercado: list[dict[str, Any]],
    excluidos: set[str],
    capital: int,
    dias_venta: float,
    fase: int,
    cierre: datetime,
) -> list[dict[str, Any]]:
    """Mochila de compras que ganan dinero limpio sin tocar el once."""
    if fase == 3 or capital <= 0:
        return []
    filas: list[dict[str, Any]] = []
    for row in mercado:
        player_id = row.get("player_id")
        if player_id in excluidos or row.get("af_alerta_bajada") is True:
            continue
        pct = _leer_pct(row)
        euros = row.get("euros")
        valor = row.get("valor") or euros
        if pct is None or pct <= 0 or not isinstance(euros, int) or euros <= 0 or not valor:
            continue
        # Prohibido comprar el dip con crédito: si hoy sigue cayendo, el lunes
        # de la J12 demostró que un buen partido no lo frena.
        delta = row.get("delta_hoy")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and float(valor) > float(delta):
            if float(delta) / (float(valor) - float(delta)) < 0:
                continue
        if fase == 2 and pct < CREDITO_PARON_PCT:
            continue
        neto = beneficio_especulacion(valor=int(valor), puja=euros, pct=pct, dias_hasta_venta=dias_venta)
        if neto < BENEFICIO_MIN_ESPECULAR:
            continue
        filas.append({"row": row, "euros": euros, "valor": int(valor), "pct": pct, "neto": neto})
    if not filas:
        return []
    problem = pulp.LpProblem("paron_especular", pulp.LpMaximize)
    elegir = [pulp.LpVariable(f"s{i}", cat=pulp.LpBinary) for i in range(len(filas))]
    problem += pulp.lpSum(fila["neto"] * var for fila, var in zip(filas, elegir))
    problem += pulp.lpSum(fila["euros"] * var for fila, var in zip(filas, elegir)) <= capital
    problem += pulp.lpSum(elegir) <= MAX_ESPECULACIONES
    problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=5))
    elegidas = [fila for fila, var in zip(filas, elegir) if (var.value() or 0.0) > 0.5]
    elegidas.sort(key=lambda fila: -fila["neto"])
    return elegidas


def _reposicion(position: str, reposiciones: list[dict[str, Any]], usadas: set[str]) -> dict[str, Any] | None:
    """El fichaje más barato del mercado que tapa un hueco y juega de verdad (≥ 3 xP; si no, el más barato)."""
    pool = [
        row
        for row in reposiciones
        if row.get("position") == position and row.get("player_id") not in usadas and isinstance(row.get("euros"), int)
    ]
    dignos = [row for row in pool if float(row.get("jornada") or 0.0) >= REPOSICION_XP_MIN]
    pool = dignos or pool
    return min(pool, key=lambda row: (row["euros"], -float(row.get("jornada") or 0.0))) if pool else None


def _fila_reposicion(rep: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": rep["player_id"],
        "nombre": rep.get("nombre"),
        "position": rep["position"],
        "jornada": float(rep.get("jornada") or 0.0),
        "valor": rep.get("valor") or rep["euros"],
        "elegible": True,
        "origen": "reposicion",
    }


def ruta_salida(
    *,
    squad: list[dict[str, Any]],
    saldo_proyectado: int,
    dias: float,
    cierre: datetime,
    reposiciones: list[dict[str, Any]] | None = None,
    premio_jornada: int = 0,
) -> dict[str, Any]:
    """Qué vender (a valor proyectado) para llegar al cierre con saldo ≥ 0 perdiendo los mínimos puntos.

    Si vender deja la plantilla sin once legal, se tapa el hueco con el fichaje
    más barato del mercado de esa posición y se cuenta su coste.
    """
    dia_venta = dia_de_venta(cierre, dias)
    dias_hasta_venta = _horizonte_dias(dias)
    ofertas = ofertas_de_ruta(dia_venta)
    esperado = float(ofertas["esperado"])
    estres = float(ofertas["estres"])
    deuda = max(0, -int(saldo_proyectado))
    base_puntos, xi_ids = _puntos(squad)
    resultado: dict[str, Any] = {
        "dia_venta": _dia_texto(dia_venta),
        "dia_venta_at": dia_venta.astimezone(_MADRID).isoformat(),
        "ventana_escaparate": _ventana_texto(dia_venta),
        "holgura_eur": HOLGURA_RUTA_EUR if deuda > 0 else 0,
        "margen_oferta": esperado,
        "oferta_esperada": esperado,
        "oferta_estres": estres,
        "en_ventana_buena": bool(ofertas["en_ventana"]),
        "escenarios": None,
        "deuda_a_saldar": deuda,
        "saldo_proyectado": int(saldo_proyectado),
        "premio_jornada_incluido": int(premio_jornada),
        "ventas": [],
        "reposiciones": [],
        "ingreso": 0,
        "cubre": deuda == 0,
        "falta_eur": 0,
        "xp_perdido": 0.0,
        "titulares_vendidos": 0,
        "texto": None,
    }
    if deuda == 0:
        resultado["texto"] = "Sin deuda prevista: el saldo llega al cierre en cero o más sin vender nada más."
        return resultado

    def ingreso(row: dict[str, Any], razon: float = esperado) -> int:
        # La menor entre el valor de hoy y el proyectado, por la oferta del escenario.
        hoy = _valor_jugador(row)
        proyectado = valor_proyectado(row, dias_hasta_venta)
        base = min(hoy, proyectado) if hoy > 0 else proyectado
        return int(base * razon)

    objetivo = deuda + HOLGURA_RUTA_EUR

    actual = list(squad)
    vendidos: list[dict[str, Any]] = []
    repuestos: list[dict[str, Any]] = []
    usadas: set[str] = set()
    neto = 0
    while neto < objetivo:
        puntos_actual, _ = _puntos(actual)
        mejor: tuple[tuple[float, float], dict[str, Any], dict[str, Any] | None, float, int] | None = None
        for row in actual:
            if ingreso(row) <= 0:
                continue
            resto = [item for item in actual if item["player_id"] != row["player_id"]]
            rep = None
            if not conserva_esqueleto(resto, set()):
                rep = _reposicion(str(row.get("position")), reposiciones or [], usadas)
                if rep is None:
                    continue
                resto = [*resto, _fila_reposicion(rep)]
                if not conserva_esqueleto(resto, set()):
                    continue
            caja = ingreso(row) - (int(rep["euros"]) if rep else 0)
            if caja <= 0:
                continue
            sin, _ = _puntos(resto)
            perdida = max(0.0, puntos_actual - sin)
            clave = (0.0, -float(caja)) if perdida <= 1e-9 else (perdida / caja * _MILLON, 0.0)
            if mejor is None or clave < mejor[0]:
                mejor = (clave, row, rep, perdida, caja)
        if mejor is None:
            break
        _clave, row, rep, perdida, caja = mejor
        actual = [item for item in actual if item["player_id"] != row["player_id"]]
        if rep is not None:
            usadas.add(rep["player_id"])
            repuestos.append(rep)
            actual.append(_fila_reposicion(rep))
        neto += caja
        vendidos.append({"row": row, "perdida": perdida})
    sin_final, _ = _puntos(actual)
    perdido = round(max(0.0, base_puntos - sin_final), 2)
    resultado["ventas"] = [
        {
            "player_id": item["row"]["player_id"],
            "nombre": _nombre(item["row"]),
            "valor_hoy": _valor_jugador(item["row"]),
            "valor_proyectado": valor_proyectado(item["row"], dias_hasta_venta),
            "ingreso": ingreso(item["row"]),
            "ingreso_estres": ingreso(item["row"], estres),
            "titular": item["row"]["player_id"] in xi_ids,
            "origen": item["row"].get("origen") or "plantilla",
            "xp_perdido": round(item["perdida"], 2),
        }
        for item in vendidos
    ]
    resultado["reposiciones"] = [
        {
            "player_id": rep["player_id"],
            "nombre": _nombre(rep),
            "posicion": rep.get("position"),
            "euros": int(rep["euros"]),
            "jornada": rep.get("jornada"),
        }
        for rep in repuestos
    ]
    resultado["ingreso"] = neto
    coste_reposiciones = sum(int(rep["euros"]) for rep in repuestos)
    neto_estres = sum(item["ingreso_estres"] for item in resultado["ventas"]) - coste_reposiciones
    resultado["ingreso_estres"] = neto_estres
    resultado["cubre_estres"] = neto_estres >= deuda
    resultado["escenarios"] = {
        "esperado": {
            "oferta": esperado,
            "ingreso": neto,
            "cubre": neto >= deuda,
            "etiqueta": f"Escenario esperado ({esperado:.3f}×)".replace(".", ","),
        },
        "estres": {
            "oferta": estres,
            "ingreso": neto_estres,
            "cubre": neto_estres >= deuda,
            "falta_eur": max(0, deuda - neto_estres),
            "etiqueta": f"Suelo de estrés histórico ({estres:.2f}×)".replace(".", ","),
        },
    }
    resultado["cubre"] = neto >= deuda
    resultado["con_holgura"] = neto >= objetivo
    resultado["falta_eur"] = max(0, deuda - neto)
    resultado["xp_perdido"] = perdido
    resultado["titulares_vendidos"] = sum(1 for item in resultado["ventas"] if item["titular"])
    premio_txt = (
        f" El saldo ya cuenta {premio_jornada / _MILLON:.1f} M€ de premio de puntos de la jornada en juego."
        if premio_jornada > 0
        else ""
    )
    nombres = ", ".join(f"{item['nombre']} ({item['ingreso'] / _MILLON:.1f} M€)" for item in resultado["ventas"])
    huecos = ", ".join(f"{item['nombre']} ({item['euros'] / _MILLON:.1f} M€)" for item in resultado["reposiciones"])
    cola = f" y repone con {huecos}" if huecos else ""
    if resultado["cubre"]:
        resultado["texto"] = (
            f"Ruta de salida antes del {_dia_texto(cierre)}: el {resultado['dia_venta']} vende {nombres}{cola}. "
            f"Entran {neto / _MILLON:.1f} M€ netos en el escenario esperado ({esperado:.2f}× sobre el menor entre el valor de hoy y el previsto) "
            f"para cubrir {deuda / _MILLON:.1f} M€ de deuda"
            + (f"; el once pierde {perdido:.1f} xP." if perdido > 0 else " sin tocar el once.")
            + f" Suelo de estrés histórico ({estres:.2f}×): {neto_estres / _MILLON:.1f} M€"
            + (" (también cubre)." if neto_estres >= deuda else f" (faltarían {(deuda - neto_estres) / _MILLON:.1f} M€).")
            + (
                ""
                if ofertas["en_ventana"]
                else " Fuera de lunes-miércoles la máquina paga menos (viernes: 0,974× de mediana)."
            )
            + premio_txt
        )
    else:
        resultado["texto"] = (
            f"Ruta de salida: ni vendiendo {nombres or 'todo lo vendible'}{cola} se cubren {deuda / _MILLON:.1f} M€; "
            f"faltarían {resultado['falta_eur'] / _MILLON:.1f} M€. Reduce compras con crédito." + premio_txt
        )
    return resultado


def construir_paron(
    *,
    fase: int,
    dias: float,
    cierre: datetime,
    saldo: int,
    owned: list[dict[str, Any]],
    mercado: list[dict[str, Any]],
    plan: dict[str, Any],
    previos: set[str],
    premio_jornada: int = 0,
) -> dict[str, Any]:
    """Capa de parón sobre un plan ya resuelto. No modifica ``plan``: devuelve el bloque ``paron``."""
    dias_venta = _horizonte_dias(dias)
    acciones_plan = [a for a in plan.get("acciones") or [] if isinstance(a, dict)]
    por_id = {row["player_id"]: row for row in mercado if isinstance(row.get("player_id"), str)}
    ventas_plan = {
        a["player_id"]
        for a in acciones_plan
        if a.get("tipo") in {"VENDE", "VENDER HOY"} and isinstance(a.get("player_id"), str)
    }
    compras_plan = [
        a for a in acciones_plan if a.get("tipo") in {"PUJA", "CLAUSULAZO"} and isinstance(a.get("player_id"), str)
    ]
    filas_compra = [fila for fila in (_fila_compra(a, por_id) for a in compras_plan) if fila]
    valor_equipo = sum(_valor_jugador(row) for row in owned)

    # Etiqueta de las compras que ya trae el solver: mejoran el once y suben.
    hold: list[dict[str, Any]] = []
    for accion in compras_plan:
        mejora = float(accion.get("mejora_neta") or 0.0)
        pct = accion.get("prevision_7d_pct")
        if mejora >= MEJORA_MINIMA:
            accion["paron_rol"] = "HOLD_J13"
            accion["etiqueta_paron"] = ETIQUETA_HOLD
            fila = por_id.get(accion["player_id"], {})
            valor = int(fila.get("valor") or accion.get("euros") or 0)
            subida = (
                int(round(valor * (float(pct) / 100.0) * (dias_venta / 7.0)))
                if isinstance(pct, (int, float)) and not isinstance(pct, bool)
                else 0
            )
            hold.append({"accion": accion, "subida": subida})

    owned_ok = [row for row in owned if isinstance(row.get("player_id"), str)]
    corta = _corta_hemorragias(
        owned=owned_ok,
        compras=filas_compra,
        ya_vendidos=set(ventas_plan),
        dias_venta=dias_venta,
    )
    acciones_nuevas: list[dict[str, Any]] = []
    ingresos_firmes = 0
    for item in corta:
        row = item["row"]
        oferta = row.get("tiene_oferta_laliga") is True
        motivo = (
            "está lesionado o sancionado en la J13"
            if item["baja"]
            else f"baja un {abs(item['pct']):.1f} % a 7 días"
        )
        if oferta:
            ingresos_firmes += int(row["venta_eur"])
        acciones_nuevas.append(
            _accion_paron(
                "VENDER HOY" if oferta else "ESCAPARATE",
                "CORTA_HEMORRAGIAS",
                ETIQUETA_CORTA,
                row,
                euros=int(row["venta_eur"]),
                ganancia=item["evitado"],
                detalle=(
                    f"{ETIQUETA_CORTA}: {motivo} y el once de la J13 no lo echa en falta. "
                    + (
                        "Hay oferta de LaLiga: acéptala hoy."
                        if oferta
                        else "Ponlo hoy en el escaparate para tener oferta mañana."
                    )
                    + f" Evita unos {item['evitado'] / _MILLON:.2f} M€ de pérdida en el parón."
                ),
            )
        )

    vendidos_ya = set(ventas_plan) | {item["row"]["player_id"] for item in corta}
    squad_final = [
        *[{**row, "origen": row.get("origen") or "plantilla"} for row in owned_ok if row["player_id"] not in vendidos_ya],
        *filas_compra,
    ]
    _, xi_final = _puntos(squad_final)

    # Fase 2: recoger beneficios del flip que ya no sube.
    recoger: list[dict[str, Any]] = []
    if fase in (2, 3):
        for row in owned_ok:
            player_id = row["player_id"]
            if player_id in vendidos_ya or player_id in xi_final:
                continue
            if venta_prematura(row, dia_limite_caja=dias_venta <= 0):
                continue
            pct = _leer_pct(row)
            flip = player_id in previos
            frena = pct is None or pct < FRENO_PCT
            if fase == 2 and not (flip and frena):
                continue
            if fase == 3 and not (flip or frena):
                continue
            venta = row.get("venta_eur")
            if isinstance(venta, bool) or not isinstance(venta, int) or venta <= 0:
                continue
            recoger.append(row)
        for row in recoger:
            acciones_nuevas.append(
                _accion_paron(
                    "ESCAPARATE",
                    "RECOGER_BENEFICIOS",
                    ETIQUETA_RECOGER,
                    row,
                    euros=int(row["venta_eur"]),
                    detalle=(
                        "Poner en escaparate para recoger beneficios: no entra en el once de la J13 "
                        "y su subida se frena."
                    ),
                )
            )

    # Fase 1 y 2: especulación con el crédito que sobra.
    capital = _capital_especulacion(plan, saldo, valor_equipo, ingresos_firmes)
    especulaciones = _especular(
        mercado=[row for row in mercado if row.get("player_id") not in {a["player_id"] for a in compras_plan}],
        excluidos=set(),
        capital=capital["caja"] + capital["credito"],
        dias_venta=dias_venta,
        fase=fase,
        cierre=cierre,
    )
    limite_venta = _dia_texto(cierre - timedelta(days=1))
    etiqueta_spec = f"💰 Especular (Vender antes del {limite_venta})"
    gasto_spec = 0
    for fila in especulaciones:
        row = fila["row"]
        gasto_spec += fila["euros"]
        acciones_nuevas.append(
            _accion_paron(
                "PUJA",
                "ESPECULAR",
                etiqueta_spec,
                row,
                euros=fila["euros"],
                ganancia=fila["neto"],
                detalle=(
                    f"{etiqueta_spec}. No entra en tu once: se compra con el crédito libre y se vende "
                    f"antes del cierre. Sube un {fila['pct']:.1f} % a 7 días; ganancia limpia esperada "
                    f"{fila['neto'] / _MILLON:.2f} M€ tras pagar el sobreprecio y vender con la oferta más baja (90 %)."
                ),
            )
        )
        squad_final.append(
            {
                "player_id": row["player_id"],
                "nombre": row.get("nombre"),
                "position": row.get("position"),
                "jornada": float(row.get("jornada") or 0.0),
                "valor": fila["valor"],
                "pct": fila["pct"],
                "elegible": True,
                "venta_eur": int(fila["valor"] * MARGEN_OFERTA),
                "origen": "fichaje",
            }
        )

    # Saldo con el que se llega al cierre si no se vende nada más.
    saldo_plan = plan.get("saldo_al_final")
    base_saldo = int(saldo_plan) if isinstance(saldo_plan, int) and not isinstance(saldo_plan, bool) else saldo
    saldo_proyectado = base_saldo + ingresos_firmes + sum(
        int(item["row"]["venta_eur"]) for item in corta if item["row"].get("tiene_oferta_laliga") is not True
    ) - gasto_spec + int(premio_jornada)
    comprados = {a["player_id"] for a in compras_plan} | {fila["row"]["player_id"] for fila in especulaciones}
    ruta = ruta_salida(
        squad=squad_final,
        saldo_proyectado=saldo_proyectado,
        dias=dias,
        cierre=cierre,
        reposiciones=[row for row in mercado if row.get("player_id") not in comprados],
        premio_jornada=premio_jornada,
    )

    # Fase 3: la ruta se ejecuta ya.
    if fase == 3:
        for venta in ruta["ventas"]:
            if venta["player_id"] in vendidos_ya or any(a["player_id"] == venta["player_id"] for a in acciones_nuevas):
                continue
            fila = next((r for r in squad_final if r["player_id"] == venta["player_id"]), None)
            if fila is None:
                continue
            acciones_nuevas.append(
                _accion_paron(
                    "ESCAPARATE",
                    "RUTA_SALIDA",
                    "🛬 Ruta de salida",
                    fila,
                    euros=venta["ingreso"],
                    detalle="Ruta de salida: ponlo en escaparate y acepta la oferta para dejar el saldo en cero o más antes del cierre.",
                )
            )

    subida_hold = sum(item["subida"] for item in hold)
    ganancia_spec = sum(fila["neto"] for fila in especulaciones)
    evitado = sum(item["evitado"] for item in corta)
    mejora_xp = plan.get("mejora_puntos_jornada")
    return {
        "activo": True,
        "fase": fase,
        "fase_nombre": NOMBRE_FASE[fase],
        "dias_al_cierre": round(dias, 2),
        "cierre": cierre.astimezone(_MADRID).isoformat(),
        "dia_venta": ruta["dia_venta"],
        "acciones": acciones_nuevas,
        "corta_hemorragias": [a for a in acciones_nuevas if a["paron_rol"] == "CORTA_HEMORRAGIAS"],
        "especular": [a for a in acciones_nuevas if a["paron_rol"] == "ESPECULAR"],
        "recoger_beneficios": [a for a in acciones_nuevas if a["paron_rol"] == "RECOGER_BENEFICIOS"],
        "hold_j13": [
            {
                "player_id": item["accion"]["player_id"],
                "nombre": item["accion"]["nombre"],
                "euros": item["accion"]["euros"],
                "subida_esperada_eur": item["subida"],
            }
            for item in hold
        ],
        "capital_especulacion": capital,
        "ruta_salida": ruta,
        "proyeccion": {
            "ganancia_hold_eur": int(subida_hold),
            "ganancia_especulacion_eur": int(ganancia_spec),
            "perdida_evitada_eur": int(evitado),
            "beneficio_total_eur": int(subida_hold + ganancia_spec + evitado),
            "mejora_xp_j13": mejora_xp if isinstance(mejora_xp, (int, float)) and not isinstance(mejora_xp, bool) else 0.0,
            "saldo_viernes_sin_ruta": int(saldo_proyectado),
            "premio_jornada_eur": int(premio_jornada),
            "xp_perdido_por_ruta": ruta["xp_perdido"],
        },
    }

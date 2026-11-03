"""Salida ordenada de los jugadores que no entran en el once antes de la jornada.

Sin banquillo, el jugador #12 en adelante no puntúa el fin de semana: es caja
parada. El trading desk los compra de lunes a miércoles. Este módulo decide
cuándo y cómo se venden, por fases según los días que faltan al primer saque:

- ``APALANCAMIENTO`` (3 días o más): se mantienen, son posiciones de trading.
  Solo se vende si la oferta ya paga el valor de mercado.
- ``ESCAPARATE`` (de 1,5 a 3 días): se ponen a la venta. La oferta de LaLiga
  es aleatoria (valor ±10 %) y se renueva cada ~24 h, así que hay que estar en
  el escaparate antes de necesitarla. Se acepta la que pague el valor.
- ``LIQUIDACION`` (menos de 1,5 días): se acepta la oferta que haya para
  dejar 11 y saldo >= 0. Saldo negativo al saque anula la jornada.

No envía órdenes ni lee caché: recibe la plantilla y las ofertas ya leídas.
"""

from __future__ import annotations

from typing import Any

from toolbox.engine.lineup_math import solve_best_xi

FASE_APALANCAMIENTO = "APALANCAMIENTO"
FASE_ESCAPARATE = "ESCAPARATE"
FASE_LIQUIDACION = "LIQUIDACION"
#: Días al saque desde los que se deja de apalancar y se sale al escaparate.
DIAS_ESCAPARATE = 3.0
#: Por debajo, se vende con la oferta que haya.
DIAS_LIQUIDACION = 1.5
#: La oferta automática de LaLiga cae entre valor -10 % y +10 %.
OFERTA_LALIGA_MIN = 0.90

ACCION_MANTENER = "MANTENER"
ACCION_VENDER = "VENDER HOY A LALIGA"
ACCION_ESCAPARATE = "PONER EN EL ESCAPARATE"
ACCION_ESPERAR = "ESPERAR OFERTA"
ACCION_SIN_OFERTA = "SIN OFERTA: VENDER A UN RIVAL"

ETIQUETA_LIQUIDAR = "VENDER HOY A LALIGA: Recoger beneficios y dejar plantilla en 11 titulares exactos y saldo >= 0"


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def fase_semana(dias_para_jornada: float | None) -> str | None:
    """Fase del ciclo semanal. Sin saque conocido no hay fase."""
    if dias_para_jornada is None:
        return None
    if dias_para_jornada >= DIAS_ESCAPARATE:
        return FASE_APALANCAMIENTO
    if dias_para_jornada >= DIAS_LIQUIDACION:
        return FASE_ESCAPARATE
    return FASE_LIQUIDACION


def _valor(row: dict[str, Any]) -> int:
    for key in ("valor", "venta_eur"):
        value = _int(row.get(key))
        if value is not None and value > 0:
            return value
    return 0


def _pct(row: dict[str, Any]) -> float:
    value = row.get("pct")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _accion(fase: str, *, valor: int, oferta: int | None, en_venta: bool, tiene_oferta: bool) -> tuple[str, str]:
    paga_valor = oferta is not None and valor > 0 and oferta >= valor
    if fase == FASE_APALANCAMIENTO:
        if paga_valor:
            return ACCION_VENDER, "La oferta ya paga el valor de mercado: no hace falta esperar al viernes."
        return ACCION_MANTENER, "Posición de trading. Sale al escaparate cuando falten 3 días."
    if fase == FASE_ESCAPARATE:
        if paga_valor:
            return ACCION_VENDER, "La oferta paga el valor de mercado."
        if not en_venta:
            return ACCION_ESCAPARATE, "Ponerlo a la venta hoy para tener oferta de LaLiga antes del cierre."
        return ACCION_ESPERAR, "Ya está en venta. La oferta se renueva cada día; se acepta la que pague el valor."
    if oferta is not None or tiene_oferta:
        return ACCION_VENDER, "Último día: se acepta la oferta que haya (como mucho un 10 % bajo el valor)."
    if not en_venta:
        return ACCION_ESCAPARATE, "Ponerlo a la venta ya. Sin oferta antes del saque, vender a un rival."
    return ACCION_SIN_OFERTA, "No hay oferta de LaLiga. Ofrecerlo a un rival antes del saque."


def plan_liquidacion(
    owned: list[dict[str, Any]],
    *,
    saldo: int | None,
    dias_para_jornada: float | None,
    ofertas: dict[str, int | None] | None = None,
    conservar: set[str] | None = None,
) -> dict[str, Any]:
    """Qué hacer con cada jugador del #12 en adelante según la fase de la semana.

    ``owned`` son las filas de la plantilla propia (``player_id``, ``position``,
    ``jornada``, ``elegible``, ``valor``, ``pct``, ``en_venta``,
    ``tiene_oferta_laliga``). ``ofertas`` da la mejor oferta conocida por
    jugador. ``conservar`` son jugadores fuera del once que se guardan a
    propósito (la cobertura de un dudoso del primer partido): no se venden.

    El saldo tras liquidar usa la oferta si se conoce y el valor si no; el
    peor caso usa la oferta o el 90 % del valor.
    """
    fase = fase_semana(dias_para_jornada)
    vacio: dict[str, Any] = {
        "activo": False,
        "fase": fase,
        "dias_para_jornada": dias_para_jornada,
        "once_ids": [],
        "sobrantes": [],
        "saldo": saldo,
        "saldo_tras_liquidar": saldo,
        "saldo_peor_caso": saldo,
        "deficit_eur": 0,
    }
    filas = [row for row in owned if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    if fase is None or not filas:
        return vacio
    elegibles = [
        {"player_id": row["player_id"], "position": row.get("position"), "jornada": float(row.get("jornada") or 0.0)}
        for row in filas
        if row.get("elegible") is not False
    ]
    xi = solve_best_xi(elegibles)
    once_ids = set(xi["player_ids"]) if xi.get("ok") else set()
    guardar = {str(item) for item in conservar or set()}
    known = ofertas or {}
    sobrantes: list[dict[str, Any]] = []
    for row in filas:
        player_id = row["player_id"]
        if player_id in once_ids:
            continue
        valor = _valor(row)
        oferta = _int(known.get(player_id))
        if player_id in guardar:
            accion, motivo = ACCION_MANTENER, "Cobertura del once: se guarda hasta ver la alineación oficial."
        else:
            accion, motivo = _accion(
                fase,
                valor=valor,
                oferta=oferta,
                en_venta=row.get("en_venta") is True,
                tiene_oferta=row.get("tiene_oferta_laliga") is True,
            )
        sobrantes.append(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "position": row.get("position"),
                "valor": valor or None,
                "oferta_eur": oferta,
                "pct": row.get("pct"),
                "elegible": row.get("elegible") is not False,
                "accion": accion,
                "motivo": motivo,
                "etiqueta": ETIQUETA_LIQUIDAR if fase == FASE_LIQUIDACION and accion == ACCION_VENDER else None,
            }
        )
    # Primero lo que baja y lo que no puede jugar; lo que sube, lo último.
    sobrantes.sort(key=lambda item: (item["elegible"], _pct(item), -(item["valor"] or 0)))
    # Proyección al cierre: todos los sobrantes vendidos, salvo la cobertura.
    vende = [item for item in sobrantes if item["player_id"] not in guardar]
    ingreso = sum(item["oferta_eur"] if item["oferta_eur"] is not None else (item["valor"] or 0) for item in vende)
    peor = sum(
        item["oferta_eur"] if item["oferta_eur"] is not None else int((item["valor"] or 0) * OFERTA_LALIGA_MIN)
        for item in vende
    )
    base = saldo if isinstance(saldo, int) and not isinstance(saldo, bool) else None
    tras = base + ingreso if base is not None else None
    peor_caso = base + peor if base is not None else None
    return {
        **vacio,
        "activo": True,
        "once_ids": sorted(once_ids),
        "once_completo": bool(xi.get("ok")),
        "sobrantes": sobrantes,
        "saldo_tras_liquidar": tras,
        "saldo_peor_caso": peor_caso,
        # Lo que falta para llegar a 0 aun vendiendo todos los sobrantes: habría
        # que vender del once.
        "deficit_eur": max(0, -peor_caso) if peor_caso is not None else 0,
    }

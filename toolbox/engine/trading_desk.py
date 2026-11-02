"""Trading desk: compras de lunes a viernes que no tocan el once.

Corre después del plan del once. Su capital es la caja que sobra tras el plan
más una parte del margen de deuda. Maximiza euros ganados de lunes a viernes,
no puntos ni porcentajes: con capital limitado es una mochila, no un ranking.

No sabe vender a LaLiga: la oferta llega cuando LaLiga quiere. Por eso solo usa
una fracción de la deuda y descuenta la fricción de la compra (prima pagada
por encima del valor de mercado).
"""

from __future__ import annotations

from typing import Any

import pulp

#: LaLiga permite endeudarse hasta el 20 % del valor del equipo.
DEUDA_PCT_EQUIPO = 0.20
#: Parte de ese margen que el trading usa. El resto cubre que la venta no llegue.
DEUDA_USO_MAX = 0.5
#: Días de lunes a viernes en los que se mantiene la posición.
DIAS_TRADING = 4.0
#: Ganancia esperada mínima para molestarse, en euros.
GANANCIA_MIN_EUR = 50_000
#: Con menos días la venta no llega a tiempo: no se propone.
DIAS_MINIMOS = 2.0
MAX_OPERACIONES = 6


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def capital_trading(saldo_sobrante: int, valor_equipo: int) -> dict[str, int]:
    """Caja libre más la deuda que el trading se atreve a usar."""
    deuda = int(max(0, valor_equipo) * DEUDA_PCT_EQUIPO * DEUDA_USO_MAX)
    return {
        "caja_libre": int(max(0, saldo_sobrante)),
        "deuda_usable": deuda,
        "capital": int(max(0, saldo_sobrante)) + deuda,
    }


def ganancia_esperada(valor: int, euros: int, pct: float, dias: float = DIAS_TRADING) -> int:
    """Euros esperados al vender: lo que sube hasta el viernes menos la prima pagada."""
    sube = valor * (pct / 100.0) * (dias / 7.0)
    prima = max(0, euros - valor)
    return int(round(sube - prima))


def build_trading_desk(
    candidatos: list[dict[str, Any]],
    *,
    saldo_sobrante: int | None,
    valor_equipo: int,
    dias_para_jornada: float | None,
) -> dict[str, Any]:
    """Elige las compras especulativas que maximizan euros dentro del capital.

    Cada candidato trae ``player_id``, ``nombre``, ``origen`` (bid/clause),
    ``euros`` (lo que sale de la caja), ``valor`` y ``pct`` (previsión a 7 días).
    """
    vacio: dict[str, Any] = {"activo": False, "operaciones": [], "capital": 0, "ganancia_esperada": 0}
    if saldo_sobrante is None or dias_para_jornada is None or dias_para_jornada < DIAS_MINIMOS:
        return vacio
    capital = capital_trading(saldo_sobrante, valor_equipo)
    dias = min(DIAS_TRADING, float(dias_para_jornada))
    filas: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for item in candidatos:
        euros = _num(item.get("euros"))
        valor = _num(item.get("valor")) or euros
        pct = _num(item.get("pct"))
        player_id = item.get("player_id")
        if not isinstance(player_id, str) or player_id in vistos or euros is None or euros <= 0 or pct is None:
            continue
        ganancia = ganancia_esperada(int(valor or 0), int(euros), pct, dias)
        if ganancia < GANANCIA_MIN_EUR:
            continue
        vistos.add(player_id)
        filas.append({**item, "euros": int(euros), "ganancia_esperada": ganancia})
    resultado = {**vacio, **capital, "activo": True}
    if not filas or capital["capital"] <= 0:
        return resultado
    problem = pulp.LpProblem("trading_desk", pulp.LpMaximize)
    elegir = [pulp.LpVariable(f"t{i}", cat=pulp.LpBinary) for i in range(len(filas))]
    problem += pulp.lpSum(fila["ganancia_esperada"] * var for fila, var in zip(filas, elegir))
    problem += pulp.lpSum(fila["euros"] * var for fila, var in zip(filas, elegir)) <= capital["capital"]
    problem += pulp.lpSum(elegir) <= MAX_OPERACIONES
    problem.solve(pulp.PULP_CBC_CMD(msg=False))
    elegidas = [fila for fila, var in zip(filas, elegir) if (var.value() or 0) > 0.5]
    elegidas.sort(key=lambda fila: fila["ganancia_esperada"], reverse=True)
    gasto = sum(fila["euros"] for fila in elegidas)
    resultado.update(
        {
            "operaciones": [
                {
                    "player_id": fila["player_id"],
                    "nombre": fila.get("nombre"),
                    "origen": fila.get("origen"),
                    "euros": fila["euros"],
                    "pct": fila.get("pct"),
                    "ganancia_esperada": fila["ganancia_esperada"],
                    "etiqueta": "COMPRAR PARA TRADING",
                    "cierre": "Vender el viernes por la mañana",
                }
                for fila in elegidas
            ],
            "gasto": gasto,
            "usa_deuda": max(0, gasto - capital["caja_libre"]),
            "ganancia_esperada": sum(fila["ganancia_esperada"] for fila in elegidas),
        }
    )
    return resultado

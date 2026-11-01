"""Plan de fichajes: once de más puntos con la caja que queda al final.

El solver junta ventas, pujas del mercado, cláusulas abiertas y, si faltan
al menos dos días para la jornada, como mucho un jugador aún por encontrar.
"""

from __future__ import annotations

from typing import Any

import pulp

from toolbox.analyzer import FORMATIONS, POSITIONS, XI_SIZE
from toolbox.engine.auction_intel import nota_y_veredicto
from toolbox.engine.lineup_math import solve_best_xi

# Un suplente buscado a ciegas rinde como un titular medio de esa posición.
BUSCA_PUNTOS = 4.7
# Por debajo de esto el once no cambia de verdad.
MEJORA_MINIMA = 0.1
_SEQ = 0


def _prefix() -> str:
    global _SEQ
    _SEQ += 1
    return f"p{_SEQ}"


def _vacio(cash: int | None, ratio: float, baseline: float) -> dict[str, Any]:
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
) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "momento": momento,
        "player_id": player_id,
        "nombre": nombre,
        "posicion": posicion,
        "jornada": jornada,
        "euros": euros,
        "detalle": detalle,
    }


def build_plan_fichajes(
    *,
    cash: int | None,
    owned: list[dict[str, Any]],
    mercado: list[dict[str, Any]],
    clausulas: list[dict[str, Any]],
    ratio: float,
    dias_para_jornada: float | None,
    baseline_puntos: float,
) -> dict[str, Any]:
    """Maximiza los puntos del once. No envía órdenes.

    ``owned`` puede venderse si trae ``venta_eur``. ``mercado`` se puja al
    coste ``euros``. ``clausulas`` igual, solo las que ya vienen filtradas
    como rentables. El sintético entra si ``dias_para_jornada >= 2``.
    """
    saldo = cash if isinstance(cash, int) and not isinstance(cash, bool) else None
    plantilla = [row for row in owned if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    compras = [row for row in mercado if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    raids = [row for row in clausulas if isinstance(row, dict) and isinstance(row.get("player_id"), str)]
    permite_busca = isinstance(dias_para_jornada, (int, float)) and not isinstance(dias_para_jornada, bool) and dias_para_jornada >= 2
    coste_busca = int(round(BUSCA_PUNTOS * ratio)) if ratio and ratio > 0 else 0
    if saldo is None:
        return _vacio(None, ratio, baseline_puntos)

    prefix = _prefix()
    problem = pulp.LpProblem(f"plan_{prefix}", pulp.LpMaximize)
    en_once: dict[str, pulp.LpVariable] = {}
    vende: dict[str, pulp.LpVariable] = {}
    puja: dict[str, pulp.LpVariable] = {}
    clausula: dict[str, pulp.LpVariable] = {}

    for index, row in enumerate(plantilla):
        player_id = row["player_id"]
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

    for index, row in enumerate(compras):
        if row.get("position") not in POSITIONS:
            continue
        euros = row.get("euros")
        if not isinstance(euros, int) or isinstance(euros, bool) or euros <= 0:
            continue
        variable = pulp.LpVariable(f"{prefix}_m{index}", cat=pulp.LpBinary)
        puja[row["player_id"]] = variable
        en_once[f"bid:{row['player_id']}"] = variable

    for index, row in enumerate(raids):
        if row.get("position") not in POSITIONS:
            continue
        euros = row.get("euros")
        if not isinstance(euros, int) or isinstance(euros, bool) or euros <= 0:
            continue
        variable = pulp.LpVariable(f"{prefix}_c{index}", cat=pulp.LpBinary)
        clausula[row["player_id"]] = variable
        en_once[f"clause:{row['player_id']}"] = variable

    busca = {
        position: pulp.LpVariable(f"{prefix}_b{position}", cat=pulp.LpBinary) for position in POSITIONS
    }
    if permite_busca and coste_busca > 0:
        problem += pulp.lpSum(busca.values()) <= 1
        # Con el once ya cerrado, solo se busca si una venta deja un hueco.
        elegibles = [
            row
            for row in plantilla
            if row.get("elegible") is not False and row.get("position") in POSITIONS
        ]
        if solve_best_xi(elegibles)["ok"]:
            if vende:
                problem += pulp.lpSum(busca.values()) <= pulp.lpSum(vende.values())
            else:
                for variable in busca.values():
                    problem += variable == 0
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

    ingresos = pulp.lpSum(
        int(row["venta_eur"]) * vende[row["player_id"]]
        for row in plantilla
        if row["player_id"] in vende and isinstance(row.get("venta_eur"), int)
    )
    gastos_puja = pulp.lpSum(int(row["euros"]) * puja[row["player_id"]] for row in compras if row["player_id"] in puja)
    gastos_clausula = pulp.lpSum(
        int(row["euros"]) * clausula[row["player_id"]] for row in raids if row["player_id"] in clausula
    )
    gastos_busca = pulp.lpSum(coste_busca * busca[position] for position in POSITIONS)
    problem += saldo + ingresos - gastos_puja - gastos_clausula - gastos_busca >= 0

    puntos = pulp.lpSum(float(row.get("jornada") or 0.0) * en_once[f"own:{row['player_id']}"] for row in plantilla)
    puntos += pulp.lpSum(float(row.get("jornada") or 0.0) * puja[row["player_id"]] for row in compras if row["player_id"] in puja)
    puntos += pulp.lpSum(
        float(row.get("jornada") or 0.0) * clausula[row["player_id"]] for row in raids if row["player_id"] in clausula
    )
    puntos += pulp.lpSum(BUSCA_PUNTOS * busca[position] for position in POSITIONS)
    # Vender o gastar sin subir el once no es un plan.
    problem += puntos - 0.0001 * pulp.lpSum(vende.values()) - 1e-12 * (gastos_puja + gastos_clausula + gastos_busca)

    status = problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=5))
    if pulp.LpStatus.get(status, "") != "Optimal":
        return _vacio(saldo, ratio, baseline_puntos)

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
    for row in plantilla:
        if row["player_id"] in vende and _on(vende[row["player_id"]]):
            euros = int(row["venta_eur"])
            ingreso += euros
            acciones.append(
                _accion(
                    "VENDE",
                    "hoy",
                    player_id=row["player_id"],
                    nombre=_nombre(row),
                    posicion=row.get("position"),
                    jornada=_jornada(row),
                    euros=euros,
                    detalle="Venta para financiar el once. Conviene hacerla hoy: la caja tiene que estar lista antes de pujar.",
                )
            )
    for row in compras:
        if row["player_id"] in puja and _on(puja[row["player_id"]]):
            euros = int(row["euros"])
            gasto += euros
            puntos_once += float(row.get("jornada") or 0.0)
            once.append(_ficha(row, "puja"))
            momento = "hoy" if row.get("caduca_hoy") is True else "luego"
            detalle = "Puja del mercado de LaLiga al precio recomendado."
            if momento == "hoy":
                detalle = "La puja de LaLiga caduca hoy. Si encaja, hay que entrarla antes del cierre."
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
                )
            )
    for row in raids:
        if row["player_id"] in clausula and _on(clausula[row["player_id"]]):
            euros = int(row["euros"])
            gasto += euros
            puntos_once += float(row.get("jornada") or 0.0)
            once.append(_ficha(row, "clausulazo"))
            acciones.append(
                _accion(
                    "CLAUSULAZO",
                    "luego",
                    player_id=row["player_id"],
                    nombre=_nombre(row),
                    posicion=row.get("position"),
                    jornada=_jornada(row),
                    euros=euros,
                    detalle="La cláusula está abierta y sus puntos por euro superan al mercado.",
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
                )
            )

    mejora = round(puntos_once - float(baseline_puntos), 2)
    if mejora < MEJORA_MINIMA:
        return _vacio(saldo, ratio, baseline_puntos)
    saldo_final = int(saldo + ingreso - gasto)
    nota, veredicto = nota_y_veredicto(mejora, acciones)
    orden = {"hoy": 0, "luego": 1}
    tipo_orden = {"VENDE": 0, "PUJA": 1, "CLAUSULAZO": 2, "BUSCA": 3}
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

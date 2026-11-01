"""Plan de fichajes: once de más puntos, sin vaciar la caja a ciegas.

El solver junta ventas, pujas, cláusulas y, si faltan al menos dos días, como
mucho un jugador aún por encontrar. El dinero que se gasta hoy no vuelve a
estar el jueves: la función objetivo resta el coste de oportunidad de esa
caja según los días que quedan hasta el inicio de la jornada.
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

    Con dos días o más, un fichaje marginal y caro va a ``en_radar``. Aceptar
    una venta hoy exige oferta firme de LaLiga: o el precio cae más de un 3 %,
    o la caja hace falta para un must-buy. Quien sería venta el viernes y aún
    sube se lista en ``ESCAPARATE`` y no se malvende. Un chollo de banquillo
    solo entra si quedan al menos dos días y sobra caja para el once.
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

    busca = {position: pulp.LpVariable(f"{prefix}_b{position}", cat=pulp.LpBinary) for position in POSITIONS}
    if permite_busca and coste_busca > 0:
        problem += pulp.lpSum(busca.values()) <= 1
        # Con el once ya cerrado, solo se busca si una venta deja un hueco.
        if actual["ok"]:
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
    # Sin oferta de LaLiga no se puede aceptar hoy, aunque el precio ya esté cayendo.
    if ventana:
        for player_id in list(vende):
            if not oferta_firme.get(player_id):
                problem += vende[player_id] == 0

    vende_libre = [
        player_id
        for player_id in vende
        if not ventana or (
            oferta_firme.get(player_id)
            and pct_propio.get(player_id) is not None
            and pct_propio[player_id] < UMBRAL_CAIDA_PCT
        )
    ]
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
    problem += (
        puntos
        + bonus
        - peaje
        - 0.0001 * pulp.lpSum(vende.values())
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
    for row in plantilla:
        if row["player_id"] in vende and _on(vende[row["player_id"]]):
            euros = int(row["venta_eur"])
            ingreso += euros
            pct = pct_propio.get(row["player_id"])
            if ventana and pct is not None and pct < UMBRAL_CAIDA_PCT:
                detalle = "Vender hoy: ya hay oferta de LaLiga y el precio cae más de un 3 % a siete días."
            elif ventana:
                detalle = "Vender hoy: ya hay oferta de LaLiga y hace falta esta caja para un must-buy que no cabe en el saldo."
            else:
                detalle = "Venta para financiar el once. Conviene hacerla hoy: la caja tiene que estar lista antes de pujar."
            acciones.append(
                _accion(
                    "VENDER HOY" if ventana else "VENDE",
                    "hoy",
                    player_id=row["player_id"],
                    nombre=_nombre(row),
                    posicion=row.get("position"),
                    jornada=_jornada(row),
                    euros=euros,
                    detalle=detalle,
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
    if mejora < MEJORA_MINIMA and not hay_urgente:
        vacio = _vacio(saldo, ratio, baseline_puntos, meta)
        vacio["en_radar"] = radar
        vacio["acciones"] = _escaparate(set())
        return vacio
    saldo_final = int(saldo + ingreso - gasto)
    nota, veredicto = nota_y_veredicto(mejora, acciones)
    if hay_urgente:
        veredicto = "Hazlo ya"
        nota = max(nota, 8)
    vendidos = {
        accion["player_id"]
        for accion in acciones
        if accion.get("tipo") in {"VENDE", "VENDER HOY"} and isinstance(accion.get("player_id"), str)
    }
    acciones.extend(_escaparate(vendidos))
    orden = {"hoy": 0, "luego": 1}
    tipo_orden = {"VENDER HOY": 0, "VENDE": 0, "ESCAPARATE": 1, "PUJA": 2, "CLAUSULAZO": 3, "BUSCA": 4}
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

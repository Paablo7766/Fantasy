"""Guardarraíl de ruina: ¿llego al cierre con saldo negativo y puntúo 0 la jornada?

Regla oficial: si al empezar el primer partido el saldo es negativo, la jornada
puntúa 0. El endeudamiento máximo es el 20 % del valor del equipo, y ese valor
se mueve cada día con los precios.

Este módulo es puro (sin red, sin caché): recibe caja, pujas vivas, historial
del valor de la plantilla y reloj, y devuelve el estado y qué hacer.

- ``saldo_peor = caja − Σ pujas vivas − ofertas de compra pendientes``. Se
  supone que ganas todas las pujas a la vez. No cuenta ningún ingreso incierto
  (ventas sin cerrar, ofertas recibidas sin aceptar).
- Colchón por caída de valor: valor estresado = valor − k·σ·√días, con σ la
  desviación típica del cambio diario del valor de la plantilla actual.
  El límite de deuda estresado es el 20 % de ese valor.
- Estados: OK, AVISO, PELIGRO, y SIN_ACTUALIZAR si la caja o los precios tienen
  más de 24 h (nunca se muestra OK con datos caducados).
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from toolbox.engine.lineup_math import solve_best_xi
from toolbox.engine.trading_desk import DEUDA_PCT_EQUIPO

#: z de la cola del 1 % (unilateral).
K_COLA = 2.33
#: Cambios diarios mínimos para fiarse de σ.
MIN_OBSERVACIONES_SIGMA = 4
#: Edad máxima de caja y precios para poder decir OK.
CADUCIDAD_SEGUNDOS = 24 * 3600
#: Con menos de este tiempo al cierre ya no hay margen para regularizar.
HORAS_PELIGRO = 24.0

OK = "OK"
AVISO = "AVISO"
PELIGRO = "PELIGRO"
SIN_ACTUALIZAR = "SIN_ACTUALIZAR"

_SEGUNDOS_DIA = 86400.0


def _entero(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return int(value)


def _dia_ordinal(dia: Any) -> int | None:
    from datetime import date

    if not isinstance(dia, str):
        return None
    try:
        return date.fromisoformat(dia[:10]).toordinal()
    except ValueError:
        return None


def _sigma_de_cambios(cambios: list[float], valor_actual: int, min_obs: int) -> dict[str, Any] | None:
    if len(cambios) < max(2, min_obs):
        return None
    media = sum(cambios) / len(cambios)
    varianza = sum((c - media) ** 2 for c in cambios) / (len(cambios) - 1)
    sigma = math.sqrt(varianza)
    return {
        "sigma_rel": sigma,
        "sigma_eur": int(round(sigma * valor_actual)),
        "observaciones": len(cambios),
        "valor_actual": int(valor_actual),
    }


def sigma_diaria(historia: list[dict[str, Any]] | None, *, min_obs: int = MIN_OBSERVACIONES_SIGMA) -> dict[str, Any] | None:
    """σ del cambio diario relativo de una serie de valor (``day``, ``value_eur``).

    Un hueco de ``n`` días se reparte como ``Δ/√n`` para no inflar σ. Sirve
    cuando la composición no cambia; con un histórico que se va llenando jugador
    a jugador usa ``sigma_cartera``. ``None`` si no hay ``min_obs`` cambios.
    """
    puntos: list[tuple[int, float]] = []
    for fila in historia or []:
        if not isinstance(fila, dict):
            continue
        ordinal = _dia_ordinal(fila.get("day"))
        valor = _entero(fila.get("value_eur"))
        if ordinal is not None and valor is not None and valor > 0:
            puntos.append((ordinal, float(valor)))
    puntos.sort()
    cambios: list[float] = []
    for (d0, v0), (d1, v1) in zip(puntos, puntos[1:]):
        huecos = d1 - d0
        if huecos > 0:
            cambios.append((v1 / v0 - 1.0) / math.sqrt(huecos))
    if not puntos:
        return None
    return _sigma_de_cambios(cambios, int(puntos[-1][1]), min_obs)


def sigma_cartera(
    historia: dict[str, list[dict[str, Any]]] | None,
    ids: list[str],
    *,
    min_cobertura: float = 0.6,
    min_obs: int = MIN_OBSERVACIONES_SIGMA,
) -> dict[str, Any] | None:
    """σ del cambio diario del valor de la plantilla ``ids``, sin saltos de composición.

    El histórico de precios no cubre a todos los jugadores desde el mismo día:
    sumar valores día a día mete saltos que no son movimiento de precios. Aquí
    solo cuentan los cambios de un mismo jugador entre dos fotos suyas, repartidos
    por √huecos, agregados por día de cierre y ponderados por valor. Un día entra
    si al menos ``min_cobertura`` de la plantilla tiene cambio ese día.
    """
    if not ids or not isinstance(historia, dict):
        return None
    por_dia: dict[int, list[tuple[float, float]]] = {}
    ultimo_valor = 0
    for pid in ids:
        puntos: list[tuple[int, float]] = []
        for fila in historia.get(pid) or []:
            if not isinstance(fila, dict):
                continue
            ordinal = _dia_ordinal(fila.get("day"))
            valor = _entero(fila.get("market_value"))
            if ordinal is not None and valor is not None and valor > 0:
                puntos.append((ordinal, float(valor)))
        puntos.sort()
        if puntos:
            ultimo_valor += int(puntos[-1][1])
        for (d0, v0), (d1, v1) in zip(puntos, puntos[1:]):
            huecos = d1 - d0
            if huecos > 0:
                por_dia.setdefault(d1, []).append(((v1 - v0) / math.sqrt(huecos), v0))
    cambios: list[float] = []
    for dia in sorted(por_dia):
        pares = por_dia[dia]
        if len(pares) / len(ids) < min_cobertura:
            continue
        base = sum(v0 for _delta, v0 in pares)
        if base > 0:
            cambios.append(sum(delta for delta, _v0 in pares) / base)
    return _sigma_de_cambios(cambios, ultimo_valor, min_obs)


def valor_estresado(valor: int, sigma_rel: float | None, dias: float, *, k: float = K_COLA) -> int:
    """Valor de la plantilla en la cola del 1 % a ``dias`` días vista."""
    if valor <= 0:
        return 0
    if sigma_rel is None:
        return int(valor)
    caida = k * sigma_rel * math.sqrt(max(0.0, dias))
    return int(round(valor * max(0.0, 1.0 - caida)))


def _edad_legible(segundos: float) -> str:
    horas = segundos / 3600
    return f"{horas:.0f} h" if horas < 48 else f"{horas / 24:.0f} días"


def evaluar(
    *,
    caja: int | None,
    pujas_vivas: list[dict[str, Any]] | None,
    valor_equipo: int | None,
    sigma: dict[str, Any] | None,
    dias_al_cierre: float | None,
    edad_caja_s: float | None,
    edad_precios_s: float | None,
    ofertas_compra_pendientes: int = 0,
    pujas_conocidas: bool = True,
) -> dict[str, Any]:
    """Estado del guardarraíl. Todos los importes en euros enteros.

    ``pujas_vivas`` es ``None`` cuando la foto no trae el mercado: entonces no
    se sabe cuánto hay comprometido y no puede salir OK.
    """
    pujas = [p for p in (pujas_vivas or []) if isinstance(p, dict) and (_entero(p.get("euros")) or 0) > 0]
    total_pujas = sum(int(p["euros"]) for p in pujas)
    razones: list[str] = []

    if caja is None:
        return {
            "estado": SIN_ACTUALIZAR,
            "razones": ["Sin caja en la foto: no se puede calcular el saldo."],
            "caja": None,
            "pujas_vivas": pujas,
            "total_pujas_vivas": total_pujas,
            "saldo_peor": None,
            "margen_eur": None,
            "datos_caducados": True,
        }

    saldo_peor = int(caja) - total_pujas - int(ofertas_compra_pendientes)
    valor = int(valor_equipo) if isinstance(valor_equipo, int) and valor_equipo > 0 else 0
    sigma_rel = sigma["sigma_rel"] if isinstance(sigma, dict) else None
    dias_stress = dias_al_cierre if isinstance(dias_al_cierre, (int, float)) and dias_al_cierre >= 0 else 7.0
    estresado = valor_estresado(valor, sigma_rel, dias_stress)
    limite_normal = int(valor * DEUDA_PCT_EQUIPO)
    limite_estresado = int(estresado * DEUDA_PCT_EQUIPO)
    horas = None if not isinstance(dias_al_cierre, (int, float)) else max(0.0, float(dias_al_cierre) * 24.0)

    caducado = False
    for etiqueta, edad in (("caja", edad_caja_s), ("precios", edad_precios_s)):
        if edad is None or edad > CADUCIDAD_SEGUNDOS:
            caducado = True
            if edad is None:
                razones.append(f"Datos de {etiqueta} sin edad conocida.")
            elif etiqueta == "precios":
                # No es la edad del mercado (esa va en la cabecera): es la última
                # foto del histórico con el que se mide la caída de valor.
                razones.append(f"El histórico de precios no guarda fotos desde hace {_edad_legible(edad)}.")
            else:
                razones.append(f"Datos de {etiqueta} de hace {_edad_legible(edad)}.")
    if not pujas_conocidas:
        caducado = True
        razones.append("La foto no trae el mercado: no sé qué pujas tienes vivas.")
    if sigma_rel is None:
        caducado = True
        razones.append("Sin histórico de precios suficiente para medir la caída de valor.")
    if valor <= 0:
        caducado = True
        razones.append("Sin valor de equipo en la foto: no se conoce el límite de deuda.")

    margen_estresado = saldo_peor + limite_estresado  # >= 0: cabe en el límite incluso con la caída
    caja_negativa = int(caja) < 0
    cierre_cerca = horas is not None and horas < HORAS_PELIGRO

    if saldo_peor >= 0:
        estado = OK
    elif saldo_peor < -limite_estresado:
        estado = PELIGRO
        razones.append(
            f"El peor caso ({saldo_peor / 1e6:.1f} M€) supera la deuda permitida con el valor estresado "
            f"({limite_estresado / 1e6:.1f} M€)."
        )
    elif caja_negativa and cierre_cerca:
        estado = PELIGRO
        razones.append("Saldo real negativo a menos de 24 h del cierre.")
    elif cierre_cerca:
        estado = PELIGRO
        razones.append("Quedan menos de 24 h y las pujas vivas te dejarían en negativo.")
    else:
        estado = AVISO
        razones.append("Si ganas todas las pujas quedas en negativo, dentro del límite. Hay que regularizar antes del saque.")

    if caducado and estado == OK:
        estado = SIN_ACTUALIZAR

    return {
        "estado": estado,
        "razones": razones,
        "caja": int(caja),
        "pujas_vivas": pujas,
        "total_pujas_vivas": total_pujas,
        "ofertas_compra_pendientes": int(ofertas_compra_pendientes),
        "saldo_peor": saldo_peor,
        "valor_equipo": valor,
        "sigma_diaria_rel": sigma_rel,
        "sigma_diaria_eur": sigma["sigma_eur"] if isinstance(sigma, dict) else None,
        "observaciones_sigma": sigma["observaciones"] if isinstance(sigma, dict) else 0,
        "k": K_COLA,
        "dias_al_cierre": None if dias_al_cierre is None else round(float(dias_al_cierre), 3),
        "valor_estresado": estresado,
        "limite_deuda": limite_normal,
        "limite_deuda_estresado": limite_estresado,
        # Euros que sobran (+) o faltan (−) para quedar dentro del límite estresado.
        "margen_eur": margen_estresado,
        # Euros que faltan para llegar a saldo_peor ≥ 0.
        "falta_eur": max(0, -saldo_peor),
        "edad_caja_s": edad_caja_s,
        "edad_precios_s": edad_precios_s,
        "datos_caducados": caducado,
    }


def _xi_puntos(jugadores: list[dict[str, Any]]) -> float:
    resultado = solve_best_xi(jugadores)
    return float(resultado["puntos"]) if resultado.get("ok") else 0.0


def plan_cobertura(
    *,
    falta_eur: int,
    pujas: list[dict[str, Any]],
    plantilla: list[dict[str, Any]],
    max_acciones: int = 3,
    pool_ventas: int = 14,
) -> dict[str, Any]:
    """Qué retirar o vender para cubrir ``falta_eur`` al menor coste en xP del once.

    ``pujas``: ``player_id``, ``nombre``, ``position``, ``jornada`` (xP del
    objetivo), ``euros``. ``plantilla``: filas propias con ``venta_eur``, el
    precio realizable (oferta con importe, o 90 % del valor), no el de mercado.
    El coste real se mide re-resolviendo el once con y sin lo retirado; la
    búsqueda exacta cubre hasta ``max_acciones`` movimientos.
    """
    if falta_eur <= 0:
        return {"falta_eur": 0, "cubre": True, "acciones": [], "coste_xp": 0.0}
    mundo: dict[str, dict[str, Any]] = {}
    for fila in plantilla:
        if isinstance(fila.get("player_id"), str):
            mundo[fila["player_id"]] = fila
    for puja in pujas:
        if isinstance(puja.get("player_id"), str) and puja["player_id"] not in mundo:
            mundo[puja["player_id"]] = puja
    base = _xi_puntos(list(mundo.values()))

    opciones: list[dict[str, Any]] = []
    for puja in pujas:
        euros = _entero(puja.get("euros"))
        if euros and euros > 0 and isinstance(puja.get("player_id"), str):
            opciones.append({"tipo": "RETIRAR_PUJA", "player_id": puja["player_id"], "nombre": puja.get("nombre"), "euros": euros})
    en_puja = {o["player_id"] for o in opciones}
    for fila in plantilla:
        venta = _entero(fila.get("venta_eur"))
        if venta and venta > 0 and fila.get("player_id") not in en_puja:
            opciones.append({"tipo": "VENDER", "player_id": fila["player_id"], "nombre": fila.get("nombre"), "euros": venta})

    def coste(ids: set[str]) -> float:
        resto = [fila for pid, fila in mundo.items() if pid not in ids]
        return max(0.0, base - _xi_puntos(resto))

    for opcion in opciones:
        opcion["coste_xp_solo"] = round(coste({opcion["player_id"]}), 3)
    ventas = sorted(
        (o for o in opciones if o["tipo"] == "VENDER"),
        key=lambda o: (o["coste_xp_solo"] / o["euros"], o["player_id"]),
    )[:pool_ventas]
    pool = [o for o in opciones if o["tipo"] == "RETIRAR_PUJA"] + ventas

    mejor: tuple[float, int, int, tuple[dict[str, Any], ...]] | None = None
    for n in range(1, max(1, max_acciones) + 1):
        for combo in itertools.combinations(pool, n):
            suma = sum(o["euros"] for o in combo)
            if suma < falta_eur:
                continue
            clave = (round(coste({o["player_id"] for o in combo}), 6), n, suma)
            if mejor is None or clave < mejor[:3]:
                mejor = (*clave, combo)
    if mejor is not None:
        elegidas = list(mejor[3])
        cubre = True
    else:
        # Ningún conjunto pequeño llega: avanza por eficiencia hasta cubrir lo que se pueda.
        elegidas = []
        suma = 0
        for o in sorted(pool, key=lambda o: (o["coste_xp_solo"] / o["euros"], o["player_id"])):
            if suma >= falta_eur:
                break
            elegidas.append(o)
            suma += o["euros"]
        cubre = suma >= falta_eur
    coste_total = round(coste({o["player_id"] for o in elegidas}), 3) if elegidas else 0.0
    return {
        "falta_eur": int(falta_eur),
        "cubre": cubre,
        "acciones": [dict(o) for o in elegidas],
        "euros_cubiertos": sum(o["euros"] for o in elegidas),
        "coste_xp": coste_total,
        "xp_once_sin_cambios": round(base, 3),
        "nota": (
            "Las ventas van al precio realizable (oferta con importe o 90 % del valor), "
            "no al de mercado. El coste en xP se mide re-resolviendo el once."
        ),
    }


def evaluar_plan(
    base: dict[str, Any],
    acciones: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Estado si además se ejecutan las compras del plan del optimizador.

    Suma pujas y cláusulas del plan al peor caso (sin contar sus ventas, que
    son ingresos inciertos). Una puja del plan sobre un jugador que ya tienes
    pujado sustituye a la viva, no se suma dos veces.
    """
    if not isinstance(base, dict) or base.get("saldo_peor") is None:
        return None
    vivas = {p["player_id"]: int(p["euros"]) for p in base.get("pujas_vivas") or [] if isinstance(p.get("player_id"), str)}
    extra = 0
    for accion in acciones or []:
        if not isinstance(accion, dict):
            continue
        # Una puja cuenta por la cifra que se escribe (``puja_final``), no por la base del solver.
        euros = (_entero(accion.get("puja_final")) if accion.get("tipo") == "PUJA" else None) or _entero(accion.get("euros"))
        if not euros or euros <= 0:
            continue
        if accion.get("tipo") == "PUJA":
            extra += max(0, euros - vivas.get(str(accion.get("player_id")), 0))
        elif accion.get("tipo") == "CLAUSULAZO":
            extra += euros
    saldo = int(base["saldo_peor"]) - extra
    limite = int(base.get("limite_deuda_estresado") or 0)
    horas = None if base.get("dias_al_cierre") is None else float(base["dias_al_cierre"]) * 24.0
    if saldo >= 0:
        estado = OK
    elif saldo < -limite or (horas is not None and horas < HORAS_PELIGRO):
        estado = PELIGRO
    else:
        estado = AVISO
    if base.get("datos_caducados") and estado == OK:
        estado = SIN_ACTUALIZAR
    return {
        "estado": estado,
        "saldo_peor": saldo,
        "margen_eur": saldo + limite,
        "gasto_plan_adicional": extra,
        "descartar": estado == PELIGRO,
    }

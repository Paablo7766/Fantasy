"""Pujas, rivales obligados a vender y, si la liga lo tiene, los dos capitanes."""

from __future__ import annotations

import math
import zlib
from typing import Any

from toolbox.engine.market_predictor import PASO_PRECIO
from toolbox.engine.reglamento import CAPITAN_ACTIVO

# La Pizarra puja un 4,7 % por encima del valor.
# El techo ya no es un +25 % fijo: prima de oportunidad, previsión a 7 días
# y dificultad del partido, con un cap absoluto del +30 % para la liquidez.
PRIMA_PUJA = 1.047
MULTIPLICADOR_BASE = 1.15
PESO_REVALORIZACION = 0.55
BONO_PARTIDO_FACIL = 0.02
BONO_PARTIDO_DIFICIL = -0.01
CAP_LIQUIDEZ = 1.30
_DIFICULTAD_FACIL = {"facil", "muy_facil", "easy", "very_easy"}
_DIFICULTAD_DIFICIL = {"dificil", "muy_dificil", "hard", "very_hard"}
# Por encima del rival con más caja que necesita el puesto.
MARGEN_RIVAL_EUR = 100_000
# Una proyección de +5 % en siete días ya es una subida alta.
PREVISION_ALTA_PCT = 5.0
# Por encima de esto, vender al titular duele de verdad.
UMBRAL_WAR_OFERTA = 1.5
# Titularidad mínima del capitán seguro.
TITULAR_SEGURO = 0.80
# Anti-Pizarra: con demanda alta pujamos por encima del escalón redondo de La Pizarra.
PASO_PIZARRA_EUR = 100_000
UMBRAL_NOTA_DEMANDA = 8.0
UMBRAL_PREVISION_DEMANDA = 15.0
# Puja competitiva de liga: cuánto más que nuestra cifra pagó, de media, quien nos
# ganó las subastas. Con pocas pérdidas la media bruta se encoge hacia un prior
# (5 %, como cuatro subastas imaginarias) y nunca pasa del 20 %: con n pequeño un
# solo rival que pagó de más (+48 %) no puede fijar la regla de la liga.
SOBREPUJA_PRIOR = 0.05
SOBREPUJA_PESO_PRIOR = 4.0
SOBREPUJA_MAX = 0.20
# Frente 20: por encima de +10 % sobre el valor la prima se pierde al revender
# (−0,85 M€ en +10..25 %, −2,94 M€ por encima de +25 %). Mide euros de reventa, no
# subastas ganadas ni puntos: vale de techo para lo que se compra sin mejorar el
# once. Los objetivos del plan usan ``puja_por_valor`` (auditoría 14-nov-2026).
TECHO_SOBREPUJA = 0.10
# Curva de la liga: parte de las compras al cierre que habrías superado con cada
# prima sobre el valor del día. Medida el 14-nov-2026 con 83 compras; se usa
# mientras la base local no tenga ``MIN_MUESTRA_CURVA`` compras propias.
CURVA_PRIMAS_PRIOR: tuple[tuple[float, float], ...] = (
    (0.00, 0.29), (0.02, 0.34), (0.05, 0.37), (0.10, 0.47), (0.15, 0.60), (0.20, 0.63),
    (0.30, 0.72), (0.40, 0.72), (0.50, 0.76), (0.75, 0.81), (1.00, 0.87),
)
MIN_MUESTRA_CURVA = 30
PRIMA_MAX_POR_VALOR = 1.0
# La curva de cada jugador: liga → tramo de valor → si su valor sube hoy → si ya
# tiene pujas. Cada nivel se mezcla con el de arriba con este peso en compras
# imaginarias: con 10 compras propias un segmento pesa 10/(10+20).
PESO_PRIOR_SEGMENTO = 20.0
# Curvas por tramo medidas el 14-nov-2026 (n compras, puntos). Entre 1 y 5 M€ la
# mediana ganadora fue +50,7 %; por encima de 5 M€, +9,5 %.
CURVAS_TRAMO_PRIOR: dict[str, tuple[int, tuple[tuple[float, float], ...]]] = {
    "<1M": (19, ((0.00, 0.37), (0.02, 0.37), (0.05, 0.37), (0.10, 0.42), (0.15, 0.42), (0.20, 0.47),
                 (0.30, 0.58), (0.40, 0.58), (0.50, 0.63), (0.75, 0.63), (1.00, 0.63))),
    "1-5M": (21, ((0.00, 0.24), (0.02, 0.29), (0.05, 0.38), (0.10, 0.38), (0.15, 0.48), (0.20, 0.48),
                  (0.30, 0.48), (0.40, 0.48), (0.50, 0.48), (0.75, 0.67), (1.00, 0.81))),
    ">=5M": (43, ((0.00, 0.28), (0.02, 0.35), (0.05, 0.37), (0.10, 0.53), (0.15, 0.74), (0.20, 0.77),
                  (0.30, 0.91), (0.40, 0.91), (0.50, 0.95), (0.75, 0.95), (1.00, 1.00))),
}
# Un parche por debajo de esto, y solo si tapa un once que si no hace 0, puede saltarse el techo.
PARCHE_SUPERVIVENCIA_EUR = 1_500_000
# Entre 140.000 y 220.000 €, en pasos de 10.000, sin múltiplos de 50.000.
DIFERENCIALES_EUR = tuple(v for v in range(140_000, 220_001, 10_000) if v % 50_000 != 0)


# Cola anti-picos. floren romi (.004/.005), Naviis10 y pablooceballos (.001/.010)
# ganan subastas pujando 1-10 EUR por encima de un numero redondo. La API acepta
# cualquier importe en euros, asi que nuestra cifra lleva una cola no redonda de
# varios miles de euros: barre cualquier +1 / +10 sobre el escalon redondo.
COLA_MIN_EUR = 1_111
COLA_MAX_EUR = 9_899


def techo_sobrepuja_eur(valor: int | float, *, supervivencia: bool = False) -> float | None:
    """Tope en euros de la puja. ``None`` solo en el parche de supervivencia barato."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor <= 0:
        return None
    if supervivencia and float(valor) < PARCHE_SUPERVIVENCIA_EUR:
        return None
    return float(valor) * (1.0 + TECHO_SOBREPUJA)


def cola_anti_picos(clave: Any) -> int:
    """Cola en euros, estable por jugador, nunca terminada en 0 (ni multiplo de 100)."""
    semilla = zlib.crc32(f"cola|{clave}".encode("utf-8"))
    cola = COLA_MIN_EUR + semilla % (COLA_MAX_EUR - COLA_MIN_EUR + 1)
    if cola % 10 == 0:
        cola += 3
    if cola % 100 == 0:
        cola += 7
    return min(cola, COLA_MAX_EUR)


def con_cola_anti_picos(
    puja: Any,
    *,
    clave: Any,
    techo: Any = None,
    saldo: Any = None,
) -> Any:
    """``puja`` mas la cola, sin pasar nunca del techo dinamico ni del presupuesto.

    Si la puja ya llega al techo o al presupuesto no hay hueco para la cola y se
    devuelve igual. Una cifra que ya trae cola (no termina en 0) tampoco se toca.
    """
    if isinstance(puja, bool) or not isinstance(puja, (int, float)) or puja <= 0:
        return puja
    if int(puja) % 10 != 0:
        return puja
    cola = cola_anti_picos(clave)
    objetivo = int(puja) + cola
    for tope in (techo, saldo):
        if isinstance(tope, bool) or not isinstance(tope, (int, float)):
            continue
        if tope <= puja:
            return puja
        objetivo = min(objetivo, int(tope))
    # La cola tiene que seguir dentro del techo: un tope redondo no puede
    # dejar la cifra terminada en .000 ni en .001–.010.
    terminacion = objetivo % 1000
    if terminacion == 0 or terminacion <= 10:
        hueco = 11 - terminacion if terminacion <= 10 else 11
        if objetivo - hueco > int(puja):
            objetivo -= hueco
    return int(objetivo)


def _paso(valor: float, paso: int = PASO_PRECIO) -> int:
    if paso <= 0:
        return int(round(valor))
    return int(round(valor / paso)) * paso


def _clave_dificultad(dificultad: str | None) -> str:
    if not isinstance(dificultad, str):
        return ""
    return (
        dificultad.strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace(" ", "_")
        .replace("-", "_")
    )


def prevision_a_puntos(value: Any) -> float:
    """``+23,2%`` o ``23.2`` → 23.2. Sin dato, 0."""
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else 0.0
    if isinstance(value, str):
        text = value.strip().replace("%", "").replace(",", ".")
        if not text:
            return 0.0
        try:
            number = float(text)
        except ValueError:
            return 0.0
        return number if math.isfinite(number) else 0.0
    return 0.0


def prima_quemada_mercado(puja: Any, valor: Any, prevision_7d_pct: Any = None) -> float:
    """Euros que no vuelven al pujar por encima del valor de mercado.

    ``max(0, puja − valor − subida_7d)``. La subida prevista a 7 días descuenta
    el sobreprecio; una bajada lo agranda. Sin valor de mercado no se puede
    medir y la prima queda en cero, igual que en un clausulazo sin valor.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor <= 0:
        return 0.0
    if isinstance(puja, bool) or not isinstance(puja, (int, float)) or puja <= 0:
        return 0.0
    subida = float(valor) * (prevision_a_puntos(prevision_7d_pct) / 100.0)
    return max(0.0, float(puja) - float(valor) - subida)


def bono_dificultad(dificultad: str | None) -> float:
    """Fácil suma 2 puntos al multiplicador. Difícil resta 1. El resto, nada."""
    clave = _clave_dificultad(dificultad)
    if clave in _DIFICULTAD_FACIL:
        return BONO_PARTIDO_FACIL
    if clave in _DIFICULTAD_DIFICIL:
        return BONO_PARTIDO_DIFICIL
    return 0.0


def multiplicador_puja(prevision_7d_pct: Any = None, dificultad: str | None = None) -> float:
    """``1,15 + 0,55·(previsión/100) + bono de partido``, nunca por encima de 1,30.

    Una subida del +23,2 % a 7 días aporta ``0,55 × 0,232 ≈ 0,127``: el techo
    sube ~12,7 puntos porque el mercado devuelve esa prima solo.
    """
    bono_revalorizacion = PESO_REVALORIZACION * (prevision_a_puntos(prevision_7d_pct) / 100.0)
    crudo = MULTIPLICADOR_BASE + bono_revalorizacion + bono_dificultad(dificultad)
    if crudo < 0:
        return 0.0
    return min(CAP_LIQUIDEZ, crudo)


def techo_puja_dinamico(
    valor_mercado: int | float,
    prevision_7d_pct: Any = None,
    dificultad: str | None = None,
    *,
    paso: int = PASO_PRECIO,
) -> int:
    """``valor × multiplicador``, redondeado al paso de precio y capado al +30 %."""
    if isinstance(valor_mercado, bool) or not isinstance(valor_mercado, (int, float)) or valor_mercado <= 0:
        return 0
    return _paso(float(valor_mercado) * multiplicador_puja(prevision_7d_pct, dificultad), paso)


def calcular_pujas(
    valor_actual: int | float,
    delta_hoy: int | float,
    valor_justo: int | float,
    *,
    tu_saldo: int | float | None,
    rivales: list[dict[str, Any]],
    posicion: str | None,
    prevision_7d_pct: Any = None,
    dificultad: str | None = None,
    clave: Any = None,
    supervivencia: bool = False,
) -> dict[str, int | None]:
    """Puja recomendada, techo dinámico y puja que deja atrás al rival.

    ``puja_recomendada`` y ``puja_smart`` llevan la cola anti-picos
    (``con_cola_anti_picos``) con ``clave`` (id del jugador; si falta, el valor).

    ``puja_recomendada`` es el valor por 1,047 más la subida de hoy, si la hay.
    ``puja_maxima`` es el techo dinámico (previsión a 7 días y dificultad),
    con cap absoluto del +30 %. ``valor_justo`` se conserva en la firma para
    quien ya lo calculaba; ya no recorta el techo.
    ``puja_smart`` suma 0,1 M€ al rival interesado con más saldo cuando todos
    los que necesitan el puesto tienen menos caja que tú, y nunca supera el techo.
    """
    del valor_justo
    vacio = {"puja_recomendada": None, "puja_maxima": None, "puja_smart": None}
    if isinstance(valor_actual, bool) or not isinstance(valor_actual, (int, float)) or valor_actual <= 0:
        return vacio
    valor = float(valor_actual)
    subida = float(delta_hoy) if isinstance(delta_hoy, (int, float)) and not isinstance(delta_hoy, bool) else 0.0
    if subida < 0:
        subida = 0.0
    recomendada = _paso(valor * PRIMA_PUJA + subida)
    maxima = techo_puja_dinamico(valor, prevision_7d_pct, dificultad)
    if maxima <= 0:
        maxima = None
    techo_duro = techo_sobrepuja_eur(valor, supervivencia=supervivencia)
    if techo_duro is not None:
        recomendada = min(recomendada, techo_duro)

    saldo = None
    if isinstance(tu_saldo, (int, float)) and not isinstance(tu_saldo, bool):
        saldo = float(tu_saldo)

    interesados: list[float] = []
    puesto = posicion if isinstance(posicion, str) else ""
    for rival in rivales:
        if not isinstance(rival, dict):
            continue
        puestos = rival.get("posiciones")
        if not isinstance(puestos, (list, set, tuple)) or puesto not in puestos:
            continue
        caja = rival.get("saldo")
        if isinstance(caja, bool) or not isinstance(caja, (int, float)):
            continue
        if float(caja) > 0:
            interesados.append(float(caja))

    base = recomendada
    if maxima is not None:
        base = min(base, maxima)
    if saldo is not None and interesados and all(caja < saldo for caja in interesados):
        objetivo = max(interesados) + MARGEN_RIVAL_EUR
        smart = max(base, _paso(objetivo))
        if maxima is not None:
            smart = min(smart, maxima)
    else:
        smart = base
    if saldo is not None:
        smart = min(float(smart), saldo)
        smart = math.floor(smart / PASO_PRECIO) * PASO_PRECIO
    if smart <= 0:
        smart_out: int | None = None
    else:
        smart_out = int(smart)

    cola_clave = clave if clave is not None else valor_actual
    techo_cola = maxima
    if techo_duro is not None:
        techo_cola = techo_duro if maxima is None else min(float(maxima), techo_duro)
    recomendada_out = con_cola_anti_picos(recomendada, clave=cola_clave, techo=techo_cola, saldo=saldo)
    smart_cola = con_cola_anti_picos(smart_out, clave=cola_clave, techo=techo_cola, saldo=saldo)
    return {
        "puja_recomendada": recomendada_out if recomendada > 0 else None,
        "puja_maxima": maxima,
        "puja_smart": smart_cola,
    }


def puja_pizarra(valor_actual: Any, delta_hoy: Any = 0) -> int | None:
    """La cifra redonda que copia quien usa La Pizarra: valor × 1,047 + subida, a 0,1 M€."""
    if isinstance(valor_actual, bool) or not isinstance(valor_actual, (int, float)) or valor_actual <= 0:
        return None
    subida = float(delta_hoy) if isinstance(delta_hoy, (int, float)) and not isinstance(delta_hoy, bool) else 0.0
    base = float(valor_actual) * PRIMA_PUJA + max(0.0, subida)
    redondeada = int(round(base / PASO_PIZARRA_EUR)) * PASO_PIZARRA_EUR
    return redondeada if redondeada > 0 else None


def diferencial_asimetrico(clave: Any) -> int:
    """Entre 140.000 y 220.000 €, estable por jugador y nunca múltiplo de 50.000.

    Una cifra que acaba en ``…640.000`` o ``…650.000`` es la que teclean los demás;
    esta no. Con la misma clave sale lo mismo en cada refresco.
    """
    semilla = zlib.crc32(str(clave).encode("utf-8"))
    return DIFERENCIALES_EUR[semilla % len(DIFERENCIALES_EUR)]


def alta_demanda(nota_mercado: Any, prevision_7d_pct: Any) -> bool:
    nota = nota_mercado if isinstance(nota_mercado, (int, float)) and not isinstance(nota_mercado, bool) else None
    if nota is not None and float(nota) >= UMBRAL_NOTA_DEMANDA:
        return True
    return prevision_a_puntos(prevision_7d_pct) > UMBRAL_PREVISION_DEMANDA


def puja_anti_pizarra(
    valor_actual: Any,
    delta_hoy: Any = 0,
    *,
    nota_mercado: Any = None,
    prevision_7d_pct: Any = None,
    clave: Any = None,
    maxima: int | None = None,
    saldo: int | float | None = None,
) -> dict[str, Any]:
    """Escalón de La Pizarra y, si el jugador está caliente, nuestra puja por encima.

    Solo se activa con ``nota_mercado >= 8`` o previsión a 7 días > 15 %. El
    diferencial no redondo gana los empates a quien puja la cifra de La Pizarra.
    Nunca pasa del techo dinámico ni de la caja; si no cabe, no se activa.
    """
    pizarra = puja_pizarra(valor_actual, delta_hoy)
    salida: dict[str, Any] = {
        "puja_pizarra": pizarra,
        "puja_anti_pizarra": None,
        "diferencial_anti_pizarra_eur": 0,
        "alta_demanda": alta_demanda(nota_mercado, prevision_7d_pct),
    }
    if pizarra is None or not salida["alta_demanda"]:
        return salida
    diferencial = diferencial_asimetrico(clave if clave is not None else valor_actual)
    objetivo = pizarra + diferencial
    if isinstance(maxima, int) and not isinstance(maxima, bool) and maxima > 0:
        objetivo = min(objetivo, maxima)
    if isinstance(saldo, (int, float)) and not isinstance(saldo, bool):
        objetivo = min(objetivo, int(math.floor(float(saldo) / PASO_PRECIO)) * PASO_PRECIO)
    objetivo = int(math.floor(objetivo / PASO_PRECIO)) * PASO_PRECIO
    if objetivo <= pizarra:
        return salida
    objetivo = con_cola_anti_picos(
        objetivo,
        clave=clave if clave is not None else valor_actual,
        techo=maxima if isinstance(maxima, int) and not isinstance(maxima, bool) and maxima > 0 else None,
        saldo=saldo,
    )
    salida["puja_anti_pizarra"] = objetivo
    salida["diferencial_anti_pizarra_eur"] = objetivo - pizarra
    return salida


def estimar_sobrepuja_liga(perdidas: list[tuple[Any, Any]]) -> dict[str, Any]:
    """Sobrepuja que hay que añadir a nuestra cifra, según las subastas que perdimos.

    ``perdidas`` son pares ``(nuestra cifra, lo que pagó el ganador)``. Solo
    cuentan como evidencia las pérdidas en las que el ganador pagó **más** que
    nosotros: si pagó lo mismo o menos, la cifra no fue la causa (no se pujó, o
    hubo empate) y meterlas como un 0 % diluiría la señal sin que lo sea.

    Devuelve ``estimada`` (``None`` sin ninguna pérdida con sobrepuja) ya
    encogida hacia el prior y con tope, y los números crudos para auditarla.
    """
    validas = 0
    excesos: list[float] = []
    for nuestra, pagado in perdidas:
        if isinstance(nuestra, bool) or isinstance(pagado, bool):
            continue
        if not isinstance(nuestra, (int, float)) or not isinstance(pagado, (int, float)):
            continue
        if nuestra <= 0 or pagado <= 0:
            continue
        validas += 1
        exceso = float(pagado) / float(nuestra) - 1.0
        if exceso > 0:
            excesos.append(exceso)
    estimada: float | None = None
    media: float | None = None
    if excesos:
        media = sum(excesos) / len(excesos)
        encogida = (sum(excesos) + SOBREPUJA_PRIOR * SOBREPUJA_PESO_PRIOR) / (len(excesos) + SOBREPUJA_PESO_PRIOR)
        estimada = round(min(SOBREPUJA_MAX, max(0.0, encogida)), 4)
    return {
        "perdidas": validas,
        "con_sobrepuja": len(excesos),
        "media_exceso": None if media is None else round(media, 4),
        "estimada": estimada,
        "tope": SOBREPUJA_MAX,
    }


def puja_competitiva_liga(
    base: Any,
    maxima: Any,
    sobrepuja: Any,
    *,
    margen: Any = None,
    clave: Any = None,
    techo_absoluto: Any = None,
) -> int | None:
    """Escalón por encima de nuestra cifra que cubre lo que suele pagar la liga.

    ``base * (1 + sobrepuja)``, nunca por encima del techo dinámico (``maxima``,
    el techo de rentabilidad) ni de ``base + margen`` si se conoce el margen de
    caja. Sin techo, sin evidencia o sin escalón libre por encima de la base no
    hay puja competitiva.
    """
    if any(isinstance(valor, bool) for valor in (base, maxima, sobrepuja)):
        return None
    if not isinstance(base, (int, float)) or base <= 0:
        return None
    if not isinstance(maxima, (int, float)) or maxima <= 0:
        return None
    if not isinstance(sobrepuja, (int, float)) or sobrepuja <= 0:
        return None
    objetivo = min(float(base) * (1.0 + float(sobrepuja)), float(maxima))
    if isinstance(margen, (int, float)) and not isinstance(margen, bool):
        objetivo = min(objetivo, float(base) + max(0.0, float(margen)))
    if isinstance(techo_absoluto, (int, float)) and not isinstance(techo_absoluto, bool) and techo_absoluto > 0:
        objetivo = min(objetivo, float(techo_absoluto))
    # El epsilon evita que 10 M€ × 1,13 = 11 299 999,999… caiga un escalón entero.
    objetivo = int(math.floor(objetivo / PASO_PRECIO + 1e-9)) * PASO_PRECIO
    if objetivo <= base:
        return None
    techo = float(maxima)
    if isinstance(margen, (int, float)) and not isinstance(margen, bool):
        techo = min(techo, float(base) + max(0.0, float(margen)))
    if isinstance(techo_absoluto, (int, float)) and not isinstance(techo_absoluto, bool) and techo_absoluto > 0:
        techo = min(techo, float(techo_absoluto))
    return con_cola_anti_picos(objetivo, clave=clave if clave is not None else base, techo=techo)


def capitanes(
    xi: list[dict[str, Any]],
    *,
    activo: bool | None = None,
) -> dict[str, dict[str, Any] | None]:
    """Capitán seguro (jornada, titularidad alta) y capitán de techo.

    Con el capitán apagado no hay nadie que doblar: las dos fichas salen vacías
    y el once se valora por los puntos de cada titular, sin x2.
    """
    if not (CAPITAN_ACTIVO if activo is None else activo):
        return {"capitan_seguro": None, "capitan_remontada": None}
    filas = [row for row in xi if isinstance(row, dict)]

    def ficha(row: dict[str, Any], criterio: str) -> dict[str, Any]:
        return {
            "player_id": row.get("player_id"),
            "nombre": row.get("nombre") or row.get("nickname") or row.get("name") or row.get("player_id"),
            "posicion": row.get("position"),
            "jornada": row.get("jornada"),
            "si_titular": row.get("si_titular"),
            "techo": row.get("techo"),
            "p_titular": row.get("p_titular"),
            "criterio": criterio,
        }

    seguros = [
        row
        for row in filas
        if isinstance(row.get("p_titular"), (int, float))
        and not isinstance(row.get("p_titular"), bool)
        and float(row["p_titular"]) >= TITULAR_SEGURO
        and isinstance(row.get("jornada"), (int, float))
        and not isinstance(row.get("jornada"), bool)
    ]
    seguro = max(seguros, key=lambda row: (float(row["jornada"]), float(row["p_titular"]), str(row.get("nombre") or ""))) if seguros else None
    techos = [
        row
        for row in filas
        if isinstance(row.get("techo"), (int, float))
        and not isinstance(row.get("techo"), bool)
        and float(row["techo"]) > 0
    ]
    remontada = max(techos, key=lambda row: (float(row["techo"]), float(row.get("jornada") or 0.0), str(row.get("nombre") or ""))) if techos else None
    return {
        "capitan_seguro": ficha(seguro, "jornada") if seguro is not None else None,
        "capitan_remontada": ficha(remontada, "techo") if remontada is not None else None,
    }


def nota_y_veredicto(mejora: float, acciones: list[dict[str, Any]]) -> tuple[int, str]:
    """Nota 0-10 y veredicto a partir de los puntos que gana el once.

    Por debajo de 0,4 es opcional. Desde 0,4, recomendable. A partir de 1,5
    —o de 0,8 si hay que actuar hoy— es para hacerlo ya. La nota sube unos
    4 puntos por cada punto esperado de mejora, con suelo según el veredicto.
    """
    if mejora <= 0 or not acciones:
        return 0, "Opcional"
    hay_hoy = any(accion.get("momento") == "hoy" for accion in acciones)
    if mejora >= 1.5 or (hay_hoy and mejora >= 0.8):
        veredicto = "Hazlo ya"
        suelo = 8
    elif mejora >= 0.4:
        veredicto = "Recomendable"
        suelo = 5
    else:
        veredicto = "Opcional"
        suelo = 0
    nota = int(round(mejora * 4))
    nota = max(suelo, min(10, nota))
    return nota, veredicto


def curva_primas(primas: list[float]) -> tuple[tuple[float, float], ...] | None:
    """Curva empírica (prima, parte de compras con prima <= esa) en los puntos de la prior.

    Primas negativas (el valor del día ya había cambiado) cuentan como 0.
    Con menos de ``MIN_MUESTRA_CURVA`` compras devuelve ``None``.
    """
    datos = sorted(max(0.0, float(x)) for x in primas if isinstance(x, (int, float)) and not isinstance(x, bool))
    if len(datos) < MIN_MUESTRA_CURVA:
        return None
    n = len(datos)
    return tuple((prima, round(sum(1 for x in datos if x <= prima + 1e-9) / n, 4)) for prima, _ in CURVA_PRIMAS_PRIOR)


def tramo_valor(valor: float) -> str:
    if valor < 1_000_000:
        return "<1M"
    if valor < 5_000_000:
        return "1-5M"
    return ">=5M"


def _cdf(primas: list[float]) -> tuple[tuple[float, float], ...]:
    n = len(primas)
    return tuple((x, sum(1 for p in primas if p <= x + 1e-9) / n) for x, _ in CURVA_PRIMAS_PRIOR)


def _mezcla(
    segmento: tuple[tuple[float, float], ...], n: int, padre: tuple[tuple[float, float], ...]
) -> tuple[tuple[float, float], ...]:
    peso = n / (n + PESO_PRIOR_SEGMENTO)
    return tuple(
        (x, round(peso * ps + (1.0 - peso) * pp, 4)) for (x, ps), (_, pp) in zip(segmento, padre)
    )


def curva_para_jugador(
    muestras: list[dict[str, Any]] | None,
    *,
    valor: float,
    subiendo: bool | None = None,
    pujas: int | None = None,
) -> tuple[tuple[tuple[float, float], ...], dict[str, Any]]:
    """Curva de ganar para este jugador, no la de toda la liga.

    ``muestras``: compras al cierre con ``prima``, ``valor``, ``subiendo`` y
    ``pujas`` (las pujas que tenía el anuncio, si se conocen). Cada segmento
    (tramo de valor → sube hoy → con o sin pujas) se mezcla con el de arriba
    según su muestra. Sin muestras, la curva medida el 14-nov y la de su tramo.
    """
    tramo = tramo_valor(float(valor))
    etiquetas = [tramo]
    datos = [m for m in muestras or [] if isinstance(m, dict) and isinstance(m.get("prima"), (int, float))]
    if len(datos) < MIN_MUESTRA_CURVA:
        n, puntos = CURVAS_TRAMO_PRIOR[tramo]
        return _mezcla(puntos, n, CURVA_PRIMAS_PRIOR), {"segmento": tramo, "muestra": n, "fuente": "prior_14nov"}
    curva = _cdf([float(m["prima"]) for m in datos])
    segmento = [m for m in datos if isinstance(m.get("valor"), (int, float)) and tramo_valor(float(m["valor"])) == tramo]
    n = len(segmento)
    if segmento:
        curva = _mezcla(_cdf([float(m["prima"]) for m in segmento]), n, curva)
    if subiendo is not None and segmento:
        segmento = [m for m in segmento if m.get("subiendo") is subiendo]
        etiquetas.append("sube hoy" if subiendo else "no sube hoy")
        n = len(segmento)
        if segmento:
            curva = _mezcla(_cdf([float(m["prima"]) for m in segmento]), n, curva)
    if pujas is not None and segmento:
        con = pujas > 0
        segmento = [m for m in segmento if isinstance(m.get("pujas"), int) and (m["pujas"] > 0) == con]
        etiquetas.append("con pujas" if con else "sin pujas")
        n = len(segmento)
        if segmento:
            curva = _mezcla(_cdf([float(m["prima"]) for m in segmento]), n, curva)
    return curva, {"segmento": " · ".join(etiquetas), "muestra": n, "fuente": "liga"}


def prob_ganar_prima(prima: float, curva: tuple[tuple[float, float], ...] | None = None) -> float:
    """Probabilidad de ganar la subasta pujando ``valor × (1 + prima)``, interpolada en la curva."""
    puntos = curva or CURVA_PRIMAS_PRIOR
    if prima <= puntos[0][0]:
        return puntos[0][1]
    for (x0, p0), (x1, p1) in zip(puntos, puntos[1:]):
        if prima <= x1:
            return p0 + (p1 - p0) * (prima - x0) / (x1 - x0)
    return puntos[-1][1]


def puja_por_valor(
    valor: Any,
    ganancia_eur: Any,
    *,
    tope_eur: Any = None,
    curva: tuple[tuple[float, float], ...] | None = None,
    clave: Any = None,
) -> dict[str, Any] | None:
    """La puja que maximiza P(ganar) × (lo que vale para tu once − la prima perdida).

    ``ganancia_eur`` es la mejora del once en euros (xP × ratio de mercado). La
    prima sobre el valor se da por perdida al revender (Frente 20). ``tope_eur``
    es lo que el plan puede poner (caja, holgura y crédito). Sin ganancia no hay
    cifra: el jugador no mejora el once y manda el techo fijo.
    """
    if any(isinstance(v, bool) for v in (valor, ganancia_eur, tope_eur)):
        return None
    if not isinstance(valor, (int, float)) or valor <= 0:
        return None
    if not isinstance(ganancia_eur, (int, float)) or ganancia_eur <= 0:
        return None
    tope = float(tope_eur) if isinstance(tope_eur, (int, float)) and tope_eur > 0 else None
    mejor: tuple[float, float, float] | None = None
    for paso in range(int(PRIMA_MAX_POR_VALOR * 100) + 1):
        prima = paso / 100.0
        cifra = float(valor) * (1.0 + prima)
        if tope is not None and cifra > tope:
            break
        p = prob_ganar_prima(prima, curva)
        esperado = p * (float(ganancia_eur) - (cifra - float(valor)))
        if mejor is None or esperado > mejor[2] + 1e-6:
            mejor = (prima, p, esperado)
    if mejor is None:
        return None
    prima, p, esperado = mejor
    cifra = max(int(valor), _paso(float(valor) * (1.0 + prima)))
    if tope is not None:
        cifra = min(cifra, int(tope))
    return {
        "puja": con_cola_anti_picos(cifra, clave=clave if clave is not None else valor, techo=tope),
        "prima": prima,
        "p_ganar": round(p, 4),
        "valor_esperado_eur": int(round(esperado)),
    }

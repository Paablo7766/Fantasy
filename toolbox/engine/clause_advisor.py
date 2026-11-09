"""Asesor de cláusulas: a quién te pueden clausular y a quién clausular tú.

Dos informes que salen de la foto que ya tiene el tablero, sin red:

* ``proteger``: tus jugadores con una cláusula que algún rival puede pagar hoy.
  Calcula la cláusula «perfecta» (la que deja fuera a todos los rivales con caja),
  lo que cuesta subirla (relación 1:2 del reglamento) y si compensa.
* ``clausulazos``: jugadores rivales a los que merece la pena pagar la cláusula,
  con cuánto mejoran tu once, cuándo se pueden pagar y quién más puede llevárselos.

Solo recomienda: pagar o subir una cláusula no se envía.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from toolbox.engine.lineup_math import solve_best_xi
from toolbox.engine.signing_plan import conserva_esqueleto
from toolbox.normalize import parse_clause_lock

_MADRID = ZoneInfo("Europe/Madrid")

#: Suelo de cláusula de la app: nadie puede bajarla de aquí.
CLAUSULA_MINIMA = 1_000_000
#: La cláusula está «en peligro» si no pasa de 1,25 veces el valor (misma regla que el tablero).
MULTIPLO_EN_PELIGRO = 1.25
#: Un rival no paga una cláusula que pase de 2,5 veces lo que vale el jugador: la regla de oro
#: ya llama chollo a hasta 2,2×, así que por encima nadie la compra.
MULTIPLO_CREIBLE = 2.5
#: Proteger no puede costar más que volver a comprar al jugador: tope de coste = valor de mercado.
MULTIPLO_COSTE_MAX = 1.0
#: Un suplente que no pasa de estos puntos de jornada no merece caja: se vende, no se protege.
PIERDE_PRESCINDIBLE = 1.0
#: Con sustituto comprable hoy solo se pierde el hueco de una jornada, no los puntos enteros.
FRACCION_HUECO_REPONIBLE = 0.25
#: Presupuesto máximo para reponer a un jugador barato: nadie gasta 24 M en sustituir a quien vale 1,5 M.
MULTIPLO_PRESUPUESTO_CLAUSULA = 2.5
MULTIPLO_PRESUPUESTO_VALOR = 4.0
#: La jornada arranca el viernes a las 21:00 (Madrid) cuando no hay hora de saque en los datos.
INICIO_JORNADA_DIA = 4
INICIO_JORNADA_HORA = 21
#: Margen sobre la caja del rival para que no le llegue por poco.
MARGEN_MIN_EUR = 250_000
MARGEN_PCT = 0.02
#: Mejora mínima del once para que un clausulazo cuente como jugada deportiva.
MEJORA_MINIMA = 0.5
#: Ventaja de valor justo sobre la cláusula para considerarlo jugada de valor.
MARGEN_VALOR_PCT = 25.0
MAX_CLAUSULAZOS = 10
#: Jueves y viernes: cuando queda un día o menos, el rival ya no puede rehacer su once.
DIAS_GOLPE_RIVAL = 1.0
#: Solo duele a quien pelea contigo por la liga.
TOP_RIVALES_GOLPE = 5
#: Menos de 11 sanos en plantilla obliga a alinear un hueco que puntúa 0.
TITULARES_MINIMOS = 11
MENSAJE_GOLPE_RIVAL = "Golpe al rival: lo dejas sin recambio en su once"
MAX_NIVELES = 4
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

#: Título del aviso cuando perder al jugador deja la plantilla sin once legal.
TITULO_SIN_RECAMBIO = "ALERTA: SIN RECAMBIO"

TITULOS_PROTEGER = {
    "PROTEGER_YA": "SUBE LA CLÁUSULA",
    "PROTEGER_PARCIAL": "SUBE UN POCO",
    "SIN_CAJA": "NO TE LLEGA LA CAJA",
    "VENDER_ANTES": "VENDE ANTES",
    "ASUMIR": "PUEDES ASUMIRLO",
    "SOBREPROTEGIDO": "YA ESTÁ BLINDADA",
    "SIN_RECAMBIO": TITULO_SIN_RECAMBIO,
}
TITULOS_CLAUSULAZO = {
    "CLAUSULAR_YA": "CLAUSULA YA",
    "PROGRAMAR": "PROGRAMA",
    "SIN_CAJA": "TE FALTA CAJA",
    "OPORTUNIDAD": "OPORTUNIDAD DE VALOR",
    "GOLPE_RIVAL": "GOLPE AL RIVAL",
}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(round(number))


def _m(value: float) -> str:
    return f"{value / 1_000_000:.1f}".replace(".", ",") + "M"


def _pts(value: float) -> str:
    return f"{abs(value):.1f}".replace(".", ",")


def coste_subida(actual: int, objetivo: int) -> int:
    """Subir 2 € de cláusula cuesta 1 €, redondeando al alza."""
    if objetivo <= actual:
        return 0
    return (objetivo - actual + 1) // 2


def _margen(caja: int) -> int:
    return max(MARGEN_MIN_EUR, int(round(caja * MARGEN_PCT)))


def _estado_lock(lock: Any, ahora: datetime) -> tuple[bool | None, datetime | None]:
    """(bloqueada, momento en que se desbloquea). ``None`` si no hay dato fiable."""
    if not isinstance(lock, dict):
        return None, None
    expira = lock.get("expires_at")
    if isinstance(expira, str) and expira.strip():
        leido = parse_clause_lock(expira, now=ahora)
        epoch = leido.get("epoch_ms")
        if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
            momento = datetime.fromtimestamp(epoch / 1000.0, tz=timezone.utc)
            return momento > ahora, momento
    marca = lock.get("is_locked")
    if marca is False:
        return False, None
    if marca is True:
        return True, None
    return None, None


def inicio_jornada_estimado(ahora: datetime) -> datetime:
    """Próximo viernes a las 21:00 de Madrid (en UTC): suposición cuando los datos no traen el saque."""
    local = ahora.astimezone(_MADRID)
    dias = (INICIO_JORNADA_DIA - local.weekday()) % 7
    candidato = (local + timedelta(days=dias)).replace(hour=INICIO_JORNADA_HORA, minute=0, second=0, microsecond=0)
    if candidato <= local:
        candidato += timedelta(days=7)
    return candidato.astimezone(timezone.utc)


def _cuando(momento: datetime | None, ahora: datetime) -> str:
    """«hoy 14:20», «mañana 10:15» o «jueves 13 nov 10:15» en hora de Madrid.

    Más allá de mañana siempre lleva el día del mes: un candado puede vencer dentro de
    dos semanas y «el lunes» a secas haría pensar en el próximo.
    """
    if momento is None:
        return "sin hora"
    local = momento.astimezone(_MADRID)
    hoy = ahora.astimezone(_MADRID).date()
    hora = local.strftime("%H:%M")
    if local.date() == hoy:
        return f"hoy {hora}"
    if local.date() == hoy + timedelta(days=1):
        return f"mañana {hora}"
    return f"{_DIAS[local.weekday()]} {local.day} {_MESES[local.month - 1]} {hora}"


def _niveles(
    clausula: int,
    capacidades: list[tuple[int, str | None]],
    saldo: int | None,
    tope: int | None = None,
    coste_max: int | None = None,
) -> list[dict[str, Any]]:
    """Cláusulas objetivo, de la más segura a la más barata.

    El nivel ``i`` deja sin cubrir a los ``i`` rivales con más caja. Cubrir a
    todos exige superar la caja del más rico más un margen, pero nunca más de
    ``tope`` (lo máximo que alguien pagaría por el jugador): subir más no protege
    nada y solo cuesta caja. Un nivel que cuesta más que ``coste_max`` (lo que vale
    volver a comprar al jugador) tampoco se ofrece.
    """
    ordenadas = sorted((caja for caja, _ in capacidades), reverse=True)
    niveles: list[dict[str, Any]] = []
    for sin_cubrir in range(0, min(len(ordenadas), MAX_NIVELES)):
        objetivo = ordenadas[sin_cubrir] + _margen(ordenadas[sin_cubrir])
        if tope is not None:
            objetivo = min(objetivo, tope)
        recortado = tope is not None and objetivo >= tope
        if objetivo <= clausula:
            continue
        # Varios escalones pueden colapsar en el mismo tope: se ofrece una sola vez.
        if any(nivel["clausula_objetivo"] == int(objetivo) for nivel in niveles):
            continue
        coste = coste_subida(clausula, objetivo)
        if coste_max is not None and coste > coste_max:
            continue
        niveles.append(
            {
                "clausula_objetivo": int(objetivo),
                "recortado_por_tope": bool(recortado),
                # Rivales a los que la cláusula REAL ya no les llega (no los que «deberían» quedar fuera).
                "rivales_fuera": sum(1 for caja in ordenadas if caja < objetivo),
                "subida_eur": int(objetivo - clausula),
                "coste_eur": int(coste),
                "caja_tras": None if saldo is None else int(saldo - coste),
                "rivales_cubiertos": len(ordenadas) - sin_cubrir,
                "rivales_sin_cubrir": sin_cubrir,
                "viable": saldo is not None and saldo - coste >= 0,
            }
        )
    return niveles


def _fecha_corta(momento: datetime) -> str:
    """``15-nov`` en hora de Madrid."""
    local = momento.astimezone(_MADRID)
    return f"{local.day}-{_MESES[local.month - 1]}"


def deja_sin_once(jugador: dict[str, Any], propios: list[dict[str, Any]]) -> bool:
    """Sin él (y sin fichar a nadie), la plantilla no puede alinear un once legal."""
    player_id = jugador.get("player_id")
    if not isinstance(player_id, str):
        return False
    plantilla = [
        {**fila, "elegible": fila.get("elegible") is not False}
        for fila in propios
        if isinstance(fila.get("player_id"), str) and fila.get("position")
    ]
    return not conserva_esqueleto(plantilla, {player_id})


def _recambio_barato(posicion: Any, alternativas: list[dict[str, Any]] | None, excluir: str) -> dict[str, Any] | None:
    """El fichaje más barato de esa posición que se puede pujar.

    Es un seguro para tener once legal, no un titular: manda el precio. A igual
    precio, el que más puntos da.
    """
    pool = [
        fila
        for fila in alternativas or []
        if fila.get("position") == posicion
        and fila.get("player_id") != excluir
        and fila.get("via", "puja") == "puja"
        and (_int(fila.get("coste")) or 0) > 0
    ]
    if not pool:
        return None
    return min(pool, key=lambda fila: (_int(fila.get("coste")) or 0, -(_num(fila.get("xp")) or 0.0)))


def _proteger(
    propios: list[dict[str, Any]],
    rivales: list[dict[str, Any]],
    *,
    saldo: int | None,
    ratio: float,
    ahora: datetime,
    cierre: datetime | None,
    alternativas: list[dict[str, Any]] | None = None,
    inicio_jornada: datetime | None = None,
) -> tuple[list[dict[str, Any]], int, int, list[dict[str, Any]]]:
    filas: list[dict[str, Any]] = []
    # Con candado toda la jornada: no hay riesgo hoy, pero se calcula la cláusula para dejarla puesta antes.
    preparar: list[dict[str, Any]] = []
    bloqueadas = 0
    seguros = 0
    con_caja = [rival for rival in rivales if _int(rival.get("saldo")) is not None and int(rival["saldo"]) > 0]
    sin_dato = len(rivales) - len([rival for rival in rivales if _int(rival.get("saldo")) is not None])
    # La caja es una sola: se protege primero a quien más daño hace perder y se descuenta lo gastado.
    restante = saldo

    def _prioridad(jugador: dict[str, Any]) -> float:
        valor_ = _int(jugador.get("valor")) or 0
        clausula_ = _int(jugador.get("clausula")) or 0
        daño = _num(jugador.get("tu_once_pierde_sin_el")) or 0.0
        xp_ = _num(jugador.get("jornada"))
        if xp_ is not None and xp_ > 0:
            daño = min(daño, xp_)
        return -(daño * ratio + max(0, valor_ - clausula_))

    for jugador in sorted(propios, key=_prioridad):
        clausula = _int(jugador.get("clausula"))
        valor = _int(jugador.get("valor"))
        if clausula is None or clausula <= 0 or jugador.get("blindado") is True or not isinstance(jugador.get("player_id"), str):
            continue
        bloqueada, desbloqueo = _estado_lock(jugador.get("bloqueo"), ahora)
        # Un candado que vence antes de que empiece la jornada deja al jugador expuesto esta jornada.
        # El mercado de clausulazos cierra 24 h antes del saque: lo que se desbloquea
        # después ya no se puede pagar antes de esta jornada. Sin ese dato, el saque.
        limite = cierre if cierre is not None else inicio_jornada
        candado = bloqueada is True and (limite is None or desbloqueo is None or desbloqueo >= limite)
        if candado:
            bloqueadas += 1
        justo = _int(jugador.get("valor_justo"))
        # Lo que paga un rival se ancla al valor de mercado. El valor justo del modelo
        # (xP × ratio) solo sirve cuando no hay valor, porque puede ser varias veces el precio.
        referencia = valor if valor else (justo or 0)
        creible = referencia > 0 and clausula <= referencia * MULTIPLO_CREIBLE
        capaces = (
            [(int(rival["saldo"]), rival) for rival in con_caja if int(rival["saldo"]) >= clausula] if creible else []
        )
        multiplo = clausula / valor if valor else None
        fragil = multiplo is not None and multiplo <= MULTIPLO_EN_PELIGRO
        if not capaces and not (fragil and creible) and not candado:
            seguros += 1
            continue
        posicion = jugador.get("position")
        pierde = _num(jugador.get("tu_once_pierde_sin_el")) or 0.0
        # Sin recambio en plantilla el WAR cuenta la jornada entera (todo el once). Aquí el daño
        # real es lo que él puntúa: el hueco se tapa con un fichaje, no se pierde todo el once.
        xp_propio = _num(jugador.get("jornada"))
        if xp_propio is not None and xp_propio > 0:
            pierde = min(pierde, xp_propio)
        en_xi = jugador.get("en_xi") is True
        # Quien no entra en el once y apenas puntúa no merece caja: vender gana al blindaje.
        prescindible = not en_xi and pierde < PIERDE_PRESCINDIBLE
        necesitan = [rival for _, rival in capaces if posicion in (rival.get("posiciones") or [])]
        capacidades = [(caja, str(rival.get("manager") or "Rival")) for caja, rival in capaces]
        tope = int(referencia * MULTIPLO_CREIBLE) if referencia > 0 else None
        coste_max = int(referencia * MULTIPLO_COSTE_MAX) if referencia > 0 else None
        niveles = _niveles(clausula, capacidades, restante, tope, coste_max) if capaces else []
        caja_antes = restante

        # Daño si te lo clausulan: los puntos que pierde tu once pagados a precio de mercado
        # y, si la cláusula está por debajo de su valor, lo que dejas de cobrar.
        regalo = max(0, (valor or 0) - clausula)
        # Con alternativas, el daño se mide en euros reales: lo que cuesta volver a tener sus puntos
        # menos lo que cobras por la cláusula, más el hueco de una jornada. Sin ellas, el modelo antiguo.
        reposicion: int | None = None
        hay_sustituto: bool | None = None
        falta_xp = 0.0
        if alternativas is not None and valor:
            reposicion, hay_sustituto, falta_xp = buscar_sustituto(jugador, alternativas, valor, clausula)
        if reposicion is not None:
            factor = FRACCION_HUECO_REPONIBLE if hay_sustituto else 1.0
            # Hueco: la fracción de jornada sin él más los puntos que el sustituto pagable no cubre.
            hueco = (pierde * factor + falta_xp) * ratio
            # Lo que cobras por la cláusula paga el sustituto: solo cuenta lo que no cubre.
            exposicion = max(0.0, reposicion - clausula + hueco)
        else:
            exposicion = pierde * ratio + regalo
        neto_cero = reposicion is not None and exposicion <= 0 and bool(capaces) and not prescindible
        elegido: dict[str, Any] | None = None
        mejor_neto = 0.0
        for nivel in () if (prescindible or neto_cero) else niveles:
            total = nivel["rivales_cubiertos"] + nivel["rivales_sin_cubrir"]
            cubierto = nivel["rivales_cubiertos"] / total if total else 0.0
            neto = exposicion * cubierto - nivel["coste_eur"]
            if nivel["viable"] and neto > mejor_neto:
                mejor_neto = neto
                elegido = nivel
        # Si te lo clausulan te quedas sin once legal: el cálculo en euros no mide ese daño,
        # así que en ese caso la cláusula perfecta se ofrece aunque el neto en euros salga a cero.
        sin_once_legal = bool(capaces) and fragil and deja_sin_once(jugador, propios)
        perfecta = None if (neto_cero and not sin_once_legal) else (niveles[0] if niveles else None)
        if elegido is not None and restante is not None and not candado:
            restante -= int(elegido["coste_eur"])

        if not capaces or neto_cero:
            riesgo = "BAJO"
        elif en_xi or pierde >= 1.0:
            riesgo = "ALTO"
        else:
            riesgo = "MEDIO"

        if neto_cero:
            codigo = "SOBREPROTEGIDO"
        elif prescindible and capaces and regalo > 0:
            codigo = "VENDER_ANTES"
        elif elegido is not None and elegido["rivales_sin_cubrir"] == 0:
            codigo = "PROTEGER_YA"
        elif elegido is not None:
            codigo = "PROTEGER_PARCIAL"
        elif perfecta is not None and not perfecta["viable"] and exposicion > perfecta["coste_eur"]:
            codigo = "SIN_CAJA"
        elif regalo > 0 and pierde < 1.8:
            codigo = "VENDER_ANTES"
        else:
            codigo = "ASUMIR"

        # Posición crítica: si te lo roban no puedes alinear once legal (0 puntos la jornada entera).
        # Cobrar la cláusula no lo arregla si el robo llega tarde: el recambio tiene que estar antes.
        sin_recambio = deja_sin_once(jugador, propios)
        abre = desbloqueo if bloqueada is True and desbloqueo is not None else (None if candado else ahora)
        alerta_prioritaria = bool(sin_recambio and capaces and not candado and fragil)
        recambio = _recambio_barato(posicion, alternativas, jugador["player_id"]) if alerta_prioritaria else None
        accion_prioritaria: str | None = None
        if alerta_prioritaria:
            codigo = "SIN_RECAMBIO"
            riesgo = "ALTO"
            futura = abre is not None and abre > ahora
            cuando_abre = f"se abre el {_fecha_corta(abre)}" if futura else "ya está abierta"
            caja_rica, rival_rico = max(capaces, key=lambda item: item[0])
            multiplo_txt = f"{multiplo:.2f}".replace(".", ",") if multiplo is not None else "?"
            partes = [
                f"Es tu único {posicion} posible: si te lo clausulan te quedas sin once legal y la jornada vale 0 puntos.",
                f"Su cláusula ({_m(clausula)}, {multiplo_txt}× su valor) {cuando_abre} "
                f"y {rival_rico.get('manager') or 'un rival'} tiene {_m(caja_rica)}.",
            ]
            if recambio is not None:
                fecha = f"antes del {_fecha_corta(abre)}" if futura else "hoy"
                partes.append(
                    f"Ficha {fecha} un {posicion} de recambio ({recambio.get('nombre') or 'el más barato'}, "
                    f"{_m(_int(recambio.get('coste')) or 0)}): asegura el once legal y la puja se puede pagar con crédito, la cláusula no."
                )
            else:
                partes.append("No hay recambio en el mercado ahora: revisa el mercado cada día hasta tener otro.")
            if elegido is not None:
                partes.append(f"Si te sobra caja, sube la cláusula: cuesta {_m(int(elegido['coste_eur']))}.")
            accion_prioritaria = " ".join(partes)

        motivos: list[str] = []
        if alerta_prioritaria:
            motivos.append(
                f"sin recambio en su puesto · se abre el {_fecha_corta(abre)}"
                if abre is not None and abre > ahora
                else "sin recambio en su puesto · cláusula abierta"
            )
        if capaces:
            motivos.append(f"{len(capaces)} de {len(rivales)} rivales pueden pagar su cláusula hoy")
        if necesitan:
            motivos.append("necesitan un " + str(posicion) + ": " + ", ".join(str(r.get("manager") or "Rival") for r in necesitan[:2]))
        if fragil:
            motivos.append(f"cláusula de solo {multiplo:.2f}× su valor".replace(".", ","))
        if sin_dato:
            motivos.append(f"{sin_dato} rivales sin caja conocida")
        if desbloqueo is not None and bloqueada is True:
            motivos.append(f"se desbloquea {_cuando(desbloqueo, ahora)}")

        nombre = str(jugador.get("nombre") or jugador["player_id"])
        motivo = accion_prioritaria or _motivo_proteger(
            codigo,
            nombre=nombre,
            clausula=clausula,
            valor=valor,
            elegido=elegido,
            perfecta=perfecta,
            pierde=pierde,
            capaces=capaces,
            saldo=caja_antes,
            en_xi=en_xi,
            reposicion=reposicion,
        )
        expuesta_desde = desbloqueo if bloqueada is True and desbloqueo is not None else None
        if expuesta_desde is not None and not accion_prioritaria:
            motivo += f" Su candado vence {_cuando(expuesta_desde, ahora)}, antes de que empiece la jornada: queda expuesto entonces."
        if candado and desbloqueo is not None:
            motivo += f" Tiene candado hasta {_cuando(desbloqueo, ahora)}: déjala puesta al menos un día antes."
        (preparar if candado else filas).append(
            {
                "en_candado": candado,
                "player_id": jugador["player_id"],
                "nombre": nombre,
                "posicion": posicion,
                "en_xi": en_xi,
                "xp_jornada": _num(jugador.get("jornada")),
                "tu_once_pierde_sin_el": round(pierde, 2),
                "valor_mercado": valor,
                "clausula_actual": clausula,
                "multiplo_clausula": round(multiplo, 2) if multiplo is not None else None,
                "prevision_7d_pct": _num(jugador.get("pct")),
                "riesgo": riesgo,
                "rivales_que_pueden_pagar": len(capaces),
                "rivales_total": len(rivales),
                "rival_mas_rico": (
                    {"manager": max(capaces, key=lambda item: item[0])[1].get("manager"), "caja": max(capaces, key=lambda item: item[0])[0]}
                    if capaces
                    else None
                ),
                "necesitan_su_posicion": [str(r.get("manager") or "Rival") for r in necesitan],
                "bloqueada_hasta": desbloqueo.isoformat() if desbloqueo is not None and bloqueada is True else None,
                "clausula_perfecta": perfecta,
                "subida_recomendada": elegido,
                "niveles": niveles,
                "exposicion_eur": int(round(exposicion)),
                "coste_reposicion": reposicion,
                "hay_sustituto": hay_sustituto,
                "falta_xp_sustituto": round(falta_xp, 2) if reposicion is not None else None,
                "expuesta_desde": expuesta_desde.isoformat() if expuesta_desde is not None else None,
                "expuesta_cuando": _cuando(expuesta_desde, ahora) if expuesta_desde is not None else None,
                "prescindible": prescindible,
                "sin_recambio": sin_recambio,
                "alerta_prioritaria": alerta_prioritaria,
                "abre_at": abre.isoformat() if abre is not None else None,
                "abre_el": (
                    _fecha_corta(abre) if abre is not None and abre > ahora else ("abierta" if abre is not None else None)
                ),
                "recambio_sugerido": (
                    {
                        "player_id": recambio.get("player_id"),
                        "nombre": recambio.get("nombre"),
                        "posicion": recambio.get("position"),
                        "coste": _int(recambio.get("coste")),
                        "xp": _num(recambio.get("xp")),
                    }
                    if recambio is not None
                    else None
                ),
                "veredicto_codigo": codigo,
                "veredicto_titulo": TITULOS_PROTEGER[codigo],
                "motivos": motivos,
                "motivo_detallado": motivo,
            }
        )
    orden = {"ALTO": 0, "MEDIO": 1, "BAJO": 2}
    filas.sort(
        key=lambda fila: (
            not fila["alerta_prioritaria"],
            orden[fila["riesgo"]],
            -fila["rivales_que_pueden_pagar"],
            -fila["exposicion_eur"],
        )
    )
    preparar.sort(key=lambda fila: (fila["bloqueada_hasta"] or "", -fila["exposicion_eur"]))
    return filas, bloqueadas, seguros, preparar


def _motivo_proteger(
    codigo: str,
    *,
    nombre: str,
    clausula: int,
    valor: int | None,
    elegido: dict[str, Any] | None,
    perfecta: dict[str, Any] | None,
    pierde: float,
    capaces: list[tuple[int, dict[str, Any]]],
    saldo: int | None,
    en_xi: bool,
    reposicion: int | None = None,
) -> str:
    if not capaces:
        return f"Nadie tiene caja para pagar su cláusula hoy, pero {_m(clausula)} es muy poco para lo que vale. Vigílala."
    rico = max(capaces, key=lambda item: item[0])
    cabeza = f"{rico[1].get('manager') or 'Un rival'} tiene {_m(rico[0])} y puede pagar sus {_m(clausula)}."
    impacto = f"Sin él tu once pierde -{_pts_txt(pierde)} pts." if pierde >= 0.05 else "Tu once no se resiente."
    if codigo == "SOBREPROTEGIDO":
        return (
            f"{cabeza} {impacto} Si te lo pagan cobras {_m(clausula)} y reponerlo cuesta {_m(reposicion or 0)}: "
            "la cláusula ya cubre el sustituto, no hace falta subirla."
        )
    if codigo in {"PROTEGER_YA", "PROTEGER_PARCIAL"} and elegido is not None and elegido.get("recortado_por_tope"):
        fuera = int(elegido.get("rivales_fuera") or 0)
        resto = (
            "Ningún rival se queda sin caja a esa cifra: reduce el riesgo, no lo elimina."
            if fuera == 0
            else f"Deja fuera a {fuera} de {len(capaces)} rivales con caja; los demás aún podrían pagarla."
        )
        return (
            f"{cabeza} {impacto} Súbela a {_m(elegido['clausula_objetivo'])}, el tope creíble (2,5× su valor) "
            f"para disuadir el robo: te cuesta {_m(elegido['coste_eur'])}. {resto}"
        )
    if codigo == "PROTEGER_YA" and elegido is not None:
        return (
            f"{cabeza} {impacto} Súbela a {_m(elegido['clausula_objetivo'])}: te cuesta {_m(elegido['coste_eur'])} "
            "y deja fuera a todos los rivales con caja."
        )
    if codigo == "PROTEGER_PARCIAL" and elegido is not None:
        return (
            f"{cabeza} {impacto} Cubrirlos a todos no sale a cuenta; sube a {_m(elegido['clausula_objetivo'])} "
            f"({_m(elegido['coste_eur'])}) y solo te quedan {elegido['rivales_sin_cubrir']} rivales por encima."
        )
    if codigo == "SIN_CAJA" and perfecta is not None:
        falta = max(0, perfecta["coste_eur"] - (saldo or 0))
        return (
            f"{cabeza} {impacto} La cláusula perfecta son {_m(perfecta['clausula_objetivo'])} ({_m(perfecta['coste_eur'])} "
            f"de coste) y te faltan {_m(falta)} de caja: vende a alguien o protege a otro."
        )
    if codigo == "VENDER_ANTES":
        return (
            f"{cabeza} {impacto} No te aporta puntos y su cláusula está por debajo de su valor "
            f"({_m(valor or 0)}): véndelo a LaLiga antes de que te lo clausulen, sin gastar caja en protegerlo."
        )
    cobro = f"Si lo pagan, cobras {_m(clausula)}"
    if valor:
        cobro += f" ({(clausula / valor - 1) * 100:+.0f}% sobre su valor)".replace(".", ",")
    return f"{cabeza} {impacto} Subir la cláusula cuesta más de lo que protege. {cobro}."


def _pts_txt(value: float) -> str:
    return _pts(value)


def bono_rosco_rival(
    jugador: dict[str, Any],
    rival: dict[str, Any] | None,
    *,
    dias_al_cierre: float | None,
) -> dict[str, Any] | None:
    """Daño directo al rival del Top 5 cuando el clausulazo le deja un hueco en el once.

    Solo cuenta con ``dias_al_cierre <= 1``. Si al quitarle al titular no le queda otro
    sano en esa posición, o se queda con menos de 11 sanos, tiene que alinear un hueco con
    0 pts: el impacto es lo que ese jugador iba a puntuar.
    """
    dias = _num(dias_al_cierre)
    if dias is None or dias > DIAS_GOLPE_RIVAL or not isinstance(rival, dict):
        return None
    puesto = _int(rival.get("puesto_liga"))
    if puesto is None or not 1 <= puesto <= TOP_RIVALES_GOLPE:
        return None
    plantilla = [fila for fila in rival.get("plantilla") or [] if isinstance(fila, dict)]
    objetivo = next((fila for fila in plantilla if fila.get("player_id") == jugador.get("player_id")), None)
    if objetivo is None or objetivo.get("sano") is not True:
        return None
    resto = [fila for fila in plantilla if fila is not objetivo and fila.get("sano") is True]
    recambios = [fila for fila in resto if fila.get("position") == objetivo.get("position")]
    if recambios and len(resto) >= TITULARES_MINIMOS:
        return None
    xp = _num(objetivo.get("jornada")) or _num(jugador.get("jornada")) or 0.0
    if xp <= 0:
        return None
    return {
        "activo": True,
        "rival": rival.get("manager"),
        "puesto_liga": puesto,
        "sin_recambio": not recambios,
        "sanos_tras": len(resto),
        "impacto_pts": round(xp, 2),
        "mensaje": MENSAJE_GOLPE_RIVAL,
    }


def _clausulazos(
    candidatos: list[dict[str, Any]],
    elegibles: list[dict[str, Any]],
    rivales: list[dict[str, Any]],
    *,
    liquidez: int | None,
    saldo: int | None,
    ratio: float,
    ahora: datetime,
    cierre: datetime | None,
    dias_al_cierre: float | None = None,
) -> list[dict[str, Any]]:
    base = solve_best_xi(elegibles)
    base_puntos = float(base["puntos"]) if base["ok"] else 0.0
    ventana_abierta = cierre is None or ahora < cierre
    filas: list[dict[str, Any]] = []
    for jugador in candidatos:
        player_id = jugador.get("player_id")
        clausula = _int(jugador.get("clausula"))
        valor = _int(jugador.get("valor"))
        xp = _num(jugador.get("jornada"))
        if not isinstance(player_id, str) or clausula is None or clausula <= 0 or jugador.get("blindado") is True:
            continue
        if jugador.get("position") not in {"POR", "DEF", "MC", "DEL"} or xp is None or xp <= 0:
            continue
        if not ventana_abierta:
            continue
        # Solo cuenta lo que se puede pagar con la caja o vendiendo a quien no juega.
        if liquidez is not None and clausula > liquidez:
            continue
        bloqueada, desbloqueo = _estado_lock(jugador.get("bloqueo"), ahora)
        if bloqueada is None:
            continue
        if bloqueada and (desbloqueo is None or (cierre is not None and desbloqueo >= cierre)):
            continue
        fantasma = {"player_id": f"nuevo:{player_id}", "position": jugador["position"], "jornada": xp}
        con = solve_best_xi([*elegibles, fantasma])
        mejora = round(max(0.0, float(con["puntos"]) - base_puntos), 2) if con["ok"] else 0.0
        justo = _int(jugador.get("valor_justo"))
        margen_justo = (justo / clausula - 1) * 100.0 if justo else None
        es_valor = margen_justo is not None and margen_justo >= MARGEN_VALOR_PCT
        rival_dueno = next((rival for rival in rivales if rival.get("team_id") == jugador.get("team_id")), None)
        golpe = bono_rosco_rival(jugador, rival_dueno, dias_al_cierre=dias_al_cierre)
        if mejora < MEJORA_MINIMA and not es_valor and golpe is None:
            continue
        dueno = jugador.get("manager")
        competencia = [
            rival
            for rival in rivales
            if rival.get("team_id") != jugador.get("team_id")
            and _int(rival.get("saldo")) is not None
            and int(rival["saldo"]) >= clausula
        ]
        asequible = saldo is not None and saldo >= clausula
        falta = max(0, clausula - saldo) if saldo is not None else None
        if not asequible:
            codigo = "SIN_CAJA"
        elif bloqueada:
            codigo = "PROGRAMAR"
        elif mejora >= MEJORA_MINIMA:
            codigo = "CLAUSULAR_YA"
        elif golpe is not None:
            codigo = "GOLPE_RIVAL"
        else:
            codigo = "OPORTUNIDAD"
        cuando = "ahora" if not bloqueada else _cuando(desbloqueo, ahora)
        hasta = _cuando(cierre, ahora) if cierre is not None else None
        nombre = str(jugador.get("nombre") or player_id)
        filas.append(
            {
                "player_id": player_id,
                "nombre": nombre,
                "posicion": jugador.get("position"),
                "propietario": dueno,
                "clausula_eur": clausula,
                "valor_mercado": valor,
                "valor_justo": justo,
                "margen_valor_justo_pct": round(margen_justo, 1) if margen_justo is not None else None,
                "multiplo_clausula": round(clausula / valor, 2) if valor else None,
                "xp_jornada": round(xp, 2),
                "mejora_once": mejora,
                "roi_pts_por_millon": round(mejora / (clausula / 1_000_000), 2) if clausula else None,
                "p_titular": _num(jugador.get("p_titular")),
                "prevision_7d_pct": _num(jugador.get("pct")),
                "abierta_ahora": not bloqueada,
                "desbloqueo": desbloqueo.isoformat() if desbloqueo is not None and bloqueada else None,
                "cuando": cuando,
                "ventana_cierra": hasta,
                "asequible": asequible,
                "falta_caja_eur": int(falta) if falta else 0,
                "caja_tras": int(saldo - clausula) if asequible and saldo is not None else None,
                "rivales_que_pueden_quitartelo": len(competencia),
                "bono_rosco_rival": golpe,
                "prioridad_estrategica": round(mejora + (golpe["impacto_pts"] if golpe else 0.0), 2),
                "veredicto_codigo": codigo,
                "veredicto_titulo": TITULOS_CLAUSULAZO[codigo],
                "motivo_detallado": _motivo_clausulazo(
                    codigo,
                    nombre=nombre,
                    dueno=dueno,
                    clausula=clausula,
                    mejora=mejora,
                    margen=margen_justo,
                    cuando=cuando,
                    hasta=hasta,
                    competencia=len(competencia),
                    falta=falta or 0,
                    pct=_num(jugador.get("pct")),
                    golpe=golpe,
                ),
            }
        )
    filas.sort(
        key=lambda fila: (
            0 if fila["asequible"] else 1,
            -fila["prioridad_estrategica"],
            -(fila["margen_valor_justo_pct"] or 0.0),
            fila["clausula_eur"],
        )
    )
    return filas[:MAX_CLAUSULAZOS]


def _motivo_clausulazo(
    codigo: str,
    *,
    nombre: str,
    dueno: Any,
    clausula: int,
    mejora: float,
    margen: float | None,
    cuando: str,
    hasta: str | None,
    competencia: int,
    falta: int,
    pct: float | None,
    golpe: dict[str, Any] | None = None,
) -> str:
    de = f" a {dueno}" if dueno else ""
    partes = [f"Pagar {_m(clausula)}{de}"]
    if mejora >= MEJORA_MINIMA:
        partes[0] += f" sube tu once +{_pts(mejora)} pts"
    if margen is not None and margen > 0:
        partes.append(f"está un {margen:.0f}% por debajo de su valor justo".replace(".", ","))
    if pct is not None and pct > 3:
        partes.append(f"sube {pct:+.1f}% a 7d: cuanto antes, más barato".replace(".", ","))
    texto = ", ".join(partes) + "."
    if codigo == "CLAUSULAR_YA":
        texto += f" Está abierta{f' hasta {hasta}' if hasta else ''}."
    elif codigo == "PROGRAMAR":
        texto += f" Se desbloquea {cuando}: tenlo listo."
    elif codigo == "SIN_CAJA":
        texto += f" Te faltan {_m(falta)} de caja: tendrías que vender a alguien que no está en el once."
    else:
        texto += " No mejora el once, pero compras por debajo de su valor."
    if competencia:
        texto += f" {competencia} {'rival' if competencia == 1 else 'rivales'} más pueden pagarla: se te puede escapar."
    if golpe is not None:
        texto = (
            f"{golpe['mensaje']}. {golpe['rival'] or 'Tu rival'} va {golpe['puesto_liga']}º y pierde "
            f"-{_pts(golpe['impacto_pts'])} pts. {texto}"
        )
    return texto


def evaluar_clausulas(
    *,
    propios: list[dict[str, Any]],
    ajenos: list[dict[str, Any]],
    rivales: list[dict[str, Any]],
    saldo: int | None,
    ratio: float,
    ahora: datetime,
    cierre: datetime | None,
    dias_al_cierre: float | None = None,
    alternativas: list[dict[str, Any]] | None = None,
    inicio_jornada: datetime | None = None,
) -> dict[str, Any]:
    """``proteger`` (tus jugadores en peligro) y ``clausulazos`` (a quién pagar y cuándo).

    ``propios`` y ``ajenos`` traen ``player_id``, ``nombre``, ``position``, ``valor``,
    ``clausula``, ``blindado``, ``bloqueo``, ``jornada``, ``pct``. Los propios añaden
    ``en_xi``, ``tu_once_pierde_sin_el`` y ``elegible``; los ajenos, ``manager``/``team_id``.
    ``rivales`` lleva ``team_id``, ``manager``, ``saldo`` y ``posiciones`` flojas; con
    ``puesto_liga`` y ``plantilla`` (``player_id``, ``position``, ``sano``, ``jornada``)
    activa el bono de daño al rival en jueves y viernes.
    """
    proteger, bloqueadas, seguros, preparar = _proteger(
        propios,
        rivales,
        saldo=saldo,
        ratio=ratio,
        ahora=ahora,
        cierre=cierre,
        alternativas=alternativas,
        inicio_jornada=inicio_jornada,
    )
    elegibles = [
        {"player_id": fila["player_id"], "position": fila["position"], "jornada": fila.get("jornada") or 0.0}
        for fila in propios
        if fila.get("elegible") is True and fila.get("position") and isinstance(fila.get("player_id"), str)
    ]
    # Caja más lo que valen los jugadores que no están en el once (se pueden vender).
    liquidez = (
        saldo + sum(int(_int(fila.get("valor")) or 0) for fila in propios if fila.get("en_xi") is not True and fila.get("blindado") is not True)
        if saldo is not None
        else None
    )
    if dias_al_cierre is None and cierre is not None:
        dias_al_cierre = (cierre - ahora).total_seconds() / 86400.0
    clausulazos = _clausulazos(
        ajenos,
        elegibles,
        rivales,
        liquidez=liquidez,
        saldo=saldo,
        ratio=ratio,
        ahora=ahora,
        cierre=cierre,
        dias_al_cierre=dias_al_cierre,
    )
    en_peligro = [fila for fila in proteger if fila["riesgo"] != "BAJO"]
    resumen = {
        "en_peligro": len(en_peligro),
        "riesgo_alto": sum(1 for fila in proteger if fila["riesgo"] == "ALTO"),
        "coste_proteger_eur": int(
            sum(
                (fila["subida_recomendada"] or {}).get("coste_eur", 0)
                for fila in proteger
                if fila["veredicto_codigo"] in {"PROTEGER_YA", "PROTEGER_PARCIAL"}
            )
        ),
        "seguros": seguros,
        "bloqueadas": bloqueadas,
        "clausulazos_listos": sum(1 for fila in clausulazos if fila["veredicto_codigo"] == "CLAUSULAR_YA"),
        "golpes_al_rival": sum(1 for fila in clausulazos if fila.get("bono_rosco_rival")),
        "clausulazos": len(clausulazos),
        "ventana_cierra": _cuando(cierre, ahora) if cierre is not None else None,
        "ventana_abierta": cierre is None or ahora < cierre,
        "inicio_jornada": _cuando(inicio_jornada, ahora) if inicio_jornada is not None else None,
        "alertas_prioritarias": [
            {
                "player_id": fila["player_id"],
                "nombre": fila["nombre"],
                "posicion": fila["posicion"],
                "abre_el": fila["abre_el"],
                "abre_at": fila["abre_at"],
                "clausula": fila["clausula_actual"],
                "rival_mas_rico": fila["rival_mas_rico"],
                "recambio_sugerido": fila["recambio_sugerido"],
                "accion": fila["motivo_detallado"],
            }
            for fila in proteger
            if fila.get("alerta_prioritaria")
        ],
    }
    return {"resumen": resumen, "proteger": proteger, "preparar": preparar, "clausulazos": clausulazos}


# Por debajo de 1,15× el valor, la cláusula es un chollo. Desde 1,30×, robarlo nos beneficia.
_UMBRAL_VULNERABLE = 1.15
_UMBRAL_SOBREPROTEGIDO = 1.30
_VENTANA_APERTURA_DIAS = 3
# Un sustituto debe rendir como mucho 0,3 xP menos que el jugador que te roban.
_TOLERANCIA_SUSTITUTO_XP = 0.3
# Sin sustituto libre, reponerlo cuesta un 60 % más que su valor.
_RECARGO_SIN_SUSTITUTO = 1.60
# Por debajo de esta pérdida, que te lo roben no cambia nada.
_PERDIDA_ESCASEZ_MIN = 2_000_000


def _millones_txt(value: float) -> str:
    return f"{value / 1_000_000:.1f}".replace(".", ",")


def _momento_apertura(value: Any, ahora: datetime) -> datetime | None:
    """Fecha en la que la cláusula se puede pagar. ``ahora`` si ya está abierta."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, dict):
        expira = value.get("expires_at") or value.get("clausulaAbre")
        if expira:
            leido = parse_clause_lock(expira, now=ahora)
            epoch = leido.get("epoch_ms")
            if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
                return datetime.fromtimestamp(float(epoch) / 1000.0, tz=timezone.utc)
        epoch = value.get("epoch_ms")
        if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
            return datetime.fromtimestamp(float(epoch) / 1000.0, tz=timezone.utc)
        if value.get("is_locked") is False:
            return ahora
        return None
    if isinstance(value, str) and value.strip():
        leido = parse_clause_lock(value, now=ahora)
        epoch = leido.get("epoch_ms")
        if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
            return datetime.fromtimestamp(float(epoch) / 1000.0, tz=timezone.utc)
    return None


def _ventana_clausula(
    jugador: dict[str, Any], ahora: datetime, hasta: datetime | None = None
) -> tuple[bool, bool, float | None]:
    """(entra en la ventana, ya está abierta, días que faltan).

    Entra si la apertura es pasada, si se abre antes de ``hasta`` (el bloqueo de la
    próxima jornada: en un parón son dos semanas) o, sin ese dato, si faltan menos de 3 días.
    """
    raw = jugador.get("clausulaAbre")
    if raw is None:
        raw = jugador.get("clausula_abre")
    if raw is None:
        raw = jugador.get("bloqueo") if jugador.get("bloqueo") is not None else jugador.get("clause_lock")
    if raw is None:
        return False, False, None
    momento = _momento_apertura(raw, ahora)
    if momento is None:
        return False, False, None
    dias = (momento - ahora).total_seconds() / 86400.0
    if dias <= 0 or dias < _VENTANA_APERTURA_DIAS or (hasta is not None and momento < hasta):
        return True, dias <= 0, dias
    return False, False, dias


def _caja_rival(rival: dict[str, Any]) -> float | None:
    for key in ("dineroEstimado", "saldo", "cash_eur", "reconstructed_cash_eur"):
        number = _num(rival.get(key))
        if number is not None:
            return number
    return None


def _euros_jugador(jugador: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        number = _int(jugador.get(key))
        if number is not None and number > 0:
            return number
    return None


def buscar_sustituto(
    jugador: dict[str, Any],
    alternativas: list[dict[str, Any]],
    valor: int,
    clausula: int | None = None,
) -> tuple[int, bool, float]:
    """Sustituto comprable de ``jugador``: ``(coste, hay_sustituto, falta_xp)``.

    Prefiere el más barato que rinda al menos ``xp - 0,3``. Con ``clausula`` el presupuesto
    se acota a ``max(2,5 × cláusula, 4 × valor)``: si el único igual de bueno cuesta más, se
    toma el que más puntos da dentro del presupuesto y ``falta_xp`` son los puntos que no cubre.
    Sin ninguno comprable, ``1,6 × valor`` y ``hay_sustituto`` falso.
    """
    sin = (int(round(valor * _RECARGO_SIN_SUSTITUTO)), False, 0.0)
    xp = _num(jugador.get("jornada"))
    posicion = jugador.get("position") or jugador.get("posicion")
    if xp is None or posicion is None:
        return sin
    presupuesto = None
    if clausula:
        presupuesto = max(clausula * MULTIPLO_PRESUPUESTO_CLAUSULA, valor * MULTIPLO_PRESUPUESTO_VALOR)
    candidatos: list[tuple[int, float]] = []
    for alternativa in alternativas:
        if alternativa.get("position") != posicion or alternativa.get("player_id") == jugador.get("player_id"):
            continue
        coste = _int(alternativa.get("coste"))
        rinde = _num(alternativa.get("xp"))
        if coste is None or coste <= 0 or rinde is None:
            continue
        candidatos.append((coste, rinde))
    iguales = [coste for coste, rinde in candidatos if rinde >= xp - _TOLERANCIA_SUSTITUTO_XP]
    if iguales and (presupuesto is None or min(iguales) <= presupuesto):
        return min(iguales), True, 0.0
    if presupuesto is None:
        return sin
    pagables = [(coste, rinde) for coste, rinde in candidatos if coste <= presupuesto]
    if not pagables:
        return sin
    coste, rinde = max(pagables, key=lambda item: (item[1], -item[0]))
    return coste, True, max(0.0, xp - rinde)


def coste_reposicion(
    jugador: dict[str, Any],
    alternativas: list[dict[str, Any]],
    valor: int,
    clausula: int | None = None,
) -> tuple[int, bool]:
    """Lo que cuesta tener otra vez los puntos de ``jugador`` si te lo roban: ``(coste, hay_sustituto)``."""
    coste, hay, _ = buscar_sustituto(jugador, alternativas, valor, clausula)
    return coste, hay


def auditar_clausulas_plantilla(
    jugadores_plantilla: list[dict[str, Any]],
    saldo_rivales: list[dict[str, Any]],
    *,
    ahora: datetime | None = None,
    alternativas: list[dict[str, Any]] | None = None,
    hasta: datetime | None = None,
) -> list[dict[str, Any]]:
    """Riesgo real de que un rival pague la cláusula de un jugador nuestro.

    Mira cláusulas ya abiertas o que se abren antes de ``hasta`` (inicio de la
    próxima jornada); sin ese dato, en menos de 3 días. Cruza
    el múltiplo de la cláusula con cuántos rivales tienen ``dineroEstimado``
    para pagarla hoy. Con ``alternativas`` (``position``, ``coste``, ``xp``)
    mide también el coste de reposición: si lo que cobras no alcanza para
    comprar un sustituto, la fila pasa a ``ESCASEZ``.
    """
    momento = ahora or datetime.now(timezone.utc)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    cajas = [_caja_rival(rival) for rival in saldo_rivales if isinstance(rival, dict)]
    cajas = [caja for caja in cajas if caja is not None]
    filas: list[dict[str, Any]] = []
    for jugador in jugadores_plantilla:
        if not isinstance(jugador, dict):
            continue
        if jugador.get("blindado") is True or jugador.get("is_shielded") is True or jugador.get("shielded") is True:
            continue
        en_ventana, abierta, dias = _ventana_clausula(jugador, momento, hasta)
        if not en_ventana:
            continue
        clausula = _euros_jugador(jugador, "clausula", "clausula_actual", "buyout_clause", "clause")
        valor = _euros_jugador(jugador, "valor_mercado", "valor", "market_value")
        if clausula is None or valor is None:
            continue
        player_id = jugador.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            continue
        pct = _num(jugador.get("prevision_7d_pct"))
        if pct is None and isinstance(jugador.get("prevision_7d_pct"), str):
            texto = jugador["prevision_7d_pct"].strip().replace("%", "").replace(",", ".")
            try:
                pct = float(texto)
            except ValueError:
                pct = None
        subida = valor * (pct / 100.0) if pct is not None else 0.0
        valor_proyectado = int(round(valor + subida))
        rivales_con_caja = sum(1 for caja in cajas if caja >= clausula)
        clausula_txt = _millones_txt(clausula)
        reposicion: int | None = None
        perdida = 0
        if alternativas is not None:
            reposicion, hay_sustituto = coste_reposicion(jugador, alternativas, valor, clausula)
            perdida = max(0, reposicion - clausula)
        if perdida > _PERDIDA_ESCASEZ_MIN and rivales_con_caja >= 1:
            estado = "ESCASEZ"
            badge = "rojo"
            origen = "el sustituto más barato" if hay_sustituto else "1,6× su valor (no hay sustituto libre)"
            consejo = (
                f"Difícil de reponer: si pagan {clausula_txt}M, sustituirlo cuesta {_millones_txt(reposicion)}M "
                f"({origen}). Pierdes {_millones_txt(perdida)}M de poder competitivo. Blíndalo."
            )
            beneficio = 0
        elif clausula >= valor * _UMBRAL_SOBREPROTEGIDO:
            beneficio = max(0, clausula - valor)
            estado = "SOBREPROTEGIDO"
            badge = "verde"
            consejo = (
                f"Bien protegido: si pagan {clausula_txt}M, ganas {_millones_txt(beneficio)}M. "
                "No hace falta subir la cláusula."
            )
        elif clausula < valor * _UMBRAL_VULNERABLE and rivales_con_caja >= 1:
            estado = "RIESGO_ALTO"
            badge = "rojo"
            consejo = (
                f"Riesgo alto: {rivales_con_caja} {'rival tiene' if rivales_con_caja == 1 else 'rivales tienen'} caja "
                f"y su cláusula ({clausula_txt}M) está barata. Súbela hoy."
            )
            beneficio = max(0, clausula - valor)
        elif clausula < valor * _UMBRAL_VULNERABLE:
            estado = "RIESGO_CERO"
            badge = "gris"
            consejo = (
                f"Sin riesgo hoy: la cláusula ({clausula_txt}M) está barata, pero ningún rival tiene caja para pagarla."
            )
            beneficio = max(0, clausula - valor)
        else:
            continue
        nombre = jugador.get("nombre") or jugador.get("nickname") or jugador.get("name") or player_id
        filas.append(
            {
                "player_id": player_id,
                "nombre": str(nombre),
                "posicion": jugador.get("position") or jugador.get("posicion"),
                "estado": estado,
                "badge": badge,
                "consejo": consejo,
                "clausula": clausula,
                "valor_mercado": valor,
                "valor_proyectado_7d": valor_proyectado,
                "prevision_7d_pct": pct,
                "beneficio_neto": int(beneficio),
                "rivales_con_caja": rivales_con_caja,
                "clausula_abierta": abierta,
                "dias_para_abrir": None if dias is None else round(dias, 2),
                "coste_reposicion": reposicion,
                "perdida_si_te_lo_roban": perdida if reposicion is not None else None,
            }
        )
    orden = {"RIESGO_ALTO": 0, "ESCASEZ": 1, "RIESGO_CERO": 2, "SOBREPROTEGIDO": 3}
    filas.sort(key=lambda fila: (orden[fila["estado"]], -fila["rivales_con_caja"], str(fila["nombre"])))
    return filas

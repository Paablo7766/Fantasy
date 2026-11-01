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
from toolbox.normalize import parse_clause_lock

_MADRID = ZoneInfo("Europe/Madrid")

#: Suelo de cláusula de la app: nadie puede bajarla de aquí.
CLAUSULA_MINIMA = 1_000_000
#: La cláusula está «en peligro» si no pasa de 1,25 veces el valor (misma regla que el tablero).
MULTIPLO_EN_PELIGRO = 1.25
#: Un rival no paga una cláusula que pase de 2,5 veces lo que vale el jugador: la regla de oro
#: ya llama chollo a hasta 2,2×, así que por encima nadie la compra.
MULTIPLO_CREIBLE = 2.5
#: Margen sobre la caja del rival para que no le llegue por poco.
MARGEN_MIN_EUR = 250_000
MARGEN_PCT = 0.02
#: Mejora mínima del once para que un clausulazo cuente como jugada deportiva.
MEJORA_MINIMA = 0.5
#: Ventaja de valor justo sobre la cláusula para considerarlo jugada de valor.
MARGEN_VALOR_PCT = 25.0
MAX_CLAUSULAZOS = 10
MAX_NIVELES = 4
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

TITULOS_PROTEGER = {
    "PROTEGER_YA": "SUBE LA CLÁUSULA",
    "PROTEGER_PARCIAL": "SUBE UN POCO",
    "SIN_CAJA": "NO TE LLEGA LA CAJA",
    "VENDER_ANTES": "VENDE ANTES",
    "ASUMIR": "PUEDES ASUMIRLO",
}
TITULOS_CLAUSULAZO = {
    "CLAUSULAR_YA": "CLAUSULA YA",
    "PROGRAMAR": "PROGRAMA",
    "SIN_CAJA": "TE FALTA CAJA",
    "OPORTUNIDAD": "OPORTUNIDAD DE VALOR",
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


def _cuando(momento: datetime | None, ahora: datetime) -> str:
    """«hoy 14:20», «mañana 10:15» o «jueves 10:15» en hora de Madrid."""
    if momento is None:
        return "sin hora"
    local = momento.astimezone(_MADRID)
    hoy = ahora.astimezone(_MADRID).date()
    hora = local.strftime("%H:%M")
    if local.date() == hoy:
        return f"hoy {hora}"
    if local.date() == hoy + timedelta(days=1):
        return f"mañana {hora}"
    return f"{_DIAS[local.weekday()]} {hora}"


def _niveles(clausula: int, capacidades: list[tuple[int, str | None]], saldo: int | None) -> list[dict[str, Any]]:
    """Cláusulas objetivo, de la más segura a la más barata.

    El nivel ``i`` deja sin cubrir a los ``i`` rivales con más caja. Cubrir a
    todos exige superar la caja del más rico más un margen.
    """
    ordenadas = sorted((caja for caja, _ in capacidades), reverse=True)
    niveles: list[dict[str, Any]] = []
    for sin_cubrir in range(0, min(len(ordenadas), MAX_NIVELES)):
        objetivo = ordenadas[sin_cubrir] + _margen(ordenadas[sin_cubrir])
        coste = coste_subida(clausula, objetivo)
        niveles.append(
            {
                "clausula_objetivo": int(objetivo),
                "subida_eur": int(objetivo - clausula),
                "coste_eur": int(coste),
                "caja_tras": None if saldo is None else int(saldo - coste),
                "rivales_cubiertos": len(ordenadas) - sin_cubrir,
                "rivales_sin_cubrir": sin_cubrir,
                "viable": saldo is not None and saldo - coste >= 0,
            }
        )
    return niveles


def _proteger(
    propios: list[dict[str, Any]],
    rivales: list[dict[str, Any]],
    *,
    saldo: int | None,
    ratio: float,
    ahora: datetime,
    cierre: datetime | None,
) -> tuple[list[dict[str, Any]], int, int]:
    filas: list[dict[str, Any]] = []
    bloqueadas = 0
    seguros = 0
    con_caja = [rival for rival in rivales if _int(rival.get("saldo")) is not None and int(rival["saldo"]) > 0]
    sin_dato = len(rivales) - len([rival for rival in rivales if _int(rival.get("saldo")) is not None])
    # La caja es una sola: se protege primero a quien más daño hace perder y se descuenta lo gastado.
    restante = saldo

    def _prioridad(jugador: dict[str, Any]) -> float:
        valor_ = _int(jugador.get("valor")) or 0
        clausula_ = _int(jugador.get("clausula")) or 0
        return -((_num(jugador.get("tu_once_pierde_sin_el")) or 0.0) * ratio + max(0, valor_ - clausula_))

    for jugador in sorted(propios, key=_prioridad):
        clausula = _int(jugador.get("clausula"))
        valor = _int(jugador.get("valor"))
        if clausula is None or clausula <= 0 or jugador.get("blindado") is True or not isinstance(jugador.get("player_id"), str):
            continue
        bloqueada, desbloqueo = _estado_lock(jugador.get("bloqueo"), ahora)
        if bloqueada is True and (cierre is None or desbloqueo is None or desbloqueo >= cierre):
            bloqueadas += 1
            continue
        justo = _int(jugador.get("valor_justo"))
        referencia = max(valor or 0, justo or 0)
        creible = referencia > 0 and clausula <= referencia * MULTIPLO_CREIBLE
        capaces = (
            [(int(rival["saldo"]), rival) for rival in con_caja if int(rival["saldo"]) >= clausula] if creible else []
        )
        multiplo = clausula / valor if valor else None
        fragil = multiplo is not None and multiplo <= MULTIPLO_EN_PELIGRO
        if not capaces and not (fragil and creible):
            seguros += 1
            continue
        posicion = jugador.get("position")
        pierde = _num(jugador.get("tu_once_pierde_sin_el")) or 0.0
        en_xi = jugador.get("en_xi") is True
        necesitan = [rival for _, rival in capaces if posicion in (rival.get("posiciones") or [])]
        capacidades = [(caja, str(rival.get("manager") or "Rival")) for caja, rival in capaces]
        niveles = _niveles(clausula, capacidades, restante) if capaces else []
        caja_antes = restante

        # Daño si te lo clausulan: los puntos que pierde tu once pagados a precio de mercado
        # y, si la cláusula está por debajo de su valor, lo que dejas de cobrar.
        regalo = max(0, (valor or 0) - clausula)
        exposicion = pierde * ratio + regalo
        elegido: dict[str, Any] | None = None
        mejor_neto = 0.0
        for nivel in niveles:
            total = nivel["rivales_cubiertos"] + nivel["rivales_sin_cubrir"]
            cubierto = nivel["rivales_cubiertos"] / total if total else 0.0
            neto = exposicion * cubierto - nivel["coste_eur"]
            if nivel["viable"] and neto > mejor_neto:
                mejor_neto = neto
                elegido = nivel
        perfecta = niveles[0] if niveles else None
        if elegido is not None and restante is not None:
            restante -= int(elegido["coste_eur"])

        if not capaces:
            riesgo = "BAJO"
        elif en_xi or pierde >= 1.0:
            riesgo = "ALTO"
        else:
            riesgo = "MEDIO"

        if elegido is not None and elegido["rivales_sin_cubrir"] == 0:
            codigo = "PROTEGER_YA"
        elif elegido is not None:
            codigo = "PROTEGER_PARCIAL"
        elif perfecta is not None and not perfecta["viable"] and exposicion > perfecta["coste_eur"]:
            codigo = "SIN_CAJA"
        elif regalo > 0 and pierde < 1.8:
            codigo = "VENDER_ANTES"
        else:
            codigo = "ASUMIR"

        motivos: list[str] = []
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
        motivo = _motivo_proteger(
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
        )
        filas.append(
            {
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
                "veredicto_codigo": codigo,
                "veredicto_titulo": TITULOS_PROTEGER[codigo],
                "motivos": motivos,
                "motivo_detallado": motivo,
            }
        )
    orden = {"ALTO": 0, "MEDIO": 1, "BAJO": 2}
    filas.sort(key=lambda fila: (orden[fila["riesgo"]], -fila["rivales_que_pueden_pagar"], -fila["exposicion_eur"]))
    return filas, bloqueadas, seguros


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
) -> str:
    if not capaces:
        return f"Nadie tiene caja para pagar su cláusula hoy, pero {_m(clausula)} es muy poco para lo que vale. Vigílala."
    rico = max(capaces, key=lambda item: item[0])
    cabeza = f"{rico[1].get('manager') or 'Un rival'} tiene {_m(rico[0])} y puede pagar sus {_m(clausula)}."
    impacto = f"Sin él tu once pierde -{_pts_txt(pierde)} pts." if pierde >= 0.05 else "Tu once no se resiente."
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
            f"{cabeza} {impacto} Proteger no compensa y su cláusula está por debajo de su valor "
            f"({_m(valor or 0)}): véndelo a LaLiga antes de que te lo clausulen."
        )
    cobro = f"Si lo pagan, cobras {_m(clausula)}"
    if valor:
        cobro += f" ({(clausula / valor - 1) * 100:+.0f}% sobre su valor)".replace(".", ",")
    return f"{cabeza} {impacto} Subir la cláusula cuesta más de lo que protege. {cobro}."


def _pts_txt(value: float) -> str:
    return _pts(value)


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
        if mejora < MEJORA_MINIMA and not es_valor:
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
                ),
            }
        )
    filas.sort(
        key=lambda fila: (
            0 if fila["asequible"] else 1,
            -fila["mejora_once"],
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
        texto += f" Te faltan {_m(falta)} de caja: tendrías que vender a alguien del banquillo."
    else:
        texto += " No mejora el once, pero compras por debajo de su valor."
    if competencia:
        texto += f" {competencia} {'rival' if competencia == 1 else 'rivales'} más pueden pagarla: se te puede escapar."
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
) -> dict[str, Any]:
    """``proteger`` (tus jugadores en peligro) y ``clausulazos`` (a quién pagar y cuándo).

    ``propios`` y ``ajenos`` traen ``player_id``, ``nombre``, ``position``, ``valor``,
    ``clausula``, ``blindado``, ``bloqueo``, ``jornada``, ``pct``. Los propios añaden
    ``en_xi``, ``tu_once_pierde_sin_el`` y ``elegible``; los ajenos, ``manager``/``team_id``.
    ``rivales`` lleva ``team_id``, ``manager``, ``saldo`` y ``posiciones`` flojas.
    """
    proteger, bloqueadas, seguros = _proteger(propios, rivales, saldo=saldo, ratio=ratio, ahora=ahora, cierre=cierre)
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
    clausulazos = _clausulazos(ajenos, elegibles, rivales, liquidez=liquidez, saldo=saldo, ratio=ratio, ahora=ahora, cierre=cierre)
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
        "clausulazos": len(clausulazos),
        "ventana_cierra": _cuando(cierre, ahora) if cierre is not None else None,
        "ventana_abierta": cierre is None or ahora < cierre,
    }
    return {"resumen": resumen, "proteger": proteger, "clausulazos": clausulazos}

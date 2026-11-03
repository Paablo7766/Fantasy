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


def capital_trading(saldo_sobrante: int, valor_equipo: int, credito_disponible: int | None = None) -> dict[str, int]:
    """Caja libre más la deuda que el trading se atreve a usar.

    ``credito_disponible`` es el margen del 20 % que las pujas del once dejan
    sin usar; la deuda del trading nunca pasa de ahí.
    """
    deuda = int(max(0, valor_equipo) * DEUDA_PCT_EQUIPO * DEUDA_USO_MAX)
    if credito_disponible is not None:
        deuda = min(deuda, max(0, int(credito_disponible)))
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
    credito_disponible: int | None = None,
) -> dict[str, Any]:
    """Elige las compras especulativas que maximizan euros dentro del capital.

    Cada candidato trae ``player_id``, ``nombre``, ``origen`` (bid/clause),
    ``euros`` (lo que sale de la caja), ``valor`` y ``pct`` (previsión a 7 días).
    ``af_alerta_bajada`` saca al jugador de la mochila: AnalíticaFantasy ya ve
    el giro aunque la inercia de ayer (``pct``) siga en positivo.
    """
    vacio: dict[str, Any] = {"activo": False, "operaciones": [], "capital": 0, "ganancia_esperada": 0}
    if saldo_sobrante is None or dias_para_jornada is None or dias_para_jornada < DIAS_MINIMOS:
        return vacio
    capital = capital_trading(saldo_sobrante, valor_equipo, credito_disponible)
    dias = min(DIAS_TRADING, float(dias_para_jornada))
    filas: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for item in candidatos:
        euros = _num(item.get("euros"))
        valor = _num(item.get("valor")) or euros
        pct = _num(item.get("pct"))
        player_id = item.get("player_id")
        if item.get("af_alerta_bajada") is True:
            continue
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


#: Por debajo de esto, tu titular está a tiro de cláusula.
RATIO_ESCUDO = 1.20
#: Por debajo de esto, la cláusula del rival en rojo es un objetivo de trading.
RATIO_FRANCOTIRADOR = 1.15


def _texto_pct(value: Any) -> float | None:
    number = _num(value)
    if number is not None:
        return number
    if not isinstance(value, str):
        return None
    texto = value.strip().replace("%", "").replace(",", ".")
    if texto.startswith("+"):
        texto = texto[1:]
    try:
        return float(texto)
    except ValueError:
        return None


def _euros(*values: Any) -> int | None:
    for value in values:
        number = _num(value)
        if number is not None and number > 0:
            return int(number)
    return None


def _nombre_persona(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Rival"


def _puesto(row: dict[str, Any]) -> str | None:
    for key in ("position", "posicion"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _en_rojo_seguro(row: dict[str, Any]) -> bool:
    if row.get("en_rojo_seguro") is True:
        return True
    marca = row.get("en_rojo")
    return marca == "seguro"


def _poder_rival(rival: dict[str, Any]) -> float | None:
    """Saldo contando el crédito: el mayor entre el tope legal y la caja más la deuda."""
    valores: list[float] = []
    for key in ("poder", "legal_bid_limit_eur", "legal_bid_limit"):
        number = _num(rival.get(key))
        if number is not None:
            valores.append(number)
    saldo = None
    for key in ("saldo", "cash_eur", "cash"):
        saldo = _num(rival.get(key))
        if saldo is not None:
            break
    deuda = _num(rival.get("debt_limit_eur")) or 0.0
    if saldo is not None:
        valores.append(saldo + max(0.0, deuda))
    return max(valores) if valores else None


def _lineas(rival: dict[str, Any]) -> tuple[set[str], set[str]]:
    huecos = {str(item) for item in rival.get("huecos") or [] if isinstance(item, str)}
    flojas = {
        str(item) for item in (rival.get("flojas") or rival.get("posiciones_flojas") or []) if isinstance(item, str)
    }
    urgencia = rival.get("urgencia") if isinstance(rival.get("urgencia"), dict) else {}
    for puesto, nivel in urgencia.items():
        if not isinstance(puesto, str):
            continue
        if nivel == "hueco":
            huecos.add(puesto)
        elif nivel in {"justo", "floja", "posicion_floja"}:
            flojas.add(puesto)
    return huecos, flojas


def alertas_escudo_francotirador(
    titulares: list[dict[str, Any]],
    rivales: list[dict[str, Any]],
    jugadores_rivales: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Escudo (te pueden clausular) y francotirador (clausulazo a un rojo seguro).

    El escudo mira a los 11 titulares. Si ``clausula / precio < 1,20`` y un
    rival con saldo (crédito incluido) tiene un hueco o una línea floja en
    ese puesto, hay alerta roja. El francotirador mira a los rivales en rojo
    seguro: cláusula por debajo de 1,15 veces el precio y previsión a 7 días
    en positivo.
    """
    alertas: list[dict[str, Any]] = []
    roster = [row for row in rivales if isinstance(row, dict)]
    for titular in titulares:
        if not isinstance(titular, dict) or titular.get("en_xi") is False:
            continue
        if titular.get("blindado") is True or titular.get("shielded") is True:
            continue
        clausula = _euros(titular.get("clausula"), titular.get("clause"), titular.get("buyout_clause"))
        precio = _euros(
            titular.get("precio_mercado"),
            titular.get("valor_mercado"),
            titular.get("valor"),
            titular.get("market_value"),
        )
        posicion = _puesto(titular)
        if clausula is None or precio is None or posicion is None:
            continue
        ratio = clausula / precio
        if ratio >= RATIO_ESCUDO:
            continue
        nombre = _nombre_persona(titular, "nombre", "nickname", "name", "player_id")
        for rival in roster:
            poder = _poder_rival(rival)
            if poder is None or poder < clausula:
                continue
            huecos, flojas = _lineas(rival)
            if posicion not in huecos and posicion not in flojas:
                continue
            rival_nombre = _nombre_persona(rival, "manager", "manager_name", "team_id")
            alertas.append(
                {
                    "tipo": "escudo",
                    "tono": "rojo",
                    "mensaje": (
                        f"🛡️ ALERTA: {rival_nombre} necesita un {posicion} y tu {nombre} está a tiro de cláusula"
                    ),
                    "player_id": titular.get("player_id"),
                    "nombre": nombre,
                    "posicion": posicion,
                    "rival": rival_nombre,
                    "ratio_clausula": round(ratio, 3),
                }
            )

    seguros: dict[str, str] = {}
    for rival in roster:
        if not _en_rojo_seguro(rival):
            continue
        nombre = _nombre_persona(rival, "manager", "manager_name", "team_id")
        team_id = rival.get("team_id")
        if isinstance(team_id, str) and team_id:
            seguros[team_id] = nombre
        seguros[nombre] = nombre
    vistos: set[tuple[str, str]] = set()
    candidatos = [row for row in (jugadores_rivales or []) if isinstance(row, dict)]
    for rival in roster:
        if _en_rojo_seguro(rival):
            candidatos.extend(row for row in rival.get("jugadores") or [] if isinstance(row, dict))
    for jugador in candidatos:
        if not isinstance(jugador, dict):
            continue
        owner = None
        if _en_rojo_seguro(jugador):
            owner = _nombre_persona(jugador, "manager", "manager_name", "team_id")
        else:
            team_id = jugador.get("team_id")
            if isinstance(team_id, str) and team_id in seguros:
                owner = seguros[team_id]
            else:
                manager = jugador.get("manager") if isinstance(jugador.get("manager"), str) else jugador.get("manager_name")
                if isinstance(manager, str) and manager in seguros:
                    owner = seguros[manager]
        if not owner:
            continue
        clausula = _euros(jugador.get("clausula"), jugador.get("clause"), jugador.get("buyout_clause"))
        precio = _euros(
            jugador.get("precio_mercado"),
            jugador.get("valor_mercado"),
            jugador.get("valor"),
            jugador.get("market_value"),
        )
        pct = _texto_pct(jugador.get("prevision_7d_pct"))
        if pct is None:
            pct = _texto_pct(jugador.get("pct"))
        if clausula is None or precio is None or pct is None or pct <= 0:
            continue
        ratio = clausula / precio
        if ratio >= RATIO_FRANCOTIRADOR:
            continue
        player_id = jugador.get("player_id") if isinstance(jugador.get("player_id"), str) else ""
        if (owner, player_id) in vistos:
            continue
        vistos.add((owner, player_id))
        nombre = _nombre_persona(jugador, "nombre", "nickname", "name", "player_id")
        alertas.append(
            {
                "tipo": "francotirador",
                "tono": "verde",
                "mensaje": (
                    f"🎯 OPORTUNIDAD: {nombre} de {owner} está subiendo de precio y su cláusula es baja. "
                    "Clausúlalo para Trading antes del viernes"
                ),
                "player_id": player_id or None,
                "nombre": nombre,
                "posicion": _puesto(jugador),
                "rival": owner,
                "ratio_clausula": round(ratio, 3),
            }
        )
    return alertas

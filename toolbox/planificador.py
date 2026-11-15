"""Planificador de jornada: xP de las 4 próximas jornadas para todos los jugadores de la liga.

Solo lee la foto guardada (sin red). El universo son los jugadores con xP
propio: los de las plantillas de la liga y los del mercado. El xP sale de la
fuente única (``own_expected_points`` para la próxima jornada y
``own_xp_siguientes`` para las tres siguientes); aquí no se recalcula nada.

Para cada jugador añade quién lo tiene (tú, un rival, el mercado) y, si es de
un rival, el estado de su cláusula: blindado, bloqueada hasta una hora o
abierta. Abierta solo quiere decir que el candado ya venció: la decisión de
pagarla (caja, crédito del 20 %, plazos) es de la pantalla de Cláusulas.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any

HORIZONTE = 4
#: Margen sobre el precio para llamar a un fichaje rentable (o caro, si falta).
#: El valor justo sale del xP y es ruidoso: dentro de ±10 % es precio justo.
MARGEN_RENTABLE = 0.10
#: Titulares que forman la curva de valor justo: misma muestra que la capa de estrategia.
P_TITULAR_CURVA = 0.60
_POS = {"POR": "POR", "PT": "POR", "DEF": "DEF", "DF": "DEF", "MC": "MC", "MED": "MC", "DEL": "DEL", "DC": "DEL"}
_BAJA = {"baja", "lesionado", "injured", "sancionado", "suspended", "fuera"}
_DUDA = {"duda", "doubtful"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _share(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number / 100.0 if number > 1 else number))


def _estado(trend: dict[str, Any], squad_row: dict[str, Any] | None) -> str | None:
    """«baja», «duda» o None, con los avisos que ya trae la foto."""
    textos = {
        str(x).strip().lower()
        for x in (
            trend.get("lineup_status"),
            trend.get("fitness"),
            (squad_row or {}).get("fitness"),
            (squad_row or {}).get("player_status"),
        )
        if x
    }
    sancion = trend.get("sanction") if isinstance(trend.get("sanction"), dict) else {}
    if textos & _BAJA or sancion.get("suspended") or trend.get("af_suspension"):
        return "baja"
    if textos & _DUDA or trend.get("af_injury"):
        return "duda"
    return None


def _clausula(row: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Estado de la cláusula de un jugador de rival."""
    euros = _int(row.get("buyout_clause"))
    if not euros or euros <= 0:
        return None
    valor = _int(row.get("market_value"))
    lock = row.get("clause_lock") if isinstance(row.get("clause_lock"), dict) else {}
    abre = _parse_iso(lock.get("expires_at"))
    if row.get("is_shielded") is True:
        estado = "blindado"
    elif abre is not None and abre > now:
        estado = "bloqueada"
    elif abre is not None or lock.get("is_locked") is False:
        estado = "abierta"
    else:
        estado = "sin_dato"
    # Misma regla que el asesor de cláusulas: si destruye patrimonio, no compensa.
    from toolbox.engine.signing_plan import evaluar_patrimonio_clausula

    patrimonio = evaluar_patrimonio_clausula({"euros": euros, "valor": valor})
    return {
        "eur": euros,
        "multiplo": round(euros / valor, 2) if valor else None,
        "estado": estado,
        "abre_at": abre.isoformat() if estado == "bloqueada" and abre else None,
        "cara": bool(patrimonio["descartar"]),
        "prima_eur": int(patrimonio["prima_quemada_neta"]) if valor else None,
    }


def _rentabilidad(fila: dict[str, Any], ratio: float, curva: Any) -> dict[str, Any] | None:
    """¿Compensa ficharlo a este precio? Valor justo de su xP frente a lo que cuesta.

    Valor justo = lo que esta liga paga en mercado por el xP de la próxima jornada
    (curva por percentiles de la capa de estrategia, la misma que usan Mercado y
    Cláusulas). Si pasa de 2,5× su valor de mercado es una estimación inflada y se
    recorta ahí. Una cláusula que quema patrimonio es «caro» aunque el xP la cubra.
    """
    from toolbox.engine.clause_advisor import MULTIPLO_CREIBLE
    from toolbox.engine.market_predictor import valor_justo_jugador

    if fila["dueno"]["tipo"] == "mio":
        return None
    if fila["mercado"] is not None:
        precio = fila["mercado"].get("precio")
        via = "mercado"
    elif fila["clausula"] and fila["clausula"]["estado"] in {"abierta", "bloqueada"}:
        precio = fila["clausula"]["eur"]
        via = "clausula"
    else:
        return None
    xp = fila["xp"][0]
    if not precio or precio <= 0 or xp is None:
        return None
    justo = valor_justo_jugador(max(0.0, float(xp)), ratio, curva)
    valor = fila.get("valor")
    if valor and justo > valor * MULTIPLO_CREIBLE:
        justo = int(valor * MULTIPLO_CREIBLE)
    margen = justo / precio - 1.0
    if via == "clausula" and fila["clausula"].get("cara"):
        veredicto = "caro"
    elif margen >= MARGEN_RENTABLE:
        veredicto = "rentable"
    elif margen <= -MARGEN_RENTABLE:
        veredicto = "caro"
    else:
        veredicto = "justo"
    return {
        "veredicto": veredicto,
        "valor_justo": int(justo),
        "precio": int(precio),
        "margen_pct": round(margen * 100.0, 1),
    }


def _jornada_siguiente(squads: list[dict[str, Any]]) -> int | None:
    """Próxima jornada: la última con puntos de cada club + 1, la más repetida."""
    por_club: dict[str, int] = {}
    for team in squads:
        for player in team.get("players") or []:
            if not isinstance(player, dict):
                continue
            rondas = player.get("week_points_by_round")
            if not isinstance(rondas, dict) or not rondas:
                continue
            try:
                ultima = max(int(k) for k in rondas)
            except ValueError:
                continue
            club = str(player.get("club") or "")
            por_club[club] = max(por_club.get(club, 0), ultima)
    if not por_club:
        return None
    return statistics.mode(v + 1 for v in por_club.values())


LIBRES_MAX = 40


def _libres(
    catalogo: list[dict[str, Any]] | None,
    con_xp: set[str],
    rivales_por_club: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Jugadores de LaLiga que no son de nadie en la liga ni están en el mercado.

    No tienen xP: el motor necesita sus actas (minutos) y solo se descargan para
    plantillas y mercado. Sin ellas el xP sale casi igual para todos los de un
    mismo club, así que aquí van con su media y su forma reciente, aparte.
    """
    from toolbox.matching import normalize_club

    filas: list[dict[str, Any]] = []
    for row in catalogo or []:
        if not isinstance(row, dict) or row.get("player_id") is None:
            continue
        pid = str(row["player_id"])
        if pid in con_xp:
            continue
        media = _num(row.get("average_points"))
        serie = [x for x in (_num(v) for v in row.get("week_points") or []) if x is not None]
        if media is None or len(serie) < 3:
            continue
        status = str(row.get("player_status") or "").lower()
        estado = "baja" if status in {"injured", "suspended"} else "duda" if status == "doubtful" else None
        ultimos = serie[-3:]
        partido = rivales_por_club.get(normalize_club(str(row.get("club") or "")))
        filas.append(
            {
                "player_id": pid,
                "nombre": row.get("nickname") or row.get("name"),
                "posicion": _POS.get(str(row.get("position") or "").upper(), "MC"),
                "club": row.get("club"),
                "image_url": row.get("image_url"),
                "media": round(media, 2),
                "forma": round(sum(ultimos) / len(ultimos), 2),
                "ultimos": ultimos,
                "valor": _int(row.get("market_value")),
                "estado": estado,
                "proximo": partido,
            }
        )
    filas.sort(key=lambda fila: (fila["estado"] == "baja", -fila["media"]))
    return filas[:LIBRES_MAX]


def build_planificador(
    board: dict[str, Any],
    *,
    now: datetime | None = None,
    catalogo: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    squads_doc = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    teams = [t for t in squads_doc.get("squads") or [] if isinstance(t, dict)]

    duenos: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    managers: list[dict[str, Any]] = []
    for team in teams:
        nombre = team.get("manager_name") or team.get("fantasy_team_name") or "Rival"
        managers.append({"team_id": team.get("team_id"), "nombre": nombre, "es_mio": bool(team.get("is_self"))})
        for player in team.get("players") or []:
            if isinstance(player, dict) and player.get("player_id") is not None:
                duenos[str(player["player_id"])] = (team, player)

    en_mercado: dict[str, dict[str, Any]] = {}
    for listing in market.get("listings") or []:
        if isinstance(listing, dict) and listing.get("player_id") is not None:
            en_mercado[str(listing["player_id"])] = listing

    jornada = _jornada_siguiente(teams)
    filas: list[dict[str, Any]] = []
    for trend in trends.get("players") or []:
        if not isinstance(trend, dict) or trend.get("player_id") is None:
            continue
        pid = str(trend["player_id"])
        proxima = _num(trend.get("own_expected_points"))
        if proxima is None:
            continue
        siguientes = trend.get("own_xp_siguientes") if isinstance(trend.get("own_xp_siguientes"), list) else []
        xp = [proxima, *(_num(x) for x in siguientes)][:HORIZONTE]
        xp += [None] * (HORIZONTE - len(xp))
        calendario = trend.get("own_calendar") if isinstance(trend.get("own_calendar"), list) else []
        partidos: list[dict[str, Any] | None] = []
        for index in range(HORIZONTE):
            celda = calendario[index] if index < len(calendario) and isinstance(calendario[index], dict) else None
            partidos.append(
                {
                    "rival": celda.get("opponent"),
                    "casa": celda.get("is_home") if isinstance(celda.get("is_home"), bool) else None,
                    "dificultad": celda.get("difficulty"),
                    "p_victoria": _num(celda.get("win_prob")),
                    "saque": celda.get("kickoff"),
                }
                if celda and celda.get("opponent")
                else None
            )

        team, squad_row = duenos.get(pid, (None, None))
        listing = en_mercado.get(pid)
        if team is not None and team.get("is_self"):
            dueno: dict[str, Any] = {"tipo": "mio", "nombre": "Tú", "team_id": team.get("team_id")}
        elif team is not None:
            dueno = {
                "tipo": "rival",
                "nombre": team.get("manager_name") or team.get("fantasy_team_name") or "Rival",
                "team_id": team.get("team_id"),
            }
        elif listing is not None:
            dueno = {"tipo": "mercado", "nombre": "Mercado", "team_id": None}
        else:
            dueno = {"tipo": "libre", "nombre": "Libre", "team_id": None}

        valores = [x for x in xp if x is not None]
        filas.append(
            {
                "player_id": pid,
                "nombre": trend.get("nickname") or trend.get("name") or (squad_row or {}).get("nickname"),
                "posicion": _POS.get(str(trend.get("position") or "").upper(), "MC"),
                "club": trend.get("club") or (squad_row or {}).get("club"),
                "image_url": trend.get("image_url") or (squad_row or {}).get("image_url"),
                "xp": [round(x, 2) if x is not None else None for x in xp],
                "xp_total": round(sum(valores), 2) if valores else None,
                "techo": _num(trend.get("own_ceiling_points")),
                "si_juega": _num(trend.get("own_points_if_starts")),
                "p_titular": _share(trend.get("p_titular")),
                "estado": _estado(trend, squad_row),
                "media": _num((squad_row or {}).get("average_points")),
                "valor": _int((squad_row or {}).get("market_value")) or _int(trend.get("fantasy_price")),
                "partidos": partidos,
                "dueno": dueno,
                "mercado": {
                    "precio": _int(listing.get("sale_price")) or _int(listing.get("market_value")),
                    "cierra_at": listing.get("expires_at") or listing.get("listing_expires_at"),
                }
                if listing is not None
                else None,
                "clausula": _clausula(squad_row, moment) if dueno["tipo"] == "rival" and squad_row else None,
            }
        )

    from toolbox.engine.market_predictor import curva_valor_justo, ratio_mercado_liga

    titulares = [
        (float(fila["valor"]), float(fila["xp"][0]))
        for fila in filas
        if fila["valor"] and fila["xp"][0] and fila["xp"][0] > 0 and (fila["p_titular"] or 0.0) >= P_TITULAR_CURVA
    ]
    ratio = float(ratio_mercado_liga(titulares)["ratio_mercado"])
    curva = curva_valor_justo(titulares)
    for fila in filas:
        fila["rentabilidad"] = _rentabilidad(fila, ratio, curva)

    filas.sort(key=lambda fila: -(fila["xp"][0] or 0.0))
    from toolbox.matching import normalize_club

    rivales_por_club: dict[str, dict[str, Any]] = {}
    for fila in filas:
        clave = normalize_club(str(fila["club"] or ""))
        if clave and clave not in rivales_por_club and fila["partidos"][0]:
            rivales_por_club[clave] = fila["partidos"][0]
    return {
        "libres": _libres(catalogo, {fila["player_id"] for fila in filas}, rivales_por_club),
        "ok": True,
        "jornada": jornada,
        "jornadas": [jornada + i if jornada is not None else None for i in range(HORIZONTE)],
        "generado_at": moment.isoformat(),
        "dashboard_at": board.get("dashboard_at"),
        "managers": managers,
        "jugadores": filas,
        "nota": "xP propio (fuente única). Universo: plantillas de la liga y mercado.",
    }

"""Capa estratégica: precio a 7 días, WAR, pujas, rivales en negativo y plan.

Lee la foto que ya tiene el tablero (plantillas, mercado, once) y no sale a
la red. El JSON de siempre se queda; estos campos se suman encima.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from toolbox.analyzer import POSITIONS, own_squad
from toolbox.bidding import MIN_HEADCOUNT
from toolbox.engine.auction_intel import (
    PREVISION_ALTA_PCT,
    UMBRAL_WAR_OFERTA,
    PARCHE_SUPERVIVENCIA_EUR,
    calcular_pujas,
    capitanes,
    puja_anti_pizarra,
    puja_competitiva_liga,
    techo_sobrepuja_eur,
)
from toolbox.engine.lineup_math import solve_best_xi, war_del_once
from toolbox.engine.liquidacion import plan_liquidacion
from toolbox.engine.market_predictor import (
    EUROS_POR_PUNTO,
    curva_valor_justo,
    proyectar_7d,
    ratio_mercado_liga,
    valor_justo_jugador,
)
from toolbox.engine.clause_advisor import auditar_clausulas_plantilla, evaluar_clausulas, inicio_jornada_estimado
from toolbox.engine.market_grade import calcular_nota_mercado
from toolbox.engine.sales_audit import LALIGA, evaluar_ventas_y_ofertas
from toolbox.engine.brecha_posicional import brecha_posicional
from toolbox.engine.signing_plan import FACTOR_AJUSTE, build_plan_fichajes, conserva_esqueleto
from toolbox.engine.paron import UMBRAL_PARON_DIAS, paron_conocido
from toolbox.engine.live_matchday import construir_jornada_en_juego
from toolbox.engine.paron_plan import construir_paron, fase_paron
from toolbox.engine.reglamento import OFERTA_LALIGA_MIN
from toolbox.engine.trading_desk import DEUDA_PCT_EQUIPO, alertas_escudo_francotirador
from toolbox.jornada_plan import earliest_kickoff
from toolbox.plan_memory import load_objetivos_previos, save_plan
from toolbox.market_intel import _jornada_kickoff, _parse_kickoff
from toolbox.normalize import exclusion_from_status, parse_clause_lock
from toolbox.rival_intel import ROJO_SEGURO, estado_rojo

logger = logging.getLogger("fantasy.strategy")

_MADRID = ZoneInfo("Europe/Madrid")
_POSITION = {
    "POR": "POR",
    "PT": "POR",
    "GK": "POR",
    "DEF": "DEF",
    "DF": "DEF",
    "MC": "MC",
    "MED": "MC",
    "MID": "MC",
    "DEL": "DEL",
    "DL": "DEL",
    "FW": "DEL",
    "ATT": "DEL",
}
# La cláusula entra si el euro compra al menos un 25 % más de puntos que el mercado.
_CLAUSE_EDGE = 1.25
_CLAUSE_MIN_XP = 3.5
_MAX_PUJAS = 20
# Oferta más baja que puede hacer LaLiga sobre el valor de mercado (−10 %, regla oficial).
VENTA_SIN_OFERTA_PCT = OFERTA_LALIGA_MIN
_MAX_CLAUSULAS = 12
_TITULAR_RATIO = 0.60
# Campos con los que una fila propia puede traer la oferta del sistema.
_OFERTA_KEYS = ("oferta_sistema", "offer_eur", "system_offer", "offer", "offer_amount")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _int(value: Any) -> int | None:
    number = _num(value)
    if number is None:
        return None
    return int(round(number))


def _pid(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _position(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _POSITION.get(value.strip().upper())


def _nombre(row: dict[str, Any]) -> str:
    for key in ("nickname", "nombre", "name", "player_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "jugador"


def _prob(value: Any) -> float | None:
    number = _num(value)
    if number is None or number < 0:
        return None
    if number > 1:
        if number > 100:
            return None
        number /= 100.0
    if number > 1:
        return None
    return number


def _puntos_ultima(row: dict[str, Any]) -> float | None:
    """Puntos de la última jornada jugada, si el registro los trae."""
    recientes = row.get("recientes") if isinstance(row.get("recientes"), list) else []
    if recientes and isinstance(recientes[-1], (int, float)) and not isinstance(recientes[-1], bool):
        return float(recientes[-1])
    return None


def _blank() -> dict[str, Any]:
    return {
        "player_id": None,
        "nombre": None,
        "position": None,
        "jornada": None,
        "si_titular": None,
        "techo": None,
        "p_titular": None,
        "valor": None,
        "delta_hoy": 0.0,
        "delta_ayer": 0.0,
        "recientes": [],
        "team_id": None,
        "is_self": False,
        "manager": None,
        "clause": None,
        "shielded": False,
        "clause_lock": None,
        "dificultad": None,
        "kickoff": None,
        "on_market": False,
        "seller_team_id": None,
        "sale_price": None,
        "leading_bid": None,
        "caduca_hoy": False,
        "excluded": False,
        "in_xi": False,
    }


def _slot(records: dict[str, dict[str, Any]], player_id: str) -> dict[str, Any]:
    row = records.get(player_id)
    if row is None:
        row = _blank()
        row["player_id"] = player_id
        records[player_id] = row
    return row


def _set_name(row: dict[str, Any], source: dict[str, Any]) -> None:
    if not row.get("nombre"):
        row["nombre"] = _nombre(source)
    position = _position(source.get("position"))
    if position and not row.get("position"):
        row["position"] = position


def _set_points(row: dict[str, Any], source: dict[str, Any], *, prefer: bool) -> None:
    jornada = _num(source.get("jornada_ev"))
    if jornada is None:
        jornada = _num(source.get("own_expected_points"))
    if jornada is None:
        jornada = _num(source.get("jornada"))
    if jornada is None:
        jornada = _num(source.get("xp_pizarra"))
    if jornada is None:
        jornada = _num(source.get("expected_points"))
    if jornada is not None and (prefer or row.get("jornada") is None):
        row["jornada"] = jornada
    si = _num(source.get("points_if_starts"))
    if si is None:
        si = _num(source.get("own_points_if_starts"))
    if si is None:
        si = _num(source.get("xp_condicional"))
    if si is None:
        si = _num(source.get("si_titular"))
    if si is not None and (prefer or row.get("si_titular") is None):
        row["si_titular"] = si
    techo = _num(source.get("ceiling_points"))
    if techo is None:
        techo = _num(source.get("own_ceiling_points"))
    if techo is None:
        techo = _num(source.get("techo"))
    if techo is not None and (prefer or row.get("techo") is None):
        row["techo"] = techo
    prob = _prob(source.get("p_titular"))
    if prob is None:
        prob = _prob(source.get("p_start_eff"))
    if prob is not None and (prefer or row.get("p_titular") is None):
        row["p_titular"] = prob


def _set_price(row: dict[str, Any], source: dict[str, Any]) -> None:
    valor = _int(source.get("market_value"))
    if valor is None or valor <= 0:
        valor = _int(source.get("fantasy_price"))
    if valor is not None and valor > 0 and row.get("valor") is None:
        row["valor"] = valor
    delta = _num(source.get("price_delta"))
    if delta is None:
        delta = _num(source.get("market_value_change"))
    if delta is None:
        delta = _num(source.get("ff_price_delta"))
    if delta is not None and not row.get("_delta_set"):
        row["delta_hoy"] = delta
        row["_delta_set"] = True
    # ``ff_price_delta_2`` es la suma de hoy y ayer. Restarla del delta de hoy
    # da el día anterior de verdad. ``acceleration`` de FútbolFantasy es una
    # señal intradía, no esa resta, y solo se usa si no hay acumulado.
    if row.get("_delta_set") and not row.get("_ayer_set"):
        hoy = float(row.get("delta_hoy") or 0.0)
        dos = _num(source.get("ff_price_delta_2"))
        if dos is not None:
            row["delta_ayer"] = dos - hoy
            row["_ayer_set"] = True
        else:
            aceleracion = _num(source.get("acceleration"))
            if aceleracion is not None:
                row["delta_ayer"] = hoy - aceleracion
                row["_ayer_set"] = True
    if not row.get("recientes"):
        row["recientes"] = _recientes(source)


def _recientes(source: dict[str, Any]) -> list[float]:
    raw = source.get("week_points")
    if not isinstance(raw, list):
        form = source.get("form") if isinstance(source.get("form"), dict) else {}
        raw = form.get("week_points")
    if not isinstance(raw, list):
        return []
    numeros: list[float] = []
    for item in raw:
        if isinstance(item, dict):
            value = item.get("puntos", item.get("points"))
        else:
            value = item
        number = _num(value)
        if number is not None:
            numeros.append(number)
    return numeros[-5:]


def _set_difficulty(row: dict[str, Any], source: dict[str, Any]) -> None:
    if isinstance(row.get("dificultad"), str) and row["dificultad"].strip():
        return
    fixture = source.get("fixture")
    if isinstance(fixture, dict) and isinstance(fixture.get("difficulty"), str) and fixture["difficulty"].strip():
        row["dificultad"] = fixture["difficulty"].strip()
        return
    for key in ("calendar_difficulty", "difficulty", "dificultad"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            row["dificultad"] = value.strip()
            return
    for key in ("own_calendar", "af_calendar"):
        calendar = source.get(key)
        if not isinstance(calendar, list) or not calendar or not isinstance(calendar[0], dict):
            continue
        value = calendar[0].get("difficulty")
        if isinstance(value, str) and value.strip():
            row["dificultad"] = value.strip()
            return


def _set_kickoff(row: dict[str, Any], source: dict[str, Any]) -> None:
    """Saque del próximo partido, en UTC, para cruzarlo con el inicio de jornada."""
    fixture = source.get("fixture") if isinstance(source.get("fixture"), dict) else {}
    raw = fixture.get("kickoff")
    if raw is None:
        calendar = source.get("own_calendar") if isinstance(source.get("own_calendar"), list) else []
        raw = calendar[0].get("kickoff") if calendar and isinstance(calendar[0], dict) else None
    moment = _parse_kickoff(raw)
    if moment is not None:
        row["kickoff"] = moment.astimezone(timezone.utc).isoformat()


def _set_calendar(row: dict[str, Any], source: dict[str, Any]) -> None:
    """Próximos partidos: el propio da el próximo y AnalíticaFantasy los siguientes."""
    from toolbox.engine.comparador_liga import calendario_combinado

    if row.get("calendario"):
        return
    calendar = calendario_combinado(source)
    if len(calendar) >= 2:
        row["calendario"] = calendar


def _futuro(row: dict[str, Any]) -> float:
    """xP de las tres jornadas siguientes a la próxima, o 0 sin calendario.

    Usa el xP propio de cada partido si lo hay; si no, reescala el de la
    próxima por la dificultad del calendario.
    """
    # comparador_liga importa de este módulo: el import va aquí para no cerrar el ciclo.
    from toolbox.engine.comparador_liga import xp_jornadas_siguientes

    jornada = row.get("jornada")
    if not isinstance(jornada, (int, float)) or isinstance(jornada, bool):
        return 0.0
    if not row.get("calendario") and not row.get("xp_siguientes"):
        return 0.0
    valor = xp_jornadas_siguientes(
        {
            "jornada": float(jornada),
            "calendario": row.get("calendario") or [],
            "own_xp_siguientes": row.get("xp_siguientes"),
        }
    )
    return round(float(valor), 3) if valor is not None else 0.0


def _en_forma(row: dict[str, Any]) -> bool:
    recientes = row.get("recientes") if isinstance(row.get("recientes"), list) else []
    if len(recientes) >= 2:
        muestra = recientes[-3:]
        return sum(muestra) / len(muestra) >= 4.0
    si = row.get("si_titular")
    if isinstance(si, (int, float)) and not isinstance(si, bool) and float(si) >= 5:
        return True
    jornada = row.get("jornada")
    prob = row.get("p_titular")
    return (
        isinstance(jornada, (int, float))
        and not isinstance(jornada, bool)
        and float(jornada) >= 5
        and isinstance(prob, (int, float))
        and not isinstance(prob, bool)
        and float(prob) >= _TITULAR_RATIO
    )


def _clause_open(row: dict[str, Any], now: datetime) -> bool:
    if row.get("shielded") is True:
        return False
    lock = row.get("clause_lock") if isinstance(row.get("clause_lock"), dict) else {}
    expires = lock.get("expires_at")
    if isinstance(expires, str) and expires.strip():
        parsed = parse_clause_lock(expires, now=now)
        if parsed.get("is_locked") is True:
            return False
        if parsed.get("is_locked") is False:
            return True
    return lock.get("is_locked") is False


def _expires_today(value: Any, now: datetime) -> bool:
    moment = _parse_kickoff(value)
    if moment is None:
        return False
    return moment.astimezone(_MADRID).date() == now.astimezone(_MADRID).date()


def _proximo_viernes_2100(now: datetime) -> datetime:
    """Viernes 21:00 hora peninsular. Si esa hora ya pasó, el viernes siguiente."""
    local = now.astimezone(_MADRID)
    dias = (4 - local.weekday()) % 7
    candidato = (local + timedelta(days=dias)).replace(hour=21, minute=0, second=0, microsecond=0)
    if candidato <= local:
        candidato += timedelta(days=7)
    return candidato


def _days_to_kickoff(trends: dict[str, Any] | None, now: datetime) -> float | None:
    """Días hasta el primer silbato. Sin hora de partido, el próximo viernes a las 21:00.

    Un ``kickoff`` vacío no puede caer en ``SIN_RELOJ``: ese modo apaga el peaje
    de liquidez y deja vender sin oferta. El viernes a las 21:00 es el cierre
    habitual de la jornada cuando la API no trae el calendario.
    """
    moment = proximo_cierre(trends, now)
    if moment is None:
        raw = _jornada_kickoff(trends, now)
        moment = _parse_kickoff(raw) if isinstance(raw, str) else None
    if moment is None:
        conocido = paron_conocido(now)
        moment = conocido[1] if conocido else _proximo_viernes_2100(now)
    return (moment - now).total_seconds() / 86400.0


def _ciclo_paron(trends: dict[str, Any] | None, now: datetime, dias: float | None) -> bool:
    """El ciclo actual es un parón aunque ya falten menos de 7,5 días.

    Lo dice la tabla de parones conocidos, o el último saque ya jugado: si
    entre aquel partido y el próximo cierre hay más de 7,5 días, es parón.
    """
    if dias is None:
        return False
    if paron_conocido(now) is not None:
        return True
    cierre = now + timedelta(days=dias)
    jugados = [m for m in _saques(trends) if m < now]
    return bool(jugados) and (cierre - max(jugados)).total_seconds() / 86400.0 > UMBRAL_PARON_DIAS


#: La alineación se bloquea en el primer partido de la jornada (viernes), no
#: partido a partido. Con la jornada empezada, el siguiente cierre es el primer
#: saque de la próxima: el plan no puede seguir apuntando al domingo.
BLOQUEO_EN_PRIMER_PARTIDO = True
_HUECO_ENTRE_JORNADAS = timedelta(hours=36)


def _saques(trends: dict[str, Any] | None) -> list[datetime]:
    """Todos los saques conocidos: el próximo de cada club y los de su calendario."""
    salida: set[datetime] = set()
    for player in (trends or {}).get("players") or [] if isinstance(trends, dict) else []:
        if not isinstance(player, dict):
            continue
        fixture = player.get("fixture") if isinstance(player.get("fixture"), dict) else {}
        en_juego = player.get("own_en_juego") if isinstance(player.get("own_en_juego"), dict) else {}
        for raw in [en_juego.get("kickoff"), fixture.get("kickoff"), *[
            celda.get("kickoff") for celda in player.get("own_calendar") or [] if isinstance(celda, dict)
        ]]:
            moment = _parse_kickoff(raw) if isinstance(raw, str) else None
            if moment is not None:
                salida.add(moment.astimezone(timezone.utc))
    return sorted(salida)


def _proximo_por_club(trends: dict[str, Any] | None) -> dict[str, datetime]:
    """Saque del próximo partido de cada club."""
    salida: dict[str, datetime] = {}
    for player in (trends or {}).get("players") or [] if isinstance(trends, dict) else []:
        if not isinstance(player, dict) or not isinstance(player.get("club"), str) or not player.get("club"):
            continue
        fixture = player.get("fixture") if isinstance(player.get("fixture"), dict) else {}
        raw = fixture.get("kickoff")
        if raw is None:
            calendario = player.get("own_calendar") if isinstance(player.get("own_calendar"), list) else []
            raw = calendario[0].get("kickoff") if calendario and isinstance(calendario[0], dict) else None
        moment = _parse_kickoff(raw) if isinstance(raw, str) else None
        if moment is not None:
            club = player["club"]
            salida[club] = min(salida.get(club, moment), moment)
    return salida


def proximo_cierre(trends: dict[str, Any] | None, now: datetime) -> datetime | None:
    """Momento en que se bloquea la próxima alineación que todavía se puede tocar.

    Los saques futuros se agrupan en bloques separados por más de 36 h (una
    jornada cada uno). Si al menos dos clubes tienen su próximo partido después
    del primer bloque, ya jugaron: la jornada está en curso y, con bloqueo en el
    primer partido, el cierre es el inicio del bloque siguiente. Si no, es el
    primer saque. None sin calendario.
    """
    futuros = [moment for moment in _saques(trends) if moment >= now]
    if not futuros:
        return None
    fin_bloque = futuros[0]
    inicio_siguiente: datetime | None = None
    for moment in futuros[1:]:
        if moment - fin_bloque > _HUECO_ENTRE_JORNADAS:
            inicio_siguiente = moment
            break
        fin_bloque = moment
    if not BLOQUEO_EN_PRIMER_PARTIDO:
        return futuros[0]
    ya_jugaron = [club for club, saque in _proximo_por_club(trends).items() if saque > fin_bloque]
    if len(ya_jugaron) >= 2:
        return inicio_siguiente
    return futuros[0]


def _saltar_jornada_bloqueada(records: dict[str, dict[str, Any]], cierre: datetime | None) -> None:
    """Con la jornada bloqueada, el partido que le queda a un club ya no cuenta para ti.

    Su «próxima jornada» pasa a ser la siguiente: el xP de J2 sube a J1 y el
    resto se corre. Así un jugador del Sevilla (ya jugó, su próximo es J13) y
    uno que juega el domingo (J12 bloqueada) se comparan en la misma jornada.
    """
    if cierre is None or not BLOQUEO_EN_PRIMER_PARTIDO:
        return
    for row in records.values():
        saque = _parse_kickoff(row.get("kickoff")) if isinstance(row.get("kickoff"), str) else None
        siguientes = row.get("xp_siguientes")
        if saque is None or saque >= cierre or not isinstance(siguientes, list) or not siguientes:
            continue
        siguiente = _num(siguientes[0])
        if siguiente is None:
            continue
        row["jornada_bloqueada"] = row.get("jornada")
        row["jornada"] = siguiente
        row["xp_siguientes"] = list(siguientes[1:])
        calendario = row.get("calendario")
        if isinstance(calendario, list) and len(calendario) > 1:
            row["calendario"] = calendario[1:]
        row.pop("kickoff", None)


#: Caja neta de los rivales por foto (``dashboard_at``): la auditoría cuesta ~1 s.
_CAJA_NETA_MEMO: dict[str, dict[str, int]] = {}


def _caja_neta_rivales(board: dict[str, Any]) -> dict[str, int]:
    """La misma caja rival que enseña la pestaña Rivales (``/api/rival-intel``).

    El libro de movimientos da un techo: no resta las subidas de cláusula, que
    no salen en el historial. La auditoría las detecta (regla 1:2) y publica la
    caja neta (``risk_adjusted_cash`` o ``calculated_cash``). Sin ella, el techo.
    """
    clave = str(board.get("dashboard_at") or board.get("last_updated") or "")
    if clave and clave in _CAJA_NETA_MEMO:
        return _CAJA_NETA_MEMO[clave]
    salida: dict[str, int] = {}
    try:
        from toolbox.rival_intel import events_from_ledgers, get_financial_intel

        squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
        needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
        ledgers = needs.get("ledgers")
        # Sin libros no hay historial: la auditoría se inventaría la caja. Se queda el techo.
        if squads and isinstance(ledgers, list) and ledgers:
            documento = get_financial_intel(squads, events_from_ledgers(ledgers), persist=False)
            for team_id, team in (documento.get("teams") or {}).items():
                if not isinstance(team, dict) or team.get("is_self") is True:
                    continue
                for key in ("risk_adjusted_cash", "calculated_cash"):
                    valor = team.get(key)
                    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                        salida[str(team_id)] = int(valor)
                        break
    except Exception:
        logger.exception("caja neta de los rivales")
        salida = {}
    if clave:
        _CAJA_NETA_MEMO.clear()
        _CAJA_NETA_MEMO[clave] = salida
    return salida


def _cash_map(board: dict[str, Any]) -> dict[str, int]:
    found: dict[str, int] = {}
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        team_id = _pid(squad.get("team_id"))
        cash = squad.get("cash")
        if team_id and isinstance(cash, int) and not isinstance(cash, bool):
            found[team_id] = cash
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    for ledger in needs.get("ledgers") or []:
        if not isinstance(ledger, dict):
            continue
        team_id = _pid(ledger.get("team_id"))
        rebuilt = ledger.get("reconstructed_cash_eur")
        if team_id and isinstance(rebuilt, int) and not isinstance(rebuilt, bool):
            found[team_id] = rebuilt
    # Un solo criterio con la pestaña Rivales: caja neta de subidas de cláusula (1:2).
    for team_id, neta in _caja_neta_rivales(board).items():
        if team_id in found:
            found[team_id] = neta
    return found


def _collect(board: dict[str, Any], now: datetime) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    for player in trends.get("players") or []:
        if not isinstance(player, dict):
            continue
        player_id = _pid(player.get("player_id"))
        if player_id is None:
            continue
        row = _slot(records, player_id)
        _set_name(row, player)
        _set_points(row, player, prefer=False)
        _set_price(row, player)
        _set_difficulty(row, player)
        _set_kickoff(row, player)
        _set_calendar(row, player)
        if isinstance(player.get("own_xp_siguientes"), list) and not row.get("xp_siguientes"):
            row["xp_siguientes"] = player["own_xp_siguientes"]
        if player.get("af_alerta_bajada") is True:
            row["af_alerta_bajada"] = True
        if isinstance(player.get("own_sancion_partidos"), int) and not isinstance(player.get("own_sancion_partidos"), bool):
            row["sancion_partidos"] = player["own_sancion_partidos"]
        if exclusion_from_status(player.get("player_status") if isinstance(player.get("player_status"), str) else None):
            row["excluded"] = True

    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    # La plantilla oficial va por detrás de la actividad (9 nov: Correia seguía
    # con su dueño y su candado 48 min después de que otro lo fichara). La
    # actividad manda: el jugador pasa a su nuevo dueño y, sin su cláusula
    # nueva, no entra como en peligro ni como clausulazo.
    from toolbox.clause_board import _latest_takers

    needs_doc = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    takers = _latest_takers(needs_doc.get("ledgers"))
    own_team_id = next(
        (_pid(sq.get("team_id")) for sq in squads.get("squads") or [] if isinstance(sq, dict) and sq.get("is_self") is True),
        None,
    )
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        team_id = _pid(squad.get("team_id"))
        is_self = squad.get("is_self") is True
        manager = squad.get("manager_name") if isinstance(squad.get("manager_name"), str) else None
        for player in squad.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = _pid(player.get("player_id"))
            if player_id is None:
                continue
            row = _slot(records, player_id)
            _set_name(row, player)
            _set_points(row, player, prefer=False)
            _set_price(row, player)
            taker = takers.get(player_id)
            moved = bool(taker) and _pid(taker.get("team_id")) not in (None, team_id)
            if moved:
                new_team = _pid(taker.get("team_id"))
                row["team_id"] = new_team
                row["is_self"] = new_team == own_team_id
                row["manager"] = taker.get("manager_name") if isinstance(taker.get("manager_name"), str) else None
                row["traspasado"] = {"desde": team_id, "at": taker.get("at"), "importe": taker.get("amount_eur")}
            else:
                row["team_id"] = team_id
                row["is_self"] = is_self
                row["manager"] = manager
            # Cláusula, escudo y candado de la plantilla vieja ya no valen si se movió.
            if not moved:
                clause = _int(player.get("buyout_clause"))
                if clause is not None and clause > 0:
                    row["clause"] = clause
                if player.get("is_shielded") is True:
                    row["shielded"] = True
                lock = player.get("clause_lock")
                if isinstance(lock, dict):
                    row["clause_lock"] = lock
            if exclusion_from_status(player.get("player_status") if isinstance(player.get("player_status"), str) else None):
                row["excluded"] = True
            if not row.get("recientes"):
                row["recientes"] = _recientes(player)
            if player.get("tiene_oferta_laliga") is True and not moved:
                row["tiene_oferta_laliga"] = True
            if is_self and not moved:
                for key in _OFERTA_KEYS:
                    importe = _int(player.get(key))
                    if importe is not None and importe > 0:
                        row.setdefault("ofertas_directas", []).append({"comprador": LALIGA, "importe": importe})
                        break

    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    for listing in market.get("listings") or []:
        if not isinstance(listing, dict):
            continue
        player_id = _pid(listing.get("player_id"))
        if player_id is None:
            continue
        row = _slot(records, player_id)
        _set_name(row, listing)
        _set_points(row, listing, prefer=False)
        _set_price(row, listing)
        _set_difficulty(row, listing)
        row["on_market"] = True
        row["bids"] = [bid for bid in listing.get("bids") or [] if isinstance(bid, dict)]
        seller = _pid(listing.get("seller_team_id"))
        if seller:
            row["seller_team_id"] = seller
        sale = _int(listing.get("sale_price"))
        if sale is not None and sale > 0:
            row["sale_price"] = sale
        leading = _int(listing.get("leading_bid"))
        if leading is not None and leading > 0:
            row["leading_bid"] = leading
        bid_count = _int(listing.get("bid_count"))
        offer_count = _int(listing.get("offer_count"))
        if bid_count is not None and bid_count >= 0:
            row["bid_count"] = bid_count
        if offer_count is not None and offer_count >= 0:
            row["offer_count"] = offer_count
        if _expires_today(listing.get("listing_expires_at"), now):
            row["caduca_hoy"] = True
        if listing.get("tiene_oferta_laliga") is True:
            row["tiene_oferta_laliga"] = True

    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else {}
    excluded_ids = {
        pid
        for row in (optimize.get("excluded") or [])
        if isinstance(row, dict)
        for pid in [_pid(row.get("player_id"))]
        if pid
    }
    for key, in_xi in (("xi", True), ("benched", False), ("excluded", False)):
        for player in optimize.get(key) or []:
            if not isinstance(player, dict):
                continue
            player_id = _pid(player.get("player_id"))
            if player_id is None:
                continue
            row = _slot(records, player_id)
            _set_name(row, player)
            _set_points(row, player, prefer=True)
            row["is_self"] = True
            if in_xi:
                row["in_xi"] = True
            if key == "excluded" or player_id in excluded_ids or player.get("excluded_reason"):
                row["excluded"] = True
    trends_doc = board.get("trends") if isinstance(board.get("trends"), dict) else None
    _saltar_jornada_bloqueada(records, proximo_cierre(trends_doc, now))
    return records


def _ofertas_propias(
    row: dict[str, Any],
    own_id: str | None,
    nombres: dict[str, str],
) -> list[dict[str, Any]]:
    """Ofertas que recibe un jugador mío: directas, pujas de su anuncio y la marca de LaLiga."""
    ofertas = [dict(oferta) for oferta in row.get("ofertas_directas") or []]
    en_mi_anuncio = row.get("on_market") is True and (row.get("seller_team_id") in {None, own_id} or row.get("is_self") is True)
    if en_mi_anuncio:
        for bid in row.get("bids") or []:
            importe = _int(bid.get("amount"))
            if importe is None or importe <= 0:
                continue
            equipo = _pid(bid.get("team_id"))
            if equipo is not None and equipo == own_id:
                continue
            if equipo is None:
                comprador = LALIGA
            else:
                comprador = nombres.get(equipo) or (bid.get("manager_name") if isinstance(bid.get("manager_name"), str) else None) or "Rival"
            ofertas.append({"comprador": comprador, "importe": importe})
    if row.get("tiene_oferta_laliga") is True and not any(oferta["comprador"] == LALIGA for oferta in ofertas):
        ofertas.append({"comprador": LALIGA, "importe": None})
    return ofertas


def _xi_and_bench(records: dict[str, dict[str, Any]], board: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else {}
    xi_ids = [_pid(row.get("player_id")) for row in (optimize.get("xi") or []) if isinstance(row, dict)]
    xi_ids = [player_id for player_id in xi_ids if player_id]
    bench_ids = [_pid(row.get("player_id")) for row in (optimize.get("benched") or []) if isinstance(row, dict)]
    bench_ids = [player_id for player_id in bench_ids if player_id and player_id not in xi_ids]
    if len(xi_ids) == 11:
        xi = [_lineup_row(records[player_id]) for player_id in xi_ids if player_id in records]
        bench = [_lineup_row(records[player_id]) for player_id in bench_ids if player_id in records and not records[player_id].get("excluded")]
        if len(xi) == 11:
            return xi, bench
    owned = [
        _lineup_row(row)
        for row in records.values()
        if row.get("is_self") is True and not row.get("excluded") and row.get("position") in POSITIONS and row.get("jornada") is not None
    ]
    solved = solve_best_xi(owned)
    if not solved["ok"]:
        return [], owned
    chosen = set(solved["player_ids"])
    xi = [row for row in owned if row["player_id"] in chosen]
    bench = [row for row in owned if row["player_id"] not in chosen]
    for row in records.values():
        if row.get("player_id") in chosen:
            row["in_xi"] = True
    return xi, bench


def _lineup_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row.get("player_id"),
        "nombre": row.get("nombre"),
        "name": row.get("nombre"),
        "position": row.get("position"),
        "jornada": float(row["jornada"]) if isinstance(row.get("jornada"), (int, float)) and not isinstance(row.get("jornada"), bool) else 0.0,
        "si_titular": row.get("si_titular"),
        "techo": row.get("techo"),
        "p_titular": row.get("p_titular"),
    }


def _poder_map(board: dict[str, Any], cash: dict[str, int]) -> dict[str, int]:
    """Caja más crédito: el tope legal del libro, o la caja más la deuda del equipo."""
    poder = dict(cash)
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        team_id = _pid(squad.get("team_id"))
        debt = squad.get("debt_limit_eur")
        if team_id and team_id in cash and isinstance(debt, int) and not isinstance(debt, bool):
            poder[team_id] = max(poder[team_id], cash[team_id] + max(0, debt))
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    for ledger in needs.get("ledgers") or []:
        if not isinstance(ledger, dict):
            continue
        team_id = _pid(ledger.get("team_id"))
        legal = ledger.get("legal_bid_limit")
        if team_id and isinstance(legal, int) and not isinstance(legal, bool):
            poder[team_id] = max(poder.get(team_id, legal), legal)
    return poder


def _rivals(records: dict[str, dict[str, Any]], cash: dict[str, int], poder: dict[str, int] | None = None) -> list[dict[str, Any]]:
    by_team: dict[str, dict[str, Any]] = {}
    for row in records.values():
        if row.get("is_self") is True or not row.get("team_id"):
            continue
        team_id = str(row["team_id"])
        bucket = by_team.setdefault(
            team_id,
            {"team_id": team_id, "manager": row.get("manager"), "counts": {position: 0 for position in POSITIONS}},
        )
        if row.get("manager") and not bucket.get("manager"):
            bucket["manager"] = row.get("manager")
        position = row.get("position")
        if position in POSITIONS and not row.get("excluded"):
            bucket["counts"][position] += 1
    salida: list[dict[str, Any]] = []
    caja_credito = poder or cash
    for team_id, bucket in by_team.items():
        counts = bucket["counts"]
        thin = [position for position in POSITIONS if counts[position] <= MIN_HEADCOUNT[position]]
        saldo = cash.get(team_id)
        rojo = estado_rojo(saldo)
        salida.append(
            {
                "team_id": team_id,
                "manager": bucket.get("manager"),
                "saldo": saldo,
                "poder": caja_credito.get(team_id, saldo),
                "posiciones": thin,
                "huecos": [position for position in POSITIONS if counts[position] == 0],
                "flojas": [position for position in POSITIONS if 0 < counts[position] <= MIN_HEADCOUNT[position]],
                "en_rojo": rojo,
                "en_rojo_seguro": rojo == ROJO_SEGURO,
            }
        )
    return salida


def _empty_plan(cash: int | None, ratio: float) -> dict[str, Any]:
    return {
        "ok": True,
        "mejora_puntos_jornada": 0.0,
        "saldo_al_final": cash,
        "nota": 0,
        "veredicto": "Opcional",
        "acciones": [],
        "formacion": None,
        "puntos_once": 0.0,
        "puntos_once_actual": 0.0,
        "ratio_mercado": round(ratio, 2) if ratio else None,
        "once": [],
        "en_radar": [],
        "dias_al_cierre": None,
        "penalizacion_liquidez": 0.0,
        "factor_ajuste": round(FACTOR_AJUSTE, 4),
        "modo_liquidez": "SIN_RELOJ",
    }


def build_strategy(board: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Calcula la capa y la deja lista para estampar en el JSON."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    records = _collect(board if isinstance(board, dict) else {}, current)
    titulares = [
        (float(row["valor"]), float(row["jornada"]))
        for row in records.values()
        if isinstance(row.get("valor"), int)
        and row["valor"] > 0
        and isinstance(row.get("jornada"), (int, float))
        and not isinstance(row.get("jornada"), bool)
        and float(row["jornada"]) > 0
        and isinstance(row.get("p_titular"), (int, float))
        and not isinstance(row.get("p_titular"), bool)
        and float(row["p_titular"]) >= _TITULAR_RATIO
    ]
    mercado = ratio_mercado_liga(titulares)
    ratio = float(mercado["ratio_mercado"])
    # Una sola curva de valor justo para previsión, pujas, ventas y cláusulas.
    curva = curva_valor_justo(titulares)

    previsiones: dict[str, dict[str, Any]] = {}
    for row in records.values():
        valor = row.get("valor")
        jornada = row.get("jornada")
        player_id = row.get("player_id")
        if not isinstance(player_id, str) or not isinstance(valor, int) or valor <= 0:
            continue
        if not isinstance(jornada, (int, float)) or isinstance(jornada, bool):
            continue
        try:
            previsto = proyectar_7d(
                valor,
                float(row.get("delta_hoy") or 0.0),
                float(row.get("delta_ayer") or 0.0),
                float(jornada),
                ratio,
                en_forma=_en_forma(row),
                curva=curva,
                puntos_jornada=_puntos_ultima(row),
                post_jornada=datetime.now(_MADRID).weekday() in (0, 1),
            )
        except (TypeError, ValueError):
            continue
        previsiones[player_id] = previsto

    xi, bench = _xi_and_bench(records, board if isinstance(board, dict) else {})
    war = war_del_once(xi, bench)
    caps = capitanes(xi)
    cajas = _cash_map(board if isinstance(board, dict) else {})
    rivales = _rivals(records, cajas, _poder_map(board if isinstance(board, dict) else {}, cajas))
    propio = own_squad(board.get("squads") if isinstance(board, dict) and isinstance(board.get("squads"), dict) else None)
    own_id = _pid(propio.get("team_id")) if isinstance(propio, dict) else None
    saldo = propio.get("cash") if isinstance(propio, dict) and isinstance(propio.get("cash"), int) and not isinstance(propio.get("cash"), bool) else None
    if own_id and own_id in cajas:
        saldo = cajas[own_id]

    valor_equipo = sum(
        int(row["valor"])
        for row in records.values()
        if row.get("is_self") is True and isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool)
    )
    # Lo que puedes pujar de verdad: caja + crédito legal (20 % del valor del equipo).
    # Una puja admite deuda; una cláusula no. Sin saldo conocido, sin poder.
    poder_pujas = saldo + int(valor_equipo * DEUDA_PCT_EQUIPO) if isinstance(saldo, int) else None
    notas = _notas_mercado(records, previsiones, poder_pujas, caja=saldo)
    sobrepuja_liga = _sobrepuja_liga()
    huecos = _puestos_en_hueco(records)

    pujas: dict[str, dict[str, Any]] = {}
    for row in records.values():
        player_id = row.get("player_id")
        valor = row.get("valor")
        if not isinstance(player_id, str) or not isinstance(valor, int) or valor <= 0:
            continue
        row["supervivencia"] = _es_parche_supervivencia(row, huecos)
        justo = previsiones.get(player_id, {}).get("valor_justo")
        if not isinstance(justo, int):
            jornada = row.get("jornada")
            justo = valor_justo_jugador(float(jornada), ratio, curva) if isinstance(jornada, (int, float)) and not isinstance(jornada, bool) else 0
        previsto_pct = previsiones.get(player_id, {}).get("pct") if isinstance(previsiones.get(player_id), dict) else None
        pujas[player_id] = calcular_pujas(
            valor,
            float(row.get("delta_hoy") or 0.0),
            int(justo or 0),
            tu_saldo=poder_pujas,
            rivales=rivales,
            posicion=row.get("position") if isinstance(row.get("position"), str) else None,
            prevision_7d_pct=previsto_pct,
            dificultad=row.get("dificultad") if isinstance(row.get("dificultad"), str) else None,
            clave=player_id,
            supervivencia=row["supervivencia"] is True,
        )
        techo = techo_sobrepuja_eur(valor, supervivencia=row["supervivencia"] is True)
        pujas[player_id]["techo_sobrepuja"] = None if techo is None else int(math.floor(techo))
        _aplicar_anti_pizarra(pujas[player_id], row, notas.get(player_id), previsto_pct, saldo)
        # Demanda alta en el mercado: el escalón de liga también se enseña fuera del plan.
        base_mercado = (
            puja_unica(pujas[player_id], row)
            if row.get("on_market") is True and row.get("is_self") is not True
            else None
        )
        _aplicar_competitiva(
            pujas[player_id],
            base=base_mercado if pujas[player_id].get("alta_demanda") is True else None,
            maxima=pujas[player_id].get("puja_maxima"),
            sobrepuja=sobrepuja_liga,
            margen=(saldo - base_mercado) if isinstance(saldo, int) and isinstance(base_mercado, int) else None,
            clave=player_id,
            techo_absoluto=pujas[player_id].get("techo_sobrepuja"),
        )

    forzadas: dict[str, str] = {}
    ventas: list[dict[str, Any]] = []
    for row in records.values():
        if row.get("is_self") is True:
            continue
        team_id = row.get("team_id") or row.get("seller_team_id")
        if not isinstance(team_id, str) or cajas.get(team_id, 0) >= 0:
            continue
        player_id = row.get("player_id")
        if not isinstance(player_id, str):
            continue
        previsto = previsiones.get(player_id)
        pct = float(previsto["pct"]) if isinstance(previsto, dict) and isinstance(previsto.get("pct"), (int, float)) else None
        en_mercado = row.get("on_market") is True or row.get("seller_team_id") == team_id
        alta = pct is not None and pct >= PREVISION_ALTA_PCT
        if not en_mercado and not alta:
            continue
        manager = row.get("manager") or "Un rival"
        motivo = (
            f"{manager} tiene la caja en negativo y necesita vender antes del viernes para que su jornada puntúe."
        )
        forzadas[player_id] = motivo
        ventas.append(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "team_id": team_id,
                "manager": row.get("manager"),
                "posicion": row.get("position"),
                "prevision_7d_pct": previsto.get("prevision_7d_pct") if isinstance(previsto, dict) else None,
                "en_mercado": en_mercado,
                "venta_forzada_rival": True,
                "detalle": motivo,
            }
        )

    plan = _plan(
        records,
        xi,
        war,
        saldo,
        ratio,
        rivales,
        board if isinstance(board, dict) else {},
        current,
        own_id,
        previsiones,
        notas,
        curva=curva,
    )
    _sellar_pujas_plan(plan, pujas, sobrepuja_liga)
    consejos = _consejos(records, war, plan, own_id)
    auditoria = _auditar_ventas(records, war, plan, previsiones, saldo, own_id)
    clausulas = _asesorar_clausulas(
        records,
        war,
        previsiones,
        rivales,
        saldo,
        ratio,
        board if isinstance(board, dict) else {},
        current,
        dias_al_cierre=_num(plan.get("dias_al_cierre")) if isinstance(plan, dict) else None,
    )
    _no_blindar_ventas_del_plan(clausulas, plan_ventas(plan), records)
    if isinstance(plan, dict):
        plan["alertas_clausulas"] = clausulas.get("alertas_clausulas") or []
        trading = plan.get("trading")
        if isinstance(trading, dict):
            trading["alertas_clausulas"] = plan["alertas_clausulas"]
    return {
        "ratio_mercado": round(ratio, 2),
        "ratio_detalle": {
            "ratio_mercado": round(ratio, 2),
            "referencia_eur_por_punto": EUROS_POR_PUNTO,
            "xp_medio_titulares": mercado.get("xp_medio_titulares"),
            "valor_medio_titulares": mercado.get("valor_medio_titulares"),
            "muestra_titulares": mercado.get("muestra_titulares"),
            "usa_referencia": mercado.get("usa_referencia") is True,
        },
        "previsiones": previsiones,
        "calendarios": {pid: row["calendario"] for pid, row in records.items() if row.get("calendario")},
        "war": war,
        "pujas": pujas,
        "consejos": consejos,
        "forzadas": forzadas,
        "ventas_forzadas": ventas,
        "capitan_seguro": caps.get("capitan_seguro"),
        "capitan_remontada": caps.get("capitan_remontada"),
        "plan_fichajes": plan,
        "compras_plan": plan_compras(plan),
        "auditoria_ventas": auditoria["filas"],
        "resumen_ventas": auditoria["resumen"],
        "asesor_clausulas": clausulas,
        "radar_anti_robo": clausulas.get("radar_anti_robo") or [],
        "notas_mercado": notas,
        "propios": {pid for pid, row in records.items() if row.get("is_self") is True},
        "caja": saldo,
        "poder_pujas": poder_pujas,
    }


def _auditar_ventas(
    records: dict[str, dict[str, Any]],
    war: dict[str, float],
    plan: dict[str, Any],
    previsiones: dict[str, dict[str, Any]],
    saldo: int | None,
    own_id: str | None,
) -> dict[str, Any]:
    nombres = {
        row["team_id"]: row["manager"]
        for row in records.values()
        if isinstance(row.get("team_id"), str) and isinstance(row.get("manager"), str) and row.get("is_self") is not True
    }
    jugadores: list[dict[str, Any]] = []
    for row in records.values():
        player_id = row.get("player_id")
        if row.get("is_self") is not True or not isinstance(player_id, str):
            continue
        valor = row.get("valor")
        previsto = previsiones.get(player_id) or {}
        jugadores.append(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "position": row.get("position") if row.get("position") in POSITIONS else None,
                "valor": valor if isinstance(valor, int) and not isinstance(valor, bool) else None,
                "valor_justo": previsto.get("valor_justo"),
                "jornada": row.get("jornada"),
                "pct": _pct_previsto(previsiones, player_id),
                "tu_once_pierde_sin_el": war.get(player_id),
                "elegible": row.get("excluded") is not True and row.get("position") in POSITIONS,
                "en_mercado": row.get("on_market") is True and row.get("seller_team_id") in {None, own_id},
                "ofertas": _ofertas_propias(row, own_id, nombres),
            }
        )
    try:
        return evaluar_ventas_y_ofertas(
            jugadores,
            plan=plan,
            saldo=saldo,
            dias_al_cierre=_num(plan.get("dias_al_cierre")) if isinstance(plan, dict) else None,
        )
    except Exception:
        logger.exception("auditoría de ventas")
        return {"resumen": _resumen_vacio(), "filas": []}


def _cierre_ventana(board: dict[str, Any], now: datetime) -> datetime | None:
    """Cierre del mercado de clausulazos: 24 h antes del primer partido de la jornada."""
    try:
        from toolbox.jornada_plan import build_clock

        trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
        squads = board.get("squads") if isinstance(board.get("squads"), dict) else None
        _, _, cierre = build_clock(trends=trends, squads=squads, decisions=[], now=now)
    except Exception:
        logger.exception("cierre de la ventana de cláusulas")
        return None
    texto = cierre.get("at") if isinstance(cierre, dict) else None
    if not isinstance(texto, str):
        return None
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _inicio_jornada(board: dict[str, Any], now: datetime) -> tuple[datetime | None, bool]:
    """Inicio de la próxima jornada que se puede tocar; sin dato, el próximo viernes 21:00 (estimado).

    Con la jornada en curso es el primer saque de la siguiente: el partido de
    esta tarde ya no abre ni cierra nada.
    """
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    try:
        from toolbox.jornada_plan import next_lock

        texto = next_lock(trends, now=now)
        if isinstance(texto, str):
            momento = datetime.fromisoformat(texto)
            return (momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)), False
    except Exception:
        logger.exception("inicio de la jornada")
    return inicio_jornada_estimado(now), True


def _clausulas_vacias() -> dict[str, Any]:
    return {
        "resumen": {
            "en_peligro": 0,
            "riesgo_alto": 0,
            "coste_proteger_eur": 0,
            "seguros": 0,
            "bloqueadas": 0,
            "clausulazos_listos": 0,
            "clausulazos": 0,
            "ventana_cierra": None,
            "ventana_abierta": True,
        },
        "proteger": [],
        "clausulazos": [],
        "reventa": [],
        "radar_anti_robo": [],
        "alertas_clausulas": [],
    }


def _puestos_liga(board: dict[str, Any]) -> dict[str, int]:
    """``team_id`` → puesto en la clasificación, si la foto lo trae."""
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    puestos: dict[str, int] = {}
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict):
            continue
        team_id = _pid(squad.get("team_id"))
        puesto = _int(squad.get("rank"))
        if team_id and puesto is not None and puesto > 0:
            puestos[team_id] = puesto
    return puestos


def _plantillas_rivales(records: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Plantilla de cada rival con puesto, sanidad y puntos esperados."""
    plantillas: dict[str, list[dict[str, Any]]] = {}
    for row in records.values():
        team_id = row.get("team_id")
        if row.get("is_self") is True or not isinstance(team_id, str) or not team_id:
            continue
        if not isinstance(row.get("player_id"), str):
            continue
        plantillas.setdefault(team_id, []).append(
            {
                "player_id": row["player_id"],
                "position": row.get("position"),
                "sano": row.get("excluded") is not True,
                "jornada": row.get("jornada"),
            }
        )
    return plantillas


def _alternativas_reposicion(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Jugadores que se pueden comprar hoy: en el mercado (libres o anunciados por un rival) a su
    valor, por puja; el resto de ajenos, a su cláusula."""
    salida: list[dict[str, Any]] = []
    for row in records.values():
        if row.get("is_self") is True or row.get("excluded") is True:
            continue
        player_id = row.get("player_id")
        if not isinstance(player_id, str) or row.get("position") not in POSITIONS:
            continue
        if row.get("on_market") is True:
            # Libre de LaLiga o anunciado por un rival: se compra pujando (admite crédito).
            coste = row.get("valor")
            via = "puja"
        elif row.get("team_id") and row.get("shielded") is not True:
            coste = row.get("clause")
            via = "clausula"
        else:
            continue
        if isinstance(coste, bool) or not isinstance(coste, int) or coste <= 0:
            continue
        salida.append(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "position": row["position"],
                "coste": coste,
                "xp": row.get("jornada"),
                # Una puja admite crédito; una cláusula no. El recambio urgente se busca por puja.
                "via": via,
            }
        )
    return salida


def _rivales_con_premio(
    rivales: list[dict[str, Any]],
    board: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    """Con la jornada en juego, la caja del rival incluye el premio que cobra al cerrarla.

    El radar de cláusulas mira quién puede pagar el lunes, no quién puede hoy.
    """
    try:
        from toolbox.player_history import actas_en_cache

        vivo = construir_jornada_en_juego(
            board.get("squads") if isinstance(board.get("squads"), dict) else None,
            board.get("trends") if isinstance(board.get("trends"), dict) else None,
            actas_en_cache(),
            now=now,
        )
    except Exception:
        logger.exception("premio de rivales")
        return rivales
    if vivo.get("activa") is not True:
        return rivales
    premios = {
        str(e["team_id"]): int(e["premio_jornada_eur"])
        for e in vivo.get("clasificacion_jornada") or []
        if not e.get("is_self") and e.get("team_id") is not None
    }
    salida: list[dict[str, Any]] = []
    for rival in rivales:
        premio = premios.get(str(rival.get("team_id"))) if isinstance(rival, dict) else None
        saldo = rival.get("saldo") if isinstance(rival, dict) else None
        if premio and isinstance(saldo, (int, float)) and not isinstance(saldo, bool):
            salida.append({**rival, "saldo": saldo + premio, "premio_jornada_eur": premio})
        else:
            salida.append(rival)
    return salida


def _asesorar_clausulas(
    records: dict[str, dict[str, Any]],
    war: dict[str, float],
    previsiones: dict[str, dict[str, Any]],
    rivales: list[dict[str, Any]],
    saldo: int | None,
    ratio: float,
    board: dict[str, Any],
    now: datetime,
    *,
    dias_al_cierre: float | None = None,
) -> dict[str, Any]:
    propios: list[dict[str, Any]] = []
    ajenos: list[dict[str, Any]] = []
    puestos = _puestos_liga(board)
    plantillas = _plantillas_rivales(records)
    alternativas = _alternativas_reposicion(records)
    rivales = _rivales_con_premio(rivales, board, now)
    for row in records.values():
        player_id = row.get("player_id")
        if not isinstance(player_id, str):
            continue
        valor = row.get("valor") if isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool) else None
        base = {
            "player_id": player_id,
            "nombre": row.get("nombre"),
            "position": row.get("position") if row.get("position") in POSITIONS else None,
            "valor": valor,
            "clausula": row.get("clause"),
            "blindado": row.get("shielded") is True,
            "bloqueo": row.get("clause_lock"),
            "jornada": row.get("jornada"),
            "p_titular": row.get("p_titular"),
            "pct": _pct_previsto(previsiones, player_id),
            "valor_justo": (previsiones.get(player_id) or {}).get("valor_justo"),
        }
        if row.get("is_self") is True:
            propios.append(
                {
                    **base,
                    "en_xi": row.get("in_xi") is True,
                    "tu_once_pierde_sin_el": war.get(player_id),
                    "elegible": row.get("excluded") is not True and base["position"] is not None,
                }
            )
        elif row.get("team_id"):
            ajenos.append(
                {
                    **base,
                    "manager": row.get("manager"),
                    "team_id": row.get("team_id"),
                    "valor_justo": (previsiones.get(player_id) or {}).get("valor_justo"),
                }
            )
    inicio, inicio_estimado = _inicio_jornada(board, now)
    radar = auditar_clausulas_plantilla(
        [
            {
                "player_id": fila.get("player_id"),
                "nombre": fila.get("nombre"),
                "position": fila.get("position"),
                "clausula": fila.get("clausula"),
                "valor_mercado": fila.get("valor"),
                "prevision_7d_pct": fila.get("pct"),
                "clausulaAbre": fila.get("bloqueo"),
                "blindado": fila.get("blindado") is True,
                "jornada": fila.get("jornada"),
            }
            for fila in propios
        ],
        [
            {"dineroEstimado": rival.get("saldo"), "manager": rival.get("manager"), "team_id": rival.get("team_id")}
            for rival in rivales
            if isinstance(rival, dict)
        ],
        ahora=now,
        alternativas=alternativas,
        # Se pueden pagar hasta que cierra el mercado de clausulazos (24 h antes del saque).
        hasta=_cierre_ventana(board, now) or inicio,
    )
    try:
        informe = evaluar_clausulas(
            propios=propios,
            ajenos=ajenos,
            rivales=[
                {
                    "team_id": rival.get("team_id"),
                    "manager": rival.get("manager"),
                    "saldo": rival.get("saldo"),
                    "posiciones": rival.get("posiciones"),
                    "puesto_liga": puestos.get(str(rival.get("team_id"))),
                    "plantilla": plantillas.get(str(rival.get("team_id")), []),
                }
                for rival in rivales
            ],
            saldo=saldo,
            ratio=ratio,
            ahora=now,
            cierre=_cierre_ventana(board, now),
            dias_al_cierre=dias_al_cierre,
            alternativas=alternativas,
            inicio_jornada=inicio,
        )
        informe["resumen"]["inicio_jornada_estimado"] = inicio_estimado
    except Exception:
        logger.exception("asesor de cláusulas")
        informe = _clausulas_vacias()
    informe["radar_anti_robo"] = radar
    informe["alertas_clausulas"] = alertas_escudo_francotirador(
        [fila for fila in propios if fila.get("en_xi") is True],
        rivales,
        ajenos,
        caja_propia=saldo,
        ventas_hoy=_ventas_con_oferta_hoy(records),
    )
    return informe


def _ventas_con_oferta_hoy(records: dict[str, dict[str, Any]]) -> int:
    """Lo que entra hoy si aceptas las ofertas de LaLiga que ya tienes (la mejor por jugador)."""
    total = 0
    for row in records.values():
        if row.get("is_self") is not True:
            continue
        importes = [
            oferta.get("importe")
            for oferta in row.get("ofertas_directas") or []
            if isinstance(oferta, dict) and isinstance(oferta.get("importe"), int) and not isinstance(oferta.get("importe"), bool)
        ]
        if importes:
            total += max(importes)
    return total


def _resumen_vacio() -> dict[str, Any]:
    return {
        "ofertas_activas": 0,
        "total_ofertas_eur": 0,
        "spread_medio_laliga_pct": None,
        "ventas_recomendadas_hoy": 0,
        "jugadores": 0,
    }


def _pct_previsto(previsiones: dict[str, dict[str, Any]], player_id: str) -> float | None:
    previsto = previsiones.get(player_id)
    if not isinstance(previsto, dict):
        return None
    pct = previsto.get("pct")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    return float(pct)


_MINIMOS_ONCE = {"POR": 1, "DEF": 3, "MC": 3, "DEL": 1}


def _puestos_en_hueco(records: dict[str, dict[str, Any]]) -> set[str]:
    """Puestos donde la plantilla no llega al mínimo de línea: sin ellos el viernes es 0."""
    cuentas = dict.fromkeys(_MINIMOS_ONCE, 0)
    for row in records.values():
        if row.get("is_self") is not True or row.get("excluded") is True:
            continue
        puesto = row.get("position")
        if puesto in cuentas:
            cuentas[puesto] += 1
    return {puesto for puesto, minimo in _MINIMOS_ONCE.items() if cuentas[puesto] < minimo}


def _es_parche_supervivencia(row: dict[str, Any], huecos: set[str]) -> bool:
    valor = row.get("valor") if isinstance(row.get("valor"), int) else row.get("market_value")
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor <= 0 or valor >= PARCHE_SUPERVIVENCIA_EUR:
        return False
    return row.get("position") in huecos


def _aplicar_anti_pizarra(
    puja: dict[str, Any],
    row: dict[str, Any],
    nota: dict[str, Any] | None,
    pct: float | None,
    saldo: int | None,
) -> None:
    """Con demanda alta sube ``puja_recomendada`` por encima del escalón de La Pizarra."""
    valor = row.get("valor") or row.get("sale_price") or 0
    maxima = puja.get("puja_maxima") if isinstance(puja.get("puja_maxima"), int) else None
    techo = techo_sobrepuja_eur(
        valor if isinstance(valor, (int, float)) and not isinstance(valor, bool) else 0,
        supervivencia=row.get("supervivencia") is True,
    )
    if techo is not None:
        maxima = int(math.floor(techo)) if maxima is None else min(maxima, int(math.floor(techo)))
    info = puja_anti_pizarra(
        valor,
        row.get("delta_hoy"),
        nota_mercado=nota.get("nota_mercado") if isinstance(nota, dict) else None,
        prevision_7d_pct=pct,
        clave=row.get("player_id"),
        maxima=maxima,
        saldo=saldo,
    )
    puja["puja_pizarra"] = info["puja_pizarra"]
    puja["puja_anti_pizarra"] = info["puja_anti_pizarra"]
    puja["diferencial_anti_pizarra_eur"] = info["diferencial_anti_pizarra_eur"]
    puja["alta_demanda"] = info["alta_demanda"]
    anti = info["puja_anti_pizarra"]
    if isinstance(anti, int) and (techo is None or anti <= techo):
        puja["puja_recomendada"] = anti
        smart = puja.get("puja_smart")
        if not isinstance(smart, int) or smart < anti:
            puja["puja_smart"] = anti


def _sobrepuja_liga() -> dict[str, Any] | None:
    """Sobrepuja media de las subastas perdidas (Marcador). ``None`` sin evidencia o sin base de datos."""
    try:
        from toolbox.engine_calibration import sobrepuja_de_liga

        return sobrepuja_de_liga()
    except Exception:  # noqa: BLE001 — sin historial no hay escalón, pero el plan sigue
        logger.debug("Sin historial de sobrepuja de liga", exc_info=True)
        return None


def _aplicar_competitiva(
    destino: dict[str, Any],
    *,
    base: Any,
    maxima: Any,
    sobrepuja: dict[str, Any] | None,
    margen: Any = None,
    clave: Any = None,
    techo_absoluto: Any = None,
) -> None:
    """Escribe ``puja_competitiva_liga`` y el porcentaje que la sostiene, o los deja en ``None``."""
    estimada = sobrepuja.get("estimada") if isinstance(sobrepuja, dict) else None
    cifra = puja_competitiva_liga(
        base, maxima, estimada, margen=margen, clave=clave, techo_absoluto=techo_absoluto
    )
    destino["puja_competitiva_liga"] = cifra
    destino["sobrepuja_liga_pct"] = round(float(estimada) * 100.0, 1) if cifra is not None else None
    destino["sobrepuja_liga_muestra"] = (
        {"perdidas": sobrepuja.get("perdidas"), "con_sobrepuja": sobrepuja.get("con_sobrepuja")}
        if cifra is not None and isinstance(sobrepuja, dict)
        else None
    )


#: Tipos de acción del plan que sacan a un jugador de tu plantilla.
_TIPOS_VENTA_PLAN = frozenset({"VENDE", "VENDER HOY", "ESCAPARATE"})
#: Momentos del plan que son de verdad parte del plan (no radar ni alternativas).
_MOMENTOS_PLAN = frozenset({"hoy", "condicional", "luego"})
#: Vetos de Mercado que solo dicen «hoy no te llega la caja».
_VETOS_DE_CAJA = frozenset({"negative_cash", "sin_caja", "caja", "presupuesto_dia", "caja_otros_mercados"})


def plan_ventas(plan: Any) -> dict[str, str]:
    """``player_id -> nombre`` de los jugadores que el plan de hoy vende o pone a la venta."""
    salida: dict[str, str] = {}
    for accion in (plan or {}).get("acciones") or [] if isinstance(plan, dict) else []:
        if not isinstance(accion, dict) or accion.get("tipo") not in _TIPOS_VENTA_PLAN:
            continue
        if accion.get("momento") not in _MOMENTOS_PLAN:
            continue
        player_id = accion.get("player_id")
        if isinstance(player_id, str):
            salida[player_id] = str(accion.get("nombre") or player_id)
    return salida


def plan_compras(plan: Any) -> dict[str, dict[str, Any]]:
    """Pujas del plan: ``player_id -> {euros, ventas (nombres), detalle}``."""
    if not isinstance(plan, dict):
        return {}
    nombres = plan_ventas(plan)
    cobertura = plan.get("cobertura_pujas") if isinstance(plan.get("cobertura_pujas"), dict) else {}
    atadas = {
        item.get("player_id"): [nombres.get(v.get("player_id"), v.get("player_id")) for v in item.get("ventas") or []]
        for item in cobertura.get("pujas") or []
        if isinstance(item, dict)
    }
    salida: dict[str, dict[str, Any]] = {}
    for accion in plan.get("acciones") or []:
        if not isinstance(accion, dict) or accion.get("tipo") != "PUJA" or accion.get("momento") not in _MOMENTOS_PLAN:
            continue
        player_id = accion.get("player_id")
        euros = accion.get("euros")
        if not isinstance(player_id, str) or not isinstance(euros, int) or isinstance(euros, bool):
            continue
        salida[player_id] = {
            "euros": euros,
            "ventas": [str(nombre) for nombre in atadas.get(player_id) or []],
            "ventas_hoy": [
                str(a.get("nombre") or a.get("player_id"))
                for a in plan.get("acciones") or []
                if isinstance(a, dict) and a.get("tipo") == "VENDER HOY"
            ],
            "mejora_neta": accion.get("mejora_neta"),
        }
    return salida


def puja_unica(puja: dict[str, Any] | None, row: dict[str, Any]) -> int | None:
    """La cifra de puja que enseñan Inicio, Mercado y la ficha: la misma que paga el plan.

    ``max(puja recomendada, precio de salida, puja líder)``, sin pasar del
    techo (``puja_maxima``). Por encima del techo no hay cifra: no se puja.
    """
    if not isinstance(puja, dict):
        return None
    recomendada = puja.get("puja_recomendada")
    if not isinstance(recomendada, int) or isinstance(recomendada, bool):
        return None
    ask = row.get("sale_price") if isinstance(row.get("sale_price"), int) and not isinstance(row.get("sale_price"), bool) else 0
    lead = row.get("leading_bid") if isinstance(row.get("leading_bid"), int) and not isinstance(row.get("leading_bid"), bool) else 0
    coste = max(recomendada, ask, lead)
    maxima = puja.get("puja_maxima")
    if isinstance(maxima, int) and not isinstance(maxima, bool) and coste > maxima:
        return None
    return int(coste)


def _veto_de_caja(row: dict[str, Any]) -> bool:
    motivos = {str(m) for m in row.get("reasons") or [] if isinstance(m, str)}
    for key in ("primary_motive", "bid_limit", "action_reason_code"):
        if isinstance(row.get(key), str):
            motivos.add(row[key])
    if motivos & {"ya_en_plantilla", "listing_propio", "lesionado", "sancionado", "mercado_cerrado", "sin_slots"}:
        return False
    return bool(motivos & _VETOS_DE_CAJA)


def _unificar_fila_mercado(row: dict[str, Any], report: dict[str, Any]) -> None:
    """Mercado habla con la voz del plan: misma cifra y, si es objetivo, mismo veredicto."""
    player_id = _pid(row.get("player_id"))
    if player_id is None:
        return
    poder = report.get("poder_pujas")
    caja = report.get("caja")

    def _sin_veto_de_caja(nuevo: str) -> None:
        row["reasons"] = [nuevo if m == "negative_cash" else m for m in row.get("reasons") or []]
        if row.get("primary_motive") == "negative_cash":
            row["primary_motive"] = nuevo

    if player_id in (report.get("propios") or set()):
        # Es tuyo (anunciado en tu escaparate): ni puja ni «no te llega la caja».
        row["smart_bid_eur"] = None
        row["puja_unica_eur"] = None
        row["reasons"] = [m for m in row.get("reasons") or [] if m != "negative_cash"]
        if row.get("primary_motive") == "negative_cash":
            row["primary_motive"] = "ya_en_plantilla"
        return
    compras = report.get("compras_plan") or {}
    objetivo = compras.get(player_id) if isinstance(compras, dict) else None
    if isinstance(objetivo, dict):
        cifra = int(objetivo["euros"])
        if isinstance(caja, int) and cifra > caja:
            # Objetivo del plan pagado con crédito: no es un veto, es cómo se financia.
            _sin_veto_de_caja("usa_credito")
        row["puja_unica_eur"] = cifra
        row["en_plan"] = True
        ventas = objetivo.get("ventas") or objetivo.get("ventas_hoy") or []
        texto = "Objetivo del plan de hoy"
        if ventas:
            texto += f": viable dentro del plan vendiendo a {', '.join(ventas)}"
        mejora = objetivo.get("mejora_neta")
        if isinstance(mejora, (int, float)) and not isinstance(mejora, bool):
            texto += f" (mejora el once {mejora:+.1f} xP)"
        if row.get("action") in {None, "PUJAR"} or _veto_de_caja(row):
            # Mercado decía «no te llega la caja» sin contar las ventas del plan.
            row["action"] = "PUJAR"
            row["decision"] = "PUJAR"
            row["is_vetoed"] = False
            row["action_reason"] = texto + "."
            row["smart_bid_eur"] = cifra
            row["suggested_bid"] = cifra
        else:
            # Otro motivo (snipe al cierre, lesión, mercado cerrado): se respeta
            # el veredicto, pero con la cifra y el contexto del plan.
            previo = row.get("action_reason") if isinstance(row.get("action_reason"), str) else ""
            row["action_reason"] = f"{texto}. {previo}".strip()
            if row.get("is_vetoed") is not True:
                row["smart_bid_eur"] = cifra
        return
    cifra = puja_unica((report.get("pujas") or {}).get(player_id), row)
    if cifra is None:
        return
    row["puja_unica_eur"] = cifra
    if _veto_de_caja(row):
        # La puja smart era tu caja (246.947 €): una cifra que nunca gana. Va la cifra real.
        row["smart_bid_eur"] = cifra
        if isinstance(poder, int) and cifra <= poder:
            _sin_veto_de_caja("fuera_del_plan")
            row["action_reason"] = (
                "Cabe con el crédito del 20 % (la puja admite deuda), pero no entra en el plan de hoy: "
                "mejora menos el once que los objetivos del plan."
            )
            row["cabe_con_credito"] = True
        else:
            row["cabe_con_credito"] = False
    elif row.get("is_vetoed") is True or row.get("decision") == "NO":
        # Descartado por otro motivo (lesión, sanción…): sin cifra de puja que tiente.
        row["smart_bid_eur"] = None
        if isinstance(poder, int) and cifra <= poder:
            _sin_veto_de_caja("fuera_del_plan")
    elif isinstance(row.get("smart_bid_eur"), int):
        row["smart_bid_eur"] = cifra


def _no_blindar_ventas_del_plan(
    clausulas: dict[str, Any],
    ventas: dict[str, str],
    records: dict[str, dict[str, Any]],
) -> None:
    """Quien el plan vende hoy no se blinda: su fila pasa a «Mejor venderlo» y no gasta caja."""
    if not ventas or not isinstance(clausulas, dict):
        return
    texto = "El plan de hoy lo vende: no gastes caja en subirle la cláusula."
    for fila in clausulas.get("proteger") or []:
        if isinstance(fila, dict) and fila.get("player_id") in ventas:
            fila["veredicto_codigo"] = "VENDER_ANTES"
            fila["veredicto_titulo"] = "VENDE ANTES"
            fila["subida_recomendada"] = None
            fila["motivo_detallado"] = texto
            fila["motivos"] = [texto, *[m for m in fila.get("motivos") or [] if m != texto]]
            fila["vende_en_plan"] = True
    clausulas["preparar"] = [
        fila for fila in clausulas.get("preparar") or [] if not (isinstance(fila, dict) and fila.get("player_id") in ventas)
    ]
    clausulas["radar_anti_robo"] = [
        fila for fila in clausulas.get("radar_anti_robo") or [] if not (isinstance(fila, dict) and fila.get("player_id") in ventas)
    ]
    clausulas["alertas_clausulas"] = [
        fila
        for fila in clausulas.get("alertas_clausulas") or []
        if not (isinstance(fila, dict) and fila.get("tipo") == "escudo" and fila.get("player_id") in ventas)
    ]
    resumen = clausulas.get("resumen")
    if isinstance(resumen, dict):
        resumen["coste_proteger_eur"] = int(
            sum(
                (fila.get("subida_recomendada") or {}).get("coste_eur", 0)
                for fila in clausulas.get("proteger") or []
                if isinstance(fila, dict) and fila.get("veredicto_codigo") in {"PROTEGER_YA", "PROTEGER_PARCIAL"}
            )
        )
        resumen["vende_en_plan"] = sorted(ventas.values())


def _sellar_pujas_plan(
    plan: dict[str, Any],
    pujas: dict[str, dict[str, Any]],
    sobrepuja: dict[str, Any] | None = None,
) -> None:
    """Las acciones PUJA del plan llevan la cifra de La Pizarra y la nuestra.

    Un objetivo del plan lleva además la puja competitiva de liga: la cifra por
    encima de la nuestra que cubre lo que suele pagar quien gana las subastas.
    Solo cabe dentro del techo dinámico y de lo que sobra en el presupuesto del
    plan (o del crédito que la propia puja ya usa en el parón).
    """
    if not isinstance(plan, dict):
        return
    presupuesto = plan.get("presupuesto") if isinstance(plan.get("presupuesto"), dict) else {}
    holgura = presupuesto.get("holgura")
    for accion in plan.get("acciones") or []:
        if not isinstance(accion, dict) or accion.get("tipo") != "PUJA":
            continue
        puja = pujas.get(accion.get("player_id")) if isinstance(accion.get("player_id"), str) else None
        if not isinstance(puja, dict):
            continue
        accion["puja_pizarra"] = puja.get("puja_pizarra")
        accion["puja_anti_pizarra"] = puja.get("puja_anti_pizarra")
        accion["diferencial_anti_pizarra_eur"] = puja.get("diferencial_anti_pizarra_eur") or 0
        accion["alta_demanda"] = puja.get("alta_demanda") is True
        accion["puja_recomendada"] = puja.get("puja_recomendada")
        accion["puja_maxima"] = puja.get("puja_maxima")
        margen = holgura if isinstance(holgura, int) and not isinstance(holgura, bool) else 0
        if accion.get("financia_con_credito") is True:
            tope = presupuesto.get("credito_20pct")
            usado = presupuesto.get("credito_paron")
            if isinstance(tope, int) and isinstance(usado, int):
                margen += max(0, tope - usado)
        _aplicar_competitiva(
            accion,
            base=accion.get("euros"),
            maxima=puja.get("puja_maxima"),
            sobrepuja=sobrepuja,
            margen=margen,
            clave=accion.get("player_id"),
            techo_absoluto=puja.get("techo_sobrepuja"),
        )
        # Mercado ve la misma cifra que el plan.
        puja["puja_competitiva_liga"] = accion["puja_competitiva_liga"]
        puja["sobrepuja_liga_pct"] = accion["sobrepuja_liga_pct"]


def _plan(
    records: dict[str, dict[str, Any]],
    xi: list[dict[str, Any]],
    war: dict[str, float],
    saldo: int | None,
    ratio: float,
    rivales: list[dict[str, Any]],
    board: dict[str, Any],
    now: datetime,
    own_id: str | None,
    previsiones: dict[str, dict[str, Any]] | None = None,
    notas: dict[str, dict[str, Any]] | None = None,
    *,
    curva: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    del rivales
    previsto = previsiones or {}
    notas_mercado = notas or {}
    owned_rows: list[dict[str, Any]] = []
    for row in records.values():
        if row.get("is_self") is not True or not isinstance(row.get("player_id"), str):
            continue
        if row.get("position") not in POSITIONS and not (isinstance(row.get("valor"), int) and row["valor"] > 0):
            continue
        # Lo que de verdad entra al vender: la mejor oferta con importe que ya
        # tienes. Sin ella, LaLiga puede ofrecer hasta un 5 % por debajo del
        # valor, así que el plan cuenta con el 95 % y no con el 100 %.
        importes = [
            oferta["importe"]
            for oferta in _ofertas_propias(row, own_id, {})
            if isinstance(oferta.get("importe"), int) and oferta["importe"] > 0
        ]
        valor_venta = row.get("valor") if isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool) else None
        if importes:
            venta = max(importes)
        elif valor_venta and valor_venta > 0:
            venta = int(valor_venta * VENTA_SIN_OFERTA_PCT)
        else:
            venta = None
        owned_rows.append(
            {
                "player_id": row["player_id"],
                "nombre": row.get("nombre"),
                "position": row.get("position"),
                "jornada": float(row["jornada"]) if isinstance(row.get("jornada"), (int, float)) and not isinstance(row.get("jornada"), bool) else 0.0,
                "elegible": row.get("excluded") is not True and row.get("position") in POSITIONS,
                "venta_eur": venta if isinstance(venta, int) and venta > 0 else None,
                "war": war.get(row["player_id"]),
                "pct": _pct_previsto(previsto, row["player_id"]),
                "valor": row.get("valor") if isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool) else None,
                "delta_hoy": row.get("delta_hoy"),
                "puntos_ultima": _puntos_ultima(row),
                "p_titular": row.get("p_titular") if isinstance(row.get("p_titular"), (int, float)) and not isinstance(row.get("p_titular"), bool) else row.get("prob_titular"),
                "si_titular": row.get("si_titular") if isinstance(row.get("si_titular"), (int, float)) and not isinstance(row.get("si_titular"), bool) else None,
                "kickoff": row.get("kickoff"),
                "tiene_oferta_laliga": row.get("tiene_oferta_laliga") is True,
                "futuro": _futuro(row),
                # Vuelve dentro de las cuatro jornadas del plan: no es una baja.
                "sancion_temporal": isinstance(row.get("sancion_partidos"), int) and row["sancion_partidos"] < 4,
            }
        )
    if saldo is not None and saldo < 0:
        baseline = 0.0
    else:
        elegibles = [row for row in owned_rows if row.get("elegible") is True]
        actual = solve_best_xi(elegibles)
        baseline = float(actual["puntos"]) if actual["ok"] else 0.0
        if xi and not actual["ok"]:
            publicado = solve_best_xi(xi)
            baseline = float(publicado["puntos"]) if publicado["ok"] else 0.0

    mercado: list[dict[str, Any]] = []
    for row in records.values():
        if row.get("is_self") is True or row.get("on_market") is not True:
            continue
        if own_id and row.get("seller_team_id") == own_id:
            continue
        if row.get("seller_team_id"):
            # Anunciado por un rival: en esta liga nadie ha ganado uno pujando, y
            # cuando pasa es por bastante más de la recomendada. No se cuenta con él.
            continue
        player_id = row.get("player_id")
        if not isinstance(player_id, str) or row.get("position") not in POSITIONS:
            continue
        jornada = row.get("jornada")
        if not isinstance(jornada, (int, float)) or isinstance(jornada, bool) or float(jornada) <= 0:
            continue
        parche = _es_parche_supervivencia(row, _puestos_en_hueco(records))
        row["supervivencia"] = parche
        puja = calcular_pujas(
            row.get("valor") or row.get("sale_price") or 0,
            float(row.get("delta_hoy") or 0.0),
            valor_justo_jugador(float(jornada), ratio, curva),
            tu_saldo=saldo,
            rivales=[],
            posicion=row.get("position"),
            prevision_7d_pct=_pct_previsto(previsto, player_id),
            dificultad=row.get("dificultad") if isinstance(row.get("dificultad"), str) else None,
            clave=player_id,
            supervivencia=parche,
        )
        _aplicar_anti_pizarra(
            puja,
            row,
            notas_mercado.get(player_id),
            _pct_previsto(previsto, player_id),
            saldo,
        )
        recomendada = puja.get("puja_recomendada")
        maxima = puja.get("puja_maxima")
        if not isinstance(recomendada, int):
            continue
        ask = row.get("sale_price") if isinstance(row.get("sale_price"), int) else 0
        lead = row.get("leading_bid") if isinstance(row.get("leading_bid"), int) else 0
        # Fichaje del mercado: se paga la puja recomendada (nunca menos que el
        # precio de salida ni que la puja líder conocida). El tope ``maxima`` es
        # el techo de la subasta, no el coste del plan: con ofertas sin importe
        # visible antes se planificaba al tope y el plan pedía un 30-40 % sobre
        # el valor, por encima incluso de lo que recomienda la pantalla Mercado.
        coste = max(recomendada, ask, lead)
        if isinstance(maxima, int) and coste > maxima:
            continue
        mercado.append(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "position": row.get("position"),
                "jornada": float(jornada),
                "euros": int(coste),
                "caduca_hoy": row.get("caduca_hoy") is True and not row.get("seller_team_id"),
                "futuro": _futuro(row),
                "pct": _pct_previsto(previsto, player_id),
                "valor": row.get("valor") if isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool) else None,
                "af_alerta_bajada": row.get("af_alerta_bajada") is True,
                "delta_hoy": row.get("delta_hoy"),
                "puntos_ultima": _puntos_ultima(row),
            }
        )
    mercado.sort(key=lambda item: float(item["jornada"]), reverse=True)
    mercado = mercado[:_MAX_PUJAS]

    clausulas: list[dict[str, Any]] = []
    for row in records.values():
        if row.get("is_self") is True or row.get("position") not in POSITIONS:
            continue
        if not _clause_open(row, now):
            continue
        clause = row.get("clause")
        jornada = row.get("jornada")
        player_id = row.get("player_id")
        if not isinstance(player_id, str) or not isinstance(clause, int) or clause <= 0:
            continue
        if not isinstance(jornada, (int, float)) or isinstance(jornada, bool) or float(jornada) < _CLAUSE_MIN_XP:
            continue
        justo = valor_justo_jugador(float(jornada), ratio, curva)
        if justo <= 0 or clause > justo / _CLAUSE_EDGE:
            continue
        if any(item["player_id"] == player_id for item in mercado):
            continue
        valor = row.get("valor") if isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool) else None
        if not valor and isinstance(row.get("market_value"), int) and not isinstance(row.get("market_value"), bool):
            valor = row["market_value"] if row["market_value"] > 0 else None
        parche = _es_parche_supervivencia({**row, "valor": valor}, _puestos_en_hueco(records))
        if isinstance(valor, int) and valor > 0 and clause > valor * 1.25 and not parche:
            continue
        clausulas.append(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "position": row.get("position"),
                "jornada": float(jornada),
                "euros": clause,
                "eficiencia": float(jornada) / clause,
                "futuro": _futuro(row),
                "pct": _pct_previsto(previsto, player_id),
                "valor": valor if isinstance(valor, int) and valor > 0 else None,
                "af_alerta_bajada": row.get("af_alerta_bajada") is True,
                "supervivencia": parche,
            }
        )
    clausulas.sort(key=lambda item: float(item["eficiencia"]), reverse=True)
    clausulas = clausulas[:_MAX_CLAUSULAS]
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    entrada = {
        "cash": saldo,
        "owned": owned_rows,
        "mercado": mercado,
        "clausulas": clausulas,
        "ratio": ratio,
        # Días hasta el inicio de jornada: primer silbato del día con más partidos.
        "dias_para_jornada": _days_to_kickoff(trends, now),
        "baseline_puntos": baseline,
        "objetivos_previos": board.get("plan_objetivos_previos") or None,
    }
    brecha = None
    try:
        squads_doc = board.get("squads") if isinstance(board.get("squads"), dict) else {}
        brecha = brecha_posicional([sq for sq in squads_doc.get("squads") or [] if isinstance(sq, dict)])
    except Exception:
        logger.debug("Sin brecha posicional", exc_info=True)
    if brecha and brecha.get("bonus_xp"):
        entrada["bonus_posicional"] = brecha["bonus_xp"]
    try:
        plan = build_plan_fichajes(**entrada)
        plan.setdefault("estado_calculo", "ok")
        plan["brecha_posicional"] = brecha
    except Exception as exc:
        logger.exception("plan de fichajes")
        vacio = _empty_plan(saldo, ratio)
        vacio["estado_calculo"] = "error"
        vacio["estado_detalle"] = f"El plan de fichajes falló al calcularse ({type(exc).__name__}). Pulsa Actualizar."
        return vacio
    try:
        # El mismo plan sin ventas condicionales: solo caja y ventas de hoy.
        prudente = build_plan_fichajes(**entrada, permitir_condicionales=False)
        ventas_prudentes = {
            accion["player_id"]
            for accion in prudente.get("acciones") or []
            if accion.get("tipo") in {"VENDE", "VENDER HOY"} and isinstance(accion.get("player_id"), str)
        }
        if ventas_prudentes and not conserva_esqueleto(owned_rows, ventas_prudentes):
            prudente = {
                "acciones": [],
                "mejora_puntos_jornada": 0.0,
                "mejora_horizonte": 0.0,
                "saldo_al_final": saldo,
                "presupuesto": None,
                "valido": False,
                "motivo": (
                    "Invalidado: las ventas dejarían la plantilla sin un once legal "
                    "si no ganas la puja."
                ),
            }
        plan["comparativa"] = {
            "completo": _resumen_plan(plan),
            "prudente": _resumen_plan(prudente),
        }
    except Exception:
        logger.exception("plan prudente")
    premio_jornada = 0
    try:
        from toolbox.player_history import actas_en_cache

        en_juego = construir_jornada_en_juego(
            board.get("squads") if isinstance(board.get("squads"), dict) else None,
            board.get("trends") if isinstance(board.get("trends"), dict) else None,
            actas_en_cache(),
            now=now,
        )
        plan["jornada_en_juego"] = en_juego
        if en_juego.get("activa") is True:
            # El premio entra el lunes. La ruta de salida solo cuenta los puntos ya firmados
            # (partidos jugados), no los esperados de lo que falta: dinero que aún no es tuyo.
            propio = en_juego.get("propio") if isinstance(en_juego.get("propio"), dict) else {}
            premio_jornada = int(propio.get("premio_ya_firme_eur") or 0)
    except Exception:
        logger.exception("jornada en juego")
    try:
        dias_cierre = _num(plan.get("dias_al_cierre"))
        fase = fase_paron(dias_cierre, _ciclo_paron(trends, now, dias_cierre))
        if fase is not None and dias_cierre is not None and saldo is not None:
            paron = construir_paron(
                fase=fase,
                dias=dias_cierre,
                cierre=now + timedelta(days=dias_cierre),
                saldo=saldo,
                owned=owned_rows,
                mercado=mercado,
                plan=plan,
                previos={str(item) for item in entrada["objetivos_previos"] or []},
                premio_jornada=premio_jornada,
            )
            plan["paron"] = paron
            # Una sola voz: en parón la especulación la decide el modo parón, no el trading desk.
            if isinstance(plan.get("trading"), dict):
                plan["trading"]["operaciones"] = []
                plan["trading"]["ganancia_esperada"] = 0
            plan["acciones"] = [*(plan.get("acciones") or []), *paron["acciones"]]
    except Exception:
        logger.exception("modo parón")
    try:
        # La cobertura mira el primer silbato real, no el día con más partidos.
        plan["liquidacion"] = _liquidacion(
            records, owned_rows, saldo, _days_to_kickoff(trends, now), own_id, earliest_kickoff(trends, now=now)
        )
    except Exception:
        logger.exception("plan de liquidación")
    return plan


def _resumen_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Lo justo para comparar dos planes: compras, ventas, gasto y puntos."""
    acciones = plan.get("acciones") or []
    compras = [a for a in acciones if a.get("tipo") in {"PUJA", "CLAUSULAZO"}]
    ventas = [a for a in acciones if a.get("tipo") in {"VENDE", "VENDER HOY"}]
    resumen = {
        "mejora_puntos_jornada": plan.get("mejora_puntos_jornada"),
        "mejora_horizonte": plan.get("mejora_horizonte"),
        "saldo_al_final": plan.get("saldo_al_final"),
        "presupuesto": plan.get("presupuesto"),
        "valido": plan.get("valido") is not False,
        "compras": [
            {k: a.get(k) for k in ("player_id", "nombre", "etiqueta", "euros", "mejora_neta", "momento")}
            for a in compras
        ],
        "ventas": [
            {k: a.get(k) for k in ("player_id", "nombre", "euros", "momento")}
            for a in ventas
        ],
    }
    if isinstance(plan.get("motivo"), str) and plan["motivo"]:
        resumen["motivo"] = plan["motivo"]
    return resumen


def _liquidacion(
    records: dict[str, dict[str, Any]],
    owned_rows: list[dict[str, Any]],
    saldo: int | None,
    dias: float | None,
    own_id: str | None,
    inicio: str | None = None,
) -> dict[str, Any]:
    """Salida del #12 en adelante con la mejor oferta con importe de cada jugador."""
    filas: list[dict[str, Any]] = []
    ofertas: dict[str, int | None] = {}
    for row in owned_rows:
        record = records.get(row["player_id"]) or {}
        filas.append(
            {**row, "en_venta": record.get("on_market") is True and record.get("seller_team_id") in {None, own_id}}
        )
        importes = [oferta["importe"] for oferta in _ofertas_propias(record, own_id, {}) if isinstance(oferta.get("importe"), int)]
        ofertas[row["player_id"]] = max(importes) if importes else None
    return plan_liquidacion(filas, saldo=saldo, dias_para_jornada=dias, ofertas=ofertas, inicio=inicio)


def _notas_mercado(
    records: dict[str, dict[str, Any]],
    previsiones: dict[str, dict[str, Any]],
    saldo: int | None,
    *,
    caja: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Nota y frase de cada jugador del mercado que puedes comprar.

    ``saldo`` es el poder de puja (caja + crédito); ``caja``, el saldo de hoy.
    Tus propios jugadores anunciados no llevan veredicto de compra.
    """
    plantilla = [
        {
            "player_id": row.get("player_id"),
            "position": row.get("position"),
            "xp": row.get("jornada"),
            "en_xi": True,
            "p_titular": row.get("p_titular"),
        }
        for row in records.values()
        if row.get("is_self") is True and row.get("in_xi") is True
    ]
    notas: dict[str, dict[str, Any]] = {}
    for row in records.values():
        if row.get("on_market") is not True or row.get("is_self") is True:
            continue
        player_id = row.get("player_id")
        if not isinstance(player_id, str):
            continue
        previsto = previsiones.get(player_id) if isinstance(previsiones.get(player_id), dict) else {}
        notas[player_id] = calcular_nota_mercado(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "position": row.get("position"),
                "xp": row.get("jornada"),
                "prevision_7d_pct": previsto.get("pct") if isinstance(previsto, dict) else None,
                "p_titular": row.get("p_titular"),
                "week_points": row.get("recientes"),
                "dificultad": row.get("dificultad"),
                "precio": row.get("sale_price") or row.get("valor"),
            },
            plantilla,
            saldo,
            caja=caja,
        )
    return notas


def _consejos(
    records: dict[str, dict[str, Any]],
    war: dict[str, float],
    plan: dict[str, Any],
    own_id: str | None,
) -> dict[str, dict[str, Any]]:
    acciones = plan.get("acciones") if isinstance(plan.get("acciones"), list) else []
    mejora = plan.get("mejora_puntos_jornada")
    mejora_num = float(mejora) if isinstance(mejora, (int, float)) and not isinstance(mejora, bool) else 0.0
    consejos: dict[str, dict[str, Any]] = {}
    for player_id, perdida in war.items():
        row = records.get(player_id)
        if row is None or row.get("on_market") is not True:
            continue
        if own_id and row.get("seller_team_id") not in {None, own_id} and row.get("is_self") is not True:
            continue
        posicion = row.get("position") or "jugador"
        sustituto = any(
            isinstance(accion, dict)
            and accion.get("tipo") == "PUJA"
            and accion.get("momento") == "hoy"
            and accion.get("posicion") == row.get("position")
            and mejora_num > 0
            for accion in acciones
        )
        if perdida > UMBRAL_WAR_OFERTA and not sustituto:
            consejos[player_id] = {
                "acepta": False,
                "explicacion": (
                    f"Sin él el once pierde {perdida:.1f} puntos y hoy no hay un {posicion} "
                    "en el mercado que mejore el equipo. No aceptes la oferta."
                ),
            }
        elif perdida > UMBRAL_WAR_OFERTA and sustituto:
            consejos[player_id] = {
                "acepta": True,
                "explicacion": (
                    f"El once pierde {perdida:.1f} puntos sin él, pero la puja de hoy en su puesto "
                    "deja el equipo por encima. La oferta se puede aceptar."
                ),
            }
        else:
            consejos[player_id] = {
                "acepta": True,
                "explicacion": (
                    f"Otro de la plantilla entra en el once: baja {perdida:.1f} puntos, "
                    "por debajo de 1,5. La oferta se puede aceptar."
                ),
            }
    return consejos


def _proximos_rivales(calendario: Any) -> list[dict[str, Any]]:
    """Rival, localía y dificultad de los próximos partidos; ``en`` = jornadas desde hoy (1 = la próxima)."""
    if not isinstance(calendario, list):
        return []
    salida: list[dict[str, Any]] = []
    for indice, celda in enumerate(calendario[:4], start=1):
        rival = celda.get("opponent") if isinstance(celda, dict) else None
        if not isinstance(rival, str) or not rival.strip():
            continue
        casa = celda.get("is_home")
        dificultad = celda.get("difficulty") or celda.get("dificultad")
        salida.append(
            {
                "en": indice,
                "rival": rival.strip(),
                "casa": casa if isinstance(casa, bool) else None,
                "dificultad": dificultad if isinstance(dificultad, str) else None,
            }
        )
    return salida


def _stamp_row(row: dict[str, Any], report: dict[str, Any]) -> None:
    player_id = _pid(row.get("player_id"))
    if player_id is None:
        return
    previsto = report["previsiones"].get(player_id)
    if isinstance(previsto, dict):
        row["prevision_7d_pct"] = previsto.get("prevision_7d_pct")
        row["valor_en_7d"] = previsto.get("valor_en_7d")
        row["valor_justo"] = previsto.get("valor_justo")
        row["xp_4_jornadas"] = previsto.get("xp_4_jornadas")
    proximos = _proximos_rivales((report.get("calendarios") or {}).get(player_id))
    if proximos:
        row["proximos_rivales"] = proximos
    if player_id in report["war"]:
        row["tu_once_pierde_sin_el"] = report["war"][player_id]
    consejo = report["consejos"].get(player_id)
    if isinstance(consejo, dict):
        row["consejo_oferta"] = consejo
    propio = player_id in (report.get("propios") or set())
    puja = None if propio else report["pujas"].get(player_id)
    if propio:
        # Es tuyo: ni puja ni «DESCARTAR, no te llega la caja».
        for key in ("puja_recomendada", "puja_maxima", "puja_smart", "puja_competitiva_liga", "sobrepuja_liga_pct",
                    "nota_mercado", "veredicto_mercado", "etiqueta_mercado", "frase_mercado"):
            row.pop(key, None)
    if isinstance(puja, dict):
        row["puja_recomendada"] = puja.get("puja_recomendada")
        row["puja_maxima"] = puja.get("puja_maxima")
        row["puja_smart"] = puja.get("puja_smart")
        row["puja_competitiva_liga"] = puja.get("puja_competitiva_liga")
        row["sobrepuja_liga_pct"] = puja.get("sobrepuja_liga_pct")
        maxima = puja.get("puja_maxima")
        if isinstance(maxima, int) and maxima > 0:
            row["financial_max_bid_eur"] = maxima
            smart = row.get("smart_bid_eur")
            if isinstance(smart, int) and smart > maxima:
                row["smart_bid_eur"] = maxima
    nota = report.get("notas_mercado") if isinstance(report.get("notas_mercado"), dict) else {}
    ficha = nota.get(player_id) if isinstance(nota, dict) else None
    if isinstance(ficha, dict):
        row["nota_mercado"] = ficha.get("nota_mercado")
        row["veredicto_mercado"] = ficha.get("veredicto_mercado")
        row["etiqueta_mercado"] = ficha.get("etiqueta_mercado")
        row["frase_mercado"] = ficha.get("frase_mercado")
    if player_id in report["forzadas"]:
        row["venta_forzada_rival"] = True
        row["venta_forzada_detalle"] = report["forzadas"][player_id]
    if any(key in row for key in ("action", "decision", "sale_price")):
        _unificar_fila_mercado(row, report)


def _stamp_list(rows: Any, report: dict[str, Any]) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if isinstance(row, dict):
            _stamp_row(row, report)


def stamp_strategy(payload: dict[str, Any], report: dict[str, Any]) -> None:
    """Añade la capa al documento que ya consume el frontend."""
    if not isinstance(payload, dict):
        return
    for key in ("market_decisions", "flips", "rising", "falling", "undervalued", "xi", "benched", "excluded", "decisions"):
        _stamp_list(payload.get(key), report)
    market = payload.get("market")
    if isinstance(market, dict):
        _stamp_list(market.get("listings"), report)
    for gap_key in ("gaps", "market_fills"):
        for gap in payload.get(gap_key) or []:
            if isinstance(gap, dict):
                _stamp_list(gap.get("options"), report)
    saved = payload.get("saved_lineup")
    if isinstance(saved, dict):
        _stamp_list(saved.get("xi"), report)
    lineup = payload.get("lineup")
    if isinstance(lineup, dict):
        _stamp_list(lineup.get("xi"), report)
    propio = payload.get("self")
    if isinstance(propio, dict):
        _stamp_list(propio.get("players"), report)
    for rival in payload.get("rivals") or []:
        if isinstance(rival, dict):
            _stamp_list(rival.get("players"), report)
    payload["ratio_mercado"] = report.get("ratio_mercado")
    payload["ratio_detalle"] = report.get("ratio_detalle")
    payload["capitan_seguro"] = report.get("capitan_seguro")
    payload["capitan_remontada"] = report.get("capitan_remontada")
    payload["plan_fichajes"] = report.get("plan_fichajes")
    payload["ventas_forzadas"] = report.get("ventas_forzadas") or []
    payload["auditoria_ventas"] = report.get("auditoria_ventas") or []
    payload["resumen_ventas"] = report.get("resumen_ventas") or _resumen_vacio()
    payload["asesor_clausulas"] = report.get("asesor_clausulas") or _clausulas_vacias()
    payload["radar_anti_robo"] = report.get("radar_anti_robo") or []


def _league_id(board: dict[str, Any]) -> str | None:
    for key in ("trends", "squads", "market"):
        document = board.get(key) if isinstance(board, dict) else None
        if isinstance(document, dict) and isinstance(document.get("league_id"), str) and document["league_id"]:
            return document["league_id"]
    return None


def publish_strategy(board: dict[str, Any], payload: dict[str, Any], *, now: datetime | None = None) -> None:
    """Calcula y estampa. Un fallo aquí no puede tumbar el resto del JSON.

    Lee los objetivos del plan anterior y guarda el de hoy (``plan_memory``):
    así el plan no salta de jugador cada mañana y se puede medir cuánto cambia.
    """
    league_id = _league_id(board)
    try:
        previos = load_objetivos_previos(league_id)
    except Exception:
        logger.exception("memoria del plan")
        previos = []
    if previos and isinstance(board, dict):
        board = {**board, "plan_objetivos_previos": previos}
    calculado = False
    try:
        report = build_strategy(board, now=now)
        calculado = True
    except Exception:
        logger.exception("capa estratégica")
        ratio = float(EUROS_POR_PUNTO)
        report = {
            "ratio_mercado": ratio,
            "ratio_detalle": {
                "ratio_mercado": ratio,
                "referencia_eur_por_punto": EUROS_POR_PUNTO,
                "xp_medio_titulares": None,
                "valor_medio_titulares": None,
                "muestra_titulares": 0,
                "usa_referencia": True,
            },
            "previsiones": {},
            "war": {},
            "pujas": {},
            "consejos": {},
            "forzadas": {},
            "ventas_forzadas": [],
            "capitan_seguro": None,
            "capitan_remontada": None,
            "plan_fichajes": _empty_plan(None, ratio),
            "auditoria_ventas": [],
            "resumen_ventas": _resumen_vacio(),
            "asesor_clausulas": _clausulas_vacias(),
            "radar_anti_robo": [],
            "notas_mercado": {},
        }
    stamp_strategy(payload, report)
    if not calculado:
        # Un plan vacío por error no puede borrar la memoria del plan bueno.
        return
    try:
        save_plan(league_id, report.get("plan_fichajes"))
    except Exception:
        logger.exception("memoria del plan")

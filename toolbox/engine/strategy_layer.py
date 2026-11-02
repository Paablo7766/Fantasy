"""Capa estratégica: precio a 7 días, WAR, pujas, rivales en negativo y plan.

Lee la foto que ya tiene el tablero (plantillas, mercado, once) y no sale a
la red. El JSON de siempre se queda; estos campos se suman encima.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from toolbox.analyzer import POSITIONS, own_squad
from toolbox.bidding import MIN_HEADCOUNT
from toolbox.engine.auction_intel import (
    PREVISION_ALTA_PCT,
    UMBRAL_WAR_OFERTA,
    calcular_pujas,
    capitanes,
    puja_anti_pizarra,
)
from toolbox.engine.lineup_math import solve_best_xi, war_del_once
from toolbox.engine.market_predictor import (
    EUROS_POR_PUNTO,
    proyectar_7d,
    ratio_mercado_liga,
    valor_justo_jugador,
)
from toolbox.engine.clause_advisor import auditar_clausulas_plantilla, evaluar_clausulas
from toolbox.engine.market_grade import calcular_nota_mercado
from toolbox.engine.sales_audit import LALIGA, evaluar_ventas_y_ofertas
from toolbox.engine.signing_plan import FACTOR_AJUSTE, build_plan_fichajes
from toolbox.market_intel import _jornada_kickoff, _parse_kickoff
from toolbox.normalize import exclusion_from_status, parse_clause_lock

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
    aceleracion = _num(source.get("acceleration"))
    if aceleracion is not None and not row.get("_ayer_set"):
        row["delta_ayer"] = float(row.get("delta_hoy") or 0.0) - aceleracion
        row["_ayer_set"] = True
    elif not row.get("_ayer_set"):
        dos = _num(source.get("ff_price_delta_2"))
        if dos is not None and row.get("_delta_set"):
            row["delta_ayer"] = dos - float(row.get("delta_hoy") or 0.0)
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


def _days_to_kickoff(trends: dict[str, Any] | None, now: datetime) -> float | None:
    raw = _jornada_kickoff(trends, now)
    moment = _parse_kickoff(raw) if isinstance(raw, str) else None
    if moment is None:
        return None
    return (moment - now).total_seconds() / 86400.0


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
        if exclusion_from_status(player.get("player_status") if isinstance(player.get("player_status"), str) else None):
            row["excluded"] = True

    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
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
            row["team_id"] = team_id
            row["is_self"] = is_self
            row["manager"] = manager
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
            if player.get("tiene_oferta_laliga") is True:
                row["tiene_oferta_laliga"] = True
            if is_self:
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


def _rivals(records: dict[str, dict[str, Any]], cash: dict[str, int]) -> list[dict[str, Any]]:
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
    for team_id, bucket in by_team.items():
        thin = [position for position in POSITIONS if bucket["counts"][position] <= MIN_HEADCOUNT[position]]
        salida.append(
            {
                "team_id": team_id,
                "manager": bucket.get("manager"),
                "saldo": cash.get(team_id),
                "posiciones": thin,
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
            )
        except (TypeError, ValueError):
            continue
        previsiones[player_id] = previsto

    xi, bench = _xi_and_bench(records, board if isinstance(board, dict) else {})
    war = war_del_once(xi, bench)
    caps = capitanes(xi)
    cajas = _cash_map(board if isinstance(board, dict) else {})
    rivales = _rivals(records, cajas)
    propio = own_squad(board.get("squads") if isinstance(board, dict) and isinstance(board.get("squads"), dict) else None)
    own_id = _pid(propio.get("team_id")) if isinstance(propio, dict) else None
    saldo = propio.get("cash") if isinstance(propio, dict) and isinstance(propio.get("cash"), int) and not isinstance(propio.get("cash"), bool) else None
    if own_id and own_id in cajas:
        saldo = cajas[own_id]

    notas = _notas_mercado(records, previsiones, saldo)

    pujas: dict[str, dict[str, Any]] = {}
    for row in records.values():
        player_id = row.get("player_id")
        valor = row.get("valor")
        if not isinstance(player_id, str) or not isinstance(valor, int) or valor <= 0:
            continue
        justo = previsiones.get(player_id, {}).get("valor_justo")
        if not isinstance(justo, int):
            jornada = row.get("jornada")
            justo = valor_justo_jugador(float(jornada), ratio) if isinstance(jornada, (int, float)) and not isinstance(jornada, bool) else 0
        previsto_pct = previsiones.get(player_id, {}).get("pct") if isinstance(previsiones.get(player_id), dict) else None
        pujas[player_id] = calcular_pujas(
            valor,
            float(row.get("delta_hoy") or 0.0),
            int(justo or 0),
            tu_saldo=saldo,
            rivales=rivales,
            posicion=row.get("position") if isinstance(row.get("position"), str) else None,
            prevision_7d_pct=previsto_pct,
            dificultad=row.get("dificultad") if isinstance(row.get("dificultad"), str) else None,
        )
        _aplicar_anti_pizarra(pujas[player_id], row, notas.get(player_id), previsto_pct, saldo)

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
    )
    _sellar_pujas_plan(plan, pujas)
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
        "war": war,
        "pujas": pujas,
        "consejos": consejos,
        "forzadas": forzadas,
        "ventas_forzadas": ventas,
        "capitan_seguro": caps.get("capitan_seguro"),
        "capitan_remontada": caps.get("capitan_remontada"),
        "plan_fichajes": plan,
        "auditoria_ventas": auditoria["filas"],
        "resumen_ventas": auditoria["resumen"],
        "asesor_clausulas": clausulas,
        "radar_anti_robo": clausulas.get("radar_anti_robo") or [],
        "notas_mercado": notas,
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
    texto = cierre.get("expires_at") if isinstance(cierre, dict) else None
    if not isinstance(texto, str):
        return None
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


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
        "radar_anti_robo": [],
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
            }
            for fila in propios
        ],
        [
            {"dineroEstimado": rival.get("saldo"), "manager": rival.get("manager"), "team_id": rival.get("team_id")}
            for rival in rivales
            if isinstance(rival, dict)
        ],
        ahora=now,
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
        )
    except Exception:
        logger.exception("asesor de cláusulas")
        informe = _clausulas_vacias()
    informe["radar_anti_robo"] = radar
    return informe


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


def _aplicar_anti_pizarra(
    puja: dict[str, Any],
    row: dict[str, Any],
    nota: dict[str, Any] | None,
    pct: float | None,
    saldo: int | None,
) -> None:
    """Con demanda alta sube ``puja_recomendada`` por encima del escalón de La Pizarra."""
    valor = row.get("valor") or row.get("sale_price") or 0
    info = puja_anti_pizarra(
        valor,
        row.get("delta_hoy"),
        nota_mercado=nota.get("nota_mercado") if isinstance(nota, dict) else None,
        prevision_7d_pct=pct,
        clave=row.get("player_id"),
        maxima=puja.get("puja_maxima") if isinstance(puja.get("puja_maxima"), int) else None,
        saldo=saldo,
    )
    puja["puja_pizarra"] = info["puja_pizarra"]
    puja["puja_anti_pizarra"] = info["puja_anti_pizarra"]
    puja["diferencial_anti_pizarra_eur"] = info["diferencial_anti_pizarra_eur"]
    puja["alta_demanda"] = info["alta_demanda"]
    anti = info["puja_anti_pizarra"]
    if isinstance(anti, int):
        puja["puja_recomendada"] = anti
        smart = puja.get("puja_smart")
        if not isinstance(smart, int) or smart < anti:
            puja["puja_smart"] = anti


def _sellar_pujas_plan(plan: dict[str, Any], pujas: dict[str, dict[str, Any]]) -> None:
    """Las acciones PUJA del plan llevan la cifra de La Pizarra y la nuestra."""
    for accion in plan.get("acciones") or [] if isinstance(plan, dict) else []:
        if not isinstance(accion, dict) or accion.get("tipo") != "PUJA":
            continue
        puja = pujas.get(accion.get("player_id")) if isinstance(accion.get("player_id"), str) else None
        if not isinstance(puja, dict):
            continue
        accion["puja_pizarra"] = puja.get("puja_pizarra")
        accion["puja_anti_pizarra"] = puja.get("puja_anti_pizarra")
        accion["diferencial_anti_pizarra_eur"] = puja.get("diferencial_anti_pizarra_eur") or 0
        accion["alta_demanda"] = puja.get("alta_demanda") is True


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
        venta = row.get("sale_price") if row.get("on_market") and isinstance(row.get("sale_price"), int) else row.get("valor")
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
                "p_titular": row.get("p_titular") if isinstance(row.get("p_titular"), (int, float)) and not isinstance(row.get("p_titular"), bool) else row.get("prob_titular"),
                "tiene_oferta_laliga": row.get("tiene_oferta_laliga") is True,
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
        player_id = row.get("player_id")
        if not isinstance(player_id, str) or row.get("position") not in POSITIONS:
            continue
        jornada = row.get("jornada")
        if not isinstance(jornada, (int, float)) or isinstance(jornada, bool) or float(jornada) <= 0:
            continue
        puja = calcular_pujas(
            row.get("valor") or row.get("sale_price") or 0,
            float(row.get("delta_hoy") or 0.0),
            valor_justo_jugador(float(jornada), ratio),
            tu_saldo=saldo,
            rivales=[],
            posicion=row.get("position"),
            prevision_7d_pct=_pct_previsto(previsto, player_id),
            dificultad=row.get("dificultad") if isinstance(row.get("dificultad"), str) else None,
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
                "pct": _pct_previsto(previsto, player_id),
                "valor": row.get("valor") if isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool) else None,
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
        justo = valor_justo_jugador(float(jornada), ratio)
        if justo <= 0 or clause > justo / _CLAUSE_EDGE:
            continue
        if any(item["player_id"] == player_id for item in mercado):
            continue
        valor = row.get("valor") if isinstance(row.get("valor"), int) and not isinstance(row.get("valor"), bool) else None
        if not valor and isinstance(row.get("market_value"), int) and not isinstance(row.get("market_value"), bool):
            valor = row["market_value"] if row["market_value"] > 0 else None
        clausulas.append(
            {
                "player_id": player_id,
                "nombre": row.get("nombre"),
                "position": row.get("position"),
                "jornada": float(jornada),
                "euros": clause,
                "eficiencia": float(jornada) / clause,
                "pct": _pct_previsto(previsto, player_id),
                "valor": valor if isinstance(valor, int) and valor > 0 else None,
            }
        )
    clausulas.sort(key=lambda item: float(item["eficiencia"]), reverse=True)
    clausulas = clausulas[:_MAX_CLAUSULAS]
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else None
    try:
        return build_plan_fichajes(
            cash=saldo,
            owned=owned_rows,
            mercado=mercado,
            clausulas=clausulas,
            ratio=ratio,
            # Días hasta el inicio de jornada: primer silbato del día con más partidos.
            dias_para_jornada=_days_to_kickoff(trends, now),
            baseline_puntos=baseline,
        )
    except Exception:
        logger.exception("plan de fichajes")
        return _empty_plan(saldo, ratio)


def _notas_mercado(
    records: dict[str, dict[str, Any]],
    previsiones: dict[str, dict[str, Any]],
    saldo: int | None,
) -> dict[str, dict[str, Any]]:
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
        if row.get("on_market") is not True:
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
                    f"El banquillo cubre el hueco: el once baja {perdida:.1f} puntos, "
                    "por debajo de 1,5. La oferta se puede aceptar."
                ),
            }
    return consejos


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
    if player_id in report["war"]:
        row["tu_once_pierde_sin_el"] = report["war"][player_id]
    consejo = report["consejos"].get(player_id)
    if isinstance(consejo, dict):
        row["consejo_oferta"] = consejo
    puja = report["pujas"].get(player_id)
    if isinstance(puja, dict):
        row["puja_recomendada"] = puja.get("puja_recomendada")
        row["puja_maxima"] = puja.get("puja_maxima")
        row["puja_smart"] = puja.get("puja_smart")
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


def publish_strategy(board: dict[str, Any], payload: dict[str, Any], *, now: datetime | None = None) -> None:
    """Calcula y estampa. Un fallo aquí no puede tumbar el resto del JSON."""
    try:
        report = build_strategy(board, now=now)
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

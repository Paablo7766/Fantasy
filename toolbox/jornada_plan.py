"""Plan de jornada: reloj, once contra el guardado y acciones con caja resultante.

Compone optimize, market-intel, cláusulas y expertos. No envía órdenes.
Una acción que deje la caja en negativo o el XI por debajo de 11 no entra.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from toolbox.analyzer import index_trends, lineup_points, own_squad, played_points
from toolbox.audit import append_audit, build_audit
from toolbox.bid_war import rival_snapshots
from toolbox.clause_intel import build_clause_intel
from toolbox.league_race import build_league_race
from toolbox.experts import (
    agreement_for_trends,
    link_mentions,
    load_expert_pages,
    mentions_from_text,
)
from toolbox.market_intel import build_market_decisions
from toolbox.normalize import SCHEMA_VERSION, display_zone

_MADRID = ZoneInfo("Europe/Madrid")
_NOTE_LIMIT = 20_000

# Acciones que no son «mejoras»: existen porque el once guardado no vale o la
# caja está en rojo. Se etiquetan como tales, nunca como un simple cambio.
SURVIVAL_KINDS = frozenset({"cerrar_hueco", "vender_emergencia"})


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clock(moment: datetime) -> dict[str, str]:
    zone_name, zone = display_zone()
    local = moment.astimezone(zone)
    return {
        "at": moment.astimezone(timezone.utc).isoformat(),
        "local_date": local.date().isoformat(),
        "local_time": local.strftime("%H:%M"),
        "local_clock": local.strftime("%H:%M:%S"),
        "timezone": zone_name,
    }


def _lock_moment(lock: dict[str, Any]) -> datetime | None:
    parsed = _parse_iso(lock.get("expires_at"))
    if parsed is not None:
        return parsed
    date = lock.get("local_date") if isinstance(lock.get("local_date"), str) else None
    clock = lock.get("local_time") if isinstance(lock.get("local_time"), str) else None
    if not date or not clock:
        return None
    stamp = clock if len(clock) > 5 else f"{clock}:00"
    try:
        naive = datetime.fromisoformat(f"{date}T{stamp}")
    except ValueError:
        return None
    return naive.replace(tzinfo=_MADRID)


def earliest_kickoff(trends: dict[str, Any] | None, *, now: datetime) -> str | None:
    """Primer saque que aún no ha pasado. Sin marca, no se inventa el inicio."""
    if not isinstance(trends, dict):
        return None
    moments: list[datetime] = []
    players = trends.get("players") if isinstance(trends.get("players"), list) else []
    for player in players:
        if not isinstance(player, dict):
            continue
        fixture = player.get("fixture") if isinstance(player.get("fixture"), dict) else {}
        kick = _parse_iso(fixture.get("kickoff"))
        if kick is None:
            calendar = player.get("own_calendar") if isinstance(player.get("own_calendar"), list) else []
            if calendar and isinstance(calendar[0], dict):
                kick = _parse_iso(calendar[0].get("kickoff"))
        if kick is not None:
            moments.append(kick)
    upcoming = [moment for moment in moments if moment >= now]
    pool = upcoming or []
    if not pool:
        return None
    return min(pool).astimezone(timezone.utc).isoformat()


def _player_label(row: dict[str, Any]) -> str:
    name = row.get("nickname") or row.get("name") or row.get("player_id") or "jugador"
    return str(name)


def _saved_player_points(
    row: dict[str, Any],
    known: dict[str, dict[str, Any]],
    rec_ids: set[Any],
) -> float | None:
    """E[pts] del jugador guardado, desde la fila guardada o desde el motor.

    Manda la cifra que trae la fila del once guardado (la que el usuario ve en
    la app). El once/banquillo del motor solo rellena el hueco cuando la fila
    guardada llega sin puntos: así un jugador que está en los dos onces se mide
    igual en los dos lados y no se inventan deltas.
    """
    points = played_points(row)
    if points is not None:
        return points
    player_id = row.get("player_id")
    source = known.get(player_id) if isinstance(player_id, str) else None
    if isinstance(source, dict):
        return played_points(source)
    return None


def lineup_delta(optimize: dict[str, Any] | None) -> dict[str, Any]:
    """Once recomendado contra el guardado, con la misma métrica en los dos.

    Los dos onces se miden sumando ``jornada_ev`` (o ``expected_points``): nunca
    se compara el ``expected_points`` del solver, que es su objetivo, con los
    puntos de jugadores guardados. Si falta el dato de un solo jugador guardado,
    el delta no se inventa: se devuelve ``None``.
    """
    document = optimize if isinstance(optimize, dict) else {}
    recommended = [row for row in document.get("xi") or [] if isinstance(row, dict)]
    saved = document.get("saved_lineup") if isinstance(document.get("saved_lineup"), dict) else {}
    saved_xi = [row for row in saved.get("xi") or [] if isinstance(row, dict)]
    known: dict[str, dict[str, Any]] = {}
    for bucket in ("xi", "benched", "excluded"):
        for row in document.get(bucket) or []:
            if isinstance(row, dict) and isinstance(row.get("player_id"), str):
                known[row["player_id"]] = row
    rec_ids = {row.get("player_id") for row in recommended if isinstance(row.get("player_id"), str)}
    saved_ids = {row.get("player_id") for row in saved_xi if isinstance(row.get("player_id"), str)}
    enters = [row for row in recommended if row.get("player_id") and row.get("player_id") not in saved_ids]
    missing_points: list[str] = []
    saved_points: float | None = None
    saved_complete = False
    leaves: list[dict[str, Any]] = []
    if saved_xi:
        total = 0.0
        saved_complete = True
        for row in saved_xi:
            points = _saved_player_points(row, known, rec_ids)
            if points is None:
                saved_complete = False
                missing_points.append(_player_label(row))
                continue
            total += points
            player_id = row.get("player_id")
            if player_id not in rec_ids:
                leaves.append(known.get(player_id) or row)
        saved_points = round(total, 4) if saved_complete else None
    row_points = lineup_points(recommended)[0]
    document_points = document.get("lineup_expected_points")
    if isinstance(document_points, bool) or not isinstance(document_points, (int, float)):
        document_points = None
    # Si el solver declara un total que no cuadra con los jugadores que devuelve,
    # manda la suma de las filas: el delta nunca se mide con dos varas.
    if (
        document_points is not None
        and row_points is not None
        and abs(float(document_points) - float(row_points)) > 0.05
    ):
        document_points = None
    recommended_points = document_points if document_points is not None else row_points
    if recommended_points is None:
        from toolbox.analyzer import projected_lineup_points

        recommended_points = projected_lineup_points(document)
    points_delta = None
    if saved_complete and saved_points is not None and recommended_points is not None:
        points_delta = round(float(recommended_points) - float(saved_points), 4)
    elif saved_xi and not saved_complete:
        missing_points = missing_points or ["puntos del once guardado"]
    gaps = [gap for gap in document.get("gaps") or [] if isinstance(gap, dict)]
    missing_slots = sum(int(gap.get("missing") or 0) for gap in gaps)
    # El once guardado está efectivamente formado solo con los 11 que trae la
    # app; el recomendado solo con 11 y sin huecos por posición.
    saved_valid = len(saved_xi) >= 11
    recommended_valid = (
        len(recommended) >= 11 and missing_slots == 0 and document.get("matchday_void") is not True
    )
    follows_solver = bool(recommended) and rec_ids == {row.get("player_id") for row in recommended if row.get("player_id")}
    formation = document.get("formation") if isinstance(document.get("formation"), str) else None
    saved_formation = saved.get("formation") if isinstance(saved.get("formation"), str) else None
    differs = (
        rec_ids != saved_ids
        or (formation is not None and saved_formation is not None and formation != saved_formation)
    )
    return {
        "formation": formation,
        "saved_formation": saved_formation,
        "expected_points": round(float(recommended_points), 4) if recommended_points is not None else None,
        "saved_points": saved_points,
        "points_delta": points_delta,
        "missing_inputs": missing_points,
        "enters": [_brief(row) for row in enters],
        "leaves": [_brief(row) for row in leaves],
        "xi": [_brief(row) for row in recommended],
        "differs": bool(saved_xi) and differs,
        "saved_valid": saved_valid,
        "recommended_valid": recommended_valid,
        "missing_slots": missing_slots,
        "recommended_partial": document.get("matchday_void") is True,
        "xi_changed": rec_ids != saved_ids,
        "follows_solver": follows_solver,
    }


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row.get("player_id"),
        "name": row.get("name"),
        "nickname": row.get("nickname"),
        "position": row.get("position"),
        "club": row.get("club"),
        "image_url": row.get("image_url") if isinstance(row.get("image_url"), str) else None,
        "expected_points": row.get("expected_points") if isinstance(row.get("expected_points"), (int, float)) else None,
        "p_titular": row.get("p_titular") if isinstance(row.get("p_titular"), (int, float)) else None,
    }


def build_clock(
    *,
    trends: dict[str, Any] | None,
    squads: dict[str, Any] | None,
    decisions: list[dict[str, Any]],
    now: datetime,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    events: list[dict[str, Any]] = []
    kickoff = earliest_kickoff(trends, now=now)
    close_clock = None
    kick_moment = _parse_iso(kickoff)
    if kick_moment is not None:
        clock = _clock(kick_moment)
        events.append({"kind": "inicio_jornada", "label": "Inicio de jornada", **clock})
        close = kick_moment - timedelta(hours=24)
        close_clock = _clock(close)
        events.append(
            {
                "kind": "clausulazo_cierra",
                "label": "Cierre del mercado de clausulazos",
                **close_clock,
            }
        )
    if isinstance(squads, dict):
        for squad in squads.get("squads") or []:
            if not isinstance(squad, dict):
                continue
            owner = squad.get("manager_name") or squad.get("fantasy_team_name") or squad.get("team_id")
            for player in squad.get("players") or []:
                if not isinstance(player, dict):
                    continue
                lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
                if lock.get("present") is not True:
                    continue
                moment = _lock_moment(lock)
                if moment is None:
                    continue
                events.append(
                    {
                        "kind": "desbloqueo",
                        "label": f"Desbloqueo {_player_label(player)}",
                        "player_id": player.get("player_id"),
                        "name": player.get("name"),
                        "nickname": player.get("nickname"),
                        "manager_name": owner,
                        "is_self": squad.get("is_self") is True,
                        **_clock(moment),
                    }
                )
    for row in decisions:
        plan = row.get("bid_plan") if isinstance(row.get("bid_plan"), dict) else {}
        snipe = row.get("snipe") if isinstance(row.get("snipe"), dict) else {}
        if plan.get("how") != "snipe":
            continue
        moment = _parse_iso(snipe.get("fire_at"))
        if moment is None:
            continue
        events.append(
            {
                "kind": "snipe",
                "label": f"Snipe {_player_label(row)}",
                "player_id": row.get("player_id"),
                "name": row.get("name"),
                "nickname": row.get("nickname"),
                "amount_eur": plan.get("recommended_bid_eur"),
                **_clock(moment),
            }
        )
    events.sort(key=lambda item: (item.get("at") or "", item.get("kind") or ""))
    return events, kickoff, close_clock


def _clause_window_open(close_clock: dict[str, Any] | None, now: datetime) -> bool | None:
    if not isinstance(close_clock, dict):
        return None
    moment = _parse_iso(close_clock.get("at"))
    if moment is None:
        return None
    return now < moment


def attach_clause_window(
    clauses: dict[str, Any],
    *,
    trends: dict[str, Any] | None,
    squads: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """Añade cierre del mercado de clausulazos y ventana abierta/cerrada a cada oferta."""
    if not isinstance(clauses, dict) or clauses.get("ok") is False:
        return clauses
    _, _, close_clock = build_clock(trends=trends, squads=squads, decisions=[], now=now)
    window = _clause_window_open(close_clock, now)
    enriched = dict(clauses)
    enriched["clause_market_close"] = close_clock
    enriched["clause_window_open"] = window
    offers = []
    for row in clauses.get("offers") or []:
        if not isinstance(row, dict):
            continue
        copy = dict(row)
        copy["window_open"] = window
        offers.append(copy)
    enriched["offers"] = offers
    return enriched


def build_actions(
    *,
    optimize: dict[str, Any] | None,
    decisions: list[dict[str, Any]],
    clauses: dict[str, Any] | None,
    cash: int | None,
    close_clock: dict[str, Any] | None,
    now: datetime,
    lineup: dict[str, Any],
    trends: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if lineup.get("differs") is True:
        relineup = _relineup_action(lineup, cash=cash, trends=trends, market=market, optimize=optimize)
        if relineup is not None:
            actions.append(relineup)
    window = _clause_window_open(close_clock, now)
    running = cash
    if isinstance(clauses, dict):
        offers = [row for row in clauses.get("offers") or [] if isinstance(row, dict)]
        for pagar in offers:
            cost = pagar.get("buyout_clause_eur") if isinstance(pagar.get("buyout_clause_eur"), int) else None
            is_top = pagar.get("decision") == "PAGAR"
            blocked = window is False or not isinstance(running, int) or not isinstance(cost, int) or running - cost < 0
            rival = pagar.get("manager_name") or pagar.get("team_id") or "rival"
            objective = pagar.get("objective")
            delta = pagar.get("points_delta")
            detail_parts = [f"De {rival}."]
            if isinstance(objective, (int, float)) and not isinstance(objective, bool):
                detail_parts.append(f"Objetivo {objective}.")
            if isinstance(delta, (int, float)) and not isinstance(delta, bool):
                detail_parts.append(f"ROI +{delta} pts esperados.")
            if window is False:
                detail_parts.append("Ventana de clausulazos cerrada.")
            elif window is True:
                detail_parts.append("Ventana abierta.")
            if is_top and not blocked and isinstance(running, int) and isinstance(cost, int):
                running = running - cost
                actions.append(
                    {
                        "kind": "clausular",
                        "player_id": pagar.get("player_id"),
                        "name": pagar.get("name"),
                        "nickname": pagar.get("nickname"),
                        "position": pagar.get("position"),
                        "image_url": pagar.get("image_url"),
                        "amount_eur": cost,
                        "cash_after_eur": running,
                        "when": "ahora",
                        "detail": " ".join(detail_parts),
                        "requires_confirmation": True,
                        "eligible": True,
                        "points_delta": delta,
                        "objective": objective,
                        "manager_name": pagar.get("manager_name"),
                        "window_open": window,
                    }
                )
            elif is_top and blocked:
                actions.append(
                    {
                        "kind": "clausular",
                        "player_id": pagar.get("player_id"),
                        "name": pagar.get("name"),
                        "nickname": pagar.get("nickname"),
                        "position": pagar.get("position"),
                        "image_url": pagar.get("image_url"),
                        "amount_eur": cost,
                        "cash_after_eur": running,
                        "when": "ahora",
                        "detail": " ".join(detail_parts),
                        "requires_confirmation": True,
                        "eligible": False,
                        "points_delta": delta,
                        "objective": objective,
                        "manager_name": pagar.get("manager_name"),
                        "window_open": window,
                        "reason": "ventana_cerrada" if window is False else "caja_insuficiente",
                    }
                )
        protect_rows = [row for row in clauses.get("protect") or [] if isinstance(row, dict)]
        if protect_rows:
            row = protect_rows[0]
            subir = next(
                (
                    option
                    for option in row.get("options") or []
                    if isinstance(option, dict)
                    and option.get("kind") == "subir_clausula"
                    and option.get("eligible") is True
                ),
                None,
            )
            if isinstance(subir, dict):
                cost = subir.get("amount_eur") if isinstance(subir.get("amount_eur"), int) else None
                top = row.get("top_rival") if isinstance(row.get("top_rival"), dict) else {}
                rival = top.get("manager_name") or top.get("team_id") or "rival"
                detail = f"Protege {_player_label(row)}. Rival más probable: {rival}."
                if isinstance(running, int) and isinstance(cost, int) and running - cost >= 0:
                    running = running - cost
                    actions.append(
                        {
                            "kind": "subir_clausula",
                            "player_id": row.get("player_id"),
                            "name": row.get("name"),
                            "nickname": row.get("nickname"),
                            "position": row.get("position"),
                            "image_url": row.get("image_url"),
                            "amount_eur": cost,
                            "cash_after_eur": running,
                            "when": "ahora",
                            "detail": detail,
                            "requires_confirmation": True,
                            "eligible": True,
                            "target_clause_eur": subir.get("target_clause_eur"),
                        }
                    )
    bids = []
    for row in decisions:
        if not isinstance(row, dict):
            continue
        plan = row.get("bid_plan") if isinstance(row.get("bid_plan"), dict) else {}
        if row.get("primary_motive") in {"caja_otros_mercados", "caja_otras_pujas"}:
            continue
        # Veto de fuentes o techo: no entra en el plan aunque el veredicto
        # interno hubiera sido PUJAR. La home nunca propone una puja vetada.
        if row.get("is_vetoed") is True or row.get("action") == "NO":
            continue
        if row.get("decision") == "PUJAR" or (plan.get("how") == "snipe" and row.get("decision") == "ESPERAR"):
            bids.append(row)
    bids.sort(
        key=lambda row: (
            0 if (row.get("bid_plan") or {}).get("how") != "snipe" else 1,
            -float(row.get("score") or 0.0),
            str(row.get("player_id") or ""),
        )
    )
    for row in bids:
        plan = row.get("bid_plan") if isinstance(row.get("bid_plan"), dict) else {}
        how = plan.get("how") if isinstance(plan.get("how"), str) else "unknown"
        amount = plan.get("recommended_bid_eur")
        if not isinstance(amount, int):
            amount = row.get("bid_eur") if isinstance(row.get("bid_eur"), int) else None
        if not isinstance(amount, int) or not isinstance(running, int):
            continue
        if running - amount < 0:
            continue
        if how == "esperar":
            continue
        when = "snipe" if how == "snipe" else "ahora"
        if how == "snipe":
            # El gasto es en el cierre, pero la caja tiene que seguir cubriéndolo.
            running = running - amount
        else:
            running = running - amount
        snipe = row.get("snipe") if isinstance(row.get("snipe"), dict) else {}
        detail = plan.get("reason") or row.get("primary_motive") or "pujar"
        if when == "snipe" and snipe.get("fire_local_time"):
            detail = f"Snipe a las {snipe.get('fire_local_time')}. {detail}"
        overbid = plan.get("overbid") if isinstance(plan.get("overbid"), dict) else {}
        if overbid.get("status"):
            detail = f"{detail}. Sobrepuja {overbid.get('status')}"
            if isinstance(overbid.get("count"), int):
                detail = f"{detail} ({overbid.get('count')})"
        actions.append(
            {
                "kind": "pujar",
                "player_id": row.get("player_id"),
                "name": row.get("name"),
                "nickname": row.get("nickname"),
                "position": row.get("position"),
                "image_url": row.get("image_url"),
                "amount_eur": amount,
                "cash_after_eur": running,
                "when": when,
                "when_local_time": snipe.get("fire_local_time") if when == "snipe" else None,
                "detail": str(detail),
                "requires_confirmation": False,
                "eligible": True,
                "bid_how": how,
                "overbid_status": overbid.get("status"),
            }
        )
    return actions


def _gain_text(value: float | None) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "sin delta"
    number = float(value)
    if abs(number) < 0.05:
        return "sin cambio real"
    return f"{number:+.1f} pts"


def _relineup_action(
    lineup: dict[str, Any],
    *,
    cash: int | None,
    trends: dict[str, Any] | None,
    market: dict[str, Any] | None = None,
    optimize: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """La acción de once, con filtro de no agresión.

    Un cambio de alineación solo se propone si suma puntos reales o si es una
    excepción de supervivencia (once guardado inválido, caja en rojo o huecos).
    Un cambio destructivo nunca entra: es mejor no recomendar nada.
    """
    saved_formation = lineup.get("saved_formation")
    formation = lineup.get("formation") or "s/d"
    saved_valid = lineup.get("saved_valid") is True
    recommended_valid = lineup.get("recommended_valid") is True
    missing_slots = int(lineup.get("missing_slots") or 0)
    delta = lineup.get("points_delta")
    delta_known = isinstance(delta, (int, float)) and not isinstance(delta, bool)
    delta_value = float(delta) if delta_known else None
    no_delta = not delta_known or abs(delta_value or 0.0) < 0.05

    # 1. Hueco por posición: el hueco cuesta la jornada entera, así que la
    #    acción es cerrarlo aunque el once parcial sume más que el guardado.
    if missing_slots > 0:
        gaps = []
        options: list[dict[str, Any]] = []
        for gap in lineup.get("gaps") or []:
            if not isinstance(gap, dict):
                continue
            count = int(gap.get("missing") or 0)
            if count <= 0:
                continue
            label = gap.get("label") or f"Falta {count} {gap.get('position') or ''}".strip()
            gaps.append(f"{count} {gap.get('position')}")
            for bucket in (gap.get("options"), gap.get("market_fills")):
                for option in bucket or []:
                    if isinstance(option, dict):
                        options.append({**option, "missing": count})
        signed = ", ".join(row for row in (gap.strip() for gap in gaps) if row) or f"{missing_slots} hueco(s)"
        options.sort(key=lambda row: _money(row.get("sale_price")))
        cheapest = options[0] if options else None
        if cheapest is not None:
            buyer = _trend_played_points(trends, cheapest.get("player_id"))
            gain = round(float(buyer) - float(delta_value), 4) if delta_known and buyer is not None else None
            detail = (
                f"Se {signed}: jornada incompleta = 0 pts. El once parcial rinde "
                f"{_fmt_points(lineup.get('expected_points'))} y puede que sume más que el guardado, "
                f"pero no vale si falta un titular. Ficha al más barato: "
                f"{_player_label(cheapest)} por {_eur(cheapest.get('sale_price'))}."
            )
            return {
                "kind": "cerrar_hueco",
                "player_id": cheapest.get("player_id"),
                "name": cheapest.get("name"),
                "nickname": cheapest.get("nickname"),
                "position": cheapest.get("position"),
                "image_url": cheapest.get("image_url"),
                "amount_eur": cheapest.get("sale_price") if isinstance(cheapest.get("sale_price"), int) else None,
                "cash_after_eur": (
                    cash - cheapest["sale_price"]
                    if isinstance(cash, int) and isinstance(cheapest.get("sale_price"), int)
                    else cash
                ),
                "when": "ahora",
                "detail": detail,
                "requires_confirmation": False,
                "eligible": False,
                "reason": "hueco_por_cerrar",
                "points_delta": gain,
                "priority_override": 0,
                "enters": [cheapest.get("nickname") or cheapest.get("name")],
                "leaves": [],
                "gaps": gaps,
                "market_fills": options,
                "signed_gaps": signed,
                "saved_formation": saved_formation,
                "formation": formation,
            }
        return {
            "kind": "cerrar_hueco",
            "player_id": None,
            "name": None,
            "nickname": None,
            "position": None,
            "amount_eur": None,
            "cash_after_eur": cash,
            "when": "ahora",
            "detail": (
                f"Se {signed}: jornada incompleta = 0 pts. El mercado no ofrece un fichaje "
                "para ese hueco: libera caja antes del cierre."
            ),
            "requires_confirmation": False,
            "eligible": False,
            "reason": "hueco_sin_oferta",
            "points_delta": None,
            "priority_override": 0,
            "enters": [],
            "leaves": [],
            "gaps": gaps,
            "market_fills": [],
            "signed_gaps": signed,
            "saved_formation": saved_formation,
            "formation": formation,
        }

    # 2. Caja en rojo: vender sí o sí, aunque el movimiento reste puntos.
    if isinstance(cash, int) and cash < 0:
        fire = _fire_sale(lineup, cash=cash, trends=trends, market=market, optimize=optimize)
        if fire is not None:
            return fire
        return {
            "kind": "vender_emergencia",
            "player_id": None,
            "name": None,
            "nickname": None,
            "position": None,
            "amount_eur": None,
            "cash_after_eur": cash,
            "when": "ahora",
            "detail": "La caja está en rojo: el motor anula la jornada. Vende antes del cierre.",
            "requires_confirmation": True,
            "eligible": False,
            "reason": "caja_negativa",
            "points_delta": None,
            "priority_override": 0,
            "enters": [],
            "leaves": [],
            "saved_formation": saved_formation,
            "formation": formation,
        }

    # 3. Once guardado inválido (menos de 11): cierre de hueco con el once del motor.
    if not saved_valid:
        return {
            "kind": "cerrar_hueco",
            "player_id": None,
            "name": None,
            "nickname": None,
            "position": None,
            "amount_eur": 0,
            "cash_after_eur": cash,
            "when": "ahora",
            "detail": (
                f"El once guardado no junta 11 jugadores: jornada incompleta = 0 pts. "
                f"Guarda el XI {formation} del motor para cerrar el hueco."
            ),
            "requires_confirmation": False,
            "eligible": True,
            "points_delta": delta if delta_known else None,
            "priority_override": 0,
            "enters": [row.get("nickname") or row.get("name") for row in lineup.get("enters") or [] if isinstance(row, dict)],
            "leaves": [row.get("nickname") or row.get("name") for row in lineup.get("leaves") or [] if isinstance(row, dict)],
            "saved_formation": saved_formation,
            "formation": formation,
        }

    # 4. Sube formación con huecos: el motor no trae once completo.
    if not recommended_valid or lineup.get("recommended_partial") is True:
        return None

    # 5. Filtro de no agresión: cambiar piezas que bajan o dejan igual los
    #    puntos no es una acción. El once guardado ya es válido.
    if no_delta or (delta_value is not None and delta_value <= 0):
        return None

    # 6. Mejora real: solo se propone si además no deshace una decisión manual
    #    del jugador que el motor no puede valorar (ver _keeps_manual_override).
    if _keeps_manual_override(lineup, trends=trends):
        return None

    return {
        "kind": "alinear",
        "player_id": None,
        "name": None,
        "nickname": None,
        "position": None,
        "amount_eur": 0,
        "cash_after_eur": cash,
        "when": "ahora",
        "detail": _lineup_detail(lineup),
        "requires_confirmation": False,
        "eligible": True,
        "points_delta": round(delta_value, 4) if delta_value is not None else None,
        "enters": [row.get("nickname") or row.get("name") for row in lineup.get("enters") or [] if isinstance(row, dict)],
        "leaves": [row.get("nickname") or row.get("name") for row in lineup.get("leaves") or [] if isinstance(row, dict)],
        "saved_formation": saved_formation,
        "formation": formation,
    }


def _fmt_points(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "s/d"
    return f"{float(value):.1f}"


def _trend_played_points(trends: dict[str, Any] | None, player_id: Any) -> float | None:
    """E[pts] de jornada del jugador del mercado, si el scraper lo trae."""
    if not isinstance(player_id, str) or not isinstance(trends, dict):
        return None
    row = index_trends(trends).get(player_id)
    if row is None:
        return None
    from toolbox.analyzer import expected_opta_points_v2_for_candidate

    position = row.get("position")
    v2 = None
    if isinstance(position, str):
        try:
            v2 = expected_opta_points_v2_for_candidate(row, row, position=position, run_monte_carlo=False)
        except Exception:  # noqa: BLE001 — sin dato v2 se cae a la forma
            v2 = None
    if isinstance(v2, dict):
        value = v2.get("expected_points")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    form = row.get("form") if isinstance(row.get("form"), dict) else None
    if isinstance(position, str) and form is not None:
        from toolbox.analyzer import expected_opta_points

        opta, _ = expected_opta_points(position, form)
        return float(opta)
    return None


def _fire_sale(
    lineup: dict[str, Any],
    *,
    cash: int,
    trends: dict[str, Any] | None,
    market: dict[str, Any] | None = None,
    optimize: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Venta por emergencia: el suplente más barato de sacrificar que deja caja ≥ 0."""
    candidates: list[tuple[float, float, dict[str, Any], float | None]] = []
    for row in lineup.get("leaves") or []:
        if not isinstance(row, dict):
            continue
        player_id = row.get("player_id")
        price = _best_price(trends, player_id)
        if not isinstance(price, (int, float)) and isinstance(player_id, str):
            price = _market_values(market).get(player_id)
        if not isinstance(price, (int, float)) and isinstance(player_id, str) and isinstance(optimize, dict):
            roster = {
                player.get("player_id"): player
                for player in optimize.get("benched") or []
                if isinstance(player, dict)
            }
            price = _best_price({"players": [roster[player_id]]}, player_id) if player_id in roster else None
        value = played_points(row)
        candidates.append(
            (
                float(value) if value is not None else float("-inf"),
                float(price) if price is not None else float("inf"),
                row,
                price,
            )
        )
    if not candidates:
        return None
    # Primero, quien deja la caja en cero o por encima; si nadie llega, el que
    # más acerca la caja al cero (reducir el rojo ya evita parte del castigo).
    candidates.sort(
        key=lambda item: (
            0 if isinstance(item[3], (int, float)) and cash + int(item[3]) >= 0 else 1,
            -(float(item[3]) if isinstance(item[3], (int, float)) else 0.0),
            item[0],
        )
    )
    value, _, row, price = candidates[0]
    sale_price = price if isinstance(price, (int, float)) and not isinstance(price, bool) else None
    after = cash + int(sale_price) if sale_price is not None else None
    covers = isinstance(after, int) and after >= 0
    detail = (
        f"Caja en rojo ({_eur(cash)}): el motor anula la jornada. Sale por emergencia "
        f"{_player_label(row)}"
    )
    if sale_price is not None:
        detail += f" por {_eur(int(sale_price))}"
    if covers:
        detail += f" y la caja queda en {_eur(after)}."
    elif sale_price is not None:
        detail += f": aún quedará saldo negativo ({_eur(after)}). Vende un segundo jugador."
    else:
        detail += ". La API no trae precio de venta: confírmalo en el mercado."
    return {
        "kind": "vender_emergencia",
        "player_id": row.get("player_id"),
        "name": row.get("name"),
        "nickname": row.get("nickname"),
        "position": row.get("position"),
        "club": row.get("club"),
        "image_url": row.get("image_url"),
        "amount_eur": int(sale_price) if sale_price is not None else None,
        "cash_after_eur": int(after) if isinstance(after, int) else cash,
        "when": "ahora",
        "detail": detail,
        "requires_confirmation": True,
        "eligible": True,
        "points_delta": None,
        "priority_override": 0,
        "enters": [],
        "leaves": [row.get("nickname") or row.get("name")],
        "saved_formation": lineup.get("saved_formation"),
        "formation": lineup.get("formation"),
    }


def _market_values(market: dict[str, Any] | None) -> dict[str, float]:
    """Valor de mercado por jugador, leído del propio documento (mercado o libro de precios)."""
    values: dict[str, float] = {}
    if not isinstance(market, dict):
        return values
    rows: Any = market.get("listings")
    if not isinstance(rows, list):
        prices = market.get("prices")
        rows = prices if isinstance(prices, list) else []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        player_id = row.get("player_id")
        value = _best_price({"players": [row]}, player_id)
        if isinstance(player_id, str) and value is not None:
            values[player_id] = value
    return values


def _best_price(trends: dict[str, Any] | None, player_id: Any) -> float | None:
    """Precio de venta conocido (P90/valor/último precio). Nunca se inventa."""
    if not isinstance(player_id, str) or not isinstance(trends, dict):
        return None
    row = index_trends(trends).get(player_id)
    if row is None:
        return None
    for key in ("sell_price", "sale_price", "market_value", "price"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0:
            return float(value)
    return None


def _keeps_manual_override(lineup: dict[str, Any], *, trends: dict[str, Any] | None) -> bool:
    """El motor no deshace una apuesta manual que el dato solo «sospecha».

    Si el motor quiere sacar a un jugador al que el scraper da como suplente
    o duda, pero el usuario lo puso a mano en el once guardado, esa apuesta es
    suya: no se le fuerza el cambio. Con el dato en contra confirmado (lesión,
    sanción) no hay override: ahí el motor sí manda.
    """
    indexed = index_trends(trends) if isinstance(trends, dict) else {}
    for row in lineup.get("leaves") or []:
        if not isinstance(row, dict):
            continue
        player_id = row.get("player_id")
        trend = indexed.get(player_id) if isinstance(player_id, str) else None
        if not isinstance(trend, dict):
            continue
        if trend.get("injured") is True or trend.get("suspended") is True:
            continue
        if trend.get("doubt") is True or trend.get("is_doubtful") is True:
            return True
        status = trend.get("lineup_status")
        if isinstance(status, str) and status.strip().lower() in {"bench", "suplente", "no_titular"}:
            return True
    return False


def _lineup_detail(lineup: dict[str, Any]) -> str:
    enters = ", ".join(_player_label(row) for row in lineup.get("enters") or []) or "nadie"
    leaves = ", ".join(_player_label(row) for row in lineup.get("leaves") or []) or "nadie"
    delta = lineup.get("points_delta")
    suffix = f" Delta {delta}." if isinstance(delta, (int, float)) else ""
    formation = lineup.get("formation") or "s/d"
    return f"XI {formation}. Entran {enters}. Salen {leaves}.{suffix}"


def build_jornada_plan(
    *,
    market: dict[str, Any] | None,
    squads: dict[str, Any] | None,
    trends: dict[str, Any] | None,
    optimize: dict[str, Any] | None,
    needs: dict[str, Any] | None,
    decisions: dict[str, Any] | None,
    clauses: dict[str, Any] | None,
    experts: dict[str, Any] | None = None,
    now: datetime | None = None,
    league_race: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    decision_rows = decisions.get("decisions") if isinstance(decisions, dict) and isinstance(decisions.get("decisions"), list) else []
    clock, kickoff, close_clock = build_clock(
        trends=trends,
        squads=squads,
        decisions=[row for row in decision_rows if isinstance(row, dict)],
        now=current,
    )
    lineup = lineup_delta(optimize)
    if isinstance(optimize, dict):
        # Los fichajes que tapan cada hueco los calcula el optimizador: vienen
        # como market_fills (uno por hueco) y no como options dentro del gap.
        fills = [fill for fill in optimize.get("market_fills") or [] if isinstance(fill, dict)]
        gaps = [gap for gap in optimize.get("gaps") or [] if isinstance(gap, dict)]
        by_position = {str(fill.get("position")): fill.get("options") or [] for fill in fills}
        lineup["gaps"] = [
            {**gap, "options": by_position.get(str(gap.get("position"))) or gap.get("options") or []}
            for gap in gaps
        ]
    own = own_squad(squads) if isinstance(squads, dict) else None
    cash = own.get("cash") if isinstance(own, dict) and isinstance(own.get("cash"), int) else None
    actions = build_actions(
        optimize=optimize,
        decisions=[row for row in decision_rows if isinstance(row, dict)],
        clauses=clauses,
        cash=cash,
        close_clock=close_clock,
        now=current,
        lineup=lineup,
        trends=trends,
        market=market,
    )
    notes = _lineup_notes(trends, experts)
    ranked = resolve_actions(actions, cash=cash, kickoff=kickoff, now=current)
    safety = red_line(optimize=optimize, cash=cash, lineup=lineup, actions=ranked)
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "plan",
        "sends": False,
        "league_id": (squads or {}).get("league_id") if isinstance(squads, dict) else None,
        "league_name": (squads or {}).get("league_name") if isinstance(squads, dict) else None,
        "fetched_at": current.astimezone(timezone.utc).isoformat(),
        "cash_eur": cash,
        "kickoff": kickoff,
        "clause_market_close": close_clock,
        "clock": clock,
        "lineup": lineup,
        "actions": actions,
        "priority_actions": ranked,
        "red_line": safety,
        "league_race": league_race if isinstance(league_race, dict) else None,
        "protect": clauses.get("protect") if isinstance(clauses, dict) and isinstance(clauses.get("protect"), list) else [],
        "clause_offers": clauses.get("offers") if isinstance(clauses, dict) and isinstance(clauses.get("offers"), list) else [],
        "expert_mentions": experts.get("mentions") if isinstance(experts, dict) and isinstance(experts.get("mentions"), list) else [],
        "lineup_notes": notes,
        "expert_sources": experts.get("sources") if isinstance(experts, dict) and isinstance(experts.get("sources"), dict) else {},
        "market_summary": decisions.get("summary") if isinstance(decisions, dict) else None,
        "needs_alert_count": len(needs.get("clause_alerts") or []) if isinstance(needs, dict) else None,
    }


def _priority_of(action: dict[str, Any]) -> int:
    """Orden duro de la home: primero no perder la jornada, luego sumar.

    1. Alinear (sin XI no hay nada).
    2. Clausulazo (ventana que se cierra).
    3. Blindaje de cláusula propia.
    4. Puja, en el orden de score que ya trae ``build_actions``.

    El sort de Python es estable: dentro del mismo grupo se respeta el orden
    original, así no se reordena una puja mejor por ser más barata.
    """
    override = action.get("priority_override")
    if isinstance(override, int) and not isinstance(override, bool):
        return override
    kind = action.get("kind")
    if kind == "alinear":
        return 0
    if kind == "clausular":
        return 1
    if kind == "subir_clausula":
        return 2
    return 3


def _money(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _ignored_cost(action: dict[str, Any]) -> str:
    """Qué pasa si no se hace. Frase corta, sin condicionales encadenados."""
    kind = action.get("kind")
    if kind == "alinear":
        return "Dejas puntos esperados en el banquillo."
    if kind == "cerrar_hueco":
        return "Una jornada con huecos por posición vale cero puntos."
    if kind == "vender_emergencia":
        return "La caja sigue en rojo y el motor anula la jornada."
    if kind == "clausular":
        return "El rival lo renueva o lo sube: se cierra la ventana barata."
    if kind == "subir_clausula":
        return "Un rival puede llevarse al jugador por su cláusula actual."
    if kind == "pujar":
        if action.get("when") == "snipe":
            return "Si no lo programas, el cierre te pilla sin puja."
        return "Otro manager se lo lleva al precio actual."
    return "Nada crítico: es una mejora, no una obligación."


def _headline(action: dict[str, Any]) -> str:
    kind = action.get("kind")
    name = action.get("nickname") or action.get("name")
    if kind == "alinear":
        enters = action.get("enters") or []
        leaves = action.get("leaves") or []
        if enters and leaves:
            return f"Cambia a {enters[0]} por {leaves[0]}"
        return "Alinea el once recomendado"
    if kind == "cerrar_hueco":
        gaps = action.get("signed_gaps")
        if name:
            return f"Cierra el hueco: ficha a {name}"
        return f"Cierra el hueco ({gaps})" if isinstance(gaps, str) and gaps else "Cierra los huecos del once"
    if kind == "vender_emergencia":
        if name:
            return f"Venta obligatoria: vende a {name}"
        return "Venta obligatoria: saca la caja del rojo"
    if kind == "clausular":
        return f"Paga la cláusula de {name or 'el jugador'}"
    if kind == "subir_clausula":
        return f"Sube la cláusula de {name or 'tu jugador'}"
    if kind == "pujar":
        amount = action.get("amount_eur")
        if action.get("when") == "snipe":
            return f"Programa la puja por {name or 'el jugador'}"
        return f"Puja {_eur(amount)} por {name or 'el jugador'}"
    return "Acción pendiente"



def _eur(value: Any) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        return "s/d"
    if value >= 1_000_000:
        millions = value / 1_000_000
        text = f"{millions:.2f}".rstrip("0").rstrip(".")
        return f"{text} M€"
    return f"{value:,} €".replace(",", ".")


def _when_text(action: dict[str, Any], kickoff: str | None, now: datetime) -> str:
    moment = _parse_iso(kickoff)
    if action.get("when") == "snipe":
        clock = action.get("when_local_time")
        return f"{clock} (cierre)" if isinstance(clock, str) and clock else "En el cierre"
    if moment is None:
        return "Ya"
    remaining = moment - now
    hours = remaining.total_seconds() / 3600
    if hours <= 0:
        return "Ya"
    if hours < 1:
        return f"Antes de {int(remaining.total_seconds() // 60)} min"
    if hours < 24:
        return f"Antes de {int(hours)} h"
    return f"Antes de {int(hours // 24)} d"


def resolve_actions(
    actions: list[dict[str, Any]],
    *,
    cash: int | None,
    kickoff: str | None,
    now: datetime,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Las 4 tarjetas de la home, con la estructura fija de decisión.

    ``what`` / ``cost`` / ``when`` / ``ignore`` no se delegan al usuario: si
    una acción no se puede ejecutar (caja, ventana), se marca ineligible y se
    explica en una línea.
    """
    rows = [row for row in actions if isinstance(row, dict)]
    rows.sort(key=_priority_of)
    ranked: list[dict[str, Any]] = []
    for index, action in enumerate(rows[:limit]):
        kind = action.get("kind")
        cost = action.get("amount_eur")
        eligible = action.get("eligible") is not False
        reason = action.get("reason") if isinstance(action.get("reason"), str) else None
        after = action.get("cash_after_eur")
        delta = action.get("points_delta")
        # Un cambio de once que baja o deja igual los puntos nunca es «HAZLO»:
        # si el motor lo manda con delta negativo, la tarjeta lo dice.
        regresses = (
            kind == "alinear"
            and isinstance(delta, (int, float))
            and not isinstance(delta, bool)
            and float(delta) <= 0
        )
        verdict = "NO" if not eligible or regresses else "HAZLO"
        if regresses and reason is None:
            reason = "resta_puntos"
        ranked.append(
            {
                **action,
                "rank": index + 1,
                "verdict": verdict,
                "what": _headline(action),
                "cost_eur": cost if isinstance(cost, int) and not isinstance(cost, bool) else 0,
                "cost_label": "Gratis"
                if kind in {"alinear", "cerrar_hueco"}
                else _eur(cost),
                "cash_after_eur": after if isinstance(after, int) and not isinstance(after, bool) else cash,
                "when": action.get("when") or "ahora",
                "when_label": _when_text(action, kickoff, now),
                "ignore": _ignored_cost(action),
                "blocked_reason": reason,
                "eligible": eligible,
                "points_delta": delta,
                "enters": action.get("enters"),
                "leaves": action.get("leaves"),
                "is_lineup": kind in {"alinear", *SURVIVAL_KINDS},
                "is_survival": kind in SURVIVAL_KINDS,
            }
        )
    return ranked


def _lineup_pending(lineup: dict[str, Any]) -> bool:
    """Solo hay cambio de once pendiente si suma puntos o si el guardado no vale.

    Que el motor prefiera otra formación con los mismos puntos no es una
    acción: no se manda al usuario a tocar un once ya válido.
    """
    if lineup.get("differs") is not True:
        return False
    if lineup.get("saved_valid") is False:
        return True
    delta = lineup.get("points_delta")
    if isinstance(delta, (int, float)) and not isinstance(delta, bool):
        return float(delta) > 0.05
    # Sin delta comparable no se puede prometer mejora: el recomendado manda.
    return lineup.get("xi_changed") is True


def _lineup_red_line_detail(lineup: dict[str, Any]) -> str:
    if _lineup_pending(lineup) is False:
        delta = lineup.get("points_delta")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and float(delta) < 0:
            return (
                "El once del motor rinde menos que el guardado: se mantiene el guardado "
                "y no se propone el cambio."
            )
        return "Ya está alineado"
    if lineup.get("saved_valid") is False:
        return "El once guardado no junta 11 jugadores: hay que cerrar el hueco"
    return "Hay cambios pendientes de guardar"


def red_line(
    *,
    optimize: dict[str, Any] | None,
    cash: int | None,
    lineup: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Checklist de supervivencia. Si algo falla, la jornada vale 0."""
    document = optimize if isinstance(optimize, dict) else {}
    void = document.get("matchday_void") is True
    reasons = [reason for reason in document.get("void_reasons") or [] if isinstance(reason, str)]
    xi_rows = document.get("xi") if isinstance(document.get("xi"), list) else []
    gaps = document.get("gaps") if isinstance(document.get("gaps"), list) else []
    missing = sum(int(gap.get("missing") or 0) for gap in gaps if isinstance(gap, dict))
    if missing:
        xi_count = max(0, 11 - missing)
    else:
        xi_count = len([row for row in xi_rows if isinstance(row, dict)])
    cash_known = isinstance(cash, int)
    checks = [
        {
            "key": "cash",
            "label": "Caja ≥ 0",
            "status": "fail" if cash_known and cash < 0 else ("unknown" if not cash_known else "ok"),
            "detail": _eur(cash) if cash_known else "La API no trajo el saldo",
            "value": cash if cash_known else None,
        },
        {
            "key": "xi",
            "label": "XI con 11 jugadores",
            "status": "fail" if void and "empty_slot" in reasons else ("ok" if xi_count >= 11 else "unknown"),
            "detail": f"{xi_count}/11 en el once" if xi_count else "Sin once calculado",
            "value": xi_count,
        },
        {
            "key": "lineup",
            "label": "Once guardado = recomendado",
            "status": "warn" if _lineup_pending(lineup) else "ok",
            "detail": _lineup_red_line_detail(lineup),
            "value": None,
        },
    ]
    failing = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warn"]
    if failing:
        status = "fail"
        headline = "Línea roja: la jornada vale 0"
    elif warnings:
        status = "warn"
        headline = "Salvado, pero sin confirmar"
    else:
        status = "ok"
        headline = "Línea roja cubierta"
    return {
        "status": status,
        "headline": headline,
        "checks": checks,
        "failing": [check["key"] for check in failing],
        "warnings": [check["key"] for check in warnings],
        # Solo cuentan las acciones que de verdad se pueden ejecutar: una
        # cláusula bloqueada o un cierre sin oferta no son «pendientes».
        "pending_actions": len([row for row in actions if row.get("eligible") is not False]),
    }


def _lineup_notes(trends: dict[str, Any] | None, experts: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(experts, dict):
        return []
    raw = experts.get("lineup_agreement")
    if not isinstance(raw, dict) or not raw:
        return []
    indexed = {}
    if isinstance(trends, dict):
        for player in trends.get("players") or []:
            if isinstance(player, dict) and isinstance(player.get("player_id"), str):
                indexed[player["player_id"]] = player
    notes = []
    for player_id, label in raw.items():
        player = indexed.get(player_id) or {}
        notes.append(
            {
                "player_id": player_id,
                "name": player.get("name"),
                "nickname": player.get("nickname"),
                "club": player.get("club"),
                "agreement": label,
            }
        )
    notes.sort(key=lambda row: (row.get("agreement") != "split", str(row.get("name") or "")))
    return notes


def _catalog(trends: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(trends, dict):
        return []
    players = trends.get("players")
    return [row for row in players if isinstance(row, dict)] if isinstance(players, list) else []


def experts_from_pages(
    pages: dict[str, Any] | None,
    trends: dict[str, Any] | None,
    *,
    note_text: str | None = None,
) -> dict[str, Any]:
    catalog = _catalog(trends)
    mentions = link_mentions(list((pages or {}).get("mentions") or []), catalog)
    bielsa_rows: list[dict[str, Any]] = []
    clubs: set[str] = set()
    for lineup in (pages or {}).get("lineups") or []:
        if not isinstance(lineup, dict):
            continue
        club = lineup.get("club") if isinstance(lineup.get("club"), str) else None
        if club:
            clubs.add(club)
        for name in lineup.get("players") or []:
            if isinstance(name, str):
                bielsa_rows.append({"name": name, "kind": "probable", "source": "bielsa", "club": club})
    bielsa_linked = link_mentions(bielsa_rows, catalog)
    note_linked = mentions_from_text(note_text or "", catalog)
    agreement = agreement_for_trends(
        catalog,
        {row["player_id"] for row in bielsa_linked if isinstance(row.get("player_id"), str)},
        bielsa_clubs=clubs,
    )
    return {
        "mentions": mentions + bielsa_linked + note_linked,
        "lineup_agreement": agreement,
        "sources": (pages or {}).get("sources") if isinstance(pages, dict) else {},
    }


def read_expert_note(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")[:_NOTE_LIMIT]
    except OSError:
        return ""


def write_expert_note(path: Path, text: str) -> str:
    cleaned = text if isinstance(text, str) else ""
    cleaned = cleaned[:_NOTE_LIMIT]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned, encoding="utf-8")
    return cleaned


def plan_from_documents(
    market: dict[str, Any],
    squads: dict[str, Any],
    trends: dict[str, Any] | None,
    optimize: dict[str, Any] | None,
    flip: dict[str, Any] | None,
    needs: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    experts: dict[str, Any] | None = None,
    memory_path: Path | None = None,
    note_text: str | None = None,
    league_race: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    rivals = needs.get("rivals") if isinstance(needs, dict) and isinstance(needs.get("rivals"), list) else None
    if not rivals:
        rivals = rival_snapshots(squads, trends)
    decisions = build_market_decisions(
        market,
        trends,
        flip,
        optimize,
        owned_ids=None,
        rivals=rivals,
        squads=squads,
        history=needs.get("history") if isinstance(needs, dict) and isinstance(needs.get("history"), dict) else None,
        now=current,
    )
    clauses = attach_clause_window(
        build_clause_intel(squads, trends, optimize, rivals, now=current),
        trends=trends,
        squads=squads,
        now=current,
    )
    expert_doc = experts
    if expert_doc is None and note_text:
        expert_doc = experts_from_pages({"mentions": [], "lineups": [], "sources": {}}, trends, note_text=note_text)
    elif isinstance(expert_doc, dict) and note_text:
        extra = mentions_from_text(note_text, _catalog(trends))
        merged = list(expert_doc.get("mentions") or []) + extra
        expert_doc = {**expert_doc, "mentions": merged}
    race = league_race if isinstance(league_race, dict) else build_league_race(squads, trends, optimize, market=market)
    document = build_jornada_plan(
        market=market,
        squads=squads,
        trends=trends,
        optimize=optimize,
        needs=needs,
        decisions=decisions,
        clauses=clauses,
        experts=expert_doc,
        now=current,
        league_race=race,
    )
    audit = build_audit(optimize, squads, now=current, kickoff=document.get("kickoff"))
    if memory_path is not None:
        audit = append_audit(audit, memory_path, now=current)
    document["audit"] = audit
    document["decisions"] = decisions.get("decisions")
    return document


def build_plan_command(
    client: Any,
    *,
    league: str | None,
    fresh: bool,
    now: datetime | None = None,
    memory_path: Path | None = None,
    note_path: Path | None = None,
) -> dict[str, Any]:
    """Ciclo de lectura: liga, señales, once, pujas y cláusulas. No envía órdenes."""
    from toolbox.analyzer import optimize_from_documents, own_squad
    from toolbox.bidding import flip_from_documents, load_activity, needs_from_documents
    from toolbox.cache import ResponseCache
    from toolbox.scrapers import build_trends

    market = client.market_document(league, fresh=fresh)
    squads = client.squads_document(league, fresh=fresh)
    trends = build_trends(league=league, fresh=fresh, laliga=client, market=market, squads=squads)
    store = ResponseCache()
    current = now or datetime.now(timezone.utc)
    try:
        optimized = optimize_from_documents(squads, trends, cache=store, fresh=fresh, market=market)
        own = own_squad(squads)
        team_id = own.get("team_id") if isinstance(own, dict) else None
        if isinstance(team_id, str) and team_id and hasattr(client, "saved_lineup"):
            optimized["saved_lineup"] = client.saved_lineup(team_id, fresh=fresh)
        flipped = flip_from_documents(
            market,
            squads,
            trends,
            lineup=optimized if optimized.get("ok") else None,
            now=current,
            cache=store,
            fresh=fresh,
        )
        league_id = squads.get("league_id") if isinstance(squads.get("league_id"), str) else None
        activity = load_activity(client, league_id, fresh=fresh)
        needs = needs_from_documents(
            market,
            squads,
            trends,
            activity,
            now=current,
            cache=store,
            fresh=fresh,
        )
    finally:
        store.close()
    note = read_expert_note(note_path) if note_path is not None else ""
    experts = load_plan_experts(trends, fresh=fresh, note_text=note)
    return plan_from_documents(
        market,
        squads,
        trends,
        optimized,
        flipped,
        needs,
        now=current,
        experts=experts,
        memory_path=memory_path,
    )


def load_plan_experts(trends: dict[str, Any] | None, *, fresh: bool, note_text: str | None) -> dict[str, Any]:
    from toolbox.net import ExternalClient

    pages: dict[str, Any] = {"mentions": [], "lineups": [], "sources": {}}
    try:
        with ExternalClient() as client:
            pages = load_expert_pages(client, fresh=fresh)
    except Exception as exc:  # noqa: BLE001 — el plan sigue sin los expertos
        pages = {
            "mentions": [],
            "lineups": [],
            "sources": {"experts": {"ok": False, "count": 0, "error": str(exc), "from_cache": False}},
        }
    return experts_from_pages(pages, trends, note_text=note_text)

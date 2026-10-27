"""Historial de la liga: caja compartida y puja que gana una guerra.

La actividad oficial pagina en ``/leagues/{id}/activity/{page}``. El presupuesto
inicial no viene en ese JSON. Si la caja propia cuadra con un residual, ese
residual es el presupuesto de toda la liga. En un rival la caja reconstruida
es un techo: subir la cláusula propia no aparece en el historial.

La prima de una compra solo existe si hay ``price_snapshots`` del mismo día.
Una diferencia de hasta el 2 % cabe en el movimiento del valor después del
cierre de las 14:08. Por encima del 100 % es un disparo y no fija la puja.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from toolbox.bidding import reconstruct_ledgers

_MADRID = ZoneInfo("Europe/Madrid")

DRIFT = 0.02
BOMB = 1.0
MIN_WARS = 3
ROUND_STEP = 100_000
ROUND_NUDGE_MAX = 100

_ACTIVITY_KIND = {
    1: "clause",
    6: "premium",
    12: "premium",
    20: "premium",
    21: "premium",
    22: "premium",
    23: "premium",
    24: "premium",
    31: "buy",
    33: "sell",
}


def parse_activity_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Una fila de actividad oficial. El id de equipo se resuelve después."""
    type_id = row.get("activityTypeId")
    if isinstance(type_id, bool) or not isinstance(type_id, int):
        return None
    kind = _ACTIVITY_KIND.get(type_id)
    if kind is None:
        return None
    amount = row.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int):
        return None
    user = row.get("user1Id")
    if isinstance(user, bool) or user is None:
        return None
    manager_id = str(user)
    player = row.get("playerMasterId")
    event: dict[str, Any] = {
        "team_id": manager_id,
        "manager_id": manager_id,
        "kind": kind,
        "amount_eur": abs(amount),
        "player_id": None if player is None or isinstance(player, bool) else str(player),
        "label": None,
        "at": row.get("createdAt") if isinstance(row.get("createdAt"), str) else None,
        "activity_type_id": type_id,
    }
    counterparty = row.get("user2Id")
    if type_id == 1 and counterparty is not None and not isinstance(counterparty, bool):
        event["counterparty_manager_id"] = str(counterparty)
    return event


def event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    """Identidad contable de un movimiento: qué se mueve, cuánto y cuándo."""
    return (
        event.get("kind"),
        event.get("amount_eur"),
        event.get("at"),
        event.get("player_id"),
    )


def _already_has_sale(event: dict[str, Any], seller_id: str, flow: list[dict[str, Any]]) -> bool:
    """El vendedor ya trae el cobro de esta cláusula en el flujo de origen.

    1. El asiento ``sell`` ya existe: ``books_from_activity`` sobre un flujo que
       ya pasó por aquí (o el motor de ``rival_intel``). Repetirlo infla la caja
       del vendedor una vez por cada lectura.
    2. El mismo importe llegó como ``premium``: el historial ya abonó el dinero
       y la fila ``clause`` solo documenta la subida.
    """
    key = event_key(event)
    for other in flow:
        if not isinstance(other, dict) or other.get("team_id") != seller_id:
            continue
        if other.get("kind") == "sell" and event_key(other) == key:
            return True
        # El cobro de una cláusula llega como prima con el importe pagado.
        # Exigir ese ``income_type`` idéntico hacía el filtro inútil fuera de
        # este módulo y volvía a sumar el cobro.
        if (
            other.get("kind") == "premium"
            and other.get("income_type", "premium") == "premium"
            and other.get("amount_eur") == event.get("amount_eur")
        ):
            return True
    return False


def bind_activity(events: list[dict[str, Any]], squads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pasa de id de mánager a id de equipo y anota el cobro de la cláusula."""
    manager_to_team: dict[str, str] = {}
    for squad in squads:
        manager_id = squad.get("manager_id")
        team_id = squad.get("team_id")
        if isinstance(manager_id, str) and manager_id and isinstance(team_id, str) and team_id:
            manager_to_team[manager_id] = team_id
    flow = [event for event in events if isinstance(event, dict)]
    bound: list[dict[str, Any]] = []
    for event in flow:
        if "activity_type_id" not in event and "manager_id" not in event:
            bound.append(event)
            continue
        item = {key: value for key, value in event.items() if key != "_flow"}
        manager_id = item.get("manager_id") if isinstance(item.get("manager_id"), str) else item.get("team_id")
        manager_key = str(manager_id) if manager_id is not None else ""
        item["manager_id"] = manager_key or None
        item["team_id"] = manager_to_team.get(manager_key, manager_key)
        bound.append(item)
        counterparty = item.get("counterparty_manager_id")
        if item.get("kind") != "clause" or not isinstance(counterparty, str) or not counterparty:
            continue
        # El cobro ya está en el flujo que llega del historial. Sintetizarlo
        # otra vez devuelve al vendedor dinero que ya se le había abonado.
        seller_id = manager_to_team.get(counterparty, counterparty)
        if not seller_id or seller_id == item.get("team_id"):
            continue
        if _already_has_sale(item, seller_id, flow):
            continue
        seller = dict(item)
        seller["kind"] = "sell"
        seller["manager_id"] = counterparty
        seller["team_id"] = seller_id
        seller["counterparty_manager_id"] = item.get("manager_id")
        seller["label"] = "clausula_cobrada"
        bound.append(seller)
    return bound


def _squad_cash(squad: dict[str, Any]) -> int | None:
    cash = squad.get("cash")
    return cash if isinstance(cash, int) and not isinstance(cash, bool) else None


def _squad_spent(squad: dict[str, Any]) -> int:
    """Gasto mínimo ya realizado por un rival según su plantilla.

    Es el suelo de su capital inicial: no puede haber pagado más de lo que
    tuvo. Sirve para descartar un residual propio que no puede ser de todos.
    """
    total = 0
    for player in squad.get("players") or []:
        if not isinstance(player, dict):
            continue
        for key in ("purchase_price", "price", "market_value", "value"):
            value = player.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                total += value
                break
    return total


def _flow_balance(events: list[dict[str, Any]], team_id: str) -> int:
    """Variación neta de caja del equipo según el historial (sin el inicial)."""
    balance = 0
    for event in events:
        if not isinstance(event, dict) or event.get("team_id") != team_id:
            continue
        amount = event.get("amount_eur")
        if isinstance(amount, bool) or not isinstance(amount, int):
            continue
        kind = event.get("kind")
        if kind in {"premium", "sell"}:
            balance += amount
        elif kind in {"buy", "clause"}:
            balance -= amount
    return balance


def shared_initial_is_plausible(initial: int, events: list[dict[str, Any]], squads: list[dict[str, Any]]) -> bool:
    """¿El residual propio puede ser el presupuesto de todos?

    Solo si cada rival con caja publicada cuadra con ese mismo inicial y con
    su propio flujo. Una liga con presupuestos distintos deja de cuadrar y
    entonces el residual propio no se reparte: se queda en casa.
    """
    for squad in squads:
        if not isinstance(squad, dict) or squad.get("is_self") is True:
            continue
        team_id = squad.get("team_id")
        if not isinstance(team_id, str) or not team_id:
            continue
        cash = _squad_cash(squad)
        if cash is None:
            continue
        if initial + _flow_balance(events, team_id) != cash:
            return False
        if _squad_spent(squad) > initial:
            return False
    return True


def infer_shared_initial(
    events: list[dict[str, Any]],
    squads: list[dict[str, Any]],
) -> tuple[int | None, str | None]:
    """Residual de la caja propia. None si el historial ya trae el presupuesto o no cuadra.

    El residual solo se comparte con la liga si el resto de cajas publicadas
    lo confirman. Si un rival no cuadra (presupuestos distintos), el historial
    manda: sin inicial explícito, su caja reconstruida queda en null en vez de
    falsearla con el residual propio.
    """
    if any(isinstance(event, dict) and event.get("kind") == "initial" for event in events):
        return None, "historial"
    own = next((squad for squad in squads if isinstance(squad, dict) and squad.get("is_self") is True), None)
    if not isinstance(own, dict):
        return None, None
    cash = _squad_cash(own)
    team_id = own.get("team_id")
    if cash is None or not isinstance(team_id, str):
        return None, None
    if not events:
        return None, None
    initial = cash - _flow_balance(events, team_id)
    if initial <= 0:
        return None, None
    if not shared_initial_is_plausible(initial, events, squads):
        return None, None
    return initial, "caja_propia"


def with_shared_initial(
    events: list[dict[str, Any]],
    squads: list[dict[str, Any]],
    initial: int | None,
) -> list[dict[str, Any]]:
    if not isinstance(initial, int):
        return events
    present = {event.get("team_id") for event in events if isinstance(event, dict) and event.get("kind") == "initial"}
    injected: list[dict[str, Any]] = []
    for squad in squads:
        team_id = squad.get("team_id") if isinstance(squad, dict) else None
        if not isinstance(team_id, str) or not team_id or team_id in present:
            continue
        # Un rival cuya caja publicada contradice el residual no se rellena:
        # la cota inventada descuadraría su libro y sus primas.
        published = _squad_cash(squad)
        if published is not None and initial + _flow_balance(events, team_id) != published:
            continue
        injected.append(
            {
                "team_id": team_id,
                "manager_id": squad.get("manager_id") if isinstance(squad.get("manager_id"), str) else None,
                "kind": "initial",
                "amount_eur": initial,
                "player_id": None,
                "label": "presupuesto_inferido",
                "at": None,
            }
        )
    return [*injected, *events]


def annotate_ledgers(
    ledgers: list[dict[str, Any]],
    squads: list[dict[str, Any]],
    source: str | None,
) -> None:
    own_ids = {squad.get("team_id") for squad in squads if isinstance(squad, dict) and squad.get("is_self") is True}
    for ledger in ledgers:
        has_initial = isinstance(ledger.get("initial_budget_eur"), int)
        ledger["initial_source"] = source if has_initial else None
        ledger["cash_is_ceiling"] = bool(
            source == "caja_propia" and has_initial and ledger.get("team_id") not in own_ids
        )


def books_from_activity(
    squads: list[dict[str, Any]],
    events: list[dict[str, Any]],
    snapshots: dict[tuple[str, str], int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Libros de caja y la muestra de guerras. No inventa primas sin valor del día."""
    roster = [squad for squad in squads if isinstance(squad, dict)]
    bound = bind_activity([event for event in events if isinstance(event, dict)], roster)
    initial, source = infer_shared_initial(bound, roster)
    prepared = with_shared_initial(bound, roster, initial) if source == "caja_propia" else bound
    ledgers = reconstruct_ledgers(roster, prepared)
    annotate_ledgers(ledgers, roster, source if initial is not None or source == "historial" else None)
    if source == "historial" and not any(ledger.get("initial_budget_eur") is not None for ledger in ledgers):
        source = None
    history = build_history(prepared, snapshots or {}, ledgers, source=source if initial is not None or source == "historial" else None)
    history["activity_buys"] = collect_activity_buys(prepared, snapshots or {}, ledgers)
    return ledgers, history


def madrid_day(at: str | None) -> str | None:
    """Fecha civil Europe/Madrid del movimiento. None si no hay marca usable."""
    if not isinstance(at, str) or not at:
        return None
    text = at.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return text[:10] if len(text) >= 10 else None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_MADRID)
    return moment.astimezone(_MADRID).date().isoformat()


def build_history(
    events: list[dict[str, Any]],
    snapshots: dict[tuple[str, str], int],
    ledgers: list[dict[str, Any]],
    *,
    source: str | None,
) -> dict[str, Any]:
    buy_count = 0
    priced = 0
    bombs = 0
    samples: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("activity_type_id") != 31:
            continue
        buy_count += 1
        player_id = event.get("player_id")
        day = madrid_day(event.get("at") if isinstance(event.get("at"), str) else None)
        amount = event.get("amount_eur")
        team_id = event.get("team_id")
        if not isinstance(player_id, str) or not isinstance(day, str):
            continue
        if isinstance(amount, bool) or not isinstance(amount, int) or not isinstance(team_id, str):
            continue
        ref = snapshots.get((player_id, day))
        if not isinstance(ref, int) or ref <= 0:
            continue
        priced += 1
        premium = (amount - ref) / ref
        if premium <= DRIFT:
            continue
        if premium > BOMB:
            # Una guerra extrema sigue siendo una guerra: la puja de corte real
            # la incluye. Antes se tiraba y el ``clearing_quote`` salía corto
            # justo en los casos donde el rival paga de verdad.
            bombs += 1
        samples.append(
            {
                "team_id": team_id,
                "premium": premium,
                "round_extra": round_extra(amount),
                "extreme": premium > BOMB,
            }
        )
    premiums = [sample["premium"] for sample in samples]
    median = statistics.median(premiums) if len(premiums) >= MIN_WARS else None
    p75 = _percentile(premiums, 0.75) if len(premiums) >= MIN_WARS else None
    cash_rows = []
    for ledger in ledgers:
        team_id = ledger.get("team_id")
        if not isinstance(team_id, str):
            continue
        observed = ledger.get("observed_cash_eur")
        reconstructed = ledger.get("reconstructed_cash_eur")
        cash = observed if isinstance(observed, int) and not isinstance(observed, bool) else reconstructed
        if isinstance(cash, bool) or not isinstance(cash, int):
            continue
        cash_rows.append(
            {
                "team_id": team_id,
                "cash_eur": cash,
                "cash_is_ceiling": ledger.get("cash_is_ceiling") is True,
            }
        )
    return {
        "initial_budget_eur": next(
            (ledger.get("initial_budget_eur") for ledger in ledgers if isinstance(ledger.get("initial_budget_eur"), int)),
            None,
        ),
        "initial_source": source,
        "buy_count": buy_count,
        "priced_count": priced,
        "war_count": len(samples),
        "bomb_count": bombs,
        "median_premium": median,
        "p75_premium": p75,
        "samples": samples,
        "cash": cash_rows,
    }


def round_extra(amount: int) -> int | None:
    """Euros por encima de un millón, o 0 si la puja va a centenas de millar."""
    remainder = amount % 1_000_000
    if 0 <= remainder <= ROUND_NUDGE_MAX:
        return remainder
    if amount % ROUND_STEP == 0:
        return 0
    return None


def clearing_quote(sale: int, history: dict[str, Any] | None) -> dict[str, Any] | None:
    """Puja para ganar a quien puede pagarla. None si hay menos de 3 guerras útiles."""
    if not isinstance(history, dict) or isinstance(sale, bool) or not isinstance(sale, int) or sale <= 0:
        return None
    cash = {
        row["team_id"]: row["cash_eur"]
        for row in history.get("cash") or []
        if isinstance(row, dict) and isinstance(row.get("team_id"), str) and isinstance(row.get("cash_eur"), int)
    }
    able = []
    for sample in history.get("samples") or []:
        if not isinstance(sample, dict):
            continue
        team_id = sample.get("team_id")
        premium = sample.get("premium")
        if not isinstance(team_id, str) or isinstance(premium, bool) or not isinstance(premium, (int, float)):
            continue
        available = cash.get(team_id)
        if not isinstance(available, int) or available < sale:
            continue
        able.append(sample)
    if len(able) < MIN_WARS:
        return None
    premiums = sorted(float(sample["premium"]) for sample in able)
    extras = [sample.get("round_extra") for sample in able if isinstance(sample.get("round_extra"), int)]
    round_style = len(extras) * 2 >= len(able)
    nudge = max(extras) if round_style and extras else 0
    median = statistics.median(premiums)
    p75 = _percentile(premiums, 0.75)
    return {
        "war_count": len(able),
        "extreme_count": sum(1 for sample in able if sample.get("extreme") is True),
        "median_premium": median,
        "p75_premium": p75,
        "round_style": round_style,
        "nudge_eur": nudge,
        "league_bid_eur": _bid_amount(sale, median, round_style=round_style, nudge=nudge),
        "stretch_bid_eur": _bid_amount(sale, p75, round_style=round_style, nudge=nudge),
    }


def apply_league_clearing(
    econ: dict[str, Any],
    quote: dict[str, Any] | None,
    *,
    to_lead: int | None,
    cash: int | None,
) -> dict[str, Any]:
    """Sube la apertura hasta la puja de liga y baja el snipe si el tope era más alto."""
    result = dict(econ)
    if not isinstance(quote, dict):
        return result
    league_bid = quote.get("league_bid_eur")
    stretch = quote.get("stretch_bid_eur")
    if isinstance(league_bid, bool) or not isinstance(league_bid, int):
        return result
    result["league_bid"] = league_bid
    result["stretch_bid"] = stretch if isinstance(stretch, int) and not isinstance(stretch, bool) else None
    result["league_war_count"] = quote.get("war_count") if isinstance(quote.get("war_count"), int) else None
    result["league_extreme_wars"] = (
        quote.get("extreme_count") if isinstance(quote.get("extreme_count"), int) else None
    )
    ceiling = result.get("value_ceiling") if isinstance(result.get("value_ceiling"), int) else None
    cap = ceiling
    if isinstance(cash, int) and not isinstance(cash, bool):
        cap = cash if cap is None else min(cap, cash)
    limit = result.get("bid_limit")
    if cap is not None and league_bid > cap:
        result["league_bid_blocked"] = True
    if limit in {"no", "sin_caja", "sobre_techo", "fuentes_no_coinciden", "sin_puja"}:
        return result
    suggested = result.get("suggested_bid")
    if isinstance(suggested, bool) or not isinstance(suggested, int):
        return result
    floor = to_lead if isinstance(to_lead, int) and not isinstance(to_lead, bool) else suggested
    if limit == "snipe_techo":
        target = max(floor, league_bid)
    else:
        target = max(suggested, league_bid)
    if cap is not None and target > cap:
        result["league_bid_blocked"] = True
        return result
    result["suggested_bid"] = target
    result["league_bid_blocked"] = False
    if isinstance(stretch, int) and not isinstance(stretch, bool) and stretch > target and (cap is None or stretch <= cap):
        result["raise_to"] = stretch
    if limit == "snipe_techo" and (ceiling is None or target < ceiling):
        result["bid_limit"] = "snipe_liga"
    return result


def _bid_amount(sale: int, premium: float, *, round_style: bool, nudge: int) -> int:
    premium = max(0.0, float(premium))
    target = math.ceil(sale * (1.0 + premium) - 1e-9)
    if target <= sale:
        target = sale + 1
    if not round_style:
        return target
    snapped = ((target + ROUND_STEP - 1) // ROUND_STEP) * ROUND_STEP
    return snapped + max(0, nudge) + 1


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


@dataclass
class RivalProfile:
    team_id: str
    manager_name: str
    alpha_aggressiveness: float
    sigma_dispersion: float
    cash_eur: float
    cash_uncertainty_eur: float
    thin_positions: list[str]
    xi_gaps: list[str]
    lacks_replacements: bool
    already_bidding: bool = False


def collect_activity_buys(
    events: list[dict[str, Any]],
    snapshots: dict[tuple[str, str], int],
    ledgers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compras (activity_type_id == 31) con valor de referencia del mismo día Madrid."""
    cash_by_team: dict[str, int] = {}
    for ledger in ledgers or []:
        if not isinstance(ledger, dict):
            continue
        team_id = ledger.get("team_id")
        cash = ledger.get("observed_cash_eur")
        if not isinstance(cash, int) or isinstance(cash, bool):
            cash = ledger.get("reconstructed_cash_eur")
        if isinstance(team_id, str) and isinstance(cash, int) and not isinstance(cash, bool):
            cash_by_team[team_id] = cash

    buys: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("activity_type_id") != 31:
            continue
        player_id = event.get("player_id")
        day = madrid_day(event.get("at") if isinstance(event.get("at"), str) else None)
        amount = event.get("amount_eur")
        team_id = event.get("team_id")
        if not isinstance(player_id, str) or not isinstance(day, str):
            continue
        if isinstance(amount, bool) or not isinstance(amount, int) or not isinstance(team_id, str):
            continue
        ref = snapshots.get((player_id, day))
        if not isinstance(ref, int) or ref <= 0:
            continue
        cash_at = cash_by_team.get(team_id)
        buys.append(
            {
                "team_id": team_id,
                "player_id": player_id,
                "amount_eur": amount,
                "reference_value_eur": ref,
                "market_value": ref,
                "cash_at_event_eur": cash_at if isinstance(cash_at, int) else None,
                "positional_urgency": 0.0,
                "at": event.get("at"),
            }
        )
    return buys


def fit_rival_profiles_eb(
    activity_buys: list[dict[str, Any]],
    rivals_state: list[dict[str, Any]],
    *,
    beta_liquidity: float = 0.18,
    beta_urgency: float = 0.25,
    eb_shrinkage_k: float = 3.0,
    cash_uncertainty_floor_eur: float | None = None,
) -> dict[str, RivalProfile]:
    """Perfil Bayesiano (James-Stein) de agresividad rival desde compras históricas.

    ``cash_uncertainty_floor_eur`` es el suelo de ``σ_cash``: el mismo parámetro
    (``CASH_UNCERTAINTY_FLOOR_EUR``) que usa el termómetro de ``rival_intel``.
    Sin él, la barrera de la puja y la lectura contable no hablarían del mismo
    grado de incertidumbre.
    """
    from toolbox.rival_intel import configured_uncertainty_floor_eur

    floor = (
        float(cash_uncertainty_floor_eur)
        if cash_uncertainty_floor_eur is not None
        else float(configured_uncertainty_floor_eur())
    )
    floor = max(0.0, floor)
    residuals_by_team: dict[str, list[float]] = {}
    all_residuals: list[float] = []

    for ev in activity_buys:
        team_id = str(ev.get("team_id", ""))
        amount = float(ev.get("amount_eur") or 0.0)
        ref_val = float(ev.get("reference_value_eur") or ev.get("market_value") or 0.0)
        if amount <= 0 or ref_val <= 0 or not team_id:
            continue
        premium = (amount - ref_val) / ref_val
        if premium <= 0.005 or premium > 1.20:
            continue

        cash_at_buy = float(ev.get("cash_at_event_eur") or ref_val * 1.5)
        urgency = float(ev.get("positional_urgency") or 0.0)
        liq_ratio = math.log(1.0 + max(0.0, cash_at_buy / ref_val))

        y_obs = math.log(premium)
        res = y_obs - beta_liquidity * liq_ratio - beta_urgency * urgency
        residuals_by_team.setdefault(team_id, []).append(res)
        all_residuals.append(res)

    mu_0 = float(np.mean(all_residuals)) if len(all_residuals) >= 5 else -2.465
    sigma_0 = float(np.std(all_residuals)) if len(all_residuals) >= 5 else 0.55
    sigma_0 = float(np.clip(sigma_0, 0.30, 0.95))

    profiles: dict[str, RivalProfile] = {}
    for rival in rivals_state:
        if not isinstance(rival, dict):
            continue
        t_id = str(rival.get("team_id", ""))
        if not t_id:
            continue
        samples = residuals_by_team.get(t_id, [])
        n_j = len(samples)
        if n_j > 0:
            r_bar = float(np.mean(samples))
            s_sq = float(np.var(samples)) if n_j > 1 else sigma_0**2
            alpha_j = (n_j / (n_j + eb_shrinkage_k)) * r_bar + (eb_shrinkage_k / (n_j + eb_shrinkage_k)) * mu_0
            sigma_j = math.sqrt(
                (n_j / (n_j + eb_shrinkage_k)) * s_sq + (eb_shrinkage_k / (n_j + eb_shrinkage_k)) * (sigma_0**2)
            )
        else:
            alpha_j, sigma_j = mu_0, sigma_0

        cash_val = float(
            rival.get("reconstructed_cash_eur")
            or rival.get("cash_eur")
            or (rival.get("ledger") or {}).get("reconstructed_cash_eur")
            or 0.0
        )
        gap_val = abs(float(rival.get("gap_eur") or 0.0))
        balanced = rival.get("balanced", True)
        # El ''balanced'' es del libro, no de la cota: un desbalance deja la
        # incertidumbre en un múltiplo del suelo, no en un número fijo.
        uncertainty = max(floor, gap_val)
        if not balanced:
            uncertainty = max(3.0 * floor, gap_val)

        profiles[t_id] = RivalProfile(
            team_id=t_id,
            manager_name=str(rival.get("manager_name") or t_id),
            alpha_aggressiveness=alpha_j,
            sigma_dispersion=float(np.clip(sigma_j, 0.25, 0.90)),
            cash_eur=max(0.0, cash_val),
            cash_uncertainty_eur=uncertainty,
            thin_positions=[str(item) for item in (rival.get("thin_positions") or []) if isinstance(item, str)],
            xi_gaps=[str(item) for item in (rival.get("xi_gaps") or []) if isinstance(item, str)],
            lacks_replacements=bool(rival.get("lacks_replacements", False)),
            already_bidding=bool(rival.get("already_bidding", False)),
        )
    return profiles

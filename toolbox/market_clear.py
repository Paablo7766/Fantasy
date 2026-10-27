"""MAE de la puja ganadora estimada contra el precio de corte real.

Piezas puras: nada de disco ni de red. Las usan ``scripts/audit_market_clear.py``
y las pruebas.

Definiciones:

  * ``predicted_win`` — puja que el motor daba para llevarse al jugador.
  * ``clearing_quote`` — puja que de verdad hizo falta para llevárselo.

El MAE es la media de ``|predicted_win - clearing_quote|`` en €. Se calcula solo
sobre cierres de rivales: comparar lo que tú pujaste con lo que tú pagaste mide
tu propia puja, no la capacidad del motor para estimar el mercado.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from toolbox.rival_intel import (
    CASH_ARBITRAGE_BAND,
    CASH_THERMOMETER_TAU,
    CASH_UNCERTAINTY_FLOOR_EUR,
    cash_control_thermometer,
)

_MADRID = ZoneInfo("Europe/Madrid")


def as_int(value: Any) -> int | None:
    """Entero limpio: rechaza ``bool`` y decimales que no son enteros."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def mae(pairs: Iterable[tuple[float, float]]) -> float | None:
    """Media de los errores absolutos de ``(predicción, real)``. ``None`` sin pares."""
    errors = [abs(float(predicted) - float(actual)) for predicted, actual in pairs]
    return sum(errors) / len(errors) if errors else None


def median(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def price_limit_error(pairs: Iterable[tuple[float, float]]) -> dict[str, Any]:
    """Resumen del error de predicción de cierres.

    ``signed_bias`` es ``predicted - real`` de media: positiva cuando el motor
    pujaba por encima del cierre (gastaba de más para ganar), negativa cuando
    se quedaba corto (perdía subastas que podía haber ganado).
    """
    values = [(float(predicted), float(actual)) for predicted, actual in pairs]
    if not values:
        return {
            "pairs": 0,
            "mae_eur": None,
            "mae_pct": None,
            "median_abs_error_eur": None,
            "max_abs_error_eur": None,
            "signed_bias_eur": None,
            "overbid_pairs": 0,
            "underbid_pairs": 0,
        }
    absolute = [abs(predicted - actual) for predicted, actual in values]
    signed = [predicted - actual for predicted, actual in values]
    # El MAE en % solo tiene sentido sobre cierres no nulos; un cierre de 0 € no existe.
    pct_errors = [error / actual * 100 for (predicted, actual), error in zip(values, absolute) if actual > 0]
    return {
        "pairs": len(values),
        "mae_eur": round(sum(absolute) / len(absolute), 2),
        "mae_pct": round(sum(pct_errors) / len(pct_errors), 2) if pct_errors else None,
        "median_abs_error_eur": round(float(median(absolute) or 0), 2),
        "max_abs_error_eur": round(max(absolute), 2),
        "signed_bias_eur": round(sum(signed) / len(signed), 2),
        "overbid_pairs": sum(1 for value in signed if value > 0),
        "underbid_pairs": sum(1 for value in signed if value < 0),
    }


def sample_row(
    prediction: Mapping[str, Any],
    quote: Mapping[str, Any] | None,
    *,
    reference: int | None = None,
) -> dict[str, Any]:
    """Fila de muestreo de un jugador: predicción, cierre y error.

    ``quote`` es el cierre del rival (``side == "rival"``). Si el cierre es tuyo
    no hay error: se marca ``side: propia`` para excluirlo del MAE aunque el
    jugador sí estuviera en el tablero.
    """
    predicted = as_int(prediction.get("predicted_win_eur"))
    row: dict[str, Any] = {
        "player_id": prediction.get("player_id"),
        "name": prediction.get("name"),
        "position": prediction.get("position"),
        "decision": prediction.get("decision"),
        "predicted_win_eur": predicted,
        "prediction_source": prediction.get("source") or "motor",
        "reference_bid_eur": as_int(prediction.get("reference_bid_eur")),
        "win_probability": prediction.get("win_probability"),
        "clearing_quote_eur": None,
        "clearing_source": None,
        "clearing_side": None,
        "winner_team_id": None,
        "winner_manager": None,
        "abs_error_eur": None,
        "error_pct": None,
        "bid_premium_pct": None,
        "missed": False,
        "counts_in_mae": False,
    }
    if not quote:
        return row
    actual = as_int(quote.get("quote_eur"))
    side = quote.get("side")
    row.update(
        {
            "clearing_quote_eur": actual,
            "clearing_source": quote.get("quote_source"),
            "clearing_side": side,
            "winner_team_id": quote.get("team_id"),
            "winner_manager": quote.get("manager_name"),
        }
    )
    if actual is None or actual <= 0 or side != "rival" or predicted is None:
        return row
    error = abs(predicted - actual)
    row.update(
        {
            "abs_error_eur": error,
            "error_pct": round(error / actual * 100, 2),
            "missed": predicted < actual,
            "counts_in_mae": True,
        }
    )
    if reference:
        row["bid_premium_pct"] = round((predicted / reference - 1) * 100, 2)
    return row


# --------------------------------------------------------------------------- #
# Cota de riesgo por rival: risk_adjusted_bid_limit
# --------------------------------------------------------------------------- #


def get_path(obj: Any, *path: str) -> Any:
    """Lee una ruta anidada sin reventar si un tramo no es un diccionario."""
    current = obj
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def own_team_id(board: Mapping[str, Any] | None) -> str | None:
    for squad in get_path(board, "squads", "squads") or []:
        if isinstance(squad, dict) and squad.get("is_self") is True:
            team_id = squad.get("team_id")
            if isinstance(team_id, str):
                return team_id
    team_id = get_path(board, "flip", "team_id")
    return team_id if isinstance(team_id, str) else None


def manager_index(board: Mapping[str, Any] | None) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for squad in get_path(board, "squads", "squads") or []:
        if isinstance(squad, dict) and isinstance(squad.get("team_id"), str):
            out[squad["team_id"]] = squad.get("manager_name")
    return out


def risk_limits_from_intel(board: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """La cota tal cual la firma la auditoría de caja, si la foto la trae."""
    out: dict[str, dict[str, Any]] = {}
    for team in get_path(board, "rival_intel", "teams") or []:
        if not isinstance(team, dict):
            continue
        team_id = team.get("team_id")
        limit = as_int(team.get("risk_adjusted_bid_limit"))
        if isinstance(team_id, str) and limit is not None:
            out[team_id] = {
                "risk_adjusted_bid_limit": max(0, limit),
                "risk_adjusted_cash": as_int(team.get("risk_adjusted_cash")),
                "calculated_cash": as_int(team.get("calculated_cash")),
                "debt_limit_eur": as_int(team.get("debt_limit_eur")) or 0,
                "confidence": team.get("confidence"),
                "source": "rival_intel",
            }
    return out


def cash_rows(board: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Filas de caja al estilo de ``history.cash`` (sale de los libros de la foto).

    Los libros mandan sobre ``needs.history.cash``: ese resumen guarda la caja
    con un ``cash_is_ceiling`` cacheado que no lleva la lectura de riesgo. Si se
    usara tal cual, un rival con la caja apretada recuperaría su cota holgada.
    ``history`` solo rellena equipos que no tienen libro en la foto.
    """
    rows: dict[str, dict[str, Any]] = {}
    from_history: dict[str, dict[str, Any]] = {}
    for row in get_path(board, "needs", "history", "cash") or []:
        if isinstance(row, dict) and isinstance(row.get("team_id"), str):
            from_history[row["team_id"]] = dict(row)
    for ledger in get_path(board, "needs", "ledgers") or []:
        if not isinstance(ledger, dict) or not isinstance(ledger.get("team_id"), str):
            continue
        team_id = ledger["team_id"]
        observed = as_int(ledger.get("observed_cash_eur"))
        reconstructed = as_int(ledger.get("reconstructed_cash_eur"))
        cash = observed if observed is not None else reconstructed
        if cash is None:
            continue
        merged = dict(from_history.get(team_id) or {})
        merged.update(
            {
                "team_id": team_id,
                "cash_eur": cash,
                "cash_is_ceiling": ledger.get("cash_is_ceiling") is True,
                "observed_cash_eur": observed,
                "reconstructed_cash_eur": reconstructed,
                # ``history.cash`` cachea un «suelo» que ya es la cota de una
                # auditoría previa. Solo vale el que sale de los libros ahora.
                "cash_floor_eur": as_int(ledger.get("cash_floor_eur")),
            }
        )
        rows[team_id] = merged
    for team_id, row in from_history.items():
        rows.setdefault(team_id, row)
    return list(rows.values())


def risk_limits_from_ledgers(board: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Reconstruye ``risk_adjusted_bid_limit`` con la aritmética de ``LedgerAuditor``.

    ``risk_adjusted_cash`` = termómetro(caja calculada, caja observada), nunca
    por debajo del suelo probado; ``risk_adjusted_bid_limit`` = eso + el
    endeudamiento permitido. Sin ``rival_intel`` en la foto no hay endeudamiento
    publicado y se declara a 0, que solo puede infravalorar la cota.

    Un ``cash_is_ceiling`` guardado **no** es la cota ajustada por riesgo: es
    la caja reconstruida de antes de apretarla con el saldo observado. Si se
    reutiliza tal cual, un rival con la caja apretada recupera su cota holgada
    y la alerta nunca salta. Aquí se recalcula siempre.
    """
    limits = risk_limits_from_intel(board)
    out: dict[str, dict[str, Any]] = dict(limits)
    for row in cash_rows(board):
        team_id = str(row["team_id"])
        if team_id in limits:
            continue
        cash = as_int(row.get("cash_eur"))
        if cash is None:
            continue
        # El suelo probado («el historial demuestra esta caja») entra **solo** en
        # el termómetro, como en ``LedgerAuditor``. No se aplica como ``max()``
        # aparte: en un rival sin saldo observado coincidiría con la cota y la
        # elevaría a la cifra de antes de apretarla, dejando la alerta muerta.
        floor = as_int(row.get("cash_floor_eur")) or as_int(row.get("reconstructed_cash_eur"))
        observed = as_int(row.get("observed_cash_eur"))
        adjusted = cash
        arbitrage = 0
        if observed is not None:
            thermometer = cash_control_thermometer(
                cash,
                observed,
                tau=CASH_THERMOMETER_TAU,
                band=CASH_ARBITRAGE_BAND,
                floor_eur=floor if floor is not None else CASH_UNCERTAINTY_FLOOR_EUR,
                accrual_eur=0,
            )
            adjusted = as_int(thermometer.get("tight_ceiling_eur")) or cash
            arbitrage = as_int(thermometer.get("arbitrage_eur")) or 0
        debt = as_int(row.get("debt_limit_eur")) or 0
        out[team_id] = {
            "risk_adjusted_bid_limit": max(0, adjusted + debt),
            "risk_adjusted_cash": adjusted,
            "calculated_cash": cash,
            "cash_floor_eur": floor,
            "observed_cash_eur": observed,
            "arbitrage_eur": arbitrage,
            "debt_limit_eur": debt,
            "confidence": None,
            "source": "ledger",
        }
    return out


# --------------------------------------------------------------------------- #
# Gasto real del día y alertas
# --------------------------------------------------------------------------- #


def madrid_day(value: Any) -> str | None:
    """Fecha civil Europe/Madrid de una marca ISO del historial."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return text[:10] if len(text) >= 10 else None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_MADRID)
    return moment.astimezone(_MADRID).date().isoformat()


def daily_rival_spend(
    buys: Iterable[Mapping[str, Any]],
    *,
    day: str,
    own: str | None,
) -> dict[str, dict[str, Any]]:
    """Gasto real del día por rival. Solo compras: las cláusulas no son cierres."""
    spent: dict[str, dict[str, Any]] = {}
    for buy in buys:
        team_id = buy.get("team_id")
        amount = as_int(buy.get("amount_eur"))
        if not isinstance(team_id, str) or team_id == own or amount is None or amount <= 0:
            continue
        if madrid_day(buy.get("at")) != day:
            continue
        row = spent.setdefault(team_id, {"team_id": team_id, "spend_eur": 0, "purchases": []})
        row["spend_eur"] += amount
        row["purchases"].append(
            {
                "player_id": buy.get("player_id"),
                "amount_eur": amount,
                "at": buy.get("at"),
            }
        )
    return spent


def ceiling_alert(
    team_id: str,
    spend_eur: int,
    limit: int,
    *,
    manager_name: str | None = None,
    limit_source: str = "desconocida",
    limit_confidence: str | None = None,
) -> dict[str, Any] | None:
    """Alerta cuando el gasto real supera la cota de riesgo del rival."""
    if spend_eur <= limit:
        return None
    return {
        "team_id": team_id,
        "manager_name": manager_name,
        "spend_eur": spend_eur,
        "risk_adjusted_bid_limit_eur": limit,
        "excess_over_ceiling_eur": spend_eur - limit,
        "ceiling_breach_pct": round((spend_eur / limit - 1) * 100, 2) if limit > 0 else None,
        "limit_source": limit_source,
        "limit_confidence": limit_confidence,
    }


def rival_alerts(
    buys: Iterable[Mapping[str, Any]],
    limits: Mapping[str, Mapping[str, Any]],
    *,
    day: str,
    own: str | None,
    managers: Mapping[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Alertas ordenadas por exceso. Los gastos sin cota se listan aparte."""
    managers = managers or {}
    spend = daily_rival_spend(buys, day=day, own=own)
    alerts: list[dict[str, Any]] = []
    for team_id, row in sorted(spend.items(), key=lambda item: -item[1]["spend_eur"]):
        limit_row = limits.get(team_id) or {}
        limit = as_int(limit_row.get("risk_adjusted_bid_limit"))
        if limit is None:
            alerts.append(
                {
                    "team_id": team_id,
                    "manager_name": managers.get(team_id),
                    "spend_eur": row["spend_eur"],
                    "risk_adjusted_bid_limit_eur": None,
                    "excess_over_ceiling_eur": None,
                    "ceiling_breach_pct": None,
                    "limit_source": "sin_cota",
                    "limit_confidence": None,
                    "purchases": row["purchases"],
                }
            )
            continue
        purchases = spend.get(team_id) or {"spend_eur": 0, "purchases": []}
        alert = ceiling_alert(
            team_id,
            purchases["spend_eur"],
            limit,
            manager_name=managers.get(team_id),
            limit_source=str(limit_row.get("source") or "desconocida"),
            limit_confidence=limit_row.get("confidence"),
        )
        if alert is None:
            continue
        alert["purchases"] = purchases["purchases"]
        alerts.append(alert)
    alerts.sort(key=lambda row: -(row.get("excess_over_ceiling_eur") or 0))
    return alerts


# --------------------------------------------------------------------------- #
# Precio de corte real (clearing_quote) por jugador
# --------------------------------------------------------------------------- #


def clearing_quotes(
    buys: Iterable[Mapping[str, Any]],
    *,
    own: str | None,
) -> dict[str, dict[str, Any]]:
    """Cierre por jugador desde el historial: gana la puja más alta registrada.

    Las compras se ordenan por importe y no por orden de llegada: un mismo
    jugador aparece varias veces en el historial de actividad cuando hay pujas
    intermedias, y la que fija el corte es la más alta.
    """
    quotes: dict[str, dict[str, Any]] = {}
    for buy in buys:
        player_id = buy.get("player_id")
        amount = as_int(buy.get("amount_eur"))
        if not isinstance(player_id, str) or amount is None or amount <= 0:
            continue
        current = quotes.get(player_id)
        if current is not None and amount <= current["quote_eur"]:
            continue
        quotes[player_id] = {
            "player_id": player_id,
            "quote_eur": amount,
            "quote_source": "activity_buys",
            "team_id": buy.get("team_id"),
            "at": buy.get("at"),
            "side": "propia" if buy.get("team_id") == own else "rival",
        }
    return quotes


def board_quotes(
    board: Mapping[str, Any] | None,
    *,
    own: str | None,
) -> dict[str, dict[str, Any]]:
    """Cierres visibles en el tablero: la mayor puja ajena de cada listing."""
    quotes: dict[str, dict[str, Any]] = {}
    for listing in get_path(board, "market", "listings") or []:
        if not isinstance(listing, dict):
            continue
        player_id = listing.get("player_id")
        if not isinstance(player_id, str):
            continue
        bids = [
            bid
            for bid in listing.get("bids") or []
            if isinstance(bid, dict)
            and as_int(bid.get("amount")) is not None
            and bid.get("team_id") != own
        ]
        best = max(bids, key=lambda bid: as_int(bid.get("amount")) or 0, default=None)
        if best is None:
            continue
        quotes[player_id] = {
            "player_id": player_id,
            "quote_eur": as_int(best.get("amount")),
            "quote_source": "tablero",
            "team_id": best.get("team_id"),
            "at": None,
            "side": "rival",
        }
    return quotes


def merged_quotes(
    buys: Iterable[Mapping[str, Any]],
    board: Mapping[str, Any] | None,
    *,
    own: str | None,
) -> dict[str, dict[str, Any]]:
    """El historial manda; el tablero rellena los jugadores sin compra registrada.

    El tablero enseña las pujas de un listing todavía abierto, que valen como
    cierre estimado («lo que haría falta para ganarlo») cuando nadie ha comprado
    aún. Cuando hay compra, el importe pagado es el cierre de verdad.
    """
    quotes = board_quotes(board, own=own)
    quotes.update(clearing_quotes(buys, own=own))
    return quotes


# --------------------------------------------------------------------------- #
# Puja ganadora estimada (predicted_win)
# --------------------------------------------------------------------------- #


def motor_predictions(
    board: Mapping[str, Any],
    *,
    moment: datetime,
    decisions: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Veredictos de la foto con la puja que el motor daba para ganar.

    ``predicted_win`` = ``suggested_bid`` (lo que se habría pujado). Si el
    veredicto era «no pujar» no hay predicción, pero el motor sí tenía una
    estimación de la puja ganadora (``optimal_bid_eur`` o ``league_bid``): solo
    se publica cuando es un jugador que se intentó comprar (``PUJAR`` o
    ``ESPERAR``). Una abstención por lesión o por estar en plantilla no tiene
    nada que comparar con el cierre, y su ``reference_bid_eur`` tampoco.
    """
    if decisions is None:
        from toolbox.market_intel import decisions_from_board

        document = decisions_from_board(dict(board), now=moment)
        rows = document.get("decisions") or []
    else:
        rows = decisions
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        player_id = row.get("player_id")
        if not isinstance(player_id, str):
            continue
        suggested = as_int(row.get("suggested_bid"))
        decision = row.get("decision")
        attempted = decision in {"PUJAR", "ESPERAR"}
        reference = (as_int(row.get("optimal_bid_eur")) or as_int(row.get("league_bid"))) if attempted else None
        if suggested is None and reference is None:
            continue
        probability = row.get("win_probability")
        out[player_id] = {
            "player_id": player_id,
            "name": row.get("nickname") or row.get("name"),
            "position": row.get("position"),
            "decision": decision,
            "suggested_bid_eur": suggested,
            "predicted_win_eur": suggested,
            "reference_bid_eur": reference,
            "win_probability": float(probability)
            if isinstance(probability, (int, float)) and not isinstance(probability, bool)
            else None,
            "auction_decision": row.get("auction_decision"),
            "source": "motor",
        }
    return out


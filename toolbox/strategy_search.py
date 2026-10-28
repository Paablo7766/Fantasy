"""Planes de fichaje que suben los puntos del once.

Un ILP elige, juntos, el once y como mucho cuatro fichajes (puja o cláusula),
más las ventas que hacen falta para pagarlos. No envía órdenes. Cada fichaje
dice a quién saca del once y cuántos puntos aporta ese cambio. Si el mejor
plan no es el único que suma, guarda alternativas aunque puntúen menos.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pulp

from toolbox.analyzer import (
    FORMATIONS,
    POSITIONS,
    XI_SIZE,
    Candidate,
    ObjectiveWeights,
    candidate_from_player,
    index_trends,
    lineup_points,
    own_squad,
)
from toolbox.normalize import SCHEMA_VERSION, parse_clause_lock

MAX_PLANS = 3
MAX_SIGNINGS = 4
# Por debajo de esto el once no cambia de verdad: no es un plan.
MIN_GAIN = 0.2
_SOLVER_TIME = 8
_CACHE_KEEP = 8
_PHOTO_CACHE: dict[str, dict[str, Any]] = {}
_SOLVE_SEQ = 0


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _euros(value: Any) -> int | None:
    number = _int(value)
    if number is None or number < 0:
        return None
    return number


@dataclass(frozen=True)
class OwnedAsset:
    candidate: Candidate
    sell_eur: int | None


@dataclass(frozen=True)
class TargetAsset:
    candidate: Candidate
    cost_eur: int
    kind: str
    manager_name: str | None = None
    team_id: str | None = None
    market_eur: int | None = None


@dataclass
class _TransferCut:
    bought: frozenset[str]
    sold: frozenset[str]


def _unlocked(player: dict[str, Any]) -> bool:
    """Candado vencido cuenta como abierto aunque la foto lo marcara cerrado."""
    if player.get("is_shielded") is True:
        return False
    lock = player.get("clause_lock") if isinstance(player.get("clause_lock"), dict) else {}
    expires = lock.get("expires_at")
    if isinstance(expires, str) and expires.strip():
        parsed = parse_clause_lock(expires)
        if parsed.get("is_locked") is True:
            return False
        if parsed.get("is_locked") is False:
            return True
    return lock.get("is_locked") is False


def _player_row(candidate: Candidate) -> dict[str, Any]:
    return {
        "player_id": candidate.player_id,
        "name": candidate.name,
        "nickname": candidate.nickname,
        "position": candidate.position,
        "club": candidate.club,
        "image_url": candidate.image_url,
        "jornada_ev": candidate.jornada_ev,
        "expected_points": candidate.expected_points,
    }


def _offer_source(listing: dict[str, Any], own_team_id: str | None) -> str:
    seller = listing.get("seller_team_id")
    seller_id = seller.strip() if isinstance(seller, str) and seller.strip() else None
    if seller_id is None:
        return "liga"
    if isinstance(own_team_id, str) and seller_id == own_team_id:
        return "propio"
    return "rival"


def _listing_price(listing: dict[str, Any]) -> int | None:
    for key in ("sale_price", "leading_bid"):
        price = _euros(listing.get(key))
        if price is not None:
            return price
    return None


def _listing_as_player(listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": listing.get("player_id"),
        "name": listing.get("name"),
        "nickname": listing.get("nickname"),
        "position": listing.get("position"),
        "club": listing.get("club"),
        "image_url": listing.get("image_url"),
        "market_value": listing.get("market_value"),
        "p_titular": listing.get("p_titular"),
        "player_status": listing.get("player_status"),
        "average_points": listing.get("average_points"),
        "form": listing.get("form"),
        "relevo_bonus": listing.get("relevo_bonus"),
    }


def collect_universe(
    market: dict[str, Any] | None,
    squads: dict[str, Any] | None,
    trends: dict[str, Any] | None,
    *,
    weights: ObjectiveWeights | None = None,
) -> tuple[int | None, list[OwnedAsset], list[TargetAsset]]:
    scale = weights or ObjectiveWeights()
    own = own_squad(squads) if isinstance(squads, dict) else None
    if not isinstance(own, dict):
        return None, [], []
    cash = _int(own.get("cash"))
    indexed = index_trends(trends)
    own_team = own.get("team_id") if isinstance(own.get("team_id"), str) else None
    owned: list[OwnedAsset] = []
    owned_ids: set[str] = set()
    for ordinal, player in enumerate(own.get("players") or []):
        if not isinstance(player, dict):
            continue
        player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else None
        candidate = candidate_from_player(
            player,
            indexed.get(player_id or ""),
            weights=scale,
            ordinal=ordinal,
        )
        if candidate is None:
            continue
        if player_id:
            owned_ids.add(player_id)
        owned.append(OwnedAsset(candidate=candidate, sell_eur=_euros(player.get("market_value"))))

    targets: list[TargetAsset] = []
    taken: set[str] = set()
    for listing in (market or {}).get("listings") or []:
        if not isinstance(listing, dict):
            continue
        if _offer_source(listing, own_team) == "propio":
            continue
        player_id = listing.get("player_id") if isinstance(listing.get("player_id"), str) else None
        if player_id is None or player_id in owned_ids or player_id in taken:
            continue
        price = _listing_price(listing)
        if price is None:
            continue
        candidate = candidate_from_player(
            _listing_as_player(listing),
            indexed.get(player_id),
            weights=scale,
            ordinal=8000 + len(targets),
        )
        if candidate is None or not candidate.eligible:
            continue
        taken.add(player_id)
        manager = listing.get("seller_manager") if isinstance(listing.get("seller_manager"), str) else None
        targets.append(
            TargetAsset(
                candidate=candidate,
                cost_eur=price,
                kind="pujar",
                manager_name=manager,
                team_id=listing.get("seller_team_id") if isinstance(listing.get("seller_team_id"), str) else None,
                market_eur=_euros(listing.get("market_value")),
            )
        )

    for squad in (squads or {}).get("squads") or []:
        if not isinstance(squad, dict) or squad.get("is_self") is True or squad.get("error"):
            continue
        manager = squad.get("manager_name") if isinstance(squad.get("manager_name"), str) else None
        team_id = squad.get("team_id") if isinstance(squad.get("team_id"), str) else None
        for player in squad.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = player.get("player_id") if isinstance(player.get("player_id"), str) else None
            if player_id is None or player_id in owned_ids or player_id in taken:
                continue
            if not _unlocked(player):
                continue
            clause = _euros(player.get("buyout_clause"))
            if clause is None:
                continue
            candidate = candidate_from_player(
                player,
                indexed.get(player_id),
                weights=scale,
                ordinal=9000 + len(targets),
            )
            if candidate is None or not candidate.eligible:
                continue
            taken.add(player_id)
            targets.append(
                TargetAsset(
                    candidate=candidate,
                    cost_eur=clause,
                    kind="clausular",
                    manager_name=manager,
                    team_id=team_id,
                    market_eur=_euros(player.get("market_value")),
                )
            )
    return cash, owned, targets


def _photo_key(
    cash: int,
    owned: list[OwnedAsset],
    targets: list[TargetAsset],
    baseline: float | None,
) -> str:
    payload = {
        "cash": cash,
        "baseline": baseline,
        "owned": [
            (
                asset.candidate.player_id,
                asset.candidate.position,
                asset.candidate.jornada_ev,
                asset.candidate.excluded_reason,
                asset.sell_eur,
            )
            for asset in owned
        ],
        "targets": [
            (
                asset.candidate.player_id,
                asset.kind,
                asset.cost_eur,
                asset.candidate.jornada_ev,
                asset.candidate.position,
            )
            for asset in targets
        ],
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _remember(key: str, document: dict[str, Any]) -> dict[str, Any]:
    _PHOTO_CACHE.pop(key, None)
    _PHOTO_CACHE[key] = document
    while len(_PHOTO_CACHE) > _CACHE_KEEP:
        _PHOTO_CACHE.pop(next(iter(_PHOTO_CACHE)))
    return document


def _baseline_points(
    owned: list[OwnedAsset],
    optimize: dict[str, Any] | None,
) -> float | None:
    if isinstance(optimize, dict) and optimize.get("matchday_void") is not True:
        total, missing = lineup_points(optimize.get("xi") if isinstance(optimize.get("xi"), list) else None)
        if total is not None and not missing:
            return total
    solved = _solve_once(
        cash=0,
        owned=owned,
        targets=[],
        allow_sales=False,
        cuts=(),
        keep_if_not_better=True,
    )
    if solved is None:
        return None
    return solved["expected_points"]


def _sales_for_plan(
    cash: int,
    spend: int,
    sellable: dict[str, OwnedAsset],
    xi_ids: set[str],
    baseline_ids: frozenset[str] | None,
) -> list[OwnedAsset]:
    """Vende a quien sale del once. Del banquillo, solo lo que falte para pagar."""
    displaced: list[OwnedAsset] = []
    bench: list[OwnedAsset] = []
    for asset in sellable.values():
        player_id = asset.candidate.player_id
        if not player_id or player_id in xi_ids:
            continue
        if baseline_ids is not None and player_id in baseline_ids:
            displaced.append(asset)
        else:
            bench.append(asset)
    chosen = list(displaced)
    income = sum(asset.sell_eur or 0 for asset in chosen)
    if cash + income < spend:
        for asset in sorted(bench, key=lambda item: -(item.sell_eur or 0)):
            chosen.append(asset)
            income += asset.sell_eur or 0
            if cash + income >= spend:
                break
    return chosen


def search_plans(
    *,
    cash: int,
    owned: list[OwnedAsset],
    targets: list[TargetAsset],
    baseline_points: float | None = None,
    allow_sales: bool = True,
    cuts: tuple[_TransferCut, ...] = (),
) -> dict[str, Any] | None:
    return _solve_once(
        cash=cash,
        owned=owned,
        targets=targets,
        allow_sales=allow_sales,
        cuts=cuts,
        baseline_points=baseline_points,
    )


def _solve_once(
    *,
    cash: int,
    owned: list[OwnedAsset],
    targets: list[TargetAsset],
    allow_sales: bool,
    cuts: tuple[_TransferCut, ...],
    baseline_points: float | None = None,
    baseline_ids: frozenset[str] | None = None,
    keep_if_not_better: bool = False,
) -> dict[str, Any] | None:
    starters: list[Candidate] = []
    sellable: dict[str, OwnedAsset] = {}
    for asset in owned:
        candidate = asset.candidate
        if candidate.eligible:
            starters.append(candidate)
        if allow_sales and asset.sell_eur is not None and candidate.player_id:
            sellable[candidate.key] = asset
    buyable: dict[str, TargetAsset] = {}
    for asset in targets:
        candidate = asset.candidate
        if not candidate.eligible:
            continue
        starters.append(candidate)
        buyable[candidate.key] = asset
    available = sum(1 for asset in owned if asset.candidate.eligible) + len(buyable)
    if available < XI_SIZE:
        return None

    global _SOLVE_SEQ
    _SOLVE_SEQ += 1
    tag = _SOLVE_SEQ
    # PuLP guarda las variables por nombre en el proceso. Reusar x_0 en el
    # siguiente plan ata el modelo nuevo al anterior y el solver no devuelve nada.
    problem = pulp.LpProblem(f"strategy_xi_{tag}", pulp.LpMaximize)
    chosen = {candidate.key: pulp.LpVariable(f"x{tag}_{index}", cat=pulp.LpBinary) for index, candidate in enumerate(starters)}
    formation_vars = {name: pulp.LpVariable(f"f{tag}_{name.replace('-', '_')}", cat=pulp.LpBinary) for name in FORMATIONS}
    buy_vars = {key: pulp.LpVariable(f"b{tag}_{index}", cat=pulp.LpBinary) for index, key in enumerate(buyable)}
    sell_vars = {key: pulp.LpVariable(f"s{tag}_{index}", cat=pulp.LpBinary) for index, key in enumerate(sellable)}

    problem += pulp.lpSum(formation_vars.values()) == 1, f"form_{tag}"
    problem += pulp.lpSum(chosen.values()) == XI_SIZE, f"xi_{tag}"
    for position in POSITIONS:
        problem += (
            pulp.lpSum(chosen[candidate.key] for candidate in starters if candidate.position == position)
            == pulp.lpSum(FORMATIONS[name][position] * formation_vars[name] for name in FORMATIONS)
        ), f"cupo_{tag}_{position}"

    owned_keys = {asset.candidate.key for asset in owned}
    for slot, candidate in enumerate(starters):
        xi = chosen[candidate.key]
        if candidate.key in owned_keys:
            if candidate.key in sell_vars:
                problem += xi <= 1 - sell_vars[candidate.key], f"disp_{tag}_{slot}"
            continue
        problem += xi <= buy_vars[candidate.key], f"compra_{tag}_{slot}"

    buy_cost = pulp.lpSum(buy_vars[key] * buyable[key].cost_eur for key in buy_vars)
    sale_income = pulp.lpSum(sell_vars[key] * sellable[key].sell_eur for key in sell_vars)
    problem += cash + sale_income - buy_cost >= 0, f"caja_{tag}"
    if buy_vars:
        problem += pulp.lpSum(buy_vars.values()) <= MAX_SIGNINGS, f"tope_{tag}"
    points = pulp.lpSum(chosen[candidate.key] * float(candidate.jornada_ev) for candidate in starters)

    for index, cut in enumerate(cuts):
        blocked = [
            buy_vars[key]
            for key in buy_vars
            if buyable[key].candidate.player_id in cut.bought
        ]
        if len(blocked) >= 2:
            problem += pulp.lpSum(blocked) <= len(blocked) - 1, f"corte_{tag}_{index}"
        elif len(blocked) == 1:
            problem += blocked[0] == 0, f"corte_{tag}_{index}"

    engine = pulp.PULP_CBC_CMD(msg=False, timeLimit=_SOLVER_TIME)
    problem.setObjective(points)
    status = pulp.LpStatus.get(problem.solve(engine), "NotSolved")
    if status != "Optimal":
        return None
    best_points = pulp.value(points)
    if best_points is None:
        return None

    def _picked(variables: dict[str, Any]) -> set[str]:
        return {key for key, variable in variables.items() if (variable.value() or 0.0) > 0.5}

    chosen_keys = _picked(chosen)
    bought_keys = _picked(buy_vars)
    formation = next((name for name, variable in formation_vars.items() if (variable.value() or 0.0) > 0.5), None)
    # CBC a veces no reacepta el óptimo de puntos al céntimo. Si el desempate
    # de precio no resuelve, nos quedamos con el once que ya maximiza puntos.
    problem += points >= float(best_points) - 0.02, f"puntos_{tag}"
    max_sale = sum(asset.sell_eur or 0 for asset in sellable.values()) + 1
    problem.sense = pulp.LpMinimize
    problem.setObjective(float(max_sale) * buy_cost + sale_income)
    if pulp.LpStatus.get(problem.solve(engine), "NotSolved") == "Optimal":
        chosen_keys = _picked(chosen)
        bought_keys = _picked(buy_vars)
        formation = next((name for name, variable in formation_vars.items() if (variable.value() or 0.0) > 0.5), formation)

    xi_rows = [candidate for candidate in starters if candidate.key in chosen_keys]
    if len(xi_rows) != XI_SIZE:
        return None
    bought = [buyable[key] for key in bought_keys]
    xi_ids = {candidate.player_id for candidate in xi_rows if candidate.player_id}
    spend_now = sum(asset.cost_eur for asset in bought)
    sold = _sales_for_plan(cash, spend_now, sellable, xi_ids, baseline_ids)
    spend = sum(asset.cost_eur for asset in bought)
    income = sum(asset.sell_eur or 0 for asset in sold)
    cash_after = cash + income - spend
    if cash_after < 0:
        return None
    expected = round(sum(float(candidate.jornada_ev) for candidate in xi_rows), 4)
    if not bought and not sold and not keep_if_not_better:
        return None
    if not keep_if_not_better and baseline_points is not None and expected < baseline_points + MIN_GAIN:
        return None
    bought_market = sum(asset.market_eur if asset.market_eur is not None else asset.cost_eur for asset in bought)
    sold_market = sum(asset.sell_eur or 0 for asset in sold)
    value_delta = income - spend + bought_market - sold_market
    xi_ids = {candidate.player_id for candidate in xi_rows}
    moves: list[dict[str, Any]] = []
    for asset in sold:
        candidate = asset.candidate
        moves.append(
            {
                "kind": "vender",
                "player_id": candidate.player_id,
                "name": candidate.name,
                "nickname": candidate.nickname,
                "position": candidate.position,
                "image_url": candidate.image_url,
                "amount_eur": asset.sell_eur,
                "jornada_ev": candidate.jornada_ev,
                "points_in_xi": candidate.jornada_ev if candidate.player_id in xi_ids else 0.0,
                "manager_name": None,
            }
        )
    for asset in bought:
        candidate = asset.candidate
        moves.append(
            {
                "kind": asset.kind,
                "player_id": candidate.player_id,
                "name": candidate.name,
                "nickname": candidate.nickname,
                "position": candidate.position,
                "image_url": candidate.image_url,
                "amount_eur": asset.cost_eur,
                "jornada_ev": candidate.jornada_ev,
                "points_in_xi": candidate.jornada_ev if candidate.player_id in xi_ids else 0.0,
                "manager_name": asset.manager_name,
            }
        )
    delta = None if baseline_points is None else round(expected - baseline_points, 4)
    per_million = None
    if spend > 0 and delta is not None:
        per_million = round(delta / (spend / 1_000_000), 4)
    return {
        "expected_points": expected,
        "points_delta": delta,
        "cash_after_eur": cash_after,
        "spend_eur": spend,
        "sale_income_eur": income,
        "net_eur": income - spend,
        "points_per_million": per_million,
        "needs_sale": bool(sold),
        "cash_only": not sold,
        "value_delta_eur": value_delta,
        "formation": formation,
        "moves": moves,
        "xi": [_player_row(candidate) for candidate in xi_rows],
        "_bought_ids": frozenset(asset.candidate.player_id for asset in bought if asset.candidate.player_id),
        "_sold_ids": frozenset(asset.candidate.player_id for asset in sold if asset.candidate.player_id),
    }


def _label(row: dict[str, Any]) -> str | None:
    nickname = row.get("nickname")
    if isinstance(nickname, str) and nickname.strip():
        return nickname.strip()
    name = row.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _attach_replacements(plan: dict[str, Any], baseline_rows: list[dict[str, Any]]) -> None:
    """Cada fichaje nombra al jugador del once al que sustituye y el delta de ese cambio."""
    base: dict[str, dict[str, Any]] = {}
    for row in baseline_rows:
        player_id = row.get("player_id")
        if isinstance(player_id, str) and player_id:
            base[player_id] = row
    new_ids = {
        row.get("player_id")
        for row in plan.get("xi") or []
        if isinstance(row, dict) and isinstance(row.get("player_id"), str)
    }
    outs = [row for player_id, row in base.items() if player_id not in new_ids]
    ins = [
        move
        for move in plan.get("moves") or []
        if move.get("kind") != "vender" and move.get("player_id") in new_ids
    ]
    used: set[str] = set()

    def _take(incoming: dict[str, Any], pool: list[dict[str, Any]]) -> None:
        outgoing = min(pool, key=lambda row: float(row.get("jornada_ev") or 0.0))
        outgoing_id = outgoing.get("player_id")
        if not isinstance(outgoing_id, str):
            return
        used.add(outgoing_id)
        in_ev = float(incoming.get("jornada_ev") or 0.0)
        out_ev = float(outgoing.get("jornada_ev") or 0.0)
        incoming["replaces_id"] = outgoing_id
        incoming["replaces_name"] = _label(outgoing)
        incoming["points_delta"] = round(in_ev - out_ev, 4)

    ordered = sorted(ins, key=lambda move: -float(move.get("jornada_ev") or 0.0))
    for incoming in ordered:
        same = [
            row
            for row in outs
            if row.get("position") == incoming.get("position") and row.get("player_id") not in used
        ]
        if same:
            _take(incoming, same)
    for incoming in ordered:
        if incoming.get("replaces_id"):
            continue
        pool = [row for row in outs if row.get("player_id") not in used]
        if pool:
            _take(incoming, pool)
    paired = {
        move.get("replaces_id"): move
        for move in ins
        if isinstance(move.get("replaces_id"), str)
    }
    for move in plan.get("moves") or []:
        if move.get("kind") != "vender":
            continue
        incoming = paired.get(move.get("player_id"))
        if not isinstance(incoming, dict):
            continue
        move["replaced_by_name"] = _label(incoming)
        move["points_delta"] = incoming.get("points_delta")


def search_strategies(
    *,
    cash: int,
    owned: list[OwnedAsset],
    targets: list[TargetAsset],
    baseline_points: float | None = None,
    baseline_xi: list[dict[str, Any]] | None = None,
    max_plans: int = MAX_PLANS,
) -> dict[str, Any]:
    rows = baseline_xi if isinstance(baseline_xi, list) and baseline_xi else []
    if not rows:
        bare = _solve_once(
            cash=0,
            owned=owned,
            targets=[],
            allow_sales=False,
            cuts=(),
            keep_if_not_better=True,
        )
        rows = bare.get("xi") if isinstance(bare, dict) else []
    baseline_ids = frozenset(
        row.get("player_id") for row in rows if isinstance(row, dict) and isinstance(row.get("player_id"), str)
    )
    plans: list[dict[str, Any]] = []
    cuts: list[_TransferCut] = []
    for _ in range(max(1, max_plans)):
        solved = _solve_once(
            cash=cash,
            owned=owned,
            targets=targets,
            allow_sales=True,
            cuts=tuple(cuts),
            baseline_points=baseline_points,
            baseline_ids=baseline_ids,
        )
        if solved is None:
            break
        plans.append(solved)
        cuts.append(_TransferCut(bought=solved["_bought_ids"], sold=solved["_sold_ids"]))

    if any(plan.get("needs_sale") for plan in plans) and len(plans) < max(1, max_plans):
        cash_only = _solve_once(
            cash=cash,
            owned=owned,
            targets=targets,
            allow_sales=False,
            cuts=(),
            baseline_points=baseline_points,
            baseline_ids=baseline_ids,
        )
        if cash_only is not None:
            signature = (cash_only["_bought_ids"], cash_only["_sold_ids"])
            if all((plan["_bought_ids"], plan["_sold_ids"]) != signature for plan in plans):
                cash_only["cash_only"] = True
                plans.append(cash_only)

    for plan in plans:
        _attach_replacements(plan, rows if isinstance(rows, list) else [])

    plans.sort(
        key=lambda plan: (
            -(float(plan["points_delta"]) if isinstance(plan.get("points_delta"), (int, float)) else float(plan["expected_points"])),
            int(plan.get("spend_eur") or 0),
        )
    )
    cleaned: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        row = {key: value for key, value in plan.items() if not key.startswith("_")}
        row["id"] = f"s{index}"
        row["rank"] = index
        cleaned.append(row)
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "strategy-search",
        "sends": False,
        "baseline_points": baseline_points,
        "strategies": cleaned,
    }


def strategies_from_documents(
    market: dict[str, Any] | None,
    squads: dict[str, Any] | None,
    trends: dict[str, Any] | None,
    optimize: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cash, owned, targets = collect_universe(market, squads, trends)
    empty = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "strategy-search",
        "sends": False,
        "baseline_points": None,
        "strategies": [],
    }
    if cash is None or not owned:
        return empty
    baseline = _baseline_points(owned, optimize)
    xi_rows = None
    if isinstance(optimize, dict) and isinstance(optimize.get("xi"), list):
        xi_rows = [row for row in optimize["xi"] if isinstance(row, dict)]
    key = _photo_key(cash, owned, targets, baseline)
    cached = _PHOTO_CACHE.get(key)
    if cached is not None:
        return cached
    document = search_strategies(
        cash=cash,
        owned=owned,
        targets=targets,
        baseline_points=baseline,
        baseline_xi=xi_rows,
    )
    return _remember(key, document)

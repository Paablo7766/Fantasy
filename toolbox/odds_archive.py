"""Cuotas reales guardadas por día y probabilidad de gol de mercado por jugador.

Dos cosas que antes se tiraban a las 6 h de caché:

* El 1X2, el más/menos 2,5 y el «ambos marcan» de Pinnacle de cada partido, un
  registro por partido y día. Sin ese histórico no se puede medir si la mezcla
  mercado/xG del calendario acierta más que el mercado solo.
* «Marca en cualquier momento» de bet365 (Pinnacle no lo ofrece en LaLiga). Se
  convierte en probabilidad de gol por jugador y se guarda junto a la propia
  (``own_goal_probability``) para compararlas. **No entra en el xP**: hasta que
  el histórico diga que acierta más que el modelo, solo se mide.

Las cuotas simuladas (modelo propio disfrazado de mercado) nunca se guardan.
"""

from __future__ import annotations

import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root, madrid_day
from toolbox.matching import name_similarity, normalize_club

SCORER_BOOKMAKER = "bet365"
MARKET_ANYTIME_SCORER = "10730"
# Por debajo, el nombre de bet365 no se enlaza: mejor sin dato que con otro jugador.
SCORER_MATCH_FLOOR = 0.85
# Fracción de los goles del equipo que marca un jugador (el resto, en propia).
_OWN_GOAL_SHARE = 0.03
# Sin λ de mercado, margen típico del «anytime» de bet365 (suma ≈ 1,25×).
_FALLBACK_MARGIN = 1.25
_P_CAP = 0.9


def _db_path() -> Path:
    return cache_root() / "responses.sqlite"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists odds_snapshots (
            match_key text not null,
            day text not null,
            source text not null,
            kickoff text,
            odds_home real, odds_draw real, odds_away real,
            odds_over25 real, odds_under25 real,
            odds_btts_yes real, odds_btts_no real,
            stored_at real not null,
            primary key (match_key, day)
        )
        """
    )
    conn.execute(
        """
        create table if not exists scorer_odds_snapshots (
            match_key text not null,
            day text not null,
            player_name text not null,
            bookmaker text not null,
            price real not null,
            player_id text,
            market_goal_probability real,
            kickoff text,
            stored_at real not null,
            primary key (match_key, day, player_name)
        )
        """
    )
    # Líneas extra de Pinnacle (totales por equipo, totales y hándicaps). Sirven
    # para medir si la portería a cero sale mejor de ``teamTotal`` a 0,5 que del
    # 1X2 con Poisson. Solo se miden: no entran en el xP.
    conn.execute(
        """
        create table if not exists odds_lines_snapshots (
            match_key text not null,
            day text not null,
            kind text not null,
            outcome text not null,
            price real not null,
            source text,
            kickoff text,
            stored_at real not null,
            primary key (match_key, day, kind, outcome)
        )
        """
    )
    conn.commit()


# --- Parseo -----------------------------------------------------------------


def display_name(raw: str) -> str:
    """bet365 escribe «Yamal, Lamine»; el catálogo, «Lamine Yamal»."""
    text = raw.strip()
    if "," in text:
        last, first = (part.strip() for part in text.split(",", 1))
        return f"{first} {last}".strip()
    return text


def scorer_prices(fixture: dict[str, Any], *, bookmaker: str = SCORER_BOOKMAKER) -> list[dict[str, Any]]:
    """Cuotas de «marca en cualquier momento» de una respuesta ``/odds``.

    bet365 deja la casa en ``suspended`` y cada línea en ``active: false`` desde
    varios días antes del partido, con la cuota ya escrita. Tirar esas líneas
    dejaba la tabla vacía: la cuota es la señal, y el cierre de la jornada
    llega antes de que la casa reabra el mercado. Una línea inactiva con la
    casa abierta (un jugador retirado del tablero) sí se descarta.
    """
    books = fixture.get("bookmakerOdds") if isinstance(fixture.get("bookmakerOdds"), dict) else {}
    book = books.get(bookmaker)
    if not isinstance(book, dict):
        return []
    book_suspended = book.get("suspended") is True
    markets = book.get("markets") if isinstance(book.get("markets"), dict) else {}
    market = markets.get(MARKET_ANYTIME_SCORER)
    if not isinstance(market, dict) or market.get("marketActive") is False:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for outcome in (market.get("outcomes") or {}).values():
        players = outcome.get("players") if isinstance(outcome, dict) else None
        if not isinstance(players, dict):
            continue
        for line in players.values():
            if not isinstance(line, dict):
                continue
            inactive = line.get("active") is False
            if inactive and not book_suspended:
                continue
            name, price = line.get("playerName"), line.get("price")
            if not isinstance(name, str) or not name.strip():
                continue
            if isinstance(price, bool) or not isinstance(price, (int, float)) or float(price) <= 1.0:
                continue
            label = display_name(name)
            if label in seen:
                continue
            seen.add(label)
            row: dict[str, Any] = {"name": label, "price": float(price), "bookmaker": bookmaker}
            if book_suspended or inactive:
                row["suspended"] = True
            rows.append(row)
    return rows


_LINE_KINDS = ("teamTotal", "totals", "spreads")


def extra_lines(fixture: dict[str, Any], *, bookmaker: str) -> list[dict[str, Any]]:
    """Cuotas activas de totales por equipo, totales y hándicaps de una respuesta ``/odds``.

    El nombre de la línea (``home/0.5/under``) viene en ``bookmakerOutcomeId``.
    Los mercados especiales de número suelto no se guardan: sin el catálogo de
    OddsPapi no se sabe qué son.
    """
    books = fixture.get("bookmakerOdds") if isinstance(fixture.get("bookmakerOdds"), dict) else {}
    book = books.get(bookmaker)
    if not isinstance(book, dict) or book.get("suspended") is True:
        return []
    markets = book.get("markets") if isinstance(book.get("markets"), dict) else {}
    rows: list[dict[str, Any]] = []
    for market in markets.values():
        if not isinstance(market, dict) or market.get("marketActive") is False:
            continue
        kind = str(market.get("bookmakerMarketId") or "").rsplit("/", 1)[-1]
        if kind not in _LINE_KINDS:
            continue
        for outcome in (market.get("outcomes") or {}).values():
            players = outcome.get("players") if isinstance(outcome, dict) else None
            line = players.get("0") if isinstance(players, dict) else None
            if not isinstance(line, dict) or line.get("active") is False:
                continue
            name, price = line.get("bookmakerOutcomeId"), line.get("price")
            if not isinstance(name, str) or not name:
                continue
            if isinstance(price, bool) or not isinstance(price, (int, float)) or float(price) <= 1.0:
                continue
            rows.append({"kind": kind, "outcome": name, "price": float(price)})
    return rows


# --- Probabilidad de mercado ------------------------------------------------


def _team_lambdas(bundle: dict[str, Any]) -> tuple[float, float] | None:
    odds_1x2 = bundle.get("odds_1x2")
    if not isinstance(odds_1x2, (list, tuple)) or len(odds_1x2) != 3:
        return None
    from toolbox.understat import invert_market_to_dixon_coles

    ou = bundle.get("odds_ou25")
    btts = bundle.get("odds_btts")
    try:
        lam_h, lam_a, _rho = invert_market_to_dixon_coles(
            tuple(float(x) for x in odds_1x2),  # type: ignore[arg-type]
            tuple(float(x) for x in ou) if isinstance(ou, (list, tuple)) and len(ou) == 2 else None,  # type: ignore[arg-type]
            tuple(float(x) for x in btts) if isinstance(btts, (list, tuple)) and len(btts) == 2 else None,  # type: ignore[arg-type]
        )
    except Exception:  # noqa: BLE001 — sin λ se usa el margen fijo
        return None
    if lam_h > 0 and lam_a > 0:
        return float(lam_h), float(lam_a)
    return None


def _scale_to_team_goals(raw: list[float], team_lambda: float) -> float:
    """Factor k tal que Σ −ln(1 − k·pᵢ) = goles esperados del equipo que marcan sus jugadores.

    Si cada jugador marca como un Poisson de media μᵢ, P(marca) = 1 − e^(−μᵢ) y
    Σ μᵢ son los goles del equipo. Quitar el margen de la casa es escalar las
    probabilidades brutas hasta que cuadren con los goles que dice el 1X2.
    """
    target = team_lambda * (1.0 - _OWN_GOAL_SHARE)
    if not raw or target <= 0:
        return 1.0 / _FALLBACK_MARGIN

    def total(k: float) -> float:
        return sum(-math.log(1.0 - min(_P_CAP, k * p)) for p in raw)

    # Si ni con las cuotas brutas se llega a los goles del equipo, la lista
    # está incompleta (goleadores sin enlazar): escalar inflaría a los que sí
    # están. La casa siempre tiene margen, así que k nunca pasa de 1.
    if total(1.0) < target:
        return 1.0 / _FALLBACK_MARGIN
    low, high = 0.0, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        if total(mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _club_key(player: dict[str, Any]) -> str:
    club = player.get("club")
    return normalize_club(club) if isinstance(club, str) and club else ""


def _link(name: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored: list[tuple[float, dict[str, Any]]] = []
    for player in candidates:
        best = max(
            name_similarity(name, player.get("name")),
            name_similarity(name, player.get("nickname")),
        )
        if best >= SCORER_MATCH_FLOOR:
            scored.append((best, player))
    if not scored:
        return None
    scored.sort(key=lambda item: -item[0])
    # Dos candidatos casi igual de parecidos: no se adivina.
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.03:
        return None
    return scored[0][1]


def apply_market_scorer_odds(players: list[dict[str, Any]], match_odds: dict[str, Any] | None) -> dict[str, Any]:
    """Escribe ``market_goal_probability`` en los jugadores con cuota de goleador.

    Solo informa: no toca ``own_expected_points`` ni ``own_goal_probability``.
    """
    by_club: dict[str, list[dict[str, Any]]] = {}
    for player in players:
        if isinstance(player, dict):
            by_club.setdefault(_club_key(player), []).append(player)
    linked = 0
    listed = 0
    matches = 0
    for key, bundle in (match_odds or {}).items():
        if not isinstance(bundle, dict) or bundle.get("source") == "simulated":
            continue
        scorers = bundle.get("anytime_scorers")
        if not isinstance(scorers, list) or not scorers:
            continue
        home_key, _, away_key = str(key).partition("|")
        sides = {home_key: by_club.get(home_key, []), away_key: by_club.get(away_key, [])}
        lambdas = _team_lambdas(bundle)
        team_lambda = {home_key: lambdas[0], away_key: lambdas[1]} if lambdas else {}
        matches += 1
        assigned: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {home_key: [], away_key: []}
        for row in scorers:
            listed += 1
            candidates = sides[home_key] + sides[away_key]
            player = _link(str(row.get("name") or ""), candidates)
            if player is None:
                continue
            side = home_key if player in sides[home_key] else away_key
            assigned[side].append((row, player))
        for side, pairs in assigned.items():
            if not pairs:
                continue
            raw = [1.0 / float(row["price"]) for row, _player in pairs]
            k = _scale_to_team_goals(raw, team_lambda[side]) if side in team_lambda else 1.0 / _FALLBACK_MARGIN
            for (row, player), p_raw in zip(pairs, raw):
                prob = round(min(_P_CAP, k * p_raw), 4)
                row["player_id"] = player.get("player_id")
                row["market_goal_probability"] = prob
                player["market_goal_probability"] = prob
                player["market_goal_price"] = row["price"]
                player["market_goal_source"] = row.get("bookmaker") or SCORER_BOOKMAKER
                linked += 1
    return {
        "ok": linked > 0,
        "count": linked,
        "error": None if linked else ("sin_cuotas_de_goleador" if matches == 0 else "goleadores_sin_enlazar"),
        "from_cache": False,
        "listed": listed,
        "matches": matches,
    }


# --- Histórico --------------------------------------------------------------


def _pair(value: Any) -> tuple[float | None, float | None]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    return None, None


def archive_match_odds(
    match_odds: dict[str, Any] | None,
    *,
    day: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Guarda las cuotas reales del día (la última captura del día gana). Las simuladas no."""
    rows = [
        (key, bundle)
        for key, bundle in (match_odds or {}).items()
        if isinstance(bundle, dict) and bundle.get("source") not in (None, "simulated")
        and isinstance(bundle.get("odds_1x2"), (list, tuple))
    ]
    if not rows:
        return 0
    own = conn is None
    db = conn or sqlite3.connect(_db_path())
    stamp = time.time()
    stamp_day = day or madrid_day()
    try:
        ensure_schema(db)
        for key, bundle in rows:
            home, draw, away = (float(x) for x in bundle["odds_1x2"])
            over, under = _pair(bundle.get("odds_ou25"))
            yes, no = _pair(bundle.get("odds_btts"))
            kickoff = bundle.get("kickoff") if isinstance(bundle.get("kickoff"), str) else None
            db.execute(
                """
                insert into odds_snapshots values (?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(match_key, day) do update set
                    source=excluded.source, kickoff=excluded.kickoff,
                    odds_home=excluded.odds_home, odds_draw=excluded.odds_draw, odds_away=excluded.odds_away,
                    odds_over25=excluded.odds_over25, odds_under25=excluded.odds_under25,
                    odds_btts_yes=excluded.odds_btts_yes, odds_btts_no=excluded.odds_btts_no,
                    stored_at=excluded.stored_at
                """,
                (key, stamp_day, str(bundle.get("source")), kickoff, home, draw, away, over, under, yes, no, stamp),
            )
            for line in bundle.get("extra_lines") or []:
                if not isinstance(line, dict) or not isinstance(line.get("outcome"), str):
                    continue
                db.execute(
                    """
                    insert into odds_lines_snapshots values (?,?,?,?,?,?,?,?)
                    on conflict(match_key, day, kind, outcome) do update set
                        price=excluded.price, source=excluded.source,
                        kickoff=excluded.kickoff, stored_at=excluded.stored_at
                    """,
                    (key, stamp_day, str(line.get("kind")), line["outcome"], float(line["price"]),
                     str(bundle.get("source")), kickoff, stamp),
                )
            for scorer in bundle.get("anytime_scorers") or []:
                if not isinstance(scorer, dict) or not isinstance(scorer.get("name"), str):
                    continue
                db.execute(
                    """
                    insert into scorer_odds_snapshots values (?,?,?,?,?,?,?,?,?)
                    on conflict(match_key, day, player_name) do update set
                        bookmaker=excluded.bookmaker, price=excluded.price,
                        player_id=coalesce(excluded.player_id, scorer_odds_snapshots.player_id),
                        market_goal_probability=coalesce(excluded.market_goal_probability, scorer_odds_snapshots.market_goal_probability),
                        kickoff=excluded.kickoff, stored_at=excluded.stored_at
                    """,
                    (
                        key,
                        stamp_day,
                        scorer["name"],
                        str(scorer.get("bookmaker") or SCORER_BOOKMAKER),
                        float(scorer["price"]),
                        scorer.get("player_id"),
                        scorer.get("market_goal_probability"),
                        kickoff,
                        stamp,
                    ),
                )
        db.commit()
    finally:
        if own:
            db.close()
    return len(rows)


def kickoff_iso(fixture: dict[str, Any]) -> str | None:
    raw = fixture.get("startTime")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc).isoformat()
    if isinstance(raw, str) and raw.strip():
        return raw.replace("Z", "+00:00")
    return None

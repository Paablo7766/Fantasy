"""Backtest retroactivo (walk-forward) del xP contra los puntos ya jugados.

Para cada jornada ``t`` de la ventana de test, predice a cada jugador solo con
las jornadas ``< t`` y compara contra sus puntos reales de ``t``.

La historia sale de ``playerMaster.lastStats``. El rival no está en esa serie:
se cruza ``(equipo, jornada)`` con el calendario (número de jornada) y con el
xG de Understat de los partidos ya disputados. El xG del propio partido ``t``
no entra en el λ: solo los partidos anteriores.

    python scripts/backtest_xp.py
    python scripts/backtest_xp.py --test-weeks 9 10 11 --min-prior 2
"""

from __future__ import annotations

import argparse
import math
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.cache import cache_root  # noqa: E402
from toolbox.engine.xp_calculator import (  # noqa: E402
    LIGA_AVG_XG,
    PRIORS_TITULAR,
    STARTER_MINUTES,
    FantasyXPEngine,
    PartidoHistorico,
    canonical_slot,
    lambdas_de_fuerzas,
)
from toolbox.matching import normalize_club  # noqa: E402
from toolbox.player_history import load_history  # noqa: E402
from toolbox.opta_points_v2 import compute_expected_opta_points_v2  # noqa: E402
from toolbox.understat import parse_openfootball_matchdays, understat_played_matches  # noqa: E402

SCHEDULE_URL = "https://raw.githubusercontent.com/openfootball/espana/master/2026-27/1-liga.txt"


def load_schedule(cache: Path) -> str | None:
    path = cache / "laliga_2026_27.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    try:
        request = urllib.request.Request(SCHEDULE_URL, headers={"User-Agent": "fantasy-backtest"})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
    except (OSError, urllib.error.URLError):
        return None
    path.write_text(text, encoding="utf-8")
    return text


def build_fixtures(
    understat: dict[str, Any] | None,
    matchdays: dict[tuple[str, str], int],
) -> dict[tuple[str, int], dict[str, Any]]:
    """``(club, jornada)`` → rival, localía y xG de ESE partido (solo resultado)."""
    if understat is None:
        return {}
    dates = [row for row in (understat.get("dates") or []) if isinstance(row, dict)]
    fixtures: dict[tuple[str, int], dict[str, Any]] = {}
    for match in understat_played_matches(dates):
        jornada = matchdays.get((match["home_key"], match["away_key"]))
        if jornada is None:
            continue
        home_side = {
            "opponent": match["away"],
            "opponent_key": match["away_key"],
            "home": True,
            "xg": match["xg_home"],
            "xga": match["xg_away"],
            "jornada": jornada,
            "kickoff": match["kickoff"],
        }
        away_side = {
            "opponent": match["home"],
            "opponent_key": match["home_key"],
            "home": False,
            "xg": match["xg_away"],
            "xga": match["xg_home"],
            "jornada": jornada,
            "kickoff": match["kickoff"],
        }
        fixtures[(match["home_key"], jornada)] = home_side
        fixtures[(match["away_key"], jornada)] = away_side
    # Identidad del rival aunque Understat no tenga xG (partido aplazado).
    # El xG de ese partido no se usa como λ: solo hace falta saber contra quién.
    for (home_key, away_key), jornada in matchdays.items():
        fixtures.setdefault(
            (home_key, jornada),
            {"opponent": away_key, "opponent_key": away_key, "home": True, "xg": None, "xga": None, "jornada": jornada},
        )
        fixtures.setdefault(
            (away_key, jornada),
            {"opponent": home_key, "opponent_key": home_key, "home": False, "xg": None, "xga": None, "jornada": jornada},
        )
    return fixtures


def _prior_rates(
    fixtures: dict[tuple[str, int], dict[str, Any]],
    club: str,
    before: str,
) -> tuple[float, float] | None:
    """Medias de xG a favor/en contra de partidos con kickoff anterior a ``before``.

    Se filtra por fecha y no por número de jornada: un aplazado de una jornada
    baja jugado después no debe colarse en el λ de una jornada posterior.
    """
    scored: list[float] = []
    conceded: list[float] = []
    for jornada in range(1, 39):
        hit = fixtures.get((club, jornada))
        if hit is None or hit["xg"] is None or hit["xga"] is None:
            continue
        if not hit.get("kickoff") or hit["kickoff"] >= before:
            continue
        scored.append(float(hit["xg"]))
        conceded.append(float(hit["xga"]))
    if not scored:
        return None
    return sum(scored) / len(scored), sum(conceded) / len(conceded)


def _league_xg(fixtures: dict[tuple[str, int], dict[str, Any]], before: str) -> float:
    # Cada partido aporta el xG de los dos equipos (una entrada por lado).
    both = [
        float(hit["xg"])
        for hit in fixtures.values()
        if hit["xg"] is not None and hit.get("kickoff") and hit["kickoff"] < before
    ]
    if not both:
        return LIGA_AVG_XG
    return sum(both) / len(both)


def _prior(entry: dict[str, Any], week: int) -> list[PartidoHistorico]:
    return [
        PartidoHistorico(puntos=pts, minutos=int(mins), jornada=wk)
        for wk, (pts, mins) in sorted(entry["weeks"].items())
        if wk < week
    ]


def _predict(entry: dict[str, Any], prior: list[PartidoHistorico], p_titular: float, lambdas: tuple[float, float] | None) -> dict[str, float]:
    player = {
        "position": entry["position"],
        "p_titular": p_titular,
        "market_value": entry.get("precio"),
        "historial": [{"puntos": p.puntos, "minutos": p.minutos, "jornada": p.jornada} for p in prior],
    }
    kwargs: dict[str, Any] = {"run_monte_carlo": False}
    if lambdas is not None:
        kwargs["lambda_own"] = lambdas[0]
        kwargs["lambda_opp"] = lambdas[1]
    return compute_expected_opta_points_v2(player, **kwargs)


def _kickoff_from_week(fixtures: dict[tuple[str, int], dict[str, Any]], week: int) -> str | None:
    """Partido sin xG (aplazado): usa el primer kickoff conocido de esa jornada."""
    stamps = [h["kickoff"] for (_, j), h in fixtures.items() if j == week and h.get("kickoff")]
    return min(stamps) if stamps else None


def _context_for(
    entry: dict[str, Any],
    week: int,
    fixtures: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any] | None:
    club = normalize_club(entry.get("team"))
    fixture = fixtures.get((club, week))
    if fixture is None:
        return None
    before = fixture.get("kickoff") or _kickoff_from_week(fixtures, week)
    if not before:
        return None
    own = _prior_rates(fixtures, club, before)
    opp = _prior_rates(fixtures, fixture["opponent_key"], before)
    if own is None or opp is None:
        return {
            "opponent": fixture["opponent"],
            "home": bool(fixture["home"]),
            "lambdas": None,
            "opp_xg": None,
            "opp_xga": None,
            "league": None,
        }
    league = _league_xg(fixtures, before)
    favor, contra = lambdas_de_fuerzas(own[0], own[1], opp[0], opp[1], es_local=bool(fixture["home"]), liga_xg=league)
    return {
        "opponent": fixture["opponent"],
        "home": bool(fixture["home"]),
        "lambdas": (favor, contra),
        "opp_xg": opp[0],
        "opp_xga": opp[1],
        "league": league,
    }


def run(
    players: dict[str, dict[str, Any]],
    fixtures: dict[tuple[str, int], dict[str, Any]],
    test_weeks: list[int],
    min_prior: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in players.values():
        slot = canonical_slot(entry["position"])
        for week in test_weeks:
            if week not in entry["weeks"]:
                continue
            prior = _prior(entry, week)
            if len(prior) < min_prior:
                continue
            actual, minutes = entry["weeks"][week]
            p_tit = FantasyXPEngine.prob_titular_heuristica(prior) or 0.5
            neutral = _predict(entry, prior, p_tit, None)
            conditional = _predict(entry, prior, 1.0, None)
            context = _context_for(entry, week, fixtures)
            lambdas = context["lambdas"] if context else None
            rival = _predict(entry, prior, p_tit, lambdas) if lambdas else neutral
            rival_if = _predict(entry, prior, 1.0, lambdas) if lambdas else conditional
            starters = [p for p in prior if p.minutos >= STARTER_MINUTES]
            played_prior = [p for p in prior if p.minutos > 0]
            rows.append(
                {
                    "pos": entry["position"],
                    "slot": slot,
                    "week": week,
                    "team": normalize_club(entry.get("team")),
                    "actual": actual,
                    "minutes": minutes,
                    "played": minutes > 0,
                    "starter": minutes >= STARTER_MINUTES,
                    "p_tit": p_tit,
                    "n_prior": len(prior),
                    "n_tit": len(starters),
                    "n_short": sum(1 for p in prior if 0 < p.minutos < STARTER_MINUTES),
                    "all_mean": sum(p.puntos for p in prior) / len(prior),
                    "starter_mean": (sum(p.puntos for p in starters) / len(starters)) if starters else None,
                    "played_mean": (sum(p.puntos for p in played_prior) / len(played_prior)) if played_prior else None,
                    "opta": float(neutral["expected_points"]),
                    "si": float(conditional["expected_points"]),
                    "opta_rival": float(rival["expected_points"]),
                    "si_rival": float(rival_if["expected_points"]),
                    "base": float(neutral["base_titular"]),
                    "factor": float(neutral["factor_partido"]),
                    "factor_rival": float(rival["factor_partido"]),
                    "linked": lambdas is not None,
                    "home": context["home"] if context else None,
                    "opponent": context["opponent"] if context else None,
                    "opp_xg": context["opp_xg"] if context else None,
                    "opp_xga": context["opp_xga"] if context else None,
                    "league": context["league"] if context else None,
                }
            )
    return rows


def _metrics(errors: list[float]) -> tuple[float, float, float]:
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    bias = sum(errors) / n
    return mae, rmse, bias


def _print_model(title: str, rows: list[dict[str, Any]], key: str) -> None:
    if not rows:
        print(f"  {title}: sin datos")
        return
    mae, rmse, bias = _metrics([r[key] - r["actual"] for r in rows])
    print(f"  {title:<28}{mae:8.3f}{rmse:8.3f}{bias:+8.3f}   n={len(rows)}")


def _band(ratio: float, *, defense: bool) -> float:
    """0,84–1,12. Para la defensa, un rival que genera mucho xG es difícil."""
    value = (1.0 / ratio) if defense and ratio > 0 else ratio
    if value >= 1.25:
        return 1.12
    if value >= 1.10:
        return 1.06
    if value >= 0.90:
        return 1.0
    if value >= 0.75:
        return 0.92
    return 0.84


def _rescale(row: dict[str, Any], factor: float) -> float:
    """Quita el factor neutro y aplica otro. El 0 de quien no juega se queda."""
    if row["opta"] <= 0 or row["factor"] <= 0:
        return 0.0
    return row["opta"] / row["factor"] * factor


def _grid(rows: list[dict[str, Any]]) -> None:
    linked = [r for r in rows if r["linked"]]
    if len(linked) < 30:
        print("\nGrid de rival: muestra insuficiente.")
        return

    def score(errors: list[float]) -> tuple[float, float, float]:
        return _metrics(errors)

    def apply(spec: dict[str, tuple[float, float]]) -> list[float]:
        errors = []
        for row in linked:
            league = row["league"] or LIGA_AVG_XG
            if row["slot"] in {"PT", "DF"}:
                signal = 1.0 - (row["opp_xg"] / league)
                weight, home_w = spec["DEF"]
            elif row["slot"] == "MC":
                signal = (row["opp_xga"] / league) - 1.0
                weight, home_w = spec["MC"]
            else:
                signal = (row["opp_xga"] / league) - 1.0
                weight, home_w = spec["DEL"]
            home = 1.0 if row["home"] else -1.0
            factor = min(1.45, max(0.70, 1.0 + weight * signal + home_w * home))
            errors.append(_rescale(row, factor) - row["actual"])
        return errors

    fixed_errors = []
    for row in linked:
        league = row["league"] or LIGA_AVG_XG
        if row["slot"] in {"PT", "DF"}:
            factor = _band(row["opp_xg"] / league, defense=True)
        else:
            factor = _band(row["opp_xga"] / league, defense=False)
        fixed_errors.append(_rescale(row, factor) - row["actual"])
    neutral_errors = [r["opta"] - r["actual"] for r in linked]
    engine_errors = [r["opta_rival"] - r["actual"] for r in linked]
    print("\nFactor de rival sobre las filas con contexto (mismo xP de base)")
    print(f"  {'modelo':<28}{'MAE':>8}{'RMSE':>8}{'sesgo':>8}")
    for name, errors in (
        ("sin rival (lambda neutro)", neutral_errors),
        ("motor actual con lambda", engine_errors),
        ("bandas fijas 0.84-1.12", fixed_errors),
    ):
        mae, rmse, bias = score(errors)
        print(f"  {name:<28}{mae:8.3f}{rmse:8.3f}{bias:+8.3f}")

    weights = (0.0, 0.25, 0.5, 0.75, 1.0)
    homes = (0.0, 0.04)
    best: tuple[tuple[float, float, float], dict[str, tuple[float, float]], tuple[float, float, float]] | None = None
    for def_w in weights:
        for mc_w in weights:
            for dl_w in weights:
                for home_w in homes:
                    spec = {"DEF": (def_w, home_w), "MC": (mc_w, home_w), "DEL": (dl_w, home_w)}
                    mae, rmse, bias = score(apply(spec))
                    rank = (mae, rmse, abs(bias))
                    if best is None or rank < best[0]:
                        best = (rank, spec, (mae, rmse, bias))
    assert best is not None
    mae, rmse, bias = best[2]
    spec = best[1]
    print(f"  {'grid 1+w*(senal)+h*local':<28}{mae:8.3f}{rmse:8.3f}{bias:+8.3f}")
    print(
        "  pesos: "
        f"POR/DEF w={spec['DEF'][0]:.2f}  MED w={spec['MC'][0]:.2f}  DEL w={spec['DEL'][0]:.2f}  "
        f"local +/-{spec['DEF'][1]:.2f}"
    )
    print("  senal DEF = 1 - xG_rival/liga; senal MED/DEL = xGA_rival/liga - 1. Recorte [0.70, 1.45].")

    print("\nRegresion lineal in-sample (y ~ base, base*senal, base*local)")
    groups = (("POR/DEF", {"PT", "DF"}, "opp_xg"), ("MED", {"MC"}, "opp_xga"), ("DEL", {"DL"}, "opp_xga"))
    for label, slots, signal_key in groups:
        subset = [r for r in linked if r["slot"] in slots]
        if len(subset) < 12:
            print(f"  {label}: n={len(subset)} insuficiente")
            continue
        design = []
        target = []
        for row in subset:
            league = row["league"] or LIGA_AVG_XG
            signal = row[signal_key] / league
            home = 1.0 if row["home"] else 0.0
            base = row["base"]
            design.append([1.0, base, base * signal, base * home])
            target.append(row["actual"])
        coef, *_ = np.linalg.lstsq(np.array(design), np.array(target), rcond=None)
        pred = np.array(design) @ coef
        mae, rmse, bias = _metrics((pred - np.array(target)).tolist())
        raw = _metrics([r["opta"] - r["actual"] for r in subset])
        print(
            f"  {label:<8} n={len(subset):<4} "
            f"a={coef[0]:+.2f} b_base={coef[1]:+.2f} b_senal={coef[2]:+.2f} b_local={coef[3]:+.2f}  "
            f"MAE {mae:.3f} (neutro {raw[0]:.3f})"
        )


def _diagnosis(rows: list[dict[str, Any]], players: dict[str, dict[str, Any]]) -> None:
    print("\nDiagnostico del sesgo (lambda neutro)")
    print(f"  {'recorte':<28}{'MAE':>8}{'RMSE':>8}{'sesgo':>8}")
    _print_model("opta_v2 todos", rows, "opta")
    _print_model("opta_v2 min>0", [r for r in rows if r["played"]], "opta")
    _print_model("opta_v2 titular >=45", [r for r in rows if r["starter"]], "opta")
    _print_model("si titular, todos", rows, "si")
    _print_model("si titular, min>0", [r for r in rows if r["played"]], "si")
    _print_model("si titular, titular >=45", [r for r in rows if r["starter"]], "si")

    starters = [r for r in rows if r["starter"]]
    if starters:
        p_mean = sum(r["p_tit"] for r in starters) / len(starters)
        all_mean = sum(r["all_mean"] for r in starters) / len(starters)
        own = [r["starter_mean"] for r in starters if r["starter_mean"] is not None]
        own_mean = sum(own) / len(own) if own else float("nan")
        base = sum(r["base"] for r in starters) / len(starters)
        print(
            f"\n  En quienes SI fueron titulares (n={len(starters)}): "
            f"p_titular media {p_mean:.2f} (techo de la heuristica 0.90), "
            f"media de toda la historia {all_mean:.2f}, "
            f"media solo de partidos >=45' {own_mean:.2f}, "
            f"base del motor {base:.2f}."
        )
        diluted = [r for r in starters if r["starter_mean"] is not None and (r["n_prior"] - r["n_tit"]) > 0]
        if diluted:
            gap = sum(r["starter_mean"] - r["all_mean"] for r in diluted) / len(diluted)
            print(
                f"  Historia con suplencia o cero: {len(diluted)}/{len(starters)}. "
                f"Sacar esos partidos SUBE la media {gap:.2f} pts. "
                "El motor ya los deja fuera de la base de titular; no hay segundo descuento por minutos."
            )

    print("\n  Prior del motor frente a la media de partidos >=45' ANTERIORES a la ventana")
    before: dict[str, list[float]] = defaultdict(list)
    for entry in players.values():
        slot = canonical_slot(entry["position"])
        for week, (pts, mins) in entry["weeks"].items():
            if week < min(r["week"] for r in rows) and mins >= STARTER_MINUTES:
                before[slot].append(pts)
    for slot, label in (("PT", "POR"), ("DF", "DEF"), ("MC", "MED"), ("DL", "DEL")):
        vals = before[slot]
        if not vals:
            continue
        empirical = sum(vals) / len(vals)
        prior = PRIORS_TITULAR[slot]
        print(f"  {label:<6} prior {prior:4.1f}   media previa n={len(vals):<3} {empirical:5.2f}   delta {prior - empirical:+5.2f}")

    raw = _metrics([r["opta"] - r["actual"] for r in rows])
    pred_mean = sum(r["opta"] for r in rows) / len(rows)
    actual_mean = sum(r["actual"] for r in rows) / len(rows)
    scale = actual_mean / pred_mean if pred_mean else 1.0
    scaled = _metrics([r["opta"] * scale - r["actual"] for r in rows])
    print(
        f"\n  Una escala global de {scale:.3f} deja el sesgo en 0, "
        f"pero el MAE pasa de {raw[0]:.3f} a {scaled[0]:.3f}. No forma parte del motor."
    )


def report(rows: list[dict[str, Any]], players: dict[str, dict[str, Any]]) -> None:
    linked = [r for r in rows if r["linked"]]
    print(f"\nFilas {len(rows)}  con rival y xG previo {len(linked)}")
    print(f"  {'modelo':<28}{'MAE':>8}{'RMSE':>8}{'sesgo':>8}")
    print("Sin contexto de rival")
    _print_model("opta_v2", rows, "opta")
    _print_model("opta_v2 si titular", rows, "si")
    print("Con el rival real (lambda de los xG previos)")
    _print_model("opta_v2", rows, "opta_rival")
    _print_model("opta_v2 si titular", rows, "si_rival")
    if linked and len(linked) != len(rows):
        print("Solo filas con rival")
        _print_model("opta_v2 neutro", linked, "opta")
        _print_model("opta_v2 con rival", linked, "opta_rival")
        neutral = _metrics([r["opta"] - r["actual"] for r in linked])
        rival = _metrics([r["opta_rival"] - r["actual"] for r in linked])
        print(
            f"  delta MAE {rival[0] - neutral[0]:+.3f}   "
            f"delta RMSE {rival[1] - neutral[1]:+.3f}   "
            f"delta sesgo {rival[2] - neutral[2]:+.3f}"
        )
    _diagnosis(rows, players)
    _grid(rows)


def _cargar_precios(players: dict[str, dict[str, Any]], cache: Path) -> None:
    """Valor de mercado del primer día guardado: prior por precio del motor."""
    import sqlite3

    db = cache / "responses.sqlite"
    if not db.is_file():
        return
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("select player_id, market_value from price_snapshots order by day desc").fetchall()
    except sqlite3.Error:
        return
    finally:
        conn.close()
    precios = {pid: value for pid, value in rows if value}
    for pid, entry in players.items():
        entry["precio"] = precios.get(pid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--test-weeks", type=int, nargs="+", default=[9, 10, 11])
    parser.add_argument("--min-prior", type=int, default=2, help="jornadas previas minimas por jugador")
    parser.add_argument("--bodies", type=Path, default=cache_root() / "scraper_bodies")
    parser.add_argument("--cache", type=Path, default=cache_root())
    args = parser.parse_args()

    players, understat = load_history(args.bodies)
    if understat is None:
        # Understat ya no sirve JSON: mismo respaldo que producción (xG de football-data).
        csv_path = args.cache / "football_data_raw_2627" / "SP1_2627.csv"
        if csv_path.exists():
            from toolbox.stats_fallback import build_backup_payload

            understat = build_backup_payload(None, {}, csv_path.read_text(encoding="utf-8"))
            print(f"Understat no está en la caché: xG de football-data ({csv_path.name}).")
    _cargar_precios(players, args.cache)
    coverage: dict[int, int] = defaultdict(int)
    for entry in players.values():
        for week in entry["weeks"]:
            coverage[week] += 1
    print(f"Jugadores con historia: {len(players)}")
    print("Cobertura por jornada:", dict(sorted(coverage.items())))

    schedule = load_schedule(args.cache)
    matchdays = parse_openfootball_matchdays(schedule) if schedule else {}
    fixtures = build_fixtures(understat, matchdays)
    print(f"Calendario: {len(matchdays)} partidos con jornada. Understat cruzado: {len(fixtures)} lados.")
    sample = fixtures.get(("real madrid", 9))
    if sample is not None:
        print(f"Control: Real Madrid J9 vs {sample['opponent']} local={sample['home']}")
    if understat is None or not matchdays:
        print("Sin calendario o sin Understat: el bloque de rival queda en lambda neutro.")

    rows = run(players, fixtures, args.test_weeks, args.min_prior)
    report(rows, players)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

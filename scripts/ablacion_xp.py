"""Ablación walk-forward del xP de producción (xp2 + opta_points_v2).

Cada jornada de test ``t`` se predice con lo que se sabía antes de su primer
saque: actas desglosadas de jornadas ``< t``, cuotas de cierre de ESE partido
(football-data para J≤11, ``odds_snapshots`` para J12), precio del último día
guardado antes de la jornada y el histórico de temporadas pasadas.

El motor que se evalúa es el de producción (``compute_expected_opta_points_v2``),
no una copia: los candidatos se aplican con parches temporales sobre sus
constantes o sobre sus entradas (p_titular, λ, P(portería a cero)).

Para cada candidato: MAE, ΔMAE frente a la base en las MISMAS filas, IC 95 % por
bootstrap pareado por bloques (jugador y partido, 10 000 remuestreos),
Wilcoxon de los |e| y Diebold-Mariano con error estándar por partido.

    python scripts/ablacion_xp.py                 # tabla completa
    python scripts/ablacion_xp.py --solo-base     # solo la base y el diagnóstico
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from scipy import stats as sstats

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.cache import cache_root  # noqa: E402
from toolbox.engine import p_titular_model as ptm  # noqa: E402
from toolbox.engine import xp2  # noqa: E402
from toolbox.engine.xp_calculator import FantasyXPEngine, PartidoHistorico, canonical_slot  # noqa: E402
from toolbox.matching import normalize_club  # noqa: E402
from toolbox.opta_points_v2 import compute_expected_opta_points_v2  # noqa: E402
from toolbox.player_history import actas_en_cache  # noqa: E402
from toolbox.understat import (  # noqa: E402
    _dixon_coles_grid,
    invert_market_to_dixon_coles,
    parse_openfootball_matchdays,
)

FD_ALIAS = {
    "santander": "racing",
    "espanol": "espanyol",
    "la coruna": "deportivo",
    "sociedad": "real sociedad",
    "ath madrid": "atletico madrid",
    "ath bilbao": "athletic",
    "vallecano": "rayo",
}
B_BOOT = 10_000
SEED = 20261110


# --------------------------------------------------------------------------
# Datos
# --------------------------------------------------------------------------


def _club(nombre: Any) -> str:
    key = normalize_club(str(nombre or ""))
    return FD_ALIAS.get(key, key)


@dataclass
class Partido:
    club: str
    rival: str
    local: bool
    kickoff: str  # ISO UTC
    lam_f: float | None = None
    lam_c: float | None = None
    p_cs: float | None = None
    p_win: float | None = None


def _mercado(odds_1x2: tuple[float, float, float], ou: tuple[float, float] | None) -> tuple[float, float, float, float, float, float]:
    lh, la, rho = invert_market_to_dixon_coles(odds_1x2, ou)
    grid = _dixon_coles_grid(lh, la, rho, max_goals=10)
    p_home = float(np.sum(np.tril(grid, -1)))
    p_away = float(np.sum(np.triu(grid, 1)))
    cs_home = float(np.sum(grid[:, 0]))  # el visitante no marca
    cs_away = float(np.sum(grid[0, :]))
    return lh, la, cs_home, cs_away, p_home, p_away


def cargar_partidos(cache: Path) -> dict[tuple[str, int], Partido]:
    md = parse_openfootball_matchdays((cache / "laliga_2026_27.txt").read_text(encoding="utf-8"))
    out: dict[tuple[str, int], Partido] = {}

    def poner(home: str, away: str, jornada: int, kickoff: str, odds: tuple | None, ou: tuple | None) -> None:
        mk = None
        if odds and all(o and o > 1.0 for o in odds):
            mk = _mercado(odds, ou)
        out[(home, jornada)] = Partido(home, away, True, kickoff)
        out[(away, jornada)] = Partido(away, home, False, kickoff)
        if mk:
            lh, la, csh, csa, ph, pa = mk
            out[(home, jornada)].__dict__.update(lam_f=lh, lam_c=la, p_cs=csh, p_win=ph)
            out[(away, jornada)].__dict__.update(lam_f=la, lam_c=lh, p_cs=csa, p_win=pa)

    with open(cache / "football_data_raw_2627" / "SP1_2627.csv", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            home, away = _club(row["HomeTeam"]), _club(row["AwayTeam"])
            jornada = md.get((home, away))
            if jornada is None:
                continue
            dt = datetime.strptime(f"{row['Date']} {row['Time']}", "%d/%m/%Y %H:%M")
            kickoff = dt.strftime("%Y-%m-%dT%H:%M:00")  # hora de Madrid; solo se usa para ordenar

            def f(k: str) -> float | None:
                try:
                    return float(row[k])
                except (KeyError, ValueError):
                    return None

            odds = (f("AvgCH"), f("AvgCD"), f("AvgCA"))
            if not all(odds):
                odds = (f("AvgH"), f("AvgD"), f("AvgA"))
            ou = (f("AvgC>2.5"), f("AvgC<2.5"))
            poner(home, away, jornada, kickoff, odds, ou if all(ou) else None)

    conn = sqlite3.connect(cache / "responses.sqlite")
    try:
        filas = conn.execute(
            "select match_key, day, kickoff, odds_home, odds_draw, odds_away, odds_over25, odds_under25 "
            "from odds_snapshots order by day"
        ).fetchall()
    finally:
        conn.close()
    ultima: dict[str, tuple] = {}
    for mkey, day, kickoff, oh, od, oa, o25, u25 in filas:
        if day < kickoff[:10]:  # solo cuotas tomadas antes del día del partido
            ultima[mkey] = (kickoff, oh, od, oa, o25, u25)
        else:
            ultima.setdefault(mkey, (kickoff, oh, od, oa, o25, u25))
    for mkey, (kickoff, oh, od, oa, o25, u25) in ultima.items():
        home, away = (_club(x) for x in mkey.split("|"))
        jornada = md.get((home, away))
        if jornada is None or (home, jornada) in out:
            continue
        local = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(timezone.utc)
        poner(home, away, jornada, local.strftime("%Y-%m-%dT%H:%M:00"), (oh, od, oa), (o25, u25) if o25 and u25 else None)
    # Partidos sin cuotas: rival y localía del calendario.
    for (home, away), jornada in md.items():
        if (home, jornada) not in out:
            out[(home, jornada)] = Partido(home, away, True, "")
            out[(away, jornada)] = Partido(away, home, False, "")
    return out


def cargar_precios(cache: Path) -> dict[str, list[tuple[str, float]]]:
    conn = sqlite3.connect(cache / "responses.sqlite")
    try:
        filas = conn.execute("select player_id, day, market_value from price_snapshots where market_value > 0").fetchall()
    finally:
        conn.close()
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for pid, day, value in filas:
        out[str(pid)].append((day, float(value)))
    for v in out.values():
        v.sort()
    return out


def precio_antes(serie: list[tuple[str, float]], dia: str) -> tuple[float | None, bool]:
    """Último precio guardado antes de ``dia``. Si no hay, el primero (marca la fuga)."""
    previos = [v for d, v in serie if d < dia]
    if previos:
        return previos[-1], False
    return (serie[0][1], True) if serie else (None, False)


def cargar_senales(cache: Path) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(cache / "responses.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        filas = conn.execute(
            "select player_id, day, stored_at, p_titular_ff, p_titular_af, p_titular_final, p_titular_fuente, lineup_status "
            "from player_signal_log"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in filas:
        out[str(r["player_id"])].append(dict(r))
    return out


# --------------------------------------------------------------------------
# Filas del backtest
# --------------------------------------------------------------------------


@dataclass
class Fila:
    pid: str
    name: str
    slot: str
    pos: str
    club: str
    week: int
    actual: float
    minutes: float
    partido: Partido
    historial: list[dict[str, Any]]
    precio: float | None
    precio_fuga: bool
    gol_real: float
    ast_real: float
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def match_id(self) -> str:
        a, b = sorted((self.club, self.partido.rival))
        return f"{self.week}:{a}|{b}"


def construir_filas(test_weeks: Iterable[int], min_prior: int = 1) -> tuple[list[Fila], dict[str, dict[str, Any]], dict]:
    cache = cache_root()
    actas = actas_en_cache()
    partidos = cargar_partidos(cache)
    precios = cargar_precios(cache)
    primer_saque: dict[int, str] = {}
    for (_, j), p in partidos.items():
        if p.kickoff and (j not in primer_saque or p.kickoff < primer_saque[j]):
            primer_saque[j] = p.kickoff
    filas: list[Fila] = []
    for pid, entry in actas.items():
        weeks = {int(k): v for k, v in (entry.get("weeks") or {}).items()}
        desg = {int(k): v for k, v in (entry.get("desglose") or {}).items()}
        club = _club(entry.get("team"))
        for t in test_weeks:
            if t not in weeks:
                continue
            hist = [
                {"jornada": w, "puntos": float(weeks[w][0]), "minutos": float(weeks[w][1]), "desglose": desg[w]}
                for w in sorted(weeks)
                if w < t and w in desg
            ]
            if len(hist) < min_prior:
                continue
            partido = partidos.get((club, t))
            if partido is None:
                continue
            dia = (primer_saque.get(t) or "9999")[:10]
            precio, fuga = precio_antes(precios.get(pid, []), dia)
            d_t = desg.get(t) or {"puntos": {}}
            filas.append(
                Fila(
                    pid=pid,
                    name=str(entry.get("name") or pid),
                    slot=canonical_slot(entry.get("position") or "MC"),
                    pos=str(entry.get("position") or "MC"),
                    club=club,
                    week=t,
                    actual=float(weeks[t][0]),
                    minutes=float(weeks[t][1]),
                    partido=partido,
                    historial=hist,
                    precio=precio,
                    precio_fuga=fuga,
                    gol_real=float(d_t["puntos"].get("goal", 0.0)),
                    ast_real=float(d_t["puntos"].get("ast", 0.0)),
                )
            )
    return filas, actas, partidos


# --------------------------------------------------------------------------
# Predicción de producción con ganchos
# --------------------------------------------------------------------------


def p_titular_heuristica(fila: Fila, pesos: dict[str, float] | None = None) -> float:
    prior = [PartidoHistorico(puntos=h["puntos"], minutos=int(h["minutos"]), jornada=h["jornada"]) for h in fila.historial]
    if pesos is None:
        return FantasyXPEngine.prob_titular_heuristica(prior) or 0.5
    feats = ptm.features_from_minutes([h["minutos"] for h in fila.historial])
    if feats is None:
        return 0.5
    return round(min(0.95, max(0.05, ptm.predict(pesos, feats))), 4)


@dataclass
class Config:
    nombre: str
    p_titular: Callable[[Fila], float] | None = None
    usar_cuotas: bool = True
    usar_rival_posicional: bool = True
    parches: dict[str, Any] = field(default_factory=dict)  # constantes de xp2
    banquillo: Callable[[Fila, dict], float] | None = None  # sustituye (1-p)*F*rev
    post: Callable[[Fila, dict], float] | None = None  # transforma la predicción final
    sin_balon_parado: bool = False
    jugador_extra: Callable[[Fila], dict] | None = None


@contextlib.contextmanager
def parchear(mod: Any, valores: dict[str, Any]):
    viejos = {k: getattr(mod, k) for k in valores}
    try:
        for k, v in valores.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in viejos.items():
            setattr(mod, k, v)


ROLES_BALON_PARADO: dict[str, list[dict[str, str]]] = {}


def jugador(fila: Fila, cfg: Config, p_tit: float) -> dict[str, Any]:
    player: dict[str, Any] = {
        "name": fila.name,
        "position": fila.pos,
        "club": fila.club,
        "team": fila.club,
        "p_titular": p_tit,
        "market_value": fila.precio,
        "historial": fila.historial,
    }
    if cfg.usar_rival_posicional:
        player["rival"] = fila.partido.rival
    roles = ROLES_BALON_PARADO.get(fila.pid)
    if roles and not cfg.sin_balon_parado:
        player["af_set_pieces"] = roles
    if cfg.jugador_extra:
        player.update(cfg.jugador_extra(fila))
    return player


def predecir(fila: Fila, cfg: Config) -> dict[str, Any]:
    p_tit = cfg.p_titular(fila) if cfg.p_titular else p_titular_heuristica(fila)
    kwargs: dict[str, Any] = {"run_monte_carlo": False}
    if cfg.usar_cuotas and fila.partido.lam_f is not None:
        kwargs.update(lambda_own=fila.partido.lam_f, lambda_opp=fila.partido.lam_c, p_cs_own=fila.partido.p_cs)
    elif fila.partido.lam_f is None or not cfg.usar_cuotas:
        kwargs.update(lambda_own=1.32, lambda_opp=1.32)
    player = jugador(fila, cfg, p_tit)
    with parchear(xp2, cfg.parches):
        out = compute_expected_opta_points_v2(player, **kwargs)
        det = xp2.prediccion_xp2(
            player,
            prob_titular=out.get("p_start_eff", p_tit),
            lambda_favor=kwargs["lambda_own"],
            lambda_contra=kwargs["lambda_opp"],
            prob_porteria_cero=kwargs.get("p_cs_own"),
            ajuste_rival=0.0,
        )
    res = {
        "xp": float(out["expected_points"]),
        "cond": float(out.get("xp_condicional") or 0.0),
        "p": float(out.get("p_start_eff") or 0.0),
        "p_in": p_tit,
        "modelo": out.get("xp_modelo"),
        "desglose": out.get("xp_desglose") or {},
        "det": det,
    }
    if cfg.banquillo is not None and res["modelo"] == "2.0" and res["p"] > 0.01:
        res["xp"] = max(0.0, res["p"] * res["cond"] + (1.0 - res["p"]) * cfg.banquillo(fila, res))
    if cfg.post is not None:
        res["xp"] = cfg.post(fila, res)
    return res


# --------------------------------------------------------------------------
# Estadística
# --------------------------------------------------------------------------


def _cluster_boot(d: np.ndarray, grupos: list[str], rng: np.random.Generator, B: int = B_BOOT) -> tuple[float, float]:
    claves = sorted(set(grupos))
    idx = {k: i for i, k in enumerate(claves)}
    g = np.array([idx[k] for k in grupos])
    sumas = np.bincount(g, weights=d, minlength=len(claves))
    cuentas = np.bincount(g, minlength=len(claves)).astype(float)
    w = rng.multinomial(len(claves), np.full(len(claves), 1.0 / len(claves)), size=B).astype(float)
    medias = (w @ sumas) / (w @ cuentas)
    return float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))


def _dm(d: np.ndarray, grupos: list[str]) -> tuple[float, float]:
    """Diebold-Mariano con varianza robusta por partido (pérdida absoluta)."""
    n = len(d)
    mu = d.mean()
    acum: dict[str, float] = defaultdict(float)
    for x, gk in zip(d - mu, grupos):
        acum[gk] += x
    var = sum(v * v for v in acum.values()) / n**2
    G = len(acum)
    var *= G / max(1, G - 1)
    if var <= 0:
        return 0.0, 1.0
    z = mu / math.sqrt(var)
    return z, 2 * (1 - sstats.norm.cdf(abs(z)))


@dataclass
class Resultado:
    nombre: str
    n: int
    mae: float
    delta: float
    ic_jug: tuple[float, float]
    ic_part: tuple[float, float]
    p_wilcoxon: float
    z_dm: float
    p_dm: float
    r: float
    por_semana: dict[int, float]
    nota: str = ""

    @property
    def veredicto(self) -> str:
        if self.delta < 0 and self.ic_jug[1] < 0 and self.ic_part[1] < 0 and self.p_dm < 0.05:
            return "ENTRA"
        return "DESCARTADO"


def comparar(nombre: str, filas: list[Fila], pred_base: np.ndarray, pred_new: np.ndarray, nota: str = "", seed: int = SEED) -> Resultado:
    y = np.array([f.actual for f in filas])
    e_b = np.abs(pred_base - y)
    e_n = np.abs(pred_new - y)
    d = e_n - e_b
    rng = np.random.default_rng(seed)
    ic_j = _cluster_boot(d, [f.pid for f in filas], rng)
    ic_p = _cluster_boot(d, [f.match_id for f in filas], rng)
    nz = d[np.abs(d) > 1e-9]
    p_w = float(sstats.wilcoxon(nz).pvalue) if len(nz) >= 10 else 1.0
    z, p_dm = _dm(d, [f.match_id for f in filas])
    r = float(np.corrcoef(pred_new, y)[0, 1]) if np.std(pred_new) > 0 else float("nan")
    semanas: dict[int, float] = {}
    for w in sorted({f.week for f in filas}):
        m = np.array([f.week == w for f in filas])
        semanas[w] = float(d[m].mean())
    return Resultado(nombre, len(filas), float(e_n.mean()), float(d.mean()), ic_j, ic_p, p_w, z, p_dm, r, semanas, nota)


def imprimir(res: list[Resultado], base_mae: float) -> None:
    print(f"\n{'Componente':<46}{'n':>5}{'MAE':>7}{'ΔMAE':>8}  {'IC95 jugador':>17}  {'IC95 partido':>17}{'Wilc p':>8}{'DM p':>7}{'r':>6}  Veredicto")
    print(f"{'(base de producción)':<46}{'':>5}{base_mae:7.3f}")
    for r in res:
        print(
            f"{r.nombre:<46}{r.n:5d}{r.mae:7.3f}{r.delta:+8.3f}  [{r.ic_jug[0]:+.3f},{r.ic_jug[1]:+.3f}]  "
            f"[{r.ic_part[0]:+.3f},{r.ic_part[1]:+.3f}]{r.p_wilcoxon:8.3f}{r.p_dm:7.3f}{r.r:6.3f}  {r.veredicto}"
            + (f"   ({r.nota})" if r.nota else "")
        )
        print("    Δ por jornada: " + "  ".join(f"J{w} {v:+.3f}" for w, v in r.por_semana.items()))


def mae(pred: np.ndarray, filas: list[Fila]) -> float:
    return float(np.mean(np.abs(pred - np.array([f.actual for f in filas]))))


def correr(filas: list[Fila], cfg: Config) -> tuple[np.ndarray, list[dict[str, Any]]]:
    salidas = [predecir(f, cfg) for f in filas]
    return np.array([s["xp"] for s in salidas]), salidas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--test-weeks", type=int, nargs="+", default=[8, 9, 10, 11, 12])
    parser.add_argument("--min-prior", type=int, default=1)
    parser.add_argument("--solo-base", action="store_true")
    args = parser.parse_args()

    filas, _, _ = construir_filas(args.test_weeks, args.min_prior)
    base, _ = correr(filas, Config("base"))
    print(f"Filas {len(filas)}  MAE base {mae(base, filas):.3f}")
    for w in args.test_weeks:
        sub = [i for i, f in enumerate(filas) if f.week == w]
        if sub:
            print(f"  J{w}: n={len(sub)} MAE {np.mean([abs(base[i] - filas[i].actual) for i in sub]):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

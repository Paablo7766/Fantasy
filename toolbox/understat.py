"""Understat: xG/xA de jugador, calendario y dificultad de rival (FDR).

La liga actual vive en ``getLeagueData/La_liga/{season}``. El cuerpo es JSON
aunque el content-type diga ``text/javascript``.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy.optimize import brentq, minimize
from scipy.stats import poisson

from toolbox.matching import canonical_position, normalize_club, normalize_name
from toolbox.net import ExternalClient, ExternalHttpError

UNDERSTAT_LEAGUE = "La_liga"
UNDERSTAT_DATA_URL = "https://understat.com/getLeagueData/{league}/{season}"

# FDR 1 (difícil) … 5 (fácil) según xGA media del rival vs media de la liga.
FDR_POINTS_MULT = {1: 0.8, 2: 0.9, 3: 1.0, 4: 1.1, 5: 1.2}
HOME_POINTS_MULT = 1.05


@dataclass
class TeamStrength:
    team_id: str
    title: str
    avg_xg: float
    avg_xga: float
    matches: int


@dataclass(frozen=True)
class TeamRollingWindow:
    """Ventana móvil de 5 partidos (índice 0 = más reciente)."""

    last5_xg: list[float]
    last5_opp_xga: list[float]
    last5_xga: list[float]
    last5_opp_xg: list[float]

    @property
    def sample_size(self) -> int:
        return len(self.last5_xg)


ROLLING_MATCH_WINDOW = 5


@dataclass
class FixtureInfo:
    opponent: str
    opponent_id: str | None
    home: bool
    kickoff: str | None
    fdr: int
    opponent_xga: float | None
    opponent_xg: float | None


def understat_season() -> str:
    raw = os.getenv("UNDERSTAT_SEASON", "").strip()
    if raw.isdigit():
        return raw
    return str(datetime.now(timezone.utc).year)


def understat_data_url(season: str | None = None) -> str:
    return UNDERSTAT_DATA_URL.format(league=UNDERSTAT_LEAGUE, season=season or understat_season())


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", ".")
        if not text or text in {"-", "—"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if number != number:
        return None
    return number


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def parse_understat_payload(payload: Any) -> tuple[list[dict[str, Any]], dict[str, TeamStrength], list[dict[str, Any]]]:
    """Devuelve (jugadores FormLine-ready, fuerzas por club, fechas crudas)."""
    if not isinstance(payload, dict):
        return [], {}, []
    players_out: list[dict[str, Any]] = []
    for row in payload.get("players") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("player_name")
        if not isinstance(name, str) or not name.strip():
            continue
        games = _as_float(row.get("games")) or 0.0
        minutes = _as_float(row.get("time"))
        starts = _as_int(row.get("games"))
        minutes_pct = None
        if minutes is not None and games > 0:
            # % de minutos sobre 90' × partidos jugados.
            minutes_pct = round(min(1.0, float(minutes) / (90.0 * games)), 4)
        xg = _as_float(row.get("xG") or row.get("npxG"))
        xa = _as_float(row.get("xA"))
        players_out.append(
            {
                "name": name.strip(),
                "source": "understat",
                "club": row.get("team_title") if isinstance(row.get("team_title"), str) else None,
                "position": canonical_position(str(row.get("position") or "")),
                "external_id": str(row["id"]) if row.get("id") is not None else None,
                "xg": xg,
                "xa": xa,
                "key_passes": _as_float(row.get("key_passes")),
                "minutes": minutes,
                "starts": starts,
                "minutes_pct": minutes_pct,
            }
        )

    strengths: dict[str, TeamStrength] = {}
    teams = payload.get("teams") if isinstance(payload.get("teams"), dict) else {}
    for team_id, team in teams.items():
        if not isinstance(team, dict):
            continue
        title = team.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        history = team.get("history") if isinstance(team.get("history"), list) else []
        xg_vals = [_as_float(item.get("xG")) for item in history if isinstance(item, dict)]
        xga_vals = [_as_float(item.get("xGA")) for item in history if isinstance(item, dict)]
        xg_ok = [value for value in xg_vals if value is not None]
        xga_ok = [value for value in xga_vals if value is not None]
        if not xga_ok:
            continue
        strength = TeamStrength(
            team_id=str(team_id),
            title=title.strip(),
            avg_xg=sum(xg_ok) / len(xg_ok) if xg_ok else 0.0,
            avg_xga=sum(xga_ok) / len(xga_ok),
            matches=len(xga_ok),
        )
        strengths[normalize_club(title)] = strength
        strengths[normalize_name(title)] = strength

    dates = [row for row in (payload.get("dates") or []) if isinstance(row, dict)]
    return players_out, strengths, dates


def rolling_window_from_history(
    history: list[dict[str, Any]],
    *,
    window: int = ROLLING_MATCH_WINDOW,
) -> TeamRollingWindow:
    """Extrae xG/xGA recientes del histórico Understat (más reciente primero)."""
    rows = [row for row in history if isinstance(row, dict)]
    if not rows:
        return TeamRollingWindow([], [], [], [])
    recent = list(reversed(rows[-window:]))
    xg: list[float] = []
    xga: list[float] = []
    for row in recent:
        gx = _as_float(row.get("xG"))
        ga = _as_float(row.get("xGA"))
        if gx is not None:
            xg.append(gx)
        if ga is not None:
            xga.append(ga)
    # En cada partido, lo generado por el rival ≈ xGA propio; lo concedido ≈ xG propio.
    opp_xga = list(xg)
    opp_xg = list(xga)
    return TeamRollingWindow(
        last5_xg=xg,
        last5_opp_xga=opp_xga,
        last5_xga=xga,
        last5_opp_xg=opp_xg,
    )


def _prepend_match_to_rolling(
    rolling: TeamRollingWindow,
    *,
    xg: float,
    xga: float,
    window: int = ROLLING_MATCH_WINDOW,
) -> TeamRollingWindow:
    xg_list = [xg, *rolling.last5_xg][:window]
    xga_list = [xga, *rolling.last5_xga][:window]
    return TeamRollingWindow(
        last5_xg=xg_list,
        last5_opp_xga=list(xg_list),
        last5_xga=xga_list,
        last5_opp_xg=list(xga_list),
    )


def team_rolling_windows_from_payload(payload: Any) -> dict[str, TeamRollingWindow]:
    """Mapa por club normalizado (y team_id) con ventanas rolling reales."""
    if not isinstance(payload, dict):
        return {}
    windows: dict[str, TeamRollingWindow] = {}
    teams = payload.get("teams") if isinstance(payload.get("teams"), dict) else {}
    for team_id, team in teams.items():
        if not isinstance(team, dict):
            continue
        title = team.get("title")
        history = team.get("history") if isinstance(team.get("history"), list) else []
        if not isinstance(title, str) or not title.strip():
            continue
        rolling = rolling_window_from_history(history)
        if rolling.sample_size == 0:
            continue
        key = normalize_club(title)
        windows[key] = rolling
        windows[normalize_name(title)] = rolling
        windows[str(team_id)] = rolling

    for row in payload.get("dates") or []:
        if not isinstance(row, dict):
            continue
        if row.get("isResult") not in (True, "true", "True", 1, "1"):
            continue
        home = row.get("h") if isinstance(row.get("h"), dict) else {}
        away = row.get("a") if isinstance(row.get("a"), dict) else {}
        home_title = home.get("title") if isinstance(home.get("title"), str) else None
        away_title = away.get("title") if isinstance(away.get("title"), str) else None
        hx = _as_float(home.get("xG"))
        ax = _as_float(away.get("xG"))
        if hx is None or ax is None or not home_title or not away_title:
            continue
        home_key = normalize_club(home_title)
        away_key = normalize_club(away_title)
        windows[home_key] = _prepend_match_to_rolling(windows.get(home_key, TeamRollingWindow([], [], [], [])), xg=hx, xga=ax)
        windows[away_key] = _prepend_match_to_rolling(windows.get(away_key, TeamRollingWindow([], [], [], [])), xg=ax, xga=hx)
        if home.get("id") is not None:
            windows[str(home["id"])] = windows[home_key]
        if away.get("id") is not None:
            windows[str(away["id"])] = windows[away_key]
    return windows


def stat_lambdas_for_fixture(
    *,
    home_team: TeamStrength | None,
    away_team: TeamStrength | None,
    home_rolling: TeamRollingWindow | None,
    away_rolling: TeamRollingWindow | None,
    league_avg_xg: float,
) -> tuple[float, float]:
    """λ estadísticos home/away con ventanas rolling reales (sin listas vacías)."""

    def _season(team: TeamStrength | None) -> tuple[float, float]:
        if team is None:
            return league_avg_xg, league_avg_xg
        return team.avg_xg, team.avg_xga

    sh_xg, sh_xga = _season(home_team)
    sa_xg, sa_xga = _season(away_team)
    hr = home_rolling or TeamRollingWindow([], [], [], [])
    ar = away_rolling or TeamRollingWindow([], [], [], [])
    if hr.sample_size == 0:
        hr = TeamRollingWindow([sh_xg], [sh_xg], [sh_xga], [sh_xga])
    if ar.sample_size == 0:
        ar = TeamRollingWindow([sa_xg], [sa_xg], [sa_xga], [sa_xga])
    return compute_rolling_xg_rates(
        hr.last5_xg,
        hr.last5_opp_xga,
        hr.last5_xga,
        hr.last5_opp_xg,
        ar.last5_xg,
        ar.last5_opp_xga,
        ar.last5_xga,
        ar.last5_opp_xg,
        sh_xg,
        sh_xga,
        sa_xg,
        sa_xga,
        league_avg_xg=league_avg_xg,
    )


def resolve_rolling_window(
    team: TeamStrength | None,
    rolling_map: dict[str, TeamRollingWindow] | None,
    club_key: str | None,
) -> TeamRollingWindow | None:
    if not rolling_map or not club_key:
        return None
    direct = rolling_map.get(club_key)
    if direct is not None and direct.sample_size > 0:
        return direct
    if team is not None:
        by_id = rolling_map.get(team.team_id)
        if by_id is not None and by_id.sample_size > 0:
            return by_id
        titled = rolling_map.get(normalize_club(team.title)) or rolling_map.get(normalize_name(team.title))
        if titled is not None and titled.sample_size > 0:
            return titled
    return None


def fdr_from_opponent_xga(opponent_xga: float, league_avg_xga: float) -> int:
    if league_avg_xga <= 0:
        return 3
    ratio = opponent_xga / league_avg_xga
    if ratio >= 1.25:
        return 5
    if ratio >= 1.1:
        return 4
    if ratio >= 0.9:
        return 3
    if ratio >= 0.75:
        return 2
    return 1


def _parse_kickoff(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value.strip(), fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def next_fixtures(
    dates: list[dict[str, Any]],
    strengths: dict[str, TeamStrength],
    *,
    now: datetime | None = None,
) -> dict[str, FixtureInfo]:
    """Próximo partido por club normalizado, con FDR según xGA del rival."""
    moment = now or datetime.now(timezone.utc)
    league_vals = [item.avg_xga for item in {id(v): v for v in strengths.values()}.values()]
    league_avg = sum(league_vals) / len(league_vals) if league_vals else 1.0
    by_id = {item.team_id: item for item in {id(v): v for v in strengths.values()}.values()}

    upcoming: list[tuple[datetime, dict[str, Any]]] = []
    for row in dates:
        if row.get("isResult") in (True, "true", "True", 1, "1"):
            continue
        kickoff = _parse_kickoff(row.get("datetime"))
        if kickoff is None or kickoff < moment:
            continue
        upcoming.append((kickoff, row))
    upcoming.sort(key=lambda item: item[0])

    fixtures: dict[str, FixtureInfo] = {}
    for kickoff, row in upcoming:
        home = row.get("h") if isinstance(row.get("h"), dict) else {}
        away = row.get("a") if isinstance(row.get("a"), dict) else {}
        for side, rival, is_home in ((home, away, True), (away, home, False)):
            title = side.get("title") if isinstance(side.get("title"), str) else None
            if not title:
                continue
            key = normalize_club(title)
            if key in fixtures:
                continue
            rival_title = rival.get("title") if isinstance(rival.get("title"), str) else None
            rival_id = str(rival["id"]) if rival.get("id") is not None else None
            strength = None
            if rival_id and rival_id in by_id:
                strength = by_id[rival_id]
            elif rival_title:
                strength = strengths.get(normalize_club(rival_title)) or strengths.get(normalize_name(rival_title))
            opponent_xga = strength.avg_xga if strength else None
            opponent_xg = strength.avg_xg if strength else None
            fdr = fdr_from_opponent_xga(opponent_xga, league_avg) if opponent_xga is not None else 3
            fixtures[key] = FixtureInfo(
                opponent=rival_title or "?",
                opponent_id=rival_id,
                home=is_home,
                kickoff=kickoff.astimezone(timezone.utc).isoformat(),
                fdr=fdr,
                opponent_xga=round(opponent_xga, 4) if opponent_xga is not None else None,
                opponent_xg=round(opponent_xg, 4) if opponent_xg is not None else None,
            )
    return fixtures


def load_understat(
    client: ExternalClient,
    *,
    ttl: float,
    fresh: bool,
    season: str | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, FixtureInfo],
    dict[str, TeamStrength],
    dict[str, TeamRollingWindow],
    dict[str, Any],
]:
    """Carga jugadores + fixtures + fuerzas + rolling 5. El status dict sirve para ``sources``."""
    url = understat_data_url(season)
    empty_rolling: dict[str, TeamRollingWindow] = {}
    try:
        body, cached = client.get_text(url, ttl=ttl, fresh=fresh)
    except ExternalHttpError as exc:
        return [], {}, {}, empty_rolling, {"ok": False, "count": 0, "error": str(exc), "from_cache": False, "url": url}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        # A veces Understat envuelve el JSON; se intenta el primer objeto.
        match = re.search(r"\{.*\}", body, flags=re.S)
        if match is None:
            return [], {}, {}, empty_rolling, {
                "ok": False,
                "count": 0,
                "error": "Understat no devolvió JSON.",
                "from_cache": cached,
                "url": url,
            }
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return [], {}, {}, empty_rolling, {
                "ok": False,
                "count": 0,
                "error": "Understat no devolvió JSON.",
                "from_cache": cached,
                "url": url,
            }
    players, strengths, dates = parse_understat_payload(payload)
    fixtures = next_fixtures(dates, strengths)
    rolling = team_rolling_windows_from_payload(payload)
    status = {
        "ok": bool(players),
        "count": len(players),
        "error": None if players else "Understat sin jugadores.",
        "from_cache": cached,
        "url": url,
        "fixtures": len(fixtures),
        "teams": len({id(v): v for v in strengths.values()}),
        "rolling_teams": len({id(v): v for v in rolling.values()}),
    }
    return players, fixtures, strengths, rolling, status


def points_multiplier(*, fdr: int | None, home: bool | None) -> float:
    """Mult. de fixture sobre E[pts]. ``home=None`` no suma ventaja local.

    Con ``is True`` el flag de local solo contaba si llegaba como ``True``
    exacto (un ``1`` lo perdía); ahora un ``False`` explícito es lo único que
    lo descarta.
    """
    mult = 1.0
    if isinstance(fdr, int) and fdr in FDR_POINTS_MULT:
        mult *= FDR_POINTS_MULT[fdr]
    if home is not False and home is not None:
        mult *= HOME_POINTS_MULT
    return round(mult, 4)


@dataclass
class MatchMarketProjection:
    lambda_home: float
    lambda_away: float
    rho_dc: float
    p_home_win: float
    p_draw: float
    p_away_win: float
    p_cs_home: float
    p_cs_away: float
    recommendation_pct_home: int
    recommendation_pct_away: int


def devig_shin_3way(odds_1x2: tuple[float, float, float]) -> tuple[np.ndarray, float]:
    """Limpia overround 1X2 con el modelo de Shin (1993)."""
    odds = np.asarray(odds_1x2, dtype=np.float64)
    if np.any(odds <= 1.0):
        raise ValueError("Las cuotas decimales deben ser estrictamente mayores que 1.0.")

    b = 1.0 / odds
    booksum = float(np.sum(b))
    if booksum <= 1.0 + 1e-9:
        return b / booksum, 0.0

    def shin_probs(z: float) -> np.ndarray:
        return (np.sqrt(z**2 + 4.0 * (1.0 - z) * (b**2) / booksum) - z) / (2.0 * (1.0 - z))

    def objective(z: float) -> float:
        return float(np.sum(shin_probs(z)) - 1.0)

    z_upper = min(0.49, (booksum - 1.0) / (len(odds) - 1.0) - 1e-9)
    try:
        z_star = float(brentq(objective, 1e-12, max(1e-6, z_upper), xtol=1e-12))
        p_clean = shin_probs(z_star)
    except Exception:
        z_star = 0.0
        p_clean = b / booksum

    p_clean /= np.sum(p_clean)
    return p_clean, z_star


def devig_power_2way(odds_pair: tuple[float, float]) -> np.ndarray:
    """De-vig binario (O/U 2.5, BTTS) con Power Method."""
    odds = np.asarray(odds_pair, dtype=np.float64)
    b = 1.0 / odds
    if np.sum(b) <= 1.0 + 1e-9:
        return b / np.sum(b)

    def objective(k: float) -> float:
        return float(np.sum(np.power(b, k)) - 1.0)

    try:
        k_star = float(brentq(objective, 1.0, 5.0, xtol=1e-12))
        p_clean = np.power(b, k_star)
    except Exception:
        p_clean = b / np.sum(b)

    return p_clean / np.sum(p_clean)


def _dixon_coles_grid(lh: float, la: float, rho: float, max_goals: int = 10) -> np.ndarray:
    goals = np.arange(max_goals)
    pmf_h = poisson.pmf(goals, lh)
    pmf_a = poisson.pmf(goals, la)
    grid = np.outer(pmf_h, pmf_a)

    grid[0, 0] *= 1.0 - lh * la * rho
    grid[0, 1] *= 1.0 + lh * rho
    grid[1, 0] *= 1.0 + la * rho
    grid[1, 1] *= 1.0 - rho

    grid = np.clip(grid, 0.0, None)
    total = np.sum(grid)
    return grid / total if total > 0 else grid


def invert_market_to_dixon_coles(
    odds_1x2: tuple[float, float, float],
    odds_ou25: tuple[float, float] | None = None,
    odds_btts: tuple[float, float] | None = None,
) -> tuple[float, float, float]:
    """Invierte probabilidades limpias → (lambda_home, lambda_away, rho_dc)."""
    p_1x2, _ = devig_shin_3way(odds_1x2)
    p_h_target, p_d_target, p_a_target = float(p_1x2[0]), float(p_1x2[1]), float(p_1x2[2])

    p_o25_target = float(devig_power_2way(odds_ou25)[0]) if odds_ou25 else None
    p_btts_target = float(devig_power_2way(odds_btts)[0]) if odds_btts else None

    idx_grid = np.add.outer(np.arange(10), np.arange(10))
    over25_mask = idx_grid >= 3

    def loss_fn(params: np.ndarray) -> float:
        lh, la, rho = float(params[0]), float(params[1]), float(params[2])
        if 1.0 - lh * la * rho <= 1e-4 or 1.0 + lh * rho <= 1e-4 or 1.0 + la * rho <= 1e-4:
            return 1e4

        grid = _dixon_coles_grid(lh, la, rho, max_goals=10)
        ph = float(np.sum(np.tril(grid, -1)))
        pd = float(np.sum(np.diag(grid)))
        pa = float(np.sum(np.triu(grid, 1)))

        err = 1.5 * ((ph - p_h_target) ** 2 + (pd - p_d_target) ** 2 + (pa - p_a_target) ** 2)
        if p_o25_target is not None:
            po25 = float(np.sum(grid[over25_mask]))
            err += 2.0 * ((po25 - p_o25_target) ** 2)
        if p_btts_target is not None:
            pbtts = float(np.sum(grid[1:, 1:]))
            err += 1.2 * ((pbtts - p_btts_target) ** 2)
        else:
            err += 0.05 * ((rho - (-0.08)) ** 2)
        return err

    res = minimize(
        loss_fn,
        x0=np.array([1.45, 1.10, -0.06]),
        bounds=[(0.15, 4.80), (0.15, 4.80), (-0.22, 0.12)],
        method="L-BFGS-B",
    )
    return float(res.x[0]), float(res.x[1]), float(res.x[2])


def compute_rolling_xg_rates(
    home_last5_xg: list[float],
    home_last5_opp_xga_avg: list[float],
    home_last5_xga: list[float],
    home_last5_opp_xg_avg: list[float],
    away_last5_xg: list[float],
    away_last5_opp_xga_avg: list[float],
    away_last5_xga: list[float],
    away_last5_opp_xg_avg: list[float],
    season_home_xg: float,
    season_home_xga: float,
    season_away_xg: float,
    season_away_xga: float,
    league_avg_xg: float = 1.32,
    xi_decay: float = 0.25,
) -> tuple[float, float]:
    """λ estadísticos: EWMA 5 partidos (60%) + temporada (40%), ajustados por rival."""

    def _ewma_adjusted(metric_seq: list[float], opp_baseline_seq: list[float], fallback: float) -> float:
        if not metric_seq or len(metric_seq) != len(opp_baseline_seq):
            return fallback
        n = len(metric_seq)
        weights = np.exp(-xi_decay * np.arange(n))
        adj_vals = [m * (league_avg_xg / max(0.5, opp_b)) for m, opp_b in zip(metric_seq, opp_baseline_seq)]
        return float(np.sum(weights * np.asarray(adj_vals)) / np.sum(weights))

    h_xg_5 = _ewma_adjusted(home_last5_xg, home_last5_opp_xga_avg, season_home_xg)
    h_xga_5 = _ewma_adjusted(home_last5_xga, home_last5_opp_xg_avg, season_home_xga)
    a_xg_5 = _ewma_adjusted(away_last5_xg, away_last5_opp_xga_avg, season_away_xg)
    a_xga_5 = _ewma_adjusted(away_last5_xga, away_last5_opp_xg_avg, season_away_xga)

    h_atk = 0.60 * h_xg_5 + 0.40 * season_home_xg
    h_def = 0.60 * h_xga_5 + 0.40 * season_home_xga
    a_atk = 0.60 * a_xg_5 + 0.40 * season_away_xg
    a_def = 0.60 * a_xga_5 + 0.40 * season_away_xga

    lambda_stat_h = 1.08 * (h_atk * a_def) / max(0.6, league_avg_xg)
    lambda_stat_a = 0.95 * (a_atk * h_def) / max(0.6, league_avg_xg)
    return float(np.clip(lambda_stat_h, 0.2, 4.5)), float(np.clip(lambda_stat_a, 0.2, 4.5))


def build_hybrid_match_projection(
    lambda_stat_h: float,
    lambda_stat_a: float,
    odds_1x2: tuple[float, float, float] | None = None,
    odds_ou25: tuple[float, float] | None = None,
    odds_btts: tuple[float, float] | None = None,
    hours_to_kickoff: float = 48.0,
) -> MatchMarketProjection:
    """Fusión log-lineal entre λ de mercado (Dixon-Coles) y λ rolling xG."""
    if odds_1x2 is not None:
        lh_mkt, la_mkt, rho_dc = invert_market_to_dixon_coles(odds_1x2, odds_ou25, odds_btts)
        w_mkt = 0.55 + (0.82 - 0.55) * math.exp(-max(0.0, hours_to_kickoff) / 72.0)
        lh_final = math.exp(w_mkt * math.log(lh_mkt) + (1.0 - w_mkt) * math.log(lambda_stat_h))
        la_final = math.exp(w_mkt * math.log(la_mkt) + (1.0 - w_mkt) * math.log(lambda_stat_a))
    else:
        lh_final, la_final, rho_dc = lambda_stat_h, lambda_stat_a, -0.08

    grid = _dixon_coles_grid(lh_final, la_final, rho_dc, max_goals=10)
    p_home = float(np.sum(np.tril(grid, -1)))
    p_draw = float(np.sum(np.diag(grid)))
    p_away = float(np.sum(np.triu(grid, 1)))

    p_cs_home = math.exp(-la_final)
    p_cs_away = math.exp(-lh_final)

    goal_diff_h = lh_final - la_final
    rec_h = int(round(100.0 * (p_home + 0.45 * p_draw) + np.clip(4.0 * goal_diff_h, -10.0, 15.0)))
    rec_a = int(round(100.0 * (p_away + 0.45 * p_draw) + np.clip(-4.0 * goal_diff_h, -10.0, 15.0)))

    return MatchMarketProjection(
        lambda_home=lh_final,
        lambda_away=la_final,
        rho_dc=rho_dc,
        p_home_win=p_home,
        p_draw=p_draw,
        p_away_win=p_away,
        p_cs_home=p_cs_home,
        p_cs_away=p_cs_away,
        recommendation_pct_home=int(np.clip(rec_h, 1, 99)),
        recommendation_pct_away=int(np.clip(rec_a, 1, 99)),
    )

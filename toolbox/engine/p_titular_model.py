"""Probabilidad de titular: modelo logístico que se reajusta con los datos.

Dos señales por jugador, calculadas solo con jornadas ya jugadas:

* ``season``: fracción de partidos de titular (>= ``STARTER_MINUTES``).
* ``minutes``: minutos medios de las tres últimas jornadas, sobre 90'.

Los pesos viven en ``<cache>/p_titular_pesos.json``. Si el archivo no existe
o está roto, el motor usa ``DEFAULT_WEIGHTS``. Nada aquí toca red.

El reajuste (:func:`evaluate_refit`) solo adopta pesos nuevos si, medidos en
jornadas que el ajuste no vio, puntúan mejor que los vigentes; y mueve los
pesos a medias (``STEP``) y con un tope por coeficiente para que una racha rara
no desplace el modelo de golpe.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from toolbox.cache import cache_root

STARTER_MINUTES = 45
RECENT_GAMES = 3

DEFAULT_WEIGHTS: dict[str, float] = {"bias": -0.747, "season": 0.375, "minutes": 2.311}
_KEYS = ("bias", "season", "minutes")

# Salvaguardas del reajuste.
MIN_CASES = 300
MIN_WEEKS = 3
MIN_PER_CLASS = 30
HALF_LIFE_WEEKS = 6.0
L2 = 1.0
STEP = 0.5
MAX_MOVE = 0.75
MIN_GAIN = 0.0005
MAX_CV_WEEKS = 6
MIN_CV_WEEK_ROWS = 30
MAX_COEF = 10.0
HISTORY_KEEP = 25

_WEIGHTS_FILE = "p_titular_pesos.json"
_CACHE_TTL = 5.0
_cached: tuple[str, float, float, dict[str, float]] | None = None


def weights_path() -> Path:
    override = os.getenv("FANTASY_P_TITULAR_WEIGHTS", "").strip()
    return Path(override) if override else cache_root() / _WEIGHTS_FILE


def features_from_minutes(minutes: Sequence[float]) -> tuple[float, float] | None:
    """``(season, minutes)`` a partir de los minutos por jornada, en orden."""
    if not minutes:
        return None
    season = sum(1.0 for m in minutes if m >= STARTER_MINUTES) / len(minutes)
    recent = minutes[-RECENT_GAMES:]
    recent_share = sum(min(max(float(m), 0.0), 90.0) / 90.0 for m in recent) / len(recent)
    return season, recent_share


def predict(weights: dict[str, float], features: Sequence[float]) -> float:
    z = weights["bias"] + weights["season"] * features[0] + weights["minutes"] * features[1]
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def _valid(weights: Any) -> dict[str, float] | None:
    if not isinstance(weights, dict):
        return None
    out: dict[str, float] = {}
    for key in _KEYS:
        value = weights.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        if abs(value) > MAX_COEF:
            return None
        out[key] = float(value)
    return out


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = path or weights_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def current_weights() -> dict[str, float]:
    """Pesos vigentes; relee el archivo como mucho cada pocos segundos."""
    global _cached
    path = weights_path()
    now = time.monotonic()
    if _cached is not None and _cached[0] == str(path) and now - _cached[1] < _CACHE_TTL:
        return _cached[3]
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    if _cached is not None and _cached[0] == str(path) and _cached[2] == mtime:
        _cached = (str(path), now, mtime, _cached[3])
        return _cached[3]
    weights = _valid(load_state(path).get("weights")) or dict(DEFAULT_WEIGHTS)
    _cached = (str(path), now, mtime, weights)
    return weights


def reset_cache() -> None:
    global _cached
    _cached = None


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or weights_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    reset_cache()


# --------------------------------------------------------------------------
# Ajuste
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    week: int
    features: tuple[float, float]
    label: float


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, n):
            factor = a[r][col] / a[col][col]
            for c in range(col, n + 1):
                a[r][c] -= factor * a[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (a[i][n] - sum(a[i][j] * x[j] for j in range(i + 1, n))) / a[i][i]
    return x


def fit_logistic(
    rows: Sequence[Row],
    sample_weights: Sequence[float] | None = None,
    *,
    l2: float = L2,
    iterations: int = 40,
) -> dict[str, float] | None:
    """Newton–Raphson con ridge en los coeficientes (no en el sesgo)."""
    if not rows:
        return None
    sw = list(sample_weights) if sample_weights is not None else [1.0] * len(rows)
    total = sum(sw)
    if total <= 0:
        return None
    sw = [w * len(rows) / total for w in sw]
    beta = [0.0, 0.0, 0.0]
    for _ in range(iterations):
        grad = [0.0, 0.0, 0.0]
        hess = [[0.0] * 3 for _ in range(3)]
        for row, w in zip(rows, sw):
            x = (1.0, row.features[0], row.features[1])
            z = sum(b * v for b, v in zip(beta, x))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = w * (p - row.label)
            curv = w * p * (1.0 - p)
            for i in range(3):
                grad[i] += err * x[i]
                for j in range(3):
                    hess[i][j] += curv * x[i] * x[j]
        for i in (1, 2):
            grad[i] += l2 * beta[i]
            hess[i][i] += l2
        step = _solve(hess, grad)
        if step is None:
            return None
        beta = [b - s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return {"bias": beta[0], "season": beta[1], "minutes": beta[2]}


def brier(rows: Sequence[Row], weights: dict[str, float]) -> float:
    return sum((predict(weights, r.features) - r.label) ** 2 for r in rows) / len(rows)


def _damp(current: dict[str, float], candidate: dict[str, float]) -> dict[str, float]:
    out = {}
    for key in _KEYS:
        move = STEP * (candidate[key] - current[key])
        move = max(-MAX_MOVE, min(MAX_MOVE, move))
        out[key] = current[key] + move
    return out


def _recency(rows: Sequence[Row], newest: int) -> list[float]:
    return [0.5 ** ((newest - r.week) / HALF_LIFE_WEEKS) for r in rows]


def evaluate_refit(rows: Sequence[Row], current: dict[str, float]) -> dict[str, Any]:
    """Decide si hay pesos nuevos y cuáles. No escribe nada.

    Devuelve ``{"accepted": bool, "reason": str, ...}``. El candidato se mide
    dejando fuera cada una de las últimas jornadas (ajuste con el resto,
    suavizado hacia los pesos vigentes) frente a los pesos vigentes en esas
    mismas filas.
    """
    n = len(rows)
    weeks = sorted({r.week for r in rows})
    positives = sum(1 for r in rows if r.label >= 0.5)
    info: dict[str, Any] = {"n": n, "weeks": [weeks[0], weeks[-1]] if weeks else []}
    if n < MIN_CASES:
        return {**info, "accepted": False, "reason": f"pocos casos ({n} < {MIN_CASES})"}
    if len(weeks) < MIN_WEEKS:
        return {**info, "accepted": False, "reason": f"pocas jornadas ({len(weeks)} < {MIN_WEEKS})"}
    if min(positives, n - positives) < MIN_PER_CLASS:
        return {**info, "accepted": False, "reason": "clases muy desequilibradas"}

    newest = weeks[-1]
    held_candidates = [
        w for w in weeks[-MAX_CV_WEEKS:] if sum(1 for r in rows if r.week == w) >= MIN_CV_WEEK_ROWS
    ]
    if len(held_candidates) < 2:
        return {**info, "accepted": False, "reason": "sin jornadas suficientes para validar"}

    sq_new = sq_old = count = 0.0
    for held in held_candidates:
        train = [r for r in rows if r.week != held]
        test = [r for r in rows if r.week == held]
        fitted = fit_logistic(train, _recency(train, newest))
        if fitted is None:
            return {**info, "accepted": False, "reason": "el ajuste no converge"}
        blended = _damp(current, fitted)
        sq_new += sum((predict(blended, r.features) - r.label) ** 2 for r in test)
        sq_old += sum((predict(current, r.features) - r.label) ** 2 for r in test)
        count += len(test)
    cv_new, cv_old = sq_new / count, sq_old / count
    info.update({"cv_brier_new": round(cv_new, 5), "cv_brier_current": round(cv_old, 5), "cv_rows": int(count)})

    full = fit_logistic(rows, _recency(rows, newest))
    if full is None:
        return {**info, "accepted": False, "reason": "el ajuste no converge"}
    proposal = _damp(current, full)
    if _valid(proposal) is None:
        return {**info, "accepted": False, "reason": "coeficientes fuera de rango"}
    if proposal["minutes"] <= 0:
        return {**info, "accepted": False, "reason": "más minutos recientes no puede bajar la probabilidad"}
    if cv_new > cv_old - MIN_GAIN:
        return {**info, "accepted": False, "reason": "no mejora a los pesos vigentes fuera de muestra"}
    return {
        **info,
        "accepted": True,
        "reason": "mejora fuera de muestra",
        "weights": {k: round(v, 4) for k, v in proposal.items()},
    }

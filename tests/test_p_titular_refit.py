"""Reajuste automático de p_titular: ajuste, salvaguardas y persistencia."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from toolbox.engine import p_titular_model as model
from toolbox.engine.xp_calculator import FantasyXPEngine, PartidoHistorico
from toolbox import p_titular_refit as refit_mod


@pytest.fixture(autouse=True)
def _own_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "pesos.json"
    monkeypatch.setenv("FANTASY_P_TITULAR_WEIGHTS", str(path))
    monkeypatch.setenv("FANTASY_CACHE_DIR", str(tmp_path))
    model.reset_cache()
    yield path
    model.reset_cache()


def _synthetic(truth: dict[str, float], weeks: range, per_week: int, seed: int = 7) -> list[model.Row]:
    rng = random.Random(seed)
    rows = []
    for week in weeks:
        for _ in range(per_week):
            f = (rng.random(), rng.random())
            p = model.predict(truth, f)
            rows.append(model.Row(week=week, features=f, label=1.0 if rng.random() < p else 0.0))
    return rows


def test_fit_recovers_known_weights() -> None:
    truth = {"bias": -1.0, "season": 0.5, "minutes": 3.0}
    rows = _synthetic(truth, range(1, 11), 400)
    fitted = model.fit_logistic(rows, l2=0.01)
    assert fitted is not None
    for key in truth:
        assert math.isclose(fitted[key], truth[key], abs_tol=0.35)


def test_default_weights_reproduce_initial_calibration() -> None:
    assert model.current_weights() == model.DEFAULT_WEIGHTS
    assert model.features_from_minutes([]) is None
    titular = model.predict(model.DEFAULT_WEIGHTS, model.features_from_minutes([90, 90, 90]))
    ausente = model.predict(model.DEFAULT_WEIGHTS, model.features_from_minutes([0, 0, 0]))
    assert titular > 0.8 > 0.4 > ausente


def test_rejects_when_too_few_cases() -> None:
    rows = _synthetic(model.DEFAULT_WEIGHTS, range(1, 5), 20)
    decision = model.evaluate_refit(rows, model.DEFAULT_WEIGHTS)
    assert not decision["accepted"]
    assert "pocos casos" in decision["reason"]


def test_keeps_weights_when_data_matches_them() -> None:
    rows = _synthetic(model.DEFAULT_WEIGHTS, range(1, 9), 120)
    decision = model.evaluate_refit(rows, model.DEFAULT_WEIGHTS)
    assert not decision["accepted"]


def test_accepts_better_weights_but_moves_gradually() -> None:
    truth = {"bias": -2.0, "season": 1.2, "minutes": 4.0}
    rows = _synthetic(truth, range(1, 9), 150)
    decision = model.evaluate_refit(rows, model.DEFAULT_WEIGHTS)
    assert decision["accepted"], decision
    new = decision["weights"]
    for key in new:
        assert abs(new[key] - model.DEFAULT_WEIGHTS[key]) <= model.MAX_MOVE + 1e-6
    assert new["minutes"] > model.DEFAULT_WEIGHTS["minutes"]


def test_rejects_implausible_direction() -> None:
    # Con los minutos recientes invertidos, el coeficiente saldría negativo.
    truth = {"bias": 1.0, "season": 0.0, "minutes": -3.0}
    rows = _synthetic(truth, range(1, 9), 150)
    current = {"bias": 0.0, "season": 0.0, "minutes": 0.2}
    decision = model.evaluate_refit(rows, current)
    assert not decision["accepted"]


def test_corrupt_or_wild_file_falls_back_to_defaults(_own_weights: Path) -> None:
    _own_weights.write_text("{no es json", encoding="utf-8")
    model.reset_cache()
    assert model.current_weights() == model.DEFAULT_WEIGHTS
    _own_weights.write_text(json.dumps({"weights": {"bias": 99, "season": 0, "minutes": 1}}), encoding="utf-8")
    model.reset_cache()
    assert model.current_weights() == model.DEFAULT_WEIGHTS


def test_engine_reads_saved_weights() -> None:
    historial = [PartidoHistorico(puntos=2.0, minutos=90, jornada=i) for i in (1, 2, 3)]
    before = FantasyXPEngine.prob_titular_heuristica(historial)
    model.save_state({"weights": {"bias": -3.0, "season": 0.0, "minutes": 1.0}})
    after = FantasyXPEngine.prob_titular_heuristica(historial)
    assert before is not None and after is not None
    assert after < before


def test_merge_keeps_richer_history_and_counts_new_rows() -> None:
    stored = {"a:5": {"w": 5, "f": [0.5, 0.5], "y": 1, "n": 4}}
    fresh = {
        "a:5": {"w": 5, "f": [0.1, 0.1], "y": 1, "n": 2},
        "b:6": {"w": 6, "f": [0.9, 0.9], "y": 0, "n": 3},
    }
    merged, added = refit_mod.merge_rows(stored, fresh)
    assert added == 1
    assert merged["a:5"]["f"] == [0.5, 0.5]
    assert "b:6" in merged


def test_collect_rows_uses_only_past_games() -> None:
    players = {"p1": {"weeks": {1: (3.0, 90.0), 2: (0.0, 0.0), 3: (5.0, 90.0), 4: (2.0, 10.0)}}}
    rows = refit_mod.collect_rows(players)
    assert set(rows) == {"p1:3", "p1:4"}
    # Jornada 3: pasado = [90, 0] → 1 titular de 2; la propia jornada 3 no entra.
    assert rows["p1:3"]["f"][0] == 0.5
    assert rows["p1:3"]["y"] == 1
    assert rows["p1:4"]["y"] == 0


def test_refit_without_cache_is_a_noop(tmp_path: Path) -> None:
    result = refit_mod.refit(bodies=tmp_path / "no_existe", force=True)
    assert result["ran"] is False


def test_maybe_refit_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FANTASY_P_TITULAR_AUTO", "0")
    assert refit_mod.maybe_refit() is None


def test_maybe_refit_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: object) -> dict:
        raise RuntimeError("fallo")

    monkeypatch.setattr(refit_mod, "refit", boom)
    assert refit_mod.maybe_refit() is None

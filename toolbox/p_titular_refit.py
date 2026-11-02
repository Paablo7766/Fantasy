"""Reajuste automático de ``p_titular`` con los datos que ya hay en la caché.

Cada actualización del tablero llama a :func:`maybe_refit`. Si hay casos nuevos
y han pasado al menos ``MIN_HOURS`` desde el último intento, lee el historial,
lo suma al dataset acumulado y deja que :func:`evaluate_refit` decida. Sin red:
solo lee ``scraper_bodies``.

El dataset se acumula en ``<cache>/p_titular_dataset.json`` porque
``lastStats`` solo trae una ventana de jornadas: sin guardarlo, las más viejas
se perderían y el ajuste se haría cada vez con menos datos.

Desactivar con ``FANTASY_P_TITULAR_AUTO=0``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from toolbox.cache import cache_root
from toolbox.engine import p_titular_model as model
from toolbox.player_history import load_history

logger = logging.getLogger(__name__)

MIN_PRIOR = 2
MIN_HOURS = 12.0
_DATASET_FILE = "p_titular_dataset.json"


def _dataset_path() -> Path:
    return cache_root() / _DATASET_FILE


def _load_dataset(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("rows") if isinstance(data, dict) else None
    return rows if isinstance(rows, dict) else {}


def _save_dataset(path: Path, rows: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"rows": rows}, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def collect_rows(players: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``jugador:jornada`` → características con el pasado y titular o no."""
    out: dict[str, dict[str, Any]] = {}
    for pid, entry in players.items():
        weeks = sorted(entry["weeks"])
        for index, week in enumerate(weeks):
            prior = [entry["weeks"][w][1] for w in weeks[:index]]
            if len(prior) < MIN_PRIOR:
                continue
            features = model.features_from_minutes(prior)
            if features is None:
                continue
            out[f"{pid}:{week}"] = {
                "w": week,
                "f": [round(features[0], 6), round(features[1], 6)],
                "y": 1 if entry["weeks"][week][1] >= model.STARTER_MINUTES else 0,
                "n": len(prior),
            }
    return out


def merge_rows(
    stored: dict[str, dict[str, Any]], fresh: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], int]:
    """Suma filas nuevas. Una fila ya guardada solo se sustituye si ahora se
    calcula con más pasado (la ventana de ``lastStats`` se desliza)."""
    merged = dict(stored)
    added = 0
    for key, row in fresh.items():
        old = merged.get(key)
        if old is None:
            added += 1
            merged[key] = row
        elif int(row.get("n", 0)) > int(old.get("n", 0)):
            merged[key] = row
    return merged, added


def to_model_rows(rows: dict[str, dict[str, Any]]) -> list[model.Row]:
    out: list[model.Row] = []
    for row in rows.values():
        try:
            out.append(
                model.Row(
                    week=int(row["w"]),
                    features=(float(row["f"][0]), float(row["f"][1])),
                    label=float(row["y"]),
                )
            )
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def refit(*, bodies: Path | None = None, force: bool = False, now: float | None = None) -> dict[str, Any]:
    """Un intento de reajuste. Devuelve un resumen; nunca lanza por datos malos."""
    moment = now if now is not None else time.time()
    bodies_dir = bodies or cache_root() / "scraper_bodies"
    state = model.load_state()
    last = state.get("last_check") if isinstance(state.get("last_check"), dict) else {}
    if not force and moment - float(last.get("at") or 0.0) < MIN_HOURS * 3600:
        return {"ran": False, "reason": "revisado hace menos de %d h" % MIN_HOURS}
    if not bodies_dir.is_dir():
        return {"ran": False, "reason": "sin historial en la caché"}

    players, _ = load_history(bodies_dir)
    dataset_path = _dataset_path()
    merged, added = merge_rows(_load_dataset(dataset_path), collect_rows(players))
    if added:
        _save_dataset(dataset_path, merged)
    if not force and not added and last:
        return {"ran": False, "reason": "sin casos nuevos", "n": len(merged)}

    current = model.current_weights()
    decision = model.evaluate_refit(to_model_rows(merged), current)
    check = {
        "at": moment,
        "accepted": bool(decision["accepted"]),
        "reason": decision["reason"],
        "n": decision.get("n"),
        "weeks": decision.get("weeks"),
        "cv_brier_new": decision.get("cv_brier_new"),
        "cv_brier_current": decision.get("cv_brier_current"),
    }
    new_state = dict(state)
    new_state["last_check"] = check
    history = list(new_state.get("history") or [])
    if decision["accepted"]:
        new_state["weights"] = decision["weights"]
        new_state["version"] = int(state.get("version") or 0) + 1
        history.append({**check, "weights": decision["weights"], "previous": current})
    elif "weights" not in new_state:
        new_state["weights"] = dict(model.DEFAULT_WEIGHTS)
    new_state["history"] = history[-model.HISTORY_KEEP :]
    model.save_state(new_state)
    return {"ran": True, **check, "weights": new_state["weights"], "added": added}


def maybe_refit() -> dict[str, Any] | None:
    """Gancho de la actualización: nunca tumba al llamador."""
    if os.getenv("FANTASY_P_TITULAR_AUTO", "1").strip().lower() in {"0", "false", "no", "off"}:
        return None
    try:
        result = refit()
    except Exception:  # noqa: BLE001 — afinar un modelo no debe romper la actualización
        logger.warning("Reajuste de p_titular fallido", exc_info=True)
        return None
    if result.get("ran"):
        logger.info(
            "p_titular: %s (%s; n=%s)",
            "pesos nuevos" if result.get("accepted") else "pesos sin cambios",
            result.get("reason"),
            result.get("n"),
        )
    return result

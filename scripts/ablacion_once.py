"""Paso 4: regret del once óptimo (J8–J12) con el xP de producción y el candidato.

El once se elige como en ``toolbox.analyzer.solve_lineup``: once exacto, una de
las siete formaciones, maximizando la suma del objetivo (el xP de jornada). Con
objetivo separable por jugador ese MILP equivale a tomar, para cada formación,
los mejores de cada puesto y quedarse con la mejor formación (se comprueba contra
pulp al arrancar).

Dos pruebas por jornada:
* **Pool completo**: el once de toda la muestra (≈140 jugadores).
* **Plantillas aleatorias**: 400 plantillas de 15 (2 POR, 5 DEF, 5 MC, 3 DEL); el
  regret es lo que sumaba el mejor once posible con puntos reales menos lo que
  sumó el elegido.

Riesgo de titularidad: objetivo = xP − λ·[0,35 ≤ p ≤ 0,70]·xP_cond·p(1−p), con λ
elegido en walk-forward (jornadas < t).

    python scripts/ablacion_once.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ablacion_xp as ax  # noqa: E402
from toolbox.analyzer import FORMATIONS  # noqa: E402

POS = {"PT": "POR", "DF": "DEF", "MC": "MC", "DL": "DEL"}
SQUAD = {"POR": 2, "DEF": 5, "MC": 5, "DEL": 3}
N_SQUADS = 400


def once(idx: np.ndarray, pos: np.ndarray, obj: np.ndarray) -> np.ndarray:
    mejor, elegido = -1e18, None
    for slots in FORMATIONS.values():
        sel = []
        ok = True
        for p, k in slots.items():
            cand = idx[pos[idx] == p]
            if len(cand) < k:
                ok = False
                break
            sel.extend(cand[np.argsort(-obj[cand], kind="stable")[:k]])
        if not ok:
            continue
        v = obj[sel].sum()
        if v > mejor:
            mejor, elegido = v, np.array(sel)
    return elegido


def comprobar_contra_pulp(pos, obj, rng) -> None:
    import pulp

    for _ in range(5):
        idx = rng.choice(len(obj), size=40, replace=False)
        mine = obj[once(idx, pos, obj)].sum()
        prob = pulp.LpProblem("x", pulp.LpMaximize)
        x = {i: pulp.LpVariable(f"x{i}", cat=pulp.LpBinary) for i in idx}
        f = {n: pulp.LpVariable(f"f{j}", cat=pulp.LpBinary) for j, n in enumerate(FORMATIONS)}
        prob += pulp.lpSum(f.values()) == 1
        prob += pulp.lpSum(x.values()) == 11
        for p in ("POR", "DEF", "MC", "DEL"):
            prob += pulp.lpSum(x[i] for i in idx if pos[i] == p) == pulp.lpSum(FORMATIONS[n][p] * f[n] for n in FORMATIONS)
        prob += pulp.lpSum(x[i] * float(obj[i]) for i in idx)
        prob.solve(pulp.PULP_CBC_CMD(msg=False))
        assert abs(pulp.value(prob.objective) - mine) < 1e-6, (pulp.value(prob.objective), mine)


def plantillas(semana_idx: np.ndarray, pos: np.ndarray, rng) -> list[np.ndarray]:
    out = []
    por_pos = {p: semana_idx[pos[semana_idx] == p] for p in SQUAD}
    for _ in range(N_SQUADS):
        out.append(np.concatenate([rng.choice(por_pos[p], size=k, replace=False) for p, k in SQUAD.items()]))
    return out


def evaluar(filas, preds: dict[str, np.ndarray], p: np.ndarray, cond: np.ndarray, rng_seed: int = 7) -> dict[str, dict[int, tuple[float, float]]]:
    y = np.array([f.actual for f in filas])
    pos = np.array([POS[f.slot] for f in filas])
    semanas = np.array([f.week for f in filas])
    rng = np.random.default_rng(rng_seed)
    comprobar_contra_pulp(pos, preds["base"], rng)
    out: dict[str, dict[int, tuple[float, float]]] = {k: {} for k in preds}
    for t in sorted(set(semanas)):
        idx = np.where(semanas == t)[0]
        squads = plantillas(idx, pos, np.random.default_rng(rng_seed + int(t)))
        for nombre, obj in preds.items():
            pool = y[once(idx, pos, obj)].sum()
            reg = []
            for sq in squads:
                real = y[once(sq, pos, obj)].sum()
                best = y[once(sq, pos, y)].sum()
                reg.append(best - real)
            out[nombre][int(t)] = (float(pool), float(np.mean(reg)))
    return out


def riesgo(xp: np.ndarray, p: np.ndarray, cond: np.ndarray, lam: float) -> np.ndarray:
    dudoso = (p >= 0.35) & (p <= 0.70)
    return xp - lam * dudoso * cond * p * (1 - p)


def main() -> int:
    import json

    filas, _, _ = ax.construir_filas([8, 9, 10, 11, 12], 1)
    base, sal = ax.correr(filas, ax.Config("base"))
    p = np.array([s["p"] for s in sal])
    cond = np.array([s["cond"] for s in sal])
    preds = {"base": base}
    extra = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if extra and extra.is_file():
        preds["nuevo"] = np.array(json.loads(extra.read_text(encoding="utf-8")))
    for lam in (0.5, 1.0, 2.0):
        preds[f"riesgo λ={lam}"] = riesgo(base, p, cond, lam)
    res = evaluar(filas, preds, p, cond)
    semanas = sorted(next(iter(res.values())).keys())
    print(f"{'objetivo':<16}" + "".join(f"   J{t} pool/regret" for t in semanas) + "   total pool  regret medio")
    for nombre, por in res.items():
        tot = sum(v[0] for v in por.values())
        reg = np.mean([v[1] for v in por.values()])
        print(f"{nombre:<16}" + "".join(f"   {por[t][0]:6.0f} / {por[t][1]:5.2f}" for t in semanas) + f"   {tot:9.0f}  {reg:8.3f}")
    # Walk-forward de λ: para t, el λ con menor regret en jornadas < t.
    lams = {0.0: "base", 0.5: "riesgo λ=0.5", 1.0: "riesgo λ=1.0", 2.0: "riesgo λ=2.0"}
    wf = []
    for t in semanas:
        prev = [s for s in semanas if s < t]
        if not prev:
            lam = 0.0
        else:
            lam = min(lams, key=lambda l: np.mean([res[lams[l]][s][1] for s in prev]))
        wf.append((t, lam, res[lams[lam]][t][1], res["base"][t][1]))
    print("\nλ walk-forward:", ", ".join(f"J{t} λ={l} regret {r:.2f} (base {b:.2f})" for t, l, r, b in wf))
    print(f"Regret medio WF {np.mean([r for *_, r, _ in wf]):.3f} vs base {np.mean([b for *_, b in wf]):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

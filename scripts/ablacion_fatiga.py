"""Paso 2.3: fatiga de competición europea y rotación corta.

Calendario de todas las competiciones por equipo (FútbolFantasy,
``.cache/calendario_competiciones_2627.json``). Para cada jugador-jornada:

* ``europa_antes``: partido de Champions/Europa/Conference ≤ 4 días antes.
* ``descanso_corto``: cualquier partido oficial < 72 h antes (incluye Copa).
* ``europa_despues``: partido europeo ≤ 4 días después (rotación preventiva).

Se mide (a) el Brier de titularidad con esas variables en el logístico
reajustado en walk-forward y (b) el MAE con un descuento a la titularidad de los
no fijos (p < 0,85), con el descuento elegido en jornadas < t, y con el
descuento de copa que ya trae ``opta_points_v2`` (``has_midweek_cup``).

    python scripts/ablacion_fatiga.py
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ablacion_xp as ax  # noqa: E402
import ablacion_xp_experimentos as ex  # noqa: E402
from toolbox.cache import cache_root  # noqa: E402
from toolbox.engine import p_titular_model as ptm  # noqa: E402

SLUG = {"atletico": "atletico madrid", "rayo-vallecano": "rayo", "real-madrid": "real madrid", "real-sociedad": "real sociedad"}
EUROPA = {"Champions League", "Europa League", "Conference League"}


def calendario() -> dict[str, list[tuple[date, str, str | None]]]:
    raw = json.loads((cache_root() / "calendario_competiciones_2627.json").read_text(encoding="utf-8"))
    out = {}
    for slug, filas in raw.items():
        club = SLUG.get(slug, slug)
        out[club] = sorted(
            (date.fromisoformat(r["fecha"]), r["comp"], r.get("jornada")) for r in filas if r["comp"] != "Amistoso"
        )
    return out


def contexto(cal, club: str, semana: int) -> dict[str, float] | None:
    partidos = cal.get(club) or []
    liga = [d for d, c, j in partidos if c == "LaLiga" and j == f"J{semana}"]
    if not liga:
        return None
    dia = liga[0]
    antes = [(dia - d).days for d, c, _ in partidos if d < dia]
    eur_antes = [(dia - d).days for d, c, _ in partidos if d < dia and c in EUROPA]
    eur_desp = [(d - dia).days for d, c, _ in partidos if d > dia and c in EUROPA]
    return {
        "europa_antes": 1.0 if eur_antes and min(eur_antes) <= 4 else 0.0,
        "descanso_corto": 1.0 if antes and min(antes) < 3 else 0.0,
        "europa_despues": 1.0 if eur_desp and min(eur_desp) <= 4 else 0.0,
        "descanso": float(min(antes)) if antes else 7.0,
    }


def main() -> int:
    cal = calendario()
    filas, actas, _ = ax.construir_filas(ex.TEST, 1)
    ctx = [contexto(cal, f.club, f.week) for f in filas]
    print(f"Filas {len(filas)}, con calendario {sum(c is not None for c in ctx)}")
    for k in ("europa_antes", "descanso_corto", "europa_despues"):
        print(f"  {k}: {sum(1 for c in ctx if c and c[k])} filas")

    # (a) Brier de titularidad, logístico WF con y sin variables de calendario.
    def extra(e, prev, weeks):
        # semana objetivo = la siguiente a prev[-1] en ``weeks``
        orden = sorted(weeks)
        w = orden[orden.index(prev[-1]) + 1]
        c = contexto(cal, ax._club(e.get("team")), w) or {"europa_antes": 0, "descanso_corto": 0, "europa_despues": 0}
        return [c["europa_antes"], c["descanso_corto"], c["europa_despues"]]

    def extra_int(e, prev, weeks):
        base = extra(e, prev, weeks)
        mins = [float(weeks[x][1]) for x in prev]
        f = ptm.features_from_minutes(mins)
        no_fijo = 1.0 - (f[0] if f else 0.0)
        return base + [b * no_fijo for b in base]

    for nombre, fx in (("sin calendario", None), ("+ Europa/descanso", extra), ("+ Europa/descanso × no fijo", extra_int)):
        pw = ex.p_wf(actas, fx, defecto=None)
        sel = [(pw[(f.pid, f.week)], 1.0 if f.minutes >= 45 else 0.0) for f in filas if (f.pid, f.week) in pw]
        p = np.array([a for a, _ in sel])
        y = np.array([b for _, b in sel])
        ll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
        print(f"  Brier WF J9–J12 {nombre:<30}{np.mean((p - y) ** 2):.4f}  log-loss {ll:.4f}  n={len(sel)}")

    # Tasas brutas: ¿juegan menos de titular los no fijos con Europa cerca?
    base, sal = ax.correr(filas, ax.Config("base"))
    p = np.array([s["p"] for s in sal])
    st = np.array([1.0 if f.minutes >= 45 else 0.0 for f in filas])
    for k in ("europa_antes", "descanso_corto", "europa_despues"):
        m = np.array([bool(c and c[k]) for c in ctx]) & (p < 0.85)
        if m.sum():
            print(f"  no fijos con {k}: n={m.sum()} titular real {st[m].mean():.2f} vs p predicha {p[m].mean():.2f}")

    # (b) MAE: descuento de titularidad a no fijos con Europa antes o descanso corto, elegido WF.
    preds = {}
    for d in (0.0, 0.05, 0.10, 0.20, 0.30):
        def ptit(f, d=d, i_map={id(f): i for i, f in enumerate(filas)}):
            c = ctx[i_map[id(f)]]
            p0 = ax.p_titular_heuristica(f)
            if c and (c["europa_antes"] or c["descanso_corto"]) and p0 < 0.85:
                return p0 * (1 - d)
            return p0
        preds[d] = ax.correr(filas, ax.Config("fat", p_titular=ptit))[0] if d else base
    nueva, eleg = ex.wf_elegir(filas, preds, 0.0)
    ex.registrar("2.3a Descuento por Europa/descanso <72h (no fijos)", filas, base, nueva, f"elegido {eleg}")
    for d, v in preds.items():
        print(f"    descuento {d:.2f}: MAE {ax.mae(v, filas):.3f}")

    # Descuento de copa ya escrito en opta_points_v2 (UEFA_FATIGUE_RHO), hoy sin llamar.
    from toolbox.opta_points_v2 import compute_expected_opta_points_v2

    out = []
    for f, c in zip(filas, ctx):
        player = ax.jugador(f, ax.Config("x"), ax.p_titular_heuristica(f))
        kw = {"run_monte_carlo": False}
        if f.partido.lam_f is not None:
            kw.update(lambda_own=f.partido.lam_f, lambda_opp=f.partido.lam_c, p_cs_own=f.partido.p_cs)
        if c and c["europa_antes"]:
            kw.update(has_midweek_cup=True, days_rest=int(c["descanso"]))
        out.append(float(compute_expected_opta_points_v2(player, **kw)["expected_points"]))
    ex.registrar("2.3b Descuento UEFA_FATIGUE_RHO ya escrito en opta_v2", filas, base, np.array(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Backtest: ¿ayuda el histórico de temporadas pasadas a xP 2.0?

Para cada jugador y jornada de test ``t`` en la que fue titular (>= 45'), predice
sus puntos de ``t`` con xP 2.0 condicional a ser titular (la titularidad es otro
problema) usando solo las actas de jornadas ``< t`` de esta temporada. Compara:

* **base**: el modelo de hoy (puesto como punto de partida).
* **hist**: igual, pero el punto de partida se mueve hacia el pasado del jugador
  (``toolbox.season_history``).

    python scripts/backtest_historico.py
    python scripts/backtest_historico.py --test-weeks 8 9 10 11 12 --min-prior 3
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.engine import xp2  # noqa: E402
from toolbox.engine.xp_calculator import canonical_slot  # noqa: E402
from toolbox.player_history import leer_almacen_actas  # noqa: E402
from toolbox.season_history import (  # noqa: E402
    emparejar,
    hist_prior,
    indice_por_club,
    leer_almacen,
    medias_por_puesto,
    resumenes_del_almacen,
)


def jugador_hasta(entry: dict[str, Any], semana: int) -> dict[str, Any]:
    """Jugador con las actas de las jornadas anteriores a ``semana``."""
    historial = []
    desgloses = {int(k): v for k, v in (entry.get("desglose") or {}).items()}
    for wk, (pts, mins) in sorted((int(k), v) for k, v in entry["weeks"].items()):
        desglose = desgloses.get(wk)
        if wk >= semana or desglose is None:
            continue
        historial.append({"jornada": wk, "puntos": pts, "minutos": mins, "desglose": desglose})
    return {"position": entry["position"], "club": entry.get("team"), "historial": historial}


def predice(player: dict[str, Any]) -> float | None:
    res = xp2.prediccion_xp2(player, prob_titular=1.0, lambda_favor=1.3, lambda_contra=1.3)
    return None if res is None else float(res["xp_condicional"])


def metricas(errores: list[float]) -> tuple[float, float]:
    n = len(errores)
    return sum(abs(e) for e in errores) / n, math.sqrt(sum(e * e for e in errores) / n)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-weeks", type=int, nargs="+", default=[8, 9, 10, 11, 12])
    parser.add_argument("--min-prior", type=int, default=2, help="titularidades previas mínimas")
    args = parser.parse_args()

    actas = leer_almacen_actas()
    almacen = leer_almacen()
    resumenes = resumenes_del_almacen(almacen)
    medias = medias_por_puesto(resumenes)
    indice = indice_por_club(almacen)
    print(f"Almacén histórico: {len(almacen)} jugadores, {len(resumenes)} con resumen. Medias por puesto:")
    for slot, m in sorted(medias.items()):
        print(f"  {slot}: suelo {m['suelo']:.2f}  goles/partido {m['goles']:.3f}  asist {m['asistencia']:.2f}")

    filas: list[dict[str, Any]] = []
    sin_cruce = 0
    for entry in actas.values():
        slug = emparejar(entry.get("name"), entry.get("team"), indice)
        slot = canonical_slot(str(entry["position"]))
        resumen = resumenes.get(slug) if slug else None
        if slug is None or resumen is None or resumen["slot"] != slot:
            sin_cruce += 1
            prior = None
        else:
            prior = hist_prior(resumen, medias)
        for semana in args.test_weeks:
            semanas = {int(k): v for k, v in entry["weeks"].items()}
            if semana not in semanas:
                continue
            real, minutos = semanas[semana]
            if minutos < xp2.MINUTO_TITULAR:
                continue
            base = jugador_hasta(entry, semana)
            if sum(1 for h in base["historial"] if h["minutos"] >= xp2.MINUTO_TITULAR) < args.min_prior:
                continue
            filas.append({"semana": semana, "slot": slot, "real": float(real), "player": base, "prior": prior, "n_pasado": resumen["n_titular"] if resumen else 0})

    con_hist = [f for f in filas if f["prior"]]
    print(f"\nJugadores de las actas sin cruce con el histórico: {sin_cruce}")
    print(f"Observaciones: {len(filas)} (con histórico: {len(con_hist)})")

    def evalua(muestra: list[dict[str, Any]], usar: bool) -> list[float]:
        errores = []
        for f in muestra:
            jugador = dict(f["player"])
            if usar and f["prior"]:
                jugador["hist_prior"] = f["prior"]
            pred = predice(jugador)
            if pred is not None:
                errores.append(pred - f["real"])
        return errores

    print("\n== Solo observaciones con histórico, MAE / RMSE (puntos) ==")
    base = metricas(evalua(con_hist, False))
    print(f"  base  MAE {base[0]:.3f}  RMSE {base[1]:.3f}")
    hist = metricas(evalua(con_hist, True))
    print(f"  hist  MAE {hist[0]:.3f}  RMSE {hist[1]:.3f}")

    print("\n== Por jornada de test (con histórico) ==")
    for semana in args.test_weeks:
        sub = [f for f in con_hist if f["semana"] == semana]
        if len(sub) < 5:
            continue
        b, h = metricas(evalua(sub, False)), metricas(evalua(sub, True))
        print(f"  J{semana}: n={len(sub):3d}  base {b[0]:.3f}  hist {h[0]:.3f}")

    print("\n== Por puesto ==")
    for slot in ("PT", "DF", "MC", "DL"):
        sub = [f for f in con_hist if f["slot"] == slot]
        if len(sub) < 5:
            continue
        b, h = metricas(evalua(sub, False)), metricas(evalua(sub, True))
        print(f"  {slot}: n={len(sub):3d}  base {b[0]:.3f}  hist {h[0]:.3f}")

    print("\n== Pocas jornadas previas (<= 3 titularidades) frente a muchas ==")
    for etiqueta, cond in (("<=3", lambda f: sum(1 for h in f["player"]["historial"] if h["minutos"] >= 45) <= 3), (">3", lambda f: sum(1 for h in f["player"]["historial"] if h["minutos"] >= 45) > 3)):
        sub = [f for f in con_hist if cond(f)]
        if len(sub) < 5:
            continue
        b, h = metricas(evalua(sub, False)), metricas(evalua(sub, True))
        print(f"  {etiqueta}: n={len(sub):3d}  base {b[0]:.3f}  hist {h[0]:.3f}")

    print("\n== Malla de pesos (K más bajo = más peso al pasado) ==")
    guardados = (xp2.K_HIST_SUELO, xp2.K_HIST_GOL, xp2.K_HIST_ASIST)
    mejor = None
    for ks in (4.0, 8.0, 12.0, 25.0, 50.0, 100.0):
        for kg in (10.0, 25.0, 50.0, 1e9):
            xp2.K_HIST_SUELO, xp2.K_HIST_GOL, xp2.K_HIST_ASIST = ks, kg, kg
            m = metricas(evalua(con_hist, True))
            marca = ""
            if mejor is None or m[0] < mejor[0]:
                mejor = (m[0], ks, kg)
            print(f"  K_suelo {ks:6.0f}  K_gol/asist {kg:9.0f}  MAE {m[0]:.3f}  RMSE {m[1]:.3f}{marca}")
    xp2.K_HIST_SUELO, xp2.K_HIST_GOL, xp2.K_HIST_ASIST = guardados
    if mejor:
        print(f"\nMejor MAE de la malla: {mejor[0]:.3f} con K_suelo={mejor[1]:.0f}, K_gol/asist={mejor[2]:.0f} (pesos actuales: {guardados[0]:.0f}/{guardados[1]:.0f}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

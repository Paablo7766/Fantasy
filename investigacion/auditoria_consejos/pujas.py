"""Cruce de las pujas del cuaderno de mercado con el precio que pagó el ganador.

Solo lee ``.cache/responses.sqlite``. No es la puja del optimizador: esa
cifra no se guardó. La segunda oferta tampoco está: la API manda el recuento,
no el array de importes.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / ".cache" / "responses.sqlite"
OUT = Path(__file__).resolve().parent


def wilson(aciertos: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = aciertos / n
    den = 1.0 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - margen), min(1.0, centro + margen)


def _dia(valor: str) -> date | None:
    texto = valor.strip()
    if texto.endswith("Z"):
        texto = f"{texto[:-1]}+00:00"
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        try:
            return date.fromisoformat(texto[:10])
        except ValueError:
            return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.date()


def cruzar(conn: sqlite3.Connection) -> dict:
    pujas = [
        {
            "day": day,
            "player_id": player_id,
            "suggested_bid": int(bid),
            "win_probability": proba,
            "outcome": outcome,
            "paid_eur": int(paid) if isinstance(paid, int) and paid > 0 else None,
        }
        for day, player_id, bid, proba, outcome, paid in conn.execute(
            """
            select snapshot_day, player_id, suggested_bid, win_probability, outcome, paid_eur
            from market_decision_snapshots
            where decision = 'PUJAR' and suggested_bid is not null
            """
        )
        if isinstance(bid, int) and bid > 0
    ]
    # El desenlace ya cruzó la compra con el día del consejo: ``paid_eur`` es
    # lo que pagó quien se la llevó. Una compra anterior no cuenta, y la misma
    # subasta fotografiada dos días seguidos cuenta una vez (manda el día del pago).
    compras: dict[str, list[date]] = defaultdict(list)
    for player_id, at in conn.execute("select player_id, at from activity_buys where amount_eur > 0"):
        dia = _dia(str(at))
        if dia is not None and isinstance(player_id, str):
            compras[player_id].append(dia)

    vistos: set[tuple[str, int]] = set()
    con_cierre: list[dict] = []
    for puja in sorted(pujas, key=lambda row: row["day"], reverse=True):
        if puja["outcome"] not in {"lost", "hit"} or puja["paid_eur"] is None:
            continue
        clave = (puja["player_id"], puja["paid_eur"])
        if clave in vistos:
            continue
        try:
            dia = date.fromisoformat(puja["day"])
        except ValueError:
            continue
        if not any(compra >= dia for compra in compras.get(puja["player_id"], [])):
            continue
        vistos.add(clave)
        amount = puja["paid_eur"]
        con_cierre.append(
            {
                **puja,
                "cierre_eur": amount,
                "cubre": puja["suggested_bid"] >= amount,
                "gap_eur": puja["suggested_bid"] - amount,
            }
        )
    sin_cierre = sum(1 for puja in pujas if puja["outcome"] not in {"lost", "hit"} or puja["paid_eur"] is None)
    fotos_repetidas = sum(1 for puja in pujas if puja["outcome"] in {"lost", "hit"} and puja["paid_eur"] is not None) - len(con_cierre)

    cubre = sum(1 for row in con_cierre if row["cubre"])
    n = len(con_cierre)
    intervalo = wilson(cubre, n)
    gaps = [row["gap_eur"] for row in con_cierre]
    bajo = [row["gap_eur"] for row in con_cierre if row["gap_eur"] < 0]
    return {
        "fuente": "market_decision_snapshots, decision PUJAR. No es la puja del plan.",
        "pujas_con_cifra": len(pujas),
        "con_precio_de_cierre": n,
        "sin_compra_en_un_dia": sin_cierre,
        "fotos_de_la_misma_subasta": fotos_repetidas,
        "cifra_cubre_o_iguala_el_cierre": cubre,
        "proporcion": None if n == 0 else round(cubre / n, 3),
        "wilson_95": None if intervalo is None else [round(intervalo[0], 3), round(intervalo[1], 3)],
        "gap_mediano_eur": _mediana(gaps),
        "se_quedan_cortas": len(bajo),
        "corto_mediano_eur": _mediana(bajo),
        "filas": sorted(con_cierre, key=lambda row: (row["day"], row["player_id"])),
    }


def _mediana(valores: list[int]) -> int | None:
    if not valores:
        return None
    ordered = sorted(valores)
    medio = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[medio]
    return int(round((ordered[medio - 1] + ordered[medio]) / 2))


def _euros(valor: int | None) -> str:
    if valor is None:
        return "—"
    signo = "−" if valor < 0 else ""
    return f"{signo}{abs(valor) / 1_000_000:.2f} M€"


def informe(resultado: dict) -> str:
    n = resultado["con_precio_de_cierre"]
    intervalo = resultado["wilson_95"]
    banda = "sin muestra" if intervalo is None else f"{intervalo[0]:.0%}–{intervalo[1]:.0%}"
    proporcion = resultado["proporcion"]
    texto_proporcion = "sin cierres" if proporcion is None else f"{proporcion:.0%}"
    return f"""# Pujas del cuaderno de mercado

Esto no es la puja del optimizador. Esa cifra, la reserva y la probabilidad del plan no se guardaron. Aquí están las {resultado["pujas_con_cifra"]} filas «PUJAR» de `market_decision_snapshots` que traen un importe, del 22 de octubre al 14 de noviembre.

El precio de quien ganó solo está cuando el cuaderno marcó la fila como ganada o perdida (`paid_eur`). Una compra anterior no entra, y dos fotos de la misma subasta cuentan una vez ({resultado["fotos_de_la_misma_subasta"]} foto de más). Así quedan {n} subastas. Otras {resultado["sin_compra_en_un_dia"]} recomendaciones no tienen precio de cierre: nadie las compró en la ventana, o el desenlace sigue abierto. Cero de las {resultado["pujas_con_cifra"]} acabaron en «hit».

En esas {n}, la cifra sugerida cubre o iguala lo que pagó el ganador en {resultado["cifra_cubre_o_iguala_el_cierre"]} ({texto_proporcion}). Intervalo de Wilson al 95 %: {banda}. El intervalo es tan ancho que no se puede decir que la recomendación se quede corta de forma sistemática, ni lo contrario.

Mediana de (cifra − precio pagado): {_euros(resultado["gap_mediano_eur"])}. Se quedan por debajo {resultado["se_quedan_cortas"]} veces; en ese caso el hueco mediano es {_euros(resultado["corto_mediano_eur"])}.

Cubrir el precio pagado no significa que la puja se hubiera ganado: «lost» quiere decir que la compró otro equipo, no que la cifra fuera insuficiente. La segunda oferta no está. La API manda el recuento de pujas y no los importes, así que el sobreprecio frente a la segunda no se puede medir.
"""


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        resultado = cruzar(conn)
    finally:
        conn.close()
    publico = {clave: valor for clave, valor in resultado.items() if clave != "filas"}
    (OUT / "resultados_pujas.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "informe_pujas.md").write_text(informe(publico), encoding="utf-8")
    print(json.dumps(publico, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

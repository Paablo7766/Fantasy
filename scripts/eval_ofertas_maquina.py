"""Evalúa una oferta del "Computer" (máquina) de LaLiga Fantasy.

La máquina ofrece una distribución uniforme de Valor de Mercado ± 5 %: el
valor esperado es el VM y la horquilla útil es ``[0.95·VM, 1.05·VM]``. Se mide
la desviación de la oferta frente al VM y se recomienda una acción.

Uso:
    python scripts/eval_ofertas_maquina.py 10.000.000 10.320.000
    python scripts/eval_ofertas_maquina.py 10000000 10320000 --json
    python scripts/eval_ofertas_maquina.py 10000000 9500000 --force-liquidity
"""

from __future__ import annotations

import argparse
import json
import sys

#: Horquilla de la máquina sobre el valor de mercado.
MACHINE_SPREAD = 0.05
INSTANT_SELL_PCT = 3.0
ACCEPT_PCT = 1.0


def _money(raw: str) -> float:
    """Acepta ``10.000.000``, ``10,000,000``, ``10 000 000`` o ``10000000``."""
    text = str(raw).strip().replace("€", "").replace(" ", "").replace("_", "")
    if not text:
        raise argparse.ArgumentTypeError("importe vacío")
    if "," in text and "." in text:
        # El último separador manda: 10.000.000,50 vs 10,000,000.50
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        clean = text.replace(",", "")
        if clean.isdigit():
            text = clean
        else:
            text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"importe no válido: {raw}") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("el importe no puede ser negativo")
    return value


def evaluate(market_value: float, offer: float, *, force_liquidity: bool = False) -> dict:
    """Devuelve desviación, posición en la horquilla y acción recomendada."""
    if market_value <= 0:
        raise ValueError("el valor de mercado debe ser positivo")
    deviation_pct = (offer - market_value) / market_value * 100.0
    low = market_value * (1.0 - MACHINE_SPREAD)
    high = market_value * (1.0 + MACHINE_SPREAD)

    if deviation_pct > INSTANT_SELL_PCT:
        action = "INSTANT_SELL"
        reason = f"por encima del +{INSTANT_SELL_PCT:.0f}%: la máquina paga por encima de su horquilla"
    elif deviation_pct > ACCEPT_PCT:
        action = "ACCEPT"
        reason = f"entre +{ACCEPT_PCT:.0f}% y +{INSTANT_SELL_PCT:.0f}%: prima positiva sobre el VM"
    elif force_liquidity:
        action = "SELL_FOR_LIQUIDITY"
        reason = "desviación no positiva, pero se fuerza liquidez"
    else:
        action = "HOLD"
        reason = "a la par o por debajo del VM: no compensa vender"

    return {
        "market_value": round(market_value, 2),
        "offer": round(offer, 2),
        "deviation_pct": round(deviation_pct, 4),
        "deviation_label": f"{deviation_pct:+.2f}%",
        "relative_to_spread": (
            "dentro_horquilla" if low <= offer <= high else ("encima_horquilla" if offer > high else "bajo_horquilla")
        ),
        "spread_range": [round(low, 2), round(high, 2)],
        "action": action,
        "reason": reason,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="¿Es buena la oferta del Computer? LaLiga Fantasy ±5 %.")
    parser.add_argument("market_value", type=_money, help="Valor de mercado actual del jugador.")
    parser.add_argument("offer", type=_money, help="Oferta recibida por la máquina.")
    parser.add_argument("--force-liquidity", action="store_true", help="Vender aunque la desviación no sea positiva.")
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    result = evaluate(args.market_value, args.offer, force_liquidity=args.force_liquidity)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(
        f"VM {result['market_value']:,.0f} € · oferta {result['offer']:,.0f} € · "
        f"desviación {result['deviation_label']}"
    )
    print(
        f"Horquilla máquina ±5 %: {result['spread_range'][0]:,.0f} – "
        f"{result['spread_range'][1]:,.0f} € ({result['relative_to_spread']})"
    )
    print(f"ACCIÓN: {result['action']} — {result['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

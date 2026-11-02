"""Reajusta a mano los pesos de ``p_titular`` (el motor lo hace solo al actualizar).

    python scripts/refit_p_titular.py           # intento normal, con salvaguardas
    python scripts/refit_p_titular.py --force   # ignora la espera de 12 h
    python scripts/refit_p_titular.py --status  # pesos vigentes e historial
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolbox.engine import p_titular_model as model  # noqa: E402
from toolbox.p_titular_refit import refit  # noqa: E402


def _status() -> None:
    state = model.load_state()
    print("Archivo:", model.weights_path())
    print("Pesos vigentes:", {k: round(v, 4) for k, v in model.current_weights().items()})
    print("Versión:", state.get("version", 0), "(0 = valores iniciales)")
    last = state.get("last_check")
    if isinstance(last, dict):
        when = datetime.fromtimestamp(float(last.get("at") or 0)).strftime("%Y-%m-%d %H:%M")
        print(f"Último intento: {when}  aceptado={last.get('accepted')}  {last.get('reason')}")
        print(f"  casos={last.get('n')}  Brier nuevo={last.get('cv_brier_new')}  vigente={last.get('cv_brier_current')}")
    for item in (state.get("history") or [])[-5:]:
        when = datetime.fromtimestamp(float(item.get("at") or 0)).strftime("%Y-%m-%d %H:%M")
        print(f"  cambio {when}: {item.get('previous')} -> {item.get('weights')}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--force", action="store_true", help="ignora la espera mínima y la comprobación de casos nuevos")
    parser.add_argument("--status", action="store_true", help="muestra los pesos y el historial, sin ajustar")
    args = parser.parse_args()
    if args.status:
        _status()
        return 0
    result = refit(force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

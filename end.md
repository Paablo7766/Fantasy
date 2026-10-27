# Fin de sesión — estado real de lo hecho

## 1. Persistencia `predicted_win` (MAE)

- Columna `predicted_win real` (nullable) en `market_decision_snapshots`.
  - Migración idempotente en `toolbox/engine_calibration.py` (`_ensure_predicted_win_column`) y en `ensure_schema` de `toolbox/market_clear_report.py`.
  - Aplicada a `.cache/responses.sqlite` (tabla tenía 228 filas; ahora 59 + 228).
- `persist_market_decisions` inserta `predicted_win` (orden: `predicted_win` → `optimal_bid_eur` → `suggested_bid`) y en el upsert usa `coalesce` para no borrar el valor anterior.
- Backfill manual del día 2026-10-26: 6 filas con `predicted_win`.
- `scripts/audit_market_clear.py` ya la leía (`read_persisted_predictions`); el informe usa la columna si existe.
- Test actualizado: `tests/test_market_clear.py::test_missing_predicted_win_column_is_migrated_and_empty`.
- Suites: `test_engine_calibration.py` + `test_market_clear.py` → 24 passed, 1 skipped.

## 2. Analizador de ofertas del Computer

- `scripts/eval_ofertas_maquina.py` (CLI aislado, sin red):
  - `python scripts/eval_ofertas_maquina.py <valor_mercado> <oferta> [--force-liquidity] [--json]`
  - Desviación %, horquilla ±5 %, acciones `INSTANT_SELL` (>+3 %), `ACCEPT` (>+1 %), `HOLD`, `SELL_FOR_LIQUIDITY`.
- Panel UI: `frontend/components/ComputerOffersPanel.tsx`, montado en `PortfolioDashboard.tsx` (pestaña Cartera). Réplica en TS de la misma regla, calculadora manual y campo por jugador.
- Endpoint nuevo: `GET /api/market-maker` en `server.py` → `toolbox.market_maker.get_market_recommendations` (motor completo: percentil banda ±10 % + EV de mañana). Solo lectura, no toca red.
- `tsc --noEmit` en `frontend`: limpio.

## 3. Pendiente / siguiente paso

Automatizar la ingesta de ofertas:
- Las pujas viven en `market.listings[].bids` (ya normalizadas por `toolbox/normalize.py::_normalize_bids` con `team_id`/`manager_name`/`amount`).
- En la foto actual (`.cache/dashboard/_default/core.json`) todos los listings vienen con `bids: []` y `leading_bid: null` → hay que confirmar si la API solo expone pujas propias o si la ruta de mercado no las trae.
- Plan: cruzar `bids.team_id == own_team_id` con `market_value` y `own_predicted_delta` para que la tarjeta se rellene sola (oferta recibida, mi puja, si voy ganando) sin pegar nada.
- La lógica de "vender / aguantar" sale de `market_maker._decide` + `toolbox/own_intel.py` (SELL_AT_CREST, SELL_CONFIRMED_REVERSAL, HOLD_RISING, HOLD_STABLE) y de `own_predicted_delta` (delta diario previsto).

## Notas

- `tests/test_market_maker.py` tiene 3 fallos previos (esperan `LIQUIDATE_NOW`, la lógica devuelve `HOLD`/`SELL`). No tocados: `toolbox/market_maker.py` y ese test no están versionados y no formaban parte de los 2 pasos.
- El backend debe reiniciarse para que exista `/api/market-maker`.

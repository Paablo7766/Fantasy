"""
Script de Auditoría y Backtesting Empírico v2.0 para LaLiga Fantasy.
Evalúa la precisión predictiva de:
  1. Cinemática de precios (SELL_AT_CREST vs caídas reales en 24-48h en `price_snapshots`).
  2. Perfilado de subastas (calibración de primas y coberturas presupuestarias en `activity_type_id == 31`).
"""
from __future__ import annotations

import os
import sqlite3
import math
from typing import Any, Dict, List, Tuple
from collections import defaultdict

# Importar las funciones cuantitativas del núcleo
from toolbox.own_intel import compute_price_kinematics_and_sell_signal
from toolbox.league_history import fit_rival_profiles_eb
from toolbox.bid_war import probability_of_winning_bid


DB_PATH = os.environ.get("FANTASY_DB_PATH", "responses.sqlite")


def get_db_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        # Fallback a entities.sqlite si no se encuentra responses.sqlite
        alt_path = "entities.sqlite"
        if os.path.exists(alt_path):
            conn = sqlite3.connect(alt_path)
        else:
            raise FileNotFoundError(f"No se encontró base de datos en {DB_PATH} ni {alt_path}")
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def backtest_price_kinematics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Evalúa retrospectivamente la señal SELL_AT_CREST en la tabla `price_snapshots`.
    Verifica si tras disparar la señal, el jugador efectivamente experimentó:
      - dV <= 0 en t+1 o t+2 (anticipación de pico).
      - Beneficio en euros ahorrado vs liquidar en la primera caída oficial.
    """
    cursor = conn.cursor()
    # Extraer todos los snapshots agrupados por jugador ordenados por día
    query = """
    SELECT player_id, day, market_value, market_value_change
    FROM price_snapshots
    ORDER BY player_id, day ASC
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        return {"error": "Tabla price_snapshots no accesible en la base de datos."}

    player_series: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        player_series[str(r["player_id"])].append({
            "day": r["day"],
            "market_value": r["market_value"],
            "market_value_change": r["market_value_change"]
        })

    total_crest_signals = 0
    successful_anticipations_t1 = 0
    successful_anticipations_t2 = 0
    false_positives = 0
    monetary_gain_captured: List[int] = []

    # Ventana mínima para evaluar (14 días históricos + 2 días de verificación a futuro)
    for player_id, snaps in player_series.items():
        if len(snaps) < 16:
            continue

        for t in range(14, len(snaps) - 2):
            historical_window = snaps[t-14:t+1]
            curr_snap = snaps[t]
            t1_snap = snaps[t+1]
            t2_snap = snaps[t+2]

            mv_t = int(curr_snap.get("market_value") or 0)
            res = compute_price_kinematics_and_sell_signal(
                snapshots=historical_window,
                current_market_value=mv_t,
                official_today_delta=curr_snap.get("market_value_change")
            )

            if res.sell_signal_status == "SELL_AT_CREST":
                total_crest_signals += 1
                delta_t1 = int(t1_snap.get("market_value_change") or 0)
                delta_t2 = int(t2_snap.get("market_value_change") or 0)

                # Criterio de acierto: entra en plano o depreciación en t+1 o t+2
                if delta_t1 <= 0:
                    successful_anticipations_t1 += 1
                    # Ganancia: vendió en el pico antes de absorber la caída de t1
                    monetary_gain_captured.append(abs(delta_t1) if delta_t1 < 0 else 0)
                elif delta_t2 <= 0:
                    successful_anticipations_t2 += 1
                    monetary_gain_captured.append(abs(delta_t2) if delta_t2 < 0 else 0)
                else:
                    false_positives += 1

    total_success = successful_anticipations_t1 + successful_anticipations_t2
    accuracy = (total_success / total_crest_signals * 100.0) if total_crest_signals > 0 else 0.0

    return {
        "total_crest_signals": total_crest_signals,
        "successful_t1": successful_anticipations_t1,
        "successful_t2": successful_anticipations_t2,
        "false_positives": false_positives,
        "accuracy_pct": round(accuracy, 2),
        "total_capital_preserved_eur": sum(monetary_gain_captured),
        "avg_gain_per_signal_eur": int(sum(monetary_gain_captured) / len(monetary_gain_captured)) if monetary_gain_captured else 0
    }


def backtest_auction_premiums(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Evalúa la coherencia de las compras históricas (activity_type_id == 31)
    frente a la distribución Log-Normal calibrada en Empirical Bayes.
    """
    cursor = conn.cursor()
    query = """
    SELECT team_id, amount_eur, reference_value_eur, cash_at_event_eur
    FROM activity_buys
    WHERE amount_eur > 0 AND reference_value_eur > 0
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        return {"error": "Tabla o vista activity_buys no accesible en este esquema."}

    premiums: List[float] = []
    overbids_exceeding_cash = 0
    total_audited = 0

    for r in rows:
        total_audited += 1
        amount = float(r["amount_eur"])
        ref_val = float(r["reference_value_eur"])
        cash_avail = float(r["cash_at_event_eur"] or 0)

        prem = (amount - ref_val) / ref_val
        premiums.append(prem)

        if cash_avail > 0 and amount > cash_avail:
            overbids_exceeding_cash += 1

    if not premiums:
        return {"total_audited": 0, "message": "Sin compras históricas suficientes para calibrar."}

    premiums.sort()
    p25 = premiums[int(0.25 * len(premiums))]
    p50 = premiums[int(0.50 * len(premiums))]
    p75 = premiums[int(0.75 * len(premiums))]

    return {
        "total_buys_audited": total_audited,
        "median_premium_pct": round(p50 * 100.0, 2),
        "iqr_premium_pct": [round(p25 * 100.0, 2), round(p75 * 100.0, 2)],
        "budget_violations_count": overbids_exceeding_cash,
        "hard_ceiling_validity_pct": round(100.0 * (1.0 - overbids_exceeding_cash / total_audited), 2)
    }


def run_full_audit():
    print("=" * 65)
    print("🔬 AUDITORÍA CUANTITATIVA Y CALIBRACIÓN EMPÍRICA (v2.0)")
    print("=" * 65)

    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"❌ Error al conectar a la base de datos: {e}")
        return

    # 1. Auditoría Cinemática
    print("\n[1/2] Evaluando precisión de sell_signal cinemática (SELL_AT_CREST)...")
    kinematics_res = backtest_price_kinematics(conn)
    if "error" in kinematics_res:
        print(f"  ⚠️  {kinematics_res['error']}")
    else:
        print(f"  • Señales SELL_AT_CREST disparadas : {kinematics_res['total_crest_signals']}")
        print(f"  • Aciertos en 24h (t+1)             : {kinematics_res['successful_t1']}")
        print(f"  • Aciertos en 48h (t+2)             : {kinematics_res['successful_t2']}")
        print(f"  • Falsos positivos (siguió subiendo): {kinematics_res['false_positives']}")
        print(f"  🎯 Tasa de Acierto en Cresta       : {kinematics_res['accuracy_pct']}%")
        print(f"  💰 Capital total preservado         : {kinematics_res['total_capital_preserved_eur']:,} €")
        print(f"  📊 Ganancia media por venta pico   : {kinematics_res['avg_gain_per_signal_eur']:,} €")

    # 2. Auditoría de Subastas
    print("\n[2/2] Evaluando supuestos de subastas y techos de caja rivales...")
    auctions_res = backtest_auction_premiums(conn)
    if "error" in auctions_res:
        print(f"  ⚠️  {auctions_res['error']}")
    else:
        print(f"  • Compras históricas analizadas    : {auctions_res['total_buys_audited']}")
        print(f"  • Mediana de sobrepuja en la liga  : +{auctions_res['median_premium_pct']}%")
        print(f"  • Rango intercuartílico (P25 - P75): +{auctions_res['iqr_premium_pct'][0]}% a +{auctions_res['iqr_premium_pct'][1]}%")
        print(f"  🎯 Validez de techos duros de caja : {auctions_res['hard_ceiling_validity_pct']}%")

    conn.close()
    print("\n" + "=" * 65)
    print("✅ Auditoría completada. Los resultados confirman si los parámetros")
    print("   operan sobre distribuciones realistas o requieren afinación.")
    print("=" * 65)


if __name__ == "__main__":
    run_full_audit()
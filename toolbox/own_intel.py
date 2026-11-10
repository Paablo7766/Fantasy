"""Motor propio de señales: puja, predicción de mercado, Poisson y E[pts] OPTA.

No inventa cifras: sin histórico suficiente o sin fixture/stats, el campo queda
ausente. Convive con ``af_*`` (Analítica Fantasy) como contraste.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from toolbox.cache import PriceSnapshotStore, madrid_day
from toolbox.matching import normalize_club, normalize_name
from toolbox.understat import (
    FDR_POINTS_MULT,
    HOME_POINTS_MULT,
    FixtureInfo,
    TeamRollingWindow,
    TeamStrength,
    build_hybrid_match_projection,
    resolve_rolling_window,
    stat_lambdas_for_fixture,
)

MIN_HISTORY_DAYS = 3
HISTORY_WINDOW = 14
SALE_BAND = 0.10
SECOND_LEG_DAMP = 0.75
OUTLIER_RATIO = 2.5
GOAL_POINTS = {"POR": 6.0, "DEF": 6.0, "MC": 5.0, "DEL": 4.0}
ASSIST_POINTS = 3.0
CS_POINTS = {"POR": 4.0, "DEF": 3.0, "MC": 2.0, "DEL": 1.0}
MINUTES_STARTER = 75.0
POISSON_GOAL_CAP = 8


@dataclass
class PriceKinematicsResult:
    price_delta_1: int
    price_delta_3: int
    price_delta_7: int
    velocity_ema3: float
    acceleration: int
    relative_acceleration: float
    jerk: int
    relative_exhaustion_index: float
    days_to_zero_crossing: float
    sell_signal: bool
    sell_signal_status: str
    predicted_next_delta: int


def compute_price_kinematics_and_sell_signal(
    snapshots: list[dict[str, Any]],
    current_market_value: int,
    official_today_delta: int | None = None,
    scraper_acceleration: float | None = None,
    allow_estimated_delta: bool = False,
) -> PriceKinematicsResult:
    """Cinemática de precios y sell_signal v2.0 desde ``price_snapshots`` (≤14 días).

    Todo lo que entra aquí tiene que ser medida propia (diferencia entre dos
    capturas de este proyecto) o el campo oficial de la API. Los deltas
    estimados por un tercero (FútbolFantasy) no pueden mover la serie: con
    ``allow_estimated_delta=False`` (por defecto) el ``sell_signal`` se bloquea
    en cuanto la serie dependa de una estimación. Solo se permite explícitamente
    para diagnóstico.
    """
    sorted_snaps = sorted(snapshots, key=lambda row: str(row.get("day") or ""))
    deltas: list[int] = []
    # Días cuyo delta no salió de restar dos capturas propias ni del campo
    # oficial: son la estimación de FútbolFantasy ya grabada en el histórico.
    estimated_days = 0

    for idx, snap in enumerate(sorted_snaps):
        if idx == 0:
            # La primera captura no se puede restar contra nada: no aporta delta
            # propio ni estimado. Meterla como estimación bloqueaba la señal de
            # venta aunque todas las medidas posteriores fueran propias.
            continue
        mv_change = snap.get("market_value_change")
        # La diferencia de ``market_value`` entre capturas es la verdad medida y
        # manda sobre la columna ``market_value_change``. Esa columna no es el
        # campo oficial de la API —no existe, ver CONTEXTO_ALGORITMO_ACTUAL.md—
        # y en el histórico ya grabado contiene la estimación de FútbolFantasy,
        # así que preferirla metería un dato de terceros en el motor. Cuando la
        # API publique un delta real, coincidirá con la diferencia medida si las
        # capturas son de días consecutivos; si hay un hueco de varios días, la
        # diferencia sigue siendo lo que de verdad pasó. Solo se usa el valor
        # guardado cuando no hay dos capturas que restar (la primera del tramo).
        value = snap.get("market_value")
        prev_value = sorted_snaps[idx - 1].get("market_value") if idx > 0 else None
        if idx > 0 and value is not None and prev_value is not None:
            deltas.append(int(value) - int(prev_value))
        elif idx > 0 and mv_change is not None:
            # ``market_value_change`` es el campo oficial de la API, no una
            # medida propia: entra solo si la fuente lo publica de verdad.
            deltas.append(int(mv_change))
            estimated_days += 1
        elif idx > 0:
            # Sin dos capturas que restar ni delta oficial: el hueco se rellena
            # con la estimación de terceros y la serie deja de ser propia.
            prev_mv = int(prev_value or current_market_value)
            curr_mv = int(value or current_market_value)
            deltas.append(curr_mv - prev_mv)
            estimated_days += 1

    # Dos capturas del mismo día (p. ej. 00:15 y 13:50) metían dos «días» de
    # movimiento en un solo tick: la velocidad, la aceleración y ``price_delta_3``
    # salían duplicados. Solo cuenta la última captura de cada día.
    if len(sorted_snaps) >= 2:
        same_day = str(sorted_snaps[-1].get("day") or "") == str(sorted_snaps[-2].get("day") or "")
        # El mismo día solo se descarta si ese delta salió de dos capturas
        # propias; si era la estimación de la primera captura del día, ese día
        # desaparece de la cuenta de estimados.
        last_is_estimated = same_day and (
            sorted_snaps[-1].get("market_value") is None or sorted_snaps[-2].get("market_value") is None
        )
        if same_day and deltas:
            deltas.pop()
            if last_is_estimated and estimated_days:
                estimated_days -= 1

    if official_today_delta is not None:
        # La reconstrucción por diferencia de valor es la verdad medida: si la
        # última captura ya es de hoy, el delta de hoy está dentro de ``deltas``.
        # Añadirlo otra vez duplicaba la serie (y con ella la aceleración y la
        # distancia al pico). Solo se usa cuando todavía no hay captura del día
        # en curso.
        last_day = str(sorted_snaps[-1].get("day") or "") if sorted_snaps else ""
        if last_day != madrid_day() and (not deltas or deltas[-1] != int(official_today_delta)):
            deltas.append(int(official_today_delta))

    if not deltas:
        deltas = [0]

    # Sin ceros de relleno delante: un delta clonado fabricaba inercia que la
    # serie no tiene (velocidad, aceleración y jerk salían de días inventados).
    # Con menos de cuatro medidas, las referencias se anulan.
    v_t = deltas[-1]
    v_t1 = deltas[-2] if len(deltas) >= 2 else 0
    v_t2 = deltas[-3] if len(deltas) >= 3 else 0

    price_delta_3 = int(v_t + v_t1 + v_t2)
    price_delta_7 = int(sum(deltas[-7:]))

    vel_ema3 = float((3.0 * v_t + 2.0 * v_t1 + 1.0 * v_t2) / 6.0)
    a_t = int(v_t - v_t1) if len(deltas) >= 2 else 0
    a_t1 = int(v_t1 - v_t2) if len(deltas) >= 3 else 0
    j_t = int(a_t - a_t1) if len(deltas) >= 3 else 0

    denom_rel = max(abs(v_t1), 10_000)
    rel_acc = float(a_t / denom_rel)

    window_7 = deltas[-7:]
    max_v_7 = max(window_7)
    prev_delta_3 = int(v_t1 + v_t2 + (deltas[-4] if len(deltas) >= 4 else 0))

    min_wave_peak = max(30_000, int(0.008 * max(current_market_value, 1_000_000)))
    in_significant_wave = (max_v_7 >= min_wave_peak) or (price_delta_3 >= min_wave_peak * 2)

    if max_v_7 > 0 and v_t > 0:
        rei_t = float(np.clip(1.0 - (v_t / float(max_v_7)), 0.0, 1.0))
    elif max_v_7 > 0 and v_t <= 0:
        rei_t = 1.0
    else:
        rei_t = 0.0

    a_eff = 0.65 * float(a_t) + 0.35 * float(a_t1) + 0.25 * float(min(0, j_t))
    if scraper_acceleration is not None and scraper_acceleration < 0 and a_eff >= 0:
        a_eff = -0.35 * float(max(abs(v_t), 20_000))

    if v_t > 0 and a_eff < -1_000.0:
        days_to_zero = float(-v_t / a_eff)
    elif v_t <= 0:
        days_to_zero = 0.0
    else:
        days_to_zero = 99.0

    pred_next_delta = int(round(v_t + 0.70 * a_t + 0.20 * min(0, j_t)))

    is_crest_exhaustion = (
        in_significant_wave
        and v_t > 0
        and price_delta_3 > 0
        and a_t < 0
        and (0.0 < days_to_zero <= 2.0)
        and (rei_t >= 0.38 or (a_t1 < 0 and rei_t >= 0.25))
    )

    had_prior_rise = (prev_delta_3 > 0) or (max_v_7 >= min_wave_peak)
    # También es giro confirmado que el día plano sea el PRIMERO sin subida
    # después de una ola significativa (v_t == 0 y antes subía). Antes solo
    # contaba la caída (v_t < 0) y una meseta tras el pico se quedaba en HOLD.
    is_confirmed_reversal = had_prior_rise and (
        v_t < 0 or (v_t == 0 and any(d > 0 for d in deltas[-4:]))
    )

    scraper_turn = scraper_acceleration is not None and scraper_acceleration < 0 and v_t > 0

    if is_crest_exhaustion or scraper_turn:
        sell_flag = True
        status = "SELL_AT_CREST"
        if scraper_turn:
            # El mismo signo que ``compute_bids`` ya usa (``a_eff``) debe verse
            # también en la predicción, o la señal dice HOLD con puja a la baja.
            pred_next_delta = min(pred_next_delta, -max(abs(v_t) // 4, 1))
    elif is_confirmed_reversal:
        sell_flag = True
        status = "SELL_CONFIRMED_REVERSAL"
    elif v_t > 0:
        sell_flag = False
        status = "HOLD_RISING"
    else:
        sell_flag = False
        status = "HOLD_STABLE"

    # Con ``market_value_change`` como respaldo, la serie puede arrastrar la
    # estimación de un tercero. Ahí no se puede afirmar una venta: la señal
    # queda bloqueada y el estado solo conserva el lado (sube / plano-cae).
    if estimated_days and not allow_estimated_delta:
        sell_flag = False
        status = "HOLD_RISING" if v_t > 0 else "HOLD_STABLE"

    return PriceKinematicsResult(
        price_delta_1=v_t,
        price_delta_3=price_delta_3,
        price_delta_7=price_delta_7,
        velocity_ema3=round(vel_ema3, 1),
        acceleration=a_t,
        relative_acceleration=round(rel_acc, 4),
        jerk=j_t,
        relative_exhaustion_index=round(rei_t, 4),
        days_to_zero_crossing=round(days_to_zero, 2),
        sell_signal=sell_flag,
        sell_signal_status=status,
        predicted_next_delta=pred_next_delta,
    )


def _apply_kinematics_to_player(player: dict[str, Any], kin: PriceKinematicsResult) -> None:
    player["price_delta_3"] = kin.price_delta_3
    player["price_delta_7"] = kin.price_delta_7
    player["velocity_ema3"] = kin.velocity_ema3
    player["price_acceleration"] = kin.acceleration
    if player.get("acceleration") is None:
        player["acceleration"] = kin.acceleration
    player["relative_acceleration"] = kin.relative_acceleration
    player["jerk"] = kin.jerk
    player["relative_exhaustion_index"] = kin.relative_exhaustion_index
    player["days_to_zero_crossing"] = kin.days_to_zero_crossing
    player["sell_signal"] = kin.sell_signal
    player["sell_signal_status"] = kin.sell_signal_status
    player["own_predicted_delta"] = kin.predicted_next_delta
    # Δ medido entre DOS capturas propias, que es lo único que este proyecto
    # puede afirmar como propio. El «oficial» de LaLiga (``market_value_change``)
    # no existe en la API, y lo que la UI pintaba como si lo fuera era la
    # estimación de FútbolFantasy. Se publica aparte para que el panel pueda
    # enseñar los dos sin disfrazar ninguno.
    player["measured_price_delta"] = kin.price_delta_1
    player["measured_price_delta_source"] = (
        "capturas_propias" if kin.price_delta_1 is not None else None
    )
    player["price_delta_estimated"] = _as_int(player.get("price_delta"))
    player["price_delta_is_estimate"] = player["price_delta_estimated"] is not None


def hours_until_kickoff(kickoff: str | None, *, now: datetime | None = None) -> float | None:
    if not isinstance(kickoff, str) or not kickoff.strip():
        return None
    text = kickoff.strip().replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    return max(0.0, (when - moment).total_seconds() / 3600.0)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value:
        return int(value)
    return None


# Backtest J9-J11 (233 jugadores-jornada con los dos, prior por precio ya activo):
# MAE 3,21 propio, 2,89 con 0,55 de AF, 2,78 solo AF. 0,55 deja margen al motor
# propio por el posible dato post-partido en el histórico de AF.
AF_XP_WEIGHT = 0.55
# Si AF supera al modelo en más de esto y el jugador viene rindiendo por debajo
# de ``AF_TOPE_RACHA``, la mezcla no pasa de ``xp_propio + AF_TOPE_SOBRE_PROPIO``.
AF_TOPE_DIFERENCIA = 2.2
AF_TOPE_RACHA = 6.0
AF_TOPE_SOBRE_PROPIO = 1.5


def _media_ultimos_jugados(player: dict[str, Any], partidos: int = 3) -> float | None:
    """Media de puntos de sus últimos ``partidos`` con minutos; None sin historial."""
    from toolbox.engine.xp_calculator import historial_desde_jugador

    jugados = [p.puntos for p in sorted(historial_desde_jugador(player), key=lambda p: p.jornada) if p.minutos != 0]
    jugados = jugados[-partidos:]
    return sum(jugados) / len(jugados) if jugados else None


def _condicional_tras_mezcla(player: dict[str, Any], condicional: Any) -> Any:
    """«Si titular» en la misma escala que el xP ya mezclado con AF.

    Se reescala con el mismo cociente que la mezcla y nunca queda por debajo
    del xP de jornada: condicionado a salir de inicio no puede valer menos.
    """
    valor = _as_float(condicional)
    if valor is None:
        return condicional
    propio = _as_float(player.get("own_xp_modelo"))
    mezcla = _as_float(player.get("own_expected_points"))
    if mezcla is None:
        return condicional
    if propio is not None and propio > 0.1 and player.get("own_xp_fuente") == "af_mezcla":
        valor = valor * (mezcla / propio)
    return round(max(valor, mezcla), 3)


def _mezclar_xp_af(player: dict[str, Any]) -> None:
    """Pasa el xP de la próxima jornada a ``AF_XP_WEIGHT`` de AF y el resto propio.

    Deja el del modelo propio en ``own_xp_modelo`` para medir ambos. Los xP de
    las jornadas siguientes se reescalan con el mismo cociente para que
    ``xp_4_jornadas`` no mezcle dos escalas.
    """
    propio = _as_float(player.get("own_expected_points"))
    af = _as_float(player.get("af_expected_points"))
    if propio is None:
        return
    player["own_xp_modelo"] = propio
    if af is None or af < 0 or not math.isfinite(af):
        return
    mezcla = AF_XP_WEIGHT * af + (1.0 - AF_XP_WEIGHT) * propio
    if af - propio > AF_TOPE_DIFERENCIA:
        racha = _media_ultimos_jugados(player)
        if racha is not None and racha < AF_TOPE_RACHA:
            mezcla = min(mezcla, propio + AF_TOPE_SOBRE_PROPIO)
            player["own_xp_tope_af"] = True
    player["own_expected_points"] = round(mezcla, 3)
    player["own_xp_fuente"] = "af_mezcla"
    techo = _as_float(player.get("own_ceiling_points"))
    if techo is not None and techo < mezcla:
        player["own_ceiling_points"] = round(mezcla, 3)
    futuros = player.get("_own_xp_siguientes")
    ratio = ratio_mezcla_futuros(player, propio, mezcla)
    if isinstance(futuros, list) and futuros and ratio != 1.0:
        player["_own_xp_siguientes"] = [round(float(v) * ratio, 3) for v in futuros]


# El cociente AF/propio de esta jornada corrige el nivel del jugador en las tres
# siguientes. Acotado: con un propio muy bajo (duda, banquillo) el cociente
# dispararía J2-J4 por algo que solo afecta a esta jornada.
RATIO_FUTUROS_MIN = 0.7
RATIO_FUTUROS_MAX = 1.3
PROPIO_MINIMO_RATIO = 1.0


def ratio_mezcla_futuros(player: dict[str, Any], propio: float, mezcla: float) -> float:
    """Factor que lleva J2-J4 a la escala de la mezcla con AF.

    Si esta jornada el jugador está en duda, sancionado, fuera del once o con
    el propio casi a cero, la diferencia con AF habla de la disponibilidad de
    hoy, no de su nivel: J2-J4 se quedan como están.
    """
    if propio < PROPIO_MINIMO_RATIO or player.get("_own_baja_puntual"):
        return 1.0
    return min(RATIO_FUTUROS_MAX, max(RATIO_FUTUROS_MIN, mezcla / propio))


def _actas_en_cache() -> dict[str, dict[str, Any]]:
    """Puntos y minutos por jornada de ``playerMaster.lastStats``.

    Sin esto el motor no ve el historial del jugador: la serie ``week_points``
    no trae minutos y no sirve para separar titular de revulsivo, así que el xP
    salía del prior del puesto para todos. Une los cuerpos del scraper en disco
    con el almacén acumulado de actas (``player_history``).
    """
    from toolbox.player_history import actas_en_cache

    return actas_en_cache()


def _inyectar_actas(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pone ``historial`` (puntos, minutos, jornada) en quien no lo trae. Devuelve a quién."""
    actas = _actas_en_cache()
    puestos: list[dict[str, Any]] = []
    for player in players:
        pid = player.get("player_id")
        if not isinstance(pid, str) or player.get("historial"):
            continue
        entry = actas.get(pid)
        if not entry or not entry.get("weeks"):
            continue
        player["historial"] = [
            {"puntos": pts, "minutos": int(mins), "jornada": week}
            for week, (pts, mins) in sorted(entry["weeks"].items())
        ]
        puestos.append(player)
    _rellenar_week_points(players)
    return puestos


def _rellenar_week_points(players: list[dict[str, Any]]) -> None:
    """``week_points`` del catálogo para quien llega sin serie (típico del mercado).

    Los fichajes del mercado no traen ``lastStats``; el catálogo sí guarda sus
    puntos por jornada. Sin minutos no corrigen el xP, pero sirven para el tope
    de la mezcla con AF y para la forma de la nota de mercado.
    """
    faltan = [
        p for p in players if isinstance(p.get("player_id"), str) and not p.get("week_points") and not p.get("historial")
    ]
    if not faltan:
        return
    try:
        from toolbox.normalize import normalize_catalog
        from toolbox.quant_valuation import cached_catalog

        catalogo = {str(row.get("player_id")): row for row in normalize_catalog(cached_catalog())}
    except Exception:  # noqa: BLE001 — sin catálogo se queda como estaba
        return
    for player in faltan:
        serie = (catalogo.get(player["player_id"]) or {}).get("week_points")
        if isinstance(serie, list) and serie:
            player["week_points"] = [float(v) for v in serie if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _vista_consenso_bajo(player: dict[str, Any]) -> dict[str, Any]:
    """Copia del jugador sin la media histórica de minutos si AF y FF lo dan de banquillo.

    ``compute_expected_opta_points_v2`` reparte la probabilidad de entrar desde
    el banquillo con ``minutes_pct``: un titular habitual que ahora es duda
    mantendría un 20 % de minutos por historia. Con consenso bajo manda el %
    del once probable.
    """
    if player.get("p_titular_consenso") != "bajo":
        return player
    p = _as_float(player.get("p_titular")) or 0.0
    form = player.get("form") if isinstance(player.get("form"), dict) else {}
    return {**player, "form": {**form, "minutes_pct": p}}


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number
    return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def deltas_from_history(history: list[dict[str, Any]]) -> list[int]:
    """Deltas de un delta por día civil, medidos entre capturas.

    La columna ``market_value_change`` no es el campo oficial de la API (no
    existe) y en el histórico ya grabado contiene la estimación de
    FútbolFantasy; se usa solo como respaldo cuando no hay dos valores que
    restar. Con capturas de días consecutivos, la diferencia es exactamente el
    cambio del día; con un hueco de varios días, es lo que de verdad pasó.

    Varias capturas del mismo día (p. ej. 00:15 y 13:50) cuentan como una
    sola: antes se emitía un delta por captura, es decir, más «días» que los
    reales, y eso inflaba ``MIN_HISTORY_DAYS``, ``project_rate`` y la ventana
    de la cinemática.
    """
    if not history:
        return []
    ordered = sorted(history, key=lambda row: str(row.get("day") or ""))
    deltas: list[int] = []
    prev_day: str | None = None
    prev_value: int | None = None
    for row in ordered:
        day = str(row.get("day") or "")
        change = _as_int(row.get("market_value_change"))
        value = _as_int(row.get("market_value"))
        same_day = day == prev_day and deltas
        if same_day:
            # Corrige el delta que ya se metió con la captura anterior del día.
            deltas.pop()
            if value is not None and prev_value is not None:
                deltas.append(value - prev_value)
            elif change is not None:
                deltas.append(change)
        elif value is not None and prev_value is not None:
            deltas.append(value - prev_value)
        elif change is not None:
            deltas.append(change)
        if value is not None:
            prev_value = value
        prev_day = day
    return deltas


def project_rate(deltas: list[int], *, today_delta: int | None = None) -> float | None:
    """Ritmo de proyección: mediana reciente; outlier del día → media."""
    if len(deltas) < MIN_HISTORY_DAYS:
        return None
    recent = [float(d) for d in deltas[-HISTORY_WINDOW:]]
    med = _median(recent)
    avg = _mean(recent)
    if med is None or avg is None:
        return None
    spot = float(today_delta) if today_delta is not None else recent[-1]
    # Salto puntual o cambio de signo brusco: no proyectar sobre el outlier.
    if abs(avg) > 1 and abs(spot) > OUTLIER_RATIO * abs(avg):
        return avg
    if avg != 0 and spot * avg < 0 and abs(spot) > abs(avg):
        return avg
    return med


def markets_until_kickoff(kickoff: str | None, *, now: datetime | None = None) -> int | None:
    """Mercados diarios restantes hasta el partido (00:15 Europe/Madrid ≈ un tick/día)."""
    if not isinstance(kickoff, str) or not kickoff.strip():
        return None
    text = kickoff.strip().replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    madrid = ZoneInfo("Europe/Madrid")
    today = moment.astimezone(madrid).date()
    match_day = when.astimezone(madrid).date()
    days = (match_day - today).days
    if days < 0:
        return 0
    return days


def compute_bids(
    *,
    price: int,
    rate: float,
    days: int,
    expected_points: float | None = None,
    jornada_avg_points: float | None = None,
    history_values: list[int] | None = None,
    falling: bool = False,
    unavailable: bool = False,
) -> tuple[int, int]:
    """Puja ideal (mitad de camino) y máxima (día del partido), con amortiguamiento."""
    if unavailable or price <= 0:
        return price, price
    if falling or rate <= 0:
        # Ideal = precio; la máxima admite sobrepujar por el margen de caída que
        # queda hasta el partido. Con días por delante, pujar al valor de hoy no
        # compra un jugador que baja: la oferta de venta estará por debajo.
        fall = abs(rate) * max(days, 0)
        ideal = price
        if days > 0:
            # Valor de venta esperado (ya con la caída) más medio margen de
            # sobrepuja, siempre por encima del precio de hoy.
            expected_sale = max(0.0, float(price) - fall)
            maximum = max(price, int(round(expected_sale + fall * 0.5)))
            if maximum <= price:
                maximum = price + int(round(fall * 0.25)) if fall > 0 else price
        else:
            maximum = price
        if maximum < ideal:
            maximum = ideal
        return ideal, maximum

    half = max(days, 0) / 2.0
    full = float(max(days, 0))
    # Proyección ideal: mitad del recorrido.
    ideal_raw = price + rate * half
    # Máx: primeros min(days,5) a rate, resto amortiguado.
    if full <= 5:
        max_raw = price + rate * full
    else:
        max_raw = price + rate * 5.0 + rate * SECOND_LEG_DAMP * (full - 5.0)

    # Ajuste por pts relativos + distancia al máximo histórico, cap 10%.
    adjust = 0.0
    band = SALE_BAND * price
    if expected_points is not None and jornada_avg_points is not None and jornada_avg_points > 0:
        # Escala en puntos absolutos (1 pt +0,35): antes se dividía por la media
        # de jornada (que aquí es la media de *jugadores*, ~1 pt) y cualquier
        # diferencial de 1 punto rozaba el clip de ±100 %.
        adjust += (float(expected_points) - float(jornada_avg_points)) * 0.35
    if history_values:
        peak = max(history_values)
        if peak > price > 0:
            room = (peak - price) / peak
            adjust += room * 0.25
        elif peak > 0 and price >= peak:
            adjust -= 0.15
    # En franja alta el ajuste se atenúa.
    if price >= 80_000_000:
        adjust *= 0.25
    elif price >= 40_000_000:
        adjust *= 0.5
    adjust = max(-1.0, min(1.0, adjust))
    shift = band * adjust * 0.4
    ideal = int(round(ideal_raw + shift))
    maximum = int(round(max_raw + shift * 0.5))
    ideal = max(price, ideal)
    maximum = max(ideal, maximum)
    # No salir de la banda de venta sobre la proyección base.
    ideal = min(ideal, int(round(ideal_raw + band)))
    maximum = min(maximum, int(round(max_raw + band)))
    ideal = max(price, ideal)
    maximum = max(ideal, maximum)
    return ideal, maximum


def compute_market_signal(
    *,
    rate: float,
    today_delta: int | None,
    fitness: str | None = None,
    form_score: float | None = None,
    universe_abs: list[float] | None = None,
) -> tuple[str, float, int]:
    """Devuelve (direction, strength 0..1, predicted_delta)."""
    base = float(today_delta) if today_delta is not None else rate
    # Forma positiva refuerza subida; lesión frena.
    if isinstance(fitness, str):
        low = fitness.lower()
        if "lesion" in low or "sancion" in low or "sanction" in low:
            base *= 0.35
        elif "duda" in low:
            base *= 0.7
    if form_score is not None:
        # form_score ~ media pts reciente centrada en 5.
        base += (form_score - 5.0) * 20_000.0

    predicted = int(round(base))
    if predicted == 0:
        predicted = 1 if rate > 0 else -1 if rate < 0 else 0
    direction = "up" if predicted > 0 else "down" if predicted < 0 else "up"
    magnitude = abs(float(predicted))
    ref = _median([abs(v) for v in (universe_abs or []) if v]) or magnitude or 1.0
    strength = min(1.0, magnitude / max(ref, 1.0))
    return direction, round(strength, 4), predicted


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def match_outcome_probs(lambda_home: float, lambda_away: float) -> dict[str, Any]:
    """P(W/D/L) desde el punto de vista del local + marcador modal."""
    win = draw = loss = 0.0
    best_p = -1.0
    best_h = best_a = 0
    exp_diff = 0.0
    for h in range(POISSON_GOAL_CAP + 1):
        ph = poisson_pmf(h, max(0.05, lambda_home))
        for a in range(POISSON_GOAL_CAP + 1):
            pa = poisson_pmf(a, max(0.05, lambda_away))
            p = ph * pa
            exp_diff += (h - a) * p
            if h > a:
                win += p
            elif h == a:
                draw += p
            else:
                loss += p
            if p > best_p:
                best_p = p
                best_h, best_a = h, a
    total = win + draw + loss
    if total > 0:
        win, draw, loss = win / total, draw / total, loss / total
    return {
        "win": round(win, 4),
        "draw": round(draw, 4),
        "loss": round(loss, 4),
        "predicted_home": best_h,
        "predicted_away": best_a,
        "expected_diff": round(exp_diff, 4),
    }


def recommendation_pct(win: float, draw: float, expected_diff: float) -> int:
    """% favorable para alinear: gana + 0.45*empate + bonus de diferencia."""
    raw = 100.0 * (win + 0.45 * draw) + max(-10.0, min(15.0, expected_diff * 4.0))
    return int(max(1, min(99, round(raw))))


def difficulty_label(rec: int) -> str:
    # Un partido igualado (1-1 previsto) da ~45-53: es "media", no "difícil".
    # Los cortes antiguos (72/54/38) dejaban casi todo el calendario en difícil.
    if rec >= 80:
        return "muy_facil"
    if rec >= 62:
        return "facil"
    if rec >= 42:
        return "media"
    if rec >= 28:
        return "dificil"
    return "muy_dificil"


def team_lambdas(
    team: TeamStrength | None,
    opponent: TeamStrength | None,
    *,
    home: bool,
    league_avg_xg: float,
) -> tuple[float, float]:
    """λ del equipo y del rival para este partido."""
    attack = team.avg_xg if team else league_avg_xg
    defence = team.avg_xga if team else league_avg_xg
    opp_attack = opponent.avg_xg if opponent else league_avg_xg
    opp_defence = opponent.avg_xga if opponent else league_avg_xg
    base = max(0.2, league_avg_xg)
    # Ataque propio × defensa rival / media, con pequeño boost local.
    lam_for = max(0.15, attack * (opp_defence / base))
    lam_against = max(0.15, opp_attack * (defence / base))
    if home:
        lam_for *= 1.08
        lam_against *= 0.95
    else:
        lam_for *= 0.95
        lam_against *= 1.08
    return lam_for, lam_against


def build_team_calendar_cell(
    *,
    team_name: str,
    fixture: FixtureInfo,
    team: TeamStrength | None,
    opponent: TeamStrength | None,
    league_avg_xg: float,
    matchday: int = 0,
    odds_1x2: tuple[float, float, float] | None = None,
    odds_ou25: tuple[float, float] | None = None,
    odds_btts: tuple[float, float] | None = None,
    hours_to_kickoff: float | None = None,
    home_rolling: TeamRollingWindow | None = None,
    away_rolling: TeamRollingWindow | None = None,
) -> dict[str, Any]:
    if fixture.home:
        home_team, away_team = team, opponent
    else:
        home_team, away_team = opponent, team

    lambda_stat_h, lambda_stat_a = stat_lambdas_for_fixture(
        home_team=home_team,
        away_team=away_team,
        home_rolling=home_rolling,
        away_rolling=away_rolling,
        league_avg_xg=league_avg_xg,
    )

    htk = hours_to_kickoff if hours_to_kickoff is not None else 48.0
    w_mkt = None
    if odds_1x2 is not None:
        w_mkt = round(0.55 + (0.82 - 0.55) * math.exp(-max(0.0, htk) / 72.0), 4)
    projection = build_hybrid_match_projection(
        lambda_stat_h,
        lambda_stat_a,
        odds_1x2=odds_1x2,
        odds_ou25=odds_ou25,
        odds_btts=odds_btts,
        hours_to_kickoff=htk,
    )

    if fixture.home:
        lam_for, lam_against = projection.lambda_home, projection.lambda_away
        win, draw, loss = projection.p_home_win, projection.p_draw, projection.p_away_win
        rec = projection.recommendation_pct_home
        exp_diff = projection.lambda_home - projection.lambda_away
    else:
        lam_for, lam_against = projection.lambda_away, projection.lambda_home
        win, draw, loss = projection.p_away_win, projection.p_draw, projection.p_home_win
        rec = projection.recommendation_pct_away
        exp_diff = projection.lambda_away - projection.lambda_home

    probs = match_outcome_probs(lam_for, lam_against)
    if fixture.home:
        score = f"{probs['predicted_home']}-{probs['predicted_away']}"
    else:
        score = f"{probs['predicted_away']}-{probs['predicted_home']}"

    return {
        "matchday": matchday,
        "opponent": fixture.opponent,
        "is_home": fixture.home,
        "predicted_score": score,
        "recommendation_pct": rec,
        "difficulty": difficulty_label(rec),
        "win_prob": round(win, 4),
        "draw_prob": round(draw, 4),
        "loss_prob": round(loss, 4),
        "lambda_for": round(lam_for, 4),
        "lambda_against": round(lam_against, 4),
        "rho_dc": round(projection.rho_dc, 4),
        "p_cs_for": round(projection.p_cs_home if fixture.home else projection.p_cs_away, 4),
        "market_weight": w_mkt,
        "kickoff": fixture.kickoff,
        "team_name": team_name,
    }


# --- E[pts] OPTA ---


def _goal_share(player_xg: float | None, team_xg: float | None) -> float:
    if player_xg is None or team_xg is None or team_xg <= 0:
        return 0.18  # prior genérico de delantero medio; se atenúa por posición fuera
    return max(0.02, min(0.55, player_xg / max(team_xg, 0.01)))


def expected_opta_points(
    *,
    position: str | None,
    p_titular: float | None,
    player_xg: float | None,
    player_xa: float | None,
    team_lambda: float | None,
    opp_lambda: float | None,
    team_avg_xg: float | None,
    home: bool = False,
    fdr: int | None = None,
    n_sims: int = 40,
    player: dict[str, Any] | None = None,
    p_cs_own: float | None = None,
    monte_carlo: bool = True,
    rival: str | None = None,
) -> dict[str, float | None]:
    """E[Pts] OPTA v2 + techo Monte Carlo (P90) y P(gol)/P(asist).

    ``monte_carlo=False`` se salta el techo: para las jornadas siguientes solo
    hace falta la media y la simulación es lo caro.
    """
    from toolbox.opta_points_v2 import MC_SIMS_DEFAULT, compute_expected_opta_points_v2

    if p_titular is None and player_xg is None and player_xa is None:
        return {
            "expected_points": None,
            "ceiling_points": None,
            "goal_probability": None,
            "assist_probability": None,
        }
    pos = position if position in GOAL_POINTS else "MC"
    base_player = dict(player) if isinstance(player, dict) else {}
    form = base_player.get("form") if isinstance(base_player.get("form"), dict) else {}
    form = {
        **form,
        "xg": player_xg if player_xg is not None else form.get("xg"),
        "xa": player_xa if player_xa is not None else form.get("xa"),
        "fdr": fdr if fdr is not None else form.get("fdr"),
        "home": home if home else form.get("home"),
    }
    payload = {
        **base_player,
        "position": pos,
        "rival": rival,
        "p_titular": p_titular,
        "form": form,
        "sanction": base_player.get("sanction") if isinstance(base_player.get("sanction"), dict) else {},
    }
    result = compute_expected_opta_points_v2(
        payload,
        lambda_own=float(team_lambda) if team_lambda is not None else 1.32,
        lambda_opp=float(opp_lambda) if opp_lambda is not None else 1.32,
        p_cs_own=p_cs_own,
        run_monte_carlo=monte_carlo,
        n_sims=n_sims if n_sims > 100 else MC_SIMS_DEFAULT,
    )
    return {
        "expected_points": result["expected_points"],
        "ceiling_points": result["ceiling_points"],
        "xp_condicional": result.get("xp_condicional"),
        "goal_probability": result.get("goal_probability"),
        "assist_probability": result.get("assist_probability"),
        "p_start_eff": result.get("p_start_eff"),
        "expected_minutes": result.get("expected_minutes"),
        "inferred_bonus": result.get("inferred_bonus"),
        "next_match_survival": result.get("next_match_survival"),
        # xP 2.0: de dónde sale el número (suelo, gol, asistencia, portería).
        "xp_modelo": result.get("xp_modelo"),
        "xp_desglose": result.get("xp_desglose"),
        "xp_breakout": result.get("xp_breakout"),
        "xp_balon_parado": result.get("xp_balon_parado"),
        "xp_ajuste_rival": result.get("xp_ajuste_rival"),
        "xp_ajuste_club": result.get("xp_ajuste_club"),
        "xp_cambio_cronico": result.get("xp_cambio_cronico"),
        "xp_produccion_pura_90": result.get("xp_produccion_pura_90"),
        "xp_suelo_muro": result.get("xp_suelo_muro"),
    }


_PARTIDOS_SANCION = re.compile(r"(\d+)\s*(?:partidos?|jornadas?|matches|games)", re.IGNORECASE)


def _texto_contiene(value: Any, *tokens: str) -> bool:
    return isinstance(value, str) and any(token in value.lower() for token in tokens)


def jugador_tras_sancion(player: dict[str, Any]) -> tuple[dict[str, Any], float | None, int] | None:
    """Sanción que acaba: el jugador como estará cuando la cumpla.

    Devuelve ``(jugador, p_titular, partidos)``: una copia sin la sanción, su
    titularidad de siempre (la de su historial, no el 0 de esta semana) y
    cuántos partidos se pierde (1 si la fuente no lo dice). Una lesión no
    tiene fecha de vuelta, así que con lesión, o sin sanción, devuelve None.
    """
    sanction = player.get("sanction") if isinstance(player.get("sanction"), dict) else {}
    status = str(player.get("player_status") or "").lower()
    sancionado = bool(
        sanction.get("suspended")
        or player.get("af_suspension")
        or status in {"suspended", "sancionado"}
        or _texto_contiene(player.get("fitness"), "sancion", "sanción", "sanction")
    )
    if not sancionado:
        return None
    lesionado = bool(
        player.get("af_injury")
        or status in {"injured", "lesionado"}
        or _texto_contiene(player.get("fitness"), "lesion", "lesión", "injured")
    )
    if lesionado:
        return None
    partidos = 1
    for key in ("matches", "partidos", "games"):
        value = _as_int(sanction.get(key))
        if value is not None and value > 0:
            partidos = value
            break
    else:
        suspension = player.get("af_suspension") if isinstance(player.get("af_suspension"), dict) else {}
        for text in (player.get("fitness_detail"), suspension.get("info"), suspension.get("report")):
            match = _PARTIDOS_SANCION.search(text) if isinstance(text, str) else None
            if match:
                partidos = max(1, int(match.group(1)))
                break
    from toolbox.engine.xp_calculator import FantasyXPEngine, historial_desde_jugador

    p_titular = FantasyXPEngine.prob_titular_heuristica(historial_desde_jugador(player))
    if p_titular is None:
        raw = _as_float(player.get("p_titular"))
        p_titular = raw if raw is not None and raw > 0 else None
    limpio = {key: value for key, value in player.items() if key != "af_suspension"}
    limpio["sanction"] = {**sanction, "suspended": False}
    limpio["p_titular"] = p_titular
    if status in {"suspended", "sancionado"}:
        limpio["player_status"] = "ok"
    # Sin rastro de lesión, un «baja» en el parte es la propia sanción.
    if _texto_contiene(player.get("fitness"), "sancion", "sanción", "sanction", "baja", "out"):
        limpio["fitness"] = None
    return limpio, p_titular, partidos


def _supervivencia_apercibido(pts: dict[str, Any], player: dict[str, Any]) -> float:
    """Probabilidad de llegar a J2 sin sanción: ``1 − P(titular)·P(amarilla)`` si está apercibido."""
    sancion = player.get("sanction") if isinstance(player.get("sanction"), dict) else {}
    if not sancion.get("on_verge"):
        return 1.0
    valor = _as_float(pts.get("next_match_survival"))
    if valor is None:
        return 1.0
    return min(1.0, max(0.0, valor))


#: Fuera del once probable sin lesión: en J2-J4 la titularidad vuelve a medio
#: camino entre la de esta semana y la de su historial (puede ser decisión técnica).
PESO_HISTORIAL_FUERA_DEL_ONCE = 0.5
_LINEUP_FUERA = {"suplente", "fuera"}


def _lesionado(player: dict[str, Any]) -> bool:
    status = str(player.get("player_status") or "").lower()
    return bool(
        player.get("af_injury")
        or status in {"injured", "lesionado"}
        or _texto_contiene(player.get("fitness"), "lesion", "lesión", "injured")
    )


def jugador_tras_duda(player: dict[str, Any]) -> tuple[dict[str, Any], float] | None:
    """El jugador en J2-J4 cuando esta semana solo es duda o se queda fuera del once.

    Una duda (golpe, molestias) afecta a esta jornada: en las siguientes vuelve
    su titularidad de siempre, la que sale de su historial. Quien se cae del
    once probable sin estar lesionado recupera la mitad del camino. Con lesión
    (sin fecha de vuelta) o sin historial, devuelve None y J2-J4 siguen igual.
    """
    from toolbox.analyzer import _source_is_doubtful
    from toolbox.engine.xp_calculator import FantasyXPEngine, historial_desde_jugador

    if _lesionado(player):
        return None
    duda = _source_is_doubtful(player)
    lineup = str(player.get("lineup_status") or "").strip().lower()
    raw = _as_float(player.get("p_titular"))
    if raw is not None and raw > 1.0:
        raw /= 100.0
    fuera = lineup in _LINEUP_FUERA and (raw is None or raw < 0.5)
    if not duda and not fuera:
        return None
    normal = FantasyXPEngine.prob_titular_heuristica(historial_desde_jugador(player))
    if normal is None:
        return None
    if duda:
        p_futuro = max(normal, raw or 0.0)
    else:
        p_futuro = PESO_HISTORIAL_FUERA_DEL_ONCE * normal + (1.0 - PESO_HISTORIAL_FUERA_DEL_ONCE) * (raw or 0.0)
    limpio = dict(player)
    for key in ("player_status", "fitness", "lineup_status", "p_titular_consenso"):
        limpio.pop(key, None)
    limpio["p_titular"] = round(p_futuro, 4)
    return limpio, round(p_futuro, 4)


def snapshot_rows_from_players(
    players: list[dict[str, Any]],
    *,
    league_id: str | None,
    day: str | None = None,
) -> list[dict[str, Any]]:
    stamp = day or madrid_day()
    rows: list[dict[str, Any]] = []
    for player in players:
        pid = player.get("player_id")
        if not isinstance(pid, str) or not pid:
            continue
        value = _as_int(player.get("fantasy_price") if player.get("fantasy_price") is not None else player.get("market_value"))
        # Solo la variación oficial de la API. ``price_delta`` es la estimación de
        # FútbolFantasy y NO puede guardarse en la columna oficial: mezclarlas
        # dejaba un histórico que parece oficial y no lo es. Si la fuente no
        # publica el campo, la columna queda nula y el delta se reconstruye con
        # la diferencia de ``market_value`` entre días.
        change = _as_int(player.get("market_value_change"))
        if value is None and change is None:
            continue
        rows.append(
            {
                "player_id": pid,
                "day": stamp,
                "league_id": league_id,
                "market_value": value,
                "market_value_change": change,
            }
        )
    return rows


def catalog_snapshot_rows(
    catalog: list[dict[str, Any]] | None,
    *,
    already: set[str],
    league_id: str | None,
    day: str | None = None,
) -> list[dict[str, Any]]:
    """Filas de precio de los jugadores del catálogo que no están en plantillas ni mercado.

    ``snapshot_rows_from_players`` solo archivaba plantillas y anuncios del día:
    el resto de libres llegaba al mercado sin serie previa. El catálogo
    (``/competition/1/players``) trae el ``marketValue`` de los ~880 fichas.
    Los ids de ``already`` ya tienen fila (con valor oficial del mercado/plantilla)
    y no se tocan.
    """
    pendientes = [
        row
        for row in (catalog or [])
        if isinstance(row, dict)
        and isinstance(row.get("player_id"), str)
        and row["player_id"] not in already
        and row.get("player_status") != "out_of_league"
        and _as_int(row.get("market_value")) not in (None, 0)
    ]
    return snapshot_rows_from_players(pendientes, league_id=league_id, day=day)


def _strength_for(
    fixture: FixtureInfo,
    strength_map: dict[str, TeamStrength],
    unique_strengths: dict[int, TeamStrength],
) -> TeamStrength | None:
    """Fuerza del rival de ``fixture``: por id de Understat y, si no, por nombre."""
    if fixture.opponent_id:
        for strength in unique_strengths.values():
            if strength.team_id == fixture.opponent_id:
                return strength
    if fixture.opponent:
        return strength_map.get(normalize_club(fixture.opponent)) or strength_map.get(normalize_name(fixture.opponent))
    return None


def apply_own_intel(
    players: list[dict[str, Any]],
    *,
    histories: dict[str, list[dict[str, Any]]],
    fixtures_by_club: dict[str, FixtureInfo] | None = None,
    strengths: dict[str, TeamStrength] | None = None,
    team_rolling: dict[str, TeamRollingWindow] | None = None,
    match_odds: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rellena ``own_*`` en cada jugador. Devuelve summary + sources status."""
    con_actas = _inyectar_actas(players)
    fixtures = fixtures_by_club or {}
    strength_map = strengths or {}
    unique_strengths = {id(v): v for v in strength_map.values()}
    league_vals = [s.avg_xg for s in unique_strengths.values() if s.avg_xg > 0]
    league_avg_xg = sum(league_vals) / len(league_vals) if league_vals else 1.25

    # Precompute calendar cells by club.
    calendar_by_club: dict[str, dict[str, Any]] = {}
    for club_key, fixture in fixtures.items():
        team = strength_map.get(club_key)
        opp = None
        if fixture.opponent_id:
            for s in unique_strengths.values():
                if s.team_id == fixture.opponent_id:
                    opp = s
                    break
        if opp is None and fixture.opponent:
            opp = strength_map.get(normalize_club(fixture.opponent)) or strength_map.get(
                normalize_name(fixture.opponent)
            )
        team_name = team.title if team else club_key
        htk = hours_until_kickoff(fixture.kickoff, now=now)
        if fixture.home:
            home_key, away_key = club_key, normalize_club(fixture.opponent)
        else:
            home_key, away_key = normalize_club(fixture.opponent), club_key
        odds_bundle = (match_odds or {}).get(f"{home_key}|{away_key}")
        home_roll = resolve_rolling_window(team if fixture.home else opp, team_rolling, home_key)
        away_roll = resolve_rolling_window(opp if fixture.home else team, team_rolling, away_key)
        odds_1x2 = odds_bundle.get("odds_1x2") if isinstance(odds_bundle, dict) else None
        odds_ou25 = odds_bundle.get("odds_ou25") if isinstance(odds_bundle, dict) else None
        odds_btts = odds_bundle.get("odds_btts") if isinstance(odds_bundle, dict) else None
        calendar_by_club[club_key] = build_team_calendar_cell(
            team_name=team_name,
            fixture=fixture,
            team=team,
            opponent=opp,
            league_avg_xg=league_avg_xg,
            hours_to_kickoff=htk if htk is not None else 48.0,
            odds_1x2=odds_1x2 if isinstance(odds_1x2, tuple) else None,
            odds_ou25=odds_ou25 if isinstance(odds_ou25, tuple) else None,
            odds_btts=odds_btts if isinstance(odds_btts, tuple) else None,
            home_rolling=home_roll,
            away_rolling=away_roll,
        )

    # J2-J4 con el mismo Poisson, sin cuotas: las casas aún no las publican y
    # la forma (rolling) es la de hoy. Es la proyección que antes se pedía a
    # AnalíticaFantasy, que solo trae una o dos jornadas.
    siguientes_by_club: dict[str, list[tuple[FixtureInfo, dict[str, Any]]]] = {}
    for club_key, fixture in fixtures.items():
        team = strength_map.get(club_key)
        for offset, later in enumerate(fixture.siguientes, start=1):
            opp = _strength_for(later, strength_map, unique_strengths)
            home_key = club_key if later.home else normalize_club(later.opponent)
            away_key = normalize_club(later.opponent) if later.home else club_key
            cell = build_team_calendar_cell(
                team_name=team.title if team else club_key,
                fixture=later,
                team=team,
                opponent=opp,
                league_avg_xg=league_avg_xg,
                matchday=offset,
                hours_to_kickoff=hours_until_kickoff(later.kickoff, now=now),
                home_rolling=resolve_rolling_window(team if later.home else opp, team_rolling, home_key),
                away_rolling=resolve_rolling_window(opp if later.home else team, team_rolling, away_key),
            )
            siguientes_by_club.setdefault(club_key, []).append((later, cell))

    # Primera pasada: pts esperados para media de jornada (ajuste de puja).
    prelim_points: dict[str, float] = {}
    for player in players:
        pid = player.get("player_id")
        if not isinstance(pid, str):
            continue
        club = player.get("club")
        club_key = normalize_club(str(club)) if isinstance(club, str) else ""
        fixture = fixtures.get(club_key) if club_key else None
        cell = calendar_by_club.get(club_key) if club_key else None
        form = player.get("form") if isinstance(player.get("form"), dict) else {}
        team = strength_map.get(club_key) if club_key else None
        from toolbox.analyzer import apply_doubt_titular_discount

        vista = _vista_consenso_bajo(player)
        pts = expected_opta_points(
            position=player.get("position") if isinstance(player.get("position"), str) else None,
            p_titular=apply_doubt_titular_discount(_as_float(player.get("p_titular")), player, None),
            player_xg=_as_float(form.get("xg")),
            player_xa=_as_float(form.get("xa")),
            team_lambda=_as_float(cell.get("lambda_for")) if cell else None,
            opp_lambda=_as_float(cell.get("lambda_against")) if cell else None,
            team_avg_xg=team.avg_xg if team else league_avg_xg,
            home=bool(fixture.home) if fixture else False,
            fdr=fixture.fdr if fixture else None,
            player=vista,
            p_cs_own=_as_float(cell.get("p_cs_for")) if cell else None,
            rival=cell.get("opponent") if cell and isinstance(cell.get("opponent"), str) else None,
        )
        if pts["expected_points"] is not None:
            prelim_points[pid] = float(pts["expected_points"])
            player["_own_pts_cache"] = pts
            # xP en cada partido siguiente, con su rival y su campo. Sin Monte
            # Carlo: solo hace falta la media, no el techo. Una sanción solo
            # cuenta en los partidos que cubre: después vuelve su titularidad.
            sancion = jugador_tras_sancion(player)
            if sancion is not None:
                player["own_sancion_partidos"] = sancion[2]
            else:
                player.pop("own_sancion_partidos", None)
            # Duda o fuera del once esta semana: J2-J4 con su titularidad normal.
            recuperado = jugador_tras_duda(player) if sancion is None else None
            if recuperado is not None or sancion is not None:
                player["_own_baja_puntual"] = True
            futuros: list[float] = []
            for offset, (later, later_cell) in enumerate(siguientes_by_club.get(club_key, []), start=1):
                cumplida = sancion is not None and offset >= sancion[2]
                if cumplida:
                    jugador_j, p_j = sancion[0], sancion[1]
                elif recuperado is not None:
                    jugador_j, p_j = recuperado
                else:
                    jugador_j, p_j = vista, _as_float(player.get("p_titular"))
                later_pts = expected_opta_points(
                    position=player.get("position") if isinstance(player.get("position"), str) else None,
                    p_titular=apply_doubt_titular_discount(p_j, jugador_j, None),
                    player_xg=_as_float(form.get("xg")),
                    player_xa=_as_float(form.get("xa")),
                    team_lambda=_as_float(later_cell.get("lambda_for")),
                    opp_lambda=_as_float(later_cell.get("lambda_against")),
                    team_avg_xg=team.avg_xg if team else league_avg_xg,
                    home=bool(later.home),
                    fdr=later.fdr,
                    player=jugador_j,
                    p_cs_own=_as_float(later_cell.get("p_cs_for")),
                    monte_carlo=False,
                    rival=later_cell.get("opponent") if isinstance(later_cell.get("opponent"), str) else None,
                )
                if later_pts["expected_points"] is None:
                    break
                valor = float(later_pts["expected_points"])
                if offset == 1 and sancion is None:
                    # Apercibido (4 amarillas): si ve una en esta jornada, se pierde la siguiente.
                    valor *= _supervivencia_apercibido(pts, player)
                futuros.append(round(valor, 3))
            player["_own_xp_siguientes"] = futuros

    jornada_avg = _mean(list(prelim_points.values()))

    # Universo de |rate| para strength.
    rates: dict[str, float] = {}
    today_deltas: dict[str, int | None] = {}
    for player in players:
        pid = player.get("player_id")
        if not isinstance(pid, str):
            continue
        hist = histories.get(pid) or []
        deltas = deltas_from_history(hist)
        # Mismo criterio que en la cinemática: solo delta oficial. Sin él,
        # ``project_rate`` usa el último delta medido de la serie.
        today = _as_int(player.get("market_value_change"))
        today_deltas[pid] = today
        rate = project_rate(deltas, today_delta=today)
        if rate is not None:
            rates[pid] = rate

    universe_abs = [abs(r) for r in rates.values()]

    bid_count = 0
    signal_count = 0
    points_count = 0
    calendar_count = 0

    kinematics_count = 0
    for player in players:
        pid = player.get("player_id")
        if not isinstance(pid, str):
            continue
        club = player.get("club")
        club_key = normalize_club(str(club)) if isinstance(club, str) else ""
        fixture = fixtures.get(club_key) if club_key else None
        cell = calendar_by_club.get(club_key) if club_key else None

        hist = histories.get(pid) or []
        price = _as_int(player.get("fantasy_price"))
        if price is None or price <= 0:
            price = _as_int(player.get("market_value")) or 0
        # Solo el delta oficial de la API. ``price_delta`` es la estimación de
        # FútbolFantasy: pasarla aquí como si fuera oficial metía un dato de
        # terceros en la cinemática. Si no hay delta oficial y ya hay captura de
        # hoy, el motor reconstruye el del día con la diferencia de valor.
        today = _as_int(player.get("market_value_change"))
        scraper_accel = _as_float(player.get("acceleration"))
        kin = compute_price_kinematics_and_sell_signal(
            hist[-HISTORY_WINDOW:],
            current_market_value=max(price, 1),
            official_today_delta=today,
            scraper_acceleration=scraper_accel,
        )
        _apply_kinematics_to_player(player, kin)
        kinematics_count += 1

        # Calendario: la próxima jornada y las siguientes del Poisson propio.
        if cell is not None:
            celdas = [cell, *(later_cell for _later, later_cell in siguientes_by_club.get(club_key, []))]
            player["own_calendar"] = [
                {
                    "matchday": celda.get("matchday") or 0,
                    "opponent": celda.get("opponent"),
                    "is_home": celda.get("is_home"),
                    "predicted_score": celda.get("predicted_score"),
                    "recommendation_pct": celda.get("recommendation_pct"),
                    "difficulty": celda.get("difficulty"),
                    "lambda_for": celda.get("lambda_for"),
                    "lambda_against": celda.get("lambda_against"),
                    "p_cs_for": celda.get("p_cs_for"),
                    "win_prob": celda.get("win_prob"),
                    # Peso de las cuotas en los goles esperados (None = sin cuotas).
                    "market_weight": celda.get("market_weight"),
                    "kickoff": celda.get("kickoff"),
                }
                for celda in celdas
            ]
            player["own_recommendation_pct"] = cell.get("recommendation_pct")
            calendar_count += 1
        # Puntos. La mezcla con AF va ANTES de publicar J2-J4: reescala
        # ``_own_xp_siguientes`` para que las cuatro jornadas compartan escala.
        pts = player.pop("_own_pts_cache", None)
        if isinstance(pts, dict) and pts.get("expected_points") is not None:
            player["own_expected_points"] = pts["expected_points"]
            player["own_ceiling_points"] = pts["ceiling_points"]
            _mezclar_xp_af(player)
            if pts.get("xp_condicional") is not None:
                player["own_points_if_starts"] = _condicional_tras_mezcla(player, pts["xp_condicional"])
            player["own_goal_probability"] = pts["goal_probability"]
            player["own_assist_probability"] = pts["assist_probability"]
            if pts.get("p_start_eff") is not None:
                player["p_start_eff"] = pts["p_start_eff"]
            if pts.get("expected_minutes") is not None:
                player["expected_minutes"] = pts["expected_minutes"]
            if pts.get("inferred_bonus") is not None:
                player["inferred_bonus"] = pts["inferred_bonus"]
            if pts.get("next_match_survival") is not None:
                player["next_match_survival"] = pts["next_match_survival"]
            for origen, destino in (
                ("xp_modelo", "own_xp_motor"),
                ("xp_desglose", "own_xp_desglose"),
                ("xp_breakout", "own_xp_breakout"),
                ("xp_balon_parado", "own_xp_balon_parado"),
                ("xp_ajuste_rival", "own_ajuste_rival"),
                ("xp_ajuste_club", "own_ajuste_club"),
                ("xp_cambio_cronico", "own_cambio_cronico"),
                ("xp_produccion_pura_90", "own_produccion_pura_90"),
                ("xp_suelo_muro", "own_suelo_muro"),
            ):
                if pts.get(origen) is not None:
                    player[destino] = pts[origen]
            value = _as_int(player.get("fantasy_price"))
            if value and value > 0 and pts["expected_points"]:
                player["own_points_per_million"] = round(
                    float(pts["expected_points"]) / (value / 1_000_000.0), 4
                )
            points_count += 1

        futuros = player.pop("_own_xp_siguientes", None)
        player.pop("_own_baja_puntual", None)
        if isinstance(futuros, list) and futuros:
            # xP de J2, J3 y J4 en este orden. La próxima está en own_expected_points.
            player["own_xp_siguientes"] = futuros

        # Mercado / puja
        rate = rates.get(pid)
        if rate is None:
            continue
        price = _as_int(player.get("fantasy_price"))
        if price is None or price <= 0:
            continue
        days = markets_until_kickoff(fixture.kickoff if fixture else None, now=now)
        if days is None:
            days = 3  # horizonte neutro si no hay fixture
        hist_values = [v for v in (_as_int(r.get("market_value")) for r in hist) if v is not None]
        fitness = player.get("fitness") if isinstance(player.get("fitness"), str) else None
        sanction = player.get("sanction") if isinstance(player.get("sanction"), dict) else {}
        from toolbox.normalize import titularity_overrides_injury

        injury_flag = fitness and ("lesion" in fitness.lower() or "injured" in fitness.lower())
        trust = titularity_overrides_injury(
            player.get("p_titular"),
            source=player.get("p_titular_source") if isinstance(player.get("p_titular_source"), str) else None,
            lineup_status=player.get("lineup_status") if isinstance(player.get("lineup_status"), str) else None,
        )
        if injury_flag and trust:
            injury_flag = False
        af_injury = player.get("af_injury")
        unavailable = bool(
            injury_flag
            or sanction.get("suspended")
            or (af_injury and not trust)
            or player.get("af_suspension")
        )
        falling = rate < 0
        exp_pts = _as_float(player.get("own_expected_points"))
        ideal, maximum = compute_bids(
            price=price,
            rate=rate,
            days=days,
            expected_points=exp_pts,
            jornada_avg_points=jornada_avg,
            history_values=hist_values,
            falling=falling,
            unavailable=unavailable,
        )
        player["own_ideal_bid"] = ideal
        player["own_max_bid"] = maximum
        bid_count += 1

        form = player.get("form") if isinstance(player.get("form"), dict) else {}
        form_score = _as_float(form.get("rating")) or _as_float(form.get("note"))
        direction, strength, predicted = compute_market_signal(
            rate=rate,
            today_delta=today_deltas.get(pid),
            fitness=fitness,
            form_score=form_score,
            universe_abs=universe_abs,
        )
        player["own_market_signal"] = direction
        player["own_signal_strength"] = strength
        if player.get("own_predicted_delta") is None:
            player["own_predicted_delta"] = predicted
        signal_count += 1

    rising = sorted(
        [p for p in players if p.get("own_market_signal") == "up"],
        key=lambda item: (-(item.get("own_signal_strength") or 0), item.get("player_id") or ""),
    )[:15]
    falling_list = sorted(
        [p for p in players if p.get("own_market_signal") == "down"],
        key=lambda item: (-(item.get("own_signal_strength") or 0), item.get("player_id") or ""),
    )[:15]

    history_ok = sum(1 for rows in histories.values() if len(deltas_from_history(rows)) >= MIN_HISTORY_DAYS)
    # ok=True aunque count=0: historial corto / sin fixtures es esperado, no marca trends partial.
    sources = {
        "own_intel_bids": {
            "ok": True,
            "count": bid_count,
            "error": None if bid_count else ("historial_insuficiente" if not history_ok else None),
            "from_cache": False,
        },
        "own_intel_signal": {
            "ok": True,
            "count": signal_count,
            "error": None if signal_count else ("historial_insuficiente" if not history_ok else None),
            "from_cache": False,
        },
        "own_intel_points": {
            "ok": True,
            "count": points_count,
            "error": None if points_count else "sin_stats",
            "from_cache": False,
        },
        "own_intel_calendar": {
            "ok": True,
            "count": calendar_count,
            "error": None if calendar_count else "sin_fixtures",
            "from_cache": False,
        },
        "own_intel_kinematics": {
            "ok": True,
            "count": kinematics_count,
            "error": None,
            "from_cache": False,
        },
    }
    for jugador in con_actas:
        jugador.pop("historial", None)
    # Jornada en curso: todos los xP y rivales pasan a la próxima jornada que se puede tocar.
    corridos = promover_jornada_bloqueada(players, now=now)
    sources["own_intel_calendar"]["jornada_corrida"] = corridos
    return {
        "prediction_rising": rising,
        "prediction_falling": falling_list,
        "sources": sources,
        "history_players": history_ok,
    }


#: Hueco entre bloques de partidos que separa una jornada de la siguiente.
_HUECO_JORNADAS_H = 36.0


def _saque(player: dict[str, Any]) -> datetime | None:
    calendario = player.get("own_calendar") if isinstance(player.get("own_calendar"), list) else []
    raw = calendario[0].get("kickoff") if calendario and isinstance(calendario[0], dict) else None
    if raw is None and isinstance(player.get("fixture"), dict):
        raw = player["fixture"].get("kickoff")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        moment = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def promover_jornada_bloqueada(players: list[dict[str, Any]], *, now: datetime | None = None) -> int:
    """Con la jornada en curso, el «próximo partido» de cada jugador es el de la siguiente.

    La alineación se bloquea en el primer partido de la jornada. Si al menos dos
    clubes ya jugaron (su próximo partido cae en un bloque posterior), la jornada
    está en curso: a quien aún juega en ella se le corre el calendario y su xP,
    rival y saque pasan a ser los de la próxima jornada que se puede tocar (J13).
    El partido bloqueado se guarda en ``own_en_juego`` para el bloque «en vivo».
    Así Equipo, Mercado, el plan y las fichas hablan de la misma jornada.
    Devuelve cuántos jugadores se corrieron.
    """
    momento = now or datetime.now(timezone.utc)
    por_club: dict[str, datetime] = {}
    saques: set[datetime] = set()
    for player in players:
        if not isinstance(player, dict):
            continue
        calendario = player.get("own_calendar") if isinstance(player.get("own_calendar"), list) else []
        for celda in calendario:
            raw = celda.get("kickoff") if isinstance(celda, dict) else None
            if isinstance(raw, str) and raw.strip():
                try:
                    k = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
                except ValueError:
                    continue
                saques.add(k if k.tzinfo else k.replace(tzinfo=timezone.utc))
        saque = _saque(player)
        club = player.get("club")
        if saque is not None and isinstance(club, str) and club:
            por_club[club] = min(por_club.get(club, saque), saque)
    futuros = sorted(k for k in saques if k >= momento - timedelta(hours=2))
    if not futuros:
        return 0
    fin_bloque = futuros[0]
    for k in futuros[1:]:
        if (k - fin_bloque).total_seconds() / 3600.0 > _HUECO_JORNADAS_H:
            break
        fin_bloque = k
    ya_jugaron = sum(1 for saque in por_club.values() if saque > fin_bloque)
    if ya_jugaron < 2:
        return 0
    corridos = 0
    for player in players:
        if not isinstance(player, dict) or player.get("own_en_juego"):
            continue
        saque = _saque(player)
        calendario = player.get("own_calendar") if isinstance(player.get("own_calendar"), list) else []
        siguientes = player.get("own_xp_siguientes") if isinstance(player.get("own_xp_siguientes"), list) else []
        if saque is None or saque > fin_bloque or len(calendario) < 2:
            continue
        actual = calendario[0] if isinstance(calendario[0], dict) else {}
        proxima = calendario[1] if isinstance(calendario[1], dict) else {}
        xp_actual = _as_float(player.get("own_expected_points"))
        xp_proxima = _as_float(siguientes[0]) if siguientes else None
        player["own_en_juego"] = {
            "kickoff": actual.get("kickoff") or (player.get("fixture") or {}).get("kickoff"),
            "opponent": actual.get("opponent"),
            "is_home": actual.get("is_home"),
            "expected_points": xp_actual,
        }
        player["own_calendar"] = calendario[1:]
        player["own_recommendation_pct"] = proxima.get("recommendation_pct")
        if xp_proxima is not None:
            factor = xp_proxima / xp_actual if xp_actual and xp_actual > 0 else 1.0
            player["own_expected_points"] = round(xp_proxima, 3)
            for key in ("own_ceiling_points", "own_points_if_starts"):
                valor = _as_float(player.get(key))
                if valor is not None:
                    player[key] = round(valor * factor, 3)
            player["own_xp_siguientes"] = siguientes[1:]
            precio = _as_int(player.get("fantasy_price"))
            if precio and precio > 0:
                player["own_points_per_million"] = round(xp_proxima / (precio / 1_000_000.0), 4)
        fixture = player.get("fixture") if isinstance(player.get("fixture"), dict) else None
        if fixture is not None:
            player["fixture"] = {
                **fixture,
                "opponent": proxima.get("opponent") or fixture.get("opponent"),
                "home": proxima.get("is_home") if proxima.get("is_home") is not None else fixture.get("home"),
                "kickoff": proxima.get("kickoff"),
            }
        player["jornada_corrida"] = True
        corridos += 1
    return corridos



def persist_and_apply_own_intel(
    players: list[dict[str, Any]],
    *,
    league_id: str | None,
    fixtures_by_club: dict[str, FixtureInfo] | None = None,
    strengths: dict[str, TeamStrength] | None = None,
    team_rolling: dict[str, TeamRollingWindow] | None = None,
    match_odds: dict[str, Any] | None = None,
    store: PriceSnapshotStore | None = None,
    root: Any = None,
    day: str | None = None,
    catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Upsert snapshots del día y aplica el motor. ``root`` solo para tests locales.

    ``day`` es el día civil de la **captura** del precio, no el día en que corre
    el proceso. En air-gap o con la API caída se sirve una copia de disco: si se
    sellara con la fecha de hoy, el histórico grabaría dos días con el mismo
    valor y el motor leería una subida de 0 € que nunca ocurrió.
    """
    snap_store = store or PriceSnapshotStore(root=root)
    rows = snapshot_rows_from_players(players, league_id=league_id, day=day)
    catalog_rows = catalog_snapshot_rows(
        catalog,
        already={row["player_id"] for row in rows},
        league_id=league_id,
        day=day,
    )
    rows = rows + catalog_rows
    written = 0
    try:
        written = snap_store.upsert_price_snapshots(rows)
    except Exception as exc:  # noqa: BLE001 — no tumba trends
        summary = apply_own_intel(
            players,
            histories={},
            fixtures_by_club=fixtures_by_club,
            strengths=strengths,
            team_rolling=team_rolling,
            match_odds=match_odds,
        )
        summary["sources"]["own_intel_snapshots"] = {
            "ok": False,
            "count": 0,
            "error": str(exc),
            "from_cache": False,
        }
        return summary

    try:
        histories = snap_store.list_history(league_id=league_id, days=HISTORY_WINDOW)
    except Exception as exc:  # noqa: BLE001
        histories = {}
        read_error = str(exc)
    else:
        read_error = None

    summary = apply_own_intel(
        players,
        histories=histories,
        fixtures_by_club=fixtures_by_club,
        strengths=strengths,
        team_rolling=team_rolling,
        match_odds=match_odds,
    )
    summary["sources"]["own_intel_snapshots"] = {
        "ok": written > 0 and read_error is None,
        "count": written,
        "error": read_error,
        "from_cache": False,
        "missing_days": snapshot_missing_days(histories),
        "catalog_rows": len(catalog_rows),
    }
    return summary


def snapshot_missing_days(histories: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Días civiles sin ninguna captura entre la primera y la última del histórico.

    Un hueco rompe ``price_delta_3`` y los ritmos de subida: el delta de un
    tramo de varios días no es el de un día. Se publica para que se vea.
    """
    days: set[date] = set()
    for rows in histories.values():
        for row in rows:
            raw = row.get("day")
            if isinstance(raw, str):
                try:
                    days.add(date.fromisoformat(raw[:10]))
                except ValueError:
                    continue
    if len(days) < 2:
        return []
    first, last = min(days), max(days)
    missing = [
        (first + timedelta(days=offset)).isoformat()
        for offset in range((last - first).days + 1)
        if (first + timedelta(days=offset)) not in days
    ]
    return missing

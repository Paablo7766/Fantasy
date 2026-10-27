"""Explotador del market maker del sistema: percentil de la oferta y EV de mañana.

El ordenador no paga lo que uno pida: se mueve dentro de una banda dura de
±10 % sobre el valor de mercado. Este módulo mide dónde cae cada oferta en esa
banda (percentil uniforme), la compara con el valor esperado de la oferta de
mañana y devuelve una sola etiqueta: ``STRONG_SELL``, ``SELL``,
``LIQUIDATE_NOW``, ``HOLD`` o ``STRONG_HOLD``.

La media histórica de ratios sale de ``market_offers_log.json``. Con menos de
``MIN_LOG_SAMPLES`` ofertas registradas no hay media: se usa
``DEFAULT_MEAN_PCT`` y se anota en la salida. Sin tendencia estimada se decide
con tendencia 0; nunca se inventa una subida o una caída.

Nota sobre ``LIQUIDATE_NOW``: la ventana no depende de la media histórica.
Liquidar exige oferta por debajo del EV de mañana (si no, ya sería ``SELL``)
pero también por debajo del mínimo que el sistema pagaría mañana
(``valor_mañana · (1 + MIN_OFFER_PCT)``): con una caída fuerte no hay oferta
futura mejor. Con ``DEFAULT_MEAN_PCT = 0`` el EV es el valor de mañana y la
señal sigue siendo alcanzable.

No envía ventas. Solo recomienda.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from toolbox import project_root
from toolbox.normalize import SCHEMA_VERSION

# --- Límites duros del juego -------------------------------------------------

MAX_OFFER_PCT = 0.10  # +10 % es la oferta máxima absoluta del sistema.
MIN_OFFER_PCT = -0.10  # -10 % es la oferta mínima absoluta.
DEFAULT_MEAN_PCT = 0.0  # Media inicial teórica.

OFFER_SPAN = MAX_OFFER_PCT - MIN_OFFER_PCT  # 0.20 de amplitud.

# Pico estadístico: percentil 90 de la banda.
STRONG_SELL_RATIO = 0.08
STRONG_SELL_PERCENTILE = 90.0

# Escenario límite del rechazo: una oferta «buena» de mañana es el percentil 80.
LIQUIDATION_PERCENTILE = 80.0
LIQUIDATION_RATIO = MIN_OFFER_PCT + (LIQUIDATION_PERCENTILE / 100.0) * OFFER_SPAN  # 0.06

# Ofertas mínimas para que la media del log sea una media y no ruido.
MIN_LOG_SAMPLES = 5
# Techo del fichero: se conservan las últimas N ofertas.
MAX_LOG_ENTRIES = 5_000

LOG_FILENAME = "market_offers_log.json"
COMMAND = "market-maker"

SELL_FLAGS = frozenset({"STRONG_SELL", "SELL", "LIQUIDATE_NOW"})
HOLD_FLAGS = frozenset({"STRONG_HOLD", "HOLD"})

__all__ = [
    "DEFAULT_MEAN_PCT",
    "LOG_FILENAME",
    "MAX_OFFER_PCT",
    "MIN_OFFER_PCT",
    "MarketMakerExploiter",
    "evaluate_offer",
    "get_market_recommendations",
    "get_offer_percentile",
    "log_offer",
]


# --- Utilidades de tipo ------------------------------------------------------


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number(value: Any) -> float | None:
    """Número finito. ``bool`` no es un importe."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _pick(row: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _eur(value: float) -> int:
    # Redondeo a entero de un importe en euros.
    if value < 0:
        return round(value) - 1
    if value > 0:
        return round(value) + 1
    return 0


def _percentile_from_ratio(ratio: float) -> float:
    clipped = min(MAX_OFFER_PCT, max(MIN_OFFER_PCT, ratio))
    return round((clipped - MIN_OFFER_PCT) / OFFER_SPAN * 100.0, 2)


# --- Persistencia del log de ofertas -----------------------------------------

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _file_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _write_text_atomic(path: Path, payload: str) -> None:
    """Escritura atómica con reintento: en Windows ``replace`` falla si el
    antivirus u otro hilo aún tiene abierto el destino."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp.{int(time.time() * 1000)}.{threading.get_ident()}")
    temporary.write_text(payload, encoding="utf-8")
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    try:
        path.write_text(payload, encoding="utf-8")
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    if last_error is not None and not path.exists():
        raise last_error


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("offers")
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _entries_ratios(entries: list[dict[str, Any]], jugador_id: str | None = None) -> list[float]:
    ratios: list[float] = []
    for row in entries:
        if jugador_id is not None and row.get("jugador_id") != jugador_id:
            continue
        ratio = _number(row.get("ratio"))
        if ratio is not None:
            ratios.append(ratio)
    return ratios


def _mean_for(entries: list[dict[str, Any]], jugador_id: str | None) -> tuple[float, int, str]:
    """(media, muestras, fuente). Del jugador si hay muestra; si no, del log entero."""
    own = _entries_ratios(entries, jugador_id) if jugador_id else []
    if len(own) >= MIN_LOG_SAMPLES:
        return sum(own) / len(own), len(own), "log_jugador"
    global_ratios = _entries_ratios(entries)
    if len(global_ratios) >= MIN_LOG_SAMPLES:
        return sum(global_ratios) / len(global_ratios), len(global_ratios), "log_global"
    return DEFAULT_MEAN_PCT, len(global_ratios), "default"


# --- Motor de decisión -------------------------------------------------------

_NOTES = {
    "pico_percentil_90": "Pico estadístico: el sistema está pagando el percentil 90 o más. Vender ya.",
    "oferta_sobre_ev": "Hoy ofrecen más de lo que se espera mañana. Aceptar.",
    "sube_y_oferta_corta": "La oferta es corta y el jugador sube: dos motivos para esperar.",
    "escenario_limite": "Aun con una oferta de percentil 80 mañana se ganaría menos que aceptando hoy.",
    "esperar_oferta_mejor": "Oferta corta, pero mañana el escenario límite aún supera lo ofrecido hoy.",
    "sin_tendencia": "Sin tendencia estimada: la oferta no supera el EV y no hay motivo para vender.",
    "ev_neutro": "Oferta igual al EV de mañana: no hay prima por aceptar hoy.",
}


def _badge(recommendation: str) -> dict[str, str]:
    """Badge semántico para el frontend: verde = vender, rojo = rechazar."""
    if recommendation in SELL_FLAGS:
        return {"label": "VENDER", "tone": "green", "recommendation": recommendation}
    return {"label": "RECHAZAR", "tone": "red", "recommendation": recommendation}


def _decide(
    *,
    oferta: float,
    valor: float,
    tendencia: float,
    jugador_id: str | None,
    mean_pct: float,
    mean_source: str,
    samples: int,
    trend_source: str | None = None,
) -> dict[str, Any]:
    # Entradas normalizadas a ``float``: las comparaciones de la decisión no
    # deben depender del tipo con que llegue la oferta (reglas duras, valor > 0).
    oferta = float(oferta)
    valor = float(valor)
    tendencia = float(tendencia)
    mean_pct = float(mean_pct)
    ratio = (oferta - valor) / valor
    percentile = _percentile_from_ratio(ratio)
    tomorrow_value = max(0.0, valor + tendencia)
    ev_tomorrow = tomorrow_value * (1.0 + max(0.0, mean_pct))
    liquidation_offer = tomorrow_value * (1.0 + LIQUIDATION_RATIO)
    # Ventana de liquidación: la oferta no llega al suelo que el sistema pagaría
    # mañana (``1 + MIN_OFFER_PCT``), con el precio cayendo. No exige además
    # ``oferta < EV``: con ``mean_pct = 0`` el EV es el valor de mañana, que
    # siempre supera el suelo, y la señal quedaría inalcanzable.
    reject_floor = max(0.0, valor + tendencia) * (1.0 + MIN_OFFER_PCT)
    liquidation_window = bool((valor + tendencia) < valor and oferta < reject_floor)
    if liquidation_window:
        # Se resuelve antes que el pico y que el EV: es una condición de caja,
        # no de comparativa de mercado.
        return {
            "jugador_id": jugador_id,
            "recommendation": "LIQUIDATE_NOW",
            "action": "SELL",
            "badge": _badge("LIQUIDATE_NOW"),
            "reason": "escenario_limite",
            "note": _NOTES["escenario_limite"],
            "offer_eur": int(round(oferta)),
            "market_value_eur": _eur(valor),
            "ratio": round(ratio, 6),
            "ratio_pct": round(ratio * 100.0, 2),
            "percentile": percentile,
            "daily_trend_eur": tendencia,
            "trend_source": trend_source,
            "tomorrow_value_eur": _eur(tomorrow_value),
            "ev_tomorrow_eur": int(round(ev_tomorrow)),
            "edge_vs_ev_eur": int(round(oferta)) - int(round(ev_tomorrow)),
            "liquidation_offer_eur": int(round(liquidation_offer)),
            "mean_pct": round(mean_pct, 6),
            "mean_source": mean_source,
            "samples": samples,
        }

    # Se compara en euros enteros: el importe que se enseña y el que decide son
    # el mismo número. Un céntimo de coma flotante no cambia un veredicto.
    offer_eur = int(round(oferta))
    ev_eur = int(round(ev_tomorrow))
    liquidation_eur = int(round(liquidation_offer))
    reject_floor_eur = int(round(reject_floor))

    if ratio >= STRONG_SELL_RATIO:
        recommendation, reason = "STRONG_SELL", "pico_percentil_90"
    elif offer_eur > ev_eur:
        recommendation, reason = "SELL", "oferta_sobre_ev"
    elif tendencia > 0:
        recommendation, reason = "STRONG_HOLD", "sube_y_oferta_corta"
    elif tendencia < 0:
        recommendation, reason = "HOLD", "esperar_oferta_mejor"
    else:
        recommendation, reason = "HOLD", "sin_tendencia"



    return {
        "jugador_id": jugador_id,
        "recommendation": recommendation,
        "action": "SELL" if recommendation in SELL_FLAGS else "HOLD",
        "badge": _badge(recommendation),
        "reason": reason,
        "note": _NOTES[reason],
        "offer_eur": offer_eur,
        "market_value_eur": _eur(valor),
        "ratio": round(ratio, 6),
        "ratio_pct": round(ratio * 100.0, 2),
        "percentile": percentile,
        "daily_trend_eur": tendencia,
        "trend_source": trend_source,
        "tomorrow_value_eur": _eur(tomorrow_value),
        "ev_tomorrow_eur": ev_eur,
        "edge_vs_ev_eur": offer_eur - ev_eur,
        "liquidation_offer_eur": liquidation_eur,
        "mean_pct": round(mean_pct, 6),
        "mean_source": mean_source,
        "samples": samples,
    }


# --- API de módulo (una oferta suelta) ---------------------------------------


def get_offer_percentile(ratio_oferta: float) -> float:
    """Percentil exacto del ratio dentro de la banda dura ``[-0.10, +0.10]``.

    La banda es uniforme: ``(ratio - mínimo) / 0.20``. Un 0.08 cae en el 90 %.
    Fuera de banda se satura en 0 o 100: una oferta de rival puede pasarse,
    el sistema no.
    """
    number = _number(ratio_oferta)
    if number is None:
        raise ValueError("ratio_oferta debe ser un número finito.")
    return _percentile_from_ratio(number)


def log_offer(
    jugador_id: str,
    valor_mercado: float,
    oferta_sistema: float,
    *,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Registra una oferta del sistema y devuelve la fila guardada.

    Atajo de módulo sobre ``MarketMakerExploiter.log_offer`` para no instanciar
    la clase cuando solo se quiere apuntar una oferta.
    """
    return MarketMakerExploiter(path).log_offer(jugador_id, valor_mercado, oferta_sistema)


def evaluate_offer(
    oferta_actual: float,
    valor_mercado_actual: float,
    tendencia_diaria_estimada: float | None,
    *,
    jugador_id: str | None = None,
    mean_pct: float | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Evalúa una oferta suelta sin instanciar la clase.

    ``path`` apunta al log de ofertas; por defecto, ``market_offers_log.json``
    en la raíz del proyecto.
    """
    return MarketMakerExploiter(path).evaluate_offer(
        oferta_actual,
        valor_mercado_actual,
        tendencia_diaria_estimada,
        jugador_id=jugador_id,
        mean_pct=mean_pct,
    )


def get_market_recommendations(
    jugadores_en_venta: Any,
    *,
    mean_pct: float | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Endpoint de integración: recomendación y badge por jugador en venta."""
    return MarketMakerExploiter(path).get_market_recommendations(
        jugadores_en_venta,
        mean_pct=mean_pct,
    )


# --- Clase -------------------------------------------------------------------


class MarketMakerExploiter:
    """Percentil de la oferta + EV de mañana → ACEPTAR o RECHAZAR."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else project_root() / LOG_FILENAME

    # -- Registro ------------------------------------------------------------

    def log_offer(self, jugador_id: str, valor_mercado: float, oferta_sistema: float) -> dict[str, Any]:
        """Guarda ``ratio = (oferta - valor) / valor`` en el log local.

        El log es la única fuente de la media histórica: sin él, el motor
        siempre usa ``DEFAULT_MEAN_PCT``. Un valor de mercado no positivo no
        define ratio y se rechaza; no se guarda una fila inventada.
        """
        pid = _text(jugador_id)
        if pid is None:
            raise ValueError("jugador_id no puede estar vacío.")
        valor = _number(valor_mercado)
        if valor is None or valor <= 0:
            raise ValueError("valor_mercado debe ser un número mayor que 0.")
        oferta = _number(oferta_sistema)
        if oferta is None or oferta < 0:
            raise ValueError("oferta_sistema debe ser un número no negativo.")

        ratio = round((oferta - valor) / valor, 6)
        entry = {
            "jugador_id": pid,
            "valor_mercado": _eur(valor),
            "oferta_sistema": _eur(oferta),
            "ratio": ratio,
            "ratio_pct": round(ratio * 100.0, 2),
            "percentile": _percentile_from_ratio(ratio),
            "registrada_en": datetime.now(timezone.utc).isoformat(),
        }

        lock = _file_lock(self.path)
        with lock:
            entries = _read_entries(self.path)
            entries.append(entry)
            if len(entries) > MAX_LOG_ENTRIES:
                entries = entries[-MAX_LOG_ENTRIES:]
            _write_text_atomic(self.path, json.dumps(entries, ensure_ascii=False))
        return entry

    def load_log(self) -> list[dict[str, Any]]:
        """Ofertas registradas. Un fichero roto se trata como vacío."""
        return _read_entries(self.path)

    def historical_mean(self, jugador_id: str | None = None) -> dict[str, Any]:
        """Media de ratios del log: del jugador, del log entero o la teórica."""
        mean, samples, source = _mean_for(self.load_log(), jugador_id)
        return {"mean_pct": round(mean, 6), "samples": samples, "mean_source": source}

    # -- Percentil -----------------------------------------------------------

    @staticmethod
    def get_offer_percentile(ratio_oferta: float) -> float:
        """Percentil exacto del ratio en la banda dura. Ver ``get_offer_percentile``."""
        return get_offer_percentile(ratio_oferta)

    # -- Decisión ------------------------------------------------------------

    def evaluate_offer(
        self,
        oferta_actual: float,
        valor_mercado_actual: float,
        tendencia_diaria_estimada: float | None,
        *,
        jugador_id: str | None = None,
        mean_pct: float | None = None,
    ) -> dict[str, Any]:
        """Evalúa una oferta contra el EV de la oferta de mañana.

        ``mean_pct`` fuerza la media histórica (calibración y pruebas). Sin él
        se lee el log: media del jugador si hay muestra suficiente y, si no,
        media global; por debajo de ``MIN_LOG_SAMPLES``, ``DEFAULT_MEAN_PCT``.

        ``tendencia_diaria_estimada`` es el delta diario esperado en euros.
        ``None`` se evalúa como 0 y queda anotado en ``trend_source``.
        """
        valor = _number(valor_mercado_actual)
        if valor is None or valor <= 0:
            raise ValueError("valor_mercado_actual debe ser un número mayor que 0.")
        oferta = _number(oferta_actual)
        if oferta is None or oferta <= 0:
            raise ValueError("oferta_actual debe ser un número mayor que 0.")
        trend = _number(tendencia_diaria_estimada)
        trend_source = "estimada" if trend is not None else None
        if trend is None:
            if tendencia_diaria_estimada is not None:
                raise ValueError("tendencia_diaria_estimada debe ser un número finito o None.")
            trend = 0.0

        if mean_pct is None:
            mean, samples, source = _mean_for(self.load_log(), _text(jugador_id))
        else:
            forced = _number(mean_pct)
            if forced is None:
                raise ValueError("mean_pct debe ser un número finito.")
            mean, samples, source = forced, 0, "forzada"

        return _decide(
            oferta=oferta,
            valor=valor,
            tendencia=trend,
            jugador_id=_text(jugador_id),
            mean_pct=mean,
            mean_source=source,
            samples=samples,
            trend_source=trend_source,
        )

    # -- Endpoint ------------------------------------------------------------

    def get_market_recommendations(
        self,
        jugadores_en_venta: Any,
        *,
        mean_pct: float | None = None,
    ) -> dict[str, Any]:
        """Cruza los jugadores propios en venta con el motor y pinta el badge.

        Acepta una lista de filas o un documento con la lista dentro. Cada fila
        necesita ``player_id``, ``market_value`` y la oferta del sistema
        (``oferta_sistema``/``offer``/…). La tendencia se toma del campo
        explícito; si falta, de ``own_predicted_delta`` → ``af_predicted_delta``
        → ``price_delta``. Una fila sin oferta, sin valor o sin id no se evalúa:
        va a ``skipped`` con el motivo, no se inventa una recomendación.
        """
        rows = _rows(jugadores_en_venta)
        entries = self.load_log()
        global_mean, global_samples, global_source = _mean_for(entries, None)
        if mean_pct is not None:
            forced = _number(mean_pct)
            if forced is None:
                raise ValueError("mean_pct debe ser un número finito.")
            global_mean, global_samples, global_source = forced, 0, "forzada"

        offers: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            player_id = _text(_pick(row, ("player_id", "jugador_id", "id")))
            valor = _number(_pick(row, ("market_value", "valor_mercado", "fantasy_price")))
            oferta = _number(_pick(row, ("oferta_sistema", "offer_eur", "system_offer", "offer", "offer_amount")))
            if player_id is None:
                skipped.append({"index": index, "reason": "sin_jugador_id"})
                continue
            if valor is None or valor <= 0:
                skipped.append({"player_id": player_id, "reason": "sin_valor_mercado"})
                continue
            if oferta is None or oferta < 0:
                skipped.append({"player_id": player_id, "reason": "sin_oferta"})
                continue

            trend_raw = _pick(
                row,
                (
                    "tendencia_diaria_estimada",
                    "daily_trend",
                    "tendencia",
                    "own_predicted_delta",
                    "af_predicted_delta",
                    "price_delta",
                ),
            )
            trend = _number(trend_raw)

            if mean_pct is not None:
                mean, samples, source = global_mean, global_samples, global_source
            else:
                mean, samples, source = _mean_for(entries, player_id)

            signal = _decide(
                oferta=oferta,
                valor=valor,
                tendencia=trend if trend is not None else 0.0,
                jugador_id=player_id,
                mean_pct=mean,
                mean_source=source,
                samples=samples,
                trend_source="estimada" if trend is not None else None,
            )
            signal.update(_identity(row, player_id))
            offers.append(signal)

        offers.sort(
            key=lambda row: (
                _rank(row.get("recommendation")),
                -float(row.get("percentile") or 0.0),
                str(row.get("jugador_id") or ""),
            )
        )
        sell_rows = [row for row in offers if row.get("action") == "SELL"]
        hold_rows = [row for row in offers if row.get("action") == "HOLD"]
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "command": COMMAND,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mean_pct": round(global_mean, 6),
            "mean_source": global_source,
            "samples": global_samples,
            "count": len(offers),
            "summary": {
                "sell": len(sell_rows),
                "hold": len(hold_rows),
                "strong_sell": sum(1 for row in offers if row.get("recommendation") == "STRONG_SELL"),
                "liquidate_now": sum(1 for row in offers if row.get("recommendation") == "LIQUIDATE_NOW"),
                "strong_hold": sum(1 for row in offers if row.get("recommendation") == "STRONG_HOLD"),
                "cash_if_sell_eur": sum(int(row.get("offer_eur") or 0) for row in sell_rows),
                "ev_if_hold_eur": sum(int(row.get("ev_tomorrow_eur") or 0) for row in hold_rows),
            },
            "offers": offers,
            "skipped": skipped,
            "sends": False,
        }


def _identity(row: Mapping[str, Any], player_id: str) -> dict[str, Any]:
    """Campos de presentación que ya venían en la fila. Los ausentes quedan nulos."""
    return {
        "name": _text(row.get("name")),
        "nickname": _text(row.get("nickname")),
        "position": _text(row.get("position")),
        "club": _text(row.get("club")),
        "image_url": _text(row.get("image_url")),
    }


def _rank(recommendation: Any) -> int:
    order = {
        "STRONG_SELL": 0,
        "LIQUIDATE_NOW": 1,
        "SELL": 2,
        "HOLD": 3,
        "STRONG_HOLD": 4,
    }
    return order.get(str(recommendation or ""), 5)


def _rows(source: Any) -> list[Mapping[str, Any]]:
    if isinstance(source, Mapping):
        for key in ("jugadores_en_venta", "jugadores", "players", "offers", "listings"):
            value = source.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
        return []
    if isinstance(source, (list, tuple)):
        return [row for row in source if isinstance(row, Mapping)]
    return []

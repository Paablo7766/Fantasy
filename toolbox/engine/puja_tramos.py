"""Tres cifras de puja a partir de lo que los rivales han pagado de verdad.

La puja ideal es el valor del día por la mediana del tramo. La de asegurar es
el percentil 90, y solo se enseña cuando la cola del tramo es fina: hace falta
una muestra grande y que dos o tres compras extremas no muevan ese percentil.
La máxima es lo que el jugador vale para esta plantilla: lo que recuperas al
revenderlo más lo que valen los puntos que suma a tu once mientras lo tienes.

Un punto de mejora no vale los 16,4 M del ratio de mercado: ese ratio es lo
que cuesta *comprar* un jugador por cada punto que da, y ese dinero vuelve al
venderlo (ya está en la reventa). Lo que un punto vale de verdad es lo que se
pierde por conseguirlo: el premio que devuelve (100.000 € por punto y jornada)
más el sobreprecio que tu liga paga sobre el valor, repartido por punto.

Los multiplicadores salen de las compras (mismo día e interpoladas, más las
que vaya cerrando el diario). No hay un ×1,047 ni un ×1,25 escrito aquí.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from toolbox.analyzer import POSITIONS
from toolbox.bidding import URGENCIA_HUECO, urgencia_posicional
from toolbox.cache import cache_root
from toolbox.engine.live_matchday import EUROS_POR_PUNTO as PREMIO_POR_PUNTO
from toolbox.engine.market_predictor import EUROS_POR_PUNTO as RATIO_REFERENCIA, HORIZONTE_JORNADAS
from toolbox.engine.trading_desk import DEUDA_PCT_EQUIPO
from toolbox.league_history import LEAGUE_INITIAL_BUDGET, madrid_day

logger = logging.getLogger("fantasy.puja_tramos")

# Por debajo de esto la reventa no suma la previsión: en la muestra bajan.
UMBRAL_REVENTA = 1_500_000
# El xP de la foto deja de valer para la puja máxima al día. Misma caducidad
# que el guardarraíl: con un modelo viejo no hay cifra ni veredicto.
CADUCIDAD_XP_S = 24 * 3600
# La cola es fina si hay al menos esta muestra y quitar las compras de más
# del doble mueve el percentil 90 como mucho este tanto.
N_MINIMO_FIABLE = 20
COLA_EXTREMA = 2.0
HOLGURA_COLA = 0.05

# Con menos compras que estas el sobreprecio de la liga no se mide: solo cuenta el premio.
N_MINIMO_SOBREPRECIO = 8

# Aviso de estilo. No entra en la cifra.
_AL_VALOR = frozenset({"gerardo_vp", "naviis10"})
_DISPARAN = frozenset({"pabs fc", "iaaagocab"})

# id, etiqueta, desde (incluido), hasta (excluido; None = sin tope)
BANDAS: tuple[tuple[str, str, int, int | None], ...] = (
    ("<1.5", "menos de 1,5 M", 0, 1_500_000),
    ("1.5-4", "1,5–4 M", 1_500_000, 4_000_000),
    ("4-8", "4–8 M", 4_000_000, 8_000_000),
    ("8-15", "8–15 M", 8_000_000, 15_000_000),
    (">=15", "15 M o más", 15_000_000, None),
)

_lock = threading.Lock()
_muestra_cache: tuple[tuple[float, float, str | None], list[dict[str, Any]]] | None = None
_diario_cache: tuple[float, str | None, list[dict[str, Any]]] | None = None
_DIARIO_SEGUNDOS = 120.0


def banda_de(valor: int) -> tuple[str, str, int, int | None]:
    for banda in BANDAS:
        hasta = banda[3]
        if valor >= banda[2] and (hasta is None or valor < hasta):
            return banda
    return BANDAS[-1]


def percentil(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    return float(np.percentile(np.asarray(valores, dtype=float), q, method="linear"))


def cola_fina(ratios: list[float]) -> bool:
    """El percentil 90 se puede enseñar: no depende de dos o tres compras extremas."""
    if len(ratios) < N_MINIMO_FIABLE:
        return False
    p90 = percentil(ratios, 90)
    if p90 is None:
        return False
    resto = [ratio for ratio in ratios if ratio <= COLA_EXTREMA]
    if len(resto) == len(ratios):
        return True
    if len(resto) < 2:
        return False
    sin_extremos = percentil(resto, 90)
    return sin_extremos is not None and abs(sin_extremos - p90) <= HOLGURA_COLA


def tabla(filas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Mediana, percentil 90 y si ese 90 es enseñable, por tramo de valor."""
    grupos: dict[str, list[float]] = {banda[0]: [] for banda in BANDAS}
    for fila in filas:
        referencia = fila.get("reference_eur")
        ratio = fila.get("ratio")
        if isinstance(referencia, bool) or not isinstance(referencia, int) or referencia <= 0:
            continue
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or ratio <= 0:
            continue
        grupos[banda_de(referencia)[0]].append(float(ratio))
    salida: dict[str, dict[str, Any]] = {}
    for banda_id, etiqueta, _desde, _hasta in BANDAS:
        ratios = grupos[banda_id]
        mediana = percentil(ratios, 50)
        p90 = percentil(ratios, 90)
        fiable = cola_fina(ratios)
        salida[banda_id] = {
            "banda": banda_id,
            "etiqueta": etiqueta,
            "n": len(ratios),
            "mediana": None if mediana is None else round(mediana, 4),
            "p90": None if p90 is None else round(p90, 4),
            "fiable": fiable,
        }
    return salida


def precio_punto(filas: list[dict[str, Any]], ratio_mercado: Any = None) -> dict[str, Any]:
    """Euros que vale un punto de mejora del once durante el horizonte.

    Dos piezas, las dos medibles:

    * el premio: cada punto devuelve 100.000 € por jornada;
    * el sobreprecio de la liga: lo que se paga de más sobre el valor (mediana
      de todas las compras menos 1) por los euros de mercado que cuesta un
      punto. Es dinero que no vuelve al revender: el precio real del punto.

    Sin muestra suficiente solo cuenta el premio.
    """
    premio = PREMIO_POR_PUNTO * HORIZONTE_JORNADAS
    ratios = [
        float(fila["ratio"])
        for fila in filas
        if isinstance(fila, dict) and isinstance(fila.get("ratio"), (int, float)) and not isinstance(fila.get("ratio"), bool) and fila["ratio"] > 0
    ]
    ratio = float(ratio_mercado) if isinstance(ratio_mercado, (int, float)) and not isinstance(ratio_mercado, bool) and ratio_mercado > 0 else float(RATIO_REFERENCIA)
    mediana = percentil(ratios, 50) if len(ratios) >= N_MINIMO_SOBREPRECIO else None
    sobreprecio = 0 if mediana is None else int(round(max(0.0, mediana - 1.0) * ratio))
    return {
        "euros_por_punto": int(premio + sobreprecio),
        "premio_eur": int(premio),
        "sobreprecio_eur": sobreprecio,
        "sobrepuja_mediana": None if mediana is None else round(mediana, 4),
        "ratio_mercado": int(round(ratio)),
        "n": len(ratios),
    }


def reventa_eur(valor: int, valor_en_7d: Any) -> tuple[int, bool]:
    """Valor de reventa. Por debajo de 1,5 M no se suma la subida prevista."""
    if valor < UMBRAL_REVENTA:
        return valor, False
    if isinstance(valor_en_7d, bool) or not isinstance(valor_en_7d, int) or valor_en_7d <= 0:
        return valor, False
    return valor_en_7d, valor_en_7d != valor


def tope_eur(report: dict[str, Any] | None) -> tuple[int | None, str | None]:
    """Tope de la puja máxima: el margen del guardarraíl, o la caja más el crédito."""
    guardarrail = report.get("guardarrail_ruina") if isinstance(report, dict) else None
    margen = guardarrail.get("margen_eur") if isinstance(guardarrail, dict) else None
    if isinstance(margen, int) and not isinstance(margen, bool):
        return max(0, margen), "guardarrail"
    poder = report.get("poder_pujas") if isinstance(report, dict) else None
    if isinstance(poder, int) and not isinstance(poder, bool):
        return max(0, poder), "caja_credito"
    return None, None


def _epoch(marca: Any) -> float | None:
    if not isinstance(marca, str) or not marca.strip():
        return None
    try:
        instante = datetime.fromisoformat(marca.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.timestamp()


def tiene_xp(row: dict[str, Any]) -> bool:
    """Hay xP propio de este jugador. Sin él la máxima no se calcula."""
    propio = row.get("own_expected_points")
    if isinstance(propio, (int, float)) and not isinstance(propio, bool):
        return True
    if row.get("expected_points_source") != "own":
        return False
    puntos = row.get("expected_points")
    return isinstance(puntos, (int, float)) and not isinstance(puntos, bool)


def frescura_xp(marca: Any, presente: bool, *, now: datetime | None = None) -> dict[str, Any]:
    """Edad de la foto de xP. Fresco solo si el jugador tiene xP y la foto tiene menos de un día."""
    actual = now or datetime.now(timezone.utc)
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=timezone.utc)
    epoch = _epoch(marca)
    segundos = None if epoch is None else max(0.0, actual.timestamp() - epoch)
    edad = None if segundos is None else int(segundos // 3600)
    return {
        "xp_fresco": bool(presente) and segundos is not None and segundos <= CADUCIDAD_XP_S,
        "xp_edad_horas": edad,
        "xp_presente": bool(presente),
        "xp_fetched_at": marca.strip() if isinstance(marca, str) and marca.strip() else None,
        "horizonte_jornadas": HORIZONTE_JORNADAS,
    }


def _marca_xp(board: dict[str, Any] | None, payload: dict[str, Any]) -> Any:
    """Reloj del xP: la foto de tendencias, no la del mercado."""
    trends = board.get("trends") if isinstance(board, dict) else None
    if isinstance(trends, dict) and isinstance(trends.get("fetched_at"), str) and trends["fetched_at"].strip():
        return trends["fetched_at"]
    marca = payload.get("fetched_at") if isinstance(payload, dict) else None
    if isinstance(marca, str) and marca.strip():
        return marca
    return None


def mejora_xp(row: dict[str, Any]) -> float:
    """xP que suma al once. Cero si el solver no lo mete en el once."""
    if row.get("points_delta_source") != "own":
        return 0.0
    replaces = row.get("replaces")
    if not isinstance(replaces, dict) or not isinstance(replaces.get("formation"), str):
        return 0.0
    delta = row.get("points_delta")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or delta <= 0:
        return 0.0
    return float(delta)


def cifras(
    valor: int,
    stats: dict[str, Any],
    *,
    xp: float,
    reventa: int,
    subida: bool,
    tope: int | None,
    tope_motivo: str | None,
    euros_por_punto: int = PREMIO_POR_PUNTO * HORIZONTE_JORNADAS,
) -> dict[str, Any]:
    """Las tres cifras de un jugador. La máxima aún no aplica el parámetro editable: van las piezas."""
    mediana = stats.get("mediana")
    p90 = stats.get("p90")
    fiable = stats.get("fiable") is True and isinstance(p90, (int, float)) and not isinstance(p90, bool)
    ideal = int(round(valor * float(mediana))) if isinstance(mediana, (int, float)) and not isinstance(mediana, bool) else None
    asegurar = int(round(valor * float(p90))) if fiable else None
    return {
        "banda": stats.get("banda"),
        "etiqueta": stats.get("etiqueta"),
        "n": int(stats.get("n") or 0),
        "mediana": mediana if isinstance(mediana, (int, float)) and not isinstance(mediana, bool) else None,
        "ideal_eur": ideal,
        "p90": float(p90) if fiable else (float(p90) if isinstance(p90, (int, float)) and not isinstance(p90, bool) else None),
        "fiable": fiable,
        "asegurar_eur": asegurar,
        "asegurar_texto": None if fiable else "sin cifra fiable",
        "xp_delta": round(xp, 4),
        "reventa_eur": reventa,
        "subida_incluida": subida,
        "tope_eur": tope,
        "tope_motivo": tope_motivo,
        "euros_por_punto": int(euros_por_punto),
        "horizonte_jornadas": HORIZONTE_JORNADAS,
        "rivales": [],
    }


def _aviso(manager: Any, equipo: Any) -> str | None:
    nombres = set()
    for raw in (manager, equipo):
        if isinstance(raw, str) and raw.strip():
            nombres.add(raw.casefold().strip())
    if nombres & _AL_VALOR:
        return "suele ganar al valor"
    if nombres & _DISPARAN:
        return "dispara"
    return None


def _valor_plantilla(squad: dict[str, Any]) -> int:
    total = 0
    for jugador in squad.get("players") or []:
        if not isinstance(jugador, dict):
            continue
        valor = jugador.get("market_value")
        if isinstance(valor, int) and not isinstance(valor, bool) and valor > 0:
            total += valor
    return total


def _huecos_plantilla(squad: dict[str, Any]) -> set[str]:
    """Hueco de verdad: sin un fichaje en esa línea el once no llega a 11."""
    depth = {position: 0 for position in POSITIONS}
    for jugador in squad.get("players") or []:
        if not isinstance(jugador, dict):
            continue
        position = jugador.get("position")
        status = jugador.get("player_status")
        if position not in depth:
            continue
        if isinstance(status, str) and status.strip().lower() in {"injured", "suspended"}:
            continue
        depth[position] += 1
    return {position for position, level in urgencia_posicional(depth).items() if level == URGENCIA_HUECO}


def _caja_alta(ledger: dict[str, Any]) -> int | None:
    """Libro reconstruido. Si partió de menos de 100 M, se sube hasta ese inicio."""
    reconstructed = ledger.get("reconstructed_cash_eur")
    if isinstance(reconstructed, bool) or not isinstance(reconstructed, int):
        return None
    initial = ledger.get("initial_budget_eur")
    if isinstance(initial, int) and not isinstance(initial, bool) and 0 < initial < LEAGUE_INITIAL_BUDGET:
        return reconstructed + (LEAGUE_INITIAL_BUDGET - initial)
    return reconstructed


def rivales_con_hueco(board: dict[str, Any] | None, position: str | None, valor: int) -> list[dict[str, Any]]:
    """Rivales que pueden pagar este jugador y tienen un hueco en su puesto."""
    if not isinstance(board, dict) or position not in POSITIONS:
        return []
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    por_equipo = {
        str(rival.get("team_id")): rival
        for rival in (needs.get("rivals") or [])
        if isinstance(rival, dict) and rival.get("team_id") is not None
    }
    squads = board.get("squads") if isinstance(board.get("squads"), dict) else {}
    salida: list[dict[str, Any]] = []
    for squad in squads.get("squads") or []:
        if not isinstance(squad, dict) or squad.get("is_self") is True:
            continue
        team_id = squad.get("team_id")
        if not isinstance(team_id, str) or not team_id:
            continue
        rival = por_equipo.get(team_id)
        if isinstance(rival, dict) and isinstance(rival.get("xi_gaps"), list):
            huecos = {str(item) for item in rival["xi_gaps"]}
        else:
            huecos = _huecos_plantilla(squad)
        if position not in huecos:
            continue
        ledger = rival.get("ledger") if isinstance(rival, dict) and isinstance(rival.get("ledger"), dict) else None
        if ledger is None:
            continue
        caja = _caja_alta(ledger)
        if caja is None:
            continue
        poder = caja + int(_valor_plantilla(squad) * DEUDA_PCT_EQUIPO)
        if poder < valor:
            continue
        manager = rival.get("manager_name") or squad.get("manager_name")
        equipo = rival.get("fantasy_team_name") or squad.get("fantasy_team_name")
        avatar = squad.get("manager_avatar") if isinstance(squad.get("manager_avatar"), str) else None
        salida.append(
            {
                "team_id": team_id,
                "manager": manager if isinstance(manager, str) and manager.strip() else (equipo or "Rival"),
                "equipo": equipo if isinstance(equipo, str) else None,
                "avatar": avatar,
                "aviso": _aviso(manager, equipo),
                "puede_pujar_eur": poder,
            }
        )
    salida.sort(key=lambda row: str(row["manager"]).casefold())
    return salida


def _referencia(serie: dict[str, int], day: str) -> tuple[int, str] | None:
    if day in serie:
        valor = serie[day]
        return (valor, "mismo_dia") if valor > 0 else None
    previos = [clave for clave in serie if clave < day]
    siguientes = [clave for clave in serie if clave > day]
    if not previos or not siguientes:
        return None
    previo = max(previos)
    siguiente = min(siguientes)
    tramo = (date.fromisoformat(siguiente) - date.fromisoformat(previo)).days
    if tramo <= 0:
        return None
    paso = (date.fromisoformat(day) - date.fromisoformat(previo)).days
    valor = int(round(serie[previo] + (serie[siguiente] - serie[previo]) * paso / tramo))
    if valor <= 0:
        return None
    return valor, "interpolada"


def _leer_json(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("data") or raw.get("rows") or []
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _compras_locales(raiz: Path, propio: str | None) -> list[dict[str, Any]]:
    """Compras rivales con valor del mismo día o interpolado entre las dos fotos vecinas."""
    db = raiz / "responses.sqlite"
    precios: dict[tuple[str, str], int] = {}
    compras: list[tuple[str, str, int, str]] = []
    if db.is_file():
        try:
            conn = sqlite3.connect(db)
        except sqlite3.Error:
            conn = None
        if conn is not None:
            try:
                for player_id, day, value in conn.execute(
                    "select player_id, day, market_value from price_snapshots where market_value > 0"
                ):
                    if isinstance(player_id, str) and isinstance(day, str) and isinstance(value, int):
                        precios[(player_id, day)] = value
                for team_id, player_id, amount, at in conn.execute(
                    "select team_id, player_id, amount_eur, at from activity_buys"
                ):
                    if isinstance(team_id, str) and isinstance(player_id, str) and isinstance(amount, int) and amount > 0:
                        compras.append((team_id, player_id, amount, at if isinstance(at, str) else ""))
                try:
                    for player_id, day, price in conn.execute(
                        "select player_id, day, price from player_signal_log where price > 0"
                    ):
                        if (
                            isinstance(player_id, str)
                            and isinstance(day, str)
                            and isinstance(price, int)
                            and (player_id, day) not in precios
                        ):
                            precios[(player_id, day)] = price
                except sqlite3.Error:
                    pass
            except sqlite3.Error:
                logger.debug("sin histórico local de pujas", exc_info=True)
            finally:
                conn.close()
    for row in _leer_json(raiz / "supabase-local" / "price_snapshots.json"):
        player_id = row.get("player_id")
        day = row.get("day")
        value = row.get("market_value")
        if isinstance(player_id, str) and isinstance(day, str) and isinstance(value, int) and not isinstance(value, bool) and value > 0:
            precios[(player_id, day)] = value
    if not compras:
        for ledger in _leer_json(raiz / "supabase-local" / "cash_ledgers.json"):
            team_id = ledger.get("team_id")
            if not isinstance(team_id, str):
                continue
            for event in ledger.get("events") or []:
                if not isinstance(event, dict) or event.get("kind") != "buy":
                    continue
                amount = event.get("amount_eur")
                player_id = event.get("player_id")
                if isinstance(amount, int) and not isinstance(amount, bool) and amount > 0 and isinstance(player_id, str):
                    compras.append((team_id, player_id, amount, event.get("at") if isinstance(event.get("at"), str) else ""))

    series: dict[str, dict[str, int]] = {}
    for (player_id, day), value in precios.items():
        series.setdefault(player_id, {})[day] = value

    filas: list[dict[str, Any]] = []
    for team_id, player_id, amount, at in compras:
        if propio and team_id == propio:
            continue
        day = madrid_day(at)
        if not day:
            continue
        hallado = _referencia(series.get(player_id) or {}, day)
        if hallado is None:
            continue
        reference, origen = hallado
        filas.append(
            {
                "team_id": team_id,
                "player_id": player_id,
                "day": day,
                "amount_eur": amount,
                "reference_eur": reference,
                "ratio": amount / reference,
                "origen": origen,
            }
        )
    return filas


def _sumar_diario(filas: list[dict[str, Any]], diario: list[dict[str, Any]], propio: str | None) -> list[dict[str, Any]]:
    """Añade las compras nuevas del diario que el libro de actividad aún no tiene."""
    vistos = {(fila["team_id"], fila["player_id"], fila["day"]) for fila in filas}
    unidas = list(filas)
    for venta in diario:
        team_id = venta.get("team_id")
        player_id = venta.get("player_id")
        day = venta.get("day")
        amount = venta.get("amount_eur")
        reference = venta.get("reference_eur")
        if not isinstance(team_id, str) or not isinstance(player_id, str) or not isinstance(day, str):
            continue
        if propio and team_id == propio:
            continue
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            continue
        if isinstance(reference, bool) or not isinstance(reference, int) or reference <= 0:
            continue
        clave = (team_id, player_id, day)
        if clave in vistos:
            continue
        vistos.add(clave)
        unidas.append(
            {
                "team_id": team_id,
                "player_id": player_id,
                "day": day,
                "amount_eur": amount,
                "reference_eur": reference,
                "ratio": amount / reference,
                "origen": "diario",
            }
        )
    return unidas


def muestra(propio: str | None, league_id: str | None, *, raiz: Path | None = None) -> list[dict[str, Any]]:
    """La muestra viva: histórico local más las compras que el diario ya cerró."""
    base = raiz or cache_root()
    db = base / "responses.sqlite"
    fotos = base / "supabase-local" / "price_snapshots.json"
    firma = (
        db.stat().st_mtime if db.is_file() else 0.0,
        fotos.stat().st_mtime if fotos.is_file() else 0.0,
        propio,
    )
    global _muestra_cache
    with _lock:
        if raiz is None and _muestra_cache is not None and _muestra_cache[0] == firma:
            locales = _muestra_cache[1]
        else:
            locales = _compras_locales(base, propio)
            if raiz is None:
                _muestra_cache = (firma, locales)
    diario = _diario(league_id) if raiz is None else []
    return _sumar_diario(locales, diario, propio)


def _diario(league_id: str | None) -> list[dict[str, Any]]:
    global _diario_cache
    ahora = time.monotonic()
    with _lock:
        if _diario_cache is not None and _diario_cache[1] == league_id and ahora - _diario_cache[0] < _DIARIO_SEGUNDOS:
            return _diario_cache[2]
    try:
        from toolbox.auction_journal import ventas_cerradas

        ventas = ventas_cerradas(league_id)
    except Exception:
        logger.debug("diario de subastas no disponible", exc_info=True)
        ventas = []
    with _lock:
        _diario_cache = (ahora, league_id, ventas)
    return ventas


def _propio(board: dict[str, Any] | None) -> str | None:
    squads = board.get("squads") if isinstance(board, dict) and isinstance(board.get("squads"), dict) else {}
    for squad in squads.get("squads") or []:
        if isinstance(squad, dict) and squad.get("is_self") is True and isinstance(squad.get("team_id"), str):
            return squad["team_id"]
    return None


def _liga(board: dict[str, Any] | None, payload: dict[str, Any]) -> str | None:
    for documento in (
        payload,
        board.get("market") if isinstance(board, dict) else None,
        board.get("squads") if isinstance(board, dict) else None,
    ):
        if isinstance(documento, dict) and isinstance(documento.get("league_id"), str) and documento["league_id"]:
            return documento["league_id"]
    return None


def estampar(payload: dict[str, Any], board: dict[str, Any] | None, report: dict[str, Any] | None) -> None:
    """Añade ``puja_tramo`` a cada jugador del mercado. Un fallo no tumba el JSON."""
    decisiones = payload.get("market_decisions") if isinstance(payload, dict) else None
    if not isinstance(decisiones, list):
        return
    filas = muestra(_propio(board), _liga(board, payload))
    stats = tabla(filas)
    tope, motivo = tope_eur(report)
    marca = _marca_xp(board, payload)
    punto = precio_punto(filas, report.get("ratio_mercado") if isinstance(report, dict) else None)
    payload["puja_tramos"] = {
        "euros_por_punto": punto["euros_por_punto"],
        "precio_punto": punto,
        "horizonte_jornadas": HORIZONTE_JORNADAS,
        "muestra": len(filas),
        "bandas": [stats[banda[0]] for banda in BANDAS],
    }
    for row in decisiones:
        if not isinstance(row, dict):
            continue
        valor = row.get("market_value")
        if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
            valor = row.get("sale_price")
        if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
            continue
        banda = banda_de(valor)
        reventa, subida = reventa_eur(valor, row.get("valor_en_7d"))
        ficha = cifras(
            valor,
            stats[banda[0]],
            xp=mejora_xp(row),
            reventa=reventa,
            subida=subida,
            tope=tope,
            tope_motivo=motivo,
            euros_por_punto=punto["euros_por_punto"],
        )
        ficha["precio_punto"] = punto
        ficha.update(frescura_xp(marca, tiene_xp(row)))
        if banda[0] == "1.5-4":
            ficha["rivales"] = rivales_con_hueco(board, row.get("position") if isinstance(row.get("position"), str) else None, valor)
        row["puja_tramo"] = ficha

"""Post-mortem del lunes: fuga de alineación e impacto de no haber operado.

La fuga compara los puntos reales del once que alineamos con el máximo legal
que daba la plantilla de esa jornada. El trading compara valor, caja y puntos
de hoy con la foto guardada el lunes pasado, deshaciendo compras, cláusulas
y ventas del libro.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from toolbox.analyzer import own_squad
from toolbox.engine.lineup_math import solve_best_xi
from toolbox.portfolio import ledger_for_squad, ledger_index

MADRID = ZoneInfo("Europe/Madrid")
COMPRAS = {"buy", "clause"}
VENTAS = {"sell"}
_PUESTO = {
    "POR": "POR",
    "PT": "POR",
    "GK": "POR",
    "DEF": "DEF",
    "DF": "DEF",
    "MC": "MC",
    "MED": "MC",
    "MID": "MC",
    "DEL": "DEL",
    "DL": "DEL",
    "FW": "DEL",
}


def _ruta(path: Path | None) -> Path:
    if path is not None:
        return path
    from toolbox.cache import cache_root

    return cache_root() / "auditoria_lunes.json"


def _ahora(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _dia_madrid(moment: datetime) -> date:
    return moment.astimezone(MADRID).date()


def _fecha(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _momento(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MADRID)
    return parsed.astimezone(timezone.utc)


def _euros(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _puntos(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _pid(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _puesto(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _PUESTO.get(value.strip().upper())


def _nombre(row: dict[str, Any], pid: str) -> str:
    for key in ("nickname", "nombre", "name"):
        label = row.get(key)
        if isinstance(label, str) and label.strip():
            return label.strip()
    return pid


def leer_snapshots(path: Path | None = None) -> list[dict[str, Any]]:
    ruta = _ruta(path)
    if not ruta.is_file():
        return []
    try:
        raw = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def guardar_snapshot(snapshot: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """La primera foto del día y la liga se queda. Las siguientes no la pisan."""
    rows = leer_snapshots(path)
    day = snapshot.get("day")
    league = snapshot.get("league_id")
    for row in rows:
        if row.get("day") == day and row.get("league_id") == league:
            return row
    rows.append(snapshot)
    ruta = _ruta(path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)
    return snapshot


def lunes_de_referencia(
    snapshots: list[dict[str, Any]],
    hoy: date,
    league_id: str | None,
) -> dict[str, Any] | None:
    """La foto de lunes más reciente, estrictamente anterior a hoy."""
    candidatos: list[tuple[date, dict[str, Any]]] = []
    for row in snapshots:
        if league_id and row.get("league_id") not in (None, league_id):
            continue
        day = _fecha(row.get("day"))
        if day is None or day >= hoy or day.weekday() != 0:
            continue
        candidatos.append((day, row))
    if not candidatos:
        return None
    candidatos.sort(key=lambda item: item[0])
    return candidatos[-1][1]


def fuga_alineacion(plantilla: list[dict[str, Any]]) -> dict[str, Any]:
    """Puntos del once alineado frente al mejor once legal de la plantilla.

    Cada fila trae ``player_id``, ``position``, ``puntos`` y ``en_xi``.
    El máximo usa los puntos reales, sin la penalización de varianza del plan.
    """
    filas = [row for row in plantilla if isinstance(row, dict) and _pid(row.get("player_id"))]
    once = [row for row in filas if row.get("en_xi") is True and _puesto(row.get("position"))]
    if len(once) != 11:
        return {
            "disponible": False,
            "motivo": "sin_once",
            "detalle": "No hay un once de 11 jugadores con puesto para auditar la alineación.",
            "puntos_once": None,
            "puntos_maximos": None,
            "fuga": None,
            "formacion_optima": None,
            "dejados_fuera": [],
            "sobraban": [],
        }
    if any(_puntos(row.get("puntos")) is None for row in once):
        return {
            "disponible": False,
            "motivo": "puntos_pendientes",
            "detalle": "La jornada todavía no tiene los puntos de todos los titulares.",
            "puntos_once": None,
            "puntos_maximos": None,
            "fuga": None,
            "formacion_optima": None,
            "dejados_fuera": [],
            "sobraban": [],
        }
    puntos_once = round(sum(float(row["puntos"]) for row in once), 2)
    candidatos = []
    for row in filas:
        puntos = _puntos(row.get("puntos"))
        puesto = _puesto(row.get("position"))
        pid = _pid(row.get("player_id"))
        if puntos is None or puesto is None or pid is None:
            continue
        candidatos.append(
            {
                "player_id": pid,
                "position": puesto,
                "jornada": puntos,
                "nombre": _nombre(row, pid),
            }
        )
    optimo = solve_best_xi(candidatos, lambda_var=0.0)
    if not optimo.get("ok"):
        return {
            "disponible": False,
            "motivo": "sin_formacion",
            "detalle": "Con los puntos de la plantilla no sale un once legal.",
            "puntos_once": puntos_once,
            "puntos_maximos": None,
            "fuga": None,
            "formacion_optima": None,
            "dejados_fuera": [],
            "sobraban": [],
        }
    por_id = {row["player_id"]: row for row in candidatos}
    ids_once = {_pid(row.get("player_id")) for row in once}
    ids_optimo = [pid for pid in optimo.get("player_ids") or [] if isinstance(pid, str)]
    puntos_maximos = round(float(optimo["puntos"]), 2)

    def _tarjeta(pid: str) -> dict[str, Any]:
        row = por_id.get(pid, {})
        return {
            "player_id": pid,
            "nombre": row.get("nombre") or pid,
            "position": row.get("position"),
            "puntos": row.get("jornada"),
        }

    return {
        "disponible": True,
        "motivo": None,
        "detalle": None,
        "puntos_once": puntos_once,
        "puntos_maximos": puntos_maximos,
        "fuga": round(max(0.0, puntos_maximos - puntos_once), 2),
        "formacion_optima": optimo.get("formacion"),
        "dejados_fuera": [_tarjeta(pid) for pid in ids_optimo if pid not in ids_once],
        "sobraban": [_tarjeta(pid) for pid in ids_once if isinstance(pid, str) and pid not in ids_optimo],
    }


def caja_sin_fichajes(
    caja_hoy: int | None,
    eventos: list[dict[str, Any]],
    desde: datetime | None,
) -> tuple[int | None, dict[str, int]]:
    """Caja de hoy deshaciendo compras, cláusulas y ventas posteriores a la foto."""
    resumen = {"compras_eur": 0, "ventas_eur": 0, "operaciones": 0}
    if not isinstance(caja_hoy, int) or isinstance(caja_hoy, bool) or desde is None:
        return None, resumen
    for evento in eventos:
        if not isinstance(evento, dict):
            continue
        momento = _momento(evento.get("at"))
        if momento is None or momento <= desde:
            continue
        importe = _euros(evento.get("amount_eur"))
        if importe is None:
            continue
        kind = evento.get("kind")
        if kind in COMPRAS:
            resumen["compras_eur"] += importe
            resumen["operaciones"] += 1
        elif kind in VENTAS:
            resumen["ventas_eur"] += importe
            resumen["operaciones"] += 1
    return caja_hoy + resumen["compras_eur"] - resumen["ventas_eur"], resumen


def _no_trading(detalle: str, motivo: str = "sin_snapshot") -> dict[str, Any]:
    return {
        "disponible": False,
        "motivo": motivo,
        "detalle": detalle,
        "snapshot_day": None,
        "snapshot_es_lunes": False,
        "operaciones": 0,
        "compras_eur": 0,
        "ventas_eur": 0,
        "valores_congelados": 0,
        "hoy": {"valor": None, "caja": None, "puntos": None},
        "sin_operar": {"valor": None, "caja": None, "puntos": None},
        "delta_valor": None,
        "delta_caja": None,
        "delta_puntos": None,
    }


def _delta(actual: int | float | None, base: int | float | None) -> int | float | None:
    if actual is None or base is None:
        return None
    if isinstance(actual, float) or isinstance(base, float):
        return round(float(actual) - float(base), 2)
    return int(actual) - int(base)


def _own(board: dict[str, Any]) -> dict[str, Any] | None:
    raw = board.get("squads")
    if isinstance(raw, list):
        return own_squad({"squads": raw})
    if isinstance(raw, dict):
        found = own_squad(raw)
        if found is not None:
            return found
    return own_squad(board)


def _league_id(board: dict[str, Any]) -> str | None:
    for key in ("squads", "trends", "market"):
        block = board.get(key)
        if isinstance(block, dict) and isinstance(block.get("league_id"), str) and block["league_id"].strip():
            return block["league_id"].strip()
    if isinstance(board.get("league_id"), str) and board["league_id"].strip():
        return board["league_id"].strip()
    return None


def _index_jugadores(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}

    def add(row: Any) -> None:
        if not isinstance(row, dict):
            return
        pid = _pid(row.get("player_id"))
        if pid is None:
            return
        previo = index.get(pid)
        if previo is None:
            index[pid] = row
            return
        previo_puntos = isinstance(previo.get("week_points_by_round"), dict)
        nuevo_puntos = isinstance(row.get("week_points_by_round"), dict)
        if nuevo_puntos and not previo_puntos:
            index[pid] = row

    document = board.get("squads")
    squads = document.get("squads") if isinstance(document, dict) else document
    if isinstance(squads, list):
        for squad in squads:
            if isinstance(squad, dict):
                for player in squad.get("players") or []:
                    add(player)
    trends = board.get("trends") if isinstance(board.get("trends"), dict) else {}
    for key in ("players", "rising", "falling", "undervalued"):
        for player in trends.get(key) or []:
            add(player)
    market = board.get("market") if isinstance(board.get("market"), dict) else {}
    for listing in market.get("listings") or []:
        add(listing)
    return index


def _once_ids(board: dict[str, Any]) -> tuple[list[str], str]:
    """El once que se audita es el guardado en la app, no el que recomienda el solver."""
    optimize = board.get("optimize") if isinstance(board.get("optimize"), dict) else {}
    saved = optimize.get("saved_lineup") if isinstance(optimize.get("saved_lineup"), dict) else {}
    xi = saved.get("xi") if isinstance(saved.get("xi"), list) else []
    ids = [pid for row in xi if isinstance(row, dict) and (pid := _pid(row.get("player_id")))]
    if len(ids) == 11:
        return ids, "guardado"
    if ids:
        return [], "incompleto"
    return [], "ninguno"


def _jornada(players: list[dict[str, Any]]) -> str | None:
    weeks: list[int] = []
    hay_serie = False
    for player in players:
        if not isinstance(player, dict):
            continue
        mapping = player.get("week_points_by_round")
        if isinstance(mapping, dict):
            for key in mapping:
                if isinstance(key, str) and key.isdigit():
                    weeks.append(int(key))
        serie = player.get("week_points")
        if isinstance(serie, list) and serie:
            hay_serie = True
    if weeks:
        return str(max(weeks))
    # La foto guarda la serie sin número de jornada. El último valor es el partido más reciente.
    return "ultima" if hay_serie else None


def _puntos_jornada(player: dict[str, Any] | None, jornada: str | None) -> float | None:
    if not isinstance(player, dict) or jornada is None:
        return None
    if jornada != "ultima":
        mapping = player.get("week_points_by_round")
        if isinstance(mapping, dict) and jornada in mapping:
            return _puntos(mapping.get(jornada))
        return None
    serie = player.get("week_points")
    if isinstance(serie, list) and serie:
        return _puntos(serie[-1])
    return None


def _eventos(board: dict[str, Any], squad: dict[str, Any] | None) -> list[dict[str, Any]]:
    needs = board.get("needs") if isinstance(board.get("needs"), dict) else {}
    ledgers = [row for row in needs.get("ledgers") or [] if isinstance(row, dict)]
    book = ledger_for_squad(squad, ledger_index(ledgers)) if isinstance(squad, dict) else None
    if not isinstance(book, dict) or not isinstance(book.get("events"), list):
        return []
    return [row for row in book["events"] if isinstance(row, dict)]


def _fila(
    player: dict[str, Any],
    *,
    jornada: str | None,
    en_xi: bool,
    propia: bool,
) -> dict[str, Any] | None:
    pid = _pid(player.get("player_id"))
    puesto = _puesto(player.get("position"))
    if pid is None or puesto is None:
        return None
    return {
        "player_id": pid,
        "nombre": _nombre(player, pid),
        "position": puesto,
        "puntos": _puntos_jornada(player, jornada),
        "valor": _euros(player.get("market_value")),
        "en_xi": en_xi,
        "propia": propia,
    }


def _puntos_plantilla_congelada(
    snapshot: dict[str, Any],
    index: dict[str, dict[str, Any]],
    jornada: str | None,
) -> float | None:
    """Mejor once legal de la plantilla del lunes, con los puntos de esta jornada."""
    candidatos: list[dict[str, Any]] = []
    for jugador in snapshot.get("jugadores") or []:
        if not isinstance(jugador, dict):
            continue
        pid = _pid(jugador.get("player_id"))
        puesto = _puesto(jugador.get("position"))
        if pid is None or puesto is None:
            continue
        puntos = _puntos_jornada(index.get(pid), jornada)
        if puntos is None:
            continue
        candidatos.append({"player_id": pid, "position": puesto, "jornada": puntos})
    optimo = solve_best_xi(candidatos, lambda_var=0.0)
    if not optimo.get("ok"):
        return None
    return round(float(optimo["puntos"]), 2)


def _valor_congelado(
    snapshot: dict[str, Any],
    index: dict[str, dict[str, Any]],
) -> tuple[int | None, int]:
    total = 0
    conocidos = 0
    congelados = 0
    for jugador in snapshot.get("jugadores") or []:
        if not isinstance(jugador, dict):
            continue
        pid = _pid(jugador.get("player_id"))
        if pid is None:
            continue
        actual = index.get(pid)
        valor = _euros(actual.get("market_value")) if isinstance(actual, dict) else None
        if valor is None:
            valor = _euros(jugador.get("valor"))
            if valor is not None:
                congelados += 1
        if valor is None:
            continue
        total += valor
        conocidos += 1
    if conocidos == 0:
        return None, congelados
    return total, congelados


def construir_post_mortem(
    board: dict[str, Any],
    *,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Audita la jornada cerrada y guarda la foto del día si todavía no existe."""
    moment = _ahora(now)
    hoy = _dia_madrid(moment)
    squad = _own(board) if isinstance(board, dict) else None
    index = _index_jugadores(board) if isinstance(board, dict) else {}
    players = squad.get("players") if isinstance(squad, dict) and isinstance(squad.get("players"), list) else []
    players = [row for row in players if isinstance(row, dict)]
    jornada = _jornada(players) or _jornada(list(index.values()))
    once_ids, once_fuente = _once_ids(board) if isinstance(board, dict) else ([], "ninguno")
    once = set(once_ids)
    plantilla: list[dict[str, Any]] = []
    for player in players:
        fila = _fila(player, jornada=jornada, en_xi=_pid(player.get("player_id")) in once, propia=True)
        if fila is not None:
            plantilla.append(fila)
    conocidos = {row["player_id"] for row in plantilla}
    for pid in once_ids:
        if pid in conocidos:
            continue
        extra = index.get(pid)
        if not isinstance(extra, dict):
            continue
        fila = _fila(extra, jornada=jornada, en_xi=True, propia=False)
        if fila is not None:
            plantilla.append(fila)
    fuga = fuga_alineacion(plantilla)
    if once_fuente == "incompleto":
        fuga["detalle"] = "El once guardado no llega a 11 jugadores, así que no se puede medir la fuga."
        fuga["motivo"] = "sin_once"
    league_id = _league_id(board) if isinstance(board, dict) else None
    referencia = lunes_de_referencia(leer_snapshots(path), hoy, league_id)
    trading = _trading(
        referencia,
        plantilla=plantilla,
        fuga=fuga,
        caja_hoy=_euros(squad.get("cash")) if isinstance(squad, dict) else None,
        eventos=_eventos(board, squad) if isinstance(board, dict) else [],
        index=index,
        jornada=jornada,
    )
    foto = _foto_del_dia(
        hoy=hoy,
        moment=moment,
        league_id=league_id,
        squad=squad,
        plantilla=plantilla,
    )
    guardada = guardar_snapshot(foto, path) if foto is not None else None
    return {
        "es_lunes": hoy.weekday() == 0,
        "hoy": hoy.isoformat(),
        "jornada": jornada,
        "once_fuente": once_fuente,
        "fuga": fuga,
        "trading": trading,
        "snapshot_guardado": None
        if guardada is None
        else {"day": guardada.get("day"), "nuevo": guardada is foto},
    }


def _trading(
    referencia: dict[str, Any] | None,
    *,
    plantilla: list[dict[str, Any]],
    fuga: dict[str, Any],
    caja_hoy: int | None,
    eventos: list[dict[str, Any]],
    index: dict[str, dict[str, Any]],
    jornada: str | None,
) -> dict[str, Any]:
    if referencia is None:
        return _no_trading(
            "Todavía no hay foto del lunes pasado. Esta visita guarda la de hoy; "
            "el impacto del trading se podrá medir a partir del próximo lunes."
        )
    desde = _momento(referencia.get("guardado_en"))
    caja_base, resumen = caja_sin_fichajes(caja_hoy, eventos, desde)
    valor_hoy = _euros_suma(row.get("valor") for row in plantilla if row.get("propia") is True)
    valor_base, congelados = _valor_congelado(referencia, index)
    puntos_hoy = _puntos(fuga.get("puntos_once")) if fuga.get("disponible") else None
    puntos_base = _puntos_plantilla_congelada(referencia, index, jornada)
    hoy_bloque = {"valor": valor_hoy, "caja": caja_hoy, "puntos": puntos_hoy}
    base_bloque = {"valor": valor_base, "caja": caja_base, "puntos": puntos_base}
    deltas = {
        "delta_valor": _delta(valor_hoy, valor_base),
        "delta_caja": _delta(caja_hoy, caja_base),
        "delta_puntos": _delta(puntos_hoy, puntos_base),
    }
    disponible = any(value is not None for value in deltas.values())
    return {
        "disponible": disponible,
        "motivo": None if disponible else "datos_incompletos",
        "detalle": None
        if disponible
        else "Hay foto del lunes, pero no se puede reconstruir valor, caja ni puntos.",
        "snapshot_day": referencia.get("day"),
        "snapshot_es_lunes": _fecha(referencia.get("day")).weekday() == 0 if _fecha(referencia.get("day")) else False,
        "operaciones": resumen["operaciones"],
        "compras_eur": resumen["compras_eur"],
        "ventas_eur": resumen["ventas_eur"],
        "valores_congelados": congelados,
        "hoy": hoy_bloque,
        "sin_operar": base_bloque,
        **deltas,
    }


def _euros_suma(valores: Any) -> int | None:
    total = 0
    alguno = False
    for valor in valores:
        importe = _euros(valor)
        if importe is None:
            continue
        total += importe
        alguno = True
    return total if alguno else None


def _foto_del_dia(
    *,
    hoy: date,
    moment: datetime,
    league_id: str | None,
    squad: dict[str, Any] | None,
    plantilla: list[dict[str, Any]],
) -> dict[str, Any] | None:
    propias = [row for row in plantilla if row.get("propia") is True]
    if not isinstance(squad, dict) or not propias:
        return None
    return {
        "day": hoy.isoformat(),
        "league_id": league_id,
        "team_id": _pid(squad.get("team_id")),
        "guardado_en": moment.astimezone(timezone.utc).isoformat(),
        "caja": _euros(squad.get("cash")),
        "puntos_equipo": _euros(squad.get("points")),
        "valor_equipo": _euros_suma(row.get("valor") for row in propias),
        "jugadores": [
            {
                "player_id": row["player_id"],
                "nombre": row["nombre"],
                "position": row["position"],
                "valor": row.get("valor"),
                "en_xi": row.get("en_xi") is True,
            }
            for row in propias
        ],
    }

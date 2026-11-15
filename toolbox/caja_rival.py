"""Caja rival única: el gasto oculto en subidas de cláusula, sacado de las fotos diarias.

El feed de actividad trae compras, ventas, premios y clausulazos, pero no las
subidas de cláusula. Este módulo las reconstruye desde el historial de fotos
de cláusulas (``clause_snapshot_history.json``) con las reglas medidas en
``investigacion/caja_pujas`` (15-nov-2026):

* una foto idéntica, equipo a equipo, a otra anterior es una copia de caché y
  se descarta (el 25-oct y el 3-nov repetían el 24-oct y cobraban dos veces);
* la base de cada jugador es la cláusula de la foto anterior o, si llegó por
  compra o clausulazo, el precio pagado; las subidas se encadenan contra la
  cláusula más alta ya medida;
* una subida que deja la cláusula en el valor de mercado del día es el suelo
  automático (la cláusula nunca baja del valor) y no cuesta nada;
* el resto cuesta la mitad del aumento sobre ``max(base, valor)`` (regla 1:2);
* un jugador del reparto inicial no tiene base conocida: su exceso sobre el
  valor no se cobra (solo cabría en un mínimo, no en la caja probable).

El resultado alimenta ``books_from_activity`` (``anchor_legal_floor``), así que
pujas, cláusulas y plan leen la misma caja: 100 M + feed − subidas.

El historial vive en ``.cache``, que en Render se borra en cada despliegue. Por
eso se copia también en Supabase (``dashboard_snapshots``, clave
``clausulas:historial``) y se fusiona al leer.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

_MADRID = ZoneInfo("Europe/Madrid")

#: Regla oficial 1:2: 2 M de cláusula cuestan 1 M de saldo.
COSTE_POR_EURO_DE_CLAUSULA = 0.5
#: Euros entre cláusula y valor del día para llamarla subida automática.
TOLERANCIA_AUTOMATICA_EUR = 1_000
#: Días de fotos que se conservan (igual que ``CLAUSE_SNAPSHOT_KEEP_DAYS``).
DIAS_CONSERVADOS = 45

REMOTO_KIND = "clausulas"
REMOTO_CLAVE = "historial"


# --- Historial de fotos -----------------------------------------------------


def _dias_validos(data: Any) -> dict[str, dict[str, dict[str, int]]]:
    """``{día: {equipo: {jugador: cláusula}}}`` limpio de un documento guardado."""
    days = data.get("days") if isinstance(data, Mapping) else None
    out: dict[str, dict[str, dict[str, int]]] = {}
    if not isinstance(days, Mapping):
        return out
    for day, teams in days.items():
        try:
            date.fromisoformat(str(day))
        except ValueError:
            continue
        if not isinstance(teams, Mapping):
            continue
        limpio: dict[str, dict[str, int]] = {}
        for team_id, players in teams.items():
            if not isinstance(players, Mapping):
                continue
            jugadores = {
                str(pid): int(clause)
                for pid, clause in players.items()
                if isinstance(clause, (int, float)) and not isinstance(clause, bool) and clause > 0
            }
            if jugadores:
                limpio[str(team_id)] = jugadores
        if limpio:
            out[str(day)] = limpio
    return out


def fusionar_historial(*documentos: Any) -> dict[str, dict[str, dict[str, int]]]:
    """Une varios historiales. Un día que ya estaba no se pisa: la primera foto del día manda."""
    days: dict[str, dict[str, dict[str, int]]] = {}
    for documento in documentos:
        for day, teams in _dias_validos(documento).items():
            days.setdefault(day, teams)
    keep = sorted(days)[-DIAS_CONSERVADOS:]
    return {day: days[day] for day in keep}


def leer_remoto() -> dict[str, Any] | None:
    """Historial copiado en Supabase, o ``None`` sin Supabase o sin copia. Nunca lanza."""
    try:
        from toolbox import snapshot_remote

        envelope = snapshot_remote.load(REMOTO_KIND, REMOTO_CLAVE)
    except Exception:  # noqa: BLE001 - sin copia remota queda la local
        return None
    if not isinstance(envelope, dict):
        return None
    value = envelope.get("value")
    return value if isinstance(value, dict) else None


def publicar_remoto(payload: Mapping[str, Any]) -> bool:
    """Copia el historial en Supabase. ``False`` sin Supabase o si falla. Nunca lanza."""
    try:
        from toolbox import snapshot_remote

        return snapshot_remote.save(
            REMOTO_KIND,
            REMOTO_CLAVE,
            {"saved_unix": time.time(), "value": dict(payload)},
        )
    except Exception:  # noqa: BLE001
        return False


def valores_de_fotos(*documentos: Any) -> dict[tuple[str, str], int]:
    """``{(jugador, día): valor}`` guardado junto a las cláusulas (historial v2)."""
    out: dict[tuple[str, str], int] = {}
    for documento in documentos:
        values = documento.get("values") if isinstance(documento, Mapping) else None
        if not isinstance(values, Mapping):
            continue
        for day, players in values.items():
            if not isinstance(players, Mapping):
                continue
            for pid, value in players.items():
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    out.setdefault((str(pid), str(day)), value)
    return out


def historial_de_clausulas(
    path: Path | None = None,
) -> tuple[dict[str, dict[str, dict[str, int]]], dict[tuple[str, str], int]]:
    """Fotos locales más las de Supabase, y el valor del día guardado con ellas.

    Lo local manda si un día está en los dos.
    """
    import json

    from toolbox.cache import cache_root
    from toolbox.rival_intel import CLAUSE_SNAPSHOTS_FILENAME

    ruta = path or cache_root() / CLAUSE_SNAPSHOTS_FILENAME
    local: Any = None
    try:
        with ruta.open("r", encoding="utf-8") as handle:
            local = json.load(handle)
    except (OSError, ValueError):
        local = None
    remoto = leer_remoto()
    return fusionar_historial(local, remoto), valores_de_fotos(local, remoto)


# --- Subidas ----------------------------------------------------------------


def _parse_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_MADRID)
    return moment.astimezone(_MADRID)


def adquisiciones_de_eventos(eventos: list[dict[str, Any]]) -> dict[tuple[str, str], list[tuple[datetime, int]]]:
    """Compras y clausulazos pagados por equipo y jugador, en orden de tiempo."""
    out: dict[tuple[str, str], list[tuple[datetime, int]]] = defaultdict(list)
    for evento in eventos:
        if not isinstance(evento, Mapping) or evento.get("kind") not in {"buy", "clause"}:
            continue
        team_id, player_id = evento.get("team_id"), evento.get("player_id")
        at = _parse_at(evento.get("at"))
        amount = evento.get("amount_eur")
        if not isinstance(team_id, str) or not isinstance(player_id, str) or at is None:
            continue
        if isinstance(amount, bool) or not isinstance(amount, int):
            continue
        out[(team_id, player_id)].append((at, abs(amount)))
    for filas in out.values():
        filas.sort(key=lambda item: item[0])
    return out


def _valor_del_dia(valores: Mapping[tuple[str, str], int], player_id: str, day: str) -> int | None:
    """Valor de mercado del día o, si no hay foto, el de la víspera."""
    for dia in (day, (date.fromisoformat(day) - timedelta(days=1)).isoformat()):
        value = valores.get((player_id, dia))
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _fin_del_dia(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(hour=23, minute=59, tzinfo=_MADRID)


def subidas_de_clausula(
    dias: Mapping[str, Mapping[str, Mapping[str, int]]],
    valores: Mapping[tuple[str, str], int],
    adquisiciones: Mapping[tuple[str, str], list[tuple[datetime, int]]],
) -> list[dict[str, Any]]:
    """Cada subida de cláusula detectada, con su tipo y su coste.

    ``tipo``: ``automatica`` (coste 0), ``manual`` / ``manual_sin_valor`` (1:2
    sobre lo que supera la base y el valor) o ``reparto`` (sin base conocida;
    coste 0 en la caja probable, el exceso queda en ``exceso_eur``).
    """
    ordenados: list[str] = []
    for day in sorted(dias):
        foto = dias[day]
        if any(all(dias[prev].get(team) == players for team, players in foto.items()) for prev in ordenados):
            continue
        ordenados.append(day)

    out: list[dict[str, Any]] = []
    previa: dict[str, tuple[str, Mapping[str, int]]] = {}
    techo: dict[tuple[str, str], int] = {}
    for day in ordenados:
        instante = _fin_del_dia(day)
        for team_id, jugadores in dias[day].items():
            antes_dia, antes = previa.get(team_id, (None, {}))
            antes_inst = _fin_del_dia(antes_dia) if antes_dia else None
            for player_id, clausula in jugadores.items():
                valor = _valor_del_dia(valores, player_id, day)
                compras = [a for a in adquisiciones.get((team_id, player_id), []) if a[0] <= instante]
                nuevas = [a for a in compras if antes_inst is None or a[0] > antes_inst]
                if nuevas:
                    techo.pop((team_id, player_id), None)
                if player_id in antes and not nuevas:
                    base: int | None = max(antes[player_id], techo.get((team_id, player_id), 0))
                elif compras:
                    base = max(compras[-1][1], techo.get((team_id, player_id), 0))
                else:
                    # Reparto inicial (primera foto) o hueco de fotos: base desconocida.
                    base = None
                fila = {
                    "team_id": team_id,
                    "player_id": player_id,
                    "day": day,
                    "from_day": antes_dia,
                    "clause_before_eur": base,
                    "clause_after_eur": clausula,
                    "market_value_eur": valor,
                    "source": "fotos",
                }
                if base is None:
                    exceso = clausula - valor if valor else None
                    if exceso and exceso > TOLERANCIA_AUTOMATICA_EUR and antes_dia is None:
                        out.append({**fila, "tipo": "reparto", "increase_eur": 0, "exceso_eur": exceso, "cost_eur": 0})
                    continue
                techo[(team_id, player_id)] = max(techo.get((team_id, player_id), 0), clausula)
                if clausula <= base:
                    continue
                if valor is not None and abs(clausula - valor) <= TOLERANCIA_AUTOMATICA_EUR:
                    out.append({**fila, "tipo": "automatica", "increase_eur": clausula - base, "cost_eur": 0})
                    continue
                aumento = clausula - max(base, valor or 0)
                if aumento <= TOLERANCIA_AUTOMATICA_EUR:
                    continue
                out.append(
                    {
                        **fila,
                        "tipo": "manual" if valor is not None else "manual_sin_valor",
                        "increase_eur": aumento,
                        "cost_eur": int(aumento * COSTE_POR_EURO_DE_CLAUSULA),
                    }
                )
            previa[team_id] = (day, jugadores)
    return out


def costes_ocultos(
    eventos: list[dict[str, Any]],
    valores: Mapping[tuple[str, str], int],
    *,
    dias: Mapping[str, Mapping[str, Mapping[str, int]]] | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Subidas con coste > 0, en el formato que espera ``anchor_legal_floor``.

    El valor guardado con la foto manda sobre ``valores`` (fotos de precio de
    otra hora o con huecos): una subida automática sin valor se cobraría.
    """
    if dias is None:
        dias, de_fotos = historial_de_clausulas(path)
        valores = {**valores, **de_fotos}
    subidas = subidas_de_clausula(dias, valores, adquisiciones_de_eventos(eventos))
    return [fila for fila in subidas if fila["cost_eur"] > 0]

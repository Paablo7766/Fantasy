"""Reglas del Marcador: qué previsión cuenta y cuándo un resultado es definitivo.

Dos fallos dejaban el Marcador contaminado:

* La J12 se puntuó a las 23:06 del viernes, dos horas después del saque del
  Sevilla-Betis. La API ya trae la fila de la jornada con 0 puntos mientras el
  partido se juega o antes de publicar los puntos: los 14 jugadores, portero
  incluido, quedaron con 0.
* La foto de la J11 se tomó el lunes, con partidos ya jugados. Una «previsión»
  guardada después del saque no es una previsión.

Aquí vive la regla única que usan el evaluador, la fusión con Supabase y la
reparación del histórico.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

#: Horas desde el saque hasta dar por buenos los puntos de LaLiga.
HORAS_PUNTOS_DEFINITIVOS = 24.0


def epoch_kickoff(kickoff: Any) -> float | None:
    """Segundos Unix del saque (ISO 8601). None si no se puede leer."""
    if not isinstance(kickoff, str) or not kickoff.strip():
        return None
    try:
        moment = datetime.fromisoformat(kickoff.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def puntos_definitivos(kickoff: Any, *, ahora: float | None = None) -> bool:
    """¿Han pasado ``HORAS_PUNTOS_DEFINITIVOS`` desde el saque?

    Sin saque conocido no se puede saber: no se puntúa.
    """
    inicio = epoch_kickoff(kickoff)
    if inicio is None:
        return False
    momento = time.time() if ahora is None else ahora
    return momento >= inicio + HORAS_PUNTOS_DEFINITIVOS * 3600.0


def previa_valida(kickoff: Any, stored_at: Any) -> bool:
    """La previsión se guardó antes del saque (o no se sabe cuándo empieza)."""
    inicio = epoch_kickoff(kickoff)
    if inicio is None or not isinstance(stored_at, (int, float)) or isinstance(stored_at, bool):
        return True
    return float(stored_at) < inicio


def evaluacion_prematura(kickoff: Any, evaluated_at: Any) -> bool:
    """Puntos apuntados antes de ser definitivos."""
    if not isinstance(evaluated_at, (int, float)) or isinstance(evaluated_at, bool):
        return False
    inicio = epoch_kickoff(kickoff)
    if inicio is None:
        return False
    return float(evaluated_at) < inicio + HORAS_PUNTOS_DEFINITIVOS * 3600.0


#: Un partido que se juega más de esto después del primero de su jornada es un
#: aplazado: no marca cuándo son definitivos los puntos del resto.
DIAS_BLOQUE_JORNADA = 4.0


def ultimo_saque_por_jornada(filas: Any) -> dict[str, str]:
    """Último saque del bloque principal de cada jornada, para las filas sin saque propio.

    ``filas``: pares ``(jornada, kickoff)``. Un aplazado semanas después (J12 tuvo uno
    el 22-nov) no cuenta: si contara, cada arranque vaciaba y volvía a poner los
    puntos de todas las filas sin saque, y quien leía entre medias veía la mitad.
    """
    saques: dict[str, list[tuple[float, str]]] = {}
    for jornada, kickoff in filas:
        momento = epoch_kickoff(kickoff)
        if momento is not None:
            saques.setdefault(jornada, []).append((momento, kickoff))
    ultimo: dict[str, str] = {}
    for jornada, lista in saques.items():
        primero = min(momento for momento, _ in lista)
        bloque = [item for item in lista if item[0] <= primero + DIAS_BLOQUE_JORNADA * 86400.0]
        ultimo[jornada] = max(bloque)[1]
    return ultimo


def reparar_historico(conn: sqlite3.Connection) -> dict[str, int]:
    """Limpia el histórico ya guardado. Idempotente.

    * Puntos apuntados antes de ser definitivos → se vacían; el evaluador los
      vuelve a poner cuando lo sean.
    * Previsión guardada después del saque → se recupera la última del registro
      diario anterior al saque; si no hay, se vacía (no cuenta en el error).
    """
    tablas = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    if "matchday_snapshots" not in tablas:
        return {"prematuras": 0, "previas_recuperadas": 0, "previas_anuladas": 0}
    filas = conn.execute(
        """select jornada_id, player_id, kickoff, stored_at, evaluated_at, actual_points, expected_points
           from matchday_snapshots"""
    ).fetchall()
    prematuras = recuperadas = anuladas = 0
    hay_log = "matchday_snapshot_log" in tablas
    ultimo = ultimo_saque_por_jornada((jornada, kickoff) for jornada, _pid, kickoff, *_resto in filas)
    for jornada, player_id, kickoff, stored_at, evaluated_at, actual, expected in filas:
        propio = kickoff
        if epoch_kickoff(kickoff) is None:
            kickoff = ultimo.get(jornada)
        if actual is not None and evaluacion_prematura(kickoff, evaluated_at):
            conn.execute(
                "update matchday_snapshots set actual_points = null, evaluated_at = null where jornada_id = ? and player_id = ?",
                (jornada, player_id),
            )
            prematuras += 1
        if expected is None or previa_valida(propio, stored_at):
            continue
        inicio = epoch_kickoff(propio)
        previa = None
        if hay_log and inicio is not None:
            previa = conn.execute(
                """select expected_points, ceiling_points, stored_at from matchday_snapshot_log
                   where jornada_id = ? and player_id = ? and stored_at < ? and expected_points is not null
                   order by stored_at desc limit 1""",
                (jornada, player_id, inicio),
            ).fetchone()
        if previa is not None:
            conn.execute(
                """update matchday_snapshots set expected_points = ?, ceiling_points = ?, stored_at = ?
                   where jornada_id = ? and player_id = ?""",
                (previa[0], previa[1], previa[2], jornada, player_id),
            )
            recuperadas += 1
        else:
            conn.execute(
                "update matchday_snapshots set expected_points = null, ceiling_points = null where jornada_id = ? and player_id = ?",
                (jornada, player_id),
            )
            anuladas += 1
    conn.commit()
    return {"prematuras": prematuras, "previas_recuperadas": recuperadas, "previas_anuladas": anuladas}

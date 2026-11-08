"""Jornada en juego: radiografía en vivo de tu once y del de cada rival.

Desde el primer saque de la jornada hasta que acaba el último partido, cada
mánager tiene puntos que ya son suyos (partidos jugados), puntos en el aire
(partidos en juego) y puntos esperados (partidos pendientes). Este módulo los
separa, proyecta el final de jornada, ordena la clasificación virtual y calcula
el dinero que cobrará cada uno al cerrar la jornada.

Fuentes, todas ya en el tablero (no descarga nada):

* puntos reales por jugador: las actas acumuladas (``player_history``);
* saque del próximo partido de cada jugador: ``trends`` (``fixture.kickoff``);
  si ya es de la jornada siguiente, el partido de esta ya se jugó;
* puntos esperados de lo que falta: ``jornada_ev`` del motor.

Límites que se dicen en el resultado y no se disimulan:

* La alineación que cada mánager registró no está publicada. El once de cada uno
  es el de mayor xP que permiten sus jugadores (el tuyo y el de los rivales
  igual), no el real.
* Un partido en juego no tiene acta hasta que termina: se cuenta como pendiente.
* Un jugador cuyo partido ya se jugó pero no tiene acta aún cuenta con su xP y
  se avisa en ``sin_acta``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from toolbox.analyzer import FORMATIONS, POSITIONS, Candidate, candidates_from_squad, index_trends
from toolbox.jornada_plan import _parse_iso

#: Dinero por punto tras cada jornada (regla oficial).
EUROS_POR_PUNTO = 100_000
#: Único abono fijo que el código conoce: el vídeo publicitario diario.
ABONO_JORNADA_EUR = 100_000
#: Un partido dura unos 105 min con el descanso; con añadido, se da por acabado a los 115.
MINUTOS_PARTIDO = 115
#: Hueco entre bloques de partidos que separa una jornada de la siguiente.
HUECO_ENTRE_JORNADAS = timedelta(hours=36)
#: Puntos desde los que un jugador "explota".
UMBRAL_EXPLOSION = 10.0

ESTADO_JUGADO = "jugado"
ESTADO_EN_JUEGO = "en_juego"
ESTADO_PENDIENTE = "pendiente"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _kickoff(row: dict[str, Any] | None) -> datetime | None:
    if not isinstance(row, dict):
        return None
    fixture = row.get("fixture") if isinstance(row.get("fixture"), dict) else {}
    moment = _parse_iso(fixture.get("kickoff"))
    if moment is None:
        calendar = row.get("own_calendar") if isinstance(row.get("own_calendar"), list) else []
        if calendar and isinstance(calendar[0], dict):
            moment = _parse_iso(calendar[0].get("kickoff"))
    return moment.astimezone(timezone.utc) if moment is not None else None


def _vista_en_juego(row: dict[str, Any]) -> dict[str, Any]:
    """El jugador tal como estaba en la jornada en juego.

    ``own_intel`` corre el xP y el rival de quien aún juega la jornada bloqueada
    a la siguiente (todas las pantallas hablan de la J13); el partido de esta
    jornada queda en ``own_en_juego``. Aquí se recupera para el bloque en vivo.
    """
    en_juego = row.get("own_en_juego") if isinstance(row, dict) else None
    if not isinstance(en_juego, dict):
        return row
    vista = dict(row)
    if isinstance(en_juego.get("expected_points"), (int, float)) and not isinstance(en_juego.get("expected_points"), bool):
        vista["own_expected_points"] = en_juego["expected_points"]
    fixture = row.get("fixture") if isinstance(row.get("fixture"), dict) else {}
    vista["fixture"] = {**fixture, "kickoff": en_juego.get("kickoff"), "opponent": en_juego.get("opponent")}
    calendario = row.get("own_calendar") if isinstance(row.get("own_calendar"), list) else []
    vista["own_calendar"] = [
        {"kickoff": en_juego.get("kickoff"), "opponent": en_juego.get("opponent"), "is_home": en_juego.get("is_home")},
        *calendario,
    ]
    return vista


def bloque_en_curso(trends_index: dict[str, dict[str, Any]], now: datetime) -> tuple[datetime | None, datetime | None]:
    """(primer saque, último saque) del bloque de partidos que aún no ha terminado.

    Parte del primer saque que no ha terminado (empezó hace menos de un partido
    o es futuro) y lo extiende mientras el hueco con el siguiente no pase de 36 h.
    """
    corte = now - timedelta(minutes=MINUTOS_PARTIDO)
    saques = sorted({k for k in (_kickoff(row) for row in trends_index.values()) if k is not None and k >= corte})
    if not saques:
        return None, None
    fin = saques[0]
    for moment in saques[1:]:
        if moment - fin > HUECO_ENTRE_JORNADAS:
            break
        fin = moment
    return saques[0], fin


def _estado(
    kick: datetime | None,
    fin_bloque: datetime | None,
    now: datetime,
    tiene_acta: bool,
) -> str:
    if tiene_acta:
        return ESTADO_JUGADO
    if kick is None or fin_bloque is None:
        return ESTADO_PENDIENTE
    if kick > fin_bloque:
        return ESTADO_JUGADO
    if kick <= now:
        return ESTADO_EN_JUEGO if now < kick + timedelta(minutes=MINUTOS_PARTIDO) else ESTADO_JUGADO
    return ESTADO_PENDIENTE


def _acta(actas: dict[str, dict[str, Any]], player_id: str | None, jornada: int) -> tuple[float, float] | None:
    """(puntos, minutos) del jugador en la jornada, si hay acta."""
    if not player_id:
        return None
    weeks = (actas.get(player_id) or {}).get("weeks")
    if not isinstance(weeks, dict):
        return None
    raw = weeks.get(str(jornada), weeks.get(jornada))
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    puntos = _num(raw[0])
    if puntos is None:
        return None
    minutos = _num(raw[1]) if len(raw) > 1 else None
    return puntos, minutos if minutos is not None else 0.0


def _mejor_once(candidatos: list[Candidate]) -> tuple[str | None, list[Candidate]]:
    """Formación y once de mayor xP con los jugadores elegibles. Vacío si no llegan a 11."""
    elegibles = [c for c in candidatos if c.eligible]
    mejor: tuple[float, str, list[Candidate]] | None = None
    for nombre, huecos in FORMATIONS.items():
        puestos: list[Candidate] = []
        for posicion in POSITIONS:
            pool = sorted((c for c in elegibles if c.position == posicion), key=lambda c: c.jornada_ev, reverse=True)
            puestos.extend(pool[: huecos[posicion]])
        if len(puestos) != sum(huecos.values()):
            continue
        total = sum(c.jornada_ev for c in puestos)
        if mejor is None or total > mejor[0]:
            mejor = (total, nombre, puestos)
    return (mejor[1], mejor[2]) if mejor else (None, [])


def _fila_jugador(
    candidato: Candidate,
    *,
    estado: str,
    acta: tuple[float, float] | None,
    kick: datetime | None,
) -> dict[str, Any]:
    puntos = acta[0] if acta else None
    minutos = acta[1] if acta else None
    sin_acta = estado == ESTADO_JUGADO and acta is None
    no_jugo = estado == ESTADO_JUGADO and acta is not None and (minutos or 0.0) <= 0.0
    return {
        "player_id": candidato.player_id,
        "nombre": candidato.nickname or candidato.name,
        "posicion": candidato.position,
        "club": candidato.club,
        "estado": estado,
        "puntos": puntos,
        "minutos": minutos,
        "xp": round(candidato.jornada_ev, 2),
        "saque": kick.isoformat() if kick else None,
        "sin_acta": sin_acta,
        "no_jugo": no_jugo,
        "rosco": estado == ESTADO_JUGADO and acta is not None and puntos is not None and puntos <= 0.0,
        "explosion": puntos is not None and puntos >= UMBRAL_EXPLOSION,
    }


def _radiografia_equipo(
    squad: dict[str, Any],
    indice: dict[str, dict[str, Any]],
    actas: dict[str, dict[str, Any]],
    jornada: int,
    fin_bloque: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    candidatos = candidates_from_squad(squad, indice)
    formacion, once = _mejor_once(candidatos)
    filas: list[dict[str, Any]] = []
    for candidato in once:
        acta = _acta(actas, candidato.player_id, jornada)
        kick = _kickoff(indice.get(candidato.player_id or ""))
        estado = _estado(kick, fin_bloque, now, acta is not None)
        filas.append(_fila_jugador(candidato, estado=estado, acta=acta, kick=kick))
    jugados = [f for f in filas if f["estado"] == ESTADO_JUGADO]
    en_juego = [f for f in filas if f["estado"] == ESTADO_EN_JUEGO]
    pendientes = [f for f in filas if f["estado"] == ESTADO_PENDIENTE]
    actuales = sum(f["puntos"] for f in jugados if f["puntos"] is not None)
    # Lo que aún no es firme: pendientes, en juego y jugados sin acta, con su xP.
    esperado = sum(f["xp"] for f in [*pendientes, *en_juego] + [f for f in jugados if f["sin_acta"]])
    proyectados = actuales + esperado
    pendientes_orden = sorted([*en_juego, *pendientes], key=lambda f: (f["saque"] or "", f["nombre"] or ""))
    cash = next((v for v in (_num(squad.get("cash_eur")), _num(squad.get("cash"))) if v is not None), None)
    return {
        "team_id": squad.get("team_id"),
        "manager": squad.get("manager_name"),
        "is_self": squad.get("is_self") is True,
        "rank_tabla": squad.get("rank") if isinstance(squad.get("rank"), int) else None,
        "puntos_tabla": squad.get("points") if isinstance(squad.get("points"), int) else None,
        "caja_eur": int(cash) if cash is not None else None,
        "formacion": formacion,
        "once_completo": len(once) == 11,
        "jugadores_jugados": len(jugados),
        "jugadores_en_juego": len(en_juego),
        "jugadores_pendientes": len(pendientes) + len(en_juego),
        "resumen_jugados": f"{len(jugados)}/{len(filas)} jugados, faltan {len(pendientes) + len(en_juego)}",
        "puntos_actuales": round(actuales, 1),
        "xp_pendiente": round(esperado, 2),
        "puntos_proyectados_final_jornada": round(proyectados, 1),
        "sin_acta": sum(1 for f in jugados if f["sin_acta"]),
        "saldo_negativo": cash is not None and cash < 0,
        "once": filas,
        "pendientes": pendientes_orden,
        "roscos": [f for f in jugados if f["rosco"]],
        "explosiones": [f for f in jugados if f["explosion"]],
    }


def _premio(puntos: float) -> int:
    """Dinero de la jornada: 100.000 € por punto (sin negativos) más el abono."""
    return int(round(max(0.0, puntos) * EUROS_POR_PUNTO)) + ABONO_JORNADA_EUR


def _texto_propio(propio: dict[str, Any], puesto: int, total: int, lider: dict[str, Any] | None) -> str:
    partes = [
        f"Jornada en juego: llevas {propio['puntos_actuales']:.0f} pts ({propio['resumen_jugados']}).",
        f"Proyección final {propio['puntos_proyectados_final_jornada']:.0f} pts: puesto {puesto} de {total} en la jornada.",
    ]
    if lider is not None and not lider.get("is_self"):
        dif = propio["puntos_proyectados_final_jornada"] - lider["puntos_proyectados_final_jornada"]
        partes.append(
            f"Frente al líder de la liga ({lider['manager']}) {'recortas' if dif > 0 else 'pierdes'} "
            f"{abs(dif):.0f} pts esta jornada."
        )
    partes.append(f"Cobras unos {propio['premio_jornada_eur'] / 1_000_000:.2f} M€ al cerrar la jornada.")
    return " ".join(partes)


def construir_jornada_en_juego(
    squads: dict[str, Any] | None,
    trends: dict[str, Any] | None,
    actas: dict[str, dict[str, Any]],
    *,
    now: datetime,
    jornada: int | None = None,
) -> dict[str, Any]:
    """Radiografía de la jornada en curso, o ``{"activa": False}`` si no hay ninguna."""
    inactiva = {"activa": False}
    if not isinstance(squads, dict) or not isinstance(trends, dict):
        return inactiva
    indice = {pid: _vista_en_juego(row) for pid, row in index_trends(trends).items()}
    inicio_bloque, fin_bloque = bloque_en_curso(indice, now)
    if inicio_bloque is None:
        return inactiva

    # La jornada está en curso si algún jugador ya la jugó (su próximo partido
    # está más allá del bloque) y aún queda algún partido por terminar en él.
    ya_jugaron = sum(
        1
        for row in indice.values()
        if (k := _kickoff(row)) is not None and fin_bloque is not None and k > fin_bloque
    )
    if ya_jugaron < 2:
        return inactiva
    if jornada is None:
        semanas = [int(w) for datos in actas.values() for w in (datos.get("weeks") or {}) if str(w).isdigit()]
        if not semanas:
            return inactiva
        jornada = max(semanas)

    equipos = [
        _radiografia_equipo(squad, indice, actas, jornada, fin_bloque, now)
        for squad in squads.get("squads") or []
        if isinstance(squad, dict) and not squad.get("error")
    ]
    if not equipos:
        return inactiva
    for equipo in equipos:
        equipo["premio_jornada_eur"] = _premio(equipo["puntos_proyectados_final_jornada"])
        equipo["premio_ya_firme_eur"] = int(round(max(0.0, equipo["puntos_actuales"]) * EUROS_POR_PUNTO))
        caja = equipo["caja_eur"]
        equipo["caja_proyectada_lunes_eur"] = caja + equipo["premio_jornada_eur"] if caja is not None else None

    orden = sorted(
        equipos,
        key=lambda e: (-e["puntos_proyectados_final_jornada"], -e["puntos_actuales"], e["manager"] or ""),
    )
    for puesto, equipo in enumerate(orden, start=1):
        equipo["puesto_jornada"] = puesto
    propio = next((e for e in equipos if e["is_self"]), None)

    # Tabla virtual: puntos de la tabla (cerrados hasta la jornada anterior) + proyección de ésta.
    for equipo in equipos:
        base = equipo["puntos_tabla"]
        equipo["puntos_tabla_proyectados"] = (
            round(base + equipo["puntos_proyectados_final_jornada"], 1) if base is not None else None
        )
    tabla = sorted(
        (e for e in equipos if e["puntos_tabla_proyectados"] is not None),
        key=lambda e: -e["puntos_tabla_proyectados"],
    )
    for puesto, equipo in enumerate(tabla, start=1):
        equipo["puesto_tabla_proyectado"] = puesto

    lider = min((e for e in equipos if e["rank_tabla"] is not None), key=lambda e: e["rank_tabla"], default=None)
    rivales_directos: list[dict[str, Any]] = []
    if propio is not None:
        mis_pts = propio["puntos_proyectados_final_jornada"]
        for equipo in equipos:
            if equipo["is_self"]:
                continue
            equipo["dif_jornada_vs_ti"] = round(mis_pts - equipo["puntos_proyectados_final_jornada"], 1)
            equipo["dif_tabla_vs_ti"] = (
                round(propio["puntos_tabla_proyectados"] - equipo["puntos_tabla_proyectados"], 1)
                if propio["puntos_tabla_proyectados"] is not None and equipo["puntos_tabla_proyectados"] is not None
                else None
            )
        if propio["rank_tabla"] is not None:
            rivales_directos = [
                e
                for e in equipos
                if not e["is_self"] and e["rank_tabla"] is not None and abs(e["rank_tabla"] - propio["rank_tabla"]) == 1
            ]
            rivales_directos.sort(key=lambda e: e["rank_tabla"])
        propio["recorte_vs_lider"] = (
            round(mis_pts - lider["puntos_proyectados_final_jornada"], 1) if lider is not None and not lider["is_self"] else 0.0
        )
        propio["recorte_tabla_vs_lider"] = (
            round(propio["puntos_tabla_proyectados"] - lider["puntos_tabla_proyectados"], 1)
            if lider is not None
            and not lider["is_self"]
            and propio["puntos_tabla_proyectados"] is not None
            and lider["puntos_tabla_proyectados"] is not None
            else 0.0
        )

    def _resumen(e: dict[str, Any]) -> dict[str, Any]:
        """Sin el detalle del once: para tablas y rivales."""
        return {k: v for k, v in e.items() if k not in {"once", "pendientes", "roscos", "explosiones"}}

    resultado: dict[str, Any] = {
        "activa": True,
        "jornada": jornada,
        "inicio": inicio_bloque.isoformat(),
        "ultimo_saque": fin_bloque.isoformat() if fin_bloque else None,
        "ahora": now.astimezone(timezone.utc).isoformat(),
        "euros_por_punto": EUROS_POR_PUNTO,
        "abono_jornada_eur": ABONO_JORNADA_EUR,
        "nota": (
            "Once de cada mánager = el de mayor xP que permiten sus jugadores; la alineación registrada no "
            "es pública. Un partido en juego cuenta como pendiente hasta que hay acta."
        ),
        "clasificacion_jornada": [_resumen(e) for e in orden],
        "clasificacion_tabla": [_resumen(e) for e in tabla],
        "rivales_directos": [_resumen(e) for e in rivales_directos],
        "lider": _resumen(lider) if lider else None,
        "propio": None,
        "liquidez_entrante_eur": 0,
    }
    if propio is not None:
        resultado["propio"] = propio
        resultado["liquidez_entrante_eur"] = propio["premio_jornada_eur"]
        resultado["resumen"] = _texto_propio(propio, propio["puesto_jornada"], len(orden), lider)
    return resultado

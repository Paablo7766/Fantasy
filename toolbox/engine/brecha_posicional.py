"""Dónde se pierden los puntos frente al mejor rival: brecha por puesto.

Suma, por puesto y en las últimas jornadas jugadas, los puntos oficiales de
los mejores jugadores actuales de cada plantilla (un 4-4-2 de referencia) y
compara la nuestra con la del rival más fuerte de la ventana. El puesto donde
más puntos faltan recibe un pequeño extra de xP en el optimizador de fichajes
(solo desempata entre fichajes parecidos) y se enseña en el diagnóstico.
"""

from __future__ import annotations

from typing import Any

PUESTOS = ("POR", "DEF", "MC", "DEL")
#: Once de referencia (4-4-2) para sumar «lo que da cada puesto».
TITULARES_REFERENCIA = {"POR": 1, "DEF": 4, "MC": 4, "DEL": 2}
VENTANA_JORNADAS = 5
#: Extra máximo de xP por jornada para un fichaje en el puesto con más brecha. Los demás,
#: en proporción. Sirve de desempate: un fichaje claramente peor no lo supera.
BONUS_MAX_XP = 0.30
#: Por debajo de esta brecha (puntos) no se corrige: es ruido.
BRECHA_MIN = 5.0


def _puntos_por_jornada(players: list[dict[str, Any]], jornadas: list[str]) -> dict[str, float]:
    total = dict.fromkeys(PUESTOS, 0.0)
    for jornada in jornadas:
        for puesto in PUESTOS:
            valores = sorted(
                (
                    float(p["week_points_by_round"][jornada])
                    for p in players
                    if isinstance(p, dict)
                    and p.get("position") == puesto
                    and isinstance(p.get("week_points_by_round"), dict)
                    and isinstance(p["week_points_by_round"].get(jornada), (int, float))
                    and not isinstance(p["week_points_by_round"].get(jornada), bool)
                ),
                reverse=True,
            )
            total[puesto] += sum(valores[: TITULARES_REFERENCIA[puesto]])
    return total


def _ultimas_jornadas(squads: list[dict[str, Any]], n: int) -> list[str]:
    vistas: set[int] = set()
    for squad in squads:
        for player in squad.get("players") or []:
            rounds = player.get("week_points_by_round") if isinstance(player, dict) else None
            if isinstance(rounds, dict):
                vistas.update(int(k) for k in rounds if str(k).isdigit())
    return [str(j) for j in sorted(vistas)[-n:]]


def brecha_posicional(squads: list[dict[str, Any]] | None, *, ventana: int = VENTANA_JORNADAS) -> dict[str, Any] | None:
    """Brecha por puesto frente al rival con más puntos en la ventana. ``None`` sin datos."""
    plantillas = [s for s in squads or [] if isinstance(s, dict) and isinstance(s.get("players"), list)]
    propia = next((s for s in plantillas if s.get("is_self") is True), None)
    rivales = [s for s in plantillas if s is not propia]
    if propia is None or not rivales:
        return None
    jornadas = _ultimas_jornadas(plantillas, ventana)
    if not jornadas:
        return None
    mios = _puntos_por_jornada(propia["players"], jornadas)
    lider: dict[str, Any] | None = None
    lider_puntos: dict[str, float] = {}
    # El rival de referencia es el primero de la clasificación (más puntos de liga); sin ese
    # dato, el que más suma en la ventana.
    def _fuerza(rival: dict[str, Any], puntos: dict[str, float]) -> tuple[float, float]:
        liga = rival.get("points")
        liga = float(liga) if isinstance(liga, (int, float)) and not isinstance(liga, bool) else -1.0
        return liga, sum(puntos.values())

    for rival in rivales:
        puntos = _puntos_por_jornada(rival["players"], jornadas)
        if lider is None or _fuerza(rival, puntos) > _fuerza(lider, lider_puntos):
            lider, lider_puntos = rival, puntos
    if lider is None or sum(lider_puntos.values()) <= 0:
        return None
    diferencia = {p: round(mios[p] - lider_puntos[p], 1) for p in PUESTOS}
    deficits = {p: -d for p, d in diferencia.items() if -d >= BRECHA_MIN}
    mayor = max(deficits.values()) if deficits else 0.0
    bonus = {p: round(BONUS_MAX_XP * deficits[p] / mayor, 3) for p in deficits} if mayor > 0 else {}
    nombre = lider.get("manager_name") or lider.get("fantasy_team_name") or "el líder"
    peor = sorted(deficits, key=lambda p: -deficits[p])
    if peor:
        texto = (
            f"Frente a {nombre} ({sum(lider_puntos.values()):.0f} vs {sum(mios.values()):.0f} pts en las últimas "
            f"{len(jornadas)} jornadas) pierdes más en "
            + " y ".join(f"{p} ({diferencia[p]:+.0f})" for p in peor[:2])
            + ": ahí cada millón invertido recorta más."
        )
    else:
        texto = f"Ningún puesto está por debajo de {nombre} en las últimas {len(jornadas)} jornadas."
    return {
        "rival": nombre,
        "jornadas": [int(j) for j in jornadas],
        "mios": {p: round(v, 1) for p, v in mios.items()},
        "rival_puntos": {p: round(v, 1) for p, v in lider_puntos.items()},
        "diferencia": diferencia,
        "bonus_xp": bonus,
        "texto": texto,
    }

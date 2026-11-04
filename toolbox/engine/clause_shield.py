"""Blindaje quirúrgico de cláusulas: teoría de juegos en vez de múltiplos fijos.

Un clausulazo en LaLiga Fantasy se paga con saldo positivo, sin crédito. Por
eso la amenaza real sobre un jugador nuestro no es "cuántos rivales tienen
dinero" sino, para cada rival, ``min(lo que puede pagar, lo que le compensa
pagar)``. La cláusula óptima es la que supera a la mayor de esas amenazas.

Todo es puro: recibe diccionarios y devuelve filas con la forma del radar
anti-robo que ya pinta el frontend (``estado``, ``badge``, ``consejo``...).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_MADRID = ZoneInfo("Europe/Madrid")

#: Lo que se recupera al vender un suplente a LaLiga: el 95 % de su valor.
FACTOR_VENTA_24H = 0.95
#: Euros que está dispuesto a pagar un rival por cada punto de xP que gana.
URGENCIA_HUECO = 3_500_000
URGENCIA_JUSTO = 2_000_000
URGENCIA_CUBIERTO = 1_200_000
#: Margen por encima de la mayor amenaza para que ya no compense pagar.
MARGEN_OPTIMA = 200_000
#: Con una cláusula así de alta sobre el valor, si el jugador apenas pesa, es un cebo.
MULTIPLO_CEBO = 1.30
PERDIDA_IRRELEVANTE = 1.0
#: Con un sustituto comprable, perder al jugador cuesta como mucho esto en xP.
TOLERANCIA_SUSTITUTO_XP = 0.3
#: De lunes a miércoles aún se puede reponer con lo cobrado.
DIAS_REPOSICION = (0, 1, 2)
#: Sin saque conocido, un candado a 3 días o más se da por activo.
VENTANA_SIN_SAQUE_DIAS = 3.0
#: 4-3-3: titulares por puesto cuando no se conoce el once del rival.
TITULARES = {"POR": 1, "DEF": 4, "MC": 3, "DEL": 3}

TEXTO_CANDADO = "🔒 CANDADO ACTIVO (No gastar caja hasta la próxima semana)"
TEXTO_FUERA = "🟢 FUERA DE ALCANCE REAL (Ningún rival tiene saldo + incentivo para pagarla)"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _apertura(raw: Any, ahora: datetime) -> datetime | None:
    """Momento en que se puede pagar la cláusula. ``ahora`` si ya está abierta."""
    if isinstance(raw, dict):
        if raw.get("is_locked") is False:
            return ahora
        epoch = _num(raw.get("epoch_ms"))
        if epoch is not None:
            return datetime.fromtimestamp(epoch / 1000.0, tz=timezone.utc)
        return _utc(raw.get("expires_at") or raw.get("clausulaAbre"))
    return _utc(raw)


def _m(euros: float) -> str:
    return f"{euros / 1_000_000:.1f}".replace(".", ",")


def _pct(value: Any) -> float | None:
    number = _num(value)
    if number is not None:
        return number
    if isinstance(value, str):
        try:
            return float(value.strip().replace("%", "").replace(",", ".").lstrip("+"))
        except ValueError:
            return None
    return None


def _sanos_por_puesto(plantilla: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    puestos: dict[str, list[dict[str, Any]]] = {puesto: [] for puesto in TITULARES}
    for fila in plantilla:
        if not isinstance(fila, dict) or fila.get("sano") is False:
            continue
        puesto = fila.get("position")
        if puesto in puestos:
            puestos[puesto].append(fila)
    for filas in puestos.values():
        filas.sort(key=lambda fila: -(_num(fila.get("jornada")) or 0.0))
    return puestos


def prescindibles_valor(plantilla: list[dict[str, Any]]) -> float:
    """Valor de los sanos fuera del once aproximado (los mejores por puesto se quedan)."""
    total = 0.0
    for puesto, filas in _sanos_por_puesto(plantilla).items():
        for fila in filas[TITULARES[puesto]:]:
            total += _num(fila.get("valor")) or 0.0
    return total


def liquidez_rival(rival: dict[str, Any], horas_al_saque: float | None) -> dict[str, int]:
    """Techos de ataque: caja hoy y caja mañana si vende los suplentes prescindibles.

    Sin crédito: la cláusula exige el 100 % en saldo positivo. Si faltan menos
    de 24 h para el primer saque, mañana no cuenta y el techo es la caja de hoy.
    """
    caja = _num(rival.get("saldo"))
    if caja is None:
        caja = _num(rival.get("calculated_cash"))
    caja = caja or 0.0
    inmediata = max(0.0, caja)
    en_24h = max(0.0, caja + FACTOR_VENTA_24H * prescindibles_valor(rival.get("plantilla") or []))
    if horas_al_saque is not None and horas_al_saque < 24.0:
        en_24h = inmediata
    return {"inmediata": int(round(inmediata)), "en_24h": int(round(en_24h))}


def necesidad_rival(rival: dict[str, Any], puesto: str, xp_jugador: float) -> tuple[str, float]:
    """(nivel, ``delta_xp``): lo que mejora mi jugador al peor titular del rival.

    ``hueco`` si el rival tiene menos sanos que plazas en ese puesto (el delta
    es todo el xP), ``justo`` si tiene los justos sin banquillo y ``cubierto``
    si le sobra alguien.
    """
    sanos = _sanos_por_puesto(rival.get("plantilla") or []).get(puesto, [])
    titulares = TITULARES.get(puesto, 0)
    if titulares == 0 or len(sanos) < titulares:
        return "hueco", max(0.0, xp_jugador)
    peor = _num(sanos[titulares - 1].get("jornada")) or 0.0
    return ("justo" if len(sanos) == titulares else "cubierto"), max(0.0, xp_jugador - peor)


def disposicion_a_pagar(valor: float, subida_7d: float, nivel: str, delta_xp: float) -> int:
    """Precio máximo racional: valor + subida esperada + urgencia por punto de mejora."""
    urgencia = {"hueco": URGENCIA_HUECO, "justo": URGENCIA_JUSTO}.get(nivel, URGENCIA_CUBIERTO)
    return int(round(valor + subida_7d + urgencia * max(0.0, delta_xp)))


def amenazas_jugador(
    jugador: dict[str, Any], rivales: list[dict[str, Any]], horas_al_saque: float | None
) -> list[dict[str, Any]]:
    """Amenaza de cada rival sobre un jugador, de mayor a menor."""
    valor = _num(jugador.get("valor_mercado")) or 0.0
    pct = _pct(jugador.get("prevision_7d_pct"))
    subida = valor * pct / 100.0 if pct is not None else 0.0
    xp = _num(jugador.get("jornada")) or 0.0
    puesto = str(jugador.get("position"))
    filas = []
    for rival in rivales:
        if not isinstance(rival, dict):
            continue
        liquidez = liquidez_rival(rival, horas_al_saque)
        nivel, delta = necesidad_rival(rival, puesto, xp)
        wtp = disposicion_a_pagar(valor, subida, nivel, delta)
        filas.append(
            {
                "manager": rival.get("manager") or rival.get("team_id") or "Rival",
                "nivel": nivel,
                "delta_xp": round(delta, 2),
                "liquidez_inmediata": liquidez["inmediata"],
                "liquidez_24h": liquidez["en_24h"],
                "wtp": wtp,
                "amenaza": min(liquidez["en_24h"], wtp),
            }
        )
    filas.sort(key=lambda fila: -fila["amenaza"])
    return filas


def cebo_o_blindaje(
    *, clausula: int, valor: int, amenaza_max: int, perdida_xp: float, ratio_eur_xp: float
) -> dict[str, Any]:
    """Decide entre blindar, dejarlo como cebo o asumir el riesgo.

    El daño neto de perderlo es ``pérdida × ratio − prima`` (la prima que cobras
    por encima del valor compensa). Si blindar cuesta más que eso, no se sube.
    """
    optima = int(round(round(amenaza_max / 1_000_000 + MARGEN_OPTIMA / 1_000_000, 1) * 1_000_000))
    coste = max(0, (optima - clausula) // 2)
    prima = clausula - valor
    dano = perdida_xp * ratio_eur_xp - prima
    irrelevante = perdida_xp < PERDIDA_IRRELEVANTE and clausula >= MULTIPLO_CEBO * valor
    if irrelevante or coste > dano:
        codigo = "CEBO" if prima > 0 else "ASUMIR"
    else:
        codigo = "BLINDAR"
    return {
        "codigo": codigo,
        "clausula_optima": optima,
        "coste_subida": coste,
        "prima_robo": prima,
        "dano_neto": int(round(dano)),
    }


def _perdida_efectiva(
    jugador: dict[str, Any], perdida_xp: float, clausula: int, ahora: datetime, alternativas: list[dict[str, Any]] | None
) -> float:
    """Descuenta el recambio comprable con lo cobrado, de lunes a miércoles."""
    if perdida_xp <= 0 or not alternativas or ahora.astimezone(_MADRID).weekday() not in DIAS_REPOSICION:
        return perdida_xp
    xp = _num(jugador.get("jornada"))
    if xp is None:
        return perdida_xp
    for alt in alternativas:
        if alt.get("position") != jugador.get("position") or alt.get("player_id") == jugador.get("player_id"):
            continue
        coste, rinde = _num(alt.get("coste")), _num(alt.get("xp"))
        if coste is not None and rinde is not None and coste <= clausula and rinde >= xp - TOLERANCIA_SUSTITUTO_XP:
            return min(perdida_xp, TOLERANCIA_SUSTITUTO_XP)
    return perdida_xp


def blindaje_quirurgico(
    plantilla: list[dict[str, Any]],
    rivales: list[dict[str, Any]],
    *,
    ahora: datetime,
    primer_saque: datetime | str | None,
    alternativas: list[dict[str, Any]] | None = None,
    ratio_eur_xp: float = 2_000_000,
) -> list[dict[str, Any]]:
    """Veredicto por jugador nuestro: candado, fuera de alcance, cebo, asumir o blindar.

    ``plantilla``: ``player_id``, ``nombre``, ``position``, ``clausula``,
    ``valor_mercado``, ``prevision_7d_pct``, ``clausulaAbre``, ``jornada`` (xP),
    ``tu_once_pierde_sin_el`` (xP) y ``blindado``.
    ``rivales``: ``saldo`` (caja sin crédito), ``manager`` y ``plantilla`` con
    ``position``, ``sano``, ``jornada`` y ``valor``.
    """
    ahora = ahora if ahora.tzinfo else ahora.replace(tzinfo=timezone.utc)
    saque = _utc(primer_saque)
    horas = (saque - ahora).total_seconds() / 3600.0 if saque else None
    filas: list[dict[str, Any]] = []
    for jugador in plantilla:
        if not isinstance(jugador, dict) or jugador.get("blindado") is True:
            continue
        pid = jugador.get("player_id")
        clausula = _num(jugador.get("clausula"))
        valor = _num(jugador.get("valor_mercado"))
        if not isinstance(pid, str) or not clausula or not valor or clausula <= 0 or valor <= 0:
            continue
        clausula_i, valor_i = int(clausula), int(valor)
        abre = _apertura(jugador.get("clausulaAbre"), ahora)
        if abre is None:
            continue
        dias = (abre - ahora).total_seconds() / 86400.0
        candado = (abre > saque) if saque else (dias >= VENTANA_SIN_SAQUE_DIAS)
        base = {
            "player_id": pid,
            "nombre": str(jugador.get("nombre") or pid),
            "posicion": jugador.get("position"),
            "clausula": clausula_i,
            "valor_mercado": valor_i,
            "clausula_abierta": dias <= 0,
            "dias_para_abrir": round(dias, 2),
            "prevision_7d_pct": _pct(jugador.get("prevision_7d_pct")),
            "beneficio_neto": max(0, clausula_i - valor_i),
            "rivales_con_caja": 0,
        }
        if candado:
            filas.append({**base, "estado": "CANDADO", "badge": "gris", "consejo": TEXTO_CANDADO})
            continue
        amenazas = amenazas_jugador(jugador, rivales, horas)
        amenaza_max = amenazas[0]["amenaza"] if amenazas else 0
        base.update(
            rivales_con_caja=sum(1 for a in amenazas if a["amenaza"] >= clausula_i),
            amenaza_max=amenaza_max,
            rival_amenaza=amenazas[0]["manager"] if amenazas else None,
            amenazas=amenazas[:3],
        )
        if amenaza_max < clausula_i:
            filas.append({**base, "estado": "FUERA_DE_ALCANCE", "badge": "verde", "consejo": TEXTO_FUERA})
            continue
        perdida = _perdida_efectiva(
            jugador, _num(jugador.get("tu_once_pierde_sin_el")) or 0.0, clausula_i, ahora, alternativas
        )
        v = cebo_o_blindaje(
            clausula=clausula_i, valor=valor_i, amenaza_max=amenaza_max, perdida_xp=perdida, ratio_eur_xp=ratio_eur_xp
        )
        extra = {
            "clausula_optima": v["clausula_optima"],
            "coste_subida": v["coste_subida"],
            "prima_robo": v["prima_robo"],
            "perdida_del_once_sin_el": round(perdida, 2),
        }
        if v["codigo"] == "BLINDAR":
            consejo = f"🛡️ BLINDAR A {_m(v['clausula_optima'])}M (Coste: {_m(v['coste_subida'])}M)"
            estado, badge = "BLINDAR", "rojo"
        elif v["codigo"] == "CEBO":
            consejo = (
                f"🪤 CEBO RENTABLE: No la subas. Si pagan {_m(clausula_i)}M te regalan "
                f"+{_m(v['prima_robo'])}M sobre su valor"
            )
            estado, badge = "CEBO", "verde"
        else:
            consejo = (
                f"🎲 ASUMIR RIESGO: blindarlo cuesta {_m(v['coste_subida'])}M "
                "y perderlo duele menos que eso"
            )
            estado, badge = "ASUMIR", "gris"
        filas.append({**base, **extra, "estado": estado, "badge": badge, "consejo": consejo})
    orden = {"BLINDAR": 0, "ASUMIR": 1, "CEBO": 2, "FUERA_DE_ALCANCE": 3, "CANDADO": 4}
    filas.sort(key=lambda f: (orden[f["estado"]], -(f.get("amenaza_max") or 0), f["nombre"]))
    return filas

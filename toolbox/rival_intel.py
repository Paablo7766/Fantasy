"""Auditoría forense de la caja rival: conciliación contable con cota superior.

El tablón público no notifica dos fugas de capital: subir una cláusula y los
abonos que solo aparecen como texto. Este módulo reconstruye la tesorería de
cada equipo con lo que sí es observable (historial de la liga, plantillas de
hoy y cláusulas) y con una regla explícita de **Caja Teórica Máxima**.

Principio de cota superior (``Upper Bound``)
-------------------------------------------
Todo lo que no se puede fechar con certeza se resuelve a favor del rival:
se le abonan **todos** los anuncios diarios desde el inicio de la liga, se
ignora cualquier ingreso dudoso (no se inventa) y, cuando el coste de una
subida de cláusula admite varias lecturas, se aplica la más barata. El
resultado nunca es una caja "esperada": es el máximo que el rival podría
tener. Si nuestra puja gana a esa cota, gana seguro.

Contabilidad
------------
    caja = presupuesto_inicial
         + primas y premios
         + ventas (incluye el cobro de una cláusula)
         - compras (mercado y cláusulas pagadas)
         + anuncios diarios
         - subidas de cláusula no publicadas

Las subidas de cláusula se detectan por dos vías que **no se solapan**:

1. Retroactiva: para cada jugador que hoy sigue en la plantilla se estima su
   cláusula base y se cobra el incremento. Es la vía completa, pero no puede
   fechar el gasto.
2. Diaria (``calculate_daily_diff``): compara la cláusula de ayer con la de hoy
   y anota el coste. Se persiste en ``hidden_expenses_log.json`` para que el
   gasto no se evapore cuando el jugador se venda y desaparezca de la
   plantilla (el "agujero fantasma"). Solo se aplica a jugadores que **ya no
   están** en la plantilla: si sigue, la vía retroactiva ya lo cuenta.

Un asiento manual (``ledger_adjustments.json``) ancla la caja a un valor
conocido en una fecha. A partir del ancla solo cuentan las variaciones
posteriores y el gasto oculto fechado por el motor diario; la estimación
retroactiva (que no tiene fecha) queda fuera para no contar dos veces lo que
el asiento ya recoge.

Termómetro de control
---------------------
La cota se contrasta con el saldo que publica la API (``reconciliation``). Si
la cota se queda corta, el sobrante sin explicar se publica en
``arbitrage_eur`` y se avisa: no se infla la cifra para taparlo. Si la cota
sobra, ``tight_ceiling_eur`` la aprieta al saldo observado más el margen
contable (ruido + anuncios devengados desde la foto) y ``temperature`` mide la
concordancia en ``(0, 1]``. ``posterior_sigma_eur`` es la ``σ_cash`` de la
barrera bayesiana que usa la puja para descontar la incertidumbre contable.

Configuración
-------------
``LEAGUE_START_DATE``, ``CLAUSE_INCREASE_MULTIPLIER``,
``STARTING_CLAUSE_MULTIPLIER``, ``CASH_THERMOMETER_TAU``,
``CASH_ARBITRAGE_BAND`` y ``CASH_UNCERTAINTY_FLOOR_EUR`` se leen del entorno
y, si la variable no está, del ``.env`` del proyecto. Una errata cae al
fallback: una configuración inválida nunca rompe la cota.

El módulo no imprime, no sale a la red y no inventa cifras: sin dato, el campo
queda ausente y la confianza del equipo baja.
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from toolbox import project_root
from toolbox.cache import cache_root
from toolbox.normalize import SCHEMA_VERSION

_MADRID = ZoneInfo("Europe/Madrid")

# --- Configuración financiera (entorno + .env) ------------------------------
# Los tres parámetros que la liga puede cambiar sin tocar código se leen del
# entorno y, si la variable no está, del ``.env`` del proyecto. El ``.env`` se
# carga tarde (lo hace ``TokenManager``), así que aquí se resuelve también
# desde el fichero: el resultado no depende del orden de importación.

ENV_CLAUSE_INCREASE_MULTIPLIER = "CLAUSE_INCREASE_MULTIPLIER"
ENV_STARTING_CLAUSE_MULTIPLIER = "STARTING_CLAUSE_MULTIPLIER"
ENV_LEAGUE_START_DATE = "LEAGUE_START_DATE"

#: Fallback de la fracción del incremento que cuesta subir una cláusula.
#:
#: El reglamento de la app muestra 1:2 (0,5). Se usa 0,20 porque el objetivo es
#: una cota superior de la caja: cobrar la subida más barata posible deja al
#: rival con más dinero del que probablemente tiene.
DEFAULT_CLAUSE_INCREASE_MULTIPLIER = 0.20

#: Fallback de la cláusula que el juego asigna a un jugador del reparto inicial.
DEFAULT_STARTING_CLAUSE_MULTIPLIER = 1.5

#: Fallback del primer día de liga (``YYYY-MM-DD``). Base del devengo de anuncios.
DEFAULT_LEAGUE_START_DATE = "2026-08-01"

# --- Termómetro de control (calibración de la cota) -------------------------

ENV_CASH_THERMOMETER_TAU = "CASH_THERMOMETER_TAU"
ENV_CASH_ARBITRAGE_BAND = "CASH_ARBITRAGE_BAND"
ENV_CASH_UNCERTAINTY_FLOOR_EUR = "CASH_UNCERTAINTY_FLOOR_EUR"

#: Hueco relativo con el que la temperatura cae a ``1/e``. Más alto = más
#: tolerante con las discrepancias entre la cota y la caja publicada.
DEFAULT_CASH_THERMOMETER_TAU = 0.10

#: Hueco relativo que se considera ruido de medición y no error de los libros.
DEFAULT_CASH_ARBITRAGE_BAND = 0.02

#: Suelo (€) de la incertidumbre que alimenta la barrera bayesiana de caja.
DEFAULT_CASH_UNCERTAINTY_FLOOR_EUR = 150_000


def _env_file_values() -> dict[str, str]:
    """Pares ``CLAVE=valor`` del ``.env`` del proyecto. Sin caché ni efectos."""
    values: dict[str, str] = {}
    try:
        path = project_root() / ".env"
        if not path.is_file():
            return values
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, raw = stripped.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            if key:
                values[key] = raw.strip().strip('"').strip("'")
    except (OSError, UnicodeDecodeError):
        return {}
    return values


def _env_text(name: str) -> str | None:
    """Valor de ``name``: primero el entorno, después el ``.env`` del proyecto."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    return _env_file_values().get(name, "").strip() or None


def _env_number(name: str, default: float) -> float:
    """Número positivo de ``name``; acepta ``0,20`` y ``0.20``. Si no vale, el fallback."""
    raw = _env_text(name)
    if raw is None:
        return default
    try:
        value = float(raw.replace("%", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def _env_day(name: str, default: str) -> str:
    """``YYYY-MM-DD`` válido de ``name``. Una errata no mueve el devengo."""
    raw = _env_text(name)
    if raw is None:
        return default
    try:
        return date.fromisoformat(raw.strip()[:10]).isoformat()
    except ValueError:
        return default


def configured_clause_increase_multiplier() -> float:
    """``CLAUSE_INCREASE_MULTIPLIER`` del entorno/``.env`` o ``0.20``.

    Fuera de ``(0, 1]`` no es una fracción del incremento: manda el fallback,
    porque una errata de configuración no debe romper la cota.
    """
    value = _env_number(ENV_CLAUSE_INCREASE_MULTIPLIER, DEFAULT_CLAUSE_INCREASE_MULTIPLIER)
    return value if value <= 1 else DEFAULT_CLAUSE_INCREASE_MULTIPLIER


def configured_starting_clause_multiplier() -> float:
    """``STARTING_CLAUSE_MULTIPLIER`` del entorno/``.env`` o ``1.5``."""
    return _env_number(ENV_STARTING_CLAUSE_MULTIPLIER, DEFAULT_STARTING_CLAUSE_MULTIPLIER)


def configured_league_start_date() -> str:
    """``LEAGUE_START_DATE`` del entorno/``.env`` o ``2026-08-01``."""
    return _env_day(ENV_LEAGUE_START_DATE, DEFAULT_LEAGUE_START_DATE)


def configured_thermometer_tau() -> float:
    """``CASH_THERMOMETER_TAU`` del entorno/``.env`` o ``0.10``."""
    return _env_number(ENV_CASH_THERMOMETER_TAU, DEFAULT_CASH_THERMOMETER_TAU)


def configured_arbitrage_band() -> float:
    """``CASH_ARBITRAGE_BAND`` del entorno/``.env`` o ``0.02``. Debe ser < 1."""
    value = _env_number(ENV_CASH_ARBITRAGE_BAND, DEFAULT_CASH_ARBITRAGE_BAND)
    return value if value < 1 else DEFAULT_CASH_ARBITRAGE_BAND


def configured_uncertainty_floor_eur() -> int:
    """``CASH_UNCERTAINTY_FLOOR_EUR`` del entorno/``.env`` o ``150.000``."""
    raw = _env_number(ENV_CASH_UNCERTAINTY_FLOOR_EUR, DEFAULT_CASH_UNCERTAINTY_FLOOR_EUR)
    return int(round(raw))


#: Presupuesto con el que arranca cada equipo al crearse la liga.
INITIAL_BUDGET = 100_000_000

#: Cláusula que el juego asigna por defecto a un jugador del reparto inicial.
STARTING_CLAUSE_MULTIPLIER = configured_starting_clause_multiplier()

#: Fracción del incremento que cuesta subir una cláusula (``.env``, 0,20 por defecto).
CLAUSE_INCREASE_MULTIPLIER = configured_clause_increase_multiplier()

#: Dinero que inyecta el juego por el vídeo publicitario diario.
DAILY_AD_REVENUE = 100_000

#: Primer día de liga (``YYYY-MM-DD``). Base del cálculo de anuncios.
LEAGUE_START_DATE = configured_league_start_date()

#: Termómetro de control leído al importar; el motor lo vuelve a leer al crearse.
CASH_THERMOMETER_TAU = configured_thermometer_tau()
CASH_ARBITRAGE_BAND = configured_arbitrage_band()
CASH_UNCERTAINTY_FLOOR_EUR = configured_uncertainty_floor_eur()

COMMAND = "rival-intel"

ADJUSTMENTS_FILENAME = "ledger_adjustments.json"
HIDDEN_EXPENSES_FILENAME = "hidden_expenses_log.json"
CLAUSE_SNAPSHOTS_FILENAME = "clause_snapshot_history.json"

#: Días de plantillas de cláusulas que se conservan para el "diff".
CLAUSE_SNAPSHOT_KEEP_DAYS = 45

#: Estados que mueven dinero en el tablón de actividad oficial.
_ACTIVITY_KIND = {
    1: "clause",
    6: "premium",
    12: "premium",
    20: "premium",
    21: "premium",
    22: "premium",
    23: "premium",
    24: "premium",
    31: "buy",
    33: "sell",
}

#: Jornadas en las que un equipo **no** puntuó. No mueven dinero: son la
#: prueba documental de un estado de caja. El tipo 8 (saldo negativo) es el
#: único que habla de dinero, y en negativo: si un equipo se quedó sin puntos
#: por saldo, su caja pudo estar bajo cero y no hay suelo de publicidad.
_NO_SCORE_KIND = {
    7: "alineacion_incompleta",
    8: "saldo_negativo",
    32: "alineacion_incorrecta",
}

#: Motivo de ``_NO_SCORE_KIND`` que invalida el suelo de publicidad por caja.
NEGATIVE_BALANCE_REASON = "saldo_negativo"

#: Filas del tablón que no mueven dinero pero fechan o prueban un estado.
#: El alta (``9``) marca el nacimiento de la liga o del equipo y por tanto el
#: primer día en que pudo cobrar publicidad: los anuncios no existen antes.
_MARKER_KIND = {
    9: "join",
    7: "no_score",
    8: "no_score",
    32: "no_score",
}

_KIND_ALIASES = {
    "initial": "initial",
    "budget": "initial",
    "presupuesto": "initial",
    "presupuestoinicial": "initial",
    "premium": "premium",
    "prima": "premium",
    "premio": "premium",
    "prize": "premium",
    "reward": "premium",
    "bonus": "premium",
    "buy": "buy",
    "compra": "buy",
    "purchase": "buy",
    "bid": "buy",
    "puja": "buy",
    "clause": "clause",
    "clausula": "clause",
    "clausulazo": "clause",
    "buyout": "clause",
    "sell": "sell",
    "venta": "sell",
    "sale": "sell",
}

#: Etiqueta de origen del jugador que pide la auditoría forense.
FICHADO = "FICHADO"
REPARTO = "REPARTO"

#: Cantidades que el tablón solo publica como prosa.
_REWARD_WORDS = re.compile(
    r"recibid|abonad|ingresad|acreditad|cobrad|premi|prima|bonus|recompensa|"
    r"received|credited|earned|prize|reward",
    re.IGNORECASE,
)

_NUMBER = re.compile(
    r"(?<![\d.,])"
    r"(?:\d{1,3}(?:[.\u00a0 ]\d{3})+(?:,\d{1,2})?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|\d+(?:[.,]\d+)?)"
    r"(?!\d)"
)

#: Campos ocultos del JSON que guardan la cláusula original del reparto.
_CLAUSE_BASE_KEYS = frozenset(
    {
        "buyprice",
        "initialclause",
        "clausebase",
        "clausulabase",
        "clausulainicial",
        "originalclause",
        "baseclause",
        "purchaseprice",
        "pricepaid",
        "boughtprice",
        "signingprice",
        "preciocompra",
    }
)

_MONEY_KINDS = frozenset({"premium", "sell", "buy", "clause"})

_TEXT_KEYS = (
    "label",
    "description",
    "message",
    "title",
    "text",
    "body",
    "detail",
    "content",
    "news",
    "comment",
    "concept",
    "reason",
)
_TIME_KEYS = ("createdAt", "created_at", "date", "at", "timestamp", "time", "publishedAt")
_PLAYER_KEYS = ("playerMasterId", "player_id", "playerId", "playerMasterID")
_TEAM_KEYS = ("team_id", "teamId", "fantasyTeamId", "user1Id", "managerId", "manager_id")
_MANAGER_KEYS = ("manager_id", "managerId", "user1Id")
_COUNTERPARTY_KEYS = ("counterparty_manager_id", "user2Id", "user2_id")

__all__ = [
    "CLAUSE_INCREASE_MULTIPLIER",
    "CASH_ARBITRAGE_BAND",
    "CASH_THERMOMETER_TAU",
    "CASH_UNCERTAINTY_FLOOR_EUR",
    "DAILY_AD_REVENUE",
    "DEFAULT_CASH_ARBITRAGE_BAND",
    "DEFAULT_CASH_THERMOMETER_TAU",
    "DEFAULT_CASH_UNCERTAINTY_FLOOR_EUR",
    "DEFAULT_CLAUSE_INCREASE_MULTIPLIER",
    "DEFAULT_LEAGUE_START_DATE",
    "DEFAULT_STARTING_CLAUSE_MULTIPLIER",
    "INITIAL_BUDGET",
    "LEAGUE_START_DATE",
    "STARTING_CLAUSE_MULTIPLIER",
    "LedgerAuditor",
    "build_rival_intel_command",
    "cash_control_thermometer",
    "configured_arbitrage_band",
    "configured_clause_increase_multiplier",
    "configured_league_start_date",
    "configured_starting_clause_multiplier",
    "configured_thermometer_tau",
    "configured_uncertainty_floor_eur",
    "events_from_ledgers",
    "extract_money",
    "get_financial_intel",
    "madrid_day_of",
    "parse_activities",
    "reward_amount",
    "today_madrid",
]


# --- Utilidades de lectura --------------------------------------------------


def _fold(text: Any) -> str:
    """Minúsculas sin acentos ni separadores: ``initial_clause`` → ``initialclause``."""
    if not isinstance(text, str):
        return ""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", plain.casefold())


def _first(node: Any, *keys: str) -> Any:
    """Primer valor no vacío de ``keys``, tolerante a ``camelCase`` y acentos."""
    if not isinstance(node, Mapping):
        return None
    folded = {_fold(str(key)): value for key, value in node.items()}
    for key in keys:
        if key in node and node[key] not in (None, ""):
            return node[key]
        alias = folded.get(_fold(key))
        if alias not in (None, ""):
            return alias
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        return _parse_amount(value)
    return None


def _parse_amount(raw: str) -> int | None:
    """Convierte ``4.500.000`` / ``4,500,000`` / ``4500000,50`` a entero de euros."""
    text = raw.replace("\u00a0", "").replace(" ", "").strip(".,")
    if not text:
        return None
    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        parts = text.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            text = f"{parts[0]}.{parts[1]}"
        else:
            text = text.replace(",", "")
    elif has_dot:
        parts = text.split(".")
        if len(parts) >= 2 and all(len(part) == 3 for part in parts[1:]):
            text = "".join(parts)
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return int(round(value))


def extract_money(text: Any) -> list[dict[str, Any]]:
    """Cantidades numéricas del texto, con marca de si llevan moneda pegada."""
    if not isinstance(text, str) or not text:
        return []
    found: list[dict[str, Any]] = []
    for match in _NUMBER.finditer(text):
        amount = _parse_amount(match.group(0))
        if amount is None or amount <= 0:
            continue
        tail = text[match.end() : match.end() + 8].lstrip()
        head = text[max(0, match.start() - 3) : match.start()].rstrip()
        currency = tail.startswith("€") or tail.casefold().startswith(("eur", "euro"))
        currency = currency or head.endswith("€")
        found.append({"amount": amount, "currency": currency, "raw": match.group(0)})
    return found


def reward_amount(text: Any) -> int | None:
    """Importe de un abono descrito en prosa. ``None`` si no hay importe creíble.

    Prioriza las cantidades pegadas al símbolo ``€``. Si no las hay, exige una
    palabra de abono y descarta los números pequeños (jornadas) y los que
    parecen un año: una fecha en el texto no es un premio.
    """
    tokens = extract_money(text)
    if not tokens:
        return None
    marked = [token["amount"] for token in tokens if token["currency"]]
    if marked:
        return max(marked)
    if isinstance(text, str) and _REWARD_WORDS.search(text):
        big = [
            token["amount"]
            for token in tokens
            if token["amount"] >= 1_000 and not 1900 <= token["amount"] <= 2100
        ]
        if big:
            return max(big)
    return None


def _madrid_day(at: Any) -> str | None:
    """Fecha civil Europe/Madrid de una marca ISO. ``None`` si no es usable."""
    if not isinstance(at, str) or not at.strip():
        return None
    text = at.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        head = text[:10]
        return head if len(head) == 10 and head[4] == "-" and head[7] == "-" else None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_MADRID)
    return moment.astimezone(_MADRID).date().isoformat()


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=_MADRID)
        return moment.astimezone(_MADRID).date()
    if isinstance(value, str):
        day = _madrid_day(value)
        if day is None:
            return None
        try:
            return date.fromisoformat(day)
        except ValueError:
            return None
    return None


def _aware(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=_MADRID)
    return moment


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def today_madrid(moment: datetime | None = None) -> date:
    """Día civil Europe/Madrid del instante dado."""
    return _aware(moment).astimezone(_MADRID).date()


def madrid_day_of(value: str) -> str | None:
    """``YYYY-MM-DD`` en Europe/Madrid de una marca ISO del tablero."""
    return _madrid_day(value)


def _days_elapsed(start: date, today: date, *, include_start: bool) -> int:
    """Días de liga transcurridos. Inclusivo por defecto: hoy también cuenta."""
    if today < start:
        return 0
    days = (today - start).days
    return days + 1 if include_start else days


def _join_days(events: list[dict[str, Any]]) -> dict[str, date]:
    """Primer día en que cada equipo aparece en la liga (marcador ``join``).

    Es el techo real del devengo de publicidad: antes de existir en la liga no
    hay vídeo que cobrar. Un equipo sin alta propia hereda el nacimiento de la
    liga (ver ``_league_birth``).
    """
    per_team: dict[str, date] = {}
    for event in events:
        if event.get("marker") != "join":
            continue
        day = _as_date(event.get("at"))
        team_id = event.get("team_id")
        if day is None or not isinstance(team_id, str) or not team_id:
            continue
        current = per_team.get(team_id)
        per_team[team_id] = day if current is None else min(current, day)
    return per_team


def _league_birth(
    events: list[dict[str, Any]], join_days: Mapping[str, date]
) -> tuple[date | None, str | None]:
    """Día en que nació la liga, según la evidencia del propio tablón.

    Dos señales, de más a menos fuerte:

    1. El alta de cualquier mánager (tipo 9). Es literal: ese día existió la
       liga.
    2. El primer movimiento fechado. No puede haber un fichaje antes de que
       exista la competición, así que el nacimiento es ese día o antes. Se usa
       como cota: es lo único que hay cuando el tablón no publica altas (el
       feed real no las trae).

    Sin ninguna de las dos, ``(None, None)``: manda la configuración.
    """
    if join_days:
        return min(join_days.values()), "alta"
    firsts = [day for day in (_as_date(event.get("at")) for event in events) if day is not None]
    if firsts:
        return min(firsts), "actividad"
    return None, None


def _no_score_reasons(events: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Motivos por los que un equipo no puntuó: ``{team_id: {motivo}}``."""
    found: dict[str, set[str]] = {}
    for event in events:
        if event.get("marker") != "no_score":
            continue
        team_id = event.get("team_id")
        reason = event.get("no_score_reason")
        if isinstance(team_id, str) and team_id and isinstance(reason, str) and reason:
            found.setdefault(team_id, set()).add(reason)
    return found


def _balance_floor_days(events: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Días en que el juego documentó saldo negativo (tipo 8), por equipo.

    Un aviso así prueba que la caja del equipo puede estar bajo cero, así que
    el suelo de anuncios se desactiva en vez de contar ese descubierto como
    prueba de publicidad cobrada.
    """
    days: dict[str, set[str]] = {}
    for event in events:
        if event.get("marker") != "no_score":
            continue
        if event.get("no_score_reason") != NEGATIVE_BALANCE_REASON:
            continue
        team_id = event.get("team_id")
        day = _madrid_day(event.get("at"))
        if isinstance(team_id, str) and team_id and day is not None:
            days.setdefault(team_id, set()).add(day)
    return days


def _balance_floor(
    events: list[dict[str, Any]],
    *,
    initial: int,
    revenue: int,
    after: str | None = None,
    excused_days: set[str] | None = None,
) -> tuple[int, int | None]:
    """Publicidad mínima que el propio gasto del rival obliga a haber cobrado.

    El juego anula la jornada entera si el saldo es negativo al inicio y lo
    publica como tipo 8. Así que, si ese aviso **no** aparece, la caja nunca
    estuvo bajo cero en un cierre: cualquier mínimo negativo del libro tuvo que
    cubrirlo publicidad.

    El suelo se aplica siempre: es una cota, no una corrección de emergencia.
    Un aviso de saldo negativo en un día no borra el resto de la serie, porque
    ese aviso es prueba de que el mecanismo de anuncios existe, no de que el
    rival viviera a crédito toda la temporada.

    Se mide a cierre de día, no intradía: un descubierto que una venta del
    mismo día arregló no es prueba de nada.

    Devuelve el importe en euros del suelo y el mínimo medido (o ``None`` si no
    hay movimientos).
    """
    movements = [
        event
        for event in events
        if event.get("kind") != "marker" and isinstance(event.get("amount_eur"), int)
    ]
    if not movements:
        return 0, None
    by_day: dict[str, int] = {}
    for event in movements:
        if event.get("kind") == "initial":
            # El presupuesto inicial ya está dentro de la caja de partida.
            continue
        day = _madrid_day(event.get("at"))
        if day is None:
            continue
        if after is not None and day <= after:
            continue
        by_day[day] = by_day.get(day, 0) + int(event["signed_eur"])
    balance = initial
    lowest = balance
    for day in sorted(by_day):
        balance += by_day[day]
        lowest = min(lowest, balance)
    if lowest >= 0:
        return 0, int(lowest)
    needed = (-lowest + revenue - 1) // revenue * revenue
    return int(needed), int(lowest)


# --- Termómetro de control --------------------------------------------------


def _normal_cdf(value: float) -> float:
    """CDF normal estándar. ``math.erf`` evita depender de scipy en este módulo."""
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def cash_control_thermometer(
    calculated_cash: int,
    observed_cash: int,
    *,
    tau: float,
    band: float,
    floor_eur: int | None = None,
    accrual_eur: int = 0,
) -> dict[str, Any]:
    """Lectura calibrada del hueco entre la cota calculada y la caja observada.

    El motor publica una **cota superior** (``calculated_cash``) y la API un
    saldo observado. El signo del hueco dice cosas distintas:

    ``hueco < 0`` (la cota se queda corta)
        La reconstrucción está mal: hay dinero que los libros no explican. La
        cota **no** se infla para taparlo (sería inventar una cifra); se publica
        ``arbitrage_eur`` para que la puja sepa cuánto se está jugando a ciegas.
    ``hueco > 0`` (la cota sobra)
        La cota cubre, pero puede estar muy holgada. ``tight_ceiling_eur`` la
        aprieta al saldo observado más el dinero que pudo entrar desde la foto
        (``accrual_eur``) y un margen de ruido contable. Nunca baja del saldo
        publicado: la cifra sigue siendo una cota superior.

    Campos:

    ``temperature``
        ``exp(-|hueco| / (tau · referencia))`` en ``(0, 1]``. Cerca de 1 la cota
        cuadra con la caja publicada; cerca de 0 la cota no explica la caja en
        absoluto. Es la lectura del termómetro: no decide nada por sí sola.
    ``posterior_sigma_eur``
        ``σ_cash = max(suelo, |hueco|)``: la incertidumbre contable que alimenta
        la barrera bayesiana de la puja (``Φ((B − C) / σ)``).
    ``cover_probability``
        ``Φ(hueco / σ)``: probabilidad de que la cota siga cubriendo la caja
        real una vez descontada esa incertidumbre.
    ``arbitrage_eur``
        Caja observada que la cota no explica y que no cabe en la banda de
        medición (``band · caja``).
    ``tight_ceiling_eur``
        Cota apretada: el mínimo entre la calculada y ``observado + margen``.
    """
    observed = int(observed_cash)
    calculated = int(calculated_cash)
    gap = calculated - observed
    reference = max(abs(observed), abs(calculated), 1)
    relative_gap = gap / reference

    tau_value = tau if math.isfinite(tau) and tau > 0 else DEFAULT_CASH_THERMOMETER_TAU
    temperature = math.exp(-abs(relative_gap) / tau_value)
    noise_eur = int(round(max(abs(observed), 1) * max(0.0, band)))
    residual = abs(gap)
    arbitrage = max(0, residual - noise_eur) if gap < 0 else 0
    floor = DEFAULT_CASH_UNCERTAINTY_FLOOR_EUR if floor_eur is None else max(0, int(floor_eur))
    sigma = float(max(floor, residual))
    cover = _normal_cdf(gap / sigma) if sigma > 0 else (1.0 if gap >= 0 else 0.0)

    # Cota calibrada. Nunca queda por debajo del saldo publicado: ese dato es
    # un hecho, y una cota por debajo de un hecho está mal por definición. Con
    # la cota por encima, se recorta el exceso más allá del margen (ruido
    # contable + publicidad devengada desde la foto). Con la cota por debajo, no
    # se inventa dinero hacia arriba: la cifra defendible es la observada y el
    # sobrante se publica en ``arbitrage_eur`` para que la puja sepa el riesgo.
    margin = floor + noise_eur + max(0, int(accrual_eur))
    if gap >= 0:
        tight = min(calculated, observed + margin)
    else:
        tight = observed
    tight = max(observed, tight)
    slack = max(0, calculated - tight)

    if gap < 0:
        status = "underestimated" if arbitrage > 0 else "within_band"
    elif gap == 0:
        status = "exact"
    else:
        status = "loose" if slack > 0 else "tight"
    return {
        "gap_eur": gap,
        "relative_gap": round(relative_gap, 6),
        "temperature": round(temperature, 4),
        "cover_probability": round(cover, 4),
        "noise_band_eur": noise_eur,
        "arbitrage_eur": int(arbitrage),
        "posterior_sigma_eur": int(round(sigma)),
        "tightening_margin_eur": int(margin),
        "tight_ceiling_eur": int(tight),
        "slack_eur": int(slack),
        "status": status,
        "underestimated": gap < 0,
        "covers_observed": gap >= 0,
    }


# --- Lectura del historial --------------------------------------------------


def _activity_rows(activity: Any, depth: int = 0) -> list[dict[str, Any]]:
    """Acepta lista de eventos, documento de actividad o ledger ya troceado."""
    if depth > 4 or activity is None:
        return []
    if isinstance(activity, Sequence) and not isinstance(activity, (str, bytes)):
        return [row for row in activity if isinstance(row, Mapping)]
    if not isinstance(activity, Mapping):
        return []
    for key in ("events", "activity", "items", "elements", "transactions", "rows", "data", "content"):
        value = activity.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            rows = [row for row in value if isinstance(row, Mapping)]
            if rows:
                return rows
    for key in ("payload", "response", "result", "board"):
        nested = activity.get(key)
        if isinstance(nested, (Mapping, list, tuple)):
            rows = _activity_rows(nested, depth + 1)
            if rows:
                return rows
    if _looks_like_event(activity):
        return [activity]
    return []


def _looks_like_event(row: Mapping[str, Any]) -> bool:
    if "activityTypeId" in row or "activity_type_id" in row:
        return True
    return _row_kind(row)[0] is not None


def _row_kind(row: Mapping[str, Any]) -> tuple[str | None, int | None]:
    """Tipo canónico y ``activityTypeId`` si venía en la fila."""
    type_id = _as_int(_first(row, "activityTypeId", "activity_type_id", "typeId"))
    if type_id is not None:
        kind = _ACTIVITY_KIND.get(type_id)
        if kind is not None:
            return kind, type_id
    for key in ("kind", "type", "operation", "action", "transactionType", "movementType"):
        raw = _first(row, key)
        if isinstance(raw, str):
            kind = _KIND_ALIASES.get(_fold(raw))
            if kind is not None:
                return kind, type_id
    return None, type_id

def _team_events(events: list[dict[str, Any]], team_id: str) -> list[dict[str, Any]]:
    """Solo los eventos que mueven dinero de un equipo.

    Un traspaso entre rivales aparece dos veces: el gasto del comprador y el
    cobro del vendedor. Aquí interesa el libro propio, así que se filtra por
    ``team_id`` y se dejan fuera los marcadores (ya no son importes).
    """
    return [
        event
        for event in events
        if event.get("team_id") == team_id
        and event.get("kind") != "marker"
        and isinstance(event.get("amount_eur"), int)
        and not isinstance(event.get("amount_eur"), bool)
    ]


def _no_score_reason(type_id: int | None) -> str | None:
    """Motivo por el que una jornada no puntuó, si el tipo lo dice."""
    return _NO_SCORE_KIND.get(type_id) if type_id is not None else None


def _row_text(row: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _TEXT_KEYS:
        value = _first(row, key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(dict.fromkeys(parts))


def _row_amount(row: Mapping[str, Any]) -> int | None:
    for key in ("amount_eur", "amount", "money", "value", "price", "cash", "cost", "signed_eur"):
        found = _as_int(_first(row, key))
        if found is not None:
            return abs(found)
    return None


def _row_player(row: Mapping[str, Any]) -> str | None:
    found = _first(row, *_PLAYER_KEYS)
    value = _as_int(found)
    if value is not None:
        return str(value)
    if isinstance(found, str) and found.strip():
        return found.strip()
    player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
    master = player.get("playerMaster") if isinstance(player.get("playerMaster"), Mapping) else {}
    for node in (player, master):
        nested = _first(node, "id", "playerId")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
        number = _as_int(nested)
        if number is not None:
            return str(number)
    return None


def _row_team(row: Mapping[str, Any]) -> str | None:
    found = _first(row, *_TEAM_KEYS)
    number = _as_int(found)
    if number is not None:
        return str(number)
    if isinstance(found, str) and found.strip():
        return found.strip()
    team = row.get("team") if isinstance(row.get("team"), Mapping) else {}
    nested = _first(team, "id", "teamId")
    if nested is not None:
        return str(nested)
    return None


def _row_manager(row: Mapping[str, Any]) -> str | None:
    found = _first(row, *_MANAGER_KEYS)
    number = _as_int(found)
    if number is not None:
        return str(number)
    return found.strip() if isinstance(found, str) and found.strip() else None


def _parse_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Una fila del tablón. La prosa solo se usa cuando el importe no viene."""
    kind, type_id = _row_kind(row)
    label = _row_text(row)
    at = _first(row, *_TIME_KEYS)
    at = at if isinstance(at, str) else None
    amount = _row_amount(row)
    matched_by = "campo" if amount is not None else None

    if amount is None:
        amount = reward_amount(label)
        matched_by = "regex" if amount is not None else None
    if kind is None and amount is not None and label:
        # Tipo desconocido con importe y palabra de abono: es una prima.
        if _REWARD_WORDS.search(label):
            kind = "premium"
    if kind is None:
        # Sin dinero: ¿es un marcador que fecha o prueba un estado de caja?
        marker = _MARKER_KIND.get(type_id) if type_id is not None else None
        if marker is None:
            return None
        activity_id = _first(row, "activityId", "id", "movementId")
        return {
            "kind": "marker",
            "marker": marker,
            "no_score_reason": _no_score_reason(type_id),
            "week_number": _as_int(_first(row, "weekNumber", "week_number")),
            "amount_eur": None,
            "team_id": _row_team(row),
            "manager_id": _row_manager(row),
            "player_id": _row_player(row),
            "label": label or None,
            "at": at,
            "activity_type_id": type_id,
            "activity_id": str(activity_id) if activity_id is not None else None,
            "matched_by": None,
            "signed_eur": 0,
        }
    if amount is None or amount <= 0:
        return None

    activity_id = _first(row, "activityId", "id", "movementId")
    event: dict[str, Any] = {
        "kind": kind,
        "amount_eur": amount,
        "team_id": _row_team(row),
        "manager_id": _row_manager(row),
        "player_id": _row_player(row),
        "label": label or None,
        "at": at,
        "activity_type_id": type_id,
        "activity_id": str(activity_id) if activity_id is not None else None,
        "matched_by": matched_by,
        "signed_eur": amount if kind in {"initial", "premium", "sell"} else -amount,
    }
    counterparty = _first(row, *_COUNTERPARTY_KEYS)
    if kind == "clause" and counterparty is not None and _as_int(counterparty) is not None:
        event["counterparty_manager_id"] = str(_as_int(counterparty))
    return event


def parse_activities(activity: Any) -> list[dict[str, Any]]:
    """Historial completo → eventos canónicos, sin duplicar páginas repetidas."""
    events: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in _activity_rows(activity):
        event = _parse_row(row)
        if event is None:
            continue
        if event["activity_id"] is not None:
            key: tuple[Any, ...] = ("id", event["activity_id"])
        else:
            key = (
                "row",
                event["team_id"],
                event["kind"],
                event["amount_eur"],
                event["at"],
                event["player_id"],
                event["label"],
            )
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    events.sort(
        key=lambda item: (
            item.get("at") is None,
            str(item.get("at") or ""),
            str(item.get("team_id") or ""),
            str(item.get("kind") or ""),
        )
    )
    return events


# --- Plantillas y jugadores -------------------------------------------------


def _roster(squads: Any) -> list[dict[str, Any]]:
    if isinstance(squads, Mapping):
        rows = squads.get("squads")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, Mapping)]
        if isinstance(squads.get("players"), list):
            return [squads]
        return []
    if isinstance(squads, Sequence) and not isinstance(squads, (str, bytes)):
        return [row for row in squads if isinstance(row, Mapping)]
    return []


def _deep_values(node: Any, folded_keys: frozenset[str], depth: int) -> list[tuple[str, Any]]:
    """Busca claves ocultas en el jugador y en sus nodos anidados."""
    if depth < 0 or not isinstance(node, Mapping):
        return []
    found: list[tuple[str, Any]] = []
    for key, value in node.items():
        folded = _fold(str(key))
        if folded in folded_keys:
            found.append((str(key), value))
        elif isinstance(value, Mapping):
            found.extend(_deep_values(value, folded_keys, depth - 1))
    return found


def _hidden_clause_base(player: Mapping[str, Any]) -> tuple[int | None, str | None]:
    """Cláusula original escondida en el JSON (``buyPrice``, ``initialClause``…).

    Con varias candidatas se elige la mayor: una base más alta deja menos
    incremento por cobrar y mantiene la cota superior de caja.
    """
    best: int | None = None
    best_key: str | None = None
    for key, value in _deep_values(player, _CLAUSE_BASE_KEYS, depth=3):
        amount = _as_int(value)
        if amount is None or amount <= 0:
            continue
        if best is None or amount > best:
            best, best_key = amount, key
    return best, best_key


def _player_view(player: Mapping[str, Any]) -> dict[str, Any]:
    """Vista común para plantillas normalizadas y para JSON crudo de la API."""
    master = player.get("playerMaster") if isinstance(player.get("playerMaster"), Mapping) else {}
    player_id = _first(player, "player_id", "playerId", "playerMasterId")
    if isinstance(player_id, str) and player_id.strip():
        player_id = player_id.strip()
    else:
        number = _as_int(player_id)
        player_id = str(number) if number is not None else None
    if player_id is None:
        nested = _first(master, "id", "playerId")
        number = _as_int(nested)
        player_id = str(number) if number is not None else (
            nested.strip() if isinstance(nested, str) and nested.strip() else None
        )

    clause = _as_int(_first(player, "buyout_clause", "buyoutClause", "clause", "buyout", "clausula"))
    market_value = _as_int(_first(player, "market_value", "marketValue", "fantasy_price"))
    if market_value is None:
        market_value = _as_int(_first(master, "marketValue", "value", "fantasyPrice"))
    hidden, hidden_key = _hidden_clause_base(player)

    name = _first(player, "name") or _first(master, "name", "fullname")
    nickname = _first(player, "nickname") or _first(master, "nickname", "shortName")
    label = nickname if isinstance(nickname, str) and nickname.strip() else name

    return {
        "player_id": player_id,
        "name": name if isinstance(name, str) and name.strip() else player_id,
        "nickname": nickname if isinstance(nickname, str) and nickname.strip() else None,
        "label": label if isinstance(label, str) and label.strip() else player_id,
        "position": _first(player, "position") or _first(master, "position"),
        "buyout_clause": clause,
        "market_value": market_value,
        "hidden_base": hidden,
        "hidden_key": hidden_key,
    }


def _acquisition_index(events: list[dict[str, Any]]) -> dict[tuple[str | None, str], dict[str, Any]]:
    """Última compra o cláusula pagada por jugador, por equipo."""
    index: dict[tuple[str | None, str], dict[str, Any]] = {}
    for event in events:
        if event.get("kind") not in {"buy", "clause"}:
            continue
        player_id = event.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            continue
        index[(event.get("team_id"), player_id)] = event
    return index


# --- Contabilidad -----------------------------------------------------------


def _bind_teams(
    events: list[dict[str, Any]],
    roster: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """De id de mánager a id de equipo y cobro de la cláusula al vendedor.

    Si el evento ya viene de un libro contable (con ``team_id`` pero sin
    ``manager_id``), no se toca: el asiento del vendedor ya está creado.
    """
    manager_to_team: dict[str, str] = {}
    for squad in roster:
        manager_id = squad.get("manager_id")
        team_id = squad.get("team_id")
        if isinstance(manager_id, (str, int)) and not isinstance(manager_id, bool):
            if isinstance(team_id, str) and team_id:
                manager_to_team[str(manager_id)] = team_id

    bound: list[dict[str, Any]] = []
    existing: set[tuple[Any, ...]] = set()
    for event in events:
        team_id = event.get("team_id")
        manager_id = event.get("manager_id")
        resolved = manager_to_team.get(str(manager_id), team_id) if manager_id is not None else team_id
        if not isinstance(resolved, str) or not resolved:
            continue
        item = dict(event)
        item["team_id"] = resolved
        bound.append(item)
        existing.add(
            (resolved, item.get("kind"), item.get("amount_eur"), item.get("at"), item.get("player_id"))
        )

    credits: list[dict[str, Any]] = []
    for item in bound:
        if item.get("kind") != "clause":
            continue
        if item.get("manager_id") is None:
            continue
        counterparty = item.get("counterparty_manager_id")
        if not isinstance(counterparty, str) or not counterparty:
            continue
        seller_team = manager_to_team.get(counterparty, counterparty)
        if not seller_team or seller_team == item.get("team_id"):
            continue
        key = (seller_team, "sell", item.get("amount_eur"), item.get("at"), item.get("player_id"))
        if key in existing:
            continue
        existing.add(key)
        credit = dict(item)
        credit.update(
            {
                "kind": "sell",
                "team_id": seller_team,
                "manager_id": counterparty,
                "counterparty_manager_id": item.get("team_id"),
                "label": "clausula_cobrada",
                "signed_eur": item.get("amount_eur"),
            }
        )
        credits.append(credit)
    return bound + credits


def _aggregate(
    events: list[dict[str, Any]],
    *,
    after: str | None = None,
) -> tuple[dict[str, dict[str, int]], dict[str, int], int, dict[str, int]]:
    """Flujos por equipo. Con ``after`` solo cuenta lo estrictamente posterior.

    Un evento sin fecha no puede colocarse después del ancla y se descarta en
    ese modo: dejar de restar un gasto mantiene la cota superior.
    """
    flows: dict[str, dict[str, int]] = {}
    initial: dict[str, int] = {}
    kinds: dict[str, int] = {}
    ignored = 0
    for event in events:
        team_id = event.get("team_id")
        kind = event.get("kind")
        amount = event.get("amount_eur")
        if kind == "marker":
            # Un alta o un "no puntuó" no mueve dinero: no cuenta ni como evento.
            continue
        if not isinstance(team_id, str) or not team_id or not isinstance(kind, str):
            ignored += 1
            continue
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            ignored += 1
            continue
        if after is not None:
            day = _madrid_day(event.get("at"))
            if day is None or day <= after:
                continue
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "initial":
            initial[team_id] = max(initial.get(team_id, 0), amount)
            continue
        if kind not in _MONEY_KINDS:
            ignored += 1
            continue
        bucket = flows.setdefault(
            team_id,
            {"premiums": 0, "sales": 0, "purchases": 0, "clauses": 0, "events": 0},
        )
        bucket["events"] += 1
        if kind == "premium":
            bucket["premiums"] += amount
        elif kind == "sell":
            bucket["sales"] += amount
        elif kind == "buy":
            bucket["purchases"] += amount
        elif kind == "clause":
            bucket["clauses"] += amount
    return flows, initial, ignored, kinds


def _clause_map(snapshot: Any) -> dict[str, dict[str, int]]:
    """Plantilla de cláusulas comparable: ``{team_id: {player_id: cláusula}}``.

    Acepta el documento de plantillas, el plano guardado por
    ``save_clause_snapshot`` y un ``{"teams": ...}`` ya indexado.
    """
    if snapshot is None:
        return {}
    if isinstance(snapshot, Mapping):
        teams = snapshot.get("teams")
        if isinstance(teams, Mapping):
            mapped = _clause_map_from_team_map(teams)
            if mapped:
                return mapped
        plain = _clause_map_from_team_map(snapshot)
        if plain:
            return plain
        return _clauses_from_squads(_roster(snapshot))
    return _clauses_from_squads(_roster(snapshot))


def _clause_map_from_team_map(teams: Mapping[Any, Any]) -> dict[str, dict[str, int]]:
    """``{team_id: {player_id: cláusula}}`` tolerante a dos niveles de anidado."""
    mapped: dict[str, dict[str, int]] = {}
    for team_id, body in teams.items():
        if not isinstance(team_id, str) or not team_id:
            continue
        if isinstance(body, Mapping):
            nested = body.get("players")
            if isinstance(nested, Mapping):
                values = {
                    str(player_id): clause
                    for player_id, raw in nested.items()
                    if (clause := _as_int(raw)) is not None and clause > 0
                }
            elif isinstance(nested, list):
                values = _clauses_from_players(nested)
            else:
                values = {
                    str(player_id): clause
                    for player_id, raw in body.items()
                    if (clause := _as_int(raw)) is not None and clause > 0
                }
        elif isinstance(body, list):
            values = _clauses_from_players(body)
        else:
            continue
        if values:
            mapped[team_id] = values
    return mapped


def _clauses_from_squads(roster: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    mapped: dict[str, dict[str, int]] = {}
    for squad in roster:
        team_id = squad.get("team_id")
        if not isinstance(team_id, str) or not team_id:
            continue
        values = _clauses_from_players(squad.get("players") or [])
        if values:
            mapped[team_id] = values
    return mapped


def _clauses_from_players(players: Any) -> dict[str, int]:
    values: dict[str, int] = {}
    for player in players if isinstance(players, list) else []:
        if not isinstance(player, Mapping):
            continue
        view = _player_view(player)
        player_id = view["player_id"]
        clause = view["buyout_clause"]
        if isinstance(player_id, str) and player_id and clause is not None and clause > 0:
            values[player_id] = clause
    return values


def _merge_expense_entries(entries: Mapping[tuple[str, str, str], dict[str, Any]], row: dict[str, Any]) -> None:
    key = (row["team_id"], row["player_id"], row["day"])
    current = entries.get(key)
    if current is None or row["cost_eur"] > current["cost_eur"]:
        entries[key] = row
    else:
        current["clause_after_eur"] = max(current.get("clause_after_eur") or 0, row["clause_after_eur"])


# --- Motor ------------------------------------------------------------------


class LedgerAuditor:
    """Conciliación de la caja rival con cota superior y gasto oculto.

    No hace red: recibe el documento de plantillas y el historial de actividad
    ya descargados. ``build_rival_intel_command`` es el adaptador de red.
    """

    def __init__(
        self,
        *,
        initial_budget: int | None = None,
        league_start_date: str | date | None = None,
        daily_ad_revenue: int | None = None,
        clause_increase_multiplier: float | None = None,
        starting_clause_multiplier: float | None = None,
        debt_limit_eur: int = 0,
        debt_limits: Mapping[str, int] | None = None,
        thermometer_tau: float | None = None,
        arbitrage_band: float | None = None,
        uncertainty_floor_eur: int | None = None,
        adjustments_path: Path | None = None,
        expenses_path: Path | None = None,
        snapshot_path: Path | None = None,
        include_start_day: bool = True,
        persist: bool = True,
    ) -> None:
        self.initial_budget = int(initial_budget) if initial_budget is not None else INITIAL_BUDGET
        # Se relee del entorno/``.env`` en cada motor: un cambio de regla no
        # exige reimportar el módulo, y el argumento explícito sigue mandando.
        self.league_start_date = (
            _as_date(league_start_date)
            or _as_date(configured_league_start_date())
            or _as_date(DEFAULT_LEAGUE_START_DATE)
            or date(2026, 8, 1)
        )
        self.daily_ad_revenue = int(daily_ad_revenue) if daily_ad_revenue is not None else DAILY_AD_REVENUE
        self.clause_increase_multiplier = (
            float(clause_increase_multiplier)
            if clause_increase_multiplier is not None
            else configured_clause_increase_multiplier()
        )
        self.starting_clause_multiplier = (
            float(starting_clause_multiplier)
            if starting_clause_multiplier is not None
            else configured_starting_clause_multiplier()
        )
        self.thermometer_tau = (
            float(thermometer_tau) if thermometer_tau is not None else configured_thermometer_tau()
        )
        if not math.isfinite(self.thermometer_tau) or self.thermometer_tau <= 0:
            self.thermometer_tau = DEFAULT_CASH_THERMOMETER_TAU
        self.arbitrage_band = (
            float(arbitrage_band) if arbitrage_band is not None else configured_arbitrage_band()
        )
        if not math.isfinite(self.arbitrage_band) or not 0 <= self.arbitrage_band < 1:
            self.arbitrage_band = DEFAULT_CASH_ARBITRAGE_BAND
        self.uncertainty_floor_eur = (
            int(uncertainty_floor_eur)
            if uncertainty_floor_eur is not None
            else configured_uncertainty_floor_eur()
        )
        self.uncertainty_floor_eur = max(0, self.uncertainty_floor_eur)
        self.debt_limit_eur = max(0, int(debt_limit_eur))
        self.debt_limits = {
            str(team_id): max(0, int(limit))
            for team_id, limit in (debt_limits or {}).items()
            if isinstance(limit, int) and not isinstance(limit, bool)
        }
        self.adjustments_path = Path(adjustments_path) if adjustments_path else project_root() / ADJUSTMENTS_FILENAME
        self.expenses_path = Path(expenses_path) if expenses_path else cache_root() / HIDDEN_EXPENSES_FILENAME
        self.snapshot_path = Path(snapshot_path) if snapshot_path else cache_root() / CLAUSE_SNAPSHOTS_FILENAME
        self.include_start_day = include_start_day
        self.persist = persist

    # -- 2. Motor de reconstrucción histórica --------------------------------

    def parse_activities(self, activity: Any) -> list[dict[str, Any]]:
        """Historial completo del endpoint ``/activity`` en eventos canónicos."""
        return parse_activities(activity)

    def _resolve_initial(
        self,
        events: list[dict[str, Any]],
        roster: list[dict[str, Any]],
    ) -> tuple[dict[str, int], int, str]:
        """Presupuesto por equipo, el de la liga y su origen.

        Un ``initial`` explícito del historial manda. Si varios equipos traen
        importes distintos se toma el mayor: es el que deja más caja al rival.
        """
        per_team = _aggregate(events)[1]
        if per_team:
            shared = max(per_team.values())
            return per_team, shared, "historial"
        return {}, self.initial_budget, "constante"

    def _ad_days(self, today: date, *, since: date | None = None, skip_first: bool = False) -> int:
        """Días con anuncio cobrable. ``skip_first`` arranca al día siguiente.

        Un asiento manual ya resume el día del ancla, así que ese día no vuelve
        a devengar anuncio: se cuenta desde el día siguiente.
        """
        start = since or self.league_start_date
        start = max(start, self.league_start_date)
        if skip_first:
            start = date.fromordinal(start.toordinal() + 1)
        return _days_elapsed(start, today, include_start=self.include_start_day)

    def _ad_accrual_since(self, observed: date, today: date) -> int:
        """Publicidad devengada desde el día del saldo observado hasta hoy.

        El saldo de la API es de la foto, no de este instante. Entre una fecha y
        otra el rival pudo cobrar anuncios: ese dinero ensancha el margen con el
        que se aprieta la cota. El día del saldo no cuenta (ya está dentro).
        """
        if today <= observed:
            return 0
        days = _days_elapsed(observed, today, include_start=False)
        return max(0, days) * self.daily_ad_revenue

    def _calibrate_own_rate(
        self,
        contexts: Mapping[str, Mapping[str, Any]],
        *,
        observed: date,
        today: date,
    ) -> tuple[float | None, str | None]:
        """Tasa diaria de vídeo del mánager propio, medida contra su caja real.

        La publicidad no deja rastro en el tablón, así que no se puede leer: se
        **deduce**. La única caja que la API publica verificada es la propia, y
        su reconstrucción es la más fiable que hay (se ve la plantilla entera y
        las cláusulas pagadas). El hueco entre lo observado y lo reconstruido
        sin anuncios es, repartido entre los días de ventana, la fracción de
        días en que el mánager vio el vídeo.

        El cálculo se hace sobre la caja reconstruida **antes** de deducir el
        gasto oculto estimado: ese gasto se deduce de las subidas de cláusula y
        usarlo aquí sería medir la estimación contra sí misma, sesgando a la
        baja la cota que heredan los rivales. Primero la caja, después la
        deducción. Si el gasto oculto fuera real, la tasa saldría más alta.

        Si la foto de caja no es de hoy, la ventana se recorta al día de la
        foto: los anuncios posteriores no están dentro de ese saldo.

        Devuelve ``(p, aviso)``. ``p`` en ``[0, 1]``, o ``None`` si no hay caja
        propia con la que medir.
        """
        for team_id, ctx in contexts.items():
            if ctx["squad"].get("is_self") is not True:
                continue
            raw_cash = ctx["squad"].get("cash")
            if not isinstance(raw_cash, int) or isinstance(raw_cash, bool):
                return None, None
            start = ctx["team_start"]
            if ctx["anchor"] is not None:
                anchor_day = _as_date(ctx["anchor"][0])
                if anchor_day is not None:
                    start = max(start, date.fromordinal(anchor_day.toordinal() + 1))
            window_days = _days_elapsed(start, today, include_start=self.include_start_day)
            if ctx["max_ad"] <= 0 or window_days <= 0:
                return None, "Sin días de ventana: no llega para calibrar el vídeo diario."
            if observed < today:
                # El saldo es de una foto vieja y la reconstrucción llega hasta
                # hoy: comparar ambas cosas mediría días que no están en la caja.
                return None, (
                    "La caja propia es de una foto anterior a hoy: no se calibra el vídeo "
                    "hasta que haya un saldo del día."
                )
            window_ad = max(0, window_days) * self.daily_ad_revenue
            # Se compara con la caja reconstruida **antes** de deducir el gasto
            # oculto: ese gasto se estima a partir de las subidas de cláusula y
            # tomarlo como punto de partida sesgaría a la baja la cota heredada
            # por los rivales. Primero la caja, después la deducción.
            documented = int(ctx["documented_cash"])
            cash = int(raw_cash)
            recons = int(ctx["pure_cash"])
            raw = (cash - recons) / window_ad
            rate = min(1.0, max(0.0, raw))
            # La diferencia que se explica con anuncios es la caja menos el libro
            # documentado, no la medida contra la cota ya recortada.
            gap = abs(cash - documented)
            note = None
            if raw < -0.02:
                note = (
                    f"Tu caja real queda {gap:,} € por debajo de lo reconstruido sin "
                    "anuncios: hay gasto propio sin registrar. La tasa de vídeo se fija en 0 % "
                    "hasta que cuadre.".replace(",", ".")
                )
            elif raw > 1.02:
                note = (
                    f"Tu caja real supera en {gap:,} € lo reconstruido incluso contando "
                    "todos los vídeos: hay ingresos sin registrar (o el alta es anterior). Tasa fijada en 100 %."
                    .replace(",", ".")
                )
            return rate, note
        return None, None

    # -- 3. Auditoría forense retroactiva -----------------------------------

    def _audit_squad(
        self,
        squad: Mapping[str, Any],
        acquisitions: Mapping[tuple[str | None, str], dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Cláusula base de cada jugador de hoy y coste de las subidas."""
        team_id = squad.get("team_id")
        entries: list[dict[str, Any]] = []
        missing_base = 0
        without_clause = 0
        players = squad.get("players") if isinstance(squad.get("players"), list) else []
        for player in players:
            if not isinstance(player, Mapping):
                continue
            view = _player_view(player)
            player_id = view["player_id"]
            clause = view["buyout_clause"]
            if not isinstance(player_id, str) or not player_id:
                continue
            if clause is None or clause <= 0:
                without_clause += 1
                continue

            acquired = acquisitions.get((team_id, player_id))
            if acquired is not None and isinstance(acquired.get("amount_eur"), int):
                base = int(acquired["amount_eur"])
                basis = "fichado"
                classification = FICHADO
            elif view["hidden_base"] is not None:
                base = int(view["hidden_base"])
                basis = "campo_oculto"
                classification = REPARTO
            elif view["market_value"] is not None and view["market_value"] > 0:
                base = int(round(view["market_value"] * self.starting_clause_multiplier))
                basis = "valor_mercado"
                classification = REPARTO
            else:
                missing_base += 1
                continue

            increase = int(clause) - base
            if increase <= 0:
                continue
            cost = int(round(increase * self.clause_increase_multiplier))
            if cost <= 0:
                continue
            entries.append(
                {
                    "team_id": team_id,
                    "player_id": player_id,
                    "name": view["label"],
                    "nickname": view["nickname"],
                    "position": view["position"],
                    "clause_base_eur": base,
                    "clause_current_eur": int(clause),
                    "increase_eur": increase,
                    "cost_eur": cost,
                    "source": "retroactivo",
                    "basis": basis,
                    "classification": classification,
                    "basis_field": view["hidden_key"] if basis == "campo_oculto" else None,
                    "day": None,
                    "from_day": None,
                }
            )
        return entries, missing_base, without_clause

    # -- 4. Motor de diff diario -------------------------------------------

    def calculate_daily_diff(
        self,
        snapshot_ayer: Any,
        snapshot_hoy: Any,
        *,
        now: datetime | None = None,
        persist: bool | None = None,
        from_day: str | None = None,
        day: str | date | None = None,
    ) -> dict[str, Any]:
        """Subidas de cláusula en 24 h y su coste. Upsert idempotente en el log.

        ``day`` es el día al que corresponden las cláusulas nuevas; por defecto,
        hoy en Europe/Madrid. Sirve para auditar una foto guardada sin fecharla
        como si fuera de ahora.
        """
        current = _aware(now)
        stamp = _as_date(day) if day is not None else today_madrid(current)
        before = _clause_map(snapshot_ayer)
        after = _clause_map(snapshot_hoy)

        changes: list[dict[str, Any]] = []
        if isinstance(snapshot_hoy, Mapping) and isinstance(snapshot_hoy.get("squads"), list):
            roster = _roster(snapshot_hoy)
        else:
            roster = _roster(snapshot_hoy) or [{"team_id": team_id} for team_id in after]
        names = {
            (squad.get("team_id"), view["player_id"]): view
            for squad in roster
            if isinstance(squad.get("team_id"), str)
            for view in (
                _player_view(player)
                for player in (squad.get("players") or [])
                if isinstance(player, Mapping)
            )
        }

        for team_id, players in after.items():
            previous = before.get(team_id)
            if not previous:
                continue
            for player_id, clause in players.items():
                start = previous.get(player_id)
                if start is None or clause <= start:
                    continue
                increase = clause - start
                cost = int(round(increase * self.clause_increase_multiplier))
                if cost <= 0:
                    continue
                view = names.get((team_id, player_id)) or {}
                changes.append(
                    {
                        "team_id": team_id,
                        "player_id": player_id,
                        "name": view.get("label") or player_id,
                        "position": view.get("position"),
                        "clause_before_eur": start,
                        "clause_after_eur": clause,
                        "increase_eur": increase,
                        "cost_eur": cost,
                        "source": "diario",
                        "basis": "snapshot",
                        "classification": REPARTO,
                        "day": stamp.isoformat(),
                        "from_day": from_day,
                        "detected_at": _iso(current),
                    }
                )

        changes.sort(key=lambda row: (-row["cost_eur"], row["team_id"], row["player_id"]))
        cost_by_team: dict[str, int] = {}
        for row in changes:
            cost_by_team[row["team_id"]] = cost_by_team.get(row["team_id"], 0) + row["cost_eur"]

        written = False
        warnings: list[str] = []
        if persist if persist is not None else self.persist:
            written, warnings = self._append_hidden_expenses(changes, now=current)

        return {
            "ok": True,
            "day": stamp.isoformat(),
            "from_day": from_day,
            "changes": changes,
            "cost_by_team": cost_by_team,
            "total_cost_eur": sum(row["cost_eur"] for row in changes),
            "persisted": written,
            "warnings": warnings,
        }

    # -- 5. Asientos de ajuste contable ------------------------------------

    def load_adjustments(self) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
        """``ledger_adjustments.json`` validado. Un fallo no tumba la auditoría."""
        data, error = _read_json(self.adjustments_path)
        if error is not None:
            return {}, [error]
        if data is None:
            # Sin fichero no hay asientos: es el caso normal, no un aviso.
            return {}, []
        if not isinstance(data, Mapping):
            return {}, [f"{self.adjustments_path.name}: la raíz no es un objeto."]
        warnings: list[str] = []
        cleaned: dict[str, dict[str, dict[str, Any]]] = {}
        for team_id, days in data.items():
            if str(team_id).startswith("_"):
                # Claves de documentación (``_comment``, ``_formato``): no son equipos.
                continue
            if not isinstance(days, Mapping):
                warnings.append(f"{self.adjustments_path.name}: {team_id} no es un objeto de fechas.")
                continue
            valid: dict[str, dict[str, Any]] = {}
            for day, entry in days.items():
                parsed_day = _as_date(day)
                if parsed_day is None or not isinstance(entry, Mapping):
                    warnings.append(f"{self.adjustments_path.name}: asiento inválido {team_id}/{day}.")
                    continue
                cash = _as_int(entry.get("cash_override"))
                if cash is None:
                    warnings.append(f"{self.adjustments_path.name}: {team_id}/{day} sin cash_override.")
                    continue
                valid[parsed_day.isoformat()] = {
                    "cash_override": cash,
                    "reason": entry.get("reason") if isinstance(entry.get("reason"), str) else None,
                }
            if valid:
                cleaned[str(team_id)] = valid
        return cleaned, warnings

    @staticmethod
    def _anchor_for(
        adjustments: Mapping[str, Mapping[str, dict[str, Any]]],
        team_id: str,
        today: date,
    ) -> tuple[str, dict[str, Any]] | None:
        """Asiento más reciente que no esté en el futuro."""
        days = adjustments.get(team_id)
        if not days:
            return None
        candidates = [day for day in days if day <= today.isoformat()]
        if not candidates:
            return None
        latest = max(candidates)
        return latest, days[latest]

    # -- Persistencia -------------------------------------------------------

    def load_hidden_expenses(self) -> dict[str, Any]:
        data, error = _read_json(self.expenses_path)
        entries: list[dict[str, Any]] = []
        if isinstance(data, Mapping) and isinstance(data.get("entries"), list):
            for row in data["entries"]:
                cleaned = _clean_expense_entry(row)
                if cleaned is not None:
                    entries.append(cleaned)
        elif isinstance(data, list):
            for row in data:
                cleaned = _clean_expense_entry(row)
                if cleaned is not None:
                    entries.append(cleaned)
        elif data is not None and error is None:
            error = f"{self.expenses_path.name}: formato no reconocido."
        return {
            "entries": entries,
            "path": str(self.expenses_path),
            "error": error,
            "total_eur": sum(row["cost_eur"] for row in entries),
        }

    def _append_hidden_expenses(
        self,
        changes: list[dict[str, Any]],
        *,
        now: datetime,
    ) -> tuple[bool, list[str]]:
        if not changes:
            return False, []
        loaded = self.load_hidden_expenses()
        indexed: dict[tuple[str, str, str], dict[str, Any]] = {
            (row["team_id"], row["player_id"], row["day"]): row for row in loaded["entries"]
        }
        for row in changes:
            _merge_expense_entries(indexed, row)
        warnings = [loaded["error"]] if loaded["error"] else []
        payload = {
            "version": 1,
            "updated_at": _iso(now),
            "entries": sorted(
                indexed.values(),
                key=lambda row: (row["day"], row["team_id"], row["player_id"]),
            ),
        }
        try:
            _write_json(self.expenses_path, payload)
        except OSError as exc:
            warnings.append(f"{self.expenses_path.name}: no se pudo escribir ({exc}).")
            return False, warnings
        return True, warnings

    def save_clause_snapshot(
        self,
        squads: Any,
        *,
        day: str | date | None = None,
        now: datetime | None = None,
        keep_existing: bool = False,
    ) -> dict[str, Any]:
        """Guarda las cláusulas de ``day`` para poder compararlas mañana.

        ``keep_existing`` no sobrescribe un día ya registrado: la primera
        lectura de la jornada es la referencia del diff.
        """
        current = _aware(now)
        stamp = _as_date(day or current)
        if stamp is None:
            return {"ok": False, "error": "fecha_invalida"}
        mapped = _clause_map(squads)
        if not mapped:
            return {"ok": False, "error": "sin_plantillas"}
        data, _error = _read_json(self.snapshot_path)
        days: dict[str, Any] = {}
        if isinstance(data, Mapping) and isinstance(data.get("days"), Mapping):
            days = {str(key): value for key, value in data["days"].items() if isinstance(value, Mapping)}
        if keep_existing and stamp.isoformat() in days:
            return {"ok": True, "day": stamp.isoformat(), "teams": len(mapped), "skipped": True}
        days[stamp.isoformat()] = mapped
        keep = sorted(days)[-CLAUSE_SNAPSHOT_KEEP_DAYS:]
        payload = {"version": 1, "updated_at": _iso(current), "days": {key: days[key] for key in keep}}
        try:
            _write_json(self.snapshot_path, payload)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "day": stamp.isoformat(), "teams": len(mapped), "skipped": False}

    def load_clause_snapshot(self, *, before: str | date) -> tuple[str | None, dict[str, Any] | None]:
        """Plantilla guardada más reciente anterior a ``before`` (aunque no sea ayer)."""
        stamp = _as_date(before)
        if stamp is None:
            return None, None
        data, _error = _read_json(self.snapshot_path)
        if not isinstance(data, Mapping) or not isinstance(data.get("days"), Mapping):
            return None, None
        days = data["days"]
        candidates = [str(key) for key in days if _as_date(key) is not None and str(key) < stamp.isoformat()]
        if not candidates:
            return None, None
        latest = max(candidates)
        snapshot = days.get(latest)
        return (latest, snapshot) if isinstance(snapshot, Mapping) else (None, None)

    # -- 6. Salida ----------------------------------------------------------

    def audit(
        self,
        squads: Any,
        activity: Any,
        *,
        snapshot_ayer: Any = None,
        snapshot_hoy: Any = None,
        now: datetime | None = None,
        observed_on: str | date | None = None,
        persist: bool | None = None,
    ) -> dict[str, Any]:
        """Reconstruye la caja de cada equipo y devuelve el documento completo.

        ``observed_on`` es la fecha a la que corresponden las cláusulas de la
        foto. Los anuncios se devengan hasta ``now`` (el juego paga cada día
        real), pero la foto de cláusulas se guarda con su propio día: si sirve
        una foto vieja, no se marca como si fuera de hoy.
        """
        current = _aware(now)
        today = current.astimezone(_MADRID).date()
        observed = _as_date(observed_on) if observed_on is not None else today
        if observed is None:
            observed = today
        roster = _roster(squads)
        events = parse_activities(activity)
        bound = _bind_teams(events, roster)

        # Nacimiento real de la liga y de cada equipo: el alta (tipo 9) fecha el
        # primer día en que se pudo cobrar el vídeo. Sin alta, manda el ``.env``.
        join_days = _join_days(bound)
        league_birth, birth_source = _league_birth(bound, join_days)
        season_start = league_birth or self.league_start_date
        no_score_reasons = _no_score_reasons(bound)
        negative_days = _balance_floor_days(bound)

        per_team_initial, shared_initial, initial_source = self._resolve_initial(bound, roster)
        flows, _initial, ignored, kinds = _aggregate(bound)
        acquisitions = _acquisition_index(bound)

        warnings: list[str] = []
        if not events:
            warnings.append(
                "Sin eventos de actividad: la caja es presupuesto más anuncios, sin ingresos ni gastos."
            )
        if league_birth is not None and league_birth != self.league_start_date:
            direction = "posterior" if league_birth > self.league_start_date else "anterior"
            warnings.append(
                f"El arranque real ({league_birth.isoformat()}, según {birth_source}) es {direction} al "
                f"configurado ({self.league_start_date.isoformat()}): los anuncios se devengan desde el real."
            )

        days = _days_elapsed(season_start, today, include_start=self.include_start_day)
        ad_total = days * self.daily_ad_revenue

        retro_by_team: dict[str, list[dict[str, Any]]] = {}
        missing_bases: dict[str, int] = {}
        without_clauses: dict[str, int] = {}
        for squad in roster:
            team_id = squad.get("team_id")
            if not isinstance(team_id, str) or not team_id:
                continue
            entries, missing, no_clause = self._audit_squad(squad, acquisitions)
            retro_by_team[team_id] = entries
            missing_bases[team_id] = missing
            without_clauses[team_id] = no_clause

        do_persist = self.persist if persist is None else persist
        previous_day: str | None = None
        if snapshot_ayer is not None or snapshot_hoy is not None:
            diff = self.calculate_daily_diff(
                snapshot_ayer,
                snapshot_hoy if snapshot_hoy is not None else squads,
                now=current,
                persist=do_persist,
                from_day=None,
                day=observed,
            )
        else:
            previous_day, previous = self.load_clause_snapshot(before=observed)
            if previous is not None:
                diff = self.calculate_daily_diff(
                    previous,
                    squads,
                    now=current,
                    persist=do_persist,
                    from_day=previous_day,
                    day=observed,
                )
            else:
                diff = {
                    "ok": True,
                    "day": observed.isoformat(),
                    "from_day": None,
                    "changes": [],
                    "cost_by_team": {},
                    "total_cost_eur": 0,
                    "persisted": False,
                    "warnings": [],
                }
            if do_persist and observed <= today:
                # Se guarda la observación del día al que pertenece la foto.
                # La primera lectura de cada día manda: otra foto del mismo día
                # no la sobrescribe, y una foto de hoy nunca se fecha en el futuro.
                saved = self.save_clause_snapshot(squads, day=observed, now=current, keep_existing=True)
                if saved.get("ok") is False:
                    warnings.append(f"No se guardó la foto de cláusulas: {saved.get('error')}.")
        warnings.extend(diff.get("warnings") or [])

        log = self.load_hidden_expenses()
        if log.get("error"):
            warnings.append(log["error"])
        indexed_log: dict[tuple[str, str, str], dict[str, Any]] = {
            (row["team_id"], row["player_id"], row["day"]): row for row in log["entries"]
        }
        for row in diff.get("changes") or []:
            _merge_expense_entries(indexed_log, row)
        if previous_day is None and diff.get("from_day"):
            previous_day = diff["from_day"]

        adjustments, adjustment_warnings = self.load_adjustments()
        warnings.extend(adjustment_warnings)

        present: dict[str, set[str]] = {
            squad["team_id"]: {
                view["player_id"]
                for view in (
                    _player_view(player)
                    for player in (squad.get("players") or [])
                    if isinstance(player, Mapping)
                )
                if isinstance(view["player_id"], str)
            }
            for squad in roster
            if isinstance(squad.get("team_id"), str)
        }

        team_ids: list[str] = []
        for team_id in [
            *(squad.get("team_id") for squad in roster),
            *flows.keys(),
            *per_team_initial.keys(),
            *adjustments.keys(),
            *(row["team_id"] for row in indexed_log.values()),
        ]:
            if isinstance(team_id, str) and team_id and team_id not in team_ids:
                team_ids.append(team_id)

        squad_by_team = {
            squad["team_id"]: squad
            for squad in roster
            if isinstance(squad.get("team_id"), str) and squad.get("team_id")
        }

        teams: dict[str, dict[str, Any]] = {}
        contexts: dict[str, dict[str, Any]] = {}
        for team_id in team_ids:
            squad = squad_by_team.get(team_id) or {}
            anchor = self._anchor_for(adjustments, team_id, today)
            team_flows = flows.get(team_id) or {
                "premiums": 0,
                "sales": 0,
                "purchases": 0,
                "clauses": 0,
                "events": 0,
            }
            initial = per_team_initial.get(team_id, shared_initial)
            # El alta del equipo recorta su ventana de anuncios: nadie cobra el
            # vídeo antes de entrar en la liga.
            team_start = max(season_start, join_days.get(team_id, season_start))

            if anchor is None:
                hidden_cost, hidden_rows = self._hidden_for_period(
                    team_id=team_id,
                    retro=retro_by_team.get(team_id, []),
                    log=indexed_log,
                    present=present.get(team_id, set()),
                    anchor_day=None,
                )
                period_flows = team_flows
                period_days = _days_elapsed(team_start, today, include_start=self.include_start_day)
                base_cash = initial
                floor_ad, lowest = _balance_floor(
                    _team_events(bound, team_id),
                    initial=initial,
                    revenue=self.daily_ad_revenue,
                    excused_days=negative_days.get(team_id, set()),
                )
            else:
                anchor_day, entry = anchor
                after_flows, _after_initial, _ignored, _kinds = _aggregate(bound, after=anchor_day)
                period_flows = after_flows.get(team_id) or {
                    "premiums": 0,
                    "sales": 0,
                    "purchases": 0,
                    "clauses": 0,
                    "events": 0,
                }
                period_days = self._ad_days(today, since=_as_date(anchor_day), skip_first=True)
                base_cash = int(entry["cash_override"])
                hidden_cost, hidden_rows = self._hidden_for_period(
                    team_id=team_id,
                    retro=retro_by_team.get(team_id, []),
                    log=indexed_log,
                    present=present.get(team_id, set()),
                    anchor_day=anchor_day,
                )
                floor_ad, lowest = _balance_floor(
                    _team_events(bound, team_id),
                    initial=base_cash,
                    revenue=self.daily_ad_revenue,
                    after=anchor_day,
                    excused_days=negative_days.get(team_id, set()),
                )

            max_ad = max(0, period_days) * self.daily_ad_revenue
            # Suelo: los anuncios que el libro obliga a haber cobrado. Si no
            # llega, la caja reconstruida queda por debajo del gasto real.
            floor_ad = min(max(0, floor_ad), max_ad)
            pure_cash = (
                base_cash
                + period_flows["premiums"]
                + period_flows["sales"]
                - period_flows["purchases"]
                - period_flows["clauses"]
                - hidden_cost
            )
            # Lo mismo, pero solo con asientos documentados (actividad). El
            # gasto oculto retroactivo es una estimación: sirve para apretar la
            # cota, no para calibrar el vídeo propio, donde sería circular.
            documented_cash = (
                base_cash
                + period_flows["premiums"]
                + period_flows["sales"]
                - period_flows["purchases"]
                - period_flows["clauses"]
            )
            contexts[team_id] = {
                "squad": squad,
                "anchor": anchor,
                "period_flows": period_flows,
                "period_days": period_days,
                "base_cash": base_cash,
                "hidden_cost": hidden_cost,
                "hidden_rows": hidden_rows,
                "pure_cash": pure_cash,
                "documented_cash": documented_cash,
                "max_ad": max_ad,
                "floor_ad": floor_ad,
                "lowest_balance": lowest,
                "team_start": team_start,
            }

        # Tasa propia de vídeo: la única caja verificable es la del mánager.
        # Con ella se estima el punto medio de los rivales en vez de suponer
        # que todos ven el anuncio (cota alta) o que ninguno (cota baja).
        own_rate, own_note = self._calibrate_own_rate(contexts, observed=observed, today=today)
        if own_note:
            warnings.append(own_note)

        for team_id in team_ids:
            ctx = contexts[team_id]
            squad = ctx["squad"]
            anchor = ctx["anchor"]
            period_flows = ctx["period_flows"]
            period_days = ctx["period_days"]
            base_cash = ctx["base_cash"]
            hidden_cost = ctx["hidden_cost"]
            hidden_rows = ctx["hidden_rows"]
            pure_cash = ctx["pure_cash"]
            max_ad = ctx["max_ad"]
            floor_ad = ctx["floor_ad"]
            lowest = ctx["lowest_balance"]

            period_ad = max_ad
            net = (
                period_flows["premiums"]
                + period_flows["sales"]
                - period_flows["purchases"]
                - period_flows["clauses"]
                + period_ad
                - hidden_cost
            )
            cash = base_cash + net
            # La banda es exactamente la ventana de publicidad: el mismo libro
            # (con el gasto oculto ya restado) sin vídeos, con los vídeos que el
            # historial obliga y con todos los vídeos posibles. Así el ancho
            # mide solo lo que no se puede saber, no la incertidumbre del gasto.
            cash_floor = pure_cash + floor_ad
            cash_expected = pure_cash + int(round(own_rate * max_ad)) if own_rate is not None else cash
            cash_expected = min(max(cash_expected, cash_floor), cash)
            debt = self.debt_limits.get(team_id, self.debt_limit_eur)
            observed_cash = squad.get("cash") if isinstance(squad.get("cash"), int) else None
            reconciliation = None
            risk_adjusted_cash = cash
            if observed_cash is not None:
                reconciliation = {
                    "observed_cash_eur": observed_cash,
                    # El saldo de la API es de la foto. Desde entonces pudo
                    # entrar publicidad: ese devengo ensancha el margen con el
                    # que se aprieta la cota, no la cota calculada.
                    **cash_control_thermometer(
                        cash,
                        observed_cash,
                        tau=self.thermometer_tau,
                        band=self.arbitrage_band,
                        floor_eur=self.uncertainty_floor_eur,
                        accrual_eur=self._ad_accrual_since(observed, today),
                    ),
                }
                risk_adjusted_cash = reconciliation["tight_ceiling_eur"]
                if reconciliation["gap_eur"] < 0:
                    warnings.append(
                        f"{team_id}: la caja calculada queda "
                        f"{abs(reconciliation['gap_eur']):,} € por debajo de la observada.".replace(",", ".")
                    )
                if reconciliation["arbitrage_eur"] > 0:
                    # La cota no se infla para tapar el hueco: se avisa de que
                    # hay dinero que los libros no explican y de cuánto es.
                    warnings.append(
                        f"{team_id}: {reconciliation['arbitrage_eur']:,} € de la caja observada quedan "
                        "fuera de los libros; revisa el historial antes de fiarte de la cota.".replace(",", ".")
                    )
            # La cota nunca baja del suelo probado: por debajo está el gasto
            # que el propio historial demuestra.
            risk_adjusted_cash = max(risk_adjusted_cash, cash_floor)

            confidence = self._confidence(squad, events, missing_bases.get(team_id, 0), without_clauses.get(team_id, 0))
            ad_bounds = {
                "days": period_days,
                "max_ad_eur": max_ad,
                "min_ad_eur": floor_ad,
                "expected_ad_eur": int(round(own_rate * max_ad)) if own_rate is not None else max_ad,
                "own_rate_pct": round(own_rate * 100, 1) if own_rate is not None else None,
                "forced_by_balance": floor_ad > 0,
                "lowest_book_balance_eur": lowest,
                "no_score_reasons": sorted(no_score_reasons.get(team_id, set())),
                "team_start_day": (
                    contexts[team_id]["team_start"].isoformat()
                    if contexts[team_id]["team_start"] != season_start
                    else None
                ),
            }

            teams[team_id] = {
                "team_id": team_id,
                "manager_name": squad.get("manager_name"),
                "fantasy_team_name": squad.get("fantasy_team_name"),
                "is_self": squad.get("is_self") is True,
                "rank": squad.get("rank") if isinstance(squad.get("rank"), int) else None,
                "calculated_cash": int(cash),
                "cash_floor_eur": int(cash_floor),
                "cash_expected_eur": int(cash_expected),
                "cash_band_eur": int(cash - cash_floor),
                "max_bid_limit": int(max(0, cash + debt)),
                "floor_bid_limit": int(max(0, cash_floor + debt)),
                "expected_bid_limit": int(max(0, cash_expected + debt)),
                "risk_adjusted_cash": int(risk_adjusted_cash),
                "risk_adjusted_bid_limit": int(max(0, risk_adjusted_cash + debt)),
                "debt_limit_eur": debt,
                "cash_is_upper_bound": anchor is None,
                "hidden_expenses_eur": int(hidden_cost),
                "detected_hidden_expenses": hidden_rows,
                "ad_bounds": ad_bounds,
                "confidence": confidence,
                "players": len(squad.get("players") or []),
                "breakdown": {
                    "initial_budget_eur": base_cash,
                    "premiums_eur": period_flows["premiums"],
                    "sales_eur": period_flows["sales"],
                    "purchases_eur": period_flows["purchases"],
                    "clauses_eur": period_flows["clauses"],
                    "ad_revenue_eur": period_ad,
                    "ad_days": period_days,
                    "cash_without_ads_eur": int(pure_cash),
                    "clause_raises_eur": -int(hidden_cost),
                    "period": "post_ancla" if anchor is not None else "temporada",
                    "anchor_day": anchor[0] if anchor else None,
                    "anchor_reason": anchor[1].get("reason") if anchor else None,
                },
                "flows": {
                    "net_eur": int(net),
                    "event_count": period_flows["events"],
                },
                "reconciliation": reconciliation,
                "squad_error": squad.get("error"),
                "missing_clause_base": missing_bases.get(team_id, 0),
                "players_without_clause": without_clauses.get(team_id, 0),
            }

        income = sum(
            row["premiums"] + row["sales"] for row in flows.values()
        )
        expense = sum(
            row["purchases"] + row["clauses"] for row in flows.values()
        )
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "command": COMMAND,
            "league_id": _league_id(squads),
            "generated_at": _iso(current),
            "config": {
                "initial_budget_eur": shared_initial,
                "initial_budget_source": initial_source,
                "starting_clause_multiplier": self.starting_clause_multiplier,
                "clause_increase_multiplier": self.clause_increase_multiplier,
                "daily_ad_revenue_eur": self.daily_ad_revenue,
                "league_start_date": self.league_start_date.isoformat(),
                "league_start_source": birth_source or "configuracion",
                "season_start_date": season_start.isoformat(),
                "own_ad_rate_pct": round(own_rate * 100, 1) if own_rate is not None else None,
                "debt_limit_eur": self.debt_limit_eur,
                "thermometer_tau": self.thermometer_tau,
                "arbitrage_band": self.arbitrage_band,
                "uncertainty_floor_eur": self.uncertainty_floor_eur,
            },
            "days_elapsed": days,
            "ad_revenue_per_team_eur": ad_total,
            "activity": {
                "ok": bool(events),
                "event_count": len(events),
                "income_eur": income,
                "expense_eur": expense,
                "ignored_events": ignored,
                "kinds": kinds,
            },
            "adjustments": {
                "path": str(self.adjustments_path),
                "teams_with_anchor": sorted(adjustments),
            },
            "hidden_log": {
                "path": log["path"],
                "entries": len(log["entries"]),
                "total_eur": log["total_eur"],
                "error": log["error"],
            },
            "daily_diff": {
                "day": diff.get("day"),
                "from_day": diff.get("from_day"),
                "change_count": len(diff.get("changes") or []),
                "total_cost_eur": diff.get("total_cost_eur") or 0,
                "persisted": diff.get("persisted") is True,
            },
            "teams": teams,
            "warnings": warnings,
        }

    @staticmethod
    def _confidence(
        squad: Mapping[str, Any],
        events: list[dict[str, Any]],
        missing_base: int,
        without_clause: int,
    ) -> str:
        """Cuánto pesa la cota: sin plantilla o sin historial, la caja es solo teoría."""
        if squad.get("error") or not squad.get("players"):
            return "low"
        if missing_base or without_clause:
            return "medium"
        if not events:
            return "medium"
        return "high"

    def _hidden_for_period(
        self,
        *,
        team_id: str,
        retro: list[dict[str, Any]],
        log: Mapping[tuple[str, str, str], dict[str, Any]],
        present: set[str],
        anchor_day: str | None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Gasto oculto imputable al periodo, sin doble conteo.

        Las dos vías miran el mismo dinero desde ángulos distintos: el diff
        diario **mide** un salto de cláusula y el retroactivo **estima** el
        total desde la base. Por jugador se cobra una sola vez y se toma el
        mayor de los dos, porque ambos son lecturas del mismo gasto y perder
        una fuga es peor que quedarse corto al auditarla.

        Con ancla solo cuenta el diario fechado después del asiento: el
        retroactivo no se puede fechar y el asiento ya lo resume.
        """
        if anchor_day is not None:
            rows = [
                dict(entry)
                for entry in log.values()
                if entry["team_id"] == team_id and entry["day"] > anchor_day
            ]
            return _dedupe_expenses(rows)

        measured: dict[str, list[dict[str, Any]]] = {}
        ghosts: list[dict[str, Any]] = []
        for entry in log.values():
            if entry["team_id"] != team_id:
                continue
            if entry["player_id"] in present:
                measured.setdefault(entry["player_id"], []).append(dict(entry))
            else:
                ghosts.append(dict(entry))

        rows = list(ghosts)
        for player_id, entries in measured.items():
            total = sum(entry["cost_eur"] for entry in entries)
            estimate = next(
                (row for row in retro if row["player_id"] == player_id),
                None,
            )
            if estimate is None or total >= estimate["cost_eur"]:
                # Cada día medido es un salto distinto: se suman todos.
                rows.extend(entries)
            else:
                rows.append(estimate)
        covered = {row["player_id"] for row in rows}
        rows.extend(row for row in retro if row["player_id"] not in covered)
        return _dedupe_expenses(rows)


def _dedupe_expenses(rows: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """Un asiento por jugador y día; el importe mayor gana."""
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["team_id"], row["player_id"], str(row.get("day") or "retro"))
        current = deduped.get(key)
        if current is None or row["cost_eur"] > current["cost_eur"]:
            deduped[key] = row
    total = sum(row["cost_eur"] for row in deduped.values())
    ordered = sorted(
        deduped.values(),
        key=lambda row: (-row["cost_eur"], str(row.get("name") or row["player_id"])),
    )
    return total, ordered


def _clean_expense_entry(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    team_id = row.get("team_id")
    player_id = row.get("player_id")
    day = row.get("day")
    cost = _as_int(row.get("cost_eur"))
    if not isinstance(team_id, str) or not team_id:
        return None
    if not isinstance(player_id, str) or not player_id:
        return None
    if not isinstance(day, str) or _as_date(day) is None or cost is None:
        return None
    return {
        "team_id": team_id,
        "player_id": player_id,
        "name": row.get("name") if isinstance(row.get("name"), str) else player_id,
        "position": row.get("position") if isinstance(row.get("position"), str) else None,
        "clause_before_eur": _as_int(row.get("clause_before_eur")),
        "clause_after_eur": _as_int(row.get("clause_after_eur")),
        "increase_eur": _as_int(row.get("increase_eur")),
        "cost_eur": max(0, cost),
        "source": "diario",
        "basis": "snapshot",
        "classification": "REPARTO",
        "day": day,
        "from_day": row.get("from_day") if isinstance(row.get("from_day"), str) else None,
        "detected_at": row.get("detected_at") if isinstance(row.get("detected_at"), str) else None,
    }


def _league_id(squads: Any) -> str | None:
    if isinstance(squads, Mapping):
        value = squads.get("league_id")
        if isinstance(value, str) and value:
            return value
    return None


def _read_json(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: {exc}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


# --- API pública ------------------------------------------------------------


def events_from_ledgers(ledgers: Any) -> dict[str, Any]:
    """Historial reconstruido desde ``needs.ledgers`` (sin volver a paginar)."""
    events: list[dict[str, Any]] = []
    for ledger in ledgers if isinstance(ledgers, list) else []:
        if not isinstance(ledger, Mapping):
            continue
        team_id = ledger.get("team_id")
        if not isinstance(team_id, str) or not team_id:
            continue
        for event in ledger.get("events") or []:
            if not isinstance(event, Mapping):
                continue
            row = dict(event)
            row["team_id"] = team_id
            row["manager_id"] = None
            events.append(row)
    return {"ok": bool(events), "source": "ledgers", "events": events}


def get_financial_intel(
    squads: Any,
    activity: Any,
    *,
    auditor: LedgerAuditor | None = None,
    snapshot_ayer: Any = None,
    snapshot_hoy: Any = None,
    now: datetime | None = None,
    observed_on: str | date | None = None,
    persist: bool | None = None,
) -> dict[str, Any]:
    """Orquesta la auditoría y devuelve un diccionario por equipo.

    Cada entrada de ``teams`` trae ``calculated_cash`` (cota superior de caja),
    ``max_bid_limit`` (poder de subasta, con endeudamiento si está configurado)
    y ``detected_hidden_expenses`` (subidas de cláusula cobradas al rival).
    """
    engine = auditor or LedgerAuditor()
    return engine.audit(
        squads,
        activity,
        snapshot_ayer=snapshot_ayer,
        snapshot_hoy=snapshot_hoy,
        now=now,
        observed_on=observed_on,
        persist=persist,
    )


def build_rival_intel_command(
    client: Any,
    *,
    league: str | None,
    fresh: bool,
    auditor: LedgerAuditor | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Adaptador de red: plantillas + historial completos → auditoría."""
    from toolbox.bidding import load_activity

    squads = client.squads_document(league, fresh=fresh)
    league_id = squads.get("league_id") if isinstance(squads, Mapping) else None
    activity = load_activity(client, league_id if isinstance(league_id, str) else None, fresh=fresh)
    document = get_financial_intel(squads, activity, auditor=auditor, now=now)
    if isinstance(squads, Mapping):
        document["league_name"] = squads.get("league_name")
    document["activity"]["source_url"] = activity.get("source_url") if isinstance(activity, Mapping) else None
    document["activity"]["ok"] = bool(activity.get("ok")) if isinstance(activity, Mapping) else False
    return document

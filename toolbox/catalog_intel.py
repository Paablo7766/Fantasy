"""Motor cuantitativo del catálogo global de LaLiga Fantasy.

Este módulo mira el catálogo entero (588 jugadores en liga) como si fuera un
libro de activos, no como una lista de nombres. De ahí salen las tres lecturas
que el mercado no publica:

* **Volatilidad y consistencia.** La media de puntos miente: un jugador de 6
  puntos de media con tres ceros y un 20 no es el mismo activo que uno de 6
  clavados. Se calcula mediana, desviación típica y tasa de *blanks* para
  separar «activos refugio» (suelo alto, varianza baja) de «activos de riesgo»
  (techo alto, varianza alta y muchos ceros).
* **Arbitraje de lesiones.** Un jugador lesionado cuyo valor cae cada vez menos
  está tocando suelo: el mercado ya ha descontado la lesión. Se mide la
  desaceleración de la caída con el histórico diario de precios, no con una
  impresión.
* **Agentes libres e inflación.** Cruzando el catálogo con las plantillas sale
  quién está disponible de verdad. Si el talento libre es escaso, la liga va a
  sobrepujar por lo poco que quede: eso es la «Alta Inflación Esperada».

Nada de aquí sale a la red. Todo se resuelve con el catálogo normalizado y el
histórico de precios que ya están en `.cache/`.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping, Sequence

# Umbrales de la clasificación cuantitativa. Son deliberadamente explícitos y
# no configurables por entorno: un cambio aquí altera qué jugadores se compran,
# así que debe verse en el diff, no en un `.env`.
MEDIAN_FLOOR = 5.0
"""Mediana mínima para considerar un jugador «top» en su puesto."""

REFUGE_MIN_MEDIAN = 5.0
REFUGE_MAX_STDEV = 3.0
REFUGE_MAX_BLANK_RATE = 0.2

RISK_MIN_STDEV = 6.0
RISK_MIN_BLANK_RATE = 0.35
RISK_MIN_CEILING = 10.0

MIN_SAMPLE_WEEKS = 3
"""Menos jornadas que esto no permiten hablar de volatilidad: es ruido."""

# Inflación: se mira el talento libre de nivel top y su liquidez total.
SCARCITY_MAX_TOP_FREE = 5
"""Con cinco o menos top libres, la liga se pelea por muy poco."""

INFLATION_MAX_LIQUIDITY_EUR = 60_000_000
"""Liquidez agregada por debajo de esto: hay dinero para todos y no hay guerra."""

DISTRESSED_STATUSES = frozenset({"injured", "suspended"})

# Un jugador en el suelo de su precio no puede seguir cayendo al mismo ritmo.
# La caída se compara con la del día anterior: si la segunda es menor en una
# fracción de esta tolerancia, la caída está desacelerando.
DECELERATION_TOLERANCE = 0.75

_EPSILON = 1e-9


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def blank_rate(series: Sequence[float]) -> float:
    """Fracción de jornadas con cero puntos o menos sobre las jugadas."""
    if not series:
        return 0.0
    blanks = sum(1 for value in series if value <= 0)
    return round(blanks / len(series), 4)


def quant_profile(series: Sequence[float]) -> dict[str, Any]:
    """Perfil estadístico de una serie de puntos de jornada.

    Devuelve ``None``-like (todo a ``None``) si no hay muestra suficiente: es
    preferible no clasificar a clasificar con dos jornadas.
    """
    values = [float(value) for value in series if value is not None]
    sample = len(values)
    if sample == 0:
        return {
            "sample": 0,
            "median": None,
            "mean": None,
            "stdev": None,
            "ceiling": None,
            "floor": None,
            "blank_rate": None,
            "consistency": None,
        }
    median = round(statistics.median(values), 4)
    mean = round(statistics.fmean(values), 4)
    # ``stdev`` con una sola muestra no está definida; se reporta ``None`` en
    # vez de 0.0 para no vender «varianza cero» con un único dato.
    stdev = round(statistics.stdev(values), 4) if sample > 1 else None
    return {
        "sample": sample,
        "median": median,
        "mean": mean,
        "stdev": stdev,
        "ceiling": round(max(values), 4),
        "floor": round(min(values), 4),
        "blank_rate": blank_rate(values),
        # Cuántos puntos de media se ganan por unidad de riesgo. Es la lectura
        # que ordena refugio frente a lotería cuando la mediana empata.
        "consistency": round(median / stdev, 4) if stdev and stdev > _EPSILON else None,
    }


def classify_asset(profile: Mapping[str, Any]) -> str | None:
    """``refugio`` / ``riesgo`` / ``equilibrado`` para un perfil ya calculado."""
    median = _as_float(profile.get("median"))
    stdev = _as_float(profile.get("stdev"))
    blanks = _as_float(profile.get("blank_rate"))
    ceiling = _as_float(profile.get("ceiling"))
    sample = _as_int(profile.get("sample")) or 0
    if median is None or sample < MIN_SAMPLE_WEEKS:
        return None
    if (
        median >= REFUGE_MIN_MEDIAN
        and stdev is not None
        and stdev <= REFUGE_MAX_STDEV
        and blanks is not None
        and blanks <= REFUGE_MAX_BLANK_RATE
    ):
        return "refugio"
    if (
        stdev is not None
        and stdev >= RISK_MIN_STDEV
        and blanks is not None
        and blanks >= RISK_MIN_BLANK_RATE
        and ceiling is not None
        and ceiling >= RISK_MIN_CEILING
    ):
        return "riesgo"
    return "equilibrado"


def price_deceleration(history: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """¿La caída de precio está frenando?

    ``history`` es el histórico diario del jugador, en orden ascendente de día,
    con ``market_value``. Se comparan los dos últimos descensos: si el de ayer
    fue más suave que el de anteayer, la caída desacelera. Un precio plano no
    es una oportunidad de suelo: es un precio que ya no baja porque nadie
    vende, y se marca aparte.
    """
    values: list[float] = []
    days: list[str] = []
    for row in history or []:
        if not isinstance(row, Mapping):
            continue
        value = _as_float(row.get("market_value"))
        if value is None:
            continue
        values.append(value)
        days.append(str(row.get("day") or ""))
    if len(values) < 3:
        return None

    first_delta = values[-2] - values[-3]
    last_delta = values[-1] - values[-2]
    if first_delta >= 0 or last_delta >= 0:
        # Solo interesa una caída sostenida. Un repunte rompe la tesis de suelo.
        return {
            "falling": False,
            "decelerating": False,
            "first_delta": round(first_delta),
            "last_delta": round(last_delta),
            "recovery": last_delta > 0,
            "days": days[-3:],
        }

    # Ambas caídas negativas. «Desacelera» = la última cae menos en valor
    # absoluto que la anterior, con margen para no confundir ruido con giro.
    decelerating = abs(last_delta) <= abs(first_delta) * DECELERATION_TOLERANCE
    return {
        "falling": True,
        "decelerating": bool(decelerating),
        "first_delta": round(first_delta),
        "last_delta": round(last_delta),
        "recovery": False,
        "days": days[-3:],
    }


def owned_player_ids(squads: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None) -> dict[str, str]:
    """``player_id`` → ``team_id`` del dueño, a partir del documento de plantillas.

    Acepta el documento completo (``{"squads": [...]}``) o la lista ya extraída.
    """
    if squads is None:
        return {}
    rows: Iterable[Any]
    if isinstance(squads, Mapping):
        candidate = squads.get("squads")
        rows = candidate if isinstance(candidate, list) else []
    elif isinstance(squads, Sequence) and not isinstance(squads, (str, bytes)):
        rows = squads
    else:
        return {}

    owners: dict[str, str] = {}
    for squad in rows:
        if not isinstance(squad, Mapping):
            continue
        team_id = _text(squad.get("team_id")) or ""
        for player in squad.get("players") or []:
            if not isinstance(player, Mapping):
                continue
            player_id = _text(player.get("player_id"))
            if player_id:
                owners[player_id] = team_id
    return owners


class MarketQuantAnalyzer:
    """Lee el catálogo como un libro de activos y expone sus ineficiencias."""

    def __init__(
        self,
        players: Sequence[Mapping[str, Any]],
        *,
        squads: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        price_history: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.players = [player for player in players if isinstance(player, Mapping)]
        self.owners = owned_player_ids(squads)
        # Sin plantillas (o con un documento vacío) no hay forma de saber quién
        # está libre: marcar a los 588 como libres sería un falso positivo que
        # inflaría la liquidez y escondería justo la escasez que este motor mide.
        self.has_squads = bool(self.owners)
        self.price_history = price_history or {}
        self._profiles: dict[str, dict[str, Any]] = {}
        for player in self.players:
            player_id = _text(player.get("player_id"))
            if not player_id:
                continue
            self._profiles[player_id] = quant_profile(self._series(player))

    # -- utilidades ------------------------------------------------------
    @staticmethod
    def _series(player: Mapping[str, Any]) -> list[float]:
        raw = player.get("week_points")
        if not isinstance(raw, list):
            return []
        return [float(value) for value in raw if isinstance(value, (int, float)) and not isinstance(value, bool)]

    @staticmethod
    def _label(player: Mapping[str, Any]) -> str | None:
        return _text(player.get("nickname")) or _text(player.get("name"))

    def profile_for(self, player: Mapping[str, Any]) -> dict[str, Any]:
        player_id = _text(player.get("player_id")) or ""
        return self._profiles.get(player_id) or quant_profile(self._series(player))

    def _row(self, player: Mapping[str, Any]) -> dict[str, Any]:
        profile = self.profile_for(player)
        player_id = _text(player.get("player_id"))
        history = self.price_history.get(player_id) if player_id else None
        free = bool(player_id) and self.has_squads and player_id not in self.owners
        return {
            "player_id": player_id,
            "name": self._label(player),
            "club": _text(player.get("club")),
            "club_short": _text(player.get("club_short")),
            "position": _text(player.get("position")),
            "player_status": _text(player.get("player_status")),
            "market_value": _as_int(player.get("market_value")),
            "image_url": _text(player.get("image_url")),
            "owner_team_id": self.owners.get(player_id) if player_id else None,
            "is_free_agent": free,
            **profile,
            "asset_class": classify_asset(profile),
            "price_trend": price_deceleration(history or []),
        }

    # -- 1. volatilidad y consistencia -----------------------------------
    def volatility_table(self) -> list[dict[str, Any]]:
        """Todos los jugadores con perfil, ordenados por mediana y consistencia."""
        rows = [self._row(player) for player in self.players]
        rows = [row for row in rows if row.get("sample")]
        rows.sort(
            key=lambda row: (
                -(row.get("median") or 0.0),
                -(row.get("consistency") or 0.0),
                str(row.get("name") or ""),
            )
        )
        return rows

    def refuge_assets(self, *, minimum_median: float | None = None) -> list[dict[str, Any]]:
        """Suelo alto y varianza baja: los que no se caen de la alineación."""
        floor = REFUGE_MIN_MEDIAN if minimum_median is None else minimum_median
        rows = [
            row
            for row in self.volatility_table()
            if row.get("asset_class") == "refugio" and (row.get("median") or 0.0) >= floor
        ]
        return rows

    def risk_assets(self) -> list[dict[str, Any]]:
        """Techo alto con muchos ceros: lotería, no inversión."""
        rows = [row for row in self.volatility_table() if row.get("asset_class") == "riesgo"]
        rows.sort(
            key=lambda row: (
                -(row.get("ceiling") or 0.0),
                -(row.get("stdev") or 0.0),
                str(row.get("name") or ""),
            )
        )
        return rows

    # -- 2. arbitraje de lesiones ---------------------------------------
    def distressed_assets(self) -> list[dict[str, Any]]:
        """Lesionados y sancionados cuya caída de precio ya está frenando.

        La tesis es de suelo: el mercado descontó la lesión cuando el precio
        caía rápido. Cuando la caída se aplana, el castigo está agotado y el
        jugador vuelve por debajo de su valor de equilibrio.
        """
        rows: list[dict[str, Any]] = []
        for player in self.players:
            status = (_text(player.get("player_status")) or "").lower()
            if status not in DISTRESSED_STATUSES:
                continue
            row = self._row(player)
            trend = row.get("price_trend")
            if not isinstance(trend, Mapping):
                # Sin histórico no se puede afirmar que esté en el suelo.
                continue
            if trend.get("decelerating") is not True:
                continue
            row["distress_kind"] = status
            row["floor_signal"] = "suelo"
            rows.append(row)
        rows.sort(
            key=lambda row: (
                -(row.get("median") or 0.0),
                -(row.get("market_value") or 0),
                str(row.get("name") or ""),
            )
        )
        return rows

    # -- 3. agentes libres ----------------------------------------------
    def free_agents(self, *, minimum_median: float | None = None) -> list[dict[str, Any]]:
        """Catálogo menos plantillas: quién se puede fichar sin cláusula.

        Sin el documento de plantillas devuelve lista vacía: no saber quién
        está fichado no es lo mismo que saber que nadie lo está.
        """
        if not self.has_squads:
            return []
        floor = 0.0 if minimum_median is None else minimum_median
        rows = [
            row
            for row in self.volatility_table()
            if row.get("is_free_agent") and (row.get("median") or 0.0) >= floor
        ]
        return rows

    def top_free_agents(self, *, minimum_median: float = MEDIAN_FLOOR) -> list[dict[str, Any]]:
        """Talento libre de nivel top: la materia prima de la subasta."""
        return self.free_agents(minimum_median=minimum_median)

    # -- 4. radar macroeconómico ----------------------------------------
    def inflation_radar(self, *, minimum_median: float = MEDIAN_FLOOR) -> dict[str, Any]:
        """Liquidez del talento libre top y veredicto de inflación esperada.

        La lectura es de escasez: si hay pocos tops libres y poco valor en
        ellos, cada puja relevante tendrá competencia y el precio de cierre
        subirá. En ese escenario conviene guardar liquidez para las subastas
        que de verdad mueven el once, no repartirla en refuerzos menores.
        """
        top = self.top_free_agents(minimum_median=minimum_median)
        liquidity = sum(int(row.get("market_value") or 0) for row in top)
        if not self.has_squads or not self.players:
            # Sin plantillas no se sabe quién está libre; sin catálogo no hay
            # nada que medir. Decirlo es mejor que inventar un «extrema» que
            # empujaría a comprar por pánico.
            return {
                "top_free_count": 0,
                "top_free_liquidity_eur": 0,
                "thresholds": {
                    "max_top_free": SCARCITY_MAX_TOP_FREE,
                    "max_liquidity_eur": INFLATION_MAX_LIQUIDITY_EUR,
                    "min_median": minimum_median,
                },
                "scarce": None,
                "level": "desconocida",
                "known": False,
                "flag": "Inflación sin medir",
                "recommendation": (
                    "Falta el documento de plantillas o el catálogo: no se puede saber qué talento "
                    "está libre. Carga ambos antes de decidir por escasez."
                ),
                "top_free": [],
            }
        scarce = len(top) <= SCARCITY_MAX_TOP_FREE or liquidity <= INFLATION_MAX_LIQUIDITY_EUR
        if not top:
            level = "extrema"
        elif scarce:
            level = "alta"
        else:
            level = "normal"
        return {
            "top_free_count": len(top),
            "top_free_liquidity_eur": liquidity,
            "thresholds": {
                "max_top_free": SCARCITY_MAX_TOP_FREE,
                "max_liquidity_eur": INFLATION_MAX_LIQUIDITY_EUR,
                "min_median": minimum_median,
            },
            "scarce": bool(scarce),
            "level": level,
            "known": True,
            "flag": "Alta Inflación Esperada" if scarce else "Inflación contenida",
            "recommendation": (
                "Guardar liquidez y concentrarla en las subastas clave: el talento libre "
                "escasea y se va a sobrepujar. Aceptar sobreprecio solo por un titular claro."
                if scarce
                else "Hay talento libre suficiente: se puede pujar con disciplina por valor, "
                "sin aceptar sobreprecios por escasez."
            ),
            "top_free": top,
        }

    # -- documento agregado ---------------------------------------------
    def report(self) -> dict[str, Any]:
        """Todo el análisis en un documento listo para el dashboard."""
        volatility = self.volatility_table()
        refuge = [row for row in volatility if row.get("asset_class") == "refugio"]
        risk = self.risk_assets()
        distressed = self.distressed_assets()
        free = [row for row in volatility if row.get("is_free_agent")]
        radar = self.inflation_radar()
        return {
            "counts": {
                "catalog": len(self.players),
                "profiled": len(volatility),
                "refuge": len(refuge),
                "risk": len(risk),
                "distressed": len(distressed),
                "free_agents": len(free),
                "owned": len(self.owners),
            },
            "inflation": {key: value for key, value in radar.items() if key != "top_free"},
            "refuge": refuge,
            "risk": risk,
            "distressed": distressed,
            "free_agents": free,
            "top_free": radar["top_free"],
        }

"""Huella de puja de cada rival: cola del importe, hora de sus clausulazos y ofertas humanas.

Solo lee lo que ya hay (compras de la actividad, libros de caja y anuncios del
mercado). No decide nada: lo enseña. Los tres hallazgos vienen de la liga real:
``floren romi``, ``Naviis10`` y ``pablooceballos`` ganan subastas 1-10 EUR por
encima de un numero redondo; cada rival clausula a su hora; y un anuncio con
``numberOfOffers`` >= 2 ya tiene a una persona pujando.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_MADRID = ZoneInfo("Europe/Madrid")

#: Un anuncio con tantas ofertas o mas tiene una persona real detras.
OFERTAS_HUMANAS_MIN = 2
ETIQUETA_OFERTA_HUMANA = "🔥 Oferta humana activa (numberOfOffers >= 2)"
#: Compras minimas para fiarse del estilo de cola.
MUESTRA_MIN_COLA = 3
#: Dos clausulazos separados por mas de esto son ventanas distintas.
HUECO_VENTANA_MIN = 90

ESTILO_PICA = "pica"
ESTILO_REDONDEA_100K = "redondea_100k"
ESTILO_REDONDEA_10K = "redondea_10k"
ESTILO_MIXTO = "mixto"
ETIQUETAS_COLA = {
    ESTILO_PICA: "Pica +1/+10 €",
    ESTILO_REDONDEA_100K: "Redondea a 100k",
    ESTILO_REDONDEA_10K: "Redondea a 10k",
    ESTILO_MIXTO: "Mixto",
}


def clase_de_cola(importe: int) -> str:
    """Como termina una puja: ``pica`` (1-10 EUR sobre un redondo), ``100k``, ``10k`` u ``otro``."""
    resto = importe % 10_000
    if resto == 0:
        return ESTILO_REDONDEA_100K if importe % 100_000 == 0 else ESTILO_REDONDEA_10K
    if resto <= 10 or resto >= 9_990:
        return ESTILO_PICA
    return ESTILO_MIXTO


def estilo_de_cola(importes: list[int]) -> dict[str, Any] | None:
    """Estilo dominante (mas de la mitad de sus compras) o ``None`` sin muestra."""
    validos = [i for i in importes if isinstance(i, int) and not isinstance(i, bool) and i > 0]
    if len(validos) < MUESTRA_MIN_COLA:
        return None
    conteo: dict[str, int] = {}
    for importe in validos:
        clase = clase_de_cola(importe)
        conteo[clase] = conteo.get(clase, 0) + 1
    dominante, n = max(conteo.items(), key=lambda par: par[1])
    estilo = dominante if n * 2 > len(validos) else ESTILO_MIXTO
    return {
        "estilo": estilo,
        "etiqueta": ETIQUETAS_COLA[estilo],
        "n_compras": len(validos),
        "conteo": conteo,
    }


def _minutos(at: Any) -> int | None:
    if not isinstance(at, str) or not at:
        return None
    texto = at.strip()
    if texto.endswith("Z"):
        texto = f"{texto[:-1]}+00:00"
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=_MADRID)
    local = momento.astimezone(_MADRID)
    return local.hour * 60 + local.minute


def _hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def ventanas_clausulazo(eventos: list[dict[str, Any]]) -> list[str]:
    """Horas (Madrid) de sus clausulazos pagados: ``"09:30"`` o ``"10:15-11:20"`` por ventana."""
    horas = sorted(
        m for m in (_minutos(e.get("at")) for e in eventos if isinstance(e, dict) and e.get("kind") == "clause") if m is not None
    )
    if not horas:
        return []
    grupos: list[list[int]] = [[horas[0]]]
    for minuto in horas[1:]:
        if minuto - grupos[-1][-1] > HUECO_VENTANA_MIN:
            grupos.append([minuto])
        else:
            grupos[-1].append(minuto)
    return [
        _hhmm(grupo[0]) if grupo[-1] - grupo[0] < 5 else f"{_hhmm(grupo[0])}-{_hhmm(grupo[-1])}"
        for grupo in grupos
    ]


def ofertas_humanas(listings: list[dict[str, Any]], team_id: str) -> list[dict[str, Any]]:
    """Anuncios de este rival con dos o mas ofertas: ya hay alguien pujando."""
    salida: list[dict[str, Any]] = []
    for anuncio in listings:
        if not isinstance(anuncio, dict) or str(anuncio.get("seller_team_id")) != str(team_id):
            continue
        ofertas = anuncio.get("offer_count")
        if isinstance(ofertas, bool) or not isinstance(ofertas, int) or ofertas < OFERTAS_HUMANAS_MIN:
            continue
        salida.append(
            {
                "market_id": anuncio.get("market_id"),
                "player_id": anuncio.get("player_id"),
                "nombre": anuncio.get("nickname") or anuncio.get("name"),
                "offer_count": ofertas,
                "sale_price": anuncio.get("sale_price") if isinstance(anuncio.get("sale_price"), int) else None,
                "etiqueta": ETIQUETA_OFERTA_HUMANA,
            }
        )
    return salida


def huella_de_rival(
    team_id: str,
    *,
    compras: list[dict[str, Any]],
    eventos: list[dict[str, Any]],
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Todo lo anterior para un rival."""
    importes = [c.get("amount_eur") for c in compras if isinstance(c, dict) and str(c.get("team_id")) == str(team_id)]
    return {
        "cola": estilo_de_cola([i for i in importes if isinstance(i, int)]),
        "ventanas_clausulazo": ventanas_clausulazo(eventos),
        "ofertas_humanas": ofertas_humanas(listings, team_id),
    }

"""La probabilidad de ganar una puja se calcula con caja + crédito del 20 %, no solo con la caja."""

from __future__ import annotations

from toolbox.bid_war import plan_market_auction_bid


def _puja(**extra):
    listing = {"player_id": "correia", "sale_price": 8_740_000, "market_value": 8_740_000, "position": "DEL"}
    base = dict(
        to_lead=None,
        leading=None,
        own_max=11_000_000,
        af_max=None,
        af_usable=False,
        ideal=9_600_000,
        cash=250_000,
        snipe_status=None,
        position="DEL",
        expected_pts=8.0,
        points_delta_xi=3.5,
        populates_empty_slot=False,
        free_tier_peers_count=0,
        rivals=[{"manager": "floren romi", "cash_eur": 80_000_000, "posiciones_flojas": ["DEL"]}],
        rival_profiles=None,
        own_team_id="yo",
        history=None,
    )
    base.update(extra)
    return plan_market_auction_bid(listing, {}, **base)


def test_solo_con_caja_la_puja_es_imposible():
    solo_caja = _puja()
    assert (solo_caja.get("smart_bid_success_pct") or 0) <= 20
    assert (solo_caja.get("smart_bid_eur") or 0) <= 250_000


def test_con_credito_la_puja_y_su_probabilidad_son_reales():
    con_credito = _puja(bid_power=250_000 + 49_500_000)
    assert (con_credito.get("smart_bid_eur") or 0) >= 8_740_000
    assert (con_credito.get("smart_bid_success_pct") or 0) > (_puja().get("smart_bid_success_pct") or 0)

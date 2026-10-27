import assert from "node:assert/strict";
import { buildRecommendations, weekdayStamp } from "./recommendations.ts";
import type { RecommendationInput } from "./recommendations.ts";

assert.equal(weekdayStamp("2026-10-30"), "vie 30/10");
assert.equal(weekdayStamp("2026-11-01", "14:08"), "dom 1/11 a las 14:08");

const input: RecommendationInput = {
  plan: {
    cash_eur: 23_700_000,
    clause_market_close: { local_date: "2026-10-30", local_time: "21:00" },
    lineup: {
      saved_points: 31.9,
      expected_points: 40.8,
      points_delta: 8.2,
      leaves: [{ player_id: "moleiro", nickname: "Moleiro", position: "DEL", expected_points: 3.4 }],
      xi: [{ player_id: "castrin", nickname: "A. Castrín", position: "DEF" }],
    },
    actions: [
      {
        kind: "pujar",
        player_id: "castrin",
        nickname: "A. Castrín",
        position: "DEF",
        amount_eur: 11_190_000,
        when: "ahora",
        eligible: true,
        points_delta: 1.4,
      },
    ],
    clock: [
      {
        kind: "desbloqueo",
        player_id: "roman",
        nickname: "Leo Román",
        is_self: false,
        amount_eur: 32_100_000,
        local_date: "2026-11-01",
        local_time: "14:08",
        manager_name: "Sausor10",
      },
    ],
    protect: [
      {
        player_id: "lejeune",
        nickname: "Lejeune",
        buyout_clause_eur: 14_700_000,
        threat_count: 2,
        top_rival: { manager_name: "Navis10" },
      },
    ],
  },
  optimize: {
    saved_lineup: {
      xi: [
        { player_id: "moleiro", nickname: "Moleiro", position: "DEL", expected_points: 3.4, market_value: 90_400_000, price_delta: 120_000 },
        { player_id: "militao", nickname: "E. Militão", position: "DEF", expected_points: 2, market_value: 7_160_000, price_delta: 40_000 },
        { player_id: "lejeune", nickname: "Lejeune", position: "DEF", expected_points: 1.5, market_value: 16_000_000 },
      ],
    },
    xi: [{ player_id: "castrin", nickname: "A. Castrín", position: "DEF", market_value: 10_690_000 }],
    benched: [],
  },
  trends: {
    market_decisions: [
      {
        player_id: "castrin",
        nickname: "A. Castrín",
        position: "DEF",
        decision: "PUJAR",
        points_delta: 1.4,
        market_value: 10_690_000,
        replaces: { player_id: "moleiro", name: "Moleiro", points: 3.4 },
      },
      {
        player_id: "roman",
        nickname: "Leo Román",
        position: "POR",
        decision: "ESPERAR",
        points_delta: 6.8,
        jornada_ev: 7.4,
        market_value: 32_100_000,
        buyout_clause: 32_100_000,
        sale_price: 40_000_000,
      },
      {
        player_id: "gk2",
        nickname: "Audero",
        position: "POR",
        decision: "ESPERAR",
        points_delta: 2.5,
        jornada_ev: 6.1,
        sale_price: 7_830_000,
      },
      {
        player_id: "lejeune",
        nickname: "Lejeune",
        position: "DEF",
        offer_source: "liga",
        leading_bid: 14_700_000,
        market_value: 16_000_000,
        jornada_ev: 1.5,
      },
    ],
  },
  squads: {
    self: { team_id: "me", cash_eur: 23_700_000, players: [] },
    sell: [{ player_id: "turrientes", nickname: "Turrientes", position: "MC", market_value: 3_240_000, price_delta: -10_000 }],
  },
};

const board = buildRecommendations(input);

assert.equal(board.hoy.some((card) => card.title === "Puja por A. Castrín"), true);
assert.equal(board.hoy.find((card) => card.id === "bid-castrin")?.amount, "11,19M");
assert.ok(board.espera.some((card) => card.id === "search-POR" && card.title.includes("7,4") && card.mystery));
const search = board.espera.find((card) => card.id === "search-POR");
assert.match(search?.fallback || "", /Leo Román/);
assert.match(search?.fallback || "", /no te llega/);
assert.match(search?.timing || "", /vie 30\/10/);
assert.equal(search?.amount, "8-40M");
assert.ok(board.espera.some((card) => card.id === "sell-moleiro" && card.tone === "sell-later"));
assert.match(board.espera.find((card) => card.id === "sell-moleiro")?.timing || "", /portero/);
assert.ok(board.hoy.some((card) => card.id === "sell-turrientes" && card.tone === "sell-now"));
assert.equal(board.offers.length, 1);
assert.match(board.offers[0]?.title || "", /No aceptes la oferta de LaLiga por Lejeune/);
assert.equal(board.watches.length, 1);
assert.equal(board.windows.length, 1);
assert.equal(board.windows[0]?.reach, "falta");
assert.match(board.narrative, /Puja hoy por A\. Castrín/);
assert.match(board.status, /BÚSQUEDA/);
assert.equal(board.pointsDelta, 8.2);

const empty = buildRecommendations({ plan: { cash_eur: 1 }, optimize: null, trends: null, squads: null });
assert.match(empty.narrative, /no tiene una compra/);
assert.equal(empty.hoy.length, 0);
assert.equal(empty.pointsDelta, null);

console.log("recommendations.check ok");

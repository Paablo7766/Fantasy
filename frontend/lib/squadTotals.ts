import type { PortfolioSummary, RivalPlayer, RivalSquad } from "@/lib/types";

function sumFromPlayers(squad: RivalSquad) {
  let market_value_total = 0;
  let price_delta_day = 0;
  let price_delta_players = 0;
  for (const player of squad.players || []) {
    market_value_total += sumMarket(player);
    const delta = playerDelta(player);
    if (delta !== null) {
      price_delta_day += delta;
      price_delta_players += 1;
    }
  }
  return {
    market_value_total: market_value_total > 0 ? market_value_total : null,
    price_delta_day: price_delta_players > 0 ? price_delta_day : null,
    price_delta_players,
  };
}

/** Recalcula agregados tras enriquecer jugadores (Mercado / caché). */
export function recomputeSquadTotals(squad: RivalSquad): RivalSquad {
  const totals = sumFromPlayers(squad);
  return {
    ...squad,
    market_value_total: totals.market_value_total ?? squad.market_value_total ?? null,
    price_delta_day: totals.price_delta_day,
    price_delta_players: totals.price_delta_players,
  };
}

/** Totales de plantilla cuando el API aún no trae agregados (p. ej. caché antigua). */
export function squadTotals(squad: RivalSquad | null | undefined): {
  market_value_total: number | null;
  price_delta_day: number | null;
  price_delta_players: number | null;
} {
  if (!squad) {
    return { market_value_total: null, price_delta_day: null, price_delta_players: null };
  }
  const fromPlayers = sumFromPlayers(squad);
  const playerDeltas = fromPlayers.price_delta_players ?? 0;
  if (playerDeltas > 0 || fromPlayers.market_value_total !== null) {
    return {
      market_value_total: fromPlayers.market_value_total ?? squad.market_value_total ?? null,
      price_delta_day: fromPlayers.price_delta_day,
      price_delta_players: fromPlayers.price_delta_players,
    };
  }
  return {
    market_value_total: squad.market_value_total ?? null,
    price_delta_day: squad.price_delta_day ?? null,
    price_delta_players: squad.price_delta_players ?? null,
  };
}

function sumMarket(player: RivalPlayer): number {
  return typeof player.market_value === "number" ? player.market_value : 0;
}

/** Δ oficial del día (app). No mezclar con predicción propia. */
function playerDelta(player: RivalPlayer): number | null {
  if (typeof player.price_delta === "number" && !Number.isNaN(player.price_delta)) return player.price_delta;
  return null;
}

export function holdingSummary(players: RivalPlayer[]): PortfolioSummary {
  let cost = 0;
  let value = 0;
  let gain = 0;
  let priced = 0;
  for (const player of players) {
    if (typeof player.cost_eur === "number") {
      cost += player.cost_eur;
      priced += 1;
    }
    if (typeof player.market_value === "number") value += player.market_value;
    if (typeof player.gain_eur === "number") gain += player.gain_eur;
  }
  return {
    player_count: players.length,
    priced_count: priced,
    cost_eur: priced ? cost : null,
    market_value_eur: value > 0 ? value : null,
    gain_eur: priced ? gain : null,
    roi: priced && cost > 0 ? gain / cost : null,
  };
}

export function squadHoldings(squad: RivalSquad | null | undefined): PortfolioSummary {
  if (!squad) return holdingSummary([]);
  if (squad.portfolio && typeof squad.portfolio.priced_count === "number" && squad.portfolio.priced_count > 0) {
    return squad.portfolio;
  }
  return holdingSummary(squad.players || []);
}

/** Caja + valor de mercado de la plantilla (patrimonio total). */
export function squadPatrimonio(squad: RivalSquad | null | undefined): number | null {
  if (!squad) return null;
  const totals = squadTotals(squad);
  const value = totals.market_value_total;
  const cash = squad.cash_eur;
  if (typeof value !== "number" && typeof cash !== "number") return null;
  return (typeof cash === "number" ? cash : 0) + (typeof value === "number" ? value : 0);
}

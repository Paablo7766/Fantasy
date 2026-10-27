import { titularShare } from "@/lib/format";
import { recomputeSquadTotals } from "@/lib/squadTotals";
import type { Player, RivalPlayer, RivalSquad, SquadsPayload, TrendsPayload } from "@/lib/types";

const TREND_LISTS: (keyof TrendsPayload)[] = [
  "rising",
  "falling",
  "undervalued",
  "availability",
  "flips",
  "catalog",
  "af_prediction_rising",
  "af_prediction_falling",
  "af_oracle_points",
  "af_oracle_chollos",
  "af_in_form",
  "own_prediction_rising",
  "own_prediction_falling",
];

function trendIndex(trends: TrendsPayload | null | undefined): Map<string, Player> {
  const map = new Map<string, Player>();
  if (!trends || trends.ok === false) return map;
  for (const key of TREND_LISTS) {
    const rows = trends[key];
    if (!Array.isArray(rows)) continue;
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const id = (row as Player).player_id;
      if (!id) continue;
      const prev = map.get(String(id));
      map.set(String(id), { ...prev, ...(row as Player) });
    }
  }
  for (const row of trends.market_decisions || []) {
    const id = row.player_id;
    if (!id) continue;
    const prev = map.get(String(id));
    map.set(String(id), { ...prev, ...row });
  }
  return map;
}

function mergePlayer(base: RivalPlayer, trend: Player | undefined): RivalPlayer {
  if (!trend) return base;
  const pTitular = titularShare(base.p_titular) ?? titularShare(trend.p_titular);
  return {
    ...base,
    price_delta: base.price_delta ?? trend.price_delta ?? undefined,
    own_predicted_delta: base.own_predicted_delta ?? trend.own_predicted_delta ?? undefined,
    own_expected_points: base.own_expected_points ?? trend.own_expected_points ?? trend.expected_points ?? undefined,
    p_titular: pTitular ?? undefined,
  };
}

function enrichSquad(squad: RivalSquad | null | undefined, index: Map<string, Player>): RivalSquad | null | undefined {
  if (!squad) return squad;
  const players = (squad.players || []).map((player) =>
    mergePlayer(player, player.player_id ? index.get(String(player.player_id)) : undefined),
  );
  return recomputeSquadTotals({ ...squad, players });
}

/** Rellena Δ y titularidad desde Mercado cuando la foto core de plantillas llegó vacía. */
export function enrichSquadsPayload(
  squads: SquadsPayload | null,
  trends: TrendsPayload | null,
): SquadsPayload | null {
  if (!squads || squads.ok === false) return squads;
  const index = trendIndex(trends);
  if (!index.size) return squads;
  return {
    ...squads,
    self: enrichSquad(squads.self, index) ?? squads.self,
    rivals: (squads.rivals || []).map((rival) => enrichSquad(rival, index)!) as RivalSquad[],
  };
}

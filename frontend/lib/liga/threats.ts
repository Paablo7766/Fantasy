import type { RivalPlayer, RivalSquad } from "@/lib/types";
import { liquidityRead } from "./liquidity";
import { rivalLabel } from "@/components/liga/dashboard/shared";

export type Threat = {
  player: RivalPlayer;
  clause: number;
  /** Rivales cuya caja cubre la cláusula, del más holgado al más justo. */
  buyers: { name: string; cash: number }[];
  /** Puntos que pierde tu once sin él, si el motor lo sabe. */
  loss: number | null;
};

/** Un jugador está expuesto si ni tiene candado ni está blindado. */
export function isOpen(player: RivalPlayer): boolean {
  return player.clause_lock?.is_locked !== true && player.is_shielded !== true;
}

/**
 * Jugadores tuyos que un rival podría llevarse ahora pagando su cláusula.
 *
 * La caja de un rival es una cota reconstruida, no un saldo seguro, así que
 * esto avisa de lo que **podría** pasar: es una alerta, no una certeza.
 * Se ordena por lo que perdería tu once y, sin ese dato, por el valor.
 */
export function clauseThreats(own: RivalSquad | null | undefined, rivals: RivalSquad[]): Threat[] {
  if (!own?.players?.length) return [];
  const purses = rivals
    .filter((row) => row.team_id == null || String(row.team_id) !== String(own.team_id))
    .map((row) => {
      const read = liquidityRead(row);
      return { name: rivalLabel(row), cash: read.calibratedCash ?? read.cash };
    })
    .filter((row): row is { name: string; cash: number } => typeof row.cash === "number" && row.cash > 0);
  const found: Threat[] = [];
  for (const player of own.players) {
    const clause = player.buyout_clause;
    if (typeof clause !== "number" || clause <= 0 || !isOpen(player)) continue;
    const buyers = purses.filter((row) => row.cash >= clause).sort((a, b) => b.cash - a.cash);
    if (!buyers.length) continue;
    found.push({ player, clause, buyers, loss: typeof player.tu_once_pierde_sin_el === "number" && player.tu_once_pierde_sin_el > 0 ? player.tu_once_pierde_sin_el : null });
  }
  return found.sort((a, b) => (b.loss ?? 0) - (a.loss ?? 0) || (b.player.market_value ?? 0) - (a.player.market_value ?? 0));
}

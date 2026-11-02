import { titularShare } from "@/lib/core/format";
import type { OptimizePayload, Player } from "@/lib/types";

/**
 * El once guardado en LALIGA solo trae quién juega: ni xP ni probabilidad de
 * titular. Esos datos viven en el once recomendado, el banquillo y los
 * excluidos, así que se juntan por id.
 */
export function savedXiWithShares(optimize: OptimizePayload | null): Player[] {
  const saved = optimize?.saved_lineup?.xi || [];
  if (!saved.length) return optimize?.xi || [];
  const known = new Map<string, Player>();
  for (const row of [...(optimize?.excluded || []), ...(optimize?.benched || []), ...(optimize?.xi || [])]) {
    if (row.player_id) known.set(String(row.player_id), row);
  }
  return saved.map((row) => {
    const base = row.player_id ? known.get(String(row.player_id)) : undefined;
    return base ? { ...base, ...row, p_titular: row.p_titular ?? base.p_titular } : row;
  });
}

/** Media de la probabilidad de titular; ``null`` si ningún jugador trae el dato. */
export function averageShare(players: Player[]): number | null {
  const shares = players.map((player) => titularShare(player.p_titular)).filter((value): value is number => value !== null);
  return shares.length ? shares.reduce((total, value) => total + value, 0) / shares.length : null;
}

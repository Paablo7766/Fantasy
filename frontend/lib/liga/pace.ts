import { points } from "@/lib/core/format";
import type { LeagueEdge, LeagueFormRow } from "@/lib/types";

/** Jornadas de una temporada de LaLiga. */
export const SEASON_ROUNDS = 38;

const nameOf = (row: LeagueFormRow) => row.manager_name || row.fantasy_team_name || "Rival";

/**
 * Cuándo alcanzas al de arriba, o te alcanza el de abajo, si cada uno sigue con
 * su media reciente. Solo se dice algo cuando el cruce ocurre antes de que acabe
 * la liga; con pocas jornadas es una orientación, no una predicción.
 */
export function paceLines(rows: LeagueFormRow[], above: LeagueEdge | null | undefined, below: LeagueEdge | null | undefined, left: number): string[] {
  const mine = rows.find((row) => row.is_self);
  if (!mine || left <= 0) return [];
  const find = (edge: LeagueEdge | null | undefined) => rows.find((row) => edge?.team_id != null && String(row.team_id) === String(edge.team_id));
  const lines: string[] = [];
  const up = find(above);
  if (up && typeof above?.edge_points === "number" && above.edge_points < 0) {
    const gap = -above.edge_points;
    const diff = mine.recent_avg - up.recent_avg;
    if (diff > 0 && Math.ceil(gap / diff) <= left) lines.push(`A este ritmo alcanzas a ${nameOf(up)} en unas ${Math.ceil(gap / diff)} jornadas.`);
    else lines.push(`A este ritmo no alcanzas a ${nameOf(up)}: te saca ${points(gap)} pts y rinde ${points(Math.max(0, -diff))} más por jornada.`);
  }
  const down = find(below);
  if (down && typeof below?.edge_points === "number" && below.edge_points > 0) {
    const lead = below.edge_points;
    const diff = down.recent_avg - mine.recent_avg;
    if (diff > 0 && Math.ceil(lead / diff) <= left) lines.push(`${nameOf(down)} te alcanza en unas ${Math.ceil(lead / diff)} jornadas si no cambias.`);
  }
  return lines;
}

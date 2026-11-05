import type { LeagueProjection, LeagueXiPlayer } from "@/lib/types";

export type H2HSide = {
  /** Puntos esperados del once completo. */
  total: number | null;
  /** Jugadores que solo tiene este lado, de más a menos puntos esperados. */
  only: LeagueXiPlayer[];
};

export type HeadToHead = {
  me: H2HSide;
  them: H2HSide;
  shared: LeagueXiPlayer[];
  /** Positivo = ventaja tuya esperada. */
  edge: number | null;
  /** Puntos que se mueven de verdad: los que solo tiene uno de los dos. */
  swing: number;
};

const ev = (player: LeagueXiPlayer) => (typeof player.expected_points === "number" ? player.expected_points : 0);
const byEv = (a: LeagueXiPlayer, b: LeagueXiPlayer) => ev(b) - ev(a);

/**
 * Cruza dos onces proyectados. Los jugadores en común puntúan igual para los
 * dos, así que la jornada se decide en los que no comparten. Devuelve `null`
 * si falta alguno de los dos onces: no se inventa un duelo sin datos.
 */
export function headToHead(mine: LeagueProjection | null | undefined, theirs: LeagueProjection | null | undefined): HeadToHead | null {
  const a = mine?.xi || [];
  const b = theirs?.xi || [];
  if (!a.length || !b.length) return null;
  const ids = (xi: LeagueXiPlayer[]) => new Set(xi.map((p) => (p.player_id != null ? String(p.player_id) : null)).filter((id): id is string => id !== null));
  const idsA = ids(a);
  const idsB = ids(b);
  const common = (p: LeagueXiPlayer, other: Set<string>) => p.player_id != null && other.has(String(p.player_id));
  const shared = a.filter((p) => common(p, idsB)).sort(byEv);
  const onlyMe = a.filter((p) => !common(p, idsB)).sort(byEv);
  const onlyThem = b.filter((p) => !common(p, idsA)).sort(byEv);
  const total = (xi: LeagueXiPlayer[], given: number | null | undefined) => (typeof given === "number" ? given : xi.reduce((sum, p) => sum + ev(p), 0));
  const mineTotal = total(a, mine?.expected_points);
  const theirTotal = total(b, theirs?.expected_points);
  return {
    me: { total: mineTotal, only: onlyMe },
    them: { total: theirTotal, only: onlyThem },
    shared,
    edge: mineTotal - theirTotal,
    swing: onlyMe.reduce((s, p) => s + ev(p), 0) + onlyThem.reduce((s, p) => s + ev(p), 0),
  };
}

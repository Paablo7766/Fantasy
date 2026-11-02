import type { OptimizePayload, PlanPayload, Player, SquadsPayload, TrendsPayload } from "@/lib/types";

type Photographed = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  image_url?: string | null;
};

export type PhotoIndex = Map<string, string>;

function foldName(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function rememberPhoto(index: PhotoIndex, player: Photographed | null | undefined) {
  const url = player?.image_url;
  if (!url) return;
  if (player?.player_id) index.set(`id:${player.player_id}`, url);
  for (const name of [player?.name, player?.nickname]) {
    if (!name) continue;
    const folded = foldName(name);
    if (!folded) continue;
    index.set(folded, url);
    const last = folded.split(" ").at(-1);
    if (last && last.length > 2) index.set(last, url);
  }
}

/** Busca la foto por id y, si no, por nombre completo o apellido. */
export function photoFor(index: PhotoIndex, id: string | null | undefined, name: string | null | undefined): string | null {
  if (id && index.has(`id:${id}`)) return index.get(`id:${id}`) || null;
  if (!name) return null;
  const folded = foldName(name);
  if (index.has(folded)) return index.get(folded) || null;
  const last = folded.split(" ").at(-1);
  return (last && index.get(last)) || null;
}

/** Junta todas las fotos que traen las respuestas de la API en un solo mapa. */
export function buildPhotoIndex(
  plan: PlanPayload | null,
  optimize: OptimizePayload | null,
  squads: SquadsPayload | null,
  trends: TrendsPayload | null,
): PhotoIndex {
  const index: PhotoIndex = new Map();
  for (const player of squads?.self?.players || []) rememberPhoto(index, player);
  for (const rival of squads?.rivals || []) {
    for (const player of rival.players || []) rememberPhoto(index, player);
  }
  for (const player of [...(squads?.shield || []), ...(squads?.sell || [])]) rememberPhoto(index, player);
  for (const player of trends?.market_decisions || []) rememberPhoto(index, player);
  for (const player of [...(optimize?.xi || []), ...(optimize?.benched || []), ...(optimize?.saved_lineup?.xi || [])]) {
    rememberPhoto(index, player);
  }
  for (const strategy of plan?.strategies || []) {
    for (const move of strategy.moves || []) rememberPhoto(index, move);
  }
  for (const action of plan?.actions || []) rememberPhoto(index, action);
  return index;
}

/** Ficha que se va completando con todo lo que las respuestas saben de un jugador. */
export type PlayerFacts = Player & { owner?: string | null; clause_eur?: number | null };
export type PlayerIndex = Map<string, PlayerFacts>;

function mergeFacts(index: PlayerIndex, row: (Player & { manager_name?: string | null }) | null | undefined, owner?: string | null) {
  if (!row) return;
  const keys: string[] = [];
  if (row.player_id) keys.push(`id:${row.player_id}`);
  for (const name of [row.name, row.nickname]) {
    const folded = name ? foldName(name) : "";
    if (folded) keys.push(folded);
  }
  for (const key of keys) {
    const current = index.get(key) || {};
    const next: PlayerFacts = { ...current };
    for (const [field, value] of Object.entries(row)) {
      if (value === null || value === undefined) continue;
      if ((next as Record<string, unknown>)[field] === undefined || (next as Record<string, unknown>)[field] === null) {
        (next as Record<string, unknown>)[field] = value;
      }
    }
    if (owner && !next.owner) next.owner = owner;
    index.set(key, next);
  }
}

export function factsFor(index: PlayerIndex, id: string | null | undefined, name: string | null | undefined): PlayerFacts | null {
  if (id && index.has(`id:${id}`)) return index.get(`id:${id}`) || null;
  if (!name) return null;
  return index.get(foldName(name)) || null;
}

/** Datos cuantitativos por jugador: titularidad, previsión de valor, valor justo, puja máxima, dueño. */
export function buildPlayerIndex(
  plan: PlanPayload | null,
  optimize: OptimizePayload | null,
  squads: SquadsPayload | null,
  trends: TrendsPayload | null,
): PlayerIndex {
  const index: PlayerIndex = new Map();
  for (const row of squads?.clauses || []) {
    mergeFacts(index, { player_id: row.player_id, name: row.name, nickname: row.nickname, buyout_clause: row.buyout_clause_eur, market_value: row.market_value }, row.manager_name);
  }
  for (const row of [...(trends?.market_decisions || []), ...(plan?.decisions || [])]) mergeFacts(index, row);
  for (const row of [...(squads?.shield || []), ...(squads?.sell || [])]) mergeFacts(index, row);
  for (const row of squads?.self?.players || []) mergeFacts(index, row);
  for (const row of [...(optimize?.xi || []), ...(optimize?.benched || []), ...(optimize?.saved_lineup?.xi || [])]) mergeFacts(index, row);
  for (const rival of squads?.rivals || []) {
    for (const row of rival.players || []) mergeFacts(index, row, rival.manager_name);
  }
  return index;
}

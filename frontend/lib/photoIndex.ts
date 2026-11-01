import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

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

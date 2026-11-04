import bustIds from "@/lib/data/bust-photos.json";

const IDS = bustIds as Record<string, string>;

/**
 * Foto de pecho con la camiseta del club (web oficial de LaLiga), por id de
 * Fantasy. El mapa lo genera ``scripts/build_bust_photos.py``; si el jugador no
 * está, devuelve ``null`` y el llamador usa la foto de cara de siempre.
 */
export function bustPhotoFor(playerId: string | null | undefined): string | null {
  const ref = playerId ? IDS[String(playerId)] : undefined;
  if (!ref) return null;
  const [team, player] = ref.split("/");
  return `https://assets.laliga.com/squad/2026/${team}/${player}/256x278/${player}_${team}_2026_1_001_000.png`;
}

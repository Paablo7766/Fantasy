import { escudoDe } from "@/lib/core/escudos";

/** Escudo del club; si no se reconoce, no pinta nada. */
export function Crest({ club, size = 20, className = "" }: { club: string | null | undefined; size?: number; className?: string }) {
  const src = escudoDe(club);
  if (!src) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" width={size} height={size} decoding="async" referrerPolicy="no-referrer" className={`shrink-0 object-contain ${className}`} style={{ width: size, height: size }} />
  );
}

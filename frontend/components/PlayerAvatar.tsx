"use client";

import { useState } from "react";
import { initials, playerName } from "@/lib/format";
import type { Player } from "@/lib/types";

export function PlayerAvatar({
  player,
  className = "",
  size = "md",
}: {
  player: Player | null | undefined;
  className?: string;
  size?: "sm" | "md";
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const name = playerName(player);
  const src = player?.image_url || null;
  const box =
    size === "sm"
      ? "h-8 w-8 shrink-0 text-[10px] ring-1 ring-ink/10"
      : "h-full w-full text-[11px]";

  // Se recuerda qué URL falló, no un booleano: al cambiar de jugador la foto
  // nueva se intenta sola, sin sembrar estado desde un efecto.
  const failed = src !== null && failedSrc === src;

  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        className={`avatar object-cover ${box} ${className}`.trim()}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailedSrc(src)}
      />
    );
  }

  return <div className={`avatar ${box} ${className}`.trim()}>{initials(name)}</div>;
}

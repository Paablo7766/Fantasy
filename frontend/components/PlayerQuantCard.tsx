"use client";

import type { ReactNode } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { eurShort, playerName, points, titularShare } from "@/lib/format";
import type { Player } from "@/lib/types";

function variationTone(text: string | null | undefined): "up" | "down" | "flat" {
  if (!text) return "flat";
  const value = text.trim();
  if (value.startsWith("-") || value.startsWith("−")) return "down";
  if (value.startsWith("+")) return "up";
  return "flat";
}

function statusRing(player: Player): string {
  const blob = `${player.player_status || ""} ${player.fitness || ""} ${player.fitness_detail || ""}`.toLowerCase();
  const out =
    player.sanction?.suspended === true ||
    /baja|lesion|lesión|sancion|sanción|no juega|out|injured|suspend/.test(blob);
  if (out) return "ring-[#4B6075]";
  const share = titularShare(player.p_titular);
  if (share !== null && share >= 0.75) return "ring-[#0297DE]";
  if (share !== null && share > 0 && share < 0.75) return "ring-[#FC734D]";
  return "ring-[#4B6075]";
}

function Bolt() {
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor" aria-hidden="true">
      <path d="M9.1 1.1 3.2 9h3.5l-.5 5.9 6.1-8.3H8.8l.3-5.5Z" />
    </svg>
  );
}

export function PlayerQuantCard({
  player,
  price,
  variation,
  xp,
  ifStarts,
  ceiling,
  rightTitle,
  rightValue,
  rightHint,
  glow,
  onClick,
  pressed,
  children,
}: {
  player: Player;
  price?: number | null;
  variation?: string | null;
  xp?: number | null;
  ifStarts?: number | null;
  ceiling?: number | null;
  rightTitle: string;
  rightValue: string;
  rightHint?: string | null;
  glow?: "metric" | "alert";
  onClick?: () => void;
  pressed?: boolean;
  children?: ReactNode;
}) {
  const tone = variationTone(variation);
  const highCeiling =
    typeof ceiling === "number" && (ceiling >= 10 || (typeof ifStarts === "number" && ceiling >= ifStarts + 2));
  const team = [player.position, player.club].filter(Boolean).join(" · ");
  const shadow =
    glow === "alert" || highCeiling
      ? "shadow-[0_0_24px_rgba(252,115,77,0.18)]"
      : glow === "metric"
        ? "shadow-[0_0_24px_rgba(2,151,222,0.18)]"
        : "shadow-[0_8px_32px_rgba(0,0,0,0.4)]";
  const body = (
    <>
      <div className="flex items-center gap-3">
        <div className={`shrink-0 rounded-full p-0.5 ring-2 ring-offset-2 ring-offset-[#02070A] ${statusRing(player)}`}>
          <PlayerAvatar player={player} size="sm" className="!h-11 !w-11 !text-[11px] !ring-0" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-tight text-[#F0F6FC]">{playerName(player)}</p>
              <p className="truncate text-[11px] text-[#8B9EB0]">{team || "Sin equipo"}</p>
            </div>
            <div className="shrink-0 text-right">
              <p className="font-mono text-sm font-semibold tabular-nums text-[#F0F6FC]">{eurShort(price ?? player.market_value)}</p>
              {variation ? (
                <span
                  className={`mt-1 inline-flex rounded-full px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums ${
                    tone === "up"
                      ? "bg-[#10B981]/15 text-[#10B981]"
                      : tone === "down"
                        ? "bg-[#FC734D]/15 text-[#FC734D]"
                        : "bg-white/5 text-[#8B9EB0]"
                  }`}
                >
                  {variation}
                </span>
              ) : (
                <span className="mt-1 inline-flex font-mono text-[10px] text-[#4B6075]">s/d</span>
              )}
            </div>
          </div>
          <div className="mt-2.5 flex items-center gap-2">
            <span className="inline-flex items-baseline gap-1 rounded-full bg-[#02070A] px-2.5 py-1 font-mono text-[13px] font-bold tabular-nums text-[#0297DE]">
              <span className="text-[9px] font-semibold tracking-wide text-[#8B9EB0]">xP</span>
              {points(xp)}
            </span>
            {typeof ceiling === "number" ? (
              <span className="inline-flex items-center gap-0.5 font-mono text-[12px] font-semibold tabular-nums text-[#FC734D]">
                <Bolt />
                {points(ceiling)}
              </span>
            ) : null}
            <span className="ml-auto min-w-0 text-right">
              <span className="block truncate text-[10px] font-semibold uppercase tracking-wider text-[#4B6075]">{rightTitle}</span>
              <span className="block font-mono text-[12px] font-semibold tabular-nums text-[#F0F6FC]">{rightValue}</span>
              {rightHint ? <span className="block truncate font-mono text-[10px] tabular-nums text-[#8B9EB0]">{rightHint}</span> : null}
            </span>
          </div>
        </div>
      </div>
      {children}
    </>
  );
  const className = `w-full rounded-2xl border border-[#0297DE]/15 bg-[#07121A]/85 p-3.5 text-left backdrop-blur-xl ${shadow} ${
    pressed ? "border-[#0297DE]" : ""
  }`;
  if (onClick) {
    return (
      <button type="button" className={className} onClick={onClick} aria-pressed={pressed}>
        {body}
      </button>
    );
  }
  return <article className={className}>{body}</article>;
}

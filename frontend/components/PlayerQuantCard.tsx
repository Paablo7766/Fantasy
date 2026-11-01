"use client";

import type { ReactNode } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { eur, playerName, points } from "@/lib/format";
import type { Player } from "@/lib/types";

function variationClass(text: string | null | undefined): string {
  if (!text) return "text-[#4B6075]";
  const value = text.trim();
  if (value.startsWith("-") || value.startsWith("−")) return "text-[#FC734D]";
  if (value.startsWith("+")) return "text-[#10B981]";
  return "text-[#8B9EB0]";
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
  onClick?: () => void;
  pressed?: boolean;
  children?: ReactNode;
}) {
  const highCeiling =
    typeof ceiling === "number" && (ceiling >= 10 || (typeof ifStarts === "number" && ceiling >= ifStarts + 2));
  const body = (
    <>
      <div className="flex items-center gap-2.5">
        <PlayerAvatar player={player} size="sm" className="!h-10 !w-10 !text-[11px]" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold tracking-tight text-[#F0F6FC]">{playerName(player)}</p>
          <p className="mt-1 flex min-w-0 items-center gap-1.5">
            {player.position ? (
              <span className="shrink-0 rounded-md border border-[rgba(2,151,222,0.28)] bg-[rgba(2,151,222,0.1)] px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-[#67C6F5]">
                {player.position}
              </span>
            ) : null}
            {player.club ? <span className="truncate text-[11px] text-[#8B9EB0]">{player.club}</span> : null}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-sm font-bold tabular-nums text-[#F0F6FC]">{eur(price ?? player.market_value)}</p>
          {variation ? (
            <p className={`font-mono text-[11px] font-semibold tabular-nums ${variationClass(variation)}`}>{variation}</p>
          ) : (
            <p className="font-mono text-[11px] text-[#4B6075]">s/d</p>
          )}
        </div>
      </div>
      <div className="mt-2.5 grid grid-cols-3 gap-2 border-t border-[rgba(2,151,222,0.14)] pt-2.5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[#4B6075]">xP Jornada</p>
          <p className="mt-0.5 font-mono text-sm font-bold tabular-nums text-[#0297DE]">{points(xp)}</p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[#4B6075]">Si titular / Techo</p>
          <p className="mt-0.5 font-mono text-[12px] font-semibold tabular-nums text-[#F0F6FC]">
            {points(ifStarts)}
            <span className="text-[#4B6075]"> / </span>
            <span className={highCeiling ? "text-[#FC734D]" : undefined}>
              {highCeiling ? "⚡ " : ""}
              {points(ceiling)}
            </span>
          </p>
        </div>
        <div className="text-right">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[#4B6075]">{rightTitle}</p>
          <p className="mt-0.5 font-mono text-sm font-bold tabular-nums text-[#F0F6FC]">{rightValue}</p>
          {rightHint ? <p className="font-mono text-[10px] tabular-nums text-[#8B9EB0]">{rightHint}</p> : null}
        </div>
      </div>
      {children}
    </>
  );
  const className = `w-full rounded-2xl border border-[rgba(2,151,222,0.14)] bg-[rgba(7,18,26,0.85)] p-3 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-xl ${
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

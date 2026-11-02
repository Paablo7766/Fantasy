"use client";

import { useEffect, useRef } from "react";
import { AuctionV2Panel } from "@/components/AuctionV2Panel";
import { GradeBadge, GradeLabel } from "@/components/MarketGrade";
import { ForcedSaleBadge } from "@/components/StrategyBits";
import { Face, Fact, TONE, Verdict, money } from "@/components/equipo/ui";
import { bidCapLine, bidStory } from "@/lib/bidStory";
import { playerName } from "@/lib/format";
import { actionReason, executableBid, isVetoed, marketAction } from "@/lib/marketAction";
import type { MarketDecision } from "@/lib/types";
import { ACTION_VERDICT, sourceLabel } from "@/components/mercado/shared";

/** Hoja lateral con el porqué de una puja: qué hacer, los datos, la teoría y lo que falta. */
export function BidSheet({ player, photo, onClose }: { player: MarketDecision | null; photo?: string | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const story = player ? bidStory(player) : null;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (player && !dialog.open) dialog.showModal();
    if (!player && dialog.open) dialog.close();
  }, [player]);

  const action = player ? marketAction(player) : "NO";
  const bid = player ? executableBid(player) : null;
  const cap = player ? bidCapLine(player) : null;

  return (
    <dialog
      ref={ref}
      className="bid-dialog mk-sheet"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {player && story ? (
        <div className="bid-dialog__body flex flex-col gap-5">
          <div className="flex items-start gap-3">
            <Face name={playerName(player)} src={player.image_url || photo} size={52} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                {typeof player.nota_mercado === "number" ? <GradeBadge note={player.nota_mercado} /> : null}
                <h3 className="truncate text-[1.2rem] font-semibold tracking-tight text-white">{playerName(player)}</h3>
              </div>
              <p className="mt-0.5 truncate text-[12.5px] text-white/45">
                {[player.position, player.club, sourceLabel(player)].filter(Boolean).join(" · ")}
              </p>
              {typeof player.nota_mercado === "number" && player.etiqueta_mercado ? (
                <p className="mt-1">
                  <GradeLabel note={player.nota_mercado} label={player.etiqueta_mercado} />
                </p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Cerrar"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/[0.06] text-white/60 transition-colors hover:bg-white/[0.12] hover:text-white"
            >
              <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          <section className="home-glass px-4 py-4">
            <div className="flex items-center justify-between gap-3">
              <Verdict {...ACTION_VERDICT[action]} />
              {isVetoed(player) ? <span className="text-[12px] font-medium" style={{ color: TONE.red }}>Veto del motor</span> : null}
            </div>
            <p className="mt-2 text-[2rem] font-semibold leading-none tabular-nums text-white">
              {typeof bid === "number" ? money(bid) : "Sin puja"}
            </p>
            {cap ? <p className="mt-1.5 text-[12.5px] text-white/50">{cap}</p> : null}
            <p className="mt-3 text-[14px] leading-relaxed text-white/80">{actionReason(player, story.motive) || story.headline}</p>
            {player.venta_forzada_rival ? (
              <p className="mt-2">
                <ForcedSaleBadge />
              </p>
            ) : null}
          </section>

          {player.frase_mercado ? <p className="px-1 text-[14px] leading-relaxed text-white/70">{player.frase_mercado}</p> : null}

          <section className="rounded-2xl px-4 py-3.5" style={{ background: "rgba(255,154,90,0.1)", border: "1px solid rgba(255,154,90,0.2)" }}>
            <p className="text-[12px] font-medium text-[#FFC08A]">Qué hacer</p>
            <p className="mt-1 text-[14px] leading-relaxed text-white">{story.action}</p>
          </section>

          <AuctionV2Panel player={player} variant="full" />

          {story.facts.length ? (
            <section>
              <p className="px-1 text-[13px] font-medium text-white/60">Las cifras</p>
              <div className="home-glass mt-2 grid grid-cols-2 gap-x-4 gap-y-4 px-4 py-4">
                {story.facts.map((fact) => (
                  <Fact key={fact.label} label={fact.label} value={fact.value} hint={fact.note} />
                ))}
              </div>
            </section>
          ) : null}

          {story.reasons.length ? (
            <section>
              <p className="px-1 text-[13px] font-medium text-white/60">Los datos</p>
              <ul className="mt-2 flex flex-col gap-2 px-1">
                {story.reasons.map((reason) => (
                  <li key={reason} className="flex gap-2.5 text-[13.5px] leading-relaxed text-white/75">
                    <span className="mt-[0.55rem] h-1 w-1 shrink-0 rounded-full bg-[#FF9A5A]" aria-hidden="true" />
                    {reason}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {story.theory ? (
            <section>
              <p className="px-1 text-[13px] font-medium text-white/60">La teoría</p>
              <p className="mt-2 px-1 text-[13.5px] leading-relaxed text-white/75">{story.theory}</p>
            </section>
          ) : null}

          {(player.rival_bids || []).length ? (
            <section>
              <p className="px-1 text-[13px] font-medium text-white/60">Pujas ya hechas</p>
              <ul className="home-glass mt-2 px-4 py-1">
                {player.rival_bids?.map((row) => (
                  <li
                    key={`${row.team_id}-${row.amount}`}
                    className="flex justify-between border-b border-white/[0.06] py-2.5 text-[14px] last:border-b-0"
                  >
                    <span className={row.own ? "font-medium text-[#FFC08A]" : "text-white/80"}>{row.own ? "Tú" : row.manager_name || "Rival"}</span>
                    <span className="font-semibold tabular-nums text-white">{money(row.amount)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {story.gaps.length ? (
            <section>
              <p className="px-1 text-[13px] font-medium text-white/60">Qué no entra en la cuenta</p>
              <ul className="mt-2 flex flex-col gap-1.5 px-1">
                {story.gaps.map((gap) => (
                  <li key={gap} className="text-[12.5px] leading-relaxed text-white/45">
                    {gap}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}

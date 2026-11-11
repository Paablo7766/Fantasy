"use client";

import { useEffect, useRef, useState } from "react";
import { playerName, stamp } from "@/lib/core/format";
import { liquidityRead } from "@/lib/liga/liquidity";
import { squadHoldings } from "@/lib/liga/squadTotals";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { ActivityEvent, RivalPlayer, RivalSquad } from "@/lib/types";
import { Crest } from "@/components/ui/Crest";
import { Chevron, Face, Fact, TONE, cleanText, forecastHint, money, parsePct, signedMoney, signedPct, toneOf } from "@/components/ui/kit";
import { POS_LABEL, POS_ORDER, rivalLabel } from "./dashboard/shared";
import { Tile } from "./parts";

type SheetTab = "plantilla" | "movimientos";

const STYLE: Record<string, string> = {
  agresivo: "Puja fuerte",
  moderado: "Puja normal",
  conservador: "Puja justo",
};

const EVENT_TEXT: Record<string, string> = {
  buy: "Fichó a",
  clause: "Clausuló a",
  sell: "Vendió a",
  premium: "Premio de jornada",
};

function eventLine(event: ActivityEvent): string {
  const head = EVENT_TEXT[String(event.kind)] || cleanText(event.label) || "Movimiento";
  return event.kind === "premium" || !event.player_name ? head : `${head} ${event.player_name}`;
}

/** Cómo se comporta en el mercado, en frases: cuánto paga de más, cómo redondea y a qué hora clausula. */
function habits(squad: RivalSquad): { text: string; color?: string }[] {
  const lines: { text: string; color?: string }[] = [];
  if (squad.dinero_caliente?.aviso) lines.push({ text: cleanText(squad.dinero_caliente.aviso), color: TONE.copper });
  const profile = squad.bid_profile;
  if (profile && profile.style !== "sin_datos") {
    const premium = typeof profile.typical_premium_pct === "number" ? `: suele pagar un ${signedPct(profile.typical_premium_pct, 0)} sobre el valor` : "";
    lines.push({ text: `${STYLE[profile.style] || "Puja"}${premium}.` });
  }
  const tail = squad.huella?.cola;
  if (tail && tail.estilo !== "mixto") lines.push({ text: `${tail.etiqueta} en sus pujas (${tail.n_compras} compras).` });
  const windows = squad.huella?.ventanas_clausulazo || [];
  if (windows.length) lines.push({ text: `Suele clausular hacia las ${windows.join(", ")}.` });
  for (const offer of squad.huella?.ofertas_humanas || []) {
    lines.push({ text: `${offer.nombre || "Un jugador suyo"}: ${offer.etiqueta.toLowerCase()} (${offer.offer_count} ofertas).`, color: TONE.red });
  }
  return lines;
}

function clauseState(player: RivalPlayer): string {
  if (player.is_shielded) return "Blindado";
  if (player.clause_lock?.is_locked) return "Con candado";
  return `Cláusula ${money(player.buyout_clause)}`;
}

function SquadPlayer({ player, photos }: { player: RivalPlayer; photos: PhotoIndex }) {
  const [open, setOpen] = useState(false);
  const name = playerName(player);
  const trend = parsePct(player.prevision_7d_pct);
  const lock = player.clause_lock;
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors duration-200 hover:bg-white/[0.03]"
      >
        <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={36} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium text-white">{name}</span>
          <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-white/40">
            <Crest club={player.club} size={13} />
            <span className="truncate">{[player.club, clauseState(player)].filter(Boolean).join(" · ")}</span>
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[14px] font-medium tabular-nums text-white">{money(player.market_value)}</span>
          {trend !== null ? (
            <span className="mt-0.5 block text-[11.5px] tabular-nums" style={{ color: toneOf(trend) }}>
              {forecastHint(player.market_value, trend)?.replace("→ ", "")}
            </span>
          ) : null}
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in grid grid-cols-3 gap-3 px-4 pb-3.5 pt-1">
          <Fact label="Pagó" value={money(player.cost_eur)} hint={player.acquired_at ? stamp(player.acquired_at) : undefined} />
          <Fact label="Ganancia" value={signedMoney(player.gain_eur)} tone={toneOf(player.gain_eur)} hint={typeof player.roi === "number" ? signedPct(player.roi * 100) : undefined} />
          <Fact label="Cláusula" value={money(player.buyout_clause)} hint={lock?.is_locked ? `Abre ${lock.local_time || lock.local_date || ""}` : player.is_shielded ? "Blindado" : "Abierta"} />
        </div>
      ) : null}
    </li>
  );
}

/** Ficha de un mánager: su dinero, cómo se mueve en el mercado, su plantilla y sus últimos movimientos. */
export function RivalDialog({
  squad,
  self,
  ownPoints,
  cash,
  photos,
  onClose,
}: {
  squad: RivalSquad | null;
  self: boolean;
  ownPoints: number | null;
  cash: number | null;
  photos: PhotoIndex;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<SheetTab>("plantilla");
  const teamId = squad?.team_id != null ? String(squad.team_id) : null;
  const [shown, setShown] = useState(teamId);
  if (shown !== teamId) {
    setShown(teamId);
    setTab("plantilla");
  }

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (squad && !dialog.open) {
      dialog.showModal();
      dialog.scrollTop = 0;
    }
    if (!squad && dialog.open) dialog.close();
  }, [squad]);

  const body = (() => {
    if (!squad) return null;
    const name = rivalLabel(squad);
    const read = liquidityRead(squad);
    const holdings = squadHoldings(squad);
    const players = squad.players || [];
    const groups = POS_ORDER.map((pos) => ({
      pos,
      rows: players.filter((player) => String(player.position || "").toUpperCase() === pos).sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0)),
    })).filter((group) => group.rows.length);
    const events = squad.activity_profile?.recent_events || [];
    const gap = !self && typeof squad.points === "number" && ownPoints !== null ? squad.points - ownPoints : null;
    const lines = self ? [] : habits(squad);
    const spent = (squad.activity_profile?.purchases_eur ?? 0) + (squad.activity_profile?.clauses_eur ?? 0);
    return (
      <article className="flex flex-col gap-4 p-4 sm:p-5">
        <span className="mx-auto -mt-1 h-1 w-10 rounded-full bg-white/20 sm:hidden" aria-hidden="true" />
        <header className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[12.5px] tabular-nums text-white/45">
              {typeof squad.rank === "number" ? `${squad.rank}º en la liga` : "Sin puesto"}
              {self ? " · Tú" : ""}
            </p>
            <h2 className="mt-0.5 truncate text-[1.5rem] font-semibold leading-tight tracking-tight text-white">{name}</h2>
            <p className="mt-1 truncate text-[13px] tabular-nums text-white/55">
              {[
                squad.fantasy_team_name && squad.fantasy_team_name !== name ? squad.fantasy_team_name : null,
                typeof squad.points === "number" ? `${squad.points} puntos` : null,
                gap !== null ? (gap === 0 ? "empatado contigo" : `${Math.abs(gap)} ${gap > 0 ? "más" : "menos"} que tú`) : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/[0.06] text-white/60 outline-none transition-colors hover:text-white"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="grid grid-cols-3 gap-2 [&>div]:bg-white/[0.05]">
          <Tile label="Caja" value={money(cash, 1)} tone={cash !== null && cash < 0 ? TONE.red : undefined} />
          <Tile label="Puja máxima" value={money(read.bidLimit, 1)} />
          <Tile label="Ganancia plantilla" value={signedMoney(holdings.gain_eur)} tone={toneOf(holdings.gain_eur)} />
        </div>

        {lines.length || read.tightened || (read.arbitrageEur ?? 0) > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {lines.map((line) => (
              <li key={line.text} className="flex items-baseline gap-2 text-[13px] leading-snug text-white/60">
                <span className="h-1.5 w-1.5 shrink-0 -translate-y-px rounded-full" style={{ background: line.color || "rgba(255,255,255,0.3)" }} aria-hidden="true" />
                <span className="min-w-0">{line.text}</span>
              </li>
            ))}
            {read.tightened || (read.arbitrageEur ?? 0) > 0 ? (
              <li className="text-[12px] leading-snug text-white/35">
                {(read.arbitrageEur ?? 0) > 0
                  ? "Tiene más caja de la que explican sus movimientos: la cifra es la que publica la liga."
                  : "La caja está ajustada con su saldo real: es lo que de verdad puede gastar."}
              </li>
            ) : null}
          </ul>
        ) : null}

        <div className="desk-switch !max-w-none !grid-cols-2" role="tablist" aria-label="Qué ver del mánager">
          {(
            [
              ["plantilla", `Plantilla · ${players.length}`],
              ["movimientos", "Movimientos"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={tab === id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "plantilla" ? (
          groups.length ? (
            <section className="home-glass overflow-hidden">
              {groups.map((group, index) => (
                <div key={group.pos} className={index ? "border-t border-white/[0.06]" : ""}>
                  <p className="px-4 pb-1 pt-3.5 text-[11.5px] font-semibold text-white/70">
                    {POS_LABEL[group.pos] || group.pos} <span className="font-normal text-white/35">{group.rows.length}</span>
                  </p>
                  <ul className="divide-y divide-white/[0.05]">
                    {group.rows.map((player) => (
                      <SquadPlayer key={String(player.player_id)} player={player} photos={photos} />
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          ) : (
            <p className="home-glass p-4 text-[13.5px] text-white/50">Esta plantilla no trae jugadores.</p>
          )
        ) : (
          <section className="home-glass overflow-hidden">
            <div className="grid grid-cols-3 gap-3 px-4 py-4">
              <Fact label="Ha gastado" value={money(spent || null)} />
              <Fact label="Ha vendido" value={money(squad.activity_profile?.sales_eur)} />
              <Fact label="Ganado vendiendo" value={signedMoney(squad.activity_profile?.realized_gain_eur)} tone={toneOf(squad.activity_profile?.realized_gain_eur)} />
            </div>
            {events.length ? (
              <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06]">
                {events.map((event, index) => {
                  const incoming = typeof event.signed_eur === "number" ? event.signed_eur > 0 : event.kind === "sell" || event.kind === "premium";
                  return (
                    <li key={`${event.at}-${event.kind}-${index}`} className="flex items-center gap-3 px-4 py-2.5">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] text-white">{eventLine(event)}</span>
                        <span className="mt-0.5 block text-[11.5px] text-white/40">{stamp(event.at) || "Sin fecha"}</span>
                      </span>
                      <span className="shrink-0 text-[14px] font-medium tabular-nums" style={{ color: incoming ? TONE.green : TONE.red }}>
                        {typeof event.signed_eur === "number" ? signedMoney(event.signed_eur) : money(event.amount_eur)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="border-t border-white/[0.06] px-4 py-4 text-[13px] text-white/45">Sin movimientos sincronizados para este mánager.</p>
            )}
          </section>
        )}
      </article>
    );
  })();

  return (
    <dialog
      ref={ref}
      className="mk-card"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {body}
    </dialog>
  );
}

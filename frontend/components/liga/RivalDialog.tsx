"use client";

import { useEffect, useRef, useState } from "react";
import { playerName, stamp } from "@/lib/core/format";
import { liquidityRead } from "@/lib/liga/liquidity";
import { squadTotals } from "@/lib/liga/squadTotals";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { ActivityEvent, RivalPlayer, RivalSquad } from "@/lib/types";
import { Crest } from "@/components/ui/Crest";
import { Chevron, Disclosure, Face, Fact, TONE, cleanText, money, parsePct, projected7d, signedMoney, signedPct, toneOf } from "@/components/ui/kit";
import { POS_LABEL, POS_ORDER, rivalLabel } from "./dashboard/shared";
import { Tile } from "./parts";

type Order = "hoy" | "linea";

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

const dayDelta = (player: RivalPlayer) => (typeof player.price_delta === "number" && Number.isFinite(player.price_delta) ? player.price_delta : null);

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

function SquadPlayer({ player, top, photos }: { player: RivalPlayer; top: number; photos: PhotoIndex }) {
  const [open, setOpen] = useState(false);
  const name = playerName(player);
  const trend = parsePct(player.prevision_7d_pct);
  const week = projected7d(player.market_value, trend);
  const lock = player.clause_lock;
  const delta = dayDelta(player) ?? 0;
  const moved = Math.abs(delta) >= 1;
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
        {/* Lo que se ha movido hoy: la barra crece desde el centro, a la derecha si sube. */}
        <span className="relative hidden h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-white/[0.06] min-[480px]:block" aria-hidden="true">
          <span className="absolute inset-y-0 left-1/2 w-px bg-white/25" />
          {moved ? (
            <span
              className="absolute inset-y-0 rounded-full"
              style={{ width: `${Math.min(1, Math.abs(delta) / top) * 50}%`, background: delta > 0 ? TONE.green : TONE.red, ...(delta > 0 ? { left: "50%" } : { right: "50%" }) }}
            />
          ) : null}
        </span>
        <span className="w-[5.75rem] shrink-0 text-right">
          <span className="block text-[14px] font-medium tabular-nums" style={{ color: moved ? toneOf(delta) : "rgba(255,255,255,0.4)" }}>
            {moved ? signedMoney(delta) : "sin cambio"}
          </span>
          <span className="mt-0.5 block text-[11.5px] tabular-nums text-white/40">vale {money(player.market_value)}</span>
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in grid grid-cols-2 gap-3 px-4 pb-3.5 pt-1 min-[480px]:grid-cols-4">
          <Fact label="En 7 días" value={week !== null ? money(week) : "—"} tone={trend !== null ? toneOf(trend) : undefined} hint={trend !== null ? signedPct(trend) : "Sin previsión"} />
          <Fact label="Pagó" value={money(player.cost_eur)} hint={player.acquired_at ? stamp(player.acquired_at) : undefined} />
          <Fact label="Ganancia" value={signedMoney(player.gain_eur)} tone={toneOf(player.gain_eur)} hint={typeof player.roi === "number" ? signedPct(player.roi * 100) : undefined} />
          <Fact label="Cláusula" value={money(player.buyout_clause)} hint={lock?.is_locked ? `Abre ${lock.local_time || lock.local_date || ""}` : player.is_shielded ? "Blindado" : "Abierta"} />
        </div>
      ) : null}
    </li>
  );
}

/** Ficha de un mánager: lo que vale y se mueve su equipo hoy, su dinero, cómo puja y su plantilla jugador a jugador. */
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
  const [order, setOrder] = useState<Order>("hoy");
  const teamId = squad?.team_id != null ? String(squad.team_id) : null;
  const [shown, setShown] = useState(teamId);
  if (shown !== teamId) {
    setShown(teamId);
    setOrder("hoy");
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
    const totals = squadTotals(squad);
    const players = squad.players || [];
    const groups = POS_ORDER.map((pos) => ({
      pos,
      rows: players.filter((player) => String(player.position || "").toUpperCase() === pos).sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0)),
    })).filter((group) => group.rows.length);
    const byDay = players.slice().sort((a, b) => (dayDelta(b) ?? 0) - (dayDelta(a) ?? 0));
    const rising = players.filter((player) => (dayDelta(player) ?? 0) >= 1);
    const falling = players.filter((player) => (dayDelta(player) ?? 0) <= -1);
    const top = Math.max(1, ...players.map((player) => Math.abs(dayDelta(player) ?? 0)));
    const best = rising.length ? byDay[0] : null;
    const worst = falling.length ? byDay[byDay.length - 1] : null;
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

        <div className="grid grid-cols-2 gap-2 min-[480px]:grid-cols-4 [&>div]:bg-white/[0.05]">
          <Tile label="Valor del equipo" value={money(totals.market_value_total, 1)} />
          <Tile
            label="Hoy"
            value={signedMoney(totals.price_delta_day)}
            tone={toneOf(totals.price_delta_day)}
            hint={rising.length || falling.length ? `${rising.length} suben · ${falling.length} bajan` : "Sin cambios"}
          />
          <Tile label="Caja" value={money(cash, 1)} tone={cash !== null && cash < 0 ? TONE.red : undefined} />
          <Tile label="Puja máxima" value={money(read.bidLimit, 1)} />
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

        <section className="home-glass overflow-hidden" aria-label="Plantilla">
          <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 px-4 pb-3 pt-4">
            <div className="min-w-0">
              <h3 className="text-[15px] font-semibold text-white">
                Plantilla <span className="ml-1 font-normal tabular-nums text-white/40">{players.length}</span>
              </h3>
              {best || worst ? (
                <p className="mt-0.5 text-[12.5px] leading-snug tabular-nums text-white/45">
                  {[
                    best ? `Quien más sube hoy: ${playerName(best)} (${signedMoney(dayDelta(best))})` : null,
                    worst ? `${best ? "quien" : "Quien"} más baja: ${playerName(worst)} (${signedMoney(dayDelta(worst))})` : null,
                  ]
                    .filter(Boolean)
                    .join("; ")}
                  .
                </p>
              ) : null}
            </div>
            <div className="flex shrink-0 gap-4" role="tablist" aria-label="Ordenar la plantilla">
              {(
                [
                  ["hoy", "Por subida de hoy"],
                  ["linea", "Por línea"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={order === id}
                  onClick={() => setOrder(id)}
                  className={`relative pb-1.5 text-[13px] transition-colors duration-200 ${order === id ? "font-semibold text-white" : "text-white/50 hover:text-white/80"}`}
                >
                  {label}
                  {order === id ? <span className="absolute inset-x-0 bottom-0 h-[2px] rounded-full bg-[#FFC08A]" aria-hidden="true" /> : null}
                </button>
              ))}
            </div>
          </div>
          {!players.length ? (
            <p className="border-t border-white/[0.06] p-4 text-[13.5px] text-white/50">Esta plantilla no trae jugadores.</p>
          ) : order === "hoy" ? (
            <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06]">
              {byDay.map((player) => (
                <SquadPlayer key={String(player.player_id)} player={player} top={top} photos={photos} />
              ))}
            </ul>
          ) : (
            groups.map((group) => (
              <div key={group.pos} className="border-t border-white/[0.06]">
                <p className="px-4 pb-1 pt-3.5 text-[11.5px] font-semibold text-white/70">
                  {POS_LABEL[group.pos] || group.pos} <span className="font-normal text-white/35">{group.rows.length}</span>
                </p>
                <ul className="divide-y divide-white/[0.05]">
                  {group.rows.map((player) => (
                    <SquadPlayer key={String(player.player_id)} player={player} top={top} photos={photos} />
                  ))}
                </ul>
              </div>
            ))
          )}
        </section>

        {events.length ? (
          <Disclosure title="Fichajes y ventas recientes" meta={`${events.length}`}>
            <div className="grid grid-cols-3 gap-3">
              <Fact label="Ha gastado" value={money(spent || null)} />
              <Fact label="Ha vendido" value={money(squad.activity_profile?.sales_eur)} />
              <Fact label="Ganado vendiendo" value={signedMoney(squad.activity_profile?.realized_gain_eur)} tone={toneOf(squad.activity_profile?.realized_gain_eur)} />
            </div>
            <ul className="mt-3 divide-y divide-white/[0.05] border-t border-white/[0.06]">
              {events.map((event, index) => {
                const incoming = typeof event.signed_eur === "number" ? event.signed_eur > 0 : event.kind === "sell" || event.kind === "premium";
                return (
                  <li key={`${event.at}-${event.kind}-${index}`} className="flex items-center gap-3 py-2.5">
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
          </Disclosure>
        ) : null}
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

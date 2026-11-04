"use client";

import { useMemo, useState } from "react";
import { playerName, points, stamp, titularShare } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { ActivityEvent, AuditoriaVenta, PlanPayload, RivalPlayer, SquadsPayload, VeredictoVenta } from "@/lib/types";
import {
  Chevron,
  Empty,
  Face,
  Fact,
  HeroStat,
  SectionHead,
  Skeleton,
  Sparkline,
  TONE,
  compact,
  money,
  parsePct,
  signedMoney,
  signedPct,
  toneOf,
} from "@/components/ui/kit";

/** La máquina de LaLiga ofrece el valor de mercado ±10 %. */
const MACHINE_SPREAD = 10;

/** Qué hacer con una oferta, en una palabra. */
const ACTION: Record<VeredictoVenta, { label: string; color: string }> = {
  ACEPTAR_YA: { label: "Acepta", color: TONE.green },
  RECHAZAR_ESPERAR: { label: "Espera", color: TONE.amber },
  RECHAZAR_RIVAL: { label: "Rechaza", color: TONE.red },
  PONER_ESCAPARATE: { label: "Véndelo", color: TONE.blue },
  MANTENER_INTOCABLE: { label: "Rechaza", color: TONE.red },
};

type Position = "all" | "POR" | "DEF" | "MC" | "DEL";
type Sort = "value" | "gain" | "points" | "payback" | "trend";

const POSITIONS: { id: Position; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "POR", label: "POR" },
  { id: "DEF", label: "DEF" },
  { id: "MC", label: "MC" },
  { id: "DEL", label: "DEL" },
];

const SORTS: { id: Sort; label: string }[] = [
  { id: "value", label: "Valor" },
  { id: "gain", label: "Revalorización" },
  { id: "payback", label: "Amortización" },
  { id: "points", label: "Puntos" },
  { id: "trend", label: "Previsión 7 días" },
];

const DAY_MS = 86_400_000;

function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.floor((Date.now() - at) / DAY_MS));
}

function ownedFor(days: number | null): string {
  if (days === null) return "";
  if (days === 0) return "hoy";
  if (days === 1) return "hace 1 día";
  if (days < 60) return `hace ${days} días`;
  return `hace ${Math.round(days / 30)} meses`;
}

function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", day: "numeric", month: "short" }).format(date);
}

/** Jugador con lo que han generado sus puntos y si ya está amortizado. */
type Holding = RivalPlayer & {
  earned_eur: number | null;
  return_eur: number | null;
  recovered_pct: number | null;
};

/** Lo que paga tu liga por punto: primas cobradas entre puntos de tu equipo. */
function eurPerPoint(premiums: number | null | undefined, teamPoints: number | null | undefined): number | null {
  if (typeof premiums !== "number" || typeof teamPoints !== "number" || premiums <= 0 || teamPoints <= 0) return null;
  return Math.round(premiums / teamPoints);
}

/** (valor + caja de sus puntos) / coste: desde 1 está amortizado. */
function withPayback(player: RivalPlayer, rate: number | null): Holding {
  const owned = player.points_owned;
  const earned = typeof owned === "number" && rate ? Math.round(owned * rate) : null;
  const cost = player.cost_eur;
  if (typeof cost !== "number" || cost <= 0 || typeof player.market_value !== "number") {
    return { ...player, earned_eur: earned, return_eur: null, recovered_pct: null };
  }
  const back = player.market_value + (earned ?? 0);
  return { ...player, earned_eur: earned, return_eur: back - cost, recovered_pct: back / cost };
}

/** Revalorización desde la compra, en %. */
function gainPct(player: RivalPlayer): number | null {
  return typeof player.roi === "number" ? player.roi * 100 : null;
}

function lockCaption(player: RivalPlayer): string {
  if (player.is_shielded) return "Blindada";
  const lock = player.clause_lock;
  if (lock?.is_locked) return lock.local_date ? `Se abre ${lock.local_date.slice(5).split("-").reverse().join("/")}` : "Con candado";
  return lock?.present ? "Abierta" : "";
}

/* ── Piezas visuales ────────────────────────────────────────────────────── */

/** Barra de amortización: cuánto de lo que pagaste recuperas hoy (valor + caja de sus puntos). */
function PaybackBar({ player }: { player: Holding }) {
  const recovered = player.recovered_pct;
  if (typeof recovered !== "number" || typeof player.cost_eur !== "number" || player.cost_eur <= 0) return null;
  const value = Math.max(0, player.market_value ?? 0) / player.cost_eur;
  const earned = Math.max(0, player.earned_eur ?? 0) / player.cost_eur;
  const done = recovered >= 1;
  // La barra llega al 100 % del coste; si se pasa, se llena entera.
  const valueWidth = Math.min(1, value) * 100;
  const earnedWidth = Math.max(0, Math.min(1, value + earned) * 100 - valueWidth);
  return (
    <div className="mt-2.5">
      <div className="flex items-center justify-between gap-2 text-[11.5px]">
        <span className="font-medium" style={{ color: done ? TONE.green : "rgba(255,255,255,0.55)" }}>
          {done ? "Amortizado" : `Recuperado ${Math.round(recovered * 100)}%`}
        </span>
        <span className="tabular-nums text-white/45">
          {done ? `${signedMoney(player.return_eur)} sobre su coste` : `Faltan ${money(-(player.return_eur ?? 0))}`}
        </span>
      </div>
      <div
        className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-white/[0.08]"
        role="img"
        aria-label={done ? "Amortizado" : `Recuperado el ${Math.round(recovered * 100)} % de lo que costó`}
      >
        <span className="h-full transition-[width] duration-700 ease-out" style={{ width: `${valueWidth}%`, background: done ? TONE.green : "rgba(255,255,255,0.7)" }} />
        <span className="h-full transition-[width] duration-700 ease-out" style={{ width: `${earnedWidth}%`, background: done ? "#5EEAB4" : "#FF9A5A" }} />
      </div>
    </div>
  );
}

/** Pastilla de revalorización desde la compra. */
function GainPill({ value }: { value: number | null }) {
  if (value === null) return null;
  const color = toneOf(value);
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[12px] font-semibold tabular-nums"
      style={{ color, background: Math.abs(value) < 1e-9 ? "rgba(255,255,255,0.06)" : `${color}1f` }}
    >
      {value > 0 ? "▲" : value < 0 ? "▼" : ""} {signedPct(value, Math.abs(value) >= 10 ? 0 : 1).replace(/^[+−]/, "")}
    </span>
  );
}

/** Dónde cae una oferta de la máquina dentro de su horquilla (−10 % … +10 %). */
function MachineRange({ spread }: { spread: number }) {
  const clamped = Math.max(-MACHINE_SPREAD, Math.min(MACHINE_SPREAD, spread));
  const left = ((clamped + MACHINE_SPREAD) / (MACHINE_SPREAD * 2)) * 100;
  return (
    <div className="mt-3" aria-label={`La oferta está a ${signedPct(spread)} de su valor; la máquina ofrece entre −10 % y +10 %`}>
      <div className="relative h-1.5 rounded-full" style={{ background: `linear-gradient(90deg, ${TONE.red}66, rgba(255,255,255,0.12) 50%, ${TONE.green}66)` }}>
        <span className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-white/30" style={{ left: "50%" }} aria-hidden="true" />
        <span
          className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#1c1c1e] bg-white shadow-[0_0_10px_rgba(255,255,255,0.4)]"
          style={{ left: `${left}%` }}
          aria-hidden="true"
        />
      </div>
      <div className="mt-1 flex justify-between text-[11px] tabular-nums text-white/35">
        <span>−10%</span>
        <span>su valor</span>
        <span>+10%</span>
      </div>
    </div>
  );
}

/* ── Ofertas ────────────────────────────────────────────────────────────── */

function OfferRow({ row, photos, index }: { row: AuditoriaVenta; photos: PhotoIndex; index: number }) {
  const [open, setOpen] = useState(false);
  const action = ACTION[row.veredicto_codigo] ?? ACTION.MANTENER_INTOCABLE;
  const offer = row.oferta_activa;
  const machine = offer.comprador === "LaLiga";
  const amount = offer.importe_oferta;
  const spread = offer.spread_pct;
  return (
    <li className="row-in rounded-[1.25rem] bg-[#1c1c1e]" style={{ animationDelay: `${index * 40}ms` }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[4rem] w-full items-center gap-3 px-3.5 py-3 text-left"
      >
        <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={42} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-medium leading-tight text-white">{row.nombre}</span>
          <span className="mt-0.5 block truncate text-[12.5px] text-white/50">
            {machine ? "LaLiga" : offer.comprador || "Oferta"}
            {typeof amount === "number" ? (
              <>
                {" · "}
                <span className="font-medium tabular-nums text-white/80">{money(amount)}</span>
              </>
            ) : null}
            {typeof spread === "number" ? (
              <span className="tabular-nums" style={{ color: toneOf(spread) }}>
                {" "}
                ({signedPct(spread)})
              </span>
            ) : null}
          </span>
        </span>
        <span
          className="shrink-0 rounded-full px-3 py-1.5 text-[13px] font-semibold"
          style={{ color: action.color, background: `${action.color}1f` }}
        >
          {action.label}
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in px-3.5 pb-4">
          <p className="text-[13px] leading-relaxed text-white/60">{row.motivo_detallado}</p>
          {machine && typeof spread === "number" ? <MachineRange spread={spread} /> : null}
          <div className="mt-3 grid grid-cols-3 gap-3">
            <Fact label="Vale hoy" value={money(row.valor_mercado)} />
            <Fact
              label="Previsión 7 días"
              value={signedPct(row.prevision_7d_pct)}
              tone={toneOf(row.prevision_7d_pct)}
            />
            <Fact
              label="Tu once sin él"
              value={row.tu_once_pierde_sin_el < 0.05 ? "Igual" : `−${points(row.tu_once_pierde_sin_el)} pts`}
              tone={row.tu_once_pierde_sin_el < 0.05 ? undefined : TONE.red}
            />
          </div>
        </div>
      ) : null}
    </li>
  );
}

function OffersCard({ sales, photos }: { sales: AuditoriaVenta[]; photos: PhotoIndex }) {
  const offers = sales.filter((row) => row.oferta_activa?.comprador);
  const toSell = sales.filter((row) => !row.oferta_activa?.comprador && row.veredicto_codigo === "PONER_ESCAPARATE");
  const accept = offers.filter((row) => row.veredicto_codigo === "ACEPTAR_YA").length;
  return (
    <section className="home-glass overflow-hidden" aria-label="Ofertas recibidas">
      <div className="flex items-start justify-between gap-3 px-4 pb-2 pt-4">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-white">Ofertas</h3>
          <p className="mt-0.5 text-[12.5px] text-white/45">
            {offers.length
              ? accept
                ? `${accept} de ${offers.length} ${offers.length === 1 ? "merece" : "merecen"} la pena`
                : "Ninguna merece la pena ahora"
              : "Las de LaLiga y los rivales se evalúan solas al llegar"}
          </p>
        </div>
        {offers.length ? (
          <span className="shrink-0 rounded-full bg-white/[0.06] px-2.5 py-1 text-[12.5px] font-semibold tabular-nums text-white">
            {offers.length}
          </span>
        ) : null}
      </div>
      {offers.length ? (
        <ul className="flex flex-col gap-1.5 px-2 pb-2">
          {offers.map((row, index) => (
            <OfferRow key={row.player_id} row={row} photos={photos} index={index} />
          ))}
        </ul>
      ) : (
        <p className="flex items-center gap-2 px-4 pb-4 text-[13px] text-white/50">
          <span className="h-1.5 w-1.5 rounded-full bg-white/30" aria-hidden="true" />
          Sin ofertas por tus jugadores ahora mismo.
        </p>
      )}
      {toSell.length ? (
        <div className="border-t border-white/[0.06] px-4 pb-4 pt-3">
          <p className="text-[12.5px] font-medium text-white/60">Te conviene ponerlos en venta</p>
          <ul className="mt-2.5 flex flex-col gap-2.5">
            {toSell.map((row) => (
              <li key={row.player_id} className="flex items-center gap-2.5">
                <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={32} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium text-white">{row.nombre}</span>
                  <span className="block truncate text-[12px] text-white/45">{row.motivo_detallado}</span>
                </span>
                <span className="shrink-0 text-[13.5px] font-medium tabular-nums text-white">{money(row.valor_mercado)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/* ── Historial ──────────────────────────────────────────────────────────── */

const EVENT_TEXT: Record<string, (name: string) => string> = {
  buy: (name) => `Fichaste a ${name}`,
  clause: (name) => `Cláusula de ${name}`,
  sell: (name) => `Vendiste a ${name}`,
  premium: () => "Premio de jornada",
  initial: () => "Presupuesto inicial",
};

function eventText(event: ActivityEvent): string {
  const kind = String(event.kind || "");
  const name = event.player_name || "un jugador";
  const make = EVENT_TEXT[kind];
  return make ? make(name) : [event.label || kind, event.player_name].filter(Boolean).join(" · ");
}

function HistoryCard({ events, ready }: { events: ActivityEvent[]; ready: boolean }) {
  const [all, setAll] = useState(false);
  const shown = all ? events : events.slice(0, 5);
  return (
    <section className="home-glass overflow-hidden" aria-label="Historial de fichajes y ventas">
      <div className="flex items-start justify-between gap-3 px-4 pb-2 pt-4">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-white">Historial</h3>
          <p className="mt-0.5 text-[12.5px] text-white/45">Fichajes, ventas y premios que mueven tu caja</p>
        </div>
      </div>
      {!ready ? <p className="px-4 pb-2 text-[12.5px] text-[#F59E0B]">Historial sin sincronizar: pulsa Actualizar.</p> : null}
      {events.length ? (
        <>
          <ul className="px-4">
            {shown.map((event, index) => {
              const signed = typeof event.signed_eur === "number" ? event.signed_eur : null;
              const incoming = signed !== null ? signed > 0 : ["sell", "premium", "initial"].includes(String(event.kind));
              const color = incoming ? TONE.green : TONE.red;
              return (
                <li
                  key={`${event.at}-${event.kind}-${index}`}
                  className="flex items-center gap-3 border-b border-white/[0.05] py-2.5 last:border-b-0"
                >
                  <span
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[13px] font-semibold"
                    style={{ color, background: `${color}1a` }}
                    aria-hidden="true"
                  >
                    {incoming ? "↓" : "↑"}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] text-white">{eventText(event)}</span>
                    <span className="block text-[12px] text-white/40">{stamp(event.at) || "Sin fecha"}</span>
                  </span>
                  <span className="shrink-0 text-[14px] font-medium tabular-nums" style={{ color }}>
                    {signed !== null ? signedMoney(signed) : money(event.amount_eur)}
                  </span>
                </li>
              );
            })}
          </ul>
          {events.length > 5 ? (
            <button
              type="button"
              onClick={() => setAll((value) => !value)}
              className="flex min-h-[2.75rem] w-full items-center justify-center gap-1.5 border-t border-white/[0.06] text-[13px] font-medium text-white/60 transition-colors duration-200 ease-out hover:text-white"
            >
              {all ? "Ver menos" : `Ver los ${events.length}`}
              <Chevron open={all} />
            </button>
          ) : (
            <div className="h-2" />
          )}
        </>
      ) : (
        <p className="px-4 pb-4 text-[13px] text-white/50">Aún no hay movimientos sincronizados.</p>
      )}
    </section>
  );
}

/* ── Jugadores ──────────────────────────────────────────────────────────── */

function PlayerCard({
  player,
  photos,
  audit,
  danger,
  rate,
  index,
}: {
  player: Holding;
  photos: PhotoIndex;
  audit: AuditoriaVenta | undefined;
  danger: boolean;
  rate: number | null;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const name = playerName(player);
  const gain = gainPct(player);
  const trend = parsePct(player.prevision_7d_pct);
  const share = titularShare(player.p_titular);
  const days = daysSince(player.acquired_at);
  const owned = player.points_owned;
  const hasCost = typeof player.cost_eur === "number" && player.cost_eur > 0;
  const perPoint = hasCost && typeof owned === "number" && owned > 0 ? player.cost_eur! / owned : null;
  const tags: { label: string; color: string }[] = [];
  if (audit?.oferta_activa?.comprador) tags.push({ label: "Con oferta", color: TONE.green });
  else if (audit?.en_mercado) tags.push({ label: "En venta", color: TONE.blue });
  if (danger) tags.push({ label: "Cláusula en peligro", color: TONE.red });
  const caption = hasCost
    ? days !== null
      ? `${days === 0 ? "Llegó hoy" : `${days} ${days === 1 ? "día" : "días"} contigo`}`
      : "Fichado"
    : player.acquired_at
      ? ownedFor(days)
      : "Plantilla inicial";

  return (
    <li className="row-in" style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="block w-full px-3.5 py-3 text-left"
      >
        <span className="flex items-center gap-3">
          <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={44} />
          <span className="min-w-0 flex-1">
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate text-[15px] font-medium leading-tight text-white">{name}</span>
              <span className="shrink-0 rounded-md bg-white/[0.07] px-1.5 py-px text-[10.5px] font-semibold text-white/55">
                {player.position || "—"}
              </span>
            </span>
            <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
              {caption}
              {typeof owned === "number" ? (
                <>
                  {" · "}
                  <span className="tabular-nums text-[#FFC08A]">{points(owned)} pts</span>
                </>
              ) : null}
            </span>
          </span>
          <span className="shrink-0 text-right">
            <span className="block text-[15px] font-semibold tabular-nums text-white">{money(player.market_value)}</span>
            <span className="mt-0.5 flex justify-end">
              {gain !== null ? (
                <GainPill value={gain} />
              ) : (
                <span className="text-[12px] tabular-nums" style={{ color: toneOf(trend) }}>
                  {trend !== null ? `${signedPct(trend)} 7d` : ""}
                </span>
              )}
            </span>
          </span>
          <Chevron open={open} />
        </span>
        {tags.length ? (
          <span className="mt-2 flex flex-wrap gap-1.5 pl-[3.5rem]">
            {tags.map((tag) => (
              <span
                key={tag.label}
                className="rounded-full px-2 py-0.5 text-[11px] font-medium"
                style={{ color: tag.color, background: `${tag.color}1a` }}
              >
                {tag.label}
              </span>
            ))}
          </span>
        ) : null}
        <span className="block pl-[3.5rem]">
          <PaybackBar player={player} />
        </span>
      </button>
      {open ? (
        <div className="row-in border-t border-white/[0.05] px-3.5 pb-4 pt-3">
          {hasCost ? (
            <div className="flex items-center gap-2 rounded-2xl bg-black/25 px-3 py-2.5 text-[13px] tabular-nums">
              <span className="min-w-0 flex-1">
                <span className="block text-[11px] text-white/40">Pagaste</span>
                <span className="block font-semibold text-white">{money(player.cost_eur)}</span>
              </span>
              <span className="text-white/25" aria-hidden="true">→</span>
              <span className="min-w-0 flex-1 text-center">
                <span className="block text-[11px] text-white/40">Vale hoy</span>
                <span className="block font-semibold text-white">{money(player.market_value)}</span>
              </span>
              <span className="text-white/25" aria-hidden="true">=</span>
              <span className="min-w-0 flex-1 text-right">
                <span className="block text-[11px] text-white/40">Diferencia</span>
                <span className="block font-semibold" style={{ color: toneOf(player.gain_eur) }}>
                  {signedMoney(player.gain_eur)}
                </span>
              </span>
            </div>
          ) : null}
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
            {hasCost ? (
              <Fact
                label="Fichado"
                value={shortDate(player.acquired_at) || "—"}
                hint={[player.acquisition_kind === "clausula" ? "Por cláusula" : "En mercado", days !== null ? `${days} días` : ""].filter(Boolean).join(" · ")}
              />
            ) : null}
            <Fact
              label={player.acquired_at ? "Puntos contigo" : "Puntos"}
              value={typeof owned === "number" ? points(owned) : "—"}
              tone="#FFC08A"
              hint={
                [
                  typeof player.rounds_owned === "number" && player.acquired_at ? `${player.rounds_owned} jornadas` : "",
                  typeof player.points_total === "number" && player.acquired_at ? `${points(player.points_total)} en total` : "",
                ]
                  .filter(Boolean)
                  .join(" · ") || undefined
              }
            />
            <Fact
              label="Ganado con puntos"
              value={typeof player.earned_eur === "number" ? money(player.earned_eur) : "—"}
              tone={typeof player.earned_eur === "number" && player.earned_eur > 0 ? TONE.green : undefined}
              hint={rate ? `${money(rate)} por punto` : "Sin primas registradas"}
            />
            {perPoint !== null ? <Fact label="Coste por punto" value={money(perPoint)} /> : null}
            <Fact label="Media" value={typeof player.average_points === "number" ? `${points(player.average_points)} pts` : "—"} hint="por jornada" />
            <Fact
              label="Próxima jornada"
              value={`${points(player.own_expected_points)} xP`}
              hint={share !== null ? `Titular ${Math.round(share * 100)}%` : undefined}
            />
            <Fact label="Previsión 7 días" value={trend !== null ? signedPct(trend) : "—"} tone={toneOf(trend)} />
            <Fact label="Cláusula" value={money(player.buyout_clause)} hint={lockCaption(player) || undefined} />
          </div>
          {audit && !audit.oferta_activa?.comprador && audit.veredicto_codigo === "PONER_ESCAPARATE" ? (
            <p className="mt-3 rounded-2xl bg-[#0297DE]/10 px-3 py-2.5 text-[13px] leading-relaxed text-white/70">{audit.motivo_detallado}</p>
          ) : null}
          {player.points_owned_estimated ? (
            <p className="mt-3 text-[11.5px] leading-snug text-white/35">
              Puntos contigo estimados por la fecha de fichaje. La caja ganada es una aproximación: puntos × lo que paga tu liga por punto.
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function Highlight({
  title,
  player,
  photos,
  value,
  tone,
}: {
  title: string;
  player: RivalPlayer;
  photos: PhotoIndex;
  value: string;
  tone: string;
}) {
  const name = playerName(player);
  return (
    <article className="home-glass min-w-0 p-3.5">
      <p className="truncate text-[11.5px] text-white/45">{title}</p>
      <div className="mt-2 flex items-center gap-2.5">
        <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={34} />
        <span className="min-w-0">
          <span className="block truncate text-[13.5px] font-medium text-white">{name}</span>
          <span className="block truncate text-[13px] font-semibold tabular-nums" style={{ color: tone }}>
            {value}
          </span>
        </span>
      </div>
    </article>
  );
}

/* ── Pestaña ────────────────────────────────────────────────────────────── */

export function CarteraTab({
  plan,
  squads,
  photos,
  loading,
}: {
  plan: PlanPayload | null;
  squads: SquadsPayload | null;
  photos: PhotoIndex;
  loading: boolean;
}) {
  const [position, setPosition] = useState<Position>("all");
  const [sort, setSort] = useState<Sort>("value");

  const own = squads?.self || null;
  const rate = eurPerPoint(own?.activity_profile?.premiums_eur, own?.points);
  const players = useMemo(() => ((own?.players || []) as RivalPlayer[]).map((player) => withPayback(player, rate)), [own, rate]);
  const audit = useMemo(() => {
    const rows = plan?.auditoria_ventas || [];
    return new Map(rows.map((row) => [String(row.player_id), row]));
  }, [plan]);
  const danger = useMemo(() => {
    const ids = new Set<string>();
    for (const row of plan?.asesor_clausulas?.proteger || []) if (row.riesgo !== "BAJO") ids.add(String(row.player_id));
    for (const row of squads?.shield || []) if (row.player_id) ids.add(String(row.player_id));
    return ids;
  }, [plan, squads]);

  const visible = useMemo(() => {
    const rows = players.filter((player) => position === "all" || (player.position || "").toUpperCase() === position);
    const key = (player: Holding): number => {
      if (sort === "gain") return gainPct(player) ?? -Infinity;
      if (sort === "payback") return player.recovered_pct ?? -Infinity;
      if (sort === "points") return player.points_owned ?? -Infinity;
      if (sort === "trend") return parsePct(player.prevision_7d_pct) ?? -Infinity;
      return player.market_value ?? -Infinity;
    };
    return rows.slice().sort((a, b) => key(b) - key(a));
  }, [players, position, sort]);

  const highlights = useMemo(() => {
    const priced = players.filter((player) => typeof player.roi === "number");
    const best = priced.slice().sort((a, b) => (b.roi ?? 0) - (a.roi ?? 0))[0];
    const worst = priced.slice().sort((a, b) => (a.roi ?? 0) - (b.roi ?? 0))[0];
    const scorer = players
      .filter((player) => typeof player.points_owned === "number")
      .sort((a, b) => (b.points_owned ?? 0) - (a.points_owned ?? 0))[0];
    return { best, worst: worst && worst !== best && (worst.roi ?? 0) < 0 ? worst : undefined, scorer };
  }, [players]);

  if (loading && !own) return <Skeleton />;
  if (!squads || squads.ok === false || !own) {
    return <Empty title="Sin cartera" detail="Pulsa Actualizar para leer tu plantilla y sus valores." />;
  }

  const summary = squads.portfolio?.summary;
  const history = (squads.value_history || []).filter((row) => typeof row.value_eur === "number");
  const total =
    own.market_value_total ?? summary?.market_value_eur ?? players.reduce((sum, player) => sum + (player.market_value ?? 0), 0);
  const first = history.length >= 2 ? history[0].value_eur : null;
  const change = first !== null ? history.at(-1)!.value_eur - first : (own.price_delta_day ?? null);
  const changePct = first ? ((history.at(-1)!.value_eur - first) / first) * 100 : null;
  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : (own.cash_eur ?? null);
  const pricedRows = players.filter((player) => player.recovered_pct !== null);
  const priced = pricedRows.length;
  const amortized = priced ? pricedRows.filter((player) => (player.recovered_pct ?? 0) >= 1).length : null;

  const sales = (plan?.auditoria_ventas || []).slice().sort((a, b) => a.prioridad - b.prioridad);
  const events = squads.portfolio?.recent_events?.length ? squads.portfolio.recent_events : own.activity_profile?.recent_events || [];

  return (
    <div className="grid gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] min-[1100px]:items-start">
      <div className="flex min-w-0 flex-col gap-4">
        <section className="home-feature" aria-label="Resumen de tu cartera">
          <div className="relative flex items-center justify-between gap-3">
            <p className="text-[13px] font-medium text-white/60">Valor de tu plantilla</p>
            <p className="text-[12px] tabular-nums text-white/45">
              {players.length} jugadores
            </p>
          </div>
          <p className="relative mt-2 text-[2.9rem] font-semibold leading-none tracking-[-0.045em] tabular-nums text-white">
            {money(total, 1)}
          </p>
          {change !== null ? (
            <p className="relative mt-2 text-[13.5px] tabular-nums text-white/55">
              <span className="font-semibold" style={{ color: toneOf(change) }}>
                {signedMoney(change)}
                {changePct !== null ? ` · ${signedPct(changePct)}` : ""}
              </span>{" "}
              {first !== null ? `en ${history.length} días` : "hoy"}
            </p>
          ) : null}
          {history.length >= 2 ? (
            <div className="relative mt-4">
              <Sparkline values={history.map((row) => row.value_eur)} label={`Evolución del valor de tu plantilla en ${history.length} días`} />
            </div>
          ) : null}
          <div className="relative mt-5 grid grid-cols-3 gap-2.5">
            <HeroStat value={compact(cash)} label="Caja" tone={cash !== null && cash < 0 ? TONE.red : undefined} />
            <HeroStat value={compact(summary?.gain_eur, true)} label="Ganancia" tone={toneOf(summary?.gain_eur)} />
            <HeroStat
              value={amortized !== null && priced ? `${amortized}/${priced}` : "—"}
              label="Amortizados"
              tone={amortized !== null && priced && amortized === priced ? TONE.green : undefined}
            />
          </div>
        </section>

        <OffersCard sales={sales} photos={photos} />

        <HistoryCard events={events} ready={squads.portfolio_meta?.history_ready !== false} />
      </div>

      <section aria-label="Jugadores de tu plantilla" className="flex min-w-0 flex-col gap-3">
        <SectionHead
          title="Jugadores"
          meta={
            <label className="inline-flex items-center gap-1.5">
              <span className="sr-only">Ordenar por</span>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as Sort)}
                className="h-10 rounded-full border border-white/[0.08] bg-white/[0.04] px-3 text-[13px] text-white outline-none"
              >
                {SORTS.map((item) => (
                  <option key={item.id} value={item.id} className="bg-[#120C09]">
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          }
        />

        {highlights.best || highlights.scorer ? (
          <div className="grid grid-cols-2 gap-2.5">
            {highlights.best ? (
              <Highlight
                title="Mejor fichaje"
                player={highlights.best}
                photos={photos}
                value={signedPct((highlights.best.roi ?? 0) * 100, 0)}
                tone={toneOf(highlights.best.roi)}
              />
            ) : null}
            {highlights.worst ? (
              <Highlight
                title="Pierde valor"
                player={highlights.worst}
                photos={photos}
                value={signedPct((highlights.worst.roi ?? 0) * 100, 0)}
                tone={TONE.red}
              />
            ) : highlights.scorer ? (
              <Highlight
                title="Más puntos contigo"
                player={highlights.scorer}
                photos={photos}
                value={`${points(highlights.scorer.points_owned)} pts`}
                tone="#FFC08A"
              />
            ) : null}
          </div>
        ) : null}

        <div className="eq-scroll -mx-1 px-1" role="toolbar" aria-label="Filtrar por posición">
          {POSITIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={position === item.id}
              onClick={() => setPosition(item.id)}
              className={position === item.id ? "eq-chip eq-chip--on" : "eq-chip"}
            >
              {item.label}
              {item.id === "all" ? <span className="tabular-nums opacity-60">{players.length}</span> : null}
            </button>
          ))}
        </div>

        {visible.length ? (
          <ul className="home-glass overflow-hidden">
            {visible.map((player, index) => (
              <PlayerCard
                key={String(player.player_id)}
                player={player}
                photos={photos}
                audit={audit.get(String(player.player_id))}
                danger={danger.has(String(player.player_id))}
                rate={rate}
                index={index}
              />
            ))}
          </ul>
        ) : (
          <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">
            {players.length ? "Nadie juega en esa posición." : "Tu plantilla no trae jugadores."}
          </p>
        )}
      </section>
    </div>
  );
}

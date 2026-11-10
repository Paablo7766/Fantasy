"use client";

import { useMemo, useState, type ReactNode } from "react";
import { playerName, points, titularShare } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { statusBadgeLabel } from "@/components/ui/StatusBadge";
import type { ActivityProfile, AuditoriaVenta, PlanPayload, RivalPlayer, SquadsPayload, VeredictoVenta } from "@/lib/types";
import { MoveBars, SeasonWaterfall, ValueChart, type MoveRow, type ValuePoint, type WaterfallStep } from "@/components/equipo/CarteraCharts";
import { Crest } from "@/components/ui/Crest";
import {
  Chevron,
  Empty,
  Face,
  Fact,
  Skeleton,
  TONE,
  money,
  projected7d,
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
type Sort = "value" | "day" | "trend" | "gain" | "points" | "xp";

const POSITIONS: { id: Position; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "POR", label: "POR" },
  { id: "DEF", label: "DEF" },
  { id: "MC", label: "MC" },
  { id: "DEL", label: "DEL" },
];

const SORTS: { id: Sort; label: string }[] = [
  { id: "value", label: "Valor" },
  { id: "day", label: "Último día" },
  { id: "trend", label: "7 días" },
  { id: "gain", label: "Rentabilidad" },
  { id: "points", label: "Puntos" },
  { id: "xp", label: "xP" },
];

const DAY_MS = 86_400_000;

function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.floor((Date.now() - at) / DAY_MS));
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
    <div>
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
              label="Valor en 7 días"
              value={projected7d(row.valor_mercado, row.prevision_7d_pct) !== null ? money(projected7d(row.valor_mercado, row.prevision_7d_pct)) : signedPct(row.prevision_7d_pct)}
              tone={toneOf(row.prevision_7d_pct)}
              hint={projected7d(row.valor_mercado, row.prevision_7d_pct) !== null ? `${signedPct(row.prevision_7d_pct)} sobre hoy` : undefined}
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
    <section className="home-glass h-full overflow-hidden" aria-label="Ofertas recibidas">
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

/* ── Tarjetas de análisis ───────────────────────────────────────────────── */

/** Tarjeta de análisis: qué se mide, la cifra que lo resume y el gráfico debajo. */
function Panel({
  title,
  caption,
  figure,
  figureTone,
  figureHint,
  children,
}: {
  title: string;
  caption?: string;
  figure?: string;
  figureTone?: string;
  figureHint?: string;
  children: ReactNode;
}) {
  return (
    <section className="home-glass flex h-full min-w-0 flex-col p-5" aria-label={title}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-white">{title}</h3>
          {caption ? <p className="mt-0.5 text-[12.5px] leading-snug text-white/45">{caption}</p> : null}
        </div>
        {figure ? (
          <div className="shrink-0 text-right">
            <p className="text-[1.15rem] font-semibold leading-none tracking-[-0.02em] tabular-nums" style={{ color: figureTone || "#fff" }}>
              {figure}
            </p>
            {figureHint ? <p className="mt-1 text-[11.5px] tabular-nums text-white/45">{figureHint}</p> : null}
          </div>
        ) : null}
      </div>
      <div className="mt-4 flex flex-1 flex-col justify-center">{children}</div>
    </section>
  );
}

/**
 * Lo que has generado como mánager: premios de jornada, lo ganado al vender y
 * la plusvalía de los que tienes, encadenados hasta el total.
 */
function seasonSteps(profile: ActivityProfile | null | undefined, unrealized: number | null | undefined, rate: number | null): WaterfallStep[] {
  if (!profile) return [];
  const steps: WaterfallStep[] = [];
  if (typeof profile.premiums_eur === "number" && profile.premiums_eur > 0) {
    steps.push({ label: "Premios", value: profile.premiums_eur, hint: rate ? `${money(rate)} por punto` : "de jornada" });
  }
  if (typeof profile.realized_gain_eur === "number") {
    steps.push({
      label: "Ventas",
      value: profile.realized_gain_eur,
      hint: profile.priced_sales ? `${profile.priced_sales} ${profile.priced_sales === 1 ? "venta" : "ventas"}` : "sin precio de compra",
    });
  }
  if (typeof unrealized === "number") {
    steps.push({ label: "Plantilla", value: unrealized, hint: "valor − coste" });
  }
  return steps;
}

/** Casilla del resumen: etiqueta arriba, cifra debajo. */
function Tile({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div className="min-w-0 rounded-[1.1rem] bg-black/40 px-3.5 py-3 backdrop-blur-md">
      <p className="truncate text-[11.5px] text-white/50">{label}</p>
      <p className="mt-1.5 truncate text-[1.1rem] font-semibold leading-none tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {hint ? <p className="mt-1.5 truncate text-[11px] tabular-nums text-white/40">{hint}</p> : null}
    </div>
  );
}

function dayNumber(day: string): number | null {
  const at = Date.parse(`${day.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(at) ? null : Math.round(at / DAY_MS);
}

function madridDay(iso: string | null | undefined): string {
  const date = iso ? new Date(iso) : new Date();
  const safe = Number.isNaN(date.getTime()) ? new Date() : date;
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(safe);
}

/* ── Movimiento de valor ────────────────────────────────────────────────── */

type MoveMode = "day" | "week";

type MoveView = { rows: MoveRow[]; total: number; hint: string; caption: string };

/** Un mismo gráfico con dos lecturas: lo que ya pasó en el último día y lo que el modelo prevé a 7. */
function MovesCard({ views }: { views: Partial<Record<MoveMode, MoveView>> }) {
  const modes = (["day", "week"] as MoveMode[]).filter((mode) => views[mode]);
  const [mode, setMode] = useState<MoveMode>("week");
  const current = views[mode] ? mode : modes[0];
  const view = views[current];
  if (!view) return null;
  return (
    <section className="home-glass flex h-full min-w-0 flex-col p-5" aria-label="Movimiento de valor de tus jugadores">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-white">Movimiento de valor</h3>
          <p key={current} className="row-in mt-0.5 text-[12.5px] leading-snug text-white/45">
            {view.caption}
          </p>
        </div>
        {modes.length > 1 ? (
          <div className="relative grid shrink-0 grid-cols-2 rounded-full bg-white/[0.06] p-[3px]" role="tablist" aria-label="Periodo">
            <span
              className="absolute inset-y-[3px] left-[3px] w-[calc(50%-3px)] rounded-full bg-white transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
              style={{ transform: `translateX(${current === "week" ? "100%" : "0"})` }}
              aria-hidden="true"
            />
            {modes.map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={current === item}
                onClick={() => setMode(item)}
                className={`relative z-10 min-h-[2rem] whitespace-nowrap rounded-full px-3 text-[12px] font-semibold transition-colors duration-300 ${
                  current === item ? "text-[#0b0b0b]" : "text-white/55 hover:text-white"
                }`}
              >
                {item === "day" ? "Último día" : "7 días"}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <p key={`figure-${current}`} className="row-in mt-4 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className="text-[1.6rem] font-semibold leading-none tracking-[-0.03em] tabular-nums" style={{ color: toneOf(view.total) }}>
          {signedMoney(view.total)}
        </span>
        <span className="text-[12px] tabular-nums text-white/45">{view.hint}</span>
      </p>
      <div className="mt-4 flex flex-1 flex-col justify-center">
        <MoveBars key={current} rows={view.rows} />
      </div>
    </section>
  );
}

/* ── Jugadores ──────────────────────────────────────────────────────────── */

/** Columnas de la tabla en escritorio; en móvil solo quedan jugador y valor. */
const ROW_GRID =
  "grid grid-cols-[minmax(0,1fr)_auto_1rem] items-center gap-x-3 min-[900px]:grid-cols-[minmax(0,3fr)_repeat(6,minmax(0,1fr))_1rem] min-[900px]:gap-x-4";

/** Lo que el modelo espera que cambie su valor en 7 días, en euros. */
function weekDelta(player: RivalPlayer): number | null {
  const today = player.market_value;
  if (typeof today !== "number" || today <= 0) return null;
  const next = typeof player.valor_en_7d === "number" ? player.valor_en_7d : projected7d(today, parsePct(player.prevision_7d_pct));
  return next === null ? null : next - today;
}

/** Celda numérica: cifra arriba y un apoyo gris debajo. Solo la cifra lleva color, y solo si es un cambio. */
function Cell({ value, sub, tone, className = "" }: { value: string; sub?: string; tone?: string; className?: string }) {
  return (
    <span className={`min-w-0 text-right ${className}`}>
      <span className="block truncate text-[14px] font-medium tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </span>
      {sub ? <span className="mt-0.5 block truncate text-[11.5px] tabular-nums text-white/40">{sub}</span> : null}
    </span>
  );
}

function PlayerCard({
  player,
  photos,
  audit,
  danger,
  rate,
  total,
}: {
  player: Holding;
  photos: PhotoIndex;
  audit: AuditoriaVenta | undefined;
  danger: boolean;
  rate: number | null;
  total: number;
}) {
  const [open, setOpen] = useState(false);
  const name = playerName(player);
  const gain = gainPct(player);
  const trend = parsePct(player.prevision_7d_pct);
  const share = titularShare(player.p_titular);
  const days = daysSince(player.acquired_at);
  const owned = player.points_owned;
  const value = player.market_value ?? 0;
  const hasCost = typeof player.cost_eur === "number" && player.cost_eur > 0;
  const perPoint = hasCost && typeof owned === "number" && owned > 0 ? player.cost_eur! / owned : null;
  const dayMove = typeof player.price_delta === "number" ? player.price_delta : null;
  const dayPct = dayMove !== null && value - dayMove > 0 ? (dayMove / (value - dayMove)) * 100 : null;
  const week = weekDelta(player);
  const weight = total > 0 ? (value / total) * 100 : null;
  const flags: { label: string; color: string }[] = [];
  if (audit?.oferta_activa?.comprador) flags.push({ label: "Con oferta", color: TONE.green });
  else if (audit?.en_mercado) flags.push({ label: "En venta", color: TONE.blue });
  const estado = statusBadgeLabel(player.official_status || player.player_status);
  if (estado) flags.push({ label: estado, color: estado === "Duda" ? TONE.amber : TONE.red });
  if (danger) flags.push({ label: "Cláusula en peligro", color: TONE.red });

  return (
    <li className="transition-colors duration-300 hover:bg-white/[0.025]" style={open ? { background: "rgba(255,255,255,0.03)" } : undefined}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((state) => !state)} className={`${ROW_GRID} w-full px-4 py-3 text-left min-[900px]:px-5`}>
        <span className="flex min-w-0 items-center gap-3">
          <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={40} />
          <span className="min-w-0">
            <span className="block truncate text-[14.5px] font-medium leading-tight text-white">{name}</span>
            <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[12px] text-white/45">
              <Crest club={player.club} size={14} />
              <span className="shrink-0">{player.position || "—"}</span>
              {flags.slice(0, 2).map((flag, index) => (
                <span key={flag.label} className={`min-w-0 items-center gap-1.5 ${index ? "hidden min-[900px]:inline-flex" : "inline-flex"}`}>
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: flag.color }} aria-hidden="true" />
                  <span className="truncate text-white/60">{flag.label}</span>
                </span>
              ))}
            </span>
          </span>
        </span>

        {/* Valor: en móvil lleva debajo el cambio del día; en escritorio, su peso en la plantilla. */}
        <span className="min-w-0 text-right">
          <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(player.market_value)}</span>
          <span className="mt-0.5 block text-[11.5px] tabular-nums min-[900px]:hidden" style={{ color: toneOf(dayMove) }}>
            {dayMove !== null ? signedMoney(dayMove) : ""}
          </span>
          <span className="mt-0.5 hidden text-[11.5px] tabular-nums text-white/40 min-[900px]:block">
            {weight !== null ? `${Math.round(weight)} % del total` : ""}
          </span>
        </span>
        <Cell
          className="hidden min-[900px]:block"
          value={dayMove !== null ? signedMoney(dayMove) : "—"}
          tone={dayMove !== null ? toneOf(dayMove) : undefined}
          sub={dayPct !== null ? signedPct(dayPct) : undefined}
        />
        <Cell
          className="hidden min-[900px]:block"
          value={week !== null ? signedMoney(week) : "—"}
          tone={week !== null ? toneOf(week) : undefined}
          sub={trend !== null ? signedPct(trend) : undefined}
        />
        <Cell
          className="hidden min-[900px]:block"
          value={hasCost ? signedMoney(player.gain_eur) : "—"}
          tone={hasCost ? toneOf(player.gain_eur) : undefined}
          sub={hasCost ? (gain !== null ? signedPct(gain, Math.abs(gain) >= 10 ? 0 : 1) : undefined) : "Plantilla inicial"}
        />
        <Cell
          className="hidden min-[900px]:block"
          value={typeof owned === "number" ? points(owned) : "—"}
          sub={typeof player.average_points === "number" ? `media ${points(player.average_points)}` : undefined}
        />
        <Cell
          className="hidden min-[900px]:block"
          value={typeof player.own_expected_points === "number" ? points(player.own_expected_points) : "—"}
          sub={share !== null ? `titular ${Math.round(share * 100)} %` : undefined}
        />
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in px-4 pb-5 pt-1 min-[900px]:px-5 min-[900px]:pl-[4.5rem]">
          {player.recovered_pct !== null ? (
            <div className="mb-3.5">
              <PaybackBar player={player} />
            </div>
          ) : null}
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
          <div className="mt-3.5 grid grid-cols-2 gap-x-4 gap-y-3.5 sm:grid-cols-4">
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
            <Fact
              label="Valor en 7 días"
              value={projected7d(player.market_value, trend) !== null ? money(projected7d(player.market_value, trend)) : trend !== null ? signedPct(trend) : "—"}
              tone={toneOf(trend)}
              hint={projected7d(player.market_value, trend) !== null ? `${signedPct(trend)} sobre hoy` : undefined}
            />
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
  const [ascending, setAscending] = useState(false);

  const own = squads?.self || null;
  const rate = eurPerPoint(own?.activity_profile?.premiums_eur, own?.points);
  const players = useMemo(() => ((own?.players || []) as RivalPlayer[]).map((player) => withPayback(player, rate)), [own, rate]);
  const audit = useMemo(() => {
    const rows = plan?.auditoria_ventas || [];
    return new Map(rows.map((row) => [String(row.player_id), row]));
  }, [plan]);
  const danger = useMemo(() => {
    const ids = new Set<string>();
    // Mismo criterio que «En peligro»: el asesor de cláusulas, que mira hasta el próximo bloqueo.
    // (El antiguo `shield` marcaba cualquier cláusula ≤ 1,25× aunque tuviera candado toda la jornada.)
    for (const row of plan?.asesor_clausulas?.proteger || []) {
      if (row.riesgo !== "BAJO" || row.alerta_prioritaria) ids.add(String(row.player_id));
    }
    return ids;
  }, [plan]);

  const visible = useMemo(() => {
    const rows = players.filter((player) => position === "all" || (player.position || "").toUpperCase() === position);
    const key = (player: Holding): number | null => {
      if (sort === "day") return player.price_delta ?? null;
      if (sort === "trend") return weekDelta(player);
      if (sort === "gain") return player.gain_eur ?? null;
      if (sort === "points") return player.points_owned ?? null;
      if (sort === "xp") return player.own_expected_points ?? null;
      return player.market_value ?? null;
    };
    // Sin dato, siempre al final, se ordene hacia donde se ordene.
    return rows.slice().sort((a, b) => {
      const left = key(a);
      const right = key(b);
      if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
      return ascending ? left - right : right - left;
    });
  }, [players, position, sort, ascending]);

  if (loading && !own) return <Skeleton />;
  if (!squads || squads.ok === false || !own) {
    return <Empty title="Sin cartera" detail="Pulsa Actualizar para leer tu plantilla y sus valores." />;
  }

  const summary = squads.portfolio?.summary;
  const total =
    own.market_value_total ?? summary?.market_value_eur ?? players.reduce((sum, player) => sum + (player.market_value ?? 0), 0);
  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : (own.cash_eur ?? null);

  // Serie de valor: solo el tramo con la misma cobertura de precios que el último día.
  // Mezclar días con media plantilla sin precio pintaba un salto que no existió.
  const rawHistory = (squads.value_history || []).filter((row) => typeof row.value_eur === "number" && dayNumber(row.day) !== null);
  const lastCoverage = rawHistory.at(-1)?.coverage ?? 1;
  let from = rawHistory.length;
  while (from > 0 && (rawHistory[from - 1].coverage ?? 1) >= lastCoverage - 0.01) from -= 1;
  const history = rawHistory.slice(from);
  const series: ValuePoint[] = history.map((row) => ({ t: dayNumber(row.day)!, value: row.value_eur, label: shortDate(`${row.day}T12:00:00Z`) }));
  const todayT = dayNumber(madridDay(squads.dashboard_at))!;
  if (series.length && series.at(-1)!.t < todayT) series.push({ t: todayT, value: total, label: "Hoy" });
  else if (series.length) series[series.length - 1] = { ...series.at(-1)!, value: total, label: "Hoy" };

  // Movimiento de valor jugador a jugador: lo previsto a 7 días y lo ya ocurrido en el último día.
  const weekRows: MoveRow[] = players
    .map((player) => {
      const delta = weekDelta(player);
      if (delta === null) return null;
      const today = player.market_value ?? 0;
      return { id: String(player.player_id), name: playerName(player), delta, hint: `${money(today)} hoy → ${money(today + delta)} en 7 días` };
    })
    .filter((row): row is MoveRow => row !== null)
    .sort((a, b) => b.delta - a.delta);
  const forecastDelta = weekRows.length ? weekRows.reduce((sum, row) => sum + row.delta, 0) : null;
  const dayRows: MoveRow[] = players
    .filter((player) => typeof player.price_delta === "number" && typeof player.market_value === "number")
    .map((player) => ({
      id: String(player.player_id),
      name: playerName(player),
      delta: player.price_delta!,
      hint: `${money(player.market_value! - player.price_delta!)} ayer → ${money(player.market_value)} hoy`,
    }))
    .sort((a, b) => b.delta - a.delta);
  const chart: ValuePoint[] =
    series.length >= 2 && forecastDelta !== null
      ? [...series, { t: series.at(-1)!.t + 7, value: total + forecastDelta, label: "en 7 días", forecast: true }]
      : series;

  const first = series.length >= 2 ? series[0] : null;
  const change = first ? total - first.value : (own.price_delta_day ?? null);
  const changePct = first && first.value ? ((total - first.value) / first.value) * 100 : null;
  const dayDelta = typeof own.price_delta_day === "number" ? own.price_delta_day : null;

  // Puesto por valor de plantilla dentro de la liga.
  const rivalValues = (squads.rivals || []).map((rival) => rival.market_value_total).filter((value): value is number => typeof value === "number");
  const valueRank = rivalValues.length ? 1 + rivalValues.filter((value) => value > total).length : null;

  const dayTotal = dayRows.reduce((sum, row) => sum + row.delta, 0);
  const moves: Partial<Record<MoveMode, MoveView>> = {};
  if (dayRows.length) {
    moves.day = {
      rows: dayRows,
      total: dayTotal,
      caption: "Lo que cambió cada jugador en el último día",
      hint: total - dayTotal > 0 ? `${signedPct((dayTotal / (total - dayTotal)) * 100)} · ayer ${money(total - dayTotal, 1)}` : "",
    };
  }
  if (weekRows.length && forecastDelta !== null) {
    moves.week = {
      rows: weekRows,
      total: forecastDelta,
      caption: "Lo que prevé el modelo para cada jugador",
      hint: total > 0 ? `${signedPct((forecastDelta / total) * 100)} · llegaría a ${money(total + forecastDelta, 1)}` : "",
    };
  }

  const steps = seasonSteps(own.activity_profile, summary?.gain_eur, rate);
  const seasonTotal = steps.reduce((sum, step) => sum + step.value, 0);

  const sales = (plan?.auditoria_ventas || []).slice().sort((a, b) => a.prioridad - b.prioridad);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <section className="home-feature" aria-label="Resumen de tu cartera">
        <div className="grid gap-6 min-[1100px]:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] min-[1100px]:items-end">
          <div className="min-w-0">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[13px] font-medium text-white/65">Valor de tu plantilla</p>
              {valueRank !== null ? (
                <p className="rounded-full bg-black/35 px-2.5 py-1 text-[11.5px] font-medium tabular-nums text-white/75 backdrop-blur-md">
                  {valueRank}.º de {rivalValues.length + 1} en la liga
                </p>
              ) : null}
            </div>
            <p className="mt-2.5 text-[3.1rem] font-semibold leading-none tracking-[-0.045em] tabular-nums text-white">{money(total, 1)}</p>
            {change !== null ? (
              <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] tabular-nums text-white/60">
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-black/40 px-2.5 py-1 font-semibold backdrop-blur-md"
                  style={{ color: toneOf(change) }}
                >
                  {change > 0 ? "▲" : change < 0 ? "▼" : ""} {signedMoney(change)}
                  {changePct !== null ? ` · ${signedPct(changePct)}` : ""}
                </span>
                <span>{first ? `desde el ${first.label}` : "hoy"}</span>
              </p>
            ) : null}
            <div className="mt-5 grid grid-cols-2 gap-2">
              <Tile label="Caja" value={money(cash, 1)} tone={cash !== null && cash < 0 ? TONE.red : undefined} />
              <Tile label="Patrimonio" value={cash !== null ? money(total + cash, 1) : "—"} hint="plantilla + caja" />
              <Tile label="Hoy" value={dayDelta !== null ? signedMoney(dayDelta) : "—"} tone={dayDelta !== null ? toneOf(dayDelta) : undefined} hint="cambio de valor" />
              <Tile
                label="Próximos 7 días"
                value={forecastDelta !== null ? signedMoney(forecastDelta) : "—"}
                tone={forecastDelta !== null ? toneOf(forecastDelta) : undefined}
                hint="previsión del modelo"
              />
            </div>
          </div>

          {chart.length >= 2 ? (
            <div className="min-w-0">
              <ValueChart
                points={chart}
                summary={`Valor de tu plantilla actual: ${money(first?.value)} el ${first?.label}, ${money(total)} hoy${
                  forecastDelta !== null ? ` y ${money(total + forecastDelta)} previstos en 7 días` : ""
                }`}
              />
              <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-white/45">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-0.5 w-4 rounded-full bg-[#FFB27A]" aria-hidden="true" />
                  Tu plantilla actual
                </span>
                {forecastDelta !== null ? (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-4 border-t-2 border-dotted border-white/60" aria-hidden="true" />
                    Previsión
                  </span>
                ) : null}
                {from > 0 ? <span>Antes del {series[0].label} faltaban precios de parte de la plantilla</span> : null}
              </p>
            </div>
          ) : null}
        </div>
      </section>

      <div className="grid gap-4 min-[768px]:grid-cols-2 min-[1100px]:grid-cols-3">
        {moves.day || moves.week ? <MovesCard views={moves} /> : null}

        {steps.length ? (
          <Panel title="Tu temporada como mánager" caption="De dónde sale lo que has generado" figure={signedMoney(seasonTotal)} figureTone={toneOf(seasonTotal)}>
            <SeasonWaterfall steps={steps} />
          </Panel>
        ) : null}

        <div className="min-w-0 min-[768px]:col-span-2 min-[1100px]:col-span-1">
          <OffersCard sales={sales} photos={photos} />
        </div>
      </div>

      <section aria-label="Jugadores de tu plantilla" className="home-glass min-w-0 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 pb-3 pt-4 min-[900px]:px-5">
          <h3 className="text-[15px] font-semibold text-white">
            Jugadores <span className="ml-1 font-normal tabular-nums text-white/40">{visible.length}</span>
          </h3>
          <div className="flex w-full min-w-0 items-center justify-between gap-2 min-[900px]:w-auto">
            <div className="eq-scroll min-w-0 !gap-0.5" role="toolbar" aria-label="Filtrar por posición">
              {POSITIONS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={position === item.id}
                  onClick={() => setPosition(item.id)}
                  className={`min-h-[2rem] shrink-0 rounded-full px-3 text-[12.5px] font-medium transition-colors duration-300 ${
                    position === item.id ? "bg-white text-[#0b0b0b]" : "text-white/55 hover:text-white"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <label className="shrink-0 min-[900px]:hidden">
              <span className="sr-only">Ordenar por</span>
              <select
                value={sort}
                onChange={(event) => {
                  setSort(event.target.value as Sort);
                  setAscending(false);
                }}
                className="h-8 rounded-full bg-white/[0.06] px-2.5 text-[12.5px] text-white outline-none"
              >
                {SORTS.map((item) => (
                  <option key={item.id} value={item.id} className="bg-[#141414]">
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {/* Cabecera de la tabla: cada columna ordena, y repetir el clic invierte el sentido. */}
        <div className={`${ROW_GRID} hidden border-y border-white/[0.06] px-5 py-2 min-[900px]:grid`}>
          <span className="text-[11.5px] text-white/40">Jugador</span>
          {SORTS.map((item) => {
            const on = sort === item.id;
            return (
              <button
                key={item.id}
                type="button"
                aria-pressed={on}
                aria-label={`Ordenar por ${item.label}${on ? (ascending ? ", de menor a mayor" : ", de mayor a menor") : ""}`}
                onClick={() => {
                  if (on) setAscending((state) => !state);
                  else {
                    setSort(item.id);
                    setAscending(false);
                  }
                }}
                className={`inline-flex items-center justify-end gap-1 text-right text-[11.5px] transition-colors duration-200 ${on ? "font-semibold text-white" : "text-white/40 hover:text-white/75"}`}
              >
                {item.label}
                <svg viewBox="0 0 8 8" className={`h-2 w-2 transition-transform duration-300 ${on ? "opacity-100" : "opacity-0"} ${ascending ? "rotate-180" : ""}`} aria-hidden="true">
                  <path d="M1 2.5 4 6l3-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            );
          })}
          <span aria-hidden="true" />
        </div>

        {visible.length ? (
          <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06] min-[900px]:border-t-0">
            {visible.map((player) => (
              <PlayerCard
                key={String(player.player_id)}
                player={player}
                photos={photos}
                audit={audit.get(String(player.player_id))}
                danger={danger.has(String(player.player_id))}
                rate={rate}
                total={total}
              />
            ))}
          </ul>
        ) : (
          <p className="border-t border-white/[0.06] px-4 py-8 text-center text-[13.5px] text-white/50">
            {players.length ? "Nadie juega en esa posición." : "Tu plantilla no trae jugadores."}
          </p>
        )}
      </section>
    </div>
  );
}

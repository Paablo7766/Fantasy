"use client";

import { useMemo, useState, type ReactNode } from "react";
import { playerName, points, titularShare } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { statusBadgeLabel } from "@/components/ui/StatusBadge";
import type { ActivityProfile, AuditoriaVenta, PlanPayload, RivalPlayer, SquadsPayload, VeredictoVenta } from "@/lib/types";
import {
  AllocationDonut,
  ForecastBars,
  SeasonWaterfall,
  ValueChart,
  type ForecastRow,
  type Slice,
  type ValuePoint,
  type WaterfallStep,
} from "@/components/equipo/CarteraCharts";
import {
  Chevron,
  Empty,
  Face,
  Fact,
  SectionHead,
  Skeleton,
  TONE,
  forecastHint,
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
    steps.push({ label: "Premios de jornada", value: profile.premiums_eur, hint: rate ? `${money(rate)} por punto` : undefined });
  }
  if (typeof profile.realized_gain_eur === "number") {
    steps.push({
      label: "Ventas",
      value: profile.realized_gain_eur,
      hint: profile.priced_sales ? `en ${profile.priced_sales} ${profile.priced_sales === 1 ? "venta" : "ventas"}` : "sin ventas con precio de compra",
    });
  }
  if (typeof unrealized === "number") {
    steps.push({ label: "Plantilla actual", value: unrealized, hint: "valor de hoy frente a lo que pagaste" });
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

const POSITION_LABEL: Record<string, string> = { POR: "Porteros", DEF: "Defensas", MC: "Medios", DEL: "Delanteros" };

function dayNumber(day: string): number | null {
  const at = Date.parse(`${day.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(at) ? null : Math.round(at / DAY_MS);
}

function madridDay(iso: string | null | undefined): string {
  const date = iso ? new Date(iso) : new Date();
  const safe = Number.isNaN(date.getTime()) ? new Date() : date;
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(safe);
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
  const estado = statusBadgeLabel(player.official_status || player.player_status);
  if (estado) tags.push({ label: estado, color: estado === "Duda" ? TONE.amber : TONE.red });
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
                  {forecastHint(player.market_value, trend)?.replace("→ ", "") ?? ""}
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
    // Mismo criterio que «En peligro»: el asesor de cláusulas, que mira hasta el próximo bloqueo.
    // (El antiguo `shield` marcaba cualquier cláusula ≤ 1,25× aunque tuviera candado toda la jornada.)
    for (const row of plan?.asesor_clausulas?.proteger || []) {
      if (row.riesgo !== "BAJO" || row.alerta_prioritaria) ids.add(String(row.player_id));
    }
    return ids;
  }, [plan]);

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

  // Previsión a 7 días, jugador a jugador.
  const forecastRows: ForecastRow[] = players
    .map((player) => {
      const today = player.market_value ?? 0;
      const pct = parsePct(player.prevision_7d_pct);
      const next = typeof player.valor_en_7d === "number" ? player.valor_en_7d : projected7d(today, pct);
      if (next === null || today <= 0) return null;
      return { id: String(player.player_id), name: playerName(player), delta: next - today, pct, today, next };
    })
    .filter((row): row is ForecastRow => row !== null)
    .sort((a, b) => b.delta - a.delta);
  const forecastDelta = forecastRows.length ? forecastRows.reduce((sum, row) => sum + row.delta, 0) : null;
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

  // Reparto por posición.
  const slices: Slice[] = ["POR", "DEF", "MC", "DEL"]
    .map((id) => {
      const rows = players.filter((player) => (player.position || "").toUpperCase() === id);
      return { id, label: POSITION_LABEL[id], value: rows.reduce((sum, player) => sum + (player.market_value ?? 0), 0), count: rows.length };
    })
    .filter((slice) => slice.count > 0);
  const heaviest = players.slice().sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))[0];
  const heaviestShare = heaviest && total > 0 ? ((heaviest.market_value ?? 0) / total) * 100 : null;

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
        {slices.length ? (
          <Panel
            title="Dónde está tu dinero"
            caption={
              heaviest && heaviestShare !== null && heaviestShare >= 20
                ? `${playerName(heaviest)} pesa el ${Math.round(heaviestShare)} % de tu plantilla`
                : "Valor repartido por posición"
            }
          >
            <AllocationDonut slices={slices} total={slices.reduce((sum, slice) => sum + slice.value, 0)} />
          </Panel>
        ) : null}

        {forecastRows.length && forecastDelta !== null ? (
          <Panel
            title="Próximos 7 días"
            caption="Quién sube y quién baja de valor"
            figure={signedMoney(forecastDelta)}
            figureTone={toneOf(forecastDelta)}
            figureHint={total > 0 ? `${signedPct((forecastDelta / total) * 100)} · ${money(total + forecastDelta, 1)}` : undefined}
          >
            <ForecastBars rows={forecastRows} />
          </Panel>
        ) : null}

        {steps.length ? (
          <div className="min-w-0 min-[768px]:col-span-2 min-[1100px]:col-span-1">
            <Panel
              title="Tu temporada como mánager"
              caption="Lo que has generado y de dónde sale"
              figure={signedMoney(seasonTotal)}
              figureTone={toneOf(seasonTotal)}
            >
              <SeasonWaterfall steps={steps} />
            </Panel>
          </div>
        ) : null}
      </div>

      <div className="grid gap-4 min-[1100px]:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] min-[1100px]:items-start">
        <OffersCard sales={sales} photos={photos} />

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
    </div>
  );
}

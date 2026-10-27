"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ErrorCard, Skeleton } from "@/components/Feedback";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import {
  clockLabel,
  deltaEur,
  deltaTone,
  eur,
  eurShort,
  glass,
  initials,
  multiple,
  playerName,
  points,
  pct,
  roiPct,
  stamp,
} from "@/lib/format";
import {
  applyLiquidity,
  financialIndex,
  liquidityRead,
  temperatureClasses,
  temperatureLabel,
  type LiquidityRead,
} from "@/lib/liquidity";
import { enrichSquadsPayload } from "@/lib/squadEnrich";
import { squadHoldings, squadPatrimonio, squadTotals } from "@/lib/squadTotals";
import type {
  ActivityEvent,
  ClauseIntelOffer,
  ClauseIntelPayload,
  ClauseRow,
  NeedRival,
  NeedsPayload,
  RivalIntelPayload,
  RivalPlayer,
  RivalSquad,
  SquadsPayload,
  TrendsPayload,
} from "@/lib/types";

type RivalSort = "rank" | "patrimonio" | "cash" | "value" | "delta";
type SheetTab = "plantilla" | "mercado" | "clausulas";

function rivalLabel(squad: RivalSquad): string {
  return squad.manager_name || squad.fantasy_team_name || String(squad.team_id || "Rival");
}

function ledgerFromNeeds(needs: NeedsPayload | null, teamId: string): NeedRival["ledger"] | null {
  return (needs?.ok ? needs.rivals || [] : []).find((row) => String(row.team_id) === teamId)?.ledger ?? null;
}

function sortKey(squad: RivalSquad, mode: RivalSort): number {
  if (mode === "cash") {
    // Ordena por la caja calibrada: es la que de verdad puede gastar.
    const cash = liquidityRead(squad).calibratedCash;
    return typeof cash === "number" ? cash : Number.NEGATIVE_INFINITY;
  }
  if (mode === "value") {
    const value = squadTotals(squad).market_value_total;
    return typeof value === "number" ? value : Number.NEGATIVE_INFINITY;
  }
  if (mode === "delta") {
    const delta = squadTotals(squad).price_delta_day;
    return typeof delta === "number" ? delta : Number.NEGATIVE_INFINITY;
  }
  if (mode === "patrimonio") {
    const patrimonio = squadPatrimonio(squad);
    return typeof patrimonio === "number" ? patrimonio : Number.NEGATIVE_INFINITY;
  }
  return Number.NEGATIVE_INFINITY;
}

function sortSquads(list: RivalSquad[], mode: RivalSort): RivalSquad[] {
  return list.slice().sort((a, b) => {
    if (mode === "rank") {
      const left = typeof a.rank === "number" ? a.rank : 9999;
      const right = typeof b.rank === "number" ? b.rank : 9999;
      if (left !== right) return left - right;
      return rivalLabel(a).localeCompare(rivalLabel(b), "es");
    }
    const delta = sortKey(b, mode) - sortKey(a, mode);
    if (delta) return delta;
    return rivalLabel(a).localeCompare(rivalLabel(b), "es");
  });
}

function windowLabel(intel: ClauseIntelPayload | null): string {
  if (!intel || intel.ok === false) return "Sin lectura";
  if (intel.clause_window_open === true) {
    const close = intel.clause_market_close;
    if (close?.local_date && close?.local_time) return `Abierta · cierra ${close.local_date} ${close.local_time}`;
    return "Abierta";
  }
  if (intel.clause_window_open === false) return "Cerrada";
  return "Ventana s/d";
}

const POS_ORDER = ["POR", "DEF", "MC", "MED", "DEL"];
const POS_LABEL: Record<string, string> = {
  POR: "Portería",
  DEF: "Defensa",
  MC: "Mediocampo",
  MED: "Mediocampo",
  DEL: "Delantera",
};

function positionGroups(players: RivalPlayer[]) {
  const buckets = new Map<string, RivalPlayer[]>();
  for (const player of players) {
    const pos = String(player.position || "?").toUpperCase();
    buckets.set(pos, [...(buckets.get(pos) || []), player]);
  }
  const ordered = POS_ORDER.filter((pos) => buckets.has(pos)).map((pos) => ({
    position: pos,
    label: POS_LABEL[pos] || pos,
    rows: buckets.get(pos) || [],
  }));
  for (const [pos, rows] of buckets) {
    if (!POS_ORDER.includes(pos)) ordered.push({ position: pos, label: POS_LABEL[pos] || pos, rows });
  }
  return ordered;
}

function acquisitionLabel(kind: string | null | undefined): string {
  if (kind === "clausula") return "Cláusula";
  if (kind === "mercado") return "Mercado";
  return "Sin origen";
}

function rankTone(rank: number | null | undefined, isSelf: boolean): string {
  if (isSelf) return "rival-rank rival-rank--self";
  if (rank === 1) return "rival-rank rival-rank--gold";
  if (rank === 2) return "rival-rank rival-rank--silver";
  if (rank === 3) return "rival-rank rival-rank--bronze";
  return "rival-rank";
}

function eventTone(event: ActivityEvent): string {
  if (event.kind === "sell" || (typeof event.signed_eur === "number" && event.signed_eur > 0)) return "text-mint";
  if (event.kind === "buy" || event.kind === "clause") return "text-coral";
  return "text-muted-strong";
}

function ThermometerIcon({ className = "h-3 w-3" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <path d="M6.6 9.1V3.6a1.4 1.4 0 0 1 2.8 0v5.5a2.6 2.6 0 1 1-2.8 0Z" strokeLinejoin="round" />
      <path d="M8 6.6v4.1" strokeLinecap="round" />
    </svg>
  );
}

/** Barra del termómetro: ancho = ``temperature``; color = confianza de la cota. */
function ThermometerBar({ read, className = "w-12" }: { read: LiquidityRead; className?: string }) {
  const classes = temperatureClasses(read.level);
  const width = read.temperaturePct === null ? 0 : Math.min(100, Math.max(3, read.temperaturePct));
  return (
    <span
      className={`inline-flex h-1.5 shrink-0 overflow-hidden rounded-full bg-[color:var(--line)] ${className}`}
      aria-hidden="true"
    >
      <span className={`block h-full rounded-full ${classes.bar}`} style={{ width: `${width}%` }} />
    </span>
  );
}

/**
 * Insignia del grupo de control.
 *
 * - «Calibrado»: la cota sobraba y se apretó al saldo observado (descuento).
 * - «Fuera de libro»: la cota se quedaba corta; hay dinero que los libros no
 *   explican y se declara como arbitraje en vez de taparlo.
 */
function CalibratedBadge({ read, compact = false }: { read: LiquidityRead; compact?: boolean }) {
  const classes = temperatureClasses(read.level);
  const size = compact ? "text-[10px]" : "text-[11px]";
  const arbitrage = read.arbitrageEur !== null && read.arbitrageEur > 0 ? read.arbitrageEur : null;
  if (arbitrage !== null) {
    return (
      <span
        className={`badge badge--bad ${size} gap-1`}
        title={`${eur(arbitrage)} de caja observada quedan fuera de los libros: la cota se queda corta.`}
      >
        <ThermometerIcon />
        Fuera de libro
      </span>
    );
  }
  if (!read.tightened) return null;
  const hint =
    read.temperaturePct === null
      ? "Cota calibrada contra el saldo observado."
      : `Cota calibrada contra el saldo observado · termómetro ${read.temperaturePct} %.`;
  return (
    <span className={`${classes.badge} ${size} gap-1`} title={hint}>
      <ThermometerIcon />
      Calibrado
    </span>
  );
}

/**
 * Caja con la cota calibrada como valor principal.
 *
 * - Cota apretada (``tightened``): la cifra anterior se queda tachada y tenue al
 *   lado, para ver de dónde sale el descuento sin perder el dato original.
 * - Cota corta (``raised``): no es un descuento; el saldo observado manda y la
 *   cifra de los libros se anota con una flecha, nunca tachada, porque no se
 *   está corrigiendo hacia abajo.
 */
function CalibratedCash({
  read,
  size = "sm",
  showOriginal = true,
}: {
  read: LiquidityRead;
  size?: "sm" | "lg";
  showOriginal?: boolean;
}) {
  const classes = temperatureClasses(read.level);
  const main = read.calibratedCash ?? read.cash;
  const former = read.tightened || read.raised ? read.cash : null;
  const showsFormer = showOriginal && typeof former === "number" && former !== main;
  const fmt = size === "lg" ? eur : eurShort;
  const text = size === "lg" ? "text-lg" : "text-[12px]";
  const aside = size === "lg" ? "text-[12px]" : "text-[11px]";
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
      <span className={`metric-value ${text} ${classes.text}`} title={typeof main === "number" ? eur(main) : undefined}>
        {fmt(main)}
      </span>
      {showsFormer && read.tightened ? (
        <s
          className={`${aside} font-normal text-faint decoration-[color:var(--line-strong)]`}
          title={`Cota publicada antes de calibrar: ${eur(former)}`}
        >
          {fmt(former)}
        </s>
      ) : null}
      {showsFormer && !read.tightened ? (
        <span className={`${aside} font-normal text-faint`} title={`Los libros solo justifican ${eur(former)}`}>
          <span aria-hidden="true">↑</span> libros {fmt(former)}
        </span>
      ) : null}
    </span>
  );
}

/** Límite de puja con el desglose de la banda de liquidez. */
function LiquidityBand({ read, label = "Límite de puja" }: { read: LiquidityRead; label?: string }) {
  const classes = temperatureClasses(read.level);
  const arbitrage = read.arbitrageEur !== null && read.arbitrageEur > 0 ? read.arbitrageEur : null;
  return (
    <div className="min-w-0 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="metric-label">{label}</p>
        <span className={`${classes.badge} gap-1 text-[10px]`} title={temperatureLabel(read.level)}>
          <ThermometerIcon />
          {temperatureLabel(read.level)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className={`metric-value text-lg ${classes.text}`}>{eurShort(read.bidLimit)}</span>
        {read.bidTightened && typeof read.rawBidLimit === "number" ? (
          <s
            className="text-[11px] text-faint decoration-[color:var(--line-strong)]"
            title={`Tope sin calibrar: ${eur(read.rawBidLimit)}`}
          >
            {eurShort(read.rawBidLimit)}
          </s>
        ) : null}
        {!read.bidTightened &&
        typeof read.rawBidLimit === "number" &&
        typeof read.bidLimit === "number" &&
        read.bidLimit > read.rawBidLimit ? (
          <span className="text-[11px] text-faint" title={`Los libros solo justifican ${eur(read.rawBidLimit)}`}>
            <span aria-hidden="true">↑</span> libros {eurShort(read.rawBidLimit)}
          </span>
        ) : null}
        <span className="ml-auto inline-flex items-center gap-1.5">
          <ThermometerBar read={read} className="w-14" />
          <span className={`metric-value text-[11px] ${classes.text}`}>
            {read.temperaturePct === null ? "s/d" : `${read.temperaturePct} %`}
          </span>
        </span>
      </div>
      <p className="mt-1 text-[11px] leading-4 text-muted">
        {arbitrage === null ? (
          <span className="text-faint">Sin margen de error detectado fuera de los libros.</span>
        ) : (
          <>
            <span className="font-medium text-coral">{eurShort(arbitrage)}</span> sin explicar
            <span className="text-faint"> · arbitraje</span>
          </>
        )}
      </p>
      <details className="mt-2 border-t border-[color:var(--line)] pt-2">
        <summary className="cursor-pointer text-[10.5px] font-medium text-faint transition-colors hover:text-muted-strong">
          Desglose de la cota
        </summary>
        <dl className="mt-1.5 space-y-1 text-[11px]">
          {(
            [
              ["Cota de libros", read.cash],
              ["Cota calibrada", read.calibratedCash],
              ["Saldo observado", read.reconciliation?.observed_cash_eur ?? null],
              ["Puja sin calibrar", read.rawBidLimit],
              ["Arbitraje (sin explicar)", read.arbitrageEur],
              ["Hueco contable", read.reconciliation?.gap_eur ?? null],
              ["σ de caja", read.reconciliation?.posterior_sigma_eur ?? null],
            ] as const
          )
            .filter(([, value]) => typeof value === "number")
            .map(([name, value]) => {
              const outOfBooks = name.startsWith("Arbitraje") && (value ?? 0) > 0;
              return (
                <div key={name} className="flex items-baseline justify-between gap-3">
                  <dt className="text-muted">{name}</dt>
                  <dd className={`metric-value ${outOfBooks ? "text-coral" : "text-ink"}`}>{eur(value)}</dd>
                </div>
              );
            })}
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-muted">Temperatura</dt>
            <dd className={`metric-value ${classes.text}`}>
              {read.temperaturePct === null ? "s/d" : `${read.temperaturePct} %`}
              <span className="ml-1.5 font-sans text-[10px] font-normal text-faint">
                · {temperatureLabel(read.level).toLowerCase()}
              </span>
            </dd>
          </div>
          {read.reconciliation?.cover_probability !== undefined &&
          read.reconciliation.cover_probability !== null ? (
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Cubre la caja real</dt>
              <dd className={`metric-value ${classes.text}`}>
                {Math.round(read.reconciliation.cover_probability * 100)} %
              </dd>
            </div>
          ) : null}
        </dl>
        <p className="mt-1.5 text-[10.5px] leading-4 text-faint">
          Temperatura alta = la cota cuadra con el saldo observado. Si baja, la cota es frágil y la puja se acerca al
          riesgo contable.
        </p>
      </details>
    </div>
  );
}

function Metric({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div>
      <p className="metric-label">{label}</p>
      <p className={`metric-value mt-1 text-lg ${tone || "text-ink"}`}>{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-faint">{hint}</p> : null}
    </div>
  );
}

function listMetric(squad: RivalSquad, sort: RivalSort): { label: string; value: string; tone?: string } {
  const totals = squadTotals(squad);
  if (sort === "delta") {
    return { label: "Δ hoy", value: deltaEur(totals.price_delta_day), tone: deltaTone(totals.price_delta_day) };
  }
  if (sort === "cash") {
    // La caja calibrada ya va en la línea del nombre; aquí manda la puja máxima,
    // que es la cifra accionable cuando el techo se aprieta.
    const read = liquidityRead(squad);
    return {
      label: read.bidTightened ? "Puja calibrada" : "Puja máx.",
      value: eurShort(read.bidLimit),
      tone: temperatureClasses(read.level).text,
    };
  }
  if (sort === "patrimonio") {
    return { label: "Patrimonio", value: eur(squadPatrimonio(squad)), tone: "text-gold" };
  }
  if (sort === "value") {
    return { label: "Valor", value: eur(totals.market_value_total), tone: "text-ink" };
  }
  const holdings = squadHoldings(squad);
  if (typeof holdings.gain_eur === "number") {
    return { label: "Plusvalía", value: deltaEur(holdings.gain_eur), tone: deltaTone(holdings.gain_eur) };
  }
  return { label: "Δ hoy", value: deltaEur(totals.price_delta_day), tone: deltaTone(totals.price_delta_day) };
}

function RivalCard({
  squad,
  isSelf,
  sort,
  onOpen,
}: {
  squad: RivalSquad;
  isSelf: boolean;
  sort: RivalSort;
  onOpen: () => void;
}) {
  const name = rivalLabel(squad);
  const teamName = squad.fantasy_team_name && squad.fantasy_team_name !== name ? squad.fantasy_team_name : null;
  const metric = listMetric(squad, sort);
  const read = liquidityRead(squad);
  return (
    <button type="button" onClick={onOpen} className={`rival-card group w-full px-4 py-3.5 text-left ${isSelf ? "rival-card--self" : ""}`}>
      <div className="flex items-center gap-3">
        <div className={rankTone(squad.rank, isSelf)}>
          {typeof squad.rank === "number" ? squad.rank : initials(name).slice(0, 2)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[15px] font-semibold tracking-tight text-ink">{name}</span>
            {isSelf ? <span className="badge badge--good text-[10px]">Tú</span> : null}
            <CalibratedBadge read={read} compact />
          </div>
          <p className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-[12px] text-muted">
            {teamName ? <span className="truncate">{teamName} ·</span> : null}
            <span>caja</span>
            <CalibratedCash read={read} />
            {read.temperaturePct !== null && (read.tightened || read.level !== "alta") ? (
              <span className="inline-flex items-center gap-1 text-[10.5px] text-faint">
                <ThermometerBar read={read} className="w-8" />
                {read.temperaturePct} %
              </span>
            ) : null}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className={`metric-value text-sm ${metric.tone || "text-ink"}`}>{metric.value}</p>
          <p className="text-[10px] text-faint">{metric.label}</p>
          {sort === "cash" && read.bidTightened && typeof read.rawBidLimit === "number" ? (
            <p className="text-[10px] text-faint" title={`Tope sin calibrar: ${eur(read.rawBidLimit)}`}>
              antes {eurShort(read.rawBidLimit)}
            </p>
          ) : null}
        </div>
      </div>
    </button>
  );
}

function PlayerDeal({
  player,
  events,
  open,
  onToggle,
}: {
  player: RivalPlayer;
  events: ActivityEvent[];
  open: boolean;
  onToggle: () => void;
}) {
  const related = events.filter((event) => event.player_id && String(event.player_id) === String(player.player_id));
  return (
    <div className={`rival-player-wrap ${open ? "rival-player-wrap--open" : ""}`}>
      <button type="button" onClick={onToggle} className="rival-player w-full text-left">
        <PlayerAvatar player={player} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold tracking-tight text-ink">{playerName(player)}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-faint">
            <span className="rival-pos">{player.position || "?"}</span>
            {player.club ? <span>{player.club}</span> : null}
            {player.acquisition_kind ? <span>{acquisitionLabel(player.acquisition_kind)}</span> : null}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className={`metric-value text-xs ${deltaTone(player.gain_eur)}`}>{deltaEur(player.gain_eur)}</p>
          <p className="text-[10px] text-faint">{typeof player.roi === "number" ? roiPct(player.roi) : "sin coste"}</p>
        </div>
      </button>
      {open ? (
        <div className="rival-deal">
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
            <Metric label="Pagó" value={eur(player.cost_eur)} hint={acquisitionLabel(player.acquisition_kind)} />
            <Metric label="Vale hoy" value={eur(player.market_value)} />
            <Metric label="Plusvalía" value={deltaEur(player.gain_eur)} tone={deltaTone(player.gain_eur)} />
            <Metric label="ROI" value={roiPct(player.roi)} tone={deltaTone(player.gain_eur)} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
            <span>Cláusula {eur(player.buyout_clause)}</span>
            <span>{clockLabel(player.clause_lock)}</span>
            {player.acquired_at ? <span>Fichado {stamp(player.acquired_at)}</span> : null}
            {typeof player.p_titular === "number" ? <span>Titular {pct(player.p_titular)}</span> : null}
            {typeof player.own_expected_points === "number" ? <span>{points(player.own_expected_points)} pts</span> : null}
          </div>
          {typeof player.cost_eur !== "number" ? (
            <p className="mt-3 text-[12px] leading-5 text-muted">
              No hay compra ni cláusula en el historial. No se puede calcular rentabilidad de este fichaje.
            </p>
          ) : null}
          {related.length ? (
            <ul className="mt-3 space-y-1.5 border-t border-[color:var(--line)] pt-3">
              {related.map((event, index) => (
                <li key={`${event.at}-${index}`} className="flex items-center justify-between gap-3 text-[12px]">
                  <span className="text-muted-strong">
                    {event.label}
                    <span className="text-faint"> · {stamp(event.at) || "sin fecha"}</span>
                  </span>
                  <span className={`metric-value ${eventTone(event)}`}>{eur(event.amount_eur)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function MarketTab({
  squad,
  ledger,
}: {
  squad: RivalSquad;
  ledger?: NeedRival["ledger"] | null;
}) {
  const profile = squad.activity_profile;
  const holdings = squadHoldings(squad);
  const spent = (profile?.purchases_eur ?? ledger?.purchases_eur ?? 0) + (profile?.clauses_eur ?? ledger?.clauses_eur ?? 0);
  const sales = profile?.sales_eur ?? ledger?.sales_eur;
  const events = profile?.recent_events || [];
  const priced = (squad.players || [])
    .filter((player) => typeof player.gain_eur === "number")
    .slice()
    .sort((a, b) => (b.gain_eur ?? 0) - (a.gain_eur ?? 0));
  const winners = priced.filter((player) => (player.gain_eur ?? 0) > 0).slice(0, 3);
  const losers = priced
    .filter((player) => (player.gain_eur ?? 0) < 0)
    .slice()
    .sort((a, b) => (a.gain_eur ?? 0) - (b.gain_eur ?? 0))
    .slice(0, 3);
  const sold = events.filter((event) => event.kind === "sell");

  return (
    <section className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <Metric label="Ha cobrado" value={eur(sales)} hint="Ventas en el historial" tone="text-mint" />
        <Metric
          label="Plusvalía vendida"
          value={deltaEur(profile?.realized_gain_eur)}
          tone={deltaTone(profile?.realized_gain_eur)}
          hint={
            typeof profile?.priced_sales === "number" && profile.priced_sales > 0
              ? `${profile.priced_sales} venta(s) con coste conocido`
              : "Sin ventas con coste"
          }
        />
        <Metric label="Ha gastado" value={eur(spent || null)} hint="Compras + cláusulas" />
        <Metric
          label="Plantilla ahora"
          value={deltaEur(holdings.gain_eur)}
          tone={deltaTone(holdings.gain_eur)}
          hint={typeof holdings.priced_count === "number" ? `${holdings.priced_count} con coste · ${roiPct(holdings.roi)}` : undefined}
        />
      </div>
      {ledger?.cash_is_ceiling ? (
        <p className="text-[12px] leading-5 text-faint">
          La caja reconstruida es un techo: algunas subidas de cláusula no aparecen en el historial.
        </p>
      ) : null}

      {winners.length || losers.length ? (
        <div className="grid gap-5 sm:grid-cols-2">
          <DealList title="Mejores fichajes" rows={winners} />
          <DealList title="Peores fichajes" rows={losers} />
        </div>
      ) : (
        <p className="text-sm text-muted">Sin costes rastreados en esta plantilla. Actualiza para sincronizar el historial.</p>
      )}

      {sold.length ? (
        <div>
          <p className="eyebrow">Dinero sacado</p>
          <ul className="mt-2 space-y-2">
            {sold.map((event, index) => (
              <li key={`${event.at}-${index}`} className="flex items-center justify-between gap-3 text-sm">
                <span className="min-w-0 truncate text-ink">{event.player_name || "Venta"}</span>
                <span className="metric-value text-mint">{eur(event.amount_eur)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {events.length ? (
        <div>
          <p className="eyebrow">Últimos movimientos</p>
          <ul className="mt-2 divide-y divide-[color:var(--line)]">
            {events.map((event, index) => (
              <li key={`${event.at}-${event.kind}-${index}`} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-sm text-ink">
                    {event.label}
                    {event.player_name ? <span className="text-muted"> · {event.player_name}</span> : null}
                  </p>
                  <p className="text-[10px] text-faint">{stamp(event.at) || "Sin fecha"}</p>
                </div>
                <span className={`metric-value text-sm ${eventTone(event)}`}>{eur(event.amount_eur)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-muted">Sin historial de operaciones para este manager.</p>
      )}
    </section>
  );
}

function DealList({ title, rows }: { title: string; rows: RivalPlayer[] }) {
  return (
    <div>
      <p className="eyebrow">{title}</p>
      {rows.length ? (
        <ul className="mt-2 space-y-2">
          {rows.map((player) => (
            <li key={String(player.player_id)} className="flex items-center gap-2">
              <PlayerAvatar player={player} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{playerName(player)}</p>
                <p className="text-[10px] text-faint">
                  {eur(player.cost_eur)} → {eur(player.market_value)}
                </p>
              </div>
              <div className="text-right">
                <p className={`metric-value text-xs ${deltaTone(player.gain_eur)}`}>{deltaEur(player.gain_eur)}</p>
                <p className="text-[10px] text-faint">{roiPct(player.roi)}</p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-muted">Nadie en esta lista.</p>
      )}
    </div>
  );
}

function RivalSheet({
  squad,
  isSelf,
  needs,
  clauses,
  clauseOffers,
  onClose,
}: {
  squad: RivalSquad | null;
  isSelf: boolean;
  needs: NeedsPayload | null;
  clauses: ClauseRow[];
  clauseOffers: ClauseIntelOffer[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<SheetTab>("plantilla");
  const [openPlayer, setOpenPlayer] = useState<string | null>(null);
  const teamId = squad?.team_id != null ? String(squad.team_id) : null;

  // Al cambiar de rival, la ficha vuelve a la pestaña de plantilla. Se ajusta
  // durante el render (patrón de React) en vez de sembrarlo desde un efecto.
  const [shownTeamId, setShownTeamId] = useState(teamId);
  if (shownTeamId !== teamId) {
    setShownTeamId(teamId);
    setTab("plantilla");
    setOpenPlayer(null);
  }

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (squad && !dialog.open) dialog.showModal();
    if (!squad && dialog.open) dialog.close();
  }, [squad]);

  if (!squad || !teamId) {
    return (
      <dialog ref={ref} className="bid-dialog rival-dialog" onClose={onClose}>
        <div className="bid-dialog__body" />
      </dialog>
    );
  }

  const holdings = squadHoldings(squad);
  const read = liquidityRead(squad);
  const players = squad.players || [];
  const groups = positionGroups(players);
  const events = squad.activity_profile?.recent_events || [];
  const teamClauses = clauses.filter((row) => String(row.team_id) === teamId);
  // La ficha muestra la plantilla **entera** con cláusula: ``squads.clauses``
  // solo publica las que cumplen la regla de oro y dejaría fuera a la mayoría.
  const teamSheetClauses: ClauseRow[] = players
    .filter((player) => typeof player.buyout_clause === "number" && player.buyout_clause > 0)
    .map((player) => ({
      team_id: teamId,
      manager_name: squad.manager_name,
      fantasy_team_name: squad.fantasy_team_name,
      player_id: player.player_id,
      name: player.name,
      nickname: player.nickname,
      position: player.position,
      club: player.club,
      image_url: player.image_url,
      buyout_clause_eur: player.buyout_clause,
      market_value: player.market_value,
      average_points: player.own_expected_points ?? null,
      clause_multiple: player.clause_multiple ?? null,
      is_shielded: player.is_shielded === true,
      is_locked: player.clause_lock?.is_locked ?? undefined,
      clause_lock: player.clause_lock ?? null,
      clause_rule: teamClauses.find((row) => String(row.player_id) === String(player.player_id))?.clause_rule ?? null,
    }))
    .sort((a, b) => {
      const da = `${a.clause_lock?.local_date || "9999-99-99"}T${a.clause_lock?.local_time || "99:99"}`;
      const db = `${b.clause_lock?.local_date || "9999-99-99"}T${b.clause_lock?.local_time || "99:99"}`;
      if (da !== db) return da.localeCompare(db);
      return (b.buyout_clause_eur || 0) - (a.buyout_clause_eur || 0);
    });
  const tabs: { id: SheetTab; label: string }[] = [
    { id: "plantilla", label: "Plantilla" },
    { id: "mercado", label: "Mercado" },
    { id: "clausulas", label: "Cláusulas" },
  ];

  return (
    <dialog
      ref={ref}
      className="bid-dialog rival-dialog"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="bid-dialog__body scroll-thin">
        <div className="rival-sheet-head">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className={`${rankTone(squad.rank, isSelf)} !h-12 !w-12 !text-base`}>
                {typeof squad.rank === "number" ? squad.rank : initials(rivalLabel(squad))}
              </div>
              <div className="min-w-0">
                <p className="eyebrow">{isSelf ? "Tu equipo" : "Rival"}</p>
                <h3 className="truncate text-xl font-semibold tracking-tight text-ink">{rivalLabel(squad)}</h3>
              </div>
            </div>
            <button type="button" className="btn btn-secondary shrink-0" onClick={onClose}>
              Cerrar
            </button>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[color:var(--line)] pt-4">
            <div>
              <div className="flex flex-wrap items-center gap-1.5">
                <p className="metric-label">Caja</p>
                <CalibratedBadge read={read} compact />
              </div>
              <p className="mt-1">
                <CalibratedCash read={read} size="lg" />
              </p>
              {read.tightened && read.temperaturePct !== null ? (
                <p className="mt-1 flex items-center gap-1.5 text-[10.5px] text-faint">
                  <ThermometerBar read={read} className="w-10" />
                  {read.temperaturePct} % de confianza
                </p>
              ) : null}
            </div>
            <Metric label="Cobrado" value={eur(squad.activity_profile?.sales_eur)} tone="text-mint" />
            <Metric label="Plusvalía" value={deltaEur(holdings.gain_eur)} tone={deltaTone(holdings.gain_eur)} />
          </div>

          <div className="seg mt-4 w-full">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? "seg__btn seg__btn--active" : "seg__btn"}
                onClick={() => setTab(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4">
          <LiquidityBand read={read} label="Banda de liquidez · puja máxima" />
        </div>

        {tab === "plantilla" ? (
          <section className="mt-5 space-y-5">
            <p className="text-[12px] text-muted">Pulsa un jugador para ver qué pagó, cuánto vale y su ROI.</p>
            {groups.length ? (
              groups.map((group) => (
                <div key={group.position}>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
                    {group.label}
                    <span className="ml-2 font-mono font-normal">{group.rows.length}</span>
                  </p>
                  <div className="space-y-2">
                    {group.rows.map((player) => {
                      const id = String(player.player_id);
                      return (
                        <PlayerDeal
                          key={id}
                          player={player}
                          events={events}
                          open={openPlayer === id}
                          onToggle={() => setOpenPlayer(openPlayer === id ? null : id)}
                        />
                      );
                    })}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted">Esta plantilla no trae jugadores.</p>
            )}
          </section>
        ) : null}

        {tab === "mercado" ? (
          <section className="mt-5">
            <MarketTab squad={squad} ledger={ledgerFromNeeds(needs, teamId)} />
          </section>
        ) : null}

        {tab === "clausulas" ? (
          <section className="mt-5 space-y-4">
            {clauseOffers.map((row) => (
              <div key={String(row.player_id)} className="flex items-center gap-3">
                <PlayerAvatar player={row} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-ink">{playerName(row)}</p>
                  <p className="text-[11px] text-muted">
                    {eur(row.buyout_clause_eur)}
                    {typeof row.points_delta === "number" ? ` · +${points(row.points_delta)} pts` : ""}
                  </p>
                </div>
                <span className={row.decision === "PAGAR" ? "badge badge--good" : "badge badge--warn"}>
                  {row.decision === "PAGAR" ? "Pagar" : "Alternativa"}
                </span>
              </div>
            ))}
            <div className="space-y-2 border-t border-[color:var(--line)] pt-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-faint">
                Plantilla completa con cláusula
                <span className="ml-2 font-mono font-normal">{teamSheetClauses.length}</span>
              </p>
              {teamSheetClauses.map((row) => (
                <div key={`${row.team_id}-${row.player_id}`} className="flex items-baseline justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">
                      {playerName(row)}
                      {typeof row.average_points === "number" ? (
                        <span className="text-faint"> · {points(row.average_points)} pts</span>
                      ) : null}
                    </p>
                    <p className="text-[11px] text-muted">
                      {eur(row.buyout_clause_eur)} · {multiple(row.clause_multiple)} · {clockLabel(row.clause_lock)}
                      {row.is_shielded ? " · blindado" : ""}
                    </p>
                  </div>
                  {row.clause_rule ? (
                    <span className={`shrink-0 text-[11px] font-medium ${row.clause_rule === "A" ? "text-mint" : "text-gold"}`}>
                      Regla {row.clause_rule}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[11px] text-faint">fuera de regla</span>
                  )}
                </div>
              ))}
              {!teamSheetClauses.length ? (
                <p className="text-sm text-muted">Este rival no tiene cláusulas en esta lectura.</p>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </dialog>
  );
}

function ExtraBlock({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-[color:var(--line)]">
      <button type="button" className="flex w-full items-center justify-between gap-3 py-3.5 text-left" onClick={onToggle}>
        <span className="text-sm font-semibold text-ink">{title}</span>
        <span className="text-[12px] text-muted">
          {count} · {open ? "Ocultar" : "Ver"}
        </span>
      </button>
      {open ? <div className="pb-4">{children}</div> : null}
    </div>
  );
}

export function RivalsDashboard({
  squads,
  needs,
  trends = null,
  clauseIntel = null,
  rivalIntel = null,
  clauseIntelLoading = false,
  loading = false,
}: {
  squads: SquadsPayload | null;
  needs: NeedsPayload | null;
  trends?: TrendsPayload | null;
  clauseIntel?: ClauseIntelPayload | null;
  /** Auditoría de caja (``/api/rival-intel``): trae la cota calibrada. */
  rivalIntel?: RivalIntelPayload | null;
  clauseIntelLoading?: boolean;
  loading?: boolean;
}) {
  const [selectedTeam, setSelectedTeam] = useState<string | null>(null);
  const [rivalSort, setRivalSort] = useState<RivalSort>("rank");
  const [showOffers, setShowOffers] = useState(false);
  const [showClauses, setShowClauses] = useState(false);
  const view = useMemo(() => enrichSquadsPayload(squads, trends), [squads, trends]);
  const financials = useMemo(
    () => financialIndex(rivalIntel?.ok === false ? null : rivalIntel?.teams),
    [rivalIntel],
  );
  // Sin la cota calibrada la tarjeta mentiría: se fusiona la auditoría de caja
  // sobre el perfil de plantillas antes de ordenar o de abrir la ficha.
  const rivals = useMemo(
    () =>
      (view?.rivals || [])
        .map((row) => applyLiquidity(row, financials.get(String(row.team_id))))
        .filter((row): row is RivalSquad => row !== null),
    [view, financials],
  );
  const own = useMemo(
    () => applyLiquidity(view?.self, view?.self ? financials.get(String(view.self.team_id)) : null),
    [view, financials],
  );
  const ownTeamId = own?.team_id != null ? String(own.team_id) : null;
  const leagueSquads = useMemo(() => {
    const all = [...rivals];
    if (own) all.push(own);
    return all;
  }, [rivals, own]);
  const sortedSquads = useMemo(() => sortSquads(leagueSquads, rivalSort), [leagueSquads, rivalSort]);
  const calibratedCount = useMemo(() => leagueSquads.filter((row) => liquidityRead(row).tightened).length, [leagueSquads]);
  const selectedSquad = useMemo(
    () => (selectedTeam ? leagueSquads.find((row) => String(row.team_id) === selectedTeam) || null : null),
    [selectedTeam, leagueSquads],
  );

  if (loading && !squads) return <Skeleton title="Rivales" rows={6} />;
  if (!view || view.ok === false) {
    return <ErrorCard title="Rivales" payload={view || squads || { error: { message: "Sin plantillas." } }} brief />;
  }

  const clauses = view.clauses || [];
  const offers = clauseIntel?.ok !== false ? clauseIntel?.offers || [] : [];
  const selectedOffers = selectedTeam ? offers.filter((row) => String(row.team_id) === selectedTeam) : [];

  return (
    <article className={glass("p-4 md:p-6")}>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Liga</p>
          <h2 className="section-title mt-1">{leagueSquads.length} managers</h2>
          <p className="section-support">Lista corta. Entra en un rival para ver plantilla y su mercado.</p>
          {calibratedCount ? (
            <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-faint">
              <ThermometerIcon className="h-3.5 w-3.5 text-mint" />
              <span className="font-medium text-mint">{calibratedCount}</span>
              caja(s) calibrada(s) por el grupo de control: la puja máxima ya descuenta el riesgo contable.
            </p>
          ) : null}
        </div>
        <div className="seg flex-wrap justify-end">
          {(
            [
              ["rank", "Puesto"],
              ["patrimonio", "Patrimonio"],
              ["cash", "Caja"],
              ["delta", "Δ hoy"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setRivalSort(key)}
              className={rivalSort === key ? "seg__btn seg__btn--active" : "seg__btn"}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <div className="divide-y divide-[color:var(--line)] rounded-2xl border border-[color:var(--line)] bg-[color:var(--surface)]">
        {sortedSquads.length ? (
          sortedSquads.map((squad) => {
            const teamId = String(squad.team_id);
            return (
              <RivalCard
                key={teamId}
                squad={squad}
                sort={rivalSort}
                isSelf={ownTeamId !== null && teamId === ownTeamId}
                onOpen={() => setSelectedTeam(teamId)}
              />
            );
          })
        ) : (
          <p className="px-4 py-6 text-sm text-muted">La liga no devolvió plantillas.</p>
        )}
      </div>

      <div className="mt-8">
        <ExtraBlock title="Clausulazos" count={offers.length} open={showOffers} onToggle={() => setShowOffers((value) => !value)}>
          <p className="mb-2 text-[11px] text-faint">{windowLabel(clauseIntel)}</p>
          {clauseIntelLoading && !clauseIntel ? (
            <p className="text-sm text-muted">Calculando…</p>
          ) : offers.length ? (
            <ul className="space-y-2">
              {offers.map((row) => (
                <li key={String(row.player_id)}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-3 text-left"
                    onClick={() => row.team_id != null && setSelectedTeam(String(row.team_id))}
                  >
                    <span className="min-w-0 truncate text-sm text-ink">
                      {playerName(row)}
                      <span className="text-muted"> · {row.manager_name || ""}</span>
                    </span>
                    <span className="metric-value text-xs text-mint">
                      {typeof row.points_delta === "number" ? `+${points(row.points_delta)}` : eur(row.buyout_clause_eur)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Ningún clausulazo mejora el XI ahora.</p>
          )}
        </ExtraBlock>
        <ExtraBlock title="Cláusulas interesantes" count={clauses.length} open={showClauses} onToggle={() => setShowClauses((value) => !value)}>
          {clauses.length ? (
            <ul className="space-y-2">
              {clauses.map((row) => (
                <li key={`${row.team_id}-${row.player_id}`}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-3 text-left"
                    onClick={() => row.team_id != null && setSelectedTeam(String(row.team_id))}
                  >
                    <span className="min-w-0 truncate text-sm text-ink">
                      {playerName(row)}
                      <span className="text-muted"> · {row.manager_name || ""}</span>
                    </span>
                    <span className="metric-value text-xs">{eur(row.buyout_clause_eur)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Ninguna cláusula cumple la regla de oro.</p>
          )}
          <p className="mt-2 text-[11px] leading-4 text-faint">
            Solo aparecen los chollos de la regla de oro. Para ver <strong className="font-semibold">todas</strong> las
            cláusulas de la liga, con la subida de cada jugador: pestaña «Todas las cláusulas».
          </p>
        </ExtraBlock>
      </div>

      <RivalSheet
        squad={selectedSquad}
        isSelf={selectedTeam !== null && selectedTeam === ownTeamId}
        needs={needs}
        clauses={clauses}
        clauseOffers={selectedOffers}
        onClose={() => setSelectedTeam(null)}
      />
    </article>
  );
}

"use client";

import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { ForcedSaleBadge, ForecastPct } from "@/components/liga/StrategyBits";
import { clockLabel, deltaEur, deltaTone, eur, playerName, points, pct, roiPct, stamp } from "@/lib/core/format";
import { squadHoldings } from "@/lib/liga/squadTotals";
import type { ActivityEvent, NeedRival, RivalPlayer, RivalSquad } from "@/lib/types";
import { Metric } from "./Metric";
import { acquisitionLabel, eventTone } from "./shared";

export function PlayerDeal({
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
            {player.venta_forzada_rival ? <ForcedSaleBadge /> : null}
            <ForecastPct value={player.prevision_7d_pct} />
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

export function MarketTab({
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

export function DealList({ title, rows }: { title: string; rows: RivalPlayer[] }) {
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

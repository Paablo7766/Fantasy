"use client";

import { useMemo, useState } from "react";
import { ComputerOffersPanel } from "@/components/ComputerOffersPanel";
import { ErrorCard, Skeleton } from "@/components/Feedback";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import {
  deltaEur,
  deltaTone,
  eur,
  glass,
  playerName,
  roiPct,
  stamp,
} from "@/lib/format";
import type { ActivityEvent, RivalPlayer, SquadsPayload } from "@/lib/types";

type SortKey = "gain" | "roi" | "value" | "cost";

function acquisitionLabel(kind: string | null | undefined): string {
  if (kind === "clausula") return "Cláusula";
  if (kind === "mercado") return "Mercado";
  return "s/d";
}

function EventRow({ event, showManager }: { event: ActivityEvent; showManager?: boolean }) {
  const signed = event.signed_eur;
  const tone =
    typeof signed === "number" ? (signed > 0 ? "text-mint" : signed < 0 ? "text-coral" : "text-muted") : "text-muted";
  return (
    <li className="flex items-start justify-between gap-3 border-t border-[color:var(--line)] py-2.5 first:border-t-0">
      <div className="min-w-0">
        <p className="text-sm font-medium tracking-tight text-ink">
          {event.label || event.kind}
          {event.player_name ? (
            <span className="font-normal text-muted-strong">
              {" "}
              · {event.player_name}
            </span>
          ) : null}
        </p>
        <p className="mt-0.5 text-[11px] text-faint">
          {showManager && event.manager_name ? `${event.manager_name} · ` : ""}
          {stamp(event.at) || "Sin fecha"}
        </p>
      </div>
      <p className={`metric-value shrink-0 text-sm ${tone}`}>{eur(event.amount_eur)}</p>
    </li>
  );
}

function SummaryTile({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-4 py-3">
      <p className="metric-label">{label}</p>
      <p className={`metric-value mt-1 text-xl ${tone || "text-ink"}`}>{value}</p>
      {note ? <p className="mt-1 text-[11px] text-faint">{note}</p> : null}
    </div>
  );
}

export function PortfolioDashboard({ squads, loading }: { squads: SquadsPayload | null; loading?: boolean }) {
  const [sort, setSort] = useState<SortKey>("gain");

  const own = squads?.self;
  const portfolio = squads?.portfolio;
  const meta = squads?.portfolio_meta;
  const summary = portfolio?.summary;
  const historyReady = meta?.history_ready === true;
  const recentEvents =
    (portfolio?.recent_events?.length ? portfolio.recent_events : null) ??
    (own?.activity_profile?.recent_events?.length ? own.activity_profile.recent_events : null) ??
    [];
  const players = useMemo(() => {
    const list = (own?.players || []) as RivalPlayer[];
    const copy = list.slice();
    copy.sort((a, b) => {
      if (sort === "value") {
        return (b.market_value ?? -1) - (a.market_value ?? -1);
      }
      if (sort === "cost") {
        return (b.cost_eur ?? -1) - (a.cost_eur ?? -1);
      }
      if (sort === "roi") {
        return (b.roi ?? -999) - (a.roi ?? -999);
      }
      const ga = typeof a.gain_eur === "number" ? a.gain_eur : -999_999_999;
      const gb = typeof b.gain_eur === "number" ? b.gain_eur : -999_999_999;
      return gb - ga;
    });
    return copy;
  }, [own?.players, sort]);

  if (loading && !squads) return <Skeleton title="Mi cartera" rows={8} />;
  if (!squads || squads.ok === false) {
    return <ErrorCard title="Mi cartera" payload={squads || { error: { message: "Sin plantilla." } }} />;
  }

  const priced = summary?.priced_count ?? 0;
  const total = summary?.player_count ?? players.length;

  return (
    <div className="flex flex-col gap-5">
      <article className={glass("p-4 md:p-5")}>
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">Inversión</p>
            <h2 className="section-title mt-1">Rentabilidad de fichajes</h2>
            <p className="section-support">
              Coste según historial de la liga (compras y cláusulas). Sin movimiento registrado, el coste queda sin dato.
            </p>
          </div>
          <p className="font-mono text-[11px] text-faint">
            {priced}/{total} jugadores con coste conocido
          </p>
        </div>

        {!historyReady ? (
          <div className="mb-4 rounded-2xl border border-[color:var(--line-strong)] bg-[color:var(--gold-soft)] px-4 py-3 text-sm leading-6 text-muted-strong">
            <p className="font-medium text-ink">Historial de la liga sin sincronizar</p>
            <p className="mt-1">
              La cartera necesita el historial de compras y cláusulas. Pulsa{" "}
              <span className="font-medium text-ink">Actualizar</span> y espera a que termine{" "}
              <span className="font-medium text-ink">Caja</span> (puede tardar un minuto la primera vez). Eventos en
              liga: {meta?.activity_event_count ?? 0} · movimientos tuyos: {meta?.ledger_event_count ?? 0}.
              {(meta?.activity_event_count ?? 0) > 0 && (meta?.ledger_event_count ?? 0) === 0 ? (
                <span className="mt-1 block text-xs text-muted">
                  La liga ya tiene actividad pero tu libro no está enlazado; vuelve a actualizar o revisa que la sesión
                  de LALIGA sea la del mánager correcto.
                </span>
              ) : null}
            </p>
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryTile label="Coste fichajes" value={eur(summary?.cost_eur)} note="Suma de adquisiciones rastreadas" />
          <SummaryTile label="Valor actual" value={eur(summary?.market_value_eur)} note="Valor de mercado hoy" />
          <SummaryTile
            label="Plusvalía"
            value={deltaEur(summary?.gain_eur)}
            tone={deltaTone(summary?.gain_eur)}
            note="Valor − coste (solo con historial)"
          />
          <SummaryTile
            label="ROI agregado"
            value={roiPct(summary?.roi)}
            tone={deltaTone(summary?.gain_eur)}
            note="Sobre el coste rastreado"
          />
        </div>
      </article>

      <ComputerOffersPanel players={players} />

      <div className="grid gap-5 xl:grid-cols-[1.4fr_0.9fr]">
        <article className={glass("p-4 md:p-5")}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h3 className="section-title text-[1.05rem]">Jugadores en plantilla</h3>
            <div className="seg flex-wrap">
              {(
                [
                  ["gain", "Plusvalía"],
                  ["roi", "ROI"],
                  ["value", "Valor"],
                  ["cost", "Coste"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSort(key)}
                  className={sort === key ? "seg__btn seg__btn--active" : "seg__btn"}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="scroll-thin overflow-x-auto">
            <table className="table-dense w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr>
                  <th>Jugador</th>
                  <th className="text-right">Coste</th>
                  <th className="text-right">Valor</th>
                  <th className="text-right">Plusvalía</th>
                  <th className="text-right">ROI</th>
                  <th>Origen</th>
                </tr>
              </thead>
              <tbody>
                {players.length ? (
                  players.map((player) => (
                    <tr key={String(player.player_id)}>
                      <td>
                        <div className="flex items-center gap-2.5">
                          <PlayerAvatar player={player} size="sm" />
                          <div className="min-w-0">
                            <p className="truncate font-medium tracking-tight">{playerName(player)}</p>
                            <p className="text-[11px] text-faint">
                              {player.position}
                              {player.club ? ` · ${player.club}` : ""}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="metric-value text-right">{eur(player.cost_eur)}</td>
                      <td className="metric-value text-right text-ink">{eur(player.market_value)}</td>
                      <td className={`metric-value text-right ${deltaTone(player.gain_eur)}`}>
                        {deltaEur(player.gain_eur)}
                      </td>
                      <td className={`metric-value text-right ${deltaTone(player.gain_eur)}`}>
                        {roiPct(player.roi)}
                      </td>
                      <td className="text-xs text-muted-strong">
                        {acquisitionLabel(player.acquisition_kind)}
                        {player.acquired_at ? (
                          <span className="mt-0.5 block text-[10px] text-faint">{stamp(player.acquired_at)}</span>
                        ) : null}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="!text-muted">
                      La plantilla no trae jugadores.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className={glass("p-4 md:p-5")}>
          <h3 className="section-title text-[1.05rem]">Tu historial reciente</h3>
          <p className="mt-1 text-xs text-muted">Movimientos de caja ligados a tu mánager en la liga.</p>
          <ul className="mt-4 max-h-[520px] overflow-auto scroll-thin">
            {recentEvents.length ? (
              recentEvents.map((event, index) => (
                <EventRow key={`${event.at}-${event.kind}-${index}`} event={event} />
              ))
            ) : (
              <li className="rounded-xl border border-dashed border-[color:var(--line-strong)] px-3 py-4 text-sm text-muted">
                Aún no hay movimientos en el historial sincronizado.
              </li>
            )}
          </ul>
        </article>
      </div>

      {(squads.activity_feed || []).length ? (
        <article className={glass("p-4 md:p-5")}>
          <h3 className="section-title text-[1.05rem]">Actividad de la liga</h3>
          <p className="mt-1 text-xs text-muted">Últimas operaciones de todos los managers (solo lectura).</p>
          <ul className="mt-4 grid gap-0 md:grid-cols-2 md:gap-x-6">
            {(squads.activity_feed || []).map((event, index) => (
              <EventRow key={`feed-${event.team_id}-${event.at}-${index}`} event={event} showManager />
            ))}
          </ul>
        </article>
      ) : null}
    </div>
  );
}

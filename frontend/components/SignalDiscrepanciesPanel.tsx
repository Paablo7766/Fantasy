"use client";

import { useMemo } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { buildSignalDiscrepancies, discrepancyKindLabel } from "@/lib/signalDiscrepancies";
import { accel, eur, glass, pct, playerName } from "@/lib/format";
import type { MarketDecision, TrendsPayload } from "@/lib/types";

function signalChip(signal: string | null | undefined): string {
  if (signal === "up") return "↑";
  if (signal === "down") return "↓";
  return "—";
}

function SideCell({
  label,
  signal,
  delta,
  maxBid,
  tone,
}: {
  label: string;
  signal: string | null | undefined;
  delta: number | null | undefined;
  maxBid: number | null | undefined;
  tone: "mint" | "gold";
}) {
  const color = tone === "mint" ? "text-mint" : "text-gold";
  return (
    <div className="min-w-[7.5rem]">
      <p className="text-[10px] uppercase tracking-wide text-faint">{label}</p>
      <p className={`metric-value text-sm ${color}`}>
        {signalChip(signal)}
        {typeof delta === "number" ? ` ${accel(delta)}` : ""}
      </p>
      <p className="text-[11px] text-muted">max {eur(maxBid)}</p>
    </div>
  );
}

export function SignalDiscrepanciesPanel({
  trends,
  loading = false,
}: {
  trends: TrendsPayload | null;
  loading?: boolean;
}) {
  const rows = useMemo(() => buildSignalDiscrepancies(trends), [trends]);

  if (loading && !trends) return null;
  if (!rows.length) return null;

  return (
    <section className={glass("p-4 md:p-5")}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="eyebrow">Discrepancias</p>
          <h2 className="section-title mt-1 text-[1.05rem]">AF vs modelo propio en una fila</h2>
          <p className="section-support">
            Señales que se contradicen: prioriza revisar antes de pujar. {rows.length} conflicto
            {rows.length === 1 ? "" : "s"} en esta lectura.
          </p>
        </div>
      </div>
      <div className="scroll-thin max-h-[420px] overflow-auto">
        <table className="table-dense w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr>
              <th>Jugador</th>
              <th>Analítica Fantasy</th>
              <th>Modelo propio</th>
              <th>Conflicto</th>
              <th>Mercado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const player = row.player;
              const decision = (player as MarketDecision).decision;
              return (
                <tr key={String(player.player_id)}>
                  <td>
                    <div className="flex items-center gap-2.5">
                      <PlayerAvatar player={player} size="sm" />
                      <div className="min-w-0">
                        <div className="truncate font-medium tracking-tight">{playerName(player)}</div>
                        <div className="text-[11px] text-muted">
                          {player.position || ""}
                          {player.club ? ` · ${player.club}` : ""}
                          {row.inMarket ? " · en mercado" : ""}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <SideCell
                      label="AF"
                      signal={player.af_market_signal}
                      delta={player.af_predicted_delta}
                      maxBid={player.af_max_bid}
                      tone="mint"
                    />
                  </td>
                  <td>
                    <SideCell
                      label="Own"
                      signal={player.own_market_signal}
                      delta={player.own_predicted_delta}
                      maxBid={player.own_max_bid}
                      tone="gold"
                    />
                  </td>
                  <td>
                    <p className="text-sm text-muted-strong">{row.headline}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {row.kinds.map((kind) => (
                        <span key={kind} className="badge badge--warn">
                          {discrepancyKindLabel(kind)}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="text-xs text-muted">
                    {decision ? (
                      <>
                        <span className="font-medium text-ink">{decision}</span>
                        {typeof player.p_titular === "number" ? ` · ${pct(player.p_titular)} tit.` : ""}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

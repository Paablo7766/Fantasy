"use client";

import { ErrorCard, Skeleton } from "@/components/Feedback";
import { accel, eur, glass, pct, playerName, points } from "@/lib/format";
import type { Player, TrendsPayload } from "@/lib/types";

type Row = Player & { kind: string };

function collect(trends: TrendsPayload): Row[] {
  const flips = (trends.flips || []).map((player) => ({ ...player, kind: "Flip" }));
  const flipIds = new Set(flips.map((item) => item.player_id));
  const rising = (trends.rising || [])
    .filter((player) => !flipIds.has(player.player_id))
    .slice(0, 6)
    .map((player) => ({ ...player, kind: "Sube" }));
  const undervalued = (trends.undervalued || []).slice(0, 4).map((player) => ({ ...player, kind: "Chollo" }));
  return [...flips.slice(0, 8), ...rising, ...undervalued];
}

export function MarketTable({
  trends,
  loading = false,
}: {
  trends: TrendsPayload | null;
  loading?: boolean;
}) {
  if (loading && !trends) return <Skeleton title="Mercado" rows={6} />;
  if (!trends || trends.ok === false) {
    return <ErrorCard title="Mercado" payload={trends || { error: { message: "Sin lectura de mercado." } }} brief />;
  }
  const rows = collect(trends);
  const alerts = (trends.availability || []).slice(0, 4);

  return (
    <article className={glass("flex max-h-[920px] flex-col p-4")}>
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-white/40">Mercado</p>
          <h2 className="text-xl font-medium">{trends.flip_count || 0} para especular</h2>
        </div>
        <p className="text-right text-xs text-white/45">
          {trends.market?.count ?? 0} fichajes
          <br />
          {trends.catalog_count ?? 0} en catálogo
        </p>
      </div>
      <div className="scroll-thin overflow-auto">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-[0.14em] text-white/40">
            <tr>
              <th className="p-4 font-medium">Jugador</th>
              <th className="p-4 font-medium">Señal</th>
              <th className="p-4 font-medium">Precio</th>
              <th className="p-4 font-medium">Titular</th>
            </tr>
          </thead>
          <tbody>
            {rows.length ? (
              rows.map((player) => {
                const price = player.bid_eur ?? player.sale_price ?? player.gap_eur;
                const tone = player.kind === "Chollo" ? "text-emerald-300" : "text-white/70";
                return (
                  <tr
                    key={`${player.kind}-${player.player_id}`}
                    className="border-t border-white/5 transition-colors hover:bg-white/10"
                  >
                    <td className="p-4">
                      <div className="font-medium">{playerName(player)}</div>
                      <div className="text-xs text-white/40">
                        {player.position || ""} · {points(player.expected_points)}
                      </div>
                    </td>
                    <td className={`p-4 font-mono text-xs ${tone}`}>
                      {player.kind}
                      <span className="mt-1 block text-emerald-300">{accel(player.acceleration)}</span>
                    </td>
                    <td className="p-4 font-mono text-sm">{eur(typeof price === "number" ? price : null)}</td>
                    <td className="p-4 font-mono text-sm">{pct(player.p_titular)}</td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td className="p-4 text-white/50" colSpan={4}>
                  No hay pujas ni chollos con la lectura de hoy.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {alerts.length ? (
        <ul className="mt-4 space-y-2">
          {alerts.map((player) => {
            const sanction = player.sanction || {};
            const flags = [player.fitness, sanction.suspended ? "sancionado" : "", sanction.on_verge ? "4 amarillas" : ""]
              .filter(Boolean)
              .join(" · ");
            return (
              <li key={String(player.player_id)} className="rounded-2xl px-4 py-3 text-sm transition hover:bg-white/10">
                {playerName(player)} <span className="text-rose-300">{flags || "alerta"}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </article>
  );
}

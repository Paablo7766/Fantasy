"use client";

import { ErrorCard, Skeleton } from "@/components/Feedback";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { accel, eur, glass, pct, playerName, points } from "@/lib/format";
import type { Player, TrendsPayload } from "@/lib/types";

function Panel({
  title,
  subtitle,
  rows,
  renderMeta,
  accent = "mint",
}: {
  title: string;
  subtitle: string;
  rows: Player[];
  renderMeta: (player: Player) => string;
  accent?: "mint" | "coral" | "gold";
}) {
  const accentBar =
    accent === "coral" ? "border-l-coral/70" : accent === "gold" ? "border-l-gold/70" : "border-l-mint/70";
  return (
    <div className={`min-w-0 border-l-[2px] ${accentBar} pl-3`}>
      <p className="eyebrow">{title}</p>
      <h3 className="mt-0.5 text-[0.95rem] font-medium tracking-tight text-ink">{subtitle}</h3>
      <ul className="mt-2">
        {rows.length ? (
          rows.slice(0, 6).map((player) => (
            <li key={`${title}-${player.player_id}`} className="data-row !gap-2.5 !px-0 !py-2">
              <PlayerAvatar player={player} size="sm" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium tracking-tight">{playerName(player)}</div>
                <div className="metric-value truncate text-[11px] text-muted">{renderMeta(player)}</div>
              </div>
            </li>
          ))
        ) : (
          <li className="py-2 text-sm text-faint">Sin datos AF en esta lectura.</li>
        )}
      </ul>
    </div>
  );
}

export function AfIntel({
  trends,
  loading = false,
}: {
  trends: TrendsPayload | null;
  loading?: boolean;
}) {
  if (loading && !trends) return <Skeleton title="Analítica Fantasy" rows={6} />;
  if (!trends || trends.ok === false) {
    return (
      <ErrorCard title="Analítica Fantasy" payload={trends || { error: { message: "Sin lectura AF." } }} brief />
    );
  }

  const rising = trends.af_prediction_rising || [];
  const falling = trends.af_prediction_falling || [];
  const oracle = trends.af_oracle_points || [];
  const chollos = trends.af_oracle_chollos || [];
  const form = trends.af_in_form || [];

  return (
    <article className={glass("p-4 md:p-5")}>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Analítica Fantasy</p>
          <h2 className="section-title mt-1">Jornada y mercado AF</h2>
          <p className="section-support">Señal externa · no sustituye al XI ni al bonus Relevo</p>
        </div>
      </div>
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        <Panel
          title="Predicción"
          subtitle="Mañana sube"
          accent="mint"
          rows={rising}
          renderMeta={(player) => `${accel(player.af_predicted_delta)} · fuerza ${pct(player.af_signal_strength)}`}
        />
        <Panel
          title="Predicción"
          subtitle="Mañana baja"
          accent="coral"
          rows={falling}
          renderMeta={(player) => `${accel(player.af_predicted_delta)} · fuerza ${pct(player.af_signal_strength)}`}
        />
        <Panel
          title="Oráculo"
          subtitle="Más puntos esperados"
          accent="gold"
          rows={oracle}
          renderMeta={(player) => `${points(player.af_expected_points)} pts · ${pct(player.p_titular)} titular`}
        />
        <Panel
          title="Oráculo"
          subtitle="Chollos €/pt"
          accent="mint"
          rows={chollos}
          renderMeta={(player) =>
            `${points(player.af_points_per_million)} pts/M · ${eur(player.af_market_value ?? player.market_value)}`
          }
        />
        <Panel
          title="Forma"
          subtitle="En racha"
          accent="gold"
          rows={form}
          renderMeta={(player) => {
            const afForm = player.af_form;
            const avg = afForm?.recent_average;
            const signals = afForm?.signal_count;
            return `${points(typeof avg === "number" ? avg : null)} media · ${signals ?? 0} señales`;
          }}
        />
        <Panel
          title="Disponibilidad"
          subtitle="Alertas enriquecidas"
          accent="coral"
          rows={(trends.availability || []).filter((player) => player.af_injury || player.af_suspension)}
          renderMeta={(player) => {
            const detail =
              player.af_injury?.info ||
              player.af_injury?.report ||
              player.af_suspension?.info ||
              player.fitness_detail ||
              player.fitness ||
              "alerta";
            return String(detail);
          }}
        />
      </div>
    </article>
  );
}

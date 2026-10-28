"use client";

import { useMemo } from "react";
import { eurShort, points } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import { squadTotals } from "@/lib/squadTotals";
import type { OptimizePayload, PlanPayload, SquadsPayload } from "@/lib/types";

type Props = {
  plan: PlanPayload | null;
  squads: SquadsPayload | null;
  optimize: OptimizePayload | null;
  loading: boolean;
};

export function RecommendationsObjective({ plan, squads, optimize, loading }: Props) {
  const metrics = useMemo(() => {
    const own = squads?.self ?? null;
    const totals = squadTotals(own);
    const cash =
      typeof plan?.cash_eur === "number"
        ? plan.cash_eur
        : typeof own?.cash_eur === "number"
          ? own.cash_eur
          : null;
    const squadValue = totals.market_value_total;
    const patrimony = cash !== null && squadValue !== null ? cash + squadValue : squadValue ?? cash;

    const expected =
      typeof plan?.lineup?.expected_points === "number"
        ? plan.lineup.expected_points
        : typeof optimize?.expected_points === "number"
          ? optimize.expected_points
          : null;
    const saved =
      typeof plan?.lineup?.saved_points === "number" ? plan.lineup.saved_points : null;
    const delta =
      typeof plan?.lineup?.points_delta === "number"
        ? plan.lineup.points_delta
        : expected !== null && saved !== null
          ? expected - saved
          : null;

    const hazlo = (plan?.priority_actions || []).filter((row) => row.verdict === "HAZLO").length;
    const posture = plan?.mode?.label || plan?.mode?.name || null;
    const gap = plan?.mode?.gap_to_leader;

    return { cash, squadValue, patrimony, expected, saved, delta, hazlo, posture, gap };
  }, [plan, squads, optimize]);

  const deltaLabel = signedPoints(metrics.delta);

  return (
    <section className="hoy-objective" aria-labelledby="rec-objetivo">
      <div className="hoy-objective__head">
        <div className="min-w-0">
          <p className="hoy-label" id="rec-objetivo">
            Objetivo del motor
          </p>
          <h2 className="mt-1 text-[1.05rem] font-semibold leading-snug tracking-[-0.03em] text-[color:var(--hoy-ink)] md:text-[1.15rem]">
            Más puntos esta jornada, sin regalar patrimonio
          </h2>
          <p className="mt-1.5 max-w-2xl text-[12px] leading-5 text-[color:var(--hoy-muted)]">
            Cada tarjeta ordena una decisión concreta: vender una oferta, poner a la venta, pujar, clausular o alinear.
            Prioridad = impacto en puntos esperados + salud de caja y valor de plantilla.
          </p>
        </div>
        {metrics.hazlo ? (
          <span className="hoy-chip hoy-chip--mint shrink-0">
            <span className="hoy-chip__dot" aria-hidden="true" />
            {metrics.hazlo} movimiento{metrics.hazlo === 1 ? "" : "s"} listo{metrics.hazlo === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      <div className="mt-4 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Puntos jornada"
          value={metrics.expected !== null ? points(metrics.expected) : loading ? "…" : "—"}
          hint={
            deltaLabel
              ? `Vs once guardado: ${deltaLabel} pts`
              : metrics.saved !== null
                ? `Guardado: ${points(metrics.saved)} pts`
                : "Once óptimo del optimizador"
          }
          tone="mint"
        />
        <MetricCard
          label="Patrimonio club"
          value={metrics.patrimony !== null ? eurShort(metrics.patrimony) : loading ? "…" : "—"}
          hint={
            metrics.cash !== null && metrics.squadValue !== null
              ? `Caja ${eurShort(metrics.cash)} + plantilla ${eurShort(metrics.squadValue)}`
              : "Caja + valor de mercado de tu plantilla"
          }
          tone="gold"
        />
        <MetricCard
          label="Caja libre"
          value={metrics.cash !== null ? eurShort(metrics.cash) : loading ? "…" : "—"}
          hint="Reserva implícita del plan antes de pujas y clausulazos"
          tone={metrics.cash !== null && metrics.cash < 0 ? "red" : "default"}
        />
        <MetricCard
          label="Postura en liga"
          value={metrics.posture || (loading ? "…" : "—")}
          hint={
            typeof metrics.gap === "number"
              ? metrics.gap > 0
                ? `${metrics.gap} pts por delante del líder`
                : metrics.gap === 0
                  ? "Empate con el líder"
                  : `${Math.abs(metrics.gap)} pts por detrás`
              : "Modo ventaja / remontada del motor"
          }
          tone="default"
        />
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone: "mint" | "gold" | "red" | "default";
}) {
  const valueClass =
    tone === "mint"
      ? "text-[color:var(--hoy-mint)]"
      : tone === "gold"
        ? "text-[color:var(--hoy-gold)]"
        : tone === "red"
          ? "text-[#fca5a5]"
          : "text-[color:var(--hoy-ink)]";

  return (
    <div className="hoy-objective__metric">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[color:var(--hoy-faint)]">{label}</p>
      <p className={`metric-value mt-1 text-xl font-semibold tabular-nums tracking-[-0.04em] ${valueClass}`}>{value}</p>
      <p className="mt-1 text-[10.5px] leading-4 text-[color:var(--hoy-muted)]">{hint}</p>
    </div>
  );
}

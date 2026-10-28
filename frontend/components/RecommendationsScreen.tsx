"use client";

import { useDashboard } from "@/components/DashboardProvider";
import { SigningBoard } from "@/components/hoy/SigningBoard";
import { eurShort, points, stamp } from "@/lib/format";
import type { NeedsPayload, OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

export function RecommendationsScreen() {
  const { state, pending, busy, refreshing, photoLine } = useDashboard();
  const plan = state.plan as PlanPayload | null;
  const squads = state.squads as SquadsPayload | null;
  const optimize = state.optimize as OptimizePayload | null;
  const trends = state.trends as TrendsPayload | null;
  const needs = state.needs as NeedsPayload | null;
  const loading = (pending.plan || busy) && !plan;
  const own = squads?.self as (SquadsPayload["self"] & { cash?: number | null; points?: number | null }) | null;
  const cash =
    typeof plan?.cash_eur === "number"
      ? plan.cash_eur
      : typeof own?.cash === "number"
        ? own.cash
        : typeof own?.cash_eur === "number"
          ? own.cash_eur
          : null;
  const rank = typeof own?.rank === "number" ? own.rank : null;
  const expected =
    typeof plan?.lineup?.expected_points === "number"
      ? plan.lineup.expected_points
      : typeof optimize?.expected_points === "number"
        ? optimize.expected_points
        : null;
  const kickoff = typeof plan?.kickoff === "string" ? plan.kickoff : null;

  return (
    <div className="hoy-root rec-home">
      <div className="rec-stats" aria-label="Cifras de la foto">
        <Stat label="Saldo" value={cash !== null ? eurShort(cash) : loading ? "…" : "—"} />
        <Stat label="Posición" value={rank !== null ? `${rank}º` : loading ? "…" : "—"} />
        <Stat label="Puntos" value={expected !== null ? points(expected) : loading ? "…" : "—"} />
        <Stat label="Jornada" value={kickoff ? stamp(kickoff) : loading ? "…" : "—"} />
      </div>
      <SigningBoard
        plan={plan}
        optimize={optimize}
        squads={squads}
        trends={trends}
        needs={needs}
        loading={loading}
        refreshing={refreshing}
        photoLine={photoLine}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rec-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

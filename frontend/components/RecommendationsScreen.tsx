"use client";

import { useDashboard } from "@/components/DashboardProvider";
import { SigningBoard } from "@/components/hoy/SigningBoard";
import { eurShort, points, stamp } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
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
  const saved = typeof plan?.lineup?.saved_points === "number" ? plan.lineup.saved_points : null;
  const delta =
    typeof plan?.lineup?.points_delta === "number"
      ? plan.lineup.points_delta
      : expected !== null && saved !== null
        ? Math.round((expected - saved) * 10) / 10
        : typeof plan?.plan_fichajes?.mejora_puntos_jornada === "number"
          ? plan.plan_fichajes.mejora_puntos_jornada
          : null;

  return (
    <div className="hoy-root rec-home">
      <div className="rec-stats" aria-label="Cifras de la foto">
        <Stat
          label="Saldo"
          value={cash !== null ? eurShort(cash) : loading ? "…" : "—"}
          tone={cash !== null && cash < 0 ? "text-[#FC734D]" : "text-[#0297DE]"}
        />
        <Stat label="Posición" value={rank !== null ? `${rank}º` : loading ? "…" : "—"} />
        <Stat
          label="Puntos esperados"
          value={expected !== null ? points(expected) : loading ? "…" : "—"}
          hint={delta !== null ? `${signedPoints(delta) || "0,0"} pts` : undefined}
          hintTone={delta !== null && delta < 0 ? "text-[#FC734D]" : "text-[#0297DE]"}
        />
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

function Stat({
  label,
  value,
  tone,
  hint,
  hintTone,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
  hintTone?: string;
}) {
  return (
    <div className="rec-stat">
      <span className="!text-[11px] !tracking-wider !text-[#8B9EB0]">{label}</span>
      <strong className={`!font-mono !text-xl !font-bold ${tone || ""}`}>{value}</strong>
      {hint ? <span className={`!normal-case !tracking-normal font-mono text-[11px] font-semibold ${hintTone || ""}`}>{hint}</span> : null}
    </div>
  );
}

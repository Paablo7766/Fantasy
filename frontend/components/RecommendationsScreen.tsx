"use client";

import { useDashboard } from "@/components/DashboardProvider";
import { SigningBoard } from "@/components/hoy/SigningBoard";
import { points, stamp } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import type { NeedsPayload, OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

const GAUGE_MAX = 80;
const ARC_R = 86;
const ARC_LEN = Math.PI * ARC_R;

function cashCompact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000) {
    return `${sign}${(abs / 1_000_000).toLocaleString("es-ES", { maximumFractionDigits: 1 })}M`;
  }
  if (abs >= 1_000) return `${sign}${Math.round(abs / 1_000)}k`;
  return `${sign}${Math.round(abs)}`;
}

function ScoreGauge({ value, delta, loading }: { value: number | null; delta: number | null; loading: boolean }) {
  const progress = value === null ? 0 : Math.max(0, Math.min(1, value / GAUGE_MAX));
  const dash = ARC_LEN * progress;
  const angle = Math.PI * (1 - progress);
  const knobX = 110 + ARC_R * Math.cos(angle);
  const knobY = 108 - ARC_R * Math.sin(angle);
  const deltaLabel = delta === null ? null : signedPoints(delta) || "0,0";
  const figure = loading ? "…" : value === null ? "—" : points(value);

  return (
    <div className="relative mx-auto w-[min(100%,240px)]">
      <svg viewBox="0 0 220 126" className="w-full" role="img" aria-label="Puntuación esperada del once">
        <defs>
          <linearGradient
            id="xi-gauge"
            gradientUnits="userSpaceOnUse"
            x1="24"
            y1="108"
            x2={progress > 0.04 ? knobX : 196}
            y2={progress > 0.04 ? knobY : 22}
          >
            <stop offset="0%" stopColor="#0297DE" />
            <stop offset="100%" stopColor="#FC734D" />
          </linearGradient>
        </defs>
        <path
          d="M 24 108 A 86 86 0 0 1 196 108"
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="12"
          strokeLinecap="round"
        />
        <path
          d="M 24 108 A 86 86 0 0 1 196 108"
          fill="none"
          stroke="url(#xi-gauge)"
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${ARC_LEN}`}
        />
        {progress > 0.02 ? (
          <circle cx={knobX} cy={knobY} r="6.5" fill="#F0F6FC" style={{ filter: "drop-shadow(0 0 8px rgba(2,151,222,0.7))" }} />
        ) : null}
      </svg>
      <div className="relative -mt-8 text-center">
        <p className="font-mono text-5xl font-semibold leading-none tracking-[-0.06em] text-[#F0F6FC] tabular-nums">
          {figure}
        </p>
        <p className="mt-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8B9EB0]">Puntos esperados</p>
        {deltaLabel ? (
          <p className={`mt-1 font-mono text-xs font-semibold tabular-nums ${delta !== null && delta < 0 ? "text-[#FC734D]" : "text-[#0297DE]"}`}>
            {deltaLabel} pts
          </p>
        ) : null}
      </div>
    </div>
  );
}

function MiniDial({
  label,
  value,
  note,
  progress,
  ring,
  valueClass,
  className = "",
}: {
  label: string;
  value: string;
  note?: string;
  progress: number;
  ring: string;
  valueClass?: string;
  className?: string;
}) {
  const r = 26;
  const circ = 2 * Math.PI * r;
  const dash = circ * Math.max(0, Math.min(1, progress));
  return (
    <div className={`flex min-w-0 flex-col items-center rounded-3xl border border-[#0297DE]/15 bg-[#02070A]/55 px-3 py-3.5 ${className}`}>
      <div className="relative h-[4.5rem] w-[4.5rem]">
        <svg viewBox="0 0 72 72" className="h-full w-full -rotate-90" aria-hidden="true">
          <circle cx="36" cy="36" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
          <circle
            cx="36"
            cy="36"
            r={r}
            fill="none"
            stroke={ring}
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circ}`}
          />
        </svg>
        <span className={`absolute inset-0 grid place-items-center px-1 text-center font-mono text-[11px] font-bold leading-tight tabular-nums ${valueClass || "text-[#F0F6FC]"}`}>
          {value}
        </span>
      </div>
      <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8B9EB0]">{label}</p>
      {note ? <p className="mt-0.5 font-mono text-[11px] font-semibold tabular-nums text-[#C5D4E2]">{note}</p> : null}
    </div>
  );
}

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
  const rank =
    typeof own?.rank === "number" ? own.rank : typeof plan?.mode?.own_rank === "number" ? plan.mode.own_rank : null;
  const totalPoints =
    typeof plan?.mode?.own_points === "number"
      ? plan.mode.own_points
      : typeof own?.points === "number"
        ? own.points
        : null;
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
  const cashProgress = cash === null ? 0 : cash < 0 ? 0.22 : Math.max(0.38, Math.min(1, cash / 2_000_000));
  const rankProgress = rank === null ? 0 : Math.max(0.16, Math.min(1, (13 - Math.min(rank, 12)) / 12));
  const pointsLabel =
    totalPoints === null ? (loading ? "…" : "—") : `${Math.round(totalPoints).toLocaleString("es-ES")} pts`;

  return (
    <div className="hoy-root rec-home">
      <section
        className="rounded-3xl border border-[#0297DE]/15 bg-[#07121A]/85 p-5 shadow-[0_8px_32px_rgba(0,0,0,0.4),0_0_24px_rgba(2,151,222,0.18)] backdrop-blur-xl"
        aria-label="Puntuación del once"
      >
        <div className="mb-1 flex items-center justify-between gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8B9EB0]">Once</p>
          <span className="rounded-full border border-white/10 bg-[#02070A]/60 px-2.5 py-1 font-mono text-[11px] text-[#C5D4E2]">
            {kickoff ? stamp(kickoff) : loading ? "…" : "Sin jornada"}
          </span>
        </div>
        <div className="mt-2 grid grid-cols-2 items-end gap-3 sm:grid-cols-[minmax(0,1fr)_240px_minmax(0,1fr)] sm:items-center sm:gap-5">
          <div className="col-span-2 sm:col-span-1 sm:col-start-2 sm:row-start-1">
            <ScoreGauge value={expected} delta={delta} loading={loading && expected === null} />
          </div>
          <MiniDial
            className="sm:col-start-1 sm:row-start-1"
            label="Saldo"
            value={cash !== null ? cashCompact(cash) : loading ? "…" : "—"}
            progress={cashProgress}
            ring="#0297DE"
            valueClass={cash !== null && cash < 0 ? "text-[#FC734D]" : "text-[#F0F6FC]"}
          />
          <MiniDial
            className="sm:col-start-3 sm:row-start-1"
            label="Posición"
            value={rank !== null ? `${rank}º` : loading ? "…" : "—"}
            note={pointsLabel}
            progress={rankProgress}
            ring="#8B9EB0"
          />
        </div>
      </section>
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

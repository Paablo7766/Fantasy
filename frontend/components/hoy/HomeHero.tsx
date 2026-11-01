"use client";

import { useMemo } from "react";
import { buildClockReport, buildSurvival, countdownClock, countdownParts, eventTitle, signedPoints } from "@/lib/hoy";
import { points, titularShare } from "@/lib/format";
import { useNow } from "@/lib/useClock";
import type { OptimizePayload, PlanPayload, Player, SquadsPayload } from "@/lib/types";

/** Saldo corto: 50,7M · 940k · 320. */
function cashFigure(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toLocaleString("es-ES", { maximumFractionDigits: 1 })}M`;
  if (abs >= 1_000) return `${sign}${Math.round(abs / 1_000)}k`;
  return `${sign}${Math.round(abs)}`;
}

function Fact({ value, label, tone }: { value: string; label: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <p className={`truncate text-[1.35rem] font-semibold leading-none tracking-tight tabular-nums ${tone || "text-white"}`}>{value}</p>
      <p className="mt-1.5 truncate text-[13px] text-[#8B9EB0]">{label}</p>
    </div>
  );
}

export function HomeHero({
  plan,
  optimize,
  squads,
  loading,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  squads: SquadsPayload | null;
  loading: boolean;
}) {
  const nowMs = useNow();
  const mounted = nowMs > 0;
  const clock = useMemo(() => buildClockReport(plan, mounted ? nowMs : 0), [plan, mounted, nowMs]);
  const survival = useMemo(() => buildSurvival(plan), [plan]);
  const parts = clock.next && mounted ? countdownParts(clock.next.ms, nowMs) : null;

  const own = squads?.self as (SquadsPayload["self"] & { cash?: number | null }) | null;
  const cash =
    typeof plan?.cash_eur === "number"
      ? plan.cash_eur
      : typeof own?.cash === "number"
        ? own.cash
        : typeof own?.cash_eur === "number"
          ? own.cash_eur
          : null;
  const rank = typeof own?.rank === "number" ? own.rank : typeof plan?.mode?.own_rank === "number" ? plan.mode.own_rank : null;
  const field = typeof squads?.rival_count === "number" ? squads.rival_count + 1 : null;

  const fichajes = plan?.plan_fichajes;
  const now =
    typeof fichajes?.puntos_once_actual === "number"
      ? fichajes.puntos_once_actual
      : typeof plan?.lineup?.saved_points === "number"
        ? plan.lineup.saved_points
        : null;
  const target =
    typeof fichajes?.puntos_once === "number"
      ? fichajes.puntos_once
      : typeof plan?.lineup?.expected_points === "number"
        ? plan.lineup.expected_points
        : (optimize?.expected_points ?? null);
  const delta =
    typeof fichajes?.mejora_puntos_jornada === "number"
      ? fichajes.mejora_puntos_jornada
      : now !== null && target !== null
        ? target - now
        : null;
  const hasGain = delta !== null && Math.abs(delta) >= 0.05;

  const xi: Player[] = optimize?.saved_lineup?.xi?.length ? optimize.saved_lineup.xi : optimize?.xi || [];
  const shares = xi.map((player) => titularShare(player.p_titular)).filter((value): value is number => value !== null);
  const avgShare = shares.length ? shares.reduce((total, value) => total + value, 0) / shares.length : null;

  const issue = plan ? survival.checks.find((check) => check.tone !== "ok" && check.id !== "clausulas") : null;
  const dash = loading ? "…" : "—";
  const big = hasGain ? signedPoints(delta) : target !== null ? points(target) : dash;

  return (
    <section className="px-1 pt-1" aria-label="Resumen de la jornada">
      <p className="text-[15px] text-[#8B9EB0]">{hasGain ? "El plan de hoy suma" : "Puntos esperados"}</p>
      <p className="mt-1 flex items-baseline gap-2 tabular-nums">
        <span className={`text-[4.25rem] font-semibold leading-none tracking-[-0.045em] ${hasGain && (delta as number) < 0 ? "text-[#FC734D]" : "text-white"}`}>
          {big}
        </span>
        <span className="text-xl font-medium text-[#8B9EB0]">pts</span>
      </p>
      {hasGain && now !== null && target !== null ? (
        <p className="mt-2 text-[15px] tabular-nums text-[#8B9EB0]">
          De {points(now)} a <span className="text-[#C5D4E2]">{points(target)}</span> esta jornada
        </p>
      ) : null}

      {issue ? (
        <p className="mt-4 inline-flex items-center gap-2 rounded-full bg-[#FC734D]/10 px-3 py-1.5 text-[13px] font-medium text-[#FC734D]" title={issue.detail}>
          <span className="h-1.5 w-1.5 rounded-full bg-[#FC734D]" aria-hidden="true" />
          {issue.label} sin cumplir
        </p>
      ) : null}

      <div className="mt-8 grid grid-cols-3 gap-4">
        <Fact value={cash !== null ? cashFigure(cash) : dash} label="Saldo" tone={cash !== null && cash < 0 ? "text-[#FC734D]" : undefined} />
        <Fact value={rank !== null ? `${rank}º` : dash} label={field ? `de ${field}` : "Posición"} />
        <Fact value={avgShare !== null ? `${Math.round(avgShare * 100)}%` : dash} label="Titulares" />
      </div>

      <p className="mt-6 flex items-center gap-2 text-[13px] text-[#8B9EB0]">
        {clock.next && parts ? (
          <>
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[#FC734D]" aria-hidden="true" />
            <span className="min-w-0 truncate">
              {eventTitle(clock.next)} · <span className="tabular-nums text-[#C5D4E2]">{parts.days > 0 ? `${parts.days}d ` : ""}{countdownClock(parts)}</span>
            </span>
          </>
        ) : (
          <span>{loading && !plan ? "Cargando el plan…" : "Sin próximos hitos"}</span>
        )}
      </p>
    </section>
  );
}

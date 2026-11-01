"use client";

import { useMemo, type ReactNode } from "react";
import { buildClockReport, buildSurvival, countdownClock, countdownParts, eventTitle, signedPoints } from "@/lib/hoy";
import { points, titularShare } from "@/lib/format";
import { useNow } from "@/lib/useClock";
import type { OptimizePayload, PlanPayload, Player, SquadsPayload } from "@/lib/types";

/** Saldo corto: 50,7M € · 940k € · 320 €. */
function cashFigure(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toLocaleString("es-ES", { maximumFractionDigits: 1 })}M €`;
  if (abs >= 1_000) return `${sign}${Math.round(abs / 1_000)}k €`;
  return `${sign}${Math.round(abs)} €`;
}

function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 px-2.5 first:pl-0 last:pr-0">
      <p className="whitespace-nowrap text-[9px] font-semibold uppercase tracking-[0.06em] text-[#8B9EB0]">{label}</p>
      {children}
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
  const gap = plan?.mode?.gap_to_leader;

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

  const xi: Player[] = optimize?.saved_lineup?.xi?.length ? optimize.saved_lineup.xi : optimize?.xi || [];
  const shares = xi.map((player) => titularShare(player.p_titular)).filter((value): value is number => value !== null);
  const avgShare = shares.length ? shares.reduce((total, value) => total + value, 0) / shares.length : null;
  const safe = shares.filter((value) => value >= 0.8).length;

  const issue = plan ? survival.checks.find((check) => check.tone !== "ok" && check.id !== "clausulas") : null;
  const placeholder = loading ? "…" : "—";

  return (
    <section className="rounded-2xl border border-white/[0.07] bg-[#07121A] p-4" aria-label="Resumen de la jornada">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-[#8B9EB0]">Proyección jornada</p>
          <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 font-mono tabular-nums">
            <span className="text-2xl font-semibold leading-none text-white">
              {now !== null ? `${points(now)} pts` : target !== null ? `${points(target)} pts` : placeholder}
            </span>
            {now !== null && target !== null && Math.abs(target - now) >= 0.05 ? (
              <span className="text-[13px] font-medium text-[#0297DE]">
                → {points(target)} pts{delta !== null ? ` (${signedPoints(delta)})` : ""}
              </span>
            ) : null}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-[#8B9EB0]">Próximo hito</p>
          <p className="mt-1.5 flex items-center justify-end gap-1.5 font-mono text-xs tabular-nums">
            {clock.next && parts ? (
              <>
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#FC734D]" aria-hidden="true" />
                <span className="text-[#F0F6FC]">
                  {parts.days > 0 ? `${parts.days}d ` : ""}
                  {countdownClock(parts)}
                </span>
              </>
            ) : (
              <span className="text-[#8B9EB0]">{loading && !plan ? "…" : "--:--:--"}</span>
            )}
          </p>
          <p className="mt-0.5 max-w-[11rem] truncate text-[11px] text-[#8B9EB0]">
            {clock.next ? eventTitle(clock.next) : plan ? (clock.exhausted ? "Sin hitos pendientes" : "Sin horas en el plan") : "Esperando el plan"}
          </p>
        </div>
      </div>

      <div className="my-3 h-[1px] bg-white/[0.06]" />

      <div className="grid grid-cols-[0.85fr_1.15fr_1.05fr_1.2fr] divide-x divide-white/[0.06]">
        <Cell label="Saldo">
          <p className={`mt-1 truncate font-mono text-sm font-semibold tabular-nums ${cash !== null && cash < 0 ? "text-[#FC734D]" : "text-white"}`}>
            {cash !== null ? cashFigure(cash) : placeholder}
          </p>
        </Cell>
        <Cell label="Posición">
          <p className="mt-1 whitespace-nowrap font-mono text-sm font-semibold tabular-nums text-white">
            {rank !== null ? `${rank}°${field ? ` / ${field}` : ""}` : placeholder}
          </p>
          {typeof gap === "number" && gap > 0 ? (
            <p className="text-[10.5px] leading-tight text-[#8B9EB0]">a {Math.round(gap)} pts del 1°</p>
          ) : rank === 1 ? (
            <p className="truncate text-[10.5px] text-[#8B9EB0]">líder</p>
          ) : null}
        </Cell>
        <Cell label="Titularidad">
          <p className="mt-1 truncate font-mono text-sm font-semibold tabular-nums text-white">
            {avgShare !== null ? `${Math.round(avgShare * 100)}%` : placeholder}
          </p>
          {avgShare !== null ? (
            <p className="text-[10.5px] leading-tight text-[#8B9EB0]">
              {safe}/{shares.length} seguros
            </p>
          ) : null}
        </Cell>
        <Cell label="Estado">
          {!plan ? (
            <p className="mt-1 text-[11px] text-[#8B9EB0]">{placeholder}</p>
          ) : issue ? (
            <span
              className="mt-1 inline-flex max-w-full items-center rounded-md border border-[#FC734D]/40 bg-[#FC734D]/10 px-1.5 py-0.5 text-[10.5px] font-medium leading-tight text-[#FC734D]"
              title={issue.detail}
            >
              {issue.label}
            </span>
          ) : (
            <span className="mt-1 inline-flex max-w-full items-center rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-[10.5px] font-medium leading-tight text-[#C5D4E2]">
              XI sincronizado
            </span>
          )}
        </Cell>
      </div>
    </section>
  );
}

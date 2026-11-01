"use client";

import { useMemo, type ReactNode } from "react";
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

const ICON = {
  cash: <path d="M3 6.5h14v8H3zM3 9h14M13 12h2" strokeLinecap="round" strokeLinejoin="round" />,
  rank: <path d="M6 16V9m4 7V4m4 12v-5" strokeLinecap="round" />,
  squad: <path d="M7 3.5 3.5 6l1.5 3 2-.8V16h6V8.2l2 .8 1.5-3L13 3.5c-.4 1-1.5 1.6-3 1.6S7.4 4.5 7 3.5Z" strokeLinejoin="round" />,
};

function Stat({ icon, value, label, tone }: { icon: ReactNode; value: string; label: string; tone?: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-white/[0.07] bg-white/[0.05] px-3 py-3 backdrop-blur-md">
      <svg viewBox="0 0 20 20" className="h-4 w-4 text-[#FF9A5A]" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        {icon}
      </svg>
      <p className={`mt-2.5 truncate text-[1.2rem] font-semibold leading-none tabular-nums ${tone || "text-white"}`}>{value}</p>
      <p className="mt-1 truncate text-[12px] text-white/50">{label}</p>
    </div>
  );
}

/** Semicírculo con relleno de cobre y un nudo luminoso en el extremo del progreso. */
function Arc({ fraction }: { fraction: number }) {
  const f = Math.min(1, Math.max(0, fraction));
  const angle = Math.PI - f * Math.PI;
  const knobX = 120 + 100 * Math.cos(angle);
  const knobY = 120 - 100 * Math.sin(angle);
  return (
    <svg viewBox="0 0 240 132" className="w-full" aria-hidden="true">
      <defs>
        <linearGradient id="hero-arc" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#FF6A2B" />
          <stop offset="1" stopColor="#FFC08A" />
        </linearGradient>
      </defs>
      <path d="M 20 120 A 100 100 0 0 1 220 120" fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth="14" strokeLinecap="round" />
      <path
        d="M 20 120 A 100 100 0 0 1 220 120"
        pathLength="100"
        fill="none"
        stroke="url(#hero-arc)"
        strokeWidth="14"
        strokeLinecap="round"
        strokeDasharray={`${f * 100} 100`}
        style={{ filter: "drop-shadow(0 0 10px rgba(255,122,61,0.65))", transition: "stroke-dasharray 900ms ease-out" }}
      />
      <circle cx={knobX} cy={knobY} r="11" fill="#fff" style={{ filter: "drop-shadow(0 0 8px rgba(255,170,110,0.9))" }} />
      <circle cx={knobX} cy={knobY} r="4.5" fill="#FF7A3D" />
    </svg>
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
  // El arco enseña cuánto del potencial del plan ya capturas con tu once guardado.
  const fraction = now !== null && target !== null && target > 0 ? now / target : target !== null ? 1 : 0;

  const xi: Player[] = optimize?.saved_lineup?.xi?.length ? optimize.saved_lineup.xi : optimize?.xi || [];
  const shares = xi.map((player) => titularShare(player.p_titular)).filter((value): value is number => value !== null);
  const avgShare = shares.length ? shares.reduce((total, value) => total + value, 0) / shares.length : null;

  const issue = plan ? survival.checks.find((check) => check.tone !== "ok" && check.id !== "clausulas") : null;
  const dash = loading ? "…" : "—";
  const big = hasGain ? signedPoints(delta) : target !== null ? points(target) : dash;

  return (
    <section className="home-hero" aria-label="Resumen de la jornada">
      <div className="relative flex items-center justify-between gap-3">
        <p className="text-[13px] font-medium text-white/60">Jornada</p>
        <p className="flex min-w-0 items-center gap-2 rounded-full border border-white/10 bg-black/25 px-3 py-1.5 text-[12px] text-white/70 backdrop-blur-md">
          {clock.next && parts ? (
            <>
              <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[#FF7A3D]" aria-hidden="true" />
              <span className="truncate">{eventTitle(clock.next)}</span>
              <span className="shrink-0 font-medium tabular-nums text-white">
                {parts.days > 0 ? `${parts.days}d ` : ""}
                {countdownClock(parts)}
              </span>
            </>
          ) : (
            <span>{loading && !plan ? "Cargando…" : "Sin próximos hitos"}</span>
          )}
        </p>
      </div>

      <div className="relative mx-auto mt-5 w-full max-w-[17.5rem]">
        <Arc fraction={fraction} />
        <div className="absolute inset-x-0 bottom-0 flex flex-col items-center">
          <p className="text-[12px] text-white/55">{hasGain ? "El plan suma" : "Puntos esperados"}</p>
          <p className="flex items-baseline gap-1.5 tabular-nums">
            <span className={`text-[3.4rem] font-semibold leading-none tracking-[-0.045em] ${hasGain && (delta as number) < 0 ? "text-[#FF8F6B]" : "text-white"}`}>{big}</span>
            <span className="text-base font-medium text-white/55">pts</span>
          </p>
        </div>
      </div>

      {hasGain && now !== null && target !== null ? (
        <p className="relative mt-3 text-center text-[13.5px] tabular-nums text-white/55">
          De {points(now)} a <span className="font-medium text-white">{points(target)}</span> esta jornada
        </p>
      ) : null}

      {issue ? (
        <p className="relative mx-auto mt-3 flex w-fit items-center gap-2 rounded-full bg-[#FF5A36]/15 px-3 py-1.5 text-[12.5px] font-medium text-[#FFA088]" title={issue.detail}>
          <span className="h-1.5 w-1.5 rounded-full bg-[#FF5A36]" aria-hidden="true" />
          {issue.label} sin cumplir
        </p>
      ) : null}

      <div className="relative mt-6 grid grid-cols-3 gap-2.5">
        <Stat icon={ICON.cash} value={cash !== null ? cashFigure(cash) : dash} label="Saldo" tone={cash !== null && cash < 0 ? "text-[#FF8F6B]" : undefined} />
        <Stat icon={ICON.rank} value={rank !== null ? `${rank}º` : dash} label={field ? `de ${field}` : "Posición"} />
        <Stat icon={ICON.squad} value={avgShare !== null ? `${Math.round(avgShare * 100)}%` : dash} label="Titulares" />
      </div>
    </section>
  );
}

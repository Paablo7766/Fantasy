"use client";

import Link from "next/link";
import { useMemo, type ReactNode } from "react";
import { buildClockReport, buildSurvival, countdownParts, eventTitle, two, type SurvivalCheck } from "@/lib/hoy";
import { points } from "@/lib/format";
import { useNow } from "@/lib/useClock";
import type { OptimizePayload, PlanPayload, SquadsPayload } from "@/lib/types";

type Tone = "blue" | "orange" | "mint" | "mute";

const STROKE: Record<Tone, string> = {
  blue: "#0297DE",
  orange: "#FC734D",
  mint: "#10B981",
  mute: "#4B6075",
};

/** Anillo de progreso con el dato en el centro. `ticks` lo dibuja segmentado, como un cuentarrevoluciones. */
function Ring({
  fraction,
  tone,
  ticks,
  children,
}: {
  fraction: number;
  tone: Tone;
  ticks?: number;
  children: ReactNode;
}) {
  const size = 92;
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(1, Math.max(0, fraction));
  const color = STROKE[tone];
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" className="absolute inset-0 -rotate-90" aria-hidden="true">
        {ticks ? (
          Array.from({ length: ticks }, (_, index) => {
            const angle = (index / ticks) * 2 * Math.PI;
            const inner = 38;
            const outer = 46;
            const lit = index < Math.round(clamped * ticks);
            return (
              <line
                key={index}
                x1={50 + Math.cos(angle) * inner}
                y1={50 + Math.sin(angle) * inner}
                x2={50 + Math.cos(angle) * outer}
                y2={50 + Math.sin(angle) * outer}
                stroke={lit ? color : "rgba(255,255,255,0.1)"}
                strokeWidth="3.2"
                strokeLinecap="round"
              />
            );
          })
        ) : (
          <>
            <circle cx="50" cy="50" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke={color}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${circumference * clamped} ${circumference}`}
              style={{ filter: `drop-shadow(0 0 6px ${color}88)`, transition: "stroke-dasharray 0.8s ease" }}
            />
          </>
        )}
      </svg>
      <div className="relative flex flex-col items-center leading-none">{children}</div>
    </div>
  );
}

function Gauge({ label, fraction, tone, ticks, value, unit }: { label: string; fraction: number; tone: Tone; ticks?: number; value: string; unit?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-2">
      <Ring fraction={fraction} tone={tone} ticks={ticks}>
        <span className="font-mono text-[1.15rem] font-bold tabular-nums tracking-tight text-[#F0F6FC]">
          {value}
          {unit ? <span className="ml-0.5 text-[0.7rem] font-semibold text-[#8B9EB0]">{unit}</span> : null}
        </span>
      </Ring>
      <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8B9EB0]">{label}</span>
    </div>
  );
}

/** Saldo corto para el centro del anillo: 8,6 M · 940 k · 320. */
function cashFigure(value: number): { value: string; unit?: string } {
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000) {
    return { value: `${sign}${(abs / 1_000_000).toLocaleString("es-ES", { maximumFractionDigits: 1 })}`, unit: "M" };
  }
  if (abs >= 1_000) return { value: `${sign}${Math.round(abs / 1_000)}`, unit: "k" };
  return { value: `${sign}${Math.round(abs)}` };
}

const FIX_HREF: Record<string, string> = { caja: "/equipo?tab=cartera", xi: "/mercado", once: "/equipo" };

function StatusChip({ check }: { check: SurvivalCheck }) {
  const good = check.tone === "ok";
  const bad = check.tone === "blocker";
  const chip = (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[11px] font-semibold ${
        good
          ? "border-[#10B981]/30 bg-[#10B981]/10 text-[#6EE7B7]"
          : bad
            ? "border-[#FC734D]/50 bg-[#FC734D]/15 text-[#FFB4A0]"
            : "border-[#FC734D]/30 bg-[#FC734D]/10 text-[#FFB4A0]"
      }`}
    >
      <span className="text-[10px]" aria-hidden="true">
        {good ? "✓" : bad ? "✕" : "!"}
      </span>
      {check.label}
    </span>
  );
  if (good) return chip;
  return (
    <Link href={FIX_HREF[check.id] || "/equipo"} title={check.detail}>
      {chip}
    </Link>
  );
}

const RAIL = ["caja", "xi", "once"] as const;

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

  const own = squads?.self as (SquadsPayload["self"] & { cash?: number | null; points?: number | null }) | null;
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
  const totalPoints =
    typeof plan?.mode?.own_points === "number" ? plan.mode.own_points : typeof own?.points === "number" ? own.points : null;
  const xiCount = optimize?.saved_lineup?.xi?.length ?? plan?.lineup?.xi?.length ?? null;
  const expected = plan?.lineup?.expected_points ?? optimize?.expected_points ?? null;
  const gap = plan?.mode?.gap_to_leader;

  const rail = RAIL.map((id) => survival.checks.find((check) => check.id === id)).filter(
    (check): check is SurvivalCheck => Boolean(check),
  );
  const verdict = !plan ? null : survival.blocked ? "bloqueo" : survival.risks.length ? "aviso" : "ok";
  const verdictCopy = verdict === "bloqueo" ? "Jornada en cero" : verdict === "aviso" ? "Revisa un punto" : "Jornada a salvo";
  const placeholder = loading ? "…" : "—";

  return (
    <section className="home-hero" aria-label="Estado de la jornada">
      <div className="home-hero__glow" aria-hidden="true" />

      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#8B9EB0]">
            {clock.next ? "Próximo hito" : "Estado del día"}
          </p>
          {parts && clock.next ? (
            <>
              <p className="mt-2 flex items-baseline gap-1 whitespace-nowrap font-mono text-[2.1rem] font-bold leading-none tracking-tight tabular-nums text-[#F0F6FC]">
                {parts.days > 0 ? <span className="mr-1 text-[1.4rem] text-[#FC734D]">{parts.days}d</span> : null}
                {two(parts.hours)}
                <span className="opacity-30">:</span>
                {two(parts.minutes)}
                <span className="opacity-30">:</span>
                <span className="text-[#67C6F5]">{two(parts.seconds)}</span>
              </p>
              <p className="mt-2 truncate text-[13px] font-semibold tracking-tight text-[#C5D4E2]">{eventTitle(clock.next)}</p>
            </>
          ) : (
            <>
              <p className="mt-2 whitespace-nowrap font-mono text-[2.1rem] font-bold leading-none tracking-tight text-[#4B6075]">
                {loading && !plan ? "…" : "--:--:--"}
              </p>
              <p className="mt-2 text-[13px] text-[#8B9EB0]">
                {!plan ? "Esperando el plan" : clock.exhausted ? "Sin hitos pendientes" : "El plan no trae horas"}
              </p>
            </>
          )}
        </div>
        {verdict ? (
          <span
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-bold ${
              verdict === "ok" ? "bg-[#10B981]/15 text-[#6EE7B7]" : "bg-[#FC734D]/20 text-[#FFB4A0]"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${verdict === "ok" ? "bg-[#10B981]" : "bg-[#FC734D]"}`} />
            {verdictCopy}
          </span>
        ) : null}
      </div>

      <div className="relative mt-6 grid grid-cols-3 gap-2">
        <Gauge
          label="Saldo"
          tone={cash === null ? "mute" : cash < 0 ? "orange" : "mint"}
          fraction={cash === null ? 0 : 1}
          value={cash !== null ? cashFigure(cash).value : placeholder}
          unit={cash !== null ? cashFigure(cash).unit : undefined}
        />
        <Gauge
          label="Posición"
          tone="blue"
          fraction={rank !== null && field && field > 1 ? 1 - (rank - 1) / (field - 1) : rank !== null ? 1 : 0}
          value={rank !== null ? `${rank}º` : placeholder}
          unit={rank !== null && field ? `/${field}` : undefined}
        />
        <Gauge
          label="Once"
          tone={xiCount === 11 ? "orange" : "mute"}
          ticks={11}
          fraction={xiCount !== null ? xiCount / 11 : 0}
          value={xiCount !== null ? `${xiCount}` : placeholder}
          unit="/11"
        />
      </div>

      <div className="relative mt-5 grid grid-cols-2 gap-2">
        <div className="rounded-2xl bg-white/[0.04] px-3.5 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8B9EB0]">Puntos liga</p>
          <p className="mt-1.5 font-mono text-xl font-bold leading-none tabular-nums text-[#F0F6FC]">
            {totalPoints === null ? placeholder : Math.round(totalPoints).toLocaleString("es-ES")}
          </p>
          {typeof gap === "number" && gap !== 0 ? (
            <p className="mt-1 font-mono text-[11px] text-[#8B9EB0]">{gap > 0 ? `${Math.round(gap)} al líder` : "líder"}</p>
          ) : null}
        </div>
        <div className="rounded-2xl bg-white/[0.04] px-3.5 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8B9EB0]">Puntos esperados</p>
          <p className="mt-1.5 font-mono text-xl font-bold leading-none tabular-nums text-[#FC734D]">
            {typeof expected === "number" ? points(expected) : placeholder}
          </p>
          <p className="mt-1 text-[11px] text-[#8B9EB0]">tu once esta jornada</p>
        </div>
      </div>

      {rail.length ? (
        <div className="relative mt-4 flex flex-wrap gap-2">
          {rail.map((check) => (
            <StatusChip key={check.id} check={check} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

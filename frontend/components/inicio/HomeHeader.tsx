"use client";

import { useMemo, type CSSProperties } from "react";
import { money, signedMoney } from "@/components/ui/kit";
import { points } from "@/lib/core/format";
import { buildClockReport, countdownClock, countdownParts, eventTitle, signedPoints } from "@/lib/inicio/hoy";
import { useNow } from "@/lib/core/useClock";
import { useCountUp } from "@/components/inicio/ui";
import type { PlanPayload, SquadsPayload } from "@/lib/types";

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string | null; tone?: string }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[12px] text-white/45">{label}</p>
      <p className="mt-1.5 truncate text-[20px] font-semibold leading-none tracking-[-0.02em] tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      <p className="mt-1.5 h-4 truncate text-[12px] tabular-nums text-white/40">{sub || ""}</p>
    </div>
  );
}

/**
 * Cabecera única de Inicio: saldo como cifra protagonista, cuenta atrás al
 * próximo hito y cuatro datos clave en una tira. Lo que hay que hacer va debajo.
 */
export function HomeHeader({ plan, squads, loading }: { plan: PlanPayload | null; squads: SquadsPayload | null; loading: boolean }) {
  const nowMs = useNow();
  const mounted = nowMs > 0;
  const clock = useMemo(() => buildClockReport(plan, mounted ? nowMs : 0), [plan, mounted, nowMs]);
  const parts = clock.next && mounted ? countdownParts(clock.next.ms, nowMs) : null;

  const own = squads?.self ?? null;
  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : (own?.cash_eur ?? null);
  const animatedCash = useCountUp(cash);
  const value = own?.market_value_total ?? null;
  const valueDay = own?.price_delta_day ?? null;
  const rank = typeof own?.rank === "number" ? own.rank : (plan?.mode?.own_rank ?? null);
  const field = typeof squads?.rival_count === "number" ? squads.rival_count + 1 : null;
  const pts = typeof own?.points === "number" ? own.points : (plan?.mode?.own_points ?? null);
  const gap = plan?.mode?.gap_to_leader ?? null;
  const redLine = plan?.red_line;
  const leagueName = squads?.league_name || plan?.league_name || null;

  const fichajes = plan?.plan_fichajes;
  const now = typeof fichajes?.puntos_once_actual === "number" ? fichajes.puntos_once_actual : (plan?.lineup?.saved_points ?? null);
  const target = typeof fichajes?.puntos_once === "number" ? fichajes.puntos_once : (plan?.lineup?.expected_points ?? null);
  const delta =
    typeof fichajes?.mejora_puntos_jornada === "number"
      ? fichajes.mejora_puntos_jornada
      : typeof now === "number" && typeof target === "number"
        ? target - now
        : null;
  const gain = delta !== null && Math.abs(delta) >= 0.05 ? delta : null;
  const cashEnd = typeof fichajes?.saldo_al_final === "number" ? fichajes.saldo_al_final : null;

  const dash = loading ? "…" : "—";
  const negative = typeof cash === "number" && cash < 0;
  const alert = redLine && redLine.status && redLine.status !== "ok" ? redLine : null;

  return (
    <section className="ini-card ini-hero ini-in" style={{ "--i": 0 } as CSSProperties} aria-label="Tu cuenta">
      <div className="flex items-center justify-between gap-3 px-5 pt-5">
        <p className="ini-eyebrow min-w-0 truncate">{leagueName || "Tu cuenta"}</p>
        {clock.next && parts ? (
          <p className="flex shrink-0 items-center gap-2 rounded-full bg-black/30 px-3 py-1.5 text-[12px] text-white/60">
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--ini-copper)]" aria-hidden="true" />
            <span className="max-w-[11rem] truncate max-[420px]:hidden">{eventTitle(clock.next)}</span>
            <span className="font-medium tabular-nums text-white">
              {parts.days > 0 ? `${parts.days}d ` : ""}
              {countdownClock(parts)}
            </span>
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-5 pb-5 pt-6">
        <div className="min-w-0">
          <p className="text-[12px] text-white/50">Saldo disponible</p>
          <p
            className="mt-1.5 text-[44px] font-semibold leading-none tracking-[-0.045em] tabular-nums"
            style={{ color: negative ? "var(--ini-red)" : "#fff" }}
          >
            {animatedCash !== null ? money(animatedCash) : dash}
          </p>
        </div>
        {gain !== null ? (
          <div className="text-right">
            <p className="text-[12px] text-white/50">Con el plan de hoy</p>
            <p className="mt-1.5 text-[20px] font-semibold leading-none tabular-nums" style={{ color: gain > 0 ? "var(--ini-mint)" : "var(--ini-red)" }}>
              {signedPoints(gain)} <span className="text-[13px] font-medium text-white/45">pts</span>
            </p>
          </div>
        ) : null}
      </div>

      {negative || alert ? (
        <p
          className="mx-5 mb-5 flex items-center gap-2 rounded-xl px-3 py-2 text-[13px]"
          style={{
            color: negative || alert?.status === "fail" ? "var(--ini-red)" : "var(--ini-amber)",
            background: negative || alert?.status === "fail" ? "rgba(255,125,102,0.1)" : "rgba(245,181,68,0.1)",
          }}
        >
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
          {negative ? "Saldo negativo: puntúas 0 hasta volver a positivo." : alert?.headline || "Revisa tu línea roja"}
        </p>
      ) : null}

      <div className="ini-stats">
        <Stat
          label="Valor de plantilla"
          value={typeof value === "number" ? money(value) : dash}
          sub={typeof valueDay === "number" && valueDay !== 0 ? `${signedMoney(valueDay)} hoy` : null}
          tone={undefined}
        />
        <Stat label="Posición" value={rank !== null ? `${rank}º` : dash} sub={field ? `de ${field}` : null} />
        <Stat
          label="Puntos"
          value={pts !== null ? String(Math.round(pts)) : dash}
          sub={typeof gap === "number" && gap !== 0 ? `${gap > 0 ? "+" : "−"}${Math.abs(gap)} vs líder` : gap === 0 ? "Líder" : null}
        />
        <Stat
          label="Saldo tras el plan"
          value={cashEnd !== null ? money(cashEnd) : dash}
          tone={cashEnd !== null && cashEnd < 0 ? "var(--ini-red)" : undefined}
          sub={typeof target === "number" ? `Once: ${points(target)} pts` : null}
        />
      </div>
    </section>
  );
}

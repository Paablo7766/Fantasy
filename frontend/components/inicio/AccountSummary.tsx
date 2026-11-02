"use client";

import { useMemo, type ReactNode } from "react";
import { money, signedMoney } from "@/components/ui/kit";
import { buildClockReport, countdownClock, countdownParts, eventTitle } from "@/lib/inicio/hoy";
import { useNow } from "@/lib/core/useClock";
import type { PlanPayload, SquadsPayload } from "@/lib/types";

function Stat({ value, label, sub }: { value: string; label: string; sub?: string | null }) {
  return (
    <div className="min-w-0 rounded-2xl border border-white/[0.07] bg-white/[0.05] px-3 py-3 backdrop-blur-md">
      <p className="truncate text-[0.8rem] text-white/50">{label}</p>
      <p className="mt-1.5 truncate text-[1.2rem] font-semibold leading-none tabular-nums text-white">{value}</p>
      {sub ? <p className="mt-1.5 truncate text-[12px] tabular-nums text-white/45">{sub}</p> : null}
    </div>
  );
}

function Pill({ children, tone }: { children: ReactNode; tone: "warn" | "fail" }) {
  const color = tone === "fail" ? "bg-[#FF5A36]/15 text-[#FFA088]" : "bg-[#FFB454]/15 text-[#FFD08A]";
  return <p className={`flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-[12.5px] font-medium ${color}`}>{children}</p>;
}

/**
 * Cabecera de Inicio: cómo está tu cuenta ahora mismo (saldo, valor, puntos y
 * posición). No recomienda nada: lo que suma el plan va justo debajo.
 */
export function AccountSummary({
  plan,
  squads,
  loading,
}: {
  plan: PlanPayload | null;
  squads: SquadsPayload | null;
  loading: boolean;
}) {
  const nowMs = useNow();
  const mounted = nowMs > 0;
  const clock = useMemo(() => buildClockReport(plan, mounted ? nowMs : 0), [plan, mounted, nowMs]);
  const parts = clock.next && mounted ? countdownParts(clock.next.ms, nowMs) : null;

  const own = squads?.self ?? null;
  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : (own?.cash_eur ?? null);
  const value = own?.market_value_total ?? null;
  const valueDay = own?.price_delta_day ?? null;
  const rank = typeof own?.rank === "number" ? own.rank : (plan?.mode?.own_rank ?? null);
  const field = typeof squads?.rival_count === "number" ? squads.rival_count + 1 : null;
  const pts = typeof own?.points === "number" ? own.points : (plan?.mode?.own_points ?? null);
  const gap = plan?.mode?.gap_to_leader ?? null;
  const locked = own?.locked_clauses ?? null;
  const players = own?.player_count ?? null;
  const redLine = plan?.red_line;
  const dash = loading ? "…" : "—";
  const leagueName = squads?.league_name || plan?.league_name || null;

  return (
    <section className="home-hero" aria-label="Tu cuenta">
      <div className="relative flex items-center justify-between gap-3">
        <p className="min-w-0 truncate text-[13px] font-medium text-white/60">
          Tu cuenta{leagueName ? ` · ${leagueName}` : ""}
        </p>
        <p className="flex min-w-0 shrink-0 items-center gap-2 rounded-full border border-white/10 bg-black/25 px-3 py-1.5 text-[12px] text-white/70 backdrop-blur-md">
          {clock.next && parts ? (
            <>
              <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[#FF7A3D]" aria-hidden="true" />
              <span className="max-w-[9rem] truncate">{eventTitle(clock.next)}</span>
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

      <div className="relative mt-5">
        <p className="text-[12px] text-white/55">Saldo disponible</p>
        <p
          className={`mt-1 text-[3.2rem] font-semibold leading-none tracking-[-0.045em] tabular-nums ${
            typeof cash === "number" && cash < 0 ? "text-[#FF8F6B]" : "text-white"
          }`}
        >
          {typeof cash === "number" ? money(cash) : dash}
        </p>
        {typeof cash === "number" && cash < 0 ? (
          <p className="mt-2 text-[13px] text-[#FFA088]">Saldo negativo: puntúas 0 hasta volver a positivo.</p>
        ) : null}
      </div>

      {redLine && redLine.status && redLine.status !== "ok" ? (
        <div className="relative mt-4">
          <Pill tone={redLine.status === "fail" ? "fail" : "warn"}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
            {redLine.headline || "Revisa tu línea roja"}
          </Pill>
        </div>
      ) : null}

      <div className="relative mt-6 grid grid-cols-2 gap-2.5 min-[720px]:grid-cols-4">
        <Stat
          value={typeof value === "number" ? money(value) : dash}
          label="Valor de plantilla"
          sub={typeof valueDay === "number" && valueDay !== 0 ? `${signedMoney(valueDay)} hoy` : players ? `${players} jugadores` : null}
        />
        <Stat value={rank !== null ? `${rank}º` : dash} label="Posición" sub={field ? `de ${field}` : null} />
        <Stat
          value={pts !== null ? String(Math.round(pts)) : dash}
          label="Puntos"
          sub={typeof gap === "number" && gap !== 0 ? `${gap > 0 ? "+" : "−"}${Math.abs(gap)} vs líder` : null}
        />
        <Stat value={locked !== null ? String(locked) : dash} label="Cláusulas con candado" sub={players ? `de ${players}` : null} />
      </div>
    </section>
  );
}

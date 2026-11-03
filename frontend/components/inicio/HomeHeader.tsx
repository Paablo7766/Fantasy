"use client";

import { useMemo, type CSSProperties, type ReactNode } from "react";
import { money, signedMoney } from "@/components/ui/kit";
import { points } from "@/lib/core/format";
import { buildClockReport, countdownParts, eventTitle, signedPoints } from "@/lib/inicio/hoy";
import { useNow } from "@/lib/core/useClock";
import { useCountUp } from "@/components/inicio/ui";
import type { PlanPayload, SquadsPayload } from "@/lib/types";

const pad = (n: number) => String(n).padStart(2, "0");

function Stat({
  label,
  value,
  sub,
  tone,
  meter,
  icon,
}: {
  label: string;
  value: string;
  sub?: string | null;
  tone?: string;
  /** 0..1: barra fina bajo la cifra (p. ej. posición en la liga). */
  meter?: number | null;
  icon: ReactNode;
}) {
  return (
    <div className="ini-stat min-w-0" data-ui="hero-stat">
      <p className="flex items-center gap-1.5 truncate text-[12px] text-white/45">
        <span className="ini-stat__icon" aria-hidden="true">
          {icon}
        </span>
        {label}
      </p>
      <p className="mt-2 truncate text-[22px] font-semibold leading-none tracking-[-0.025em] tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {typeof meter === "number" ? (
        <span className="ini-meter mt-2.5" aria-hidden="true">
          <span style={{ width: `${Math.max(4, Math.min(100, meter * 100))}%` }} />
        </span>
      ) : null}
      <p className="mt-1.5 h-4 truncate text-[12px] tabular-nums text-white/40">{sub || ""}</p>
    </div>
  );
}

const ico = { viewBox: "0 0 16 16", width: 12, height: 12, fill: "none", stroke: "currentColor", strokeWidth: 1.6 } as const;

/**
 * Cabecera de Inicio: saldo como cifra protagonista, cuenta atrás grande al
 * próximo hito y cuatro datos clave en una tira. En escritorio ocupa todo el
 * ancho; lo que hay que hacer va debajo, en dos columnas.
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
  const rankMeter = rank !== null && field && field > 1 ? (field - rank) / (field - 1) : null;
  const urgent = parts ? parts.totalMs < 3 * 3600 * 1000 : false;

  const tiles = parts
    ? ([
        ...(parts.days > 0 ? [["días", String(parts.days)]] : []),
        ["horas", pad(parts.hours)],
        ["min", pad(parts.minutes)],
        ["seg", pad(parts.seconds)],
      ] as const)
    : null;

  return (
    <section className="ini-card ini-hero ini-in" style={{ "--i": 0 } as CSSProperties} aria-label="Tu cuenta" data-ui="home-hero">
      <span className="ini-hero__grid-bg" aria-hidden="true" />

      <div className="ini-hero__body">
        <div className="ini-hero__main min-w-0">
          <p className="ini-chip">
            <span className="ini-chip__dot" aria-hidden="true" />
            <span className="truncate">{leagueName || "Tu cuenta"}</span>
          </p>

          <p className="mt-6 text-[12px] font-medium uppercase tracking-[0.14em] text-white/45">Saldo disponible</p>
          <p
            className="ini-cash mt-2 tabular-nums"
            data-negative={negative ? "true" : undefined}
            data-ui="home-cash"
          >
            {animatedCash !== null ? money(animatedCash) : dash}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {gain !== null ? (
              <span className="ini-pill" data-tone={gain > 0 ? "up" : "down"}>
                <svg {...ico} aria-hidden="true">
                  <path d={gain > 0 ? "M4 10l4-4 4 4" : "M4 6l4 4 4-4"} strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {signedPoints(gain)} pts con el plan de hoy
              </span>
            ) : null}
            {cashEnd !== null ? (
              <span className="ini-pill" data-tone={cashEnd < 0 ? "down" : undefined}>
                Tras el plan · {money(cashEnd)}
              </span>
            ) : null}
          </div>

          {negative || alert ? (
            <p
              className="mt-4 flex items-center gap-2 rounded-xl px-3 py-2 text-[13px]"
              style={{
                color: negative || alert?.status === "fail" ? "var(--ini-red)" : "var(--ini-amber)",
                background: negative || alert?.status === "fail" ? "rgba(255,125,102,0.1)" : "rgba(245,181,68,0.1)",
              }}
              role="alert"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
              {negative ? "Saldo negativo: puntúas 0 hasta volver a positivo." : alert?.headline || "Revisa tu línea roja"}
            </p>
          ) : null}
        </div>

        {clock.next && tiles ? (
          <div className="ini-clock" data-urgent={urgent ? "true" : undefined} data-ui="home-countdown">
            <p className="flex items-center gap-2 text-[12px] text-white/55">
              <span className="ini-live" aria-hidden="true" />
              Próximo hito
            </p>
            <p className="mt-1.5 truncate text-[15px] font-semibold tracking-[-0.01em] text-white">{eventTitle(clock.next)}</p>
            <div className="ini-clock__tiles mt-4" role="timer" aria-label={`Faltan ${tiles.map(([u, v]) => `${v} ${u}`).join(", ")}`}>
              {tiles.map(([unit, v], idx) => (
                <div key={unit} className="ini-tile">
                  <span className="ini-tile__v tabular-nums">{v}</span>
                  <span className="ini-tile__u">{unit}</span>
                  {idx < tiles.length - 1 ? <span className="ini-tile__sep" aria-hidden="true">:</span> : null}
                </div>
              ))}
            </div>
            {clock.next.localLabel ? <p className="mt-3 truncate text-[12px] text-white/40">{clock.next.localLabel}</p> : null}
          </div>
        ) : null}
      </div>

      <div className="ini-stats">
        <Stat
          label="Valor de plantilla"
          icon={
            <svg {...ico}>
              <path d="M2.5 12.5 6 8.5l2.5 2.5 5-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          }
          value={typeof value === "number" ? money(value) : dash}
          sub={typeof valueDay === "number" && valueDay !== 0 ? `${signedMoney(valueDay)} hoy` : null}
        />
        <Stat
          label="Posición"
          icon={
            <svg {...ico}>
              <path d="M5 2.5h6v3a3 3 0 0 1-6 0v-3ZM8 8.5v3M5.5 13.5h5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          }
          value={rank !== null ? `${rank}º` : dash}
          meter={rankMeter}
          sub={field ? `de ${field}` : null}
        />
        <Stat
          label="Puntos"
          icon={
            <svg {...ico}>
              <path d="M8 2.5l1.7 3.5 3.8.5-2.8 2.6.7 3.8L8 11.1l-3.4 1.8.7-3.8-2.8-2.6 3.8-.5L8 2.5Z" strokeLinejoin="round" />
            </svg>
          }
          value={pts !== null ? String(Math.round(pts)) : dash}
          sub={typeof gap === "number" && gap !== 0 ? `${gap > 0 ? "+" : "−"}${Math.abs(gap)} vs líder` : gap === 0 ? "Líder" : null}
        />
        <Stat
          label="Saldo tras el plan"
          icon={
            <svg {...ico}>
              <rect x="2.5" y="4" width="11" height="8.5" rx="1.8" />
              <path d="M10.5 8.2h1" strokeLinecap="round" />
            </svg>
          }
          value={cashEnd !== null ? money(cashEnd) : dash}
          tone={cashEnd !== null && cashEnd < 0 ? "var(--ini-red)" : undefined}
          sub={typeof target === "number" ? `Once: ${points(target)} pts` : null}
        />
      </div>
    </section>
  );
}

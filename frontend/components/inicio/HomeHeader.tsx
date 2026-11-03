"use client";

import { useMemo, type CSSProperties, type ReactNode } from "react";
import { money, signedMoney } from "@/components/ui/kit";
import { points } from "@/lib/core/format";
import { buildClockReport, countdownParts, eventTitle, signedPoints } from "@/lib/inicio/hoy";
import { useNow } from "@/lib/core/useClock";
import { useCountUp } from "@/components/inicio/ui";
import type { PlanPayload, SquadsPayload } from "@/lib/types";

const pad = (n: number) => String(n).padStart(2, "0");

/** «56,9 M€» → cifra grande + unidad pequeña, como «190 lbs». */
function Figure({ text }: { text: string }) {
  const cut = text.lastIndexOf(" ");
  if (cut <= 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, cut)}
      <small>{text.slice(cut + 1)}</small>
    </>
  );
}

function Tile({ icon, value, label, sub, children }: { icon?: ReactNode; value?: ReactNode; label: string; sub?: string | null; children?: ReactNode }) {
  return (
    <div className="ini-tile" data-ui="home-tile">
      <div className="flex items-start justify-between gap-2">
        {children ?? <span className="ini-tile__value tabular-nums">{value}</span>}
        {icon ? (
          <span className="ini-tile__icon shrink-0" aria-hidden="true">
            {icon}
          </span>
        ) : null}
      </div>
      <div className="min-w-0">
        {children && value ? <p className="ini-tile__value tabular-nums">{value}</p> : null}
        <p className="ini-tile__label truncate">{label}</p>
        <p className="ini-tile__sub truncate tabular-nums">{sub || " "}</p>
      </div>
    </div>
  );
}

function Ring({ value, ratio }: { value: string; ratio: number | null }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const p = ratio === null ? 0 : Math.max(0.04, Math.min(1, ratio));
  return (
    <svg className="ini-ring" viewBox="0 0 52 52" aria-hidden="true">
      <circle className="ini-ring__track" cx="26" cy="26" r={r} />
      <circle className="ini-ring__bar" cx="26" cy="26" r={r} strokeDasharray={c} strokeDashoffset={c * (1 - p)} transform="rotate(-90 26 26)" />
      <text x="26" y="31" textAnchor="middle">
        {value}
      </text>
    </svg>
  );
}

/** Matriz 10×3: un punto por cada 10 % del valor; el último encendido brilla. */
function Dots({ ratio }: { ratio: number | null }) {
  const total = 30;
  const on = ratio === null ? 0 : Math.round(Math.max(0, Math.min(1, ratio)) * total);
  return (
    <span className="ini-dots" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} data-on={i < on ? "true" : undefined} data-hot={i === on - 1 ? "true" : undefined} />
      ))}
    </span>
  );
}

const ico = { viewBox: "0 0 16 16", width: 14, height: 14, fill: "none", stroke: "currentColor", strokeWidth: 1.6 } as const;

/**
 * Cabecera de Inicio: hero oscuro con halo naranja (saldo centrado y botón
 * blanco con la cuenta atrás) y cuatro tarjetas «bento» con las cifras clave.
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
  const rankRatio = rank !== null && field && field > 1 ? (field - rank) / (field - 1) : null;
  const leaderPts = typeof pts === "number" && typeof gap === "number" ? pts - gap : null;
  const ptsRatio = typeof pts === "number" && leaderPts && leaderPts > 0 ? pts / Math.max(leaderPts, pts) : null;
  const urgent = parts ? parts.totalMs < 3 * 3600 * 1000 : false;
  const timeText = parts ? `${parts.days > 0 ? `${parts.days}d ` : ""}${pad(parts.hours)}:${pad(parts.minutes)}:${pad(parts.seconds)}` : null;

  return (
    <div className="ini-top">
      <section className="ini-card ini-hero ini-in" style={{ "--i": 0 } as CSSProperties} aria-label="Tu cuenta" data-ui="home-hero">
        <span className="ini-hero__glow" aria-hidden="true" />

        <div className="ini-hero__bar">
          <p className="ini-chip">
            <span className="truncate">{leagueName || "Tu cuenta"}</span>
          </p>
          {gain !== null ? (
            <p className="ini-chip">
              <span className="ini-pill" data-tone={gain > 0 ? "up" : "down"}>
                {signedPoints(gain)} pts
              </span>
              <span className="max-[420px]:hidden">con el plan</span>
            </p>
          ) : null}
        </div>

        <div className="ini-hero__center">
          <p className="ini-kicker">Saldo disponible</p>
          <p className="ini-cash tabular-nums" data-negative={negative ? "true" : undefined} data-ui="home-cash">
            {animatedCash !== null ? <Figure text={money(animatedCash)} /> : dash}
          </p>
          {cashEnd !== null ? (
            <p className="ini-pill mt-3" data-tone={cashEnd < 0 ? "down" : undefined}>
              Tras el plan · {money(cashEnd)}
            </p>
          ) : null}

          {clock.next && timeText ? (
            <p className="ini-cta" data-urgent={urgent ? "true" : undefined} role="timer" data-ui="home-countdown">
              <span className="ini-live" aria-hidden="true" />
              <span className="max-w-[14rem] truncate">{eventTitle(clock.next)}</span>
              <span className="ini-cta__time">{timeText}</span>
              {clock.next.localLabel ? <span className="ini-cta__when max-sm:hidden">{clock.next.localLabel}</span> : null}
            </p>
          ) : null}

          {negative || alert ? (
            <p
              className="ini-alert"
              style={{ color: negative || alert?.status === "fail" ? "#ffb3a4" : "#ffd58a" }}
              role="alert"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
              {negative ? "Saldo negativo: puntúas 0 hasta volver a positivo." : alert?.headline || "Revisa tu línea roja"}
            </p>
          ) : null}
        </div>
      </section>

      <div className="ini-bento ini-in" style={{ "--i": 1 } as CSSProperties}>
        <Tile
          value={<Ring value={rank !== null ? String(rank) : dash} ratio={rankRatio} />}
          label="Posición"
          sub={field ? `de ${field} en la liga` : null}
          icon={
            <svg {...ico}>
              <path d="M5 2.5h6v3a3 3 0 0 1-6 0v-3ZM8 8.5v3M5.5 13.5h5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          }
        />
        <Tile
          value={pts !== null ? <Figure text={`${Math.round(pts)} pts`} /> : dash}
          label="Puntos"
          sub={typeof gap === "number" && gap !== 0 ? `${gap > 0 ? "+" : "−"}${Math.abs(gap)} vs líder` : gap === 0 ? "Eres líder" : null}
        >
          <Dots ratio={ptsRatio} />
        </Tile>
        <Tile
          value={typeof value === "number" ? <Figure text={money(value)} /> : dash}
          label="Valor de plantilla"
          sub={typeof valueDay === "number" && valueDay !== 0 ? `${signedMoney(valueDay)} hoy` : null}
          icon={
            <svg {...ico}>
              <path d="M2.5 12.5 6 8.5l2.5 2.5 5-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          }
        />
        <Tile
          value={typeof target === "number" ? <Figure text={`${points(target)} pts`} /> : dash}
          label="Once previsto"
          sub={cashEnd !== null ? `Saldo final ${money(cashEnd)}` : null}
          icon={
            <svg {...ico}>
              <circle cx="8" cy="4" r="1.4" />
              <circle cx="4" cy="8" r="1.4" />
              <circle cx="12" cy="8" r="1.4" />
              <circle cx="8" cy="12" r="1.4" />
            </svg>
          }
        />
      </div>
    </div>
  );
}

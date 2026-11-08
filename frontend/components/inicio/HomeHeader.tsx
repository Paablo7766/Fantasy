"use client";

import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { money, signedMoney } from "@/components/ui/kit";
import { points } from "@/lib/core/format";
import { buildClockReport, countdownParts, eventTitle } from "@/lib/inicio/hoy";
import { useNow } from "@/lib/core/useClock";
import { RefreshChip } from "@/components/inicio/RefreshChip";
import { RollingNumber } from "@/components/ui/RollingNumber";
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
      {icon ? (
        <span className="ini-tile__icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children ? <div className="ini-tile__viz">{children}</div> : null}
      {value !== undefined ? <p className="ini-tile__value tabular-nums">{value}</p> : null}
      <div className="min-w-0 max-w-full">
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
      <text x="26" y="31.5" textAnchor="middle">
        {value}
      </text>
    </svg>
  );
}

/** Cifra que cuenta desde cero al montarse (cada dato del hero se monta con su clave). */
function CountFigure({ value, fmt }: { value: number; fmt: (v: number) => string }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const t0 = performance.now();
    const dur = reduced ? 0 : 1800;
    let frame = 0;
    const tick = (now: number) => {
      const p = dur ? Math.min(1, (now - t0) / dur) : 1;
      // ease-out exponencial: arranca rápido y se posa muy despacio.
      const e = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
      setV(value * e);
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return (
    <span className="ini-cash__in">
      <Figure text={fmt(v)} />
    </span>
  );
}

/** Tus puntos frente a los del líder: dos barras con su cifra. */
function VsLeader({ you, leader }: { you: number | null; leader: number | null }) {
  if (you === null || leader === null) return <span className="ini-vs" />;
  const top = Math.max(you, leader, 1);
  const rows = [
    { label: "Tú", v: you, me: true },
    { label: "Líder", v: leader, me: false },
  ];
  return (
    <span className="ini-vs" aria-hidden="true">
      {rows.map((row) => (
        <span key={row.label} className="ini-vs__row">
          <span className="ini-vs__label">{row.label}</span>
          <span className="ini-vs__track">
            <span data-me={row.me ? "true" : undefined} style={{ width: `${Math.max(4, (row.v / top) * 100)}%` }} />
          </span>
          <span className="ini-vs__v tabular-nums">{Math.round(row.v)}</span>
        </span>
      ))}
    </span>
  );
}

const DATE_FMT = new Intl.DateTimeFormat("es-ES", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Madrid" });

/**
 * Cabecera de Inicio: hero oscuro con halo naranja (saldo centrado y botón
 * blanco con la cuenta atrás) y cuatro tarjetas «bento» con las cifras clave.
 */
export function HomeHeader({ plan, squads, loading }: { plan: PlanPayload | null; squads: SquadsPayload | null; loading: boolean }) {
  const nowMs = useNow();
  const mounted = nowMs > 0;
  const clock = useMemo(() => buildClockReport(plan, mounted ? nowMs : 0), [plan, mounted, nowMs]);
  // La cuenta atrás es la del bloqueo del once; un desbloqueo suelto no es «la hora límite».
  const target = clock.lock ?? clock.next;
  const parts = target && mounted ? countdownParts(target.ms, nowMs) : null;

  const own = squads?.self ?? null;
  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : (own?.cash_eur ?? null);
  const value = own?.market_value_total ?? null;
  const valueDay = own?.price_delta_day ?? null;
  const rank = typeof own?.rank === "number" ? own.rank : (plan?.mode?.own_rank ?? null);
  const field = typeof squads?.rival_count === "number" ? squads.rival_count + 1 : null;
  const pts = typeof own?.points === "number" ? own.points : (plan?.mode?.own_points ?? null);
  const gap = plan?.mode?.gap_to_leader ?? null;
  const redLine = plan?.red_line;
  const leagueName = squads?.league_name || plan?.league_name || null;

  const fichajes = plan?.plan_fichajes;
  const cashEnd = typeof fichajes?.saldo_al_final === "number" ? fichajes.saldo_al_final : null;
  // Fase de la app: en qué momento estamos y, por tanto, en qué se enfoca.
  // Las alertas largas (deuda, cláusulas) viven en el Plan, no en el hero.
  const paron = fichajes?.paron?.activo ? fichajes.paron : null;
  const phase = paron
    ? { key: "paron", label: "Parón de selecciones", sub: paron.fase_nombre || "Mercado abierto" }
    : clock.lock
      ? { key: "prep", label: "Preparando la jornada", sub: "Mercado y once abiertos" }
      : clock.exhausted
        ? { key: "live", label: "Jornada en juego", sub: "Once bloqueado" }
        : null;

  const dash = loading ? "…" : "—";
  const negative = typeof cash === "number" && cash < 0;
  const alert = redLine && redLine.status && redLine.status !== "ok" ? redLine : null;
  const rankRatio = rank !== null && field && field > 1 ? (field - rank) / (field - 1) : null;
  const leaderPts = typeof pts === "number" && typeof gap === "number" ? pts - gap : null;
  const urgent = parts ? parts.totalMs < 3 * 3600 * 1000 : false;
  // Once previsto: el mismo once recomendado que enseña la pestaña Once, para que las dos cifras coincidan.
  // El once del plan de fichajes (solo lo ejecutable hoy) queda como respaldo.
  const onceTarget = [plan?.lineup?.expected_points, fichajes?.puntos_once, plan?.lineup?.saved_points, fichajes?.puntos_once_actual].find(
    (v): v is number => typeof v === "number" && v > 0,
  ) ?? null;
  const dateText = mounted ? DATE_FMT.format(nowMs) : "";

  // Cifra protagonista: rota cada 6 s entre seis datos distintos. Cada uno
  // entra con su propio conteo desde cero y un fundido largo.
  const gain = typeof fichajes?.mejora_puntos_jornada === "number" && Math.abs(fichajes.mejora_puntos_jornada) >= 0.05 ? fichajes.mejora_puntos_jornada : null;
  const pts1 = (v: number) => `${points(v)} pts`;
  type Fig = { key: string; label: string; v: number | null; fmt: (v: number) => string; other: string };
  const rawFigures: (Fig | null)[] = [
    { key: "cash", label: "Saldo disponible", v: cash, fmt: money, other: cashEnd !== null ? `Tras el plan · ${money(cashEnd)}` : "Listo para pujar hoy" },
    gain !== null ? { key: "gain", label: "Mejora con el plan de hoy", v: gain, fmt: (v: number) => `${v > 0 ? "+" : "−"}${points(Math.abs(v))} pts`, other: "Puntos extra en tu once si lo sigues" } : null,
    cashEnd !== null ? { key: "end", label: "Saldo tras el plan", v: cashEnd, fmt: money, other: "Lo que te queda tras pujas y ventas" } : null,
    typeof value === "number" ? { key: "value", label: "Valor de tu plantilla", v: value, fmt: money, other: typeof valueDay === "number" && valueDay !== 0 ? `${signedMoney(valueDay)} desde ayer` : "Suma del valor de mercado" } : null,
    onceTarget !== null ? { key: "once", label: "Once previsto", v: onceTarget, fmt: pts1, other: "Puntos esperados de tu mejor alineación" } : null,
    typeof gap === "number" && gap < 0 ? { key: "gap", label: "Distancia al líder", v: Math.abs(gap), fmt: (v: number) => `${Math.round(v)} pts`, other: rank !== null && field ? `Vas ${rank}º de ${field}` : "Por recortar esta jornada" } : null,
  ];
  const figures = rawFigures.filter((f): f is Fig => f !== null);
  const slide = figures.length > 1 && mounted && typeof cash === "number" ? Math.floor(nowMs / 6000) % figures.length : 0;
  const shown = figures[slide];
  const shownNegative = typeof shown.v === "number" && shown.v < 0 && shown.key !== "gain";

  // Formato corto: lejos, días y horas; a menos de un día, horas y minutos; en la última hora, minutos y segundos.
  const timeText = parts
    ? parts.days > 0
      ? `${parts.days}d ${parts.hours}h`
      : parts.hours > 0
        ? `${parts.hours}h ${pad(parts.minutes)}m`
        : `${pad(parts.minutes)}:${pad(parts.seconds)}`
    : null;

  return (
    <div className="ini-top">
      <section className="ini-card ini-hero ini-in" style={{ "--i": 0 } as CSSProperties} aria-label="Tu cuenta" data-ui="home-hero">
        <span className="ini-hero__glow" aria-hidden="true" />

        <div className="ini-hero__bar">
          <span className="ini-hero__date">{dateText}</span>
          <p className="ini-chip justify-self-center">
            <span className="truncate">{leagueName || "Tu cuenta"}</span>
          </p>
          <RefreshChip />
        </div>

        <div className="ini-hero__center">
          <p className="ini-swap" aria-live="polite">
            <span key={shown.key} className="ini-kicker ini-swap__in">
              {shown.label}
            </span>
          </p>
          <p className="ini-cash tabular-nums" data-negative={shownNegative ? "true" : undefined} data-ui="home-cash">
            {typeof shown.v === "number" ? <CountFigure key={shown.key} value={shown.v} fmt={shown.fmt} /> : dash}
          </p>
          <p className="ini-swap mt-3">
            <span key={shown.key} className="ini-pill ini-swap__in ini-swap__in--late">
              {shown.other}
            </span>
          </p>
          {figures.length > 1 ? (
            <span className="ini-steps" aria-hidden="true">
              {figures.map((f, i) => (
                <span key={f.key} data-on={i === slide ? "true" : undefined} />
              ))}
            </span>
          ) : null}

          {phase ? (
            <p className="ini-phase" data-phase={phase.key} data-ui="home-phase">
              <span>{phase.label}</span>
              <i aria-hidden="true" />
              <span>{phase.sub}</span>
            </p>
          ) : null}

          {target && timeText ? (
            <p className="ini-cta" data-urgent={urgent ? "true" : undefined} role="timer" data-ui="home-countdown" title={eventTitle(target)}>
              <span className="ini-live" aria-hidden="true" />
              <span className="ini-cta__label">{target.kind === "inicio_jornada" ? "Inicio de jornada" : eventTitle(target)}</span>
              <span className="ini-cta__time">{timeText}</span>
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
          label="Posición"
          sub={field ? `de ${field} en la liga` : null}
        >
          <Ring value={rank !== null ? `${rank}º` : dash} ratio={rankRatio} />
        </Tile>
        <Tile
          value={pts !== null ? <RollingNumber value={pts} format={(v) => `${Math.round(v)} pts`} render={(t) => <Figure text={t} />} memoKey="tile:puntos" /> : dash}
          label="Puntos"
          sub={typeof gap === "number" && gap !== 0 ? `${gap > 0 ? "+" : "−"}${Math.abs(gap)} vs líder` : gap === 0 ? "Eres líder" : null}
        >
          <VsLeader you={pts} leader={leaderPts} />
        </Tile>
        <Tile
          value={typeof value === "number" ? <RollingNumber value={value} format={money} render={(t) => <Figure text={t} />} memoKey="tile:valor" /> : dash}
          label="Valor de plantilla"
          sub={typeof valueDay === "number" && valueDay !== 0 ? `${signedMoney(valueDay)} hoy` : null}
        />
        <Tile
          value={onceTarget !== null ? <RollingNumber value={onceTarget} format={(v) => `${points(v)} pts`} render={(t) => <Figure text={t} />} memoKey="tile:once" /> : dash}
          label="Once previsto"
          sub={cashEnd !== null ? `Saldo final ${money(cashEnd)}` : null}
        />
      </div>
    </div>
  );
}

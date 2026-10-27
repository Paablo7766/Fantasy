"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  buildClockReport,
  buildDeadlineMode,
  buildSurvival,
  clockEventDetail,
  countdownParts,
  eventTitle,
  postureCopy,
  two,
  type CheckTone,
  type SurvivalCheck,
} from "@/lib/hoy";
import { ageFromStamp, durationAgo, stamp } from "@/lib/format";
import { useNow } from "@/lib/useClock";
import type { PlanPayload } from "@/lib/types";
const MARK: Record<CheckTone, { char: string; className: string }> = {
  ok: { char: "✓", className: "hoy-rail__mark hoy-rail__mark--ok" },
  risk: { char: "!", className: "hoy-rail__mark hoy-rail__mark--risk" },
  blocker: { char: "✕", className: "hoy-rail__mark hoy-rail__mark--blocker" },
};

/** Sólo las tres condiciones que anulan la jornada: caja, XI y once guardado. */
const RAIL_ORDER = ["caja", "xi", "once"] as const;

function RailRow({ check }: { check: SurvivalCheck }) {
  const mark = MARK[check.tone];
  const valueTone =
    check.tone === "blocker"
      ? "text-[#fca5a5]"
      : check.tone === "risk"
        ? "text-[color:var(--hoy-gold)]"
        : "text-[color:var(--hoy-ink)]";
  return (
    <div className="hoy-rail__row">
      <span className={mark.className} aria-hidden="true">
        {mark.char}
      </span>
      <div className="min-w-0">
        <p className="truncate text-[12.5px] font-medium leading-4 text-[color:var(--hoy-ink)]">{check.label}</p>
        {check.tone !== "ok" ? (
          <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-[color:var(--hoy-muted)]">{check.detail}</p>
        ) : null}
      </div>
      <span className={`metric-value shrink-0 text-right text-[12.5px] tabular-nums ${valueTone}`}>{check.value}</span>
    </div>
  );
}

const NEXT_LABEL: Record<string, string> = {
  clausulazo_cierra: "Cierre de clausulazos",
  inicio_jornada: "Inicio de jornada",
  desbloqueo: "Próximo desbloqueo",
  snipe: "Snipe de puja",
};

/** Cómo se resuelve cada check que no está en verde, con la puerta correcta. */
const FIX_COPY: Record<string, string> = {
  caja: "vende un jugador en Cartera hasta dejar el saldo en positivo.",
  xi: "ficha el jugador que falta en el Mercado y guarda el once con 11.",
};

const FIX_HREF: Record<string, string> = { caja: "/cartera", xi: "/mercado", once: "/once" };
const FIX_LABEL: Record<string, string> = { caja: "Vender", xi: "Ir al mercado", once: "Abrir once" };

export function HoyHero({
  plan,
  loading,
  refreshing,
  onRefresh,
}: {
  plan: PlanPayload | null;
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const nowMs = useNow();
  const mounted = nowMs > 0;
  // La edad sale del sello absoluto de captura (``last_updated``), no de un
  // ``photo_age_seconds`` congelado en la respuesta: así envejece sola en cada
  // tick del reloj y no hay estado que se pueda quedar desfasado.
  const planAge = ageFromStamp(plan?.last_updated, nowMs) ?? plan?.photo_age_seconds ?? null;

  const clock = useMemo(() => buildClockReport(plan, mounted ? nowMs : 0), [plan, mounted, nowMs]);
  const deadline = useMemo(() => buildDeadlineMode(clock, mounted ? nowMs : 0), [clock, mounted, nowMs]);
  const posture = useMemo(() => postureCopy(plan), [plan]);
  const survival = useMemo(() => buildSurvival(plan), [plan]);

  const rail = useMemo(() => {
    const ordered = RAIL_ORDER.map((id) => survival.checks.find((check) => check.id === id)).filter(
      (check): check is SurvivalCheck => Boolean(check),
    );
    const rest = survival.checks.filter((check) => !RAIL_ORDER.includes(check.id as (typeof RAIL_ORDER)[number]));
    return [...ordered, ...rest.filter((check) => check.id !== "clausulas")];
  }, [survival]);

  const parts = clock.next && mounted ? countdownParts(clock.next.ms, nowMs) : null;
  const critical = deadline.phase === "t10" || deadline.phase === "t60";
  const verdict = survival.blocked ? "bloqueo" : survival.risks.length ? "aviso" : "ok";
  const verdictCopy =
    verdict === "bloqueo" ? "Jornada en cero" : verdict === "aviso" ? "Revisa un punto" : "Jornada a salvo";
  // Sólo se enseña el aviso cuando desbloquear el punto cambia algo hoy.
  const actionable =
    plan && !loading ? survival.checks.find((check) => check.tone !== "ok" && check.id !== "clausulas") || null : null;

  return (
    <section
      className={`hoy-hero ${survival.blocked ? "hoy-hero--alert" : ""}`}
      aria-labelledby="hoy-veredicto"
    >
      <div className="relative grid gap-6 p-4 md:p-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-8">
        {/* Veredicto + cuenta atrás */}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="hoy-label" id="hoy-veredicto">
              {clock.next ? NEXT_LABEL[clock.next.kind || ""] || "Próximo hito" : "Estado del día"}
            </p>
            <div className="flex items-center gap-2">
              {planAge !== null && planAge > 15 * 60 ? (
                <span className="hoy-chip hoy-chip--gold">Foto de {durationAgo(planAge)}</span>
              ) : null}
              {critical ? (
                <span className={deadline.phase === "t10" ? "hoy-chip hoy-chip--red" : "hoy-chip hoy-chip--gold"}>
                  {deadline.label.split(" · ")[0]}
                </span>
              ) : null}
              <button
                type="button"
                onClick={onRefresh}
                disabled={refreshing}
                className="hoy-btn"
                aria-label="Descargar datos nuevos"
              >
                {refreshing ? "Descargando…" : "Actualizar"}
              </button>
            </div>
          </div>

          {loading && !plan ? (
            <div className="mt-5 h-[3.6rem] w-72 max-w-full animate-pulse rounded-xl bg-white/5" />
          ) : clock.next && parts ? (
            <>
              <div className="mt-4 flex flex-wrap items-end gap-2.5">
                {parts.days > 0 ? <span className="hoy-days">{parts.days}d</span> : null}
                <div className="flex items-baseline">
                  <span className={`hoy-digit ${parts.expired ? "hoy-digit--gold" : ""}`}>{two(parts.hours)}</span>
                  <span className="hoy-digit mx-[0.08em] opacity-25">:</span>
                  <span className={`hoy-digit ${parts.expired ? "hoy-digit--gold" : ""}`}>{two(parts.minutes)}</span>
                  <span className="hoy-digit mx-[0.08em] opacity-25">:</span>
                  <span
                    className={`hoy-digit ${parts.expired ? "hoy-digit--gold" : "opacity-70"}`}
                  >
                    {two(parts.seconds)}
                  </span>
                </div>
              </div>
              <p className="mt-4 text-[15px] font-semibold tracking-[-0.02em] text-white">
                {eventTitle(clock.next)}
              </p>
              <p className="mt-0.5 text-[11.5px] text-[color:var(--hoy-muted)]">{clockEventDetail(clock.next)}</p>
            </>
          ) : (
            <>
              <div className="mt-4 flex items-baseline">
                <span className="hoy-digit hoy-digit--muted opacity-45">--</span>
                <span className="hoy-digit mx-[0.08em] opacity-20">:</span>
                <span className="hoy-digit hoy-digit--muted opacity-45">--</span>
                <span className="hoy-digit mx-[0.08em] opacity-20">:</span>
                <span className="hoy-digit hoy-digit--muted opacity-45">--</span>
              </div>
              <p className="mt-4 text-[15px] font-semibold tracking-[-0.02em] text-white">
                {!mounted
                  ? "Sincronizando el reloj"
                  : clock.exhausted
                    ? "Sin hitos pendientes"
                    : "El plan no trae horas"}
              </p>
              <p className="mt-0.5 text-[11.5px] leading-4 text-[color:var(--hoy-muted)]">
                {!mounted
                  ? "La cuenta atrás arranca en cuanto el navegador toma la hora."
                  : clock.exhausted
                    ? "Todos los hitos conocidos ya pasaron. Recarga para leer el siguiente."
                    : "No se inventa una cuenta atrás sin hora de la API."}
              </p>
            </>
          )}

          {posture ? (
            <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-[color:var(--hoy-line)] pt-3">
              <span className="hoy-chip hoy-chip--gold">{posture.label}</span>
              <span className="min-w-0 truncate text-[11.5px] text-[color:var(--hoy-muted)]">{posture.headline}</span>
              {posture.gap ? (
                <span className="metric-value text-[11px] text-[color:var(--hoy-faint)]">· {posture.gap}</span>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* Línea roja: sólo lo que anula la jornada */}
        <div className="min-w-0 lg:border-l lg:border-[color:var(--hoy-line)] lg:pl-8">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="hoy-label">Lo que anula la jornada</p>
            <span
              className={`hoy-verdict ${
                verdict === "bloqueo" ? "hoy-verdict--blocker" : verdict === "aviso" ? "hoy-verdict--risk" : ""
              }`}
            >
              <span className="hoy-chip__dot" aria-hidden="true" />
              {verdictCopy}
            </span>
          </div>

          <div className="hoy-rail mt-3">
            {!plan && loading ? (
              Array.from({ length: 3 }, (_, index) => (
                <div key={index} className="hoy-rail__row">
                  <span className="hoy-rail__mark bg-white/5" aria-hidden="true" />
                  <div className="h-3 w-32 animate-pulse rounded bg-white/5" />
                  <div className="h-3 w-14 animate-pulse rounded bg-white/5" />
                </div>
              ))
            ) : rail.length ? (
              rail.map((check) => <RailRow key={check.id} check={check} />)
            ) : (
              <p className="py-3 text-[11.5px] leading-4 text-[color:var(--hoy-muted)]">
                El plan todavía no devolvió la línea roja. Sin ese dato no se firma la jornada.
              </p>
            )}
          </div>

          {!plan ? null : actionable ? (
            <div className="mt-2.5 flex items-start justify-between gap-3 rounded-lg border border-[color:var(--hoy-line)] bg-white/[0.02] px-2.5 py-2">
              <p className="min-w-0 text-[11px] leading-4 text-[color:var(--hoy-muted)]">
                <span className="font-semibold text-[color:var(--hoy-ink)]">Cómo se arregla </span>
                {FIX_COPY[actionable.id] || actionable.detail}
              </p>
              <Link
                href={FIX_HREF[actionable.id] || "/once"}
                className="hoy-btn shrink-0 px-2 py-1 text-[10.5px]"
              >
                {FIX_LABEL[actionable.id] || "Abrir"}
              </Link>
            </div>
          ) : null}

          {plan?.last_updated || plan?.fetched_at ? (
            <p className="mt-2 font-mono text-[10px] text-[color:var(--hoy-faint)] opacity-60">
              foto {stamp(plan.last_updated || plan.fetched_at)}
              {planAge !== null ? ` · ${durationAgo(planAge)}` : ""}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

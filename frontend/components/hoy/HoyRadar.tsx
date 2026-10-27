"use client";

import Link from "next/link";
import { useMemo } from "react";
import { buildClockReport, buildClockWaves, buildExposure } from "@/lib/hoy";
import { eurShort } from "@/lib/format";
import { useNow } from "@/lib/useClock";
import { HoyQuant } from "@/components/hoy/HoyQuant";
import type { PlanPayload } from "@/lib/types";

/** Clave de día y etiqueta en Europe/Madrid: el mismo huso que el backend. */
function madridDay(ms: number): { key: string; label: string } {
  const key = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(ms));
  const label = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short" })
    .format(new Date(ms))
    .replace(".", "")
    .slice(0, 3);
  return { key, label };
}

/** Carga por día: cuántos hitos caen en cada jornada de los próximos 7 días. */
function dayLoad(plan: PlanPayload | null, nowMs: number): { label: string; count: number }[] {
  // Sin reloj de cliente no se pinta nada: el render de servidor no conoce el día.
  if (nowMs <= 0) return [];
  const clock = buildClockReport(plan, nowMs);
  const buckets = new Map<string, { label: string; count: number }>();
  for (let offset = 0; offset < 7; offset += 1) {
    const { key, label } = madridDay(nowMs + offset * 86_400_000);
    buckets.set(key, { label, count: 0 });
  }
  for (const event of clock.upcoming) {
    if (event.ms === null) continue;
    const bucket = buckets.get(madridDay(event.ms).key);
    if (bucket) bucket.count += 1;
  }
  return Array.from(buckets.values());
}

function Timeline({ plan }: { plan: PlanPayload | null }) {
  const nowMs = useNow();
  const waves = useMemo(
    () => (nowMs > 0 ? buildClockWaves(buildClockReport(plan, nowMs)).slice(0, 3) : []),
    [plan, nowMs],
  );
  const load = useMemo(() => dayLoad(plan, nowMs), [plan, nowMs]);
  const max = Math.max(1, ...load.map((day) => day.count));
  const total = load.reduce((sum, day) => sum + day.count, 0);
  const peak = load.reduce((best, day) => (day.count > best.count ? day : best), load[0] ?? { label: "", count: 0 });

  return (
    <div className="hoy-panel flex min-w-0 flex-col p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="hoy-label">Radar</p>
        <Link href="/clausulazos" className="text-[10.5px] text-[color:var(--hoy-faint)] hover:text-[color:var(--hoy-ink)]">
          Calendario
        </Link>
      </div>

      {total ? (
        <p className="mt-2 text-[11px] leading-4 text-[color:var(--hoy-muted)]">
          <span className="metric-value font-semibold text-[color:var(--hoy-ink)]">{total}</span> hitos con hora en 7 días
          {peak && peak.count ? (
            <>
              {" "}
              · pico el <span className="text-[color:var(--hoy-ink)]">{peak.label}</span>
            </>
          ) : null}
        </p>
      ) : null}

      <div className="hoy-load mt-3" role="img" aria-label="Hitos por día en los próximos 7 días">
        {load.map((day, index) => (
          <div key={`${day.label}-${index}`} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1">
            <div
              className={`hoy-load__bar w-full ${day.count ? "" : "opacity-20"} ${
                index === 0 && day.count ? "hoy-load__bar--next" : ""
              }`}
              style={{ height: `${day.count ? Math.max(5, Math.round(Math.sqrt(day.count / max) * 26)) : 3}px` }}
              title={`${day.label}: ${day.count} hitos`}
            />
            <span className="text-[9px] uppercase tracking-[0.06em] text-[color:var(--hoy-faint)]">{day.label}</span>
          </div>
        ))}
      </div>

      <div className="mt-1">
        {waves.length ? (
          waves.map((wave) => (
            <div key={wave.key} className="hoy-wave">
              <span className="hoy-wave__count">{wave.count}</span>
              <div className="min-w-0">
                <p className="truncate text-[12px] font-medium leading-4 text-[color:var(--hoy-ink)]">{wave.title}</p>
                <p className="truncate text-[10.5px] text-[color:var(--hoy-faint)]">
                  {wave.names.slice(0, 2).join(" · ")}
                  {wave.names.length > 2 ? ` +${wave.names.length - 2}` : ""}
                </p>
              </div>
              <span className="metric-value shrink-0 text-[10.5px] text-[color:var(--hoy-muted)]">{wave.localLabel}</span>
            </div>
          ))
        ) : (
          <p className="py-3 text-[11px] leading-4 text-[color:var(--hoy-faint)]">
            Sin hitos con hora en la API. No se pinta un calendario inventado.
          </p>
        )}
      </div>
    </div>
  );
}

function Exposure({ plan }: { plan: PlanPayload | null }) {
  const exposure = useMemo(() => buildExposure(plan), [plan]);
  const safe = exposure.count === 0;

  return (
    <div className="hoy-panel flex min-w-0 flex-col p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="hoy-label">Riesgo de cláusula</p>
        <Link href="/clausulazos" className="text-[10.5px] text-[color:var(--hoy-faint)] hover:text-[color:var(--hoy-ink)]">
          Proteger
        </Link>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span
          className={`metric-value text-[2rem] leading-none tracking-[-0.05em] ${
            safe ? "text-[color:var(--hoy-mint)]" : "text-[color:var(--hoy-gold)]"
          }`}
        >
          {exposure.count}
        </span>
        <span className="text-[11.5px] leading-4 text-[color:var(--hoy-muted)]">
          {exposure.count === 1 ? "cláusula al alcance rival" : "cláusulas al alcance rival"}
        </span>
      </div>

      {safe ? (
        <p className="mt-2 text-[11px] leading-4 text-[color:var(--hoy-muted)]">
          Ningún rival con caja llega a una cláusula tuya. No hay que blindar nada hoy.
        </p>
      ) : (
        <>
          {exposure.cheapest ? (
            <div className="mt-3 rounded-lg border border-[color:var(--hoy-line)] bg-black/25 px-2.5 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[color:var(--hoy-faint)]">
                La más barata
              </p>
              <p className="mt-1 flex items-baseline justify-between gap-2">
                <span className="truncate text-[12.5px] font-medium text-[color:var(--hoy-ink)]">
                  {exposure.cheapest.name}
                </span>
                <span className="metric-value shrink-0 text-[12px] text-[color:var(--hoy-gold)]">
                  {eurShort(exposure.cheapest.clause)}
                </span>
              </p>
            </div>
          ) : null}
          <p className="mt-2 text-[11px] leading-4 text-[color:var(--hoy-muted)]">
            Hasta <span className="font-semibold text-[color:var(--hoy-ink)]">{exposure.threats}</span> rivales con caja
            podrían pagarla. Subir la cláusula exige caja propia.
          </p>
        </>
      )}
    </div>
  );
}

function Market({ plan }: { plan: PlanPayload | null }) {
  const summary = plan?.market_summary;
  const pujar = summary?.pujar || 0;
  const esperar = summary?.esperar || 0;
  const no = summary?.no || 0;
  const total = pujar + esperar + no;

  return (
    <div className="hoy-panel flex min-w-0 flex-col p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="hoy-label">Mercado</p>
        <Link href="/mercado" className="text-[10.5px] text-[color:var(--hoy-faint)] hover:text-[color:var(--hoy-ink)]">
          Ver listings
        </Link>
      </div>

      {total ? (
        <>
          <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-white/8" role="img" aria-label="Reparto de veredictos">
            {pujar ? <span className="h-full bg-[color:var(--hoy-mint)]" style={{ width: `${(pujar / total) * 100}%` }} /> : null}
            {esperar ? (
              <span className="h-full bg-[color:var(--hoy-gold)]" style={{ width: `${(esperar / total) * 100}%` }} />
            ) : null}
            {no ? <span className="h-full bg-white/20" style={{ width: `${(no / total) * 100}%` }} /> : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px]">
            {pujar ? (
              <span className="text-[color:var(--hoy-mint)]">
                <span className="metric-value">{pujar}</span> pujar
              </span>
            ) : null}
            {esperar ? (
              <span className="text-[color:var(--hoy-gold)]">
                <span className="metric-value">{esperar}</span> esperar
              </span>
            ) : null}
            {no ? (
              <span className="text-[color:var(--hoy-faint)]">
                <span className="metric-value">{no}</span> descartar
              </span>
            ) : null}
          </div>
        </>
      ) : (
        <p className="mt-3 text-[11px] leading-4 text-[color:var(--hoy-muted)]">
          La API no devolvió veredictos de mercado para hoy.
        </p>
      )}

      <dl className="mt-auto grid grid-cols-2 gap-x-3 gap-y-2 pt-3">
        <div>
          <dt className="text-[9.5px] font-semibold uppercase tracking-[0.1em] text-[color:var(--hoy-faint)]">
            Presupuesto día
          </dt>
          <dd className="metric-value mt-0.5 truncate text-[12px] text-[color:var(--hoy-ink)]">
            {eurShort(summary?.day_budget_eur)}
          </dd>
        </div>
        <div>
          <dt className="text-[9.5px] font-semibold uppercase tracking-[0.1em] text-[color:var(--hoy-faint)]">
            Plan de gasto
          </dt>
          <dd className="metric-value mt-0.5 truncate text-[12px] text-[color:var(--hoy-muted)]">
            {eurShort(summary?.plan_spend_eur)}
          </dd>
        </div>
        {typeof summary?.markets_left === "number" ? (
          <div className="col-span-2">
            <dt className="text-[9.5px] font-semibold uppercase tracking-[0.1em] text-[color:var(--hoy-faint)]">
              Hasta el saque
            </dt>
            <dd className="mt-0.5 text-[11px] text-[color:var(--hoy-muted)]">
              {summary.markets_left} mercado(s) por delante antes de cerrar plantilla.
            </dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

export function HoyRadar({ plan }: { plan: PlanPayload | null }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <Timeline plan={plan} />
      <Exposure plan={plan} />
      <Market plan={plan} />
      <HoyQuant />
    </div>
  );
}

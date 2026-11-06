"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { endpoint } from "@/lib/core/api";
import { useCachedJson } from "@/lib/core/useCachedJson";
import { buildDataHealthReport } from "@/lib/laboratorio/dataHealth";
import type { ApiUsagePayload } from "@/lib/types";
import { HeroStat, TONE } from "@/components/ui/kit";
import { CopyNetworkReportButton } from "./ApiUsagePanel";

type View = "resumen" | "fuentes" | "peticiones";

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "resumen", label: "Resumen", hint: "Si los datos de la foto están completos y qué puede fallar por ello." },
  { id: "fuentes", label: "Fuentes", hint: "Cada web o API de la que se descargan datos y si respondió en la última actualización." },
  { id: "peticiones", label: "Peticiones", hint: "Cuántas llamadas hace la app a cada fuente. Demasiadas seguidas pueden hacer que te bloqueen." },
];

export function DatosSimple() {
  const search = useSearchParams();
  const league = search.get("league");
  const { state, stale, photoAge, refreshing } = useDashboard();
  const report = useMemo(() => buildDataHealthReport(state), [state]);
  const usage = useCachedJson<ApiUsagePayload>(endpoint("/api/api-usage", league));
  const [view, setView] = useState<View>("resumen");
  const current = VIEWS.find((v) => v.id === view)!;

  const level = report?.level ?? "bad";
  const color = level === "ok" ? TONE.green : level === "warn" ? TONE.amber : TONE.red;
  const failedCount = report?.sources.filter((src) => !src.ok).length ?? 0;
  const verdict =
    level === "ok" ? (failedCount ? "Lo importante está completo" : "Datos completos") : level === "warn" ? "Faltan algunos datos" : "Datos incompletos";
  const failed = report?.sources.filter((s) => !s.ok) ?? [];
  const perMinute = usage?.rate?.per_minute ?? 0;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <section className="home-glass flex flex-wrap items-center gap-5 p-5">
        <span className="relative grid h-[5.5rem] w-[5.5rem] shrink-0 place-items-center">
          <svg viewBox="0 0 36 36" className="absolute inset-0 h-full w-full -rotate-90" aria-hidden="true">
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
            <circle cx="18" cy="18" r="15.5" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${((report?.score ?? 0) / 100) * 97.4} 97.4`} />
          </svg>
          <span className="text-[1.5rem] font-semibold tabular-nums text-white">{report ? `${report.score}%` : "—"}</span>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-white/60">{photoAge ? `Foto de ${photoAge}` : "Sin foto"}{stale ? " · antigua" : ""}</p>
          <p className="mt-1 text-[1.35rem] font-semibold leading-tight tracking-tight" style={{ color }}>
            {report ? verdict : "Sin foto cargada"}
          </p>
          <p className="mt-1 text-[13.5px] leading-snug text-white/60">
            {report
              ? failed.length
                ? `${failed.length} fuente${failed.length === 1 ? "" : "s"} no respondi${failed.length === 1 ? "ó" : "eron"} en la última actualización.`
                : "Todas las fuentes respondieron en la última actualización."
              : "Actualiza desde Inicio para cargar los datos."}
          </p>
        </div>
      </section>

      <div className="eq-scroll -mx-1 flex gap-1.5 px-1" role="tablist" aria-label="Vistas de datos">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} className={view === v.id ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setView(v.id)}>
            {v.label}
          </button>
        ))}
      </div>
      <p className="-mt-1 px-1 text-[13px] text-white/50">{current.hint}</p>

      <div key={view} className="row-in min-w-0">
        {view === "resumen" ? (
          <div className="flex flex-col gap-2.5">
            {report?.compromised.length ? (
              <ul className="home-glass flex flex-col gap-2 p-5">
                <p className="text-[13px] font-medium text-white/60">Qué puede estar afectado</p>
                {report.compromised.map((line) => (
                  <li key={line} className="!bg-transparent flex gap-2.5 text-[13.5px] leading-snug text-white/80">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TONE.red }} aria-hidden="true" />
                    {line}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="home-glass px-5 py-5 text-[13.5px] text-white/70">
                <span style={{ color: TONE.green }}>●</span> Nada importante afectado: el plan, el mercado y el once tienen los datos que necesitan.
              </p>
            )}
            {report ? (
              <ul className="grid gap-2.5 sm:grid-cols-2">
                {report.blocks.map((block) => (
                  <li key={block.id} className="home-glass flex items-start gap-3 p-4">
                    <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: block.ok ? TONE.green : TONE.amber }} aria-hidden="true" />
                    <span className="min-w-0">
                      <span className="block text-[14.5px] font-medium text-white">{block.label}</span>
                      <span className="block text-[12.5px] leading-snug text-white/50">{block.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : view === "fuentes" ? (
          report?.sources.length ? (
            <ul className="home-glass overflow-hidden">
              {report.sources
                .slice()
                .sort((a, b) => Number(a.ok) - Number(b.ok))
                .map((src) => (
                  <li key={src.id} className="flex items-center gap-3 px-4 py-3">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: src.ok ? TONE.green : TONE.red }} aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14.5px] font-medium text-white">{src.label}</span>
                      <span className="block truncate text-[12px] text-white/45" title={src.error ?? undefined}>
                        {src.ok ? `${src.group}${typeof src.count === "number" ? ` · ${src.count} datos` : ""}` : src.impacts.length ? `Afecta a: ${src.impacts.slice(0, 2).join("; ")}` : src.error || "Error"}
                      </span>
                    </span>
                    <span className="shrink-0 text-[12.5px] font-medium" style={{ color: src.ok ? TONE.green : TONE.red }}>
                      {src.ok ? "Bien" : "Falló"}
                    </span>
                  </li>
                ))}
            </ul>
          ) : (
            <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">La foto rápida no trae fuentes externas. Aparecen tras una actualización completa.</p>
          )
        ) : usage === null ? (
          <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">Leyendo contadores…</p>
        ) : usage.ok === false ? (
          <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">{usage.error?.message || "El contador no respondió."}</p>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-3 gap-2.5">
              <HeroStat value={refreshing ? `${perMinute.toFixed(0)}/min` : "En reposo"} label="ahora mismo" tone={perMinute > 60 ? TONE.amber : TONE.green} />
              <HeroStat value={String(usage.rate?.calls_10m ?? 0)} label="últimos 10 min" />
              <HeroStat value={String(usage.totals?.calls ?? 0)} label="desde el arranque" />
            </div>
            {usage.risk?.headline ? (
              <p className="home-glass px-5 py-4 text-[13.5px] leading-snug text-white/70">
                {usage.risk.headline}
                {usage.risk.advice ? <span className="mt-1 block text-[12.5px] text-white/45">{usage.risk.advice}</span> : null}
              </p>
            ) : null}
            {(usage.sources ?? []).length ? (
              <ul className="home-glass flex flex-col gap-3 p-5">
                {(() => {
                  const top = Math.max(1, ...(usage.sources ?? []).map((s) => s.calls));
                  return (usage.sources ?? []).map((s) => (
                    <li key={s.id} className="!bg-transparent">
                      <div className="flex items-baseline justify-between text-[13px]">
                        <span className="text-white/75">{s.label}</span>
                        <span className="tabular-nums text-white">
                          {s.calls}
                          {s.errors ? <span className="ml-2 text-[#FC734D]">{s.errors} fallos</span> : null}
                        </span>
                      </div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                        <span className="block h-full rounded-full" style={{ width: `${(s.calls / top) * 100}%`, background: TONE.copper }} />
                      </div>
                    </li>
                  ));
                })()}
              </ul>
            ) : (
              <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">Aún no ha salido ninguna petición desde que arrancó el servidor.</p>
            )}
            <div className="lab-panel flex justify-end">
              <CopyNetworkReportButton />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

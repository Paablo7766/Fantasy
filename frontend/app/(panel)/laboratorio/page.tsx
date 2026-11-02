"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { AfIntel } from "@/components/AfIntel";
import { ApiUsagePanel } from "@/components/ApiUsagePanel";
import { CalibrationDashboard } from "@/components/CalibrationDashboard";
import { DataHealthPanel } from "@/components/DataHealthPanel";
import { useDashboard } from "@/components/DashboardProvider";
import { ExpertNotePanel } from "@/components/ExpertNotePanel";
import { SignalDiscrepanciesPanel } from "@/components/SignalDiscrepanciesPanel";
import { Skeleton } from "@/components/equipo/ui";
import { RadarTecnico } from "@/components/laboratorio/RadarTecnico";
import { buildPhotoIndex } from "@/lib/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Tab = "radar" | "calibracion" | "senales" | "datos";

/**
 * Zona de auditoría: cómo se construye cada número. Nada de aquí decide una
 * compra; sirve para fiarse (o no) del modelo y de la foto.
 */
const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "radar", label: "Radar técnico", hint: "Pesos de la nota, tóxicos descartados y precio de referencia por posición." },
  { id: "calibracion", label: "Calibración", hint: "Cuánto acierta el modelo frente a lo que ocurrió." },
  { id: "senales", label: "Señales", hint: "Fuentes externas, discrepancias entre ellas y la nota del experto." },
  { id: "datos", label: "Datos y API", hint: "Frescura de cada bloque y consumo de peticiones." },
];

function asTab(value: string | null): Tab {
  return TABS.some((item) => item.id === value) ? (value as Tab) : "radar";
}

function LaboratorioContent() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = asTab(search.get("tab"));
  const { state, pending, busy } = useDashboard();
  const trends = state.trends as TrendsPayload | null;
  const photos = useMemo(
    () =>
      buildPhotoIndex(state.plan as PlanPayload | null, state.optimize as OptimizePayload | null, state.squads as SquadsPayload | null, trends),
    [state.plan, state.optimize, state.squads, trends],
  );
  const trendsLoading = pending.trends || (!state.trends && busy);
  const current = TABS.find((item) => item.id === tab)!;

  const select = (next: Tab) => {
    const params = new URLSearchParams(search.toString());
    if (next === "radar") params.delete("tab");
    else params.set("tab", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <div className="eq-stack reveal min-w-0">
      <div className="flex flex-col gap-3 px-1">
        <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-white">Laboratorio</h1>
        <div className="desk-switch" role="tablist" aria-label="Herramientas del laboratorio">
          {TABS.map((item) => (
            <button
              key={item.id}
              id={`lab-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              aria-controls={`lab-panel-${item.id}`}
              className={tab === item.id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => select(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className="text-[12.5px] text-white/50">{current.hint}</p>
      </div>

      <div key={tab} id={`lab-panel-${tab}`} role="tabpanel" aria-labelledby={`lab-tab-${tab}`} className="row-in min-w-0">
        {tab === "radar" ? (
          <RadarTecnico photos={photos} />
        ) : tab === "calibracion" ? (
          <CalibrationDashboard />
        ) : tab === "senales" ? (
          <div className="flex min-w-0 flex-col gap-6">
            <SignalDiscrepanciesPanel trends={trends} loading={trendsLoading} />
            <section className="min-w-0">
              <AfIntel trends={trends} loading={pending.trends && !state.trends} />
            </section>
            <ExpertNotePanel />
          </div>
        ) : (
          <div className="flex flex-col items-start gap-3">
            <DataHealthPanel />
            <ApiUsagePanel />
          </div>
        )}
      </div>
    </div>
  );
}

export default function LaboratorioPage() {
  return (
    <Suspense
      fallback={
        <div className="eq-stack">
          <Skeleton />
        </div>
      }
    >
      <LaboratorioContent />
    </Suspense>
  );
}

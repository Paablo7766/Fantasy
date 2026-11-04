"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { AfIntel } from "@/components/laboratorio/AfIntel";
import { ApiUsagePanel } from "@/components/laboratorio/ApiUsagePanel";
import { CalibrationDashboard } from "@/components/laboratorio/CalibrationDashboard";
import { PostMortemPanel } from "@/components/laboratorio/PostMortemPanel";
import { DataHealthPanel } from "@/components/laboratorio/DataHealthPanel";
import { useDashboard } from "@/components/DashboardProvider";
import { ExpertNotePanel } from "@/components/laboratorio/ExpertNotePanel";
import { SignalDiscrepanciesPanel } from "@/components/laboratorio/SignalDiscrepanciesPanel";
import { Skeleton } from "@/components/ui/kit";
import { RadarTecnico } from "@/components/laboratorio/RadarTecnico";
import { ClauseBoardPanel } from "@/components/liga/ClauseBoardPanel";
import { RivalIntelPanel } from "@/components/liga/RivalIntelPanel";
import { LabSection } from "@/components/mercado/LabSection";
import { OportunidadesTab } from "@/components/mercado/OportunidadesTab";
import { buildPhotoIndex } from "@/lib/core/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Tab = "radar" | "rivales" | "calibracion" | "senales" | "datos";

/**
 * Zona de auditoría: cómo se construye cada número. Nada de aquí decide una
 * compra; sirve para fiarse (o no) del modelo y de la foto.
 */
const TABS: { id: Tab; label: string; hint: string }[] = [
  {
    id: "radar",
    label: "Radar técnico",
    hint: "Fichables fuera del mercado por valor y momentum, pesos de la nota, tóxicos descartados y precio de referencia por posición.",
  },
  { id: "rivales", label: "Rivales", hint: "Cómo se reconstruye la caja de cada rival y el tablero con todas las cláusulas de la liga." },
  { id: "calibracion", label: "Calibración", hint: "Cuánto acierta el modelo, y el post-mortem del lunes: puntos que habrías sumado alineando a otro de la plantilla, e impacto de haber operado." },
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
          <div className="flex min-w-0 flex-col gap-6">
            <OportunidadesTab photos={photos} />
            <LabSection photos={photos} />
            <RadarTecnico photos={photos} />
          </div>
        ) : tab === "rivales" ? (
          <div className="flex min-w-0 flex-col gap-6">
            <RivalIntelPanel />
            <ClauseBoardPanel />
          </div>
        ) : tab === "calibracion" ? (
          <div className="flex min-w-0 flex-col gap-6">
            <PostMortemPanel />
            <CalibrationDashboard />
          </div>
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

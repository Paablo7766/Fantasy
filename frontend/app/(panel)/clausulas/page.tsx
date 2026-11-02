"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { ClausulasTab, type ClausulasView } from "@/components/clausulas/ClausulasTab";
import { ComparadorLauncher } from "@/components/comparador/ComparadorReal";
import { useDashboard } from "@/components/DashboardProvider";
import { Skeleton } from "@/components/ui/kit";
import { buildPhotoIndex } from "@/lib/core/photoIndex";
import type { NeedsPayload, OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

const TABS: { id: ClausulasView; label: string }[] = [
  { id: "mias", label: "Mías" },
  { id: "clausulazos", label: "Clausulazos" },
];

function asTab(value: string | null): ClausulasView {
  return value === "clausulazos" ? value : "mias";
}

function ClausulasContent() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = asTab(search.get("tab"));
  const { state, pending, busy } = useDashboard();
  const plan = state.plan as PlanPayload | null;
  const optimize = state.optimize as OptimizePayload | null;
  const squads = state.squads as SquadsPayload | null;
  const trends = state.trends as TrendsPayload | null;
  const needs = state.needs as NeedsPayload | null;
  const photos = useMemo(() => buildPhotoIndex(plan, optimize, squads, trends), [plan, optimize, squads, trends]);

  const select = (next: ClausulasView) => {
    const params = new URLSearchParams(search.toString());
    if (next === "mias") params.delete("tab");
    else params.set("tab", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <div className="eq-stack reveal min-w-0">
      <div className="flex flex-col gap-3 px-1">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-white">Cláusulas</h1>
          <ComparadorLauncher />
        </div>
        <div className="desk-switch" role="tablist" aria-label="Secciones de cláusulas">
          {TABS.map((item) => (
            <button
              key={item.id}
              id={`cl-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              aria-controls={`cl-panel-${item.id}`}
              className={tab === item.id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => select(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div key={tab} id={`cl-panel-${tab}`} role="tabpanel" aria-labelledby={`cl-tab-${tab}`} className="row-in min-w-0">
        <ClausulasTab
          plan={plan}
          squads={squads}
          needs={needs}
          photos={photos}
          loading={(pending.plan || busy) && !plan}
          view={tab}
        />
      </div>
    </div>
  );
}

export default function ClausulasPage() {
  return (
    <Suspense
      fallback={
        <div className="eq-stack">
          <Skeleton />
        </div>
      }
    >
      <ClausulasContent />
    </Suspense>
  );
}

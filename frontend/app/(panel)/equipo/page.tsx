"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { CarteraTab } from "@/components/equipo/CarteraTab";
import { ClausulasTab } from "@/components/equipo/ClausulasTab";
import { OnceTab } from "@/components/equipo/OnceTab";
import { Skeleton } from "@/components/equipo/ui";
import { buildPhotoIndex } from "@/lib/photoIndex";
import type { NeedsPayload, OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Tab = "once" | "cartera" | "clausulas";

const TABS: { id: Tab; label: string }[] = [
  { id: "once", label: "Once" },
  { id: "cartera", label: "Cartera" },
  { id: "clausulas", label: "Cláusulas" },
];

function asTab(value: string | null): Tab {
  return value === "cartera" || value === "clausulas" ? value : "once";
}

function EquipoContent() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  // La pestaña vive en la URL: ``/equipo?tab=cartera`` desde Inicio o el dock abre la correcta.
  const tab = asTab(search.get("tab"));
  const { state, pending, busy } = useDashboard();
  const plan = state.plan as PlanPayload | null;
  const optimize = state.optimize as OptimizePayload | null;
  const squads = state.squads as SquadsPayload | null;
  const trends = state.trends as TrendsPayload | null;
  const needs = state.needs as NeedsPayload | null;
  const photos = useMemo(() => buildPhotoIndex(plan, optimize, squads, trends), [plan, optimize, squads, trends]);

  const select = (next: Tab) => {
    const params = new URLSearchParams(search.toString());
    if (next === "once") params.delete("tab");
    else params.set("tab", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <div className="eq-stack reveal min-w-0">
      <div className="flex flex-col gap-3 px-1">
        <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-white">Mi equipo</h1>
        <div className="desk-switch" role="tablist" aria-label="Secciones de tu equipo">
          {TABS.map((item) => (
            <button
              key={item.id}
              id={`eq-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              aria-controls={`eq-panel-${item.id}`}
              className={tab === item.id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => select(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div key={tab} id={`eq-panel-${tab}`} role="tabpanel" aria-labelledby={`eq-tab-${tab}`} className="row-in min-w-0">
        {tab === "once" ? (
          <OnceTab plan={plan} optimize={optimize} squads={squads} photos={photos} loading={(pending.optimize || busy) && !optimize} />
        ) : tab === "cartera" ? (
          <CarteraTab plan={plan} squads={squads} photos={photos} loading={(pending.squads || busy) && !squads} />
        ) : (
          <ClausulasTab
            plan={plan}
            squads={squads}
            needs={needs}
            photos={photos}
            loading={(pending.plan || busy) && !plan}
          />
        )}
      </div>
    </div>
  );
}

export default function EquipoPage() {
  return (
    <Suspense
      fallback={
        <div className="eq-stack">
          <Skeleton />
        </div>
      }
    >
      <EquipoContent />
    </Suspense>
  );
}

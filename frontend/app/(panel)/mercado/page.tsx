"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { Skeleton } from "@/components/equipo/ui";
import { RadarTab } from "@/components/mercado/RadarTab";
import { FichajesTab } from "@/components/mercado/FichajesTab";
import { UniversoTab } from "@/components/mercado/UniversoTab";
import { ComparadorLauncher } from "@/components/comparador/ComparadorReal";
import { buildPhotoIndex } from "@/lib/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Tab = "fichajes" | "radar" | "universo";

/**
 * Fichajes mira la puja de la liga; el radar, el valor intrínseco y el dinero
 * global; el universo, todo lo que no está anunciado. Se separan para que
 * ninguna fuente de decisión tape a la otra.
 */
const TABS: { id: Tab; label: string }[] = [
  { id: "fichajes", label: "Hoy" },
  { id: "radar", label: "Radar" },
  { id: "universo", label: "Todos" },
];

function asTab(value: string | null): Tab {
  return value === "radar" || value === "universo" ? value : "fichajes";
}

function MercadoContent() {
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
  const loading = pending.trends || (!state.trends && busy);

  const select = (next: Tab) => {
    const params = new URLSearchParams(search.toString());
    if (next === "fichajes") params.delete("tab");
    else params.set("tab", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <div className="eq-stack reveal min-w-0">
      <div className="flex flex-col gap-3 px-1">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-white">Mercado</h1>
          <ComparadorLauncher />
        </div>
        <div className="desk-switch" role="tablist" aria-label="Secciones del mercado">
          {TABS.map((item) => (
            <button
              key={item.id}
              id={`mk-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              aria-controls={`mk-panel-${item.id}`}
              className={tab === item.id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => select(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div key={tab} id={`mk-panel-${tab}`} role="tabpanel" aria-labelledby={`mk-tab-${tab}`} className="row-in min-w-0">
        {tab === "fichajes" ? (
          <FichajesTab trends={trends} photos={photos} loading={loading} />
        ) : tab === "radar" ? (
          <RadarTab photos={photos} />
        ) : (
          <UniversoTab trends={trends} photos={photos} loading={loading} />
        )}
      </div>
    </div>
  );
}

export default function MercadoPage() {
  return (
    <Suspense
      fallback={
        <div className="eq-stack">
          <Skeleton />
        </div>
      }
    >
      <MercadoContent />
    </Suspense>
  );
}

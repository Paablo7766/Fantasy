"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { Skeleton } from "@/components/equipo/ui";
import { BuscadorTab } from "@/components/mercado/BuscadorTab";
import { HoyTab } from "@/components/mercado/HoyTab";
import { LabSection } from "@/components/mercado/LabSection";
import { OportunidadesTab } from "@/components/mercado/OportunidadesTab";
import { ComparadorLauncher } from "@/components/comparador/ComparadorReal";
import { buildPhotoIndex } from "@/lib/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Tab = "hoy" | "oportunidades" | "buscador";

/**
 * Hoy mira la puja de tu liga y es la única que dice qué comprar. Oportunidades
 * reúne las señales que la apoyan (radar, dinero global, perfiles fuera del
 * mercado) y Buscador es la consulta libre del catálogo.
 */
const TABS: { id: Tab; label: string }[] = [
  { id: "hoy", label: "Hoy" },
  { id: "oportunidades", label: "Oportunidades" },
  { id: "buscador", label: "Buscador" },
];

/** Acepta también los ids antiguos (``radar``, ``universo``) de enlaces ya guardados. */
function asTab(value: string | null): Tab {
  if (value === "oportunidades" || value === "radar") return "oportunidades";
  if (value === "buscador" || value === "universo") return "buscador";
  return "hoy";
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
    if (next === "hoy") params.delete("tab");
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
        {tab === "hoy" ? (
          <HoyTab trends={trends} photos={photos} loading={loading} />
        ) : tab === "oportunidades" ? (
          <div className="flex min-w-0 flex-col gap-5">
            <OportunidadesTab photos={photos} />
            <LabSection photos={photos} />
          </div>
        ) : (
          <BuscadorTab trends={trends} photos={photos} loading={loading} />
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

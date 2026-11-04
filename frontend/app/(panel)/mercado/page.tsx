"use client";

import { Suspense, useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { Skeleton } from "@/components/ui/kit";
import { HoyTab } from "@/components/mercado/HoyTab";
import { ComparadorLauncher } from "@/components/comparador/ComparadorReal";
import { buildPhotoIndex } from "@/lib/core/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

/**
 * Mercado es una sola pantalla: lo que está en venta hoy y qué hacer con ello.
 * El buscador vive en la propia búsqueda (también encuentra a los que no están
 * en venta) y el radar de oportunidades pasó al Laboratorio, porque no decide
 * ninguna compra de hoy.
 */
function MercadoContent() {
  const { state, pending, busy } = useDashboard();
  const trends = state.trends as TrendsPayload | null;
  const photos = useMemo(
    () =>
      buildPhotoIndex(state.plan as PlanPayload | null, state.optimize as OptimizePayload | null, state.squads as SquadsPayload | null, trends),
    [state.plan, state.optimize, state.squads, trends],
  );
  const loading = pending.trends || (!state.trends && busy);

  return (
    <div className="eq-stack reveal min-w-0">
      <div className="flex items-center justify-between gap-3 px-1">
        <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-white">Mercado</h1>
        <ComparadorLauncher />
      </div>
      <div className="row-in min-w-0">
        <HoyTab trends={trends} photos={photos} loading={loading} />
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

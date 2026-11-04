"use client";

import { Suspense, useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { LigaView } from "@/components/liga/LigaView";
import { Skeleton } from "@/components/ui/kit";
import { buildPhotoIndex } from "@/lib/core/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

/**
 * Liga es la clasificación y tu carrera: dónde estás, a cuánto del de arriba y
 * cómo es cada rival. La caja forense y el tablero de todas las cláusulas son
 * auditoría y viven en Laboratorio → Rivales.
 */
function LigaContent() {
  const { state, pending, busy } = useDashboard();
  const squads = state.squads as SquadsPayload | null;
  const trends = state.trends as TrendsPayload | null;
  const photos = useMemo(
    () => buildPhotoIndex(state.plan as PlanPayload | null, state.optimize as OptimizePayload | null, squads, trends),
    [state.plan, state.optimize, squads, trends],
  );
  return (
    <div className="eq-stack reveal min-w-0">
      <h1 className="px-1 text-[1.6rem] font-semibold leading-tight tracking-tight text-white">Liga</h1>
      <div className="row-in min-w-0">
        <LigaView squads={squads} trends={trends} photos={photos} loading={(pending.squads || busy) && !squads} />
      </div>
    </div>
  );
}

export default function LigaPage() {
  return (
    <Suspense
      fallback={
        <div className="eq-stack">
          <Skeleton />
        </div>
      }
    >
      <LigaContent />
    </Suspense>
  );
}

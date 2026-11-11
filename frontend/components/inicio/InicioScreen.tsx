"use client";

import { useMemo, type PointerEvent } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { HomeHeader } from "@/components/inicio/HomeHeader";
import { GuardarrailRuina } from "@/components/mercado/GuardarrailRuina";
import { LiveJornada } from "@/components/inicio/LiveJornada";
import { SquadDesk } from "@/components/inicio/SquadDesk";
import { TodayPlan } from "@/components/inicio/TodayPlan";
import { buildPhotoIndex, buildPlayerIndex } from "@/lib/core/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

/**
 * Foco de luz que sigue al puntero dentro de cada tarjeta. Se escribe en
 * variables CSS (sin estado de React) para no re-renderizar en cada movimiento.
 */
function trackSpotlight(event: PointerEvent<HTMLDivElement>) {
  if (event.pointerType !== "mouse") return;
  const card = (event.target as HTMLElement).closest<HTMLElement>(".ini-card");
  if (!card) return;
  const box = card.getBoundingClientRect();
  card.style.setProperty("--mx", `${event.clientX - box.left}px`);
  card.style.setProperty("--my", `${event.clientY - box.top}px`);
}

export function InicioScreen() {
  const { state, pending, busy } = useDashboard();
  const plan = state.plan as PlanPayload | null;
  const squads = state.squads as SquadsPayload | null;
  const optimize = state.optimize as OptimizePayload | null;
  const trends = state.trends as TrendsPayload | null;
  const loading = (pending.plan || busy) && !plan;
  const photos = useMemo(() => buildPhotoIndex(plan, optimize, squads, trends), [plan, optimize, squads, trends]);
  const facts = useMemo(() => buildPlayerIndex(plan, optimize, squads, trends), [plan, optimize, squads, trends]);
  return (
    <div className="hoy-root home-stack ini" onPointerMove={trackSpotlight} data-ui="inicio">
      <div className="ini-area-hero">
        <HomeHeader plan={plan} squads={squads} loading={loading} />
      </div>
      <div className="ini-area-plan min-w-0">
        <GuardarrailRuina data={plan?.guardarrail_ruina} modo="inicio" />
        <LiveJornada plan={plan} />
        <TodayPlan plan={plan} squads={squads} loading={loading} photos={photos} facts={facts} />
      </div>
      <aside className="ini-area-squad min-w-0" aria-label="Plantilla">
        <SquadDesk plan={plan} photos={photos} loading={loading} />
      </aside>
    </div>
  );
}

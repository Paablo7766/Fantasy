"use client";

import { useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { HomeHeader } from "@/components/inicio/HomeHeader";
import { SquadDesk } from "@/components/inicio/SquadDesk";
import { TodayPlan } from "@/components/inicio/TodayPlan";
import { buildPhotoIndex, buildPlayerIndex } from "@/lib/core/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

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
    <div className="hoy-root home-stack ini">
      <HomeHeader plan={plan} squads={squads} loading={loading} />
      <TodayPlan plan={plan} squads={squads} loading={loading} photos={photos} facts={facts} />
      <SquadDesk plan={plan} photos={photos} loading={loading} />
    </div>
  );
}

"use client";

import { useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { AccountSummary } from "@/components/inicio/AccountSummary";
import { HojaDeRuta } from "@/components/inicio/HojaDeRuta";
import { HomeLineup } from "@/components/inicio/HomeLineup";
import { SigningBoard } from "@/components/inicio/SigningBoard";
import { StrategyImpact } from "@/components/inicio/StrategyImpact";
import { buildPhotoIndex, buildPlayerIndex } from "@/lib/core/photoIndex";
import type { NeedsPayload, OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

export function InicioScreen() {
  const { state, pending, busy, refreshing, photoLine } = useDashboard();
  const plan = state.plan as PlanPayload | null;
  const squads = state.squads as SquadsPayload | null;
  const optimize = state.optimize as OptimizePayload | null;
  const trends = state.trends as TrendsPayload | null;
  const needs = state.needs as NeedsPayload | null;
  const loading = (pending.plan || busy) && !plan;
  const photos = useMemo(() => buildPhotoIndex(plan, optimize, squads, trends), [plan, optimize, squads, trends]);
  const facts = useMemo(() => buildPlayerIndex(plan, optimize, squads, trends), [plan, optimize, squads, trends]);

  return (
    <div className="hoy-root rec-home home-stack">
      <AccountSummary plan={plan} squads={squads} loading={loading} />
      <StrategyImpact plan={plan} optimize={optimize} loading={loading} />
      <HojaDeRuta fichajes={plan?.plan_fichajes} loading={loading} />
      <SigningBoard
        plan={plan}
        optimize={optimize}
        squads={squads}
        trends={trends}
        needs={needs}
        loading={loading}
        refreshing={refreshing}
        photos={photos}
        facts={facts}
        photoLine={photoLine}
      />
      <HomeLineup plan={plan} optimize={optimize} photos={photos} />
    </div>
  );
}

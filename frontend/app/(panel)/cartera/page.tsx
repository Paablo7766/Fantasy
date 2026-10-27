"use client";

import { useDashboard } from "@/components/DashboardProvider";
import { PortfolioDashboard } from "@/components/PortfolioDashboard";
import type { SquadsPayload } from "@/lib/types";

export default function CarteraPage() {
  const { state, pending } = useDashboard();
  return (
    <section className="reveal min-w-0">
      <PortfolioDashboard
        squads={state.squads as SquadsPayload | null}
        loading={pending.squads && !state.squads}
      />
    </section>
  );
}

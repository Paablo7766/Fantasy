"use client";

import { useDashboard } from "@/components/DashboardProvider";
import { Pitch } from "@/components/Pitch";
import type { OptimizePayload, SquadsPayload } from "@/lib/types";

export default function OncePage() {
  const { state, pending } = useDashboard();

  return (
    <section className="reveal min-w-0">
      <Pitch
        optimize={state.optimize as OptimizePayload | null}
        squads={state.squads as SquadsPayload | null}
        loading={pending.optimize && !state.optimize}
      />
    </section>
  );
}

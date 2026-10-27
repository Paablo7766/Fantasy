"use client";

import { AfIntel } from "@/components/AfIntel";
import { ExpertNotePanel } from "@/components/ExpertNotePanel";
import { useDashboard } from "@/components/DashboardProvider";
import { SignalDiscrepanciesPanel } from "@/components/SignalDiscrepanciesPanel";
import type { TrendsPayload } from "@/lib/types";

export default function IntelPage() {
  const { state, pending, busy } = useDashboard();
  const trends = state.trends as TrendsPayload | null;
  const trendsLoading = pending.trends || (!state.trends && busy);

  return (
    <div className="reveal flex min-w-0 flex-col gap-6">
      <SignalDiscrepanciesPanel trends={trends} loading={trendsLoading} />
      <section className="min-w-0">
        <AfIntel trends={trends} loading={pending.trends && !state.trends} />
      </section>
      <ExpertNotePanel />
    </div>
  );
}

"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { Pitch } from "@/components/Pitch";
import { PortfolioDashboard } from "@/components/PortfolioDashboard";
import { ClausulazosGuide } from "@/components/ClausulazosGuide";
import type { OptimizePayload, SquadsPayload } from "@/lib/types";

type Tab = "once" | "cartera" | "clausulas";

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "once", label: "Once", hint: "Alineación óptima y puntos esperados" },
  { id: "cartera", label: "Cartera", hint: "Vender, ofertas del ordenador y rentabilidad" },
  { id: "clausulas", label: "Cláusulas", hint: "Proteger, pagar clausulazo y calendario" },
];

function EquipoContent() {
  const search = useSearchParams();
  const tabParam = search.get("tab");
  const initial: Tab =
    tabParam === "cartera" || tabParam === "clausulas" || tabParam === "once" ? tabParam : "once";
  const [tab, setTab] = useState<Tab>(initial);
  const { state, pending } = useDashboard();

  useEffect(() => {
    if (tabParam === "cartera" || tabParam === "clausulas" || tabParam === "once") {
      setTab(tabParam);
    }
  }, [tabParam]);

  const active = TABS.find((item) => item.id === tab) ?? TABS[0];

  return (
    <div className="reveal flex min-w-0 flex-col gap-4">
      <div className="card p-4 md:p-5">
        <p className="eyebrow">Mi equipo</p>
        <h2 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-ink">{active.label}</h2>
        <p className="mt-1 text-sm text-muted">{active.hint}</p>
        <div className="seg mt-4">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={tab === item.id ? "seg__btn seg__btn--active" : "seg__btn"}
              aria-pressed={tab === item.id}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "once" ? (
        <Pitch
          optimize={state.optimize as OptimizePayload | null}
          squads={state.squads as SquadsPayload | null}
          loading={pending.optimize && !state.optimize}
        />
      ) : null}

      {tab === "cartera" ? (
        <PortfolioDashboard
          squads={state.squads as SquadsPayload | null}
          loading={pending.squads && !state.squads}
        />
      ) : null}

      {tab === "clausulas" ? <ClausulazosGuide /> : null}
    </div>
  );
}

export default function EquipoPage() {
  return (
    <Suspense fallback={<div className="reveal min-h-[40vh] animate-pulse rounded-2xl bg-white/5" />}>
      <EquipoContent />
    </Suspense>
  );
}

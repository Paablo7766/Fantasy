"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ClauseBoardPanel } from "@/components/ClauseBoardPanel";
import { LeagueRacePanel } from "@/components/LeagueRacePanel";
import { RivalIntelPanel } from "@/components/RivalIntelPanel";
import { RivalsDashboard } from "@/components/RivalsDashboard";
import { endpoint, getJson } from "@/lib/api";
import type {
  ClauseIntelPayload,
  NeedsPayload,
  RivalIntelPayload,
  SquadsPayload,
  TrendsPayload,
} from "@/lib/types";

type Vista = "liga" | "clausulas" | "caja";

export default function RivalesPage() {
  const search = useSearchParams();
  const league = search.get("league");
  const { state, pending } = useDashboard();
  const [vista, setVista] = useState<Vista>("liga");
  const [clauseIntel, setClauseIntel] = useState<{ league: string | null; payload: ClauseIntelPayload } | null>(
    null,
  );
  // La auditoría de caja trae la cota calibrada (``risk_adjusted_cash`` y
  // ``risk_adjusted_bid_limit``). Sin ella la tarjeta del rival solo puede
  // pintar la caja plana, así que se lee siempre, no solo en «Caja forense».
  const [rivalIntel, setRivalIntel] = useState<{ league: string | null; payload: RivalIntelPayload } | null>(null);
  const clauseIntelPayload = clauseIntel && clauseIntel.league === league ? clauseIntel.payload : null;
  const clauseIntelLoading = clauseIntelPayload === null;
  const rivalIntelPayload = rivalIntel && rivalIntel.league === league ? rivalIntel.payload : null;

  useEffect(() => {
    let cancelled = false;
    getJson<ClauseIntelPayload>(endpoint("/api/clause-intel", league))
      .then((payload) => {
        if (!cancelled) setClauseIntel({ league, payload });
      })
      .catch(() => {
        if (!cancelled) {
          setClauseIntel({ league, payload: { ok: false, error: { message: "Sin clause-intel." } } });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  useEffect(() => {
    let cancelled = false;
    getJson<RivalIntelPayload>(endpoint("/api/rival-intel", league))
      .then((payload) => {
        if (!cancelled) setRivalIntel({ league, payload });
      })
      .catch(() => {
        if (!cancelled) {
          setRivalIntel({ league, payload: { ok: false, error: { message: "Sin rival-intel." } } });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  return (
    <div className="reveal flex min-w-0 flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="seg">
          {(
            [
              ["liga", "Liga y plantillas"],
              ["clausulas", "Todas las cláusulas"],
              ["caja", "Caja forense"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setVista(key)}
              className={vista === key ? "seg__btn seg__btn--active" : "seg__btn"}
              aria-pressed={vista === key}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-[11px] leading-4 text-faint">
          {vista === "caja"
            ? "Reconstrucción de caja y cota de puja por rival, con el gasto que no aparece en los libros."
            : vista === "clausulas"
              ? "Todas las cláusulas rivales, sin filtro de regla de oro, con la subida de cada jugador fechada."
              : "Carrera de liga, plantillas y cláusulas a la vista."}
        </p>
      </div>

      {vista === "caja" ? (
        <RivalIntelPanel />
      ) : vista === "clausulas" ? (
        <ClauseBoardPanel />
      ) : (
        <>
          <LeagueRacePanel />
          <section className="min-w-0">
            <RivalsDashboard
              squads={state.squads as SquadsPayload | null}
              needs={state.needs as NeedsPayload | null}
              trends={state.trends as TrendsPayload | null}
              clauseIntel={clauseIntelPayload}
              rivalIntel={rivalIntelPayload}
              clauseIntelLoading={clauseIntelLoading}
              loading={(pending.squads || pending.needs) && !state.squads && !state.needs}
            />
          </section>
        </>
      )}
    </div>
  );
}

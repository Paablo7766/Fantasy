"use client";

import { useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { CatalogLab } from "@/components/CatalogLab";
import { MarketCard } from "@/components/MarketCard";
import { MarketTable } from "@/components/MarketTable";
import { QuantRadarPanel } from "@/components/QuantRadarPanel";
import type { TrendsPayload } from "@/lib/types";

type Vista = "mercado" | "radar" | "catalogo";

/**
 * Mercado y radar cuantitativo comparten pestaña pero no fuente de decisión:
 * la tabla mira la puja de la liga; el radar, el valor intrínseco y el dinero
 * global. Se separan para que ninguna tape a la otra. El catálogo es el
 * universo completo (libres, suelo y loterías), no solo lo anunciado.
 */
export default function MercadoPage() {
  const { state, pending, busy } = useDashboard();
  const trends = state.trends as TrendsPayload | null;
  const trendsLoading = pending.trends || (!state.trends && busy);
  const [vista, setVista] = useState<Vista>("mercado");

  return (
    <div className="reveal flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="seg">
          {(
            [
              ["mercado", "Mercado de la liga"],
              ["radar", "Radar cuantitativo"],
              ["catalogo", "Catálogo"],
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
          {vista === "radar"
            ? "Value investing: coste por punto, momentum global y blank rate. Sin mirar a tus rivales."
            : vista === "catalogo"
              ? "Agentes libres, suelo de lesión y loterías: el universo que no está anunciado."
              : "Pujar, esperar o dejar pasar según lo que hace tu liga."}
        </p>
      </div>

      {vista === "radar" ? (
        <QuantRadarPanel />
      ) : vista === "catalogo" ? (
        <CatalogLab />
      ) : (
        <section className="min-w-0 flex flex-col gap-6">
          <div>
            <h2 className="mb-3 text-sm font-semibold tracking-wide text-white">
              MERCADO HOY
            </h2>
            <MarketCard
              id="market-castrin"
              name="A. Castrín"
              position="DEF"
              team="Valencia"
              probability="100%"
              price="10,69M"
              trend={{ text: "-164K hoy", isUp: false }}
              recommendedBid="11,2M"
              analysis={{
                text: "+1,4 pts/jornada · sale Turrientes",
                isPositive: true,
              }}
            />
            <MarketCard
              id="market-diakhaby"
              name="Diakhaby"
              position="DEF"
              team="Valencia"
              probability="100%"
              price="1,24M"
              trend={{ text: "-24K hoy", isUp: false }}
              recommendedBid="1,24M"
              analysis={{ text: "No entra en tu once", isPositive: false }}
            />
          </div>
          {/* Las discrepancias ya no viven aquí: el motor las convierte en veto
              (acción NO + motivo) dentro de la propia tabla. El detalle AF vs
              modelo propio queda en Contexto · Intel. */}
          <MarketTable trends={trends} loading={trendsLoading} />
        </section>
      )}
    </div>
  );
}

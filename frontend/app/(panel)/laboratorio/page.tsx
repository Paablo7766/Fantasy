"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo } from "react";
import { prefetchLaboratorio } from "@/lib/laboratorio/prefetch";
import { CalibrationDashboard } from "@/components/laboratorio/CalibrationDashboard";
import { PostMortemPanel } from "@/components/laboratorio/PostMortemPanel";
import { useDashboard } from "@/components/DashboardProvider";
import { ModelReportPanel } from "@/components/laboratorio/ModelReportPanel";
import { PreviaPanel } from "@/components/laboratorio/PreviaPanel";
import { Skeleton } from "@/components/ui/kit";
import { RadarSimple } from "@/components/laboratorio/RadarSimple";
import { RivalesSimple } from "@/components/laboratorio/RivalesSimple";
import { SenalesSimple } from "@/components/laboratorio/SenalesSimple";
import { DatosSimple } from "@/components/laboratorio/DatosSimple";
import { CuentaPanel } from "@/components/laboratorio/CuentaPanel";
import { buildPhotoIndex } from "@/lib/core/photoIndex";
import type { OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Tab = "modelo" | "previa" | "radar" | "rivales" | "calibracion" | "senales" | "datos" | "cuenta";

/**
 * Zona de auditoría: cómo se construye cada número. Nada de aquí decide una
 * compra; sirve para fiarse (o no) del modelo y de la foto.
 */
const TABS: { id: Tab; label: string; hint: string }[] = [
  {
    id: "modelo",
    label: "Modelo",
    hint: "Si los datos llegan bien, qué dicen las casas de apuestas de cada partido y qué mejoras se están probando. Con un botón copias el informe para pegármelo.",
  },
  {
    id: "previa",
    label: "Previa",
    hint: "En pruebas: quién se espera que puntúe esta jornada, tus jugadores, a quién evitar y si la previa acierta.",
  },
  {
    id: "radar",
    label: "Radar técnico",
    hint: "Jugadores baratos para lo que puntúan, los que suben de precio y los libres que merecen la pena.",
  },
  { id: "rivales", label: "Rivales", hint: "Cuánto puede pujar cada rival y qué cláusulas tienes a tiro." },
  { id: "calibracion", label: "Calibración", hint: "Cuánto acierta el modelo con los puntos, las pujas y los avisos de venta, y el repaso de la última jornada." },
  { id: "senales", label: "Señales", hint: "Lo que dicen fuentes externas: precios de mañana, más puntos, chollos, lesiones y los onces de expertos." },
  { id: "datos", label: "Datos y API", hint: "Si la foto tiene todos los datos, qué fuente ha fallado y cuántas peticiones hace la app." },
  { id: "cuenta", label: "Cuenta", hint: "La foto guardada, conectar tu cuenta de LaLiga Fantasy y los avisos en este dispositivo." },
];

function asTab(value: string | null): Tab {
  return TABS.some((item) => item.id === value) ? (value as Tab) : "modelo";
}

function LaboratorioContent() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = asTab(search.get("tab"));
  const { state, pending, busy } = useDashboard();
  const trends = state.trends as TrendsPayload | null;
  const photos = useMemo(
    () =>
      buildPhotoIndex(state.plan as PlanPayload | null, state.optimize as OptimizePayload | null, state.squads as SquadsPayload | null, trends),
    [state.plan, state.optimize, state.squads, trends],
  );
  const trendsLoading = pending.trends || (!state.trends && busy);
  const current = TABS.find((item) => item.id === tab)!;
  const queryLeague = search.get("league");
  const apiLeague = trends?.league_id || queryLeague;

  // Todas las pestañas a la vez, en segundo plano: al cambiar de pestaña ya
  // está la respuesta en caché y se pinta sin esperar.
  useEffect(() => {
    prefetchLaboratorio(apiLeague, queryLeague);
  }, [apiLeague, queryLeague]);

  const select = (next: Tab) => {
    const params = new URLSearchParams(search.toString());
    if (next === "modelo") params.delete("tab");
    else params.set("tab", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  return (
    <div className="eq-stack reveal min-w-0">
      <section className="home-feature" aria-label="Laboratorio">
        <div className="relative flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-white/60">Zona de auditoría</p>
            <h1 className="mt-1 text-[2rem] font-semibold leading-none tracking-[-0.035em] text-white">Laboratorio</h1>
          </div>
          <span className="rounded-full bg-black/30 px-3 py-1.5 text-[12px] font-semibold text-[#FF9A5A] backdrop-blur-md">
            {TABS.findIndex((item) => item.id === tab) + 1} / {TABS.length} · {current.label}
          </span>
        </div>
        <p className="relative mt-3 max-w-2xl text-[13.5px] leading-snug text-white/60">{current.hint}</p>
        <p className="relative mt-2 text-[12px] text-white/40">Nada de aquí decide una compra: sirve para fiarse (o no) del modelo y de la foto.</p>
      </section>

      <nav className="lab-nav" role="tablist" aria-label="Herramientas del laboratorio">
        {TABS.map((item) => (
          <button
            key={item.id}
            id={`lab-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            aria-controls={`lab-panel-${item.id}`}
            className={tab === item.id ? "eq-chip eq-chip--on" : "eq-chip"}
            onClick={() => select(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div key={tab} id={`lab-panel-${tab}`} role="tabpanel" aria-labelledby={`lab-tab-${tab}`} className="lab-panel row-in min-w-0">
        {tab === "modelo" ? (
          <ModelReportPanel />
        ) : tab === "previa" ? (
          <PreviaPanel />
        ) : tab === "radar" ? (
          <RadarSimple photos={photos} />
        ) : tab === "rivales" ? (
          <RivalesSimple photos={photos} />
        ) : tab === "calibracion" ? (
          <div className="flex min-w-0 flex-col gap-4">
            <CalibrationDashboard />
            <PostMortemPanel />
          </div>
        ) : tab === "senales" ? (
          <SenalesSimple trends={trends} loading={trendsLoading} photos={photos} />
        ) : tab === "cuenta" ? (
          <CuentaPanel />
        ) : (
          <DatosSimple />
        )}
      </div>
    </div>
  );
}

export default function LaboratorioPage() {
  return (
    <Suspense
      fallback={
        <div className="eq-stack">
          <Skeleton />
        </div>
      }
    >
      <LaboratorioContent />
    </Suspense>
  );
}

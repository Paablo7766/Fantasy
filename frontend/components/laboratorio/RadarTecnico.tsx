"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Disclosure, Empty, SectionHead, Skeleton, money } from "@/components/equipo/ui";
import { QuantList } from "@/components/mercado/OportunidadesTab";
import { endpoint, getJson } from "@/lib/api";
import { points } from "@/lib/format";
import type { PhotoIndex } from "@/lib/photoIndex";
import type { QuantRadarPayload } from "@/lib/types";

/**
 * Lo que hay detrás de «Oportunidades»: cómo se puntúa el radar, qué se
 * descarta y contra qué precio se compara. Para auditar el modelo, no para
 * decidir una compra.
 */
export function RadarTecnico({ photos }: { photos: PhotoIndex }) {
  const search = useSearchParams();
  const league = search.get("league");
  const [loaded, setLoaded] = useState<{ league: string | null; payload: QuantRadarPayload } | null>(null);
  const payload = loaded && loaded.league === league ? loaded.payload : null;

  useEffect(() => {
    let cancelled = false;
    getJson<QuantRadarPayload>(endpoint("/api/market/quant-radar", league))
      .then((value) => {
        if (!cancelled) setLoaded({ league, payload: value });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ league, payload: { ok: false, error: { message: "Sin /api/market/quant-radar." } } });
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const toxic = useMemo(() => (Array.isArray(payload?.toxic) ? payload!.toxic! : []), [payload]);

  if (payload === null) return <Skeleton />;
  if (payload.ok === false) {
    return <Empty title="Sin lectura cuantitativa" detail={`${payload.error?.message || "El radar no devolvió datos."} Pulsa Actualizar para guardar una foto nueva.`} />;
  }

  const baselines = payload.baselines || {};
  const weights = payload.assumptions?.weights;

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-3">
        <SectionHead title="Pesos de la nota" />
        <p className="home-glass px-4 py-4 text-[13.5px] leading-relaxed text-white/60">
          La nota del radar (0–100) combina valor {Math.round((weights?.value ?? 0.55) * 100)} %, descuento{" "}
          {Math.round((weights?.discount ?? 0.25) * 100)} % y momentum {Math.round((weights?.momentum ?? 0.2) * 100)} %.
        </p>
      </section>

      <Disclosure title="Tóxicos descartados" meta={`${toxic.length}`} defaultOpen>
        <p className="mb-3 text-[12.5px] text-white/50">Baratos, pero dejan demasiadas jornadas en blanco.</p>
        {toxic.length ? <QuantList rows={toxic} tone="toxic" photos={photos} /> : <p className="text-[13px] text-white/45">Ninguno entre los fichables.</p>}
      </Disclosure>

      <Disclosure title="Precio de referencia por posición" meta="€ / punto" defaultOpen>
        <p className="text-[12.5px] leading-relaxed text-white/50">
          Cuánto cuesta cada punto que produce un jugador, comparado con la mediana de su posición: un MC de 2 M que puntúa como uno de 6 M es una
          ineficiencia, no una corazonada.
        </p>
        <ul className="mt-2">
          {(["POR", "DEF", "MC", "DEL"] as const).map((position) => {
            const row = baselines[position];
            return (
              <li key={position} className="flex items-center justify-between gap-3 border-b border-white/[0.06] py-2.5 last:border-b-0">
                <span className="text-[14.5px] font-medium text-white">{position}</span>
                <span className="text-right">
                  <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(row?.median_cost_per_point_eur)}</span>
                  <span className="block text-[12px] text-white/45">
                    {row?.count ?? 0} con muestra · mediana {points(row?.median_points)} pts
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-[12px] leading-relaxed text-white/40">
          Blank = jornadas con ≤ {payload.assumptions?.blank_threshold_points ?? 2} puntos. Por encima del{" "}
          {Math.round((payload.assumptions?.max_blank_rate ?? 0.4) * 100)} % el jugador se marca tóxico aunque esté barato.
        </p>
      </Disclosure>
    </div>
  );
}

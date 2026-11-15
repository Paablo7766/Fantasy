"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { lastName } from "@/components/ui/kit";
import { endpoint } from "@/lib/core/api";
import { points } from "@/lib/core/format";
import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { construirTablero } from "@/lib/equipo/planificador";
import type { PlanificadorPayload } from "@/lib/types";

/** Acceso al Planificador desde Equipo: una fila, con el mejor fichable de la próxima jornada. */
export function PlanificadorAcceso() {
  const search = useSearchParams();
  const { trends } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const url = endpoint("/api/planificador", league);
  const param = search.get("league");
  const href = param ? `/equipo/planificador?league=${encodeURIComponent(param)}` : "/equipo/planificador";
  const [payload, setPayload] = useState<PlanificadorPayload | null>(() => peekJson<PlanificadorPayload>(url) ?? null);

  useEffect(() => {
    let cancelled = false;
    cachedJson<PlanificadorPayload>(url)
      .then((data) => {
        if (!cancelled) setPayload(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [url]);

  const detalle = useMemo(() => {
    const mejor = payload?.jugadores?.length ? construirTablero(payload.jugadores, 0).fichables[0] : null;
    if (!mejor) return "Quién suma más y si su precio compensa";
    const jornada = payload?.jornadas?.[0];
    return `Mejor fichable${jornada ? ` en J${jornada}` : ""}: ${lastName(mejor.nombre || "")} · ${points(mejor.xp[0])} xP`;
  }, [payload]);

  return (
    <Link
      href={href}
      className="home-glass group flex items-center gap-3 px-4 py-3.5 transition-colors duration-200 ease-out hover:bg-white/[0.06]"
    >
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-semibold leading-tight text-white">Planificador</span>
        <span className="mt-1 block truncate text-[12.5px] text-white/50">{detalle}</span>
      </span>
      <svg
        viewBox="0 0 16 16"
        className="h-4 w-4 shrink-0 text-white/35 transition-transform duration-200 ease-out group-hover:translate-x-0.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        aria-hidden="true"
      >
        <path d="m6 3 5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </Link>
  );
}

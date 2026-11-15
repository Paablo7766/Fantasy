"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { TONE } from "@/components/ui/kit";
import { endpoint } from "@/lib/core/api";
import { points } from "@/lib/core/format";
import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { construirPlan } from "@/lib/equipo/planificador";
import type { PlanificadorPayload } from "@/lib/types";

/** Acceso al Planificador desde Equipo: enseña lo que sube tu once en la próxima jornada. */
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

  const resumen = useMemo(() => {
    if (!payload?.jugadores?.length) return null;
    const plan = construirPlan(payload.jugadores, 0);
    if (!plan.base || !plan.techo) return null;
    return { mejora: plan.techo.total - plan.base.total, pasos: plan.pasos.length, jornada: payload.jornadas?.[0] ?? null };
  }, [payload]);

  const jornada = resumen?.jornada ? `J${resumen.jornada}` : "próxima";
  const detalle = !resumen
    ? "Qué fichar y clausular"
    : resumen.pasos
      ? `${resumen.pasos === 1 ? "1 movimiento" : `${resumen.pasos} movimientos`} para la ${jornada}`
      : `Tu once ya es el mejor · ${jornada}`;

  return (
    <Link href={href} className="plan-cta group">
      <span className="plan-cta__icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 14.5 7.5 10l3 3L17 6.5" />
          <path d="M12.5 6.5H17V11" />
        </svg>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-semibold leading-tight text-white">Planificador</span>
        <span className="mt-0.5 block truncate text-[12.5px] text-white/50">{detalle}</span>
      </span>
      {resumen && resumen.pasos ? (
        <span className="shrink-0 text-right">
          <span className="block font-mono text-[1.15rem] font-semibold leading-none tabular-nums" style={{ color: TONE.green }}>
            +{points(resumen.mejora)}
          </span>
          <span className="mt-1 block text-[11px] text-white/40">xP</span>
        </span>
      ) : null}
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

"use client";

import { useDashboard } from "@/components/DashboardProvider";
import { ageFromStamp, durationAgo } from "@/lib/core/format";
import { useNow } from "@/lib/core/useClock";
import type { SquadsPayload, TrendsPayload } from "@/lib/types";

export type AgeKey = "mercado" | "plantillas" | "titularidad";

/** A partir de aquí el dato de LaLiga ya no es de fiar para pujar o fijar el once. */
const STALE_SECONDS = 6 * 3600;

/** Horas hasta las 48 h (``durationAgo`` pasa a días a las 24 h y «hace 1 d» es demasiado burdo). */
function ago(seconds: number): string {
  return seconds >= 86400 && seconds < 172800 ? `hace ${Math.round(seconds / 3600)} h` : durationAgo(seconds);
}

const LABEL: Record<AgeKey, string> = { mercado: "Mercado", plantillas: "Plantillas", titularidad: "Titularidad" };

/**
 * Edad de cada dato, con la marca que ya trae la foto (nada de red):
 * mercado → ``trends.market.fetched_at`` (LaLiga), plantillas →
 * ``squads.fetched_at`` (LaLiga), titularidad → ``trends.fetched_at``
 * (FútbolFantasy / Analítica Fantasy). Solo se pinta si algo pasa de 6 h:
 * un aviso de una línea con el botón Actualizar (lo lanza la persona).
 */
export function DataAge({ show }: { show: AgeKey[] }) {
  const { state, refresh, refreshing, connecting } = useDashboard();
  const nowMs = useNow();
  if (nowMs === 0) return null;
  const trends = state.trends as TrendsPayload | null;
  const squads = state.squads as SquadsPayload | null;
  const stamp: Record<AgeKey, string | null | undefined> = {
    mercado: trends?.market?.fetched_at ?? trends?.fetched_at,
    plantillas: squads?.fetched_at,
    titularidad: trends?.fetched_at,
  };
  const rows = show.map((key) => ({ key, seconds: ageFromStamp(stamp[key], nowMs) }));
  const stale = rows.filter((row) => row.seconds === null || row.seconds >= STALE_SECONDS);
  // Al día no hay nada que decir: la edad solo aparece cuando ya no es de fiar.
  if (!stale.length) return null;
  const detail = stale.map((row) => `${LABEL[row.key].toLowerCase()} ${row.seconds === null ? "sin fecha" : ago(row.seconds).replace("hace ", "de hace ")}`).join(" · ");
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-amber-soft/[0.08] px-4 py-2.5" role="status" data-ui="data-age">
      <p className="flex min-w-0 items-start gap-2.5 text-[13px] leading-snug text-white/75">
        <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-amber-soft" aria-hidden="true" />
        <span className="min-w-0">
          Datos antiguos: <span className="tabular-nums text-white/55">{detail}</span>
        </span>
      </p>
      <button
        type="button"
        onClick={() => void refresh()}
        disabled={refreshing || connecting}
        className="relative shrink-0 rounded-full bg-white/10 px-3.5 py-1.5 before:absolute before:-inset-x-1 before:-inset-y-2 text-[12.5px] font-semibold text-white transition-colors hover:bg-white/15 disabled:opacity-50"
      >
        {refreshing ? "Actualizando…" : "Actualizar"}
      </button>
    </div>
  );
}

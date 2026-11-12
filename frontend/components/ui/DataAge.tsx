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
 * (FútbolFantasy / Analítica Fantasy). Si algo pasa de 6 h se sugiere
 * Actualizar, pero lo lanza la persona: aquí no se pide nada solo.
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
  const old = rows.some((row) => row.seconds === null || row.seconds >= STALE_SECONDS);
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[12px] text-white/45" data-ui="data-age">
      {rows.map((row) => {
        const stale = row.seconds === null || row.seconds >= STALE_SECONDS;
        return (
          <span key={row.key}>
            {LABEL[row.key]}{" "}
            <span
              className="tabular-nums"
              style={{ fontFamily: "var(--font-mono), ui-monospace, monospace", color: stale ? "var(--ini-amber, #f5b544)" : undefined }}
            >
              {row.seconds === null ? "sin dato" : ago(row.seconds)}
            </span>
          </span>
        );
      })}
      {old ? (
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing || connecting}
          className="text-[12px] font-medium text-[var(--ini-copper)] hover:underline disabled:opacity-50"
        >
          {refreshing ? "Actualizando…" : "Datos viejos: Actualizar"}
        </button>
      ) : null}
    </p>
  );
}

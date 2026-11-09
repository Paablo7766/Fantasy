"use client";

import { useEffect, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";

const HOUR = 3600;

/**
 * Estado de los datos y recarga en un solo gesto, bajo la cifra del hero:
 * «● Actualizado hace 2 h ⟳». El punto pasa de verde (< 1 h) a ámbar (< 6 h)
 * y a rojo cuando conviene descargar. Pulsarlo descarga datos nuevos.
 */
export function RefreshChip() {
  const { photoAge, photoAgeSeconds, refreshing, busy, refreshPct, progress, refreshError, connecting, refresh } = useDashboard();
  const [justDone, setJustDone] = useState(false);
  const [wasRefreshing, setWasRefreshing] = useState(refreshing);

  if (wasRefreshing !== refreshing) {
    setWasRefreshing(refreshing);
    if (!refreshing && !refreshError) setJustDone(true);
  }
  useEffect(() => {
    if (!justDone) return;
    const id = window.setTimeout(() => setJustDone(false), 2400);
    return () => window.clearTimeout(id);
  }, [justDone]);

  const working = refreshing || busy;
  const pct = refreshing ? refreshPct : progress.pct;
  const old = photoAgeSeconds === null || photoAgeSeconds >= 6 * HOUR;
  const tone = working ? "#38bdf8" : refreshError ? "#ff7d66" : justDone ? "#34d399" : old ? "#ff7d66" : photoAgeSeconds! >= HOUR ? "#f5b544" : "#34d399";
  const label = refreshing
    ? `Actualizando ${pct}%`
    : busy
      ? `Cargando ${pct}%`
      : refreshError
        ? "No se pudo actualizar · reintentar"
        : justDone
          ? "Al día"
          : photoAge
            ? `Actualizado ${photoAge}`
            : "Sin datos · actualizar";

  return (
    <button
      type="button"
      className="ini-sync"
      onClick={() => void refresh()}
      disabled={connecting || refreshing}
      aria-label={refreshError ? "Reintentar la descarga" : "Actualizar datos"}
      title="Descargar datos nuevos (R)"
      data-ui="refresh"
    >
      <span className="ini-sync__dot" style={{ background: tone, boxShadow: `0 0 0 3px ${tone}2e` }} aria-hidden="true" />
      <span aria-live="polite" className="ini-sync__text">{label}</span>
      <svg viewBox="0 0 20 20" className={`ini-sync__icon ${refreshing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <path d="M16.2 10a6.2 6.2 0 1 1-1.6-4.1" strokeLinecap="round" />
        <path d="M16.4 3.6v3.2h-3.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {working ? (
        <span className="ini-sync__bar" aria-hidden="true">
          <span style={{ width: `${Math.max(4, Math.min(100, pct))}%` }} />
        </span>
      ) : null}
    </button>
  );
}

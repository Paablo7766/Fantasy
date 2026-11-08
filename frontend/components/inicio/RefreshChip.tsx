"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { AvisosBell } from "@/components/AvisosBell";

const HOUR = 3600;

/**
 * Recarga de datos, solo en Inicio y dentro del hero: «hace 2 h» y un icono.
 * El punto pasa de verde (< 1 h) a ámbar (< 6 h) y a rojo cuando conviene
 * descargar. Tocar la hora abre un menú corto con la foto, el Laboratorio y
 * Conectar cuenta (en móvil no hay barra lateral para llegar a ellos).
 */
export function RefreshChip() {
  const {
    photoAge,
    photoAgeSeconds,
    photoLine,
    refreshing,
    busy,
    refreshPct,
    progress,
    refreshError,
    connecting,
    refresh,
    connectAccount,
    trends,
  } = useDashboard();
  const search = useSearchParams();
  const [open, setOpen] = useState(false);
  const [justDone, setJustDone] = useState(false);
  const [wasRefreshing, setWasRefreshing] = useState(refreshing);
  const box = useRef<HTMLDivElement>(null);

  if (wasRefreshing !== refreshing) {
    setWasRefreshing(refreshing);
    if (!refreshing && !refreshError) setJustDone(true);
  }
  useEffect(() => {
    if (!justDone) return;
    const id = window.setTimeout(() => setJustDone(false), 2400);
    return () => window.clearTimeout(id);
  }, [justDone]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const working = refreshing || busy;
  const pct = refreshing ? refreshPct : progress.pct;
  const old = photoAgeSeconds === null || photoAgeSeconds >= 6 * HOUR;
  const tone = working ? "#38bdf8" : refreshError ? "#ff7d66" : justDone ? "#34d399" : old ? "#ff7d66" : photoAgeSeconds! >= HOUR ? "#f5b544" : "#34d399";
  const label = refreshing
    ? `Actualizando ${pct}%`
    : busy
      ? `Cargando ${pct}%`
      : refreshError
        ? "Falló"
        : justDone
          ? "Al día"
          : photoAge || "Sin datos";
  const query = search.toString();
  const labHref = query ? `/laboratorio?${query}` : "/laboratorio";

  return (
    <div ref={box} className="relative justify-self-end" data-ui="refresh-chip">
      <div className="ini-refresh ini-refresh--quiet">
        <button
          type="button"
          className="ini-refresh__age"
          onClick={() => setOpen((value) => !value)}
          aria-haspopup="menu"
          aria-expanded={open}
          title={`${label} · ver la foto`}
        >
          <span className="ini-refresh__dot" style={{ background: tone, boxShadow: old && !working ? `0 0 0 3px ${tone}33` : undefined }} aria-hidden="true" />
          <span aria-live="polite" className={working ? "text-working" : undefined}>{label}</span>
        </button>
        <button
          type="button"
          className="ini-refresh__btn"
          onClick={() => void refresh()}
          disabled={connecting || refreshing}
          aria-label={refreshError ? "Reintentar la descarga" : "Actualizar datos"}
          title="Descargar datos nuevos (R)"
          data-ui="refresh"
          data-progress={working ? "true" : undefined}
          style={{ "--p": `${Math.max(0, Math.min(100, pct))}%` } as CSSProperties}
        >
          <svg viewBox="0 0 20 20" className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M16.2 10a6.2 6.2 0 1 1-1.6-4.1" strokeLinecap="round" />
            <path d="M16.4 3.6v3.2h-3.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {open ? (
        <div role="menu" className="ini-refresh__menu">
          <p className="font-mono text-[11px] text-white/70">{photoLine}</p>
          {refreshError ? <p className="mt-1 text-[11.5px] text-[#ffb3a4]">{refreshError}</p> : null}
          {trends?.partial ? <p className="mt-1 text-[11.5px] text-[#ffd58a]">Lectura parcial</p> : null}
          <div className="mt-2.5 flex flex-col gap-1">
            <Link role="menuitem" href={labHref} className="ini-refresh__item" onClick={() => setOpen(false)}>
              Laboratorio · estado del modelo
            </Link>
            <button
              role="menuitem"
              type="button"
              className="ini-refresh__item"
              disabled={connecting || busy}
              onClick={() => {
                setOpen(false);
                void connectAccount();
              }}
            >
              {connecting ? "Elige tu cuenta en Chrome…" : "Conectar cuenta"}
            </button>
            <AvisosBell className="ini-refresh__item" />
          </div>
        </div>
      ) : null}
    </div>
  );
}

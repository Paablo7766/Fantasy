"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { AvisosBell } from "@/components/AvisosBell";

/**
 * Pie del hero, simétrico: matraz (Laboratorio) a la izquierda, el estado que
 * recarga en el centro y «⋯» (foto, Conectar cuenta y Avisos) a la derecha
 * (en móvil no hay barra lateral para llegar a ellos).
 */
export function HeroTools({ children }: { children: ReactNode }) {
  const { photoLine, refreshError, connecting, busy, connectAccount, trends } = useDashboard();
  const search = useSearchParams();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const query = search.toString();
  const labHref = query ? `/laboratorio?${query}` : "/laboratorio";

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

  return (
    <div ref={box} className="ini-dock" data-ui="hero-tools">
      <Link href={labHref} className="ini-tool" aria-label="Laboratorio" title="Laboratorio · estado del modelo" data-ui="home-lab">
        <svg viewBox="0 0 20 20" className="h-[1.05rem] w-[1.05rem]" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <path d="M8 2.8h4M8.8 2.8v4.6L4.4 15a1.4 1.4 0 0 0 1.2 2.1h8.8A1.4 1.4 0 0 0 15.6 15l-4.4-7.6V2.8" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M6.4 12.2h7.2" strokeLinecap="round" />
        </svg>
      </Link>
      {children}
      <button type="button" className="ini-tool" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label="Más opciones" title="Foto guardada, cuenta y avisos">
        <svg viewBox="0 0 20 20" className="h-[1.05rem] w-[1.05rem]" fill="currentColor" aria-hidden="true">
          <circle cx="4.5" cy="10" r="1.4" />
          <circle cx="10" cy="10" r="1.4" />
          <circle cx="15.5" cy="10" r="1.4" />
        </svg>
      </button>
      {open ? (
        <div role="menu" className="ini-refresh__menu">
          <p className="font-mono text-[11px] text-white/70">{photoLine}</p>
          {refreshError ? <p className="mt-1 text-[11.5px] text-[#ffb3a4]">{refreshError}</p> : null}
          {trends?.partial ? <p className="mt-1 text-[11.5px] text-[#ffd58a]">Lectura parcial</p> : null}
          <div className="mt-2.5 flex flex-col gap-1">
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

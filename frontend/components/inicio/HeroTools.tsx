"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

/**
 * Pie del hero: el estado que recarga y el acceso al Laboratorio, juntos y
 * centrados. Foto guardada, Conectar cuenta y Avisos viven ahora en
 * Laboratorio › Cuenta.
 */
export function HeroTools({ children }: { children: ReactNode }) {
  const search = useSearchParams();
  const query = search.toString();
  const labHref = query ? `/laboratorio?${query}` : "/laboratorio";
  return (
    <div className="ini-dock" data-ui="hero-tools">
      <span className="ini-dock__side" aria-hidden="true" />
      {children}
      <Link href={labHref} className="ini-tool ini-dock__side" aria-label="Laboratorio" title="Laboratorio · estado del modelo" data-ui="home-lab">
        <svg viewBox="0 0 20 20" className="h-[1.05rem] w-[1.05rem]" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <path d="M8 2.8h4M8.8 2.8v4.6L4.4 15a1.4 1.4 0 0 0 1.2 2.1h8.8A1.4 1.4 0 0 0 15.6 15l-4.4-7.6V2.8" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M6.4 12.2h7.2" strokeLinecap="round" />
        </svg>
      </Link>
    </div>
  );
}

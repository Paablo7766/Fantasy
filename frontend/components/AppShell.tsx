"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { DataHealthPanel } from "@/components/DataHealthPanel";
import { ApiUsagePanel } from "@/components/ApiUsagePanel";
import { useDashboard } from "@/components/DashboardProvider";

type NavItem = {
  href: string;
  label: string;
  title: string;
  hint: string;
};

const SECTIONS: readonly NavItem[] = [
  {
    href: "/",
    label: "Recomendaciones",
    title: "Hoy",
    hint: "Qué hacer primero: vender, pujar, clausular o alinear",
  },
  {
    href: "/equipo",
    label: "Equipo",
    title: "Equipo",
    hint: "Tu once y tu cartera",
  },
  {
    href: "/mercado",
    label: "Mercado",
    title: "Mercado",
    hint: "Qué comprar hoy, oportunidades y buscador",
  },
  {
    href: "/clausulas",
    label: "Cláusulas",
    title: "Cláusulas",
    hint: "Defiende las tuyas y ataca las rivales",
  },
  {
    href: "/liga",
    label: "Liga",
    title: "Liga",
    hint: "Clasificación, rivales y cláusulas ajenas",
  },
] as const;

type SectionLabel = (typeof SECTIONS)[number]["label"];

function Icon({ name }: { name: SectionLabel }) {
  const common = {
    viewBox: "0 0 20 20",
    className: "h-4 w-4",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    "aria-hidden": true as const,
  };
  if (name === "Recomendaciones") {
    return (
      <svg {...common}>
        <path d="M10 3.2 12.4 8h4.6l-3.7 2.7 1.4 4.5L10 14.8l-4.7 3.4 1.4-4.5L3 8h4.6L10 3.2Z" strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "Equipo") {
    return (
      <svg {...common}>
        <circle cx="10" cy="6.2" r="1.5" />
        <circle cx="5.4" cy="10" r="1.5" />
        <circle cx="14.6" cy="10" r="1.5" />
        <circle cx="10" cy="14.2" r="1.5" />
      </svg>
    );
  }
  if (name === "Mercado") {
    return (
      <svg {...common}>
        <path d="M3.5 8.2h13l-1.1 7.2H4.6L3.5 8.2Z" strokeLinejoin="round" />
        <path d="M7 8.1 8.2 4.8h3.6L13 8.1" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "Cláusulas") {
    return (
      <svg {...common}>
        <rect x="4.5" y="9" width="11" height="7.5" rx="1.6" strokeLinejoin="round" />
        <path d="M7 9V6.8a3 3 0 0 1 6 0V9" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M5 18V8l7-4 7 4v10" strokeLinejoin="round" />
      <path d="M9 18v-5h6v5" strokeLinejoin="round" />
    </svg>
  );
}

function sectionFromPath(pathname: string): NavItem {
  const match = SECTIONS.find((section) =>
    section.href === "/" ? pathname === "/" : pathname === section.href || pathname.startsWith(`${section.href}/`),
  );
  return match ?? SECTIONS[0];
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function DockLink({ item, active, href }: { item: NavItem; active: boolean; href: string }) {
  return (
    <Link
      href={href}
      className="flex h-full min-w-0 flex-1 items-center justify-center"
      aria-current={active ? "page" : undefined}
    >
      <span
        className={`flex flex-col items-center gap-0.5 rounded-xl px-3.5 py-1.5 text-[10px] font-medium tracking-tight transition-all duration-200 ${
          active ? "bg-[#FF7A3D] text-[#120C09] shadow-[0_0_18px_rgba(255,122,61,0.45)]" : "text-white/50"
        }`}
      >
        <Icon name={item.label} />
        <span>{item.label === "Recomendaciones" ? "Inicio" : item.label}</span>
      </span>
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const {
    trends,
    leagueName,
    busy,
    refreshing,
    refreshError,
    stale,
    photoAge,
    photoLine,
    progress,
    refreshLine,
    refreshPct,
    connecting,
    connectMessage,
    connectAccount,
    refresh,
    markShellReady,
  } = useDashboard();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [toolsOpen, setToolsOpen] = useState(false);
  const section = sectionFromPath(pathname);
  const query = searchParams.toString();
  const withQuery = (href: string) => (query ? `${href}?${query}` : href);

  useEffect(() => {
    markShellReady();
  }, [markShellReady]);

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="flex items-center gap-3 px-2 pb-5">
          <span className="brand-mark">LF</span>
          <div className="min-w-0">
            <p className="text-[0.95rem] font-semibold leading-none tracking-[-0.03em] text-white">LALIGA Fantasy</p>
            <p className="mt-1 text-[11px] text-[color:var(--sidebar-muted)]">5 pantallas · decisión clara</p>
          </div>
        </div>

        <nav className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1" aria-label="Secciones">
          {SECTIONS.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.label}
                href={withQuery(item.href)}
                className={active ? "side-link side-link--active" : "side-link"}
                aria-current={active ? "page" : undefined}
              >
                <span className="side-link__icon">
                  <Icon name={item.label} />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium tracking-tight">{item.label}</span>
                  <span className="block truncate text-[11px] text-[color:var(--sidebar-muted)]">{item.hint}</span>
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-4 border-t border-[color:var(--sidebar-line)] px-2 pt-4">
          <p className="truncate text-sm font-medium text-white">{leagueName}</p>
          <p className="mt-1 font-mono text-[11px] text-[color:var(--sidebar-muted)]">{photoLine}</p>
          <button
            type="button"
            onClick={() => void connectAccount()}
            disabled={connecting || busy}
            className="btn btn-ghost mt-3 w-full justify-start px-0"
          >
            {connecting ? "Elige tu cuenta en Chrome…" : "Conectar cuenta"}
          </button>
        </div>
      </aside>

      <div className="app-frame">
        <header className="app-topbar relative">
          <div className="flex h-14 items-center justify-between gap-3 px-4 lg:px-7">
            <div className="flex min-w-0 items-center gap-2.5">
              <h1 className="truncate text-lg font-bold tracking-tight text-ink">{section.title}</h1>
              <button
                type="button"
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[rgba(2,151,222,0.28)] bg-[rgba(2,151,222,0.08)] px-2 py-1 text-[11px] font-semibold text-[#8B9EB0]"
                onClick={() => setToolsOpen(true)}
                aria-haspopup="dialog"
                aria-expanded={toolsOpen}
                title={photoLine}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    refreshing || busy ? "animate-pulse bg-[#0297DE]" : stale || refreshError ? "bg-[#FC734D]" : "bg-[#10B981]"
                  }`}
                  style={{ boxShadow: "0 0 8px currentColor" }}
                />
                <span className="font-mono tabular-nums">
                  {refreshing ? `${refreshPct}%` : busy ? `${progress.pct}%` : photoAge || "sin foto"}
                </span>
              </button>
            </div>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={connecting || refreshing}
              className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-[#0297DE]/40 bg-[#0297DE]/15 px-3 text-xs font-medium text-[#0297DE] transition-all hover:bg-[#0297DE]/25 active:scale-95 disabled:opacity-50"
              title="Descarga una foto nueva de LALIGA y los scrapers"
            >
              <svg
                viewBox="0 0 20 20"
                className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden="true"
              >
                <path d="M16.2 10a6.2 6.2 0 1 1-1.6-4.1" strokeLinecap="round" />
                <path d="M16.4 3.6v3.2h-3.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {refreshing ? "Actualizando" : "Actualizar"}
            </button>
          </div>
          {refreshing ? (
            <div className="absolute inset-x-0 bottom-0" role="status" aria-live="polite" aria-label={refreshLine}>
              <div className="load-progress">
                <div className="load-progress__bar" style={{ width: `${Math.max(refreshPct, 4)}%` }} />
              </div>
            </div>
          ) : null}
          {connectMessage ? (
            <div className="px-4 pb-3 lg:px-7" role={connecting ? "status" : "alert"} aria-live="polite">
              <div className="status-note">{connectMessage}</div>
            </div>
          ) : null}
        </header>
        {toolsOpen ? (
          <div className="fixed inset-0 z-[80] flex items-start justify-center bg-black/55 px-4 pt-16" onClick={() => setToolsOpen(false)}>
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Foto, uso de API y conexión"
              className="card w-full max-w-sm p-4"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-[#8B9EB0]">Foto</p>
                  <p className="mt-1 font-mono text-xs text-[#F0F6FC]">{photoLine}</p>
                  {refreshError ? <p className="mt-1 text-xs text-[#FC734D]">{refreshError}</p> : null}
                  {trends?.partial ? <p className="mt-1 text-xs text-[#FC734D]">Lectura parcial</p> : null}
                </div>
                <button type="button" className="btn btn-secondary !px-2.5 !py-1 text-xs" onClick={() => setToolsOpen(false)}>
                  Cerrar
                </button>
              </div>
              <div className="flex flex-col items-start gap-2">
                <ApiUsagePanel />
                <DataHealthPanel />
                <button
                  type="button"
                  onClick={() => void connectAccount()}
                  disabled={connecting || busy}
                  className="btn btn-secondary w-full"
                  title="Abre Chrome para elegir la cuenta de Google de LALIGA Fantasy"
                >
                  {connecting ? "Elige tu cuenta en Chrome…" : "Conectar cuenta"}
                </button>
              </div>
            </div>
          </div>
        ) : null}

        <div className="app-page min-w-0 app-page--dock">{children}</div>

        <nav
          className="fixed inset-x-5 bottom-3 z-50 flex h-14 items-stretch overflow-hidden rounded-2xl border border-white/[0.08] bg-[#060E14]/90 backdrop-blur-2xl lg:hidden"
          aria-label="Navegación principal"
        >
          {SECTIONS.map((item) => (
            <DockLink key={item.label} item={item} active={isActive(pathname, item.href)} href={withQuery(item.href)} />
          ))}
        </nav>

        <footer className="mx-auto w-full max-w-[1240px] px-4 pb-24 text-xs leading-5 text-faint md:px-7 md:pb-8 lg:pb-8">
          Solo lectura. Las horas de cláusula salen de la API en Europe/Madrid. Pulsa Actualizar antes de decidir con
          dinero real.
        </footer>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";
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
    title: "Recomendaciones",
    hint: "Qué hacer primero: vender, pujar, clausular o alinear",
  },
  {
    href: "/equipo",
    label: "Equipo",
    title: "Equipo",
    hint: "Once, cartera y cláusulas en un solo sitio",
  },
  {
    href: "/mercado",
    label: "Mercado",
    title: "Mercado",
    hint: "Pujas, radar cuantitativo y catálogo",
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
  if (href === "/equipo") {
    return (
      pathname === "/equipo" ||
      pathname.startsWith("/equipo/") ||
      pathname === "/once" ||
      pathname === "/cartera" ||
      pathname === "/clausulazos"
    );
  }
  if (href === "/liga") {
    return pathname === "/liga" || pathname === "/rivales" || pathname.startsWith("/rivales/");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
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
            <p className="mt-1 text-[11px] text-[color:var(--sidebar-muted)]">4 pantallas · decisión clara</p>
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
        <header className="app-topbar">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-7">
            <div className="flex min-w-0 items-center gap-3 lg:block">
              <span className="brand-mark lg:hidden">LF</span>
              <div className="min-w-0">
                <p className="eyebrow hidden sm:block">Mesa de decisión</p>
                <h1 className="truncate text-lg font-semibold tracking-[-0.03em] text-ink md:text-xl">{section.title}</h1>
                <p className="hidden truncate text-sm text-muted sm:block">{section.hint}</p>
              </div>
            </div>

            <div className="flex w-full min-w-0 items-center gap-1.5 overflow-x-auto sm:w-auto sm:justify-end sm:gap-2">
              {refreshing ? (
                <span className="status-dot status-dot--pulse" aria-live="polite">
                  Descargando {refreshPct}%
                </span>
              ) : busy ? (
                <span className="status-dot status-dot--pulse" aria-live="polite">
                  Leyendo {progress.pct}%
                </span>
              ) : stale ? (
                <span className="status-dot status-dot--warn" title="La foto guardada tiene más de 15 minutos">
                  {photoAge ? `Foto de ${photoAge}` : "Foto antigua"}
                </span>
              ) : null}
              {refreshError ? (
                <span className="status-dot status-dot--warn" role="alert" title={refreshError}>
                  Sin actualizar
                </span>
              ) : null}
              {trends?.partial ? <span className="status-dot status-dot--warn">Lectura parcial</span> : null}
              <ApiUsagePanel />
              <DataHealthPanel />
              <button
                type="button"
                onClick={() => void connectAccount()}
                disabled={connecting || busy}
                className="btn btn-secondary"
                title="Abre Chrome para elegir la cuenta de Google de LALIGA Fantasy"
              >
                {connecting ? "Chrome…" : "Conectar"}
              </button>
              <button
                type="button"
                onClick={() => void refresh()}
                disabled={connecting || refreshing}
                className="btn btn-primary"
                title="Descarga una foto nueva de LALIGA y los scrapers"
              >
                {refreshing ? "Actualizando…" : "Actualizar"}
              </button>
            </div>
          </div>
          {refreshing ? (
            <div className="px-4 pb-3 md:px-7" role="status" aria-live="polite">
              <div className="mb-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px] text-muted">
                <span className="font-mono tabular-nums">{refreshLine}</span>
                <span className="font-mono tabular-nums">{refreshPct}%</span>
              </div>
              <div className="load-progress">
                <div className="load-progress__bar" style={{ width: `${Math.max(refreshPct, 4)}%` }} />
              </div>
            </div>
          ) : null}
          {connectMessage ? (
            <div className="px-4 pb-3 md:px-7" role={connecting ? "status" : "alert"} aria-live="polite">
              <div className="status-note">{connectMessage}</div>
            </div>
          ) : null}
        </header>

        <nav className="app-tabs scroll-thin" aria-label="Secciones">
          {SECTIONS.map((item) => (
            <Link
              key={item.label}
              href={withQuery(item.href)}
              className={isActive(pathname, item.href) ? "tab-link tab-link--active" : "tab-link"}
              aria-current={isActive(pathname, item.href) ? "page" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="app-page min-w-0 app-page--dock">{children}</div>

        <nav className="app-dock lg:hidden" aria-label="Navegación principal">
          {SECTIONS.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.label}
                href={withQuery(item.href)}
                className={active ? "app-dock__link app-dock__link--active" : "app-dock__link"}
                aria-current={active ? "page" : undefined}
              >
                <Icon name={item.label} />
                <span>{item.label === "Recomendaciones" ? "Inicio" : item.label}</span>
              </Link>
            );
          })}
        </nav>

        <footer className="mx-auto w-full max-w-[1240px] px-4 pb-24 text-xs leading-5 text-faint md:px-7 md:pb-8 lg:pb-8">
          Solo lectura. Las horas de cláusula salen de la API en Europe/Madrid. Pulsa Actualizar antes de decidir con
          dinero real.
        </footer>
      </div>
    </div>
  );
}

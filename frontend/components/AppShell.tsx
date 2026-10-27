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

type NavGroup = {
  id: string;
  label: string;
  hint: string;
  items: readonly NavItem[];
};

const GROUPS: readonly NavGroup[] = [
  {
    id: "hoy",
    label: "Hoy",
    hint: "Qué hacer antes del próximo cierre",
    items: [{ href: "/", label: "Hoy", title: "Hoy", hint: "Reloj, supervivencia y acciones del día" }],
  },
  {
    id: "equipo",
    label: "Mi Equipo",
    hint: "Once, dinero y cláusulas",
    items: [
      { href: "/once", label: "Once", title: "Once", hint: "Alineación óptima y huecos" },
      { href: "/cartera", label: "Cartera", title: "Cartera", hint: "Rentabilidad e historial de fichajes" },
      {
        href: "/clausulazos",
        label: "Cláusulas",
        title: "Cláusulas",
        hint: "Proteger, calendario, fichaje y confirmar",
      },
    ],
  },
  {
    id: "contexto",
    label: "Contexto",
    hint: "Mercado, rivales y modelo",
    items: [
      { href: "/mercado", label: "Mercado", title: "Mercado", hint: "Pujar, esperar o dejar pasar" },
      { href: "/rivales", label: "Rivales", title: "Rivales", hint: "Caja ajena y cláusulas" },
      { href: "/intel", label: "Intel", title: "Intel", hint: "Señales externas de la jornada" },
      {
        href: "/calibracion",
        label: "Calibración",
        title: "Calibración",
        hint: "Precisión del motor y tendencias",
      },
    ],
  },
] as const;

const SECTIONS = GROUPS.flatMap((group) => group.items);

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
  if (name === "Hoy") {
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="6.4" />
        <path d="M10 6.6V10l2.2 1.4" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "Cláusulas") {
    return (
      <svg {...common}>
        <rect x="4.5" y="8.5" width="11" height="8.5" rx="1.4" />
        <path d="M7 8.5V6.8a3 3 0 0 1 6 0V8.5" strokeLinecap="round" />
        <circle cx="10" cy="12.5" r="1.1" fill="currentColor" stroke="none" />
      </svg>
    );
  }
  if (name === "Cartera") {
    return (
      <svg {...common}>
        <path d="M4 7.5h12v8.5H4V7.5Z" strokeLinejoin="round" />
        <path d="M7 7.5V6a3 3 0 0 1 6 0v1.5" strokeLinecap="round" />
        <path d="M10 11.2v2.6" strokeLinecap="round" />
        <circle cx="10" cy="10.5" r="0.9" fill="currentColor" stroke="none" />
      </svg>
    );
  }
  if (name === "Once") {
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
  if (name === "Intel") {
    return (
      <svg {...common}>
        <path d="M4 14.5 8.2 9.6l2.6 2.4L16 6.2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M12.2 6.2H16V10" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "Calibración") {
    return (
      <svg {...common}>
        <path d="M4 15.5 7.5 11l2.5 2 6-6.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="14.5" cy="6.5" r="1.6" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="7" cy="7.2" r="2" />
      <circle cx="13.2" cy="8" r="1.7" />
      <path d="M3.6 15.2c.5-2 2-3.1 3.4-3.1s2.9 1.1 3.4 3.1" strokeLinecap="round" />
      <path d="M11.2 12.4c.8-.4 1.6-.5 2.2-.4 1.1.2 2 1.1 2.5 2.8" strokeLinecap="round" />
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
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
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
  const group = GROUPS.find((candidate) => candidate.items.some((item) => item.href === section.href));
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
            <p className="mt-1 text-[11px] text-[color:var(--sidebar-muted)]">Mesa de decisión</p>
          </div>
        </div>

        <nav className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1" aria-label="Secciones">
          {GROUPS.map((navGroup) => (
            <div key={navGroup.id} className="flex flex-col gap-1">
              <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--sidebar-muted)]">
                {navGroup.label}
              </p>
              {navGroup.items.map((item) => {
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
            </div>
          ))}
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
                <p className="eyebrow hidden sm:block">{group?.label ?? "Hoy"}</p>
                <h1 className="truncate text-lg font-semibold tracking-[-0.03em] text-ink md:text-xl">{section.title}</h1>
                <p className="hidden truncate text-sm text-muted sm:block">{section.hint}</p>
              </div>
            </div>

            <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
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
            <div
              className="px-4 pb-3 md:px-7"
              role={connecting ? "status" : "alert"}
              aria-live="polite"
            >
              <div className="status-note">{connectMessage}</div>
            </div>
          ) : null}
        </header>

        <nav className="app-tabs scroll-thin" aria-label="Secciones">
          {GROUPS.map((navGroup) => (
            <div key={navGroup.id} className="flex shrink-0 items-center gap-1">
              <span className="whitespace-nowrap px-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-faint">
                {navGroup.label}
              </span>
              {navGroup.items.map((item) => (
                <Link
                  key={item.label}
                  href={withQuery(item.href)}
                  className={isActive(pathname, item.href) ? "tab-link tab-link--active" : "tab-link"}
                  aria-current={isActive(pathname, item.href) ? "page" : undefined}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>

        <div className="app-page min-w-0">{children}</div>

        <footer className="mx-auto w-full max-w-[1240px] px-4 pb-8 text-xs leading-5 text-faint md:px-7">
          Solo lectura. Las horas de cláusula salen de la API en Europe/Madrid, con hora y minuto. Si la marca no viene,
          el tablero no inventa una hora. Las señales af_* de Analítica Fantasy no sustituyen al optimizador ni al bonus
          Relevo.
        </footer>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, type CSSProperties, type ReactNode } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { prefetchLaboratorio } from "@/lib/laboratorio/prefetch";
import { useNow } from "@/lib/core/useClock";
import { AvisosBell } from "@/components/AvisosBell";

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
    hint: "Qué comprar hoy y a qué precio",
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
    hint: "Clasificación y rivales",
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

const LABORATORIO: NavItem = { href: "/laboratorio", label: "Laboratorio", title: "Laboratorio", hint: "Auditoría del modelo y de los datos" };

function sectionFromPath(pathname: string): NavItem {
  if (pathname === LABORATORIO.href || pathname.startsWith(`${LABORATORIO.href}/`)) return LABORATORIO;
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
  const label = item.label === "Recomendaciones" ? "Inicio" : item.label;
  return (
    <Link href={href} className="dock-link" data-active={active ? "true" : undefined} aria-current={active ? "page" : undefined} aria-label={label} title={label}>
      <Icon name={item.label} />
    </Link>
  );
}

const DATE_FMT = new Intl.DateTimeFormat("es-ES", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Madrid" });

/** Fecha de hoy junto al título; vacía hasta montar para no romper la hidratación. */
function TodayStamp() {
  const now = useNow();
  if (!now) return null;
  return <span className="topbar-date truncate max-sm:hidden">{DATE_FMT.format(now)}</span>;
}

export function AppShell({ children }: { children: ReactNode }) {
  const {
    busy,
    refreshing,
    refreshLine,
    refreshPct,
    connecting,
    connectMessage,
    connectAccount,
    refresh,
    markShellReady,
    trends: dashTrends,
  } = useDashboard();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const section = sectionFromPath(pathname);
  const query = searchParams.toString();
  const withQuery = (href: string) => (query ? `${href}?${query}` : href);

  useEffect(() => {
    markShellReady();
  }, [markShellReady]);

  // Con la foto ya cargada y la pantalla quieta, deja precalentado el
  // Laboratorio: así al abrirlo cada pestaña sale al instante.
  const queryLeague = searchParams.get("league");
  const labLeague = dashTrends?.league_id || queryLeague;
  const trendsReady = Boolean(dashTrends);
  useEffect(() => {
    if (!trendsReady) return;
    const timer = window.setTimeout(() => prefetchLaboratorio(labLeague, queryLeague), 2500);
    return () => window.clearTimeout(timer);
  }, [trendsReady, labLeague, queryLeague]);

  // Atajo «R»: actualiza los datos sin buscar el botón (ignorado al escribir).
  const canRefresh = !connecting && !refreshing;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "r" || event.metaKey || event.ctrlKey || event.altKey || event.repeat) return;
      const el = event.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (!canRefresh) return;
      event.preventDefault();
      void refresh();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canRefresh, refresh]);

  // La recarga vive solo en Inicio, dentro del hero (RefreshChip). Aquí queda
  // el atajo «R» y la barra de progreso mientras descarga.
  const dockIndex = SECTIONS.findIndex((item) => isActive(pathname, item.href));
  const home = pathname === "/" || ["/equipo", "/mercado", "/clausulas", "/liga"].some((path) => pathname === path || pathname.startsWith(`${path}/`));

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="flex items-center gap-3 px-2 pb-5">
          <span className="brand-mark" aria-hidden="true">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo-mark.svg" alt="" width={28} height={28} />
          </span>
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
          <button
            type="button"
            onClick={() => void connectAccount()}
            disabled={connecting || busy}
            className="btn btn-ghost w-full justify-start px-0"
          >
            {connecting ? "Elige tu cuenta en Chrome…" : "Conectar cuenta"}
          </button>
          <AvisosBell className="btn btn-ghost mt-1 w-full justify-start px-0" />
        </div>
      </aside>

      <div className="app-frame">
        <header className={`app-topbar relative ${home ? "app-topbar--bare" : ""}`}>
          <div className="app-topbar__row" data-ui="topbar" hidden={home}>
            <div className="flex min-w-0 items-center gap-3">
              <span className="topbar-mark lg:hidden" aria-hidden="true">
                <Icon name={section.label === "Laboratorio" ? "Liga" : (section.label as SectionLabel)} />
              </span>
              <div className="min-w-0">
                <div className="flex min-w-0 items-baseline gap-2.5">
                  <h1 className="topbar-title truncate">{section.title}</h1>
                  <TodayStamp />
                </div>
                <p className="topbar-hint truncate">{section.hint}</p>
              </div>
            </div>
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
        <div className="app-page min-w-0 app-page--dock">
          {/* Clave por ruta: cada sección entra con un único fundido suave. */}
          <div key={pathname} className="page-in">
            {children}
          </div>
        </div>

        <nav
          className="dock lg:hidden"
          aria-label="Navegación principal"
          style={{ "--dock-i": Math.max(0, dockIndex) } as CSSProperties}
          data-has-active={dockIndex >= 0 ? "true" : undefined}
        >
          <span className="dock__ind" aria-hidden="true" />
          {SECTIONS.map((item) => (
            <DockLink key={item.label} item={item} active={isActive(pathname, item.href)} href={withQuery(item.href)} />
          ))}
        </nav>

        <div className="pb-24 lg:pb-8" aria-hidden="true" />
      </div>
    </div>
  );
}

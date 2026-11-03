"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { useNow } from "@/lib/core/useClock";

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

const HOUR = 3600;

const DATE_FMT = new Intl.DateTimeFormat("es-ES", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Madrid" });

/** Fecha de hoy junto al título; vacía hasta montar para no romper la hidratación. */
function TodayStamp() {
  const now = useNow();
  if (!now) return null;
  return <span className="topbar-date truncate max-sm:hidden">{DATE_FMT.format(now)}</span>;
}

/**
 * Frescura de los datos y botón Actualizar en una sola pastilla. El punto pasa
 * de verde (< 1 h) a ámbar (< 6 h) y a rojo con pulso cuando conviene descargar.
 */
function Freshness({
  ageSeconds,
  age,
  refreshing,
  busy,
  pct,
  error,
  disabled,
  onRefresh,
  onOpen,
  open,
}: {
  ageSeconds: number | null;
  age: string;
  refreshing: boolean;
  busy: boolean;
  pct: number;
  error: boolean;
  disabled: boolean;
  onRefresh: () => void;
  onOpen: () => void;
  open: boolean;
}) {
  const [justDone, setJustDone] = useState(false);
  const [wasRefreshing, setWasRefreshing] = useState(refreshing);
  if (wasRefreshing !== refreshing) {
    setWasRefreshing(refreshing);
    if (!refreshing && !error) setJustDone(true);
  }
  useEffect(() => {
    if (!justDone) return;
    const id = window.setTimeout(() => setJustDone(false), 2400);
    return () => window.clearTimeout(id);
  }, [justDone]);

  const old = ageSeconds === null || ageSeconds >= 6 * HOUR;
  const state = refreshing || busy ? "busy" : error ? "error" : justDone ? "done" : old ? "old" : ageSeconds >= HOUR ? "aging" : "fresh";
  const color = {
    busy: "#38bdf8",
    error: "#ff7d66",
    done: "#34d399",
    old: "#ff7d66",
    aging: "#f5b544",
    fresh: "#34d399",
  }[state];
  const label = refreshing
    ? `Actualizando · ${pct}%`
    : busy
      ? `Cargando · ${pct}%`
      : error
        ? "Falló la descarga"
        : justDone
          ? "Actualizado ahora"
          : age
            ? (
                <>
                  <span className="max-[420px]:hidden">Actualizado </span>
                  {age}
                </>
              )
            : "Sin datos";

  return (
    <div className={`fresh fresh--${state}`} data-ui="freshness" data-state={state}>
      <button type="button" className="fresh__label" onClick={onOpen} aria-haspopup="dialog" aria-expanded={open} title="Ver detalle de los datos">
        <span className="fresh__dot" style={{ color }} aria-hidden="true" />
        <span aria-live="polite">{label}</span>
      </button>
      <kbd className="fresh__kbd max-md:hidden" title="Pulsa R para actualizar">R</kbd>
      <button
        type="button"
        className="fresh__btn"
        onClick={onRefresh}
        disabled={disabled}
        aria-label={error ? "Reintentar la descarga" : "Actualizar datos"}
        aria-keyshortcuts="R"
        title="Descarga una foto nueva de LALIGA y los scrapers (R)"
        data-ui="refresh"
        data-progress={refreshing || busy ? "true" : undefined}
        style={{ "--p": `${Math.max(0, Math.min(100, pct))}%`, "--c": color } as CSSProperties}
      >
        {justDone && !refreshing ? (
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-[#34d399]" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
            <path d="M3.4 8.4 6.3 11.3 12.6 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg viewBox="0 0 20 20" className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M16.2 10a6.2 6.2 0 1 1-1.6-4.1" strokeLinecap="round" />
            <path d="M16.4 3.6v3.2h-3.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const {
    trends,
    leagueName,
    busy,
    refreshing,
    refreshError,
    photoAge,
    photoAgeSeconds,
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
  const labHref = (tab?: string) => {
    const params = new URLSearchParams(query);
    if (tab) params.set("tab", tab);
    const text = params.toString();
    return text ? `/laboratorio?${text}` : "/laboratorio";
  };

  useEffect(() => {
    markShellReady();
  }, [markShellReady]);

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

  // En Inicio no hay barra superior: la recarga vive en la barra lateral
  // (escritorio) y en un botón flotante sobre el dock (móvil).
  const home = pathname === "/" || pathname === "/equipo" || pathname.startsWith("/equipo/");
  const freshness = (
    <Freshness
      ageSeconds={photoAgeSeconds}
      age={photoAge}
      refreshing={refreshing}
      busy={busy}
      pct={refreshing ? refreshPct : progress.pct}
      error={Boolean(refreshError)}
      disabled={connecting || refreshing}
      onRefresh={() => void refresh()}
      onOpen={() => setToolsOpen(true)}
      open={toolsOpen}
    />
  );

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
          {home ? <div className="side-fresh mt-3">{freshness}</div> : null}
          <Link
            href={labHref()}
            className={`mt-3 block text-sm no-underline ${pathname.startsWith("/laboratorio") ? "text-white" : "text-[color:var(--sidebar-muted)] hover:text-white"}`}
          >
            Laboratorio
          </Link>
          <button
            type="button"
            onClick={() => void connectAccount()}
            disabled={connecting || busy}
            className="btn btn-ghost mt-1 w-full justify-start px-0"
          >
            {connecting ? "Elige tu cuenta en Chrome…" : "Conectar cuenta"}
          </button>
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
            {freshness}
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
              aria-label="Foto y conexión"
              className="card w-full max-w-sm p-4"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-[#8B9EB0]">Foto</p>
                  <p className="mt-1 font-mono text-xs text-[#F0F6FC]">{photoLine}</p>
                  {refreshError ? <p className="mt-1 text-xs text-[#FC734D]">{refreshError}</p> : null}
                  {trends?.partial ? <p className="mt-1 text-xs text-[#FC734D]">Lectura parcial</p> : null}
                  <p className="mt-3 text-xs leading-5 text-[#8B9EB0]">
                    Solo lectura. Las horas de cláusula salen de la API en Europe/Madrid. Actualiza antes de decidir con dinero real.
                  </p>
                </div>
                <button type="button" className="btn btn-secondary !px-2.5 !py-1 text-xs" onClick={() => setToolsOpen(false)}>
                  Cerrar
                </button>
              </div>
              <div className="flex flex-col items-start gap-2">
                <Link
                  href={labHref("datos")}
                  onClick={() => setToolsOpen(false)}
                  className="btn btn-secondary w-full no-underline"
                  title="Frescura de los datos, consumo de API, calibración y señales"
                >
                  Laboratorio · datos y API
                </Link>
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

        {home ? <div className="fab-fresh lg:hidden">{freshness}</div> : null}

        <nav
          className="fixed inset-x-5 bottom-3 z-50 flex h-14 items-stretch overflow-hidden rounded-2xl border border-white/[0.08] bg-[#060E14]/90 backdrop-blur-2xl lg:hidden"
          aria-label="Navegación principal"
        >
          {SECTIONS.map((item) => (
            <DockLink key={item.label} item={item} active={isActive(pathname, item.href)} href={withQuery(item.href)} />
          ))}
        </nav>

        <div className="pb-24 lg:pb-8" aria-hidden="true" />
      </div>
    </div>
  );
}

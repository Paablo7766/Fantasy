"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { eur, eurShort, points } from "@/lib/core/format";
import type { PlanFichajeAccion, PlanFichajes } from "@/lib/types";

const MAX_STEPS = 4;
const STORAGE_PREFIX = "fantasy:hoja-ruta:";

type Step = {
  key: string;
  kind: "vende" | "escaparate" | "puja" | "clausula";
  text: string;
  note: string | null;
  /** Importe exacto que se copia al tocarlo. */
  copy: number | null;
  action: PlanFichajeAccion;
};

/** Día de mercado en hora de Madrid: la lista de tareas se reinicia con él. */
function marketDay(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

const listeners = new Set<() => void>();
/** Respaldo si el navegador no deja usar localStorage: vale para esta sesión. */
const memory = new Map<string, string>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function snapshot(): string {
  const key = STORAGE_PREFIX + marketDay();
  try {
    return window.localStorage.getItem(key) ?? memory.get(key) ?? "[]";
  } catch {
    return memory.get(key) ?? "[]";
  }
}

function serverSnapshot(): string {
  return "[]";
}

function writeDone(done: string[]) {
  const key = STORAGE_PREFIX + marketDay();
  const raw = JSON.stringify(done);
  memory.set(key, raw);
  try {
    window.localStorage.setItem(key, raw);
  } catch {
    /* sin almacenamiento: la casilla solo vale para esta sesión */
  }
  listeners.forEach((listener) => listener());
}

function parseDone(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function stepFrom(action: PlanFichajeAccion): Step | null {
  const tipo = (action.tipo || "").toUpperCase();
  const name = action.nombre || "este jugador";
  const euros = typeof action.euros === "number" && action.euros > 0 ? Math.round(action.euros) : null;
  const key = `${tipo}:${action.player_id || name}`;
  if (tipo === "VENDE" || tipo === "VENDER HOY") {
    return {
      key,
      kind: "vende",
      text: `Vende hoy a ${name}`,
      note: euros ? `Acepta la oferta de ${eurShort(euros)} de LaLiga` : "Acepta la oferta de LaLiga",
      copy: null,
      action,
    };
  }
  if (tipo === "ESCAPARATE") {
    return {
      key,
      kind: "escaparate",
      text: `Pon en el mercado a ${name}`,
      note: (action.detalle || "").includes("Para tener oferta")
        ? "Ponlo en venta hoy. Mañana véndelo solo si ganas la puja"
        : "Solo para recibir oferta, no lo vendas hoy",
      copy: null,
      action,
    };
  }
  if (tipo === "PUJA" && euros) {
    return { key, kind: "puja", text: `Puja ${eurShort(euros)} por ${name}`, note: "Toca la cifra para copiarla exacta", copy: euros, action };
  }
  if (tipo === "CLAUSULAZO" && euros) {
    return { key, kind: "clausula", text: `Paga la cláusula de ${name}`, note: `${eurShort(euros)}, toca la cifra para copiarla`, copy: euros, action };
  }
  return null;
}

/** Lo que mueve caja o puntos va primero; el escaparate solo avisa y no pasa de MAX_SHOWCASE. */
const ORDER: Record<Step["kind"], number> = { vende: 0, escaparate: 1, puja: 2, clausula: 3 };
const MAX_SHOWCASE = 1;

export function buildSteps(fichajes: PlanFichajes | null | undefined): { steps: Step[]; rest: number } {
  const acciones = Array.isArray(fichajes?.acciones) ? fichajes.acciones : [];
  const seen = new Set<string>();
  const all: Step[] = [];
  for (const action of acciones) {
    if (action.momento && action.momento !== "hoy") continue;
    const step = stepFrom(action);
    if (!step || seen.has(step.key)) continue;
    seen.add(step.key);
    all.push(step);
  }
  all.sort((a, b) => ORDER[a.kind] - ORDER[b.kind]);
  let showcase = 0;
  const steps = all
    .filter((step) => step.kind !== "escaparate" || ++showcase <= MAX_SHOWCASE)
    .slice(0, MAX_STEPS);
  return { steps, rest: all.length - steps.length };
}

function Details({ step, fichajes }: { step: Step; fichajes: PlanFichajes | null | undefined }) {
  const { action } = step;
  const lines: string[] = [];
  if (typeof action.mejora_neta === "number") lines.push(`Mejora neta del once: ${action.mejora_neta >= 0 ? "+" : ""}${points(action.mejora_neta)} xP`);
  if (typeof action.prevision_7d_pct === "number") {
    lines.push(`Previsión a 7 días: ${action.prevision_7d_pct >= 0 ? "+" : ""}${action.prevision_7d_pct.toLocaleString("es-ES", { maximumFractionDigits: 1 })}%`);
  }
  if (step.kind === "puja" && typeof action.puja_anti_pizarra === "number" && typeof action.puja_pizarra === "number") {
    lines.push(
      `Demanda alta: La Pizarra pediría ${eurShort(action.puja_pizarra)}; esta cifra la supera en ${eur(action.diferencial_anti_pizarra_eur ?? 0)} para ganar los empates.`,
    );
  }
  if (step.kind === "puja" || step.kind === "clausula") {
    const peaje = fichajes?.penalizacion_liquidez;
    const dias = fichajes?.dias_al_cierre;
    if (typeof peaje === "number" && typeof dias === "number") {
      lines.push(
        `Peaje de liquidez: ${peaje.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} pts/M€ · faltan ${dias.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días`,
      );
    }
  }
  if (action.detalle) lines.push(action.detalle);
  if (!lines.length) lines.push("Sin más datos: la acción sale directa del plan de hoy.");
  return (
    <ul className="border-t border-white/[0.06] px-4 pb-3.5 pt-3 text-[12.5px] leading-5 text-white/55">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

export function HojaDeRuta({
  fichajes,
  loading,
}: {
  fichajes: PlanFichajes | null | undefined;
  loading: boolean;
}) {
  const { steps, rest } = useMemo(() => buildSteps(fichajes), [fichajes]);
  const raw = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const done = useMemo(() => parseDone(raw), [raw]);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    };
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 1800);
  }, []);

  const toggle = (key: string) => {
    writeDone(done.includes(key) ? done.filter((item) => item !== key) : [...done, key]);
  };

  const copy = async (amount: number) => {
    try {
      await navigator.clipboard.writeText(String(amount));
      showToast(`Copiado: ${eur(amount)}`);
    } catch {
      showToast(`No se pudo copiar. Cifra: ${eur(amount)}`);
    }
  };

  const finished = steps.filter((step) => done.includes(step.key)).length;

  return (
    <section className="home-glass overflow-hidden" aria-label="Hoja de ruta de hoy">
      <div className="flex items-baseline justify-between gap-3 px-4 pb-2 pt-4">
        <h2 className="text-[11.5px] font-semibold uppercase tracking-[0.14em] text-white/55">Hoja de ruta de hoy</h2>
        {steps.length ? (
          <span className="text-[12px] tabular-nums text-white/40">
            {finished}/{steps.length} hechas{rest > 0 ? ` · ${rest} más abajo` : ""}
          </span>
        ) : null}
      </div>

      {loading && !fichajes ? (
        <div className="mx-4 mb-4 h-20 animate-pulse rounded-2xl bg-white/5" aria-hidden="true" />
      ) : steps.length ? (
        <ol className="divide-y divide-white/[0.06]">
          {steps.map((step, index) => {
            const checked = done.includes(step.key);
            const open = openKey === step.key;
            return (
              <li key={step.key} className={checked ? "opacity-50" : ""}>
                <div className="flex items-center gap-3 px-4 py-3">
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={checked}
                    aria-label={`Marcar como hecho: ${step.text}`}
                    onClick={() => toggle(step.key)}
                    className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border transition-colors ${
                      checked ? "border-[#34D399] bg-[#34D399]/20 text-[#34D399]" : "border-white/25 text-transparent hover:border-white/50"
                    }`}
                  >
                    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
                      <path d="M3.4 8.4 6.3 11.3 12.6 5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => setOpenKey(open ? null : step.key)}
                    aria-expanded={open}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span className={`block text-[15px] font-medium leading-tight text-white ${checked ? "line-through" : ""}`}>
                      <span className="mr-1.5 tabular-nums text-white/40">{index + 1}.</span>
                      {step.text}
                    </span>
                    {step.note ? <span className="mt-0.5 block text-[12.5px] leading-4 text-white/50">{step.note}</span> : null}
                  </button>
                  {step.copy !== null ? (
                    <button
                      type="button"
                      onClick={() => void copy(step.copy as number)}
                      aria-label={`Copiar ${eur(step.copy)}`}
                      className="shrink-0 rounded-xl border border-white/15 bg-white/[0.06] px-3 py-1.5 text-[14px] font-semibold tabular-nums text-white transition-colors hover:bg-white/[0.12] active:scale-95"
                    >
                      {eurShort(step.copy)}
                    </button>
                  ) : null}
                </div>
                {open ? <Details step={step} fichajes={fichajes} /> : null}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="px-4 pb-4 text-[14px] text-white/55">Nada que ejecutar hoy. Revisa de nuevo tras el próximo mercado.</p>
      )}

      <div
        role="status"
        aria-live="polite"
        className={`pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center transition-opacity duration-200 ${toast ? "opacity-100" : "opacity-0"}`}
      >
        {toast ? (
          <span className="rounded-full border border-white/15 bg-[#120C09]/95 px-4 py-2 text-[13px] font-medium tabular-nums text-white shadow-lg">
            {toast}
          </span>
        ) : null}
      </div>
    </section>
  );
}

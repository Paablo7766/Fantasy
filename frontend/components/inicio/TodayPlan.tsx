"use client";

import { BlurText } from "@/components/ui/BlurText";
import { RollingNumber } from "@/components/ui/RollingNumber";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import { eur, eurShort, points, titularShare } from "@/lib/core/format";
import { signedPoints } from "@/lib/inicio/hoy";
import { factsFor, photoFor, type PhotoIndex, type PlayerIndex } from "@/lib/core/photoIndex";
import { Avatar, Chevron, Collapse, FactGrid, Tag, type Fact } from "@/components/inicio/ui";
import type { PlanFichajeAccion, PlanFichajes, PlanPayload, SquadsPayload } from "@/lib/types";

// ── Casillas hechas: se guardan por día de mercado (hora de Madrid) ──────────

const STORAGE_PREFIX = "fantasy:hoja-ruta:";

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

// ── Pasos del plan ───────────────────────────────────────────────────────────

type Kind = "vende" | "escaparate" | "puja" | "clausula" | "busca";

const KIND: Record<Kind, { label: string; color: string }> = {
  vende: { label: "Vender", color: "var(--ini-mint)" },
  escaparate: { label: "Escaparate", color: "var(--ini-amber)" },
  puja: { label: "Pujar", color: "var(--ini-sky)" },
  clausula: { label: "Clausulazo", color: "var(--ini-violet)" },
  busca: { label: "Buscar", color: "rgba(255,255,255,0.55)" },
};

/** Lo que mueve caja va primero: vender, pujar y clausular; el escaparate solo prepara. */
const ORDER: Record<Kind, number> = { vende: 0, puja: 1, clausula: 2, escaparate: 3, busca: 4 };

type Step = {
  key: string;
  kind: Kind;
  name: string;
  position: string | null;
  imageUrl: string | null;
  amount: number | null;
  note: string | null;
  later: boolean;
  action: PlanFichajeAccion;
  href: string;
  guide: string;
};

function kindOf(tipo: string, etiqueta?: string | null): Kind {
  if (etiqueta === "CLAUSULAR") return "clausula";
  if (etiqueta === "PUJAR") return "puja";
  if (tipo === "VENDE" || tipo === "VENDER HOY") return "vende";
  if (tipo === "ESCAPARATE") return "escaparate";
  if (tipo === "CLAUSULAZO") return "clausula";
  if (tipo === "BUSCA") return "busca";
  return "puja";
}

function pctText(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toLocaleString("es-ES", { maximumFractionDigits: 0 })}%`;
}

function stepFrom(action: PlanFichajeAccion, photos: PhotoIndex): Step {
  const tipo = (action.tipo || "PUJA").toUpperCase();
  const kind = kindOf(tipo, action.etiqueta);
  const conditional = action.momento === "condicional";
  const euros = typeof action.euros === "number" && action.euros !== 0 ? Math.abs(Math.round(action.euros)) : null;
  const impulso = (action.impulso || "").toUpperCase();
  const position = action.posicion ? action.posicion.slice(0, 3).toUpperCase() : null;
  const name = kind === "busca" ? `Buscar ${action.posicion ? `un ${action.posicion}` : "un hueco"}` : action.nombre || "Jugador";

  let note: string | null = position;
  if (conditional) note = "Solo si ganas la puja";
  else if (kind === "vende") note = "Acepta la oferta de LaLiga";
  else if (kind === "escaparate")
    note = (action.detalle || "").includes("Para tener oferta") ? "Mañana, véndelo solo si ganas la puja" : "Para recibir oferta, no lo vendas hoy";
  else if (impulso === "MUST-BUY") note = "Imprescindible";
  else if (impulso === "CHOLLO") note = typeof action.prevision_7d_pct === "number" ? `Chollo · ${pctText(action.prevision_7d_pct)} en 7 días` : "Chollo";

  const toWallet = kind === "vende" || kind === "escaparate" || conditional;
  return {
    key: `${tipo}:${action.player_id || action.nombre || action.posicion || ""}`,
    kind: conditional ? "vende" : kind,
    name,
    position,
    imageUrl: kind === "busca" ? null : photoFor(photos, action.player_id, action.nombre),
    amount: kind === "escaparate" ? null : euros,
    note,
    later: action.momento === "luego" || conditional,
    action,
    href: toWallet ? "/equipo?tab=cartera" : kind === "clausula" ? "/clausulas" : "/mercado",
    guide: toWallet ? "Cartera" : kind === "clausula" ? "Cláusulas" : "Mercado",
  };
}

function buildSteps(fichajes: PlanFichajes | null | undefined, photos: PhotoIndex) {
  const seen = new Set<string>();
  const all: Step[] = [];
  for (const action of fichajes?.acciones || []) {
    const step = stepFrom(action, photos);
    if (seen.has(step.key)) continue;
    seen.add(step.key);
    all.push(step);
  }
  all.sort((a, b) => ORDER[a.kind] - ORDER[b.kind]);
  return { today: all.filter((step) => !step.later), later: all.filter((step) => step.later) };
}

function stepFacts(step: Step, info: ReturnType<typeof factsFor>, fichajes: PlanFichajes | null | undefined, rivalsWithCash: (amount: number | null) => number | null): Fact[] {
  const { action, kind, amount } = step;
  const rows: Fact[] = [];
  if (kind === "vende" || kind === "escaparate") {
    const share = titularShare(info?.p_titular);
    if (share !== null) rows.push({ label: "Titular", value: `${Math.round(share * 100)}%` });
    if (typeof info?.tu_once_pierde_sin_el === "number") rows.push({ label: "Tu once pierde", value: `−${points(Math.abs(info.tu_once_pierde_sin_el))} pts`, tone: "var(--ini-red)" });
  } else if (kind === "clausula") {
    if (info?.owner) rows.push({ label: "Propietario", value: info.owner });
    if (typeof info?.valor_justo === "number") {
      rows.push({ label: "Valor justo", value: eurShort(info.valor_justo) });
      if (amount) {
        const margin = (info.valor_justo / amount - 1) * 100;
        rows.push({ label: "Margen", value: `${margin >= 0 ? "+" : "−"}${Math.abs(Math.round(margin))}%`, tone: margin >= 0 ? "var(--ini-mint)" : "var(--ini-red)" });
      }
    }
  } else if (kind === "puja") {
    if (typeof info?.market_value === "number") rows.push({ label: "Valor de mercado", value: eurShort(info.market_value) });
    const rivals = rivalsWithCash(amount);
    if (rivals !== null) rows.push({ label: "Rivales que pueden pujarlo", value: String(rivals) });
  }
  if (typeof action.mejora_neta === "number") rows.push({ label: "Mejora del once", value: `${signedPoints(action.mejora_neta)} pts`, tone: action.mejora_neta >= 0 ? "var(--ini-mint)" : "var(--ini-red)" });
  else if (typeof action.jornada === "number") rows.push({ label: "Puntos esperados", value: `${points(action.jornada)} pts` });
  if (typeof action.prevision_7d_pct === "number") rows.push({ label: "Previsión 7 días", value: pctText(action.prevision_7d_pct), tone: action.prevision_7d_pct >= 0 ? "var(--ini-mint)" : "var(--ini-red)" });
  if ((kind === "puja" || kind === "clausula") && typeof fichajes?.penalizacion_liquidez === "number") {
    rows.push({ label: "Peaje de liquidez", value: `${fichajes.penalizacion_liquidez.toLocaleString("es-ES", { maximumFractionDigits: 2 })} pts/M€` });
  }
  return rows;
}

// Puja competitiva de liga: un escalón más si quien nos ganó las subastas pagó por encima de nuestra cifra.
function withCompetitiva(text: string | null, action: PlanFichajeAccion): string | null {
  if (typeof action.puja_competitiva_liga !== "number") return text;
  const pct = typeof action.sobrepuja_liga_pct === "number" ? ` (+${action.sobrepuja_liga_pct.toLocaleString("es-ES", { maximumFractionDigits: 1 })} % de sobrepuja media en tus subastas perdidas)` : "";
  const extra = `Puja competitiva de liga: ${eurShort(action.puja_competitiva_liga)}${pct}. Dentro del techo de rentabilidad.`;
  return text ? `${text} ${extra}` : extra;
}

function stepReason(step: Step): string | null {
  const { action } = step;
  if (step.kind === "puja" && typeof action.puja_anti_pizarra === "number" && typeof action.puja_pizarra === "number") {
    const extra = `Supera en ${eur(action.diferencial_anti_pizarra_eur ?? 0)} a la puja de La Pizarra (${eurShort(action.puja_pizarra)}) para ganar los empates.`;
    const base = action.detalle ? `${action.detalle} ${extra}` : extra;
    return withCompetitiva(base, action);
  }
  return withCompetitiva(action.detalle || null, action);
}

// ── Componentes ──────────────────────────────────────────────────────────────

function StepRow({
  step,
  index,
  checkable,
  done,
  open,
  onToggleDone,
  onToggleOpen,
  onCopy,
  facts,
  reason,
}: {
  step: Step;
  index: number;
  checkable: boolean;
  done: boolean;
  open: boolean;
  onToggleDone: () => void;
  onToggleOpen: () => void;
  onCopy: (amount: number) => void;
  facts: Fact[];
  reason: string | null;
}) {
  const meta = KIND[step.kind];
  // Al marcar (no al desmarcar ni al cargar ya marcado): pulso en la casilla.
  const [pop, setPop] = useState(0);
  useEffect(() => {
    if (!pop) return;
    const id = window.setTimeout(() => setPop(0), 700);
    return () => window.clearTimeout(id);
  }, [pop]);
  const copyable = step.amount !== null && (step.kind === "puja" || step.kind === "clausula");
  return (
    <li className="ini-row ini-in" data-done={done} data-pop={pop ? "true" : undefined} style={{ "--i": index + 2 } as CSSProperties}>
      <div className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
        {checkable ? (
          <button
            type="button"
            role="checkbox"
            aria-checked={done}
            aria-label={`Marcar como hecho: ${step.name}`}
            onClick={() => {
              if (!done) setPop((n) => n + 1);
              onToggleDone();
            }}
            className="ini-check"
          >
            <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
              <path d="M3.4 8.4 6.3 11.3 12.6 5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ) : null}
        <button type="button" onClick={onToggleOpen} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <Avatar name={step.name} imageUrl={step.imageUrl} color={meta.color} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[15px] font-medium leading-tight text-white">
              <span className="ini-strike">{step.name}</span>
            </span>
            <span className="mt-1 flex min-w-0 items-center gap-2">
              <Tag label={meta.label} color={meta.color} />
              {step.note ? <span className="truncate text-[12px] text-white/45">{step.note}</span> : null}
            </span>
          </span>
        </button>
        {copyable ? (
          <button type="button" onClick={() => onCopy(step.amount as number)} className="ini-amount" aria-label={`Copiar ${eur(step.amount)}`} title="Copiar la cifra exacta">
            {eurShort(step.amount)}
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-white/40 max-sm:hidden" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <rect x="5" y="5" width="8" height="8" rx="2" />
              <path d="M3 10.5V4.5A1.5 1.5 0 0 1 4.5 3h6" strokeLinecap="round" />
            </svg>
          </button>
        ) : step.amount !== null ? (
          <span className="shrink-0 text-[15px] font-semibold tabular-nums" style={{ color: step.kind === "vende" ? "var(--ini-mint)" : "#fff" }}>
            {step.kind === "vende" ? "+" : ""}
            {eurShort(step.amount)}
          </span>
        ) : null}
        <button type="button" onClick={onToggleOpen} aria-label={open ? "Ocultar detalle" : "Ver detalle"} className="-mr-1 grid h-8 w-6 place-items-center max-sm:hidden">
          <Chevron open={open} />
        </button>
      </div>
      <Collapse open={open}>
        <div className={`px-4 pb-4 sm:px-5 ${checkable ? "pl-[6.25rem] sm:pl-[6.5rem]" : "pl-[4.25rem] sm:pl-[4.5rem]"}`}>
          <FactGrid facts={facts} />
          {reason ? <p className="mt-3 text-[13px] leading-5 text-white/55">{reason}</p> : null}
          <Link href={step.href} className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-[var(--ini-copper)] hover:underline">
            Abrir en {step.guide} <span aria-hidden="true">→</span>
          </Link>
        </div>
      </Collapse>
    </li>
  );
}

function Disclosure({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  if (!count) return null;
  return (
    <div className="ini-disclosure">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left sm:px-5">
        <span className="text-[13px] font-medium text-white/60">
          {title} <span className="ml-1 tabular-nums text-white/35">{count}</span>
        </span>
        <Chevron open={open} />
      </button>
      <Collapse open={open}>{children}</Collapse>
    </div>
  );
}

/**
 * Plan de hoy: el veredicto, el progreso y cada acción en una fila con su
 * cifra. Fusiona la antigua hoja de ruta y la mesa de fichajes.
 */
export function TodayPlan({
  plan,
  squads,
  loading,
  photos,
  facts,
}: {
  plan: PlanPayload | null;
  squads: SquadsPayload | null;
  loading: boolean;
  photos: PhotoIndex;
  facts: PlayerIndex;
}) {
  const fichajes = plan?.plan_fichajes;
  const { today, later } = useMemo(() => buildSteps(fichajes, photos), [fichajes, photos]);
  const radar = fichajes?.en_radar || [];
  const alternativas = fichajes?.alternativas_liquidez || [];
  const presupuesto = fichajes?.presupuesto ?? null;
  const comparativa = fichajes?.comparativa ?? null;
  const raw = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const done = useMemo(() => parseDone(raw), [raw]);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 1800);
  }, []);

  const copy = async (amount: number) => {
    try {
      await navigator.clipboard.writeText(String(amount));
      showToast(`Copiado · ${eur(amount)}`);
    } catch {
      showToast(`No se pudo copiar · ${eur(amount)}`);
    }
  };

  // Rivales que pueden pujar esa cifra: caja + crédito del 20 % de su plantilla (una puja admite deuda).
  const rivalsWithCash = (amount: number | null) => {
    if (amount === null || !squads?.rivals?.length) return null;
    return squads.rivals.filter((rival) => {
      if (typeof rival.cash_eur !== "number") return false;
      const credito = typeof rival.market_value_total === "number" ? rival.market_value_total * 0.2 : 0;
      return rival.cash_eur + credito >= amount;
    }).length;
  };

  const checkable = today.filter((step) => step.kind !== "busca");
  const finished = checkable.filter((step) => done.includes(step.key)).length;
  const allDone = checkable.length > 0 && finished === checkable.length;
  const delta = fichajes?.mejora_puntos_jornada;
  const estado = fichajes?.estado_calculo ?? null;
  const failed = !!estado && !["ok", "sin_cambios"].includes(estado);
  const verdict = allDone
    ? "Todo listo por hoy"
    : today.length
      ? fichajes?.veredicto || "Hazlo hoy"
      : failed
        ? "El cálculo no terminó"
        : "Hoy toca esperar";
  const income = today.filter((s) => s.kind === "vende").reduce((t, s) => t + (s.amount || 0), 0);
  // Crédito que el plan usa por encima de la caja: deuda real hasta la ruta de salida.
  const saldoFinal = typeof fichajes?.saldo_al_final === "number" ? fichajes.saldo_al_final : null;
  const credit = Math.max(
    typeof presupuesto?.credito_paron === "number" ? presupuesto.credito_paron : 0,
    saldoFinal !== null && saldoFinal < 0 ? -saldoFinal : 0,
  );
  const saleDay = fichajes?.paron?.ruta_salida?.dia_venta || null;
  const spend = today.filter((s) => s.kind === "puja" || s.kind === "clausula").reduce((t, s) => t + (s.amount || 0), 0);

  const renderRow = (step: Step, index: number, canCheck: boolean) => (
    <StepRow
      key={step.key}
      step={step}
      index={index}
      checkable={canCheck && step.kind !== "busca"}
      done={canCheck && done.includes(step.key)}
      open={openKey === step.key}
      onToggleDone={() => writeDone(done.includes(step.key) ? done.filter((k) => k !== step.key) : [...done, step.key])}
      onToggleOpen={() => setOpenKey(openKey === step.key ? null : step.key)}
      onCopy={(amount) => void copy(amount)}
      facts={stepFacts(step, step.kind === "busca" ? null : factsFor(facts, step.action.player_id, step.action.nombre || step.name), fichajes, rivalsWithCash)}
      reason={stepReason(step)}
    />
  );

  if (loading && !plan) return <div className="ini-skel h-72" aria-hidden="true" />;

  return (
    <section className="ini-card ini-in" style={{ "--i": 1 } as CSSProperties} aria-label="Plan de hoy">
      <header className="px-5 pb-4 pt-5">
        <div className="flex items-center justify-between gap-3">
          <p className="ini-eyebrow">Plan de hoy</p>
          {checkable.length ? (
            <p className="text-[12px] tabular-nums text-white/45">
              <span className="font-medium text-white">
                <RollingNumber value={finished} format={(v) => String(Math.round(v))} duration={400} />
              </span>{" "}
              de {checkable.length} hechas
            </p>
          ) : null}
        </div>
        <div className="mt-2 flex items-center gap-2.5">
          {allDone ? (
            <span className="ini-done-pop grid h-7 w-7 place-items-center rounded-full bg-[var(--ini-mint)] text-[#04110c]" aria-hidden="true">
              <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.4">
                <path d="M3.4 8.4 6.3 11.3 12.6 5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
          ) : null}
          <h2 className="text-[28px] font-semibold leading-tight tracking-[-0.03em] text-white">
            <BlurText text={verdict} delay={120} />
          </h2>
        </div>
        <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[13px] tabular-nums text-white/50">
          {typeof delta === "number" && Math.abs(delta) >= 0.05 ? (
            <span>
              <span style={{ color: delta > 0 ? "var(--ini-mint)" : "var(--ini-red)" }} className="font-medium">
                <RollingNumber value={delta} format={(v) => `${signedPoints(v)} pts`} memoKey="plan:mejora" />
              </span>{" "}
              en tu once
            </span>
          ) : null}
          {income > 0 ? (
            <span>
              Ingresas <RollingNumber value={income} format={eurShort} memoKey="plan:ingresos" />
            </span>
          ) : null}
          {spend > 0 ? (
            <span>
              Inviertes <RollingNumber value={spend} format={eurShort} memoKey="plan:inversion" />
            </span>
          ) : null}
          {presupuesto && presupuesto.gasto_pujas + presupuesto.gasto_clausulas > 0 ? (
            <span className="w-full text-[12px] text-white/40">
              Lo pagas con caja {eurShort(presupuesto.caja)}
              {presupuesto.ventas_hoy > 0 ? ` + ventas de hoy ${eurShort(presupuesto.ventas_hoy)}` : ""}
              {presupuesto.ventas_si_ganas > 0 ? ` + ventas solo si ganas ${eurShort(presupuesto.ventas_si_ganas)}` : ""}
              {credit > 0
                ? ` + crédito ${eurShort(credit)} · deuda planificada −${eurShort(credit)}: vende antes del ${saleDay || "cierre"}`
                : ` · sobran ${eurShort(presupuesto.holgura)} · sin usar crédito`}
            </span>
          ) : null}
          {!today.length ? (
            failed ? (
              <span style={{ color: "var(--ini-red)" }}>{fichajes?.estado_detalle || "El plan no se pudo calcular. Pulsa Actualizar."}</span>
            ) : (
              <span>Ningún movimiento mejora tu once con los datos de ahora.</span>
            )
          ) : null}
        </p>
        {checkable.length ? (
          <div className="ini-bar mt-4" data-full={allDone} role="progressbar" aria-valuemin={0} aria-valuemax={checkable.length} aria-valuenow={finished}>
            <span style={{ width: `${(finished / checkable.length) * 100}%` }} />
          </div>
        ) : null}
      </header>

      {today.length ? <ol className="ini-divide">{today.map((step, i) => renderRow(step, i, true))}</ol> : null}

      {later.length || radar.length || alternativas.length || comparativa ? (
        <div className="pb-1">
          <Disclosure title="Después" count={later.length}>
            <ol className="ini-divide border-t border-[var(--ini-line)]">{later.map((step, i) => renderRow(step, i, false))}</ol>
          </Disclosure>
          {comparativa?.completo && comparativa?.prudente ? (
            <Disclosure title="Comparar con el plan prudente" count={1}>
              <div className="grid gap-3 border-t border-[var(--ini-line)] px-4 py-3 sm:grid-cols-2 sm:px-5">
                {([
                  ["Plan completo", comparativa.completo],
                  ["Prudente · solo caja y ventas de hoy", comparativa.prudente],
                ] as const).map(([titulo, r]) => (
                  <div key={titulo} className="min-w-0">
                    <p className="text-[12px] font-medium text-white/60">{titulo}</p>
                    <p className="mt-1 text-[13px] tabular-nums text-white/80">
                      {typeof r.mejora_puntos_jornada === "number" ? `${signedPoints(r.mejora_puntos_jornada)} pts` : "—"} · {r.compras?.length ?? 0} compras · {r.ventas?.length ?? 0} ventas
                    </p>
                    <p className="text-[12px] tabular-nums text-white/40">
                      Gasto {eurShort(r.presupuesto?.gasto_pujas ?? 0)} · sobran {eurShort(r.saldo_al_final ?? 0)}
                    </p>
                    {r.valido === false ? (
                      <p className="mt-1.5 text-[12px] text-[var(--ini-amber)]">{r.motivo || "Invalidado: sin once legal si fallan las pujas."}</p>
                    ) : (
                    <ul className="mt-1.5 text-[12px] text-white/55">
                      {(r.compras || []).map((c, i) => (
                        <li key={`c${i}`} className="truncate">+ {c.nombre} · {eurShort(c.euros ?? 0)}{typeof c.mejora_neta === "number" ? ` · ${signedPoints(c.mejora_neta)} pts` : ""}</li>
                      ))}
                      {(r.ventas || []).map((v, i) => (
                        <li key={`v${i}`} className="truncate text-white/40">− {v.nombre} · {eurShort(v.euros ?? 0)}{v.momento === "condicional" ? " · si ganas" : ""}</li>
                      ))}
                    </ul>
                    )}
                  </div>
                ))}
              </div>
            </Disclosure>
          ) : null}
          <Disclosure title="Alternativas si consigues liquidez" count={alternativas.length}>
            <ul className="ini-divide border-t border-[var(--ini-line)]">
              {alternativas.map((row, i) => {
                const name = row.nombre || "Jugador";
                return (
                  <li key={`${row.player_id || name}-alt-${i}`} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                    <Avatar name={name} imageUrl={photoFor(photos, row.player_id, name)} size={32} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] text-white/80">{name}</span>
                      <span className="block text-[12px] text-white/40">
                        {row.etiqueta === "CLAUSULAR" ? "Clausular" : "Pujar"}
                        {typeof row.mejora_neta === "number" ? ` · ${signedPoints(row.mejora_neta)} pts` : ""}
                        {typeof row.falta_eur === "number" && row.falta_eur > 0 ? ` · faltan ${eurShort(row.falta_eur)}` : ""}
                      </span>
                    </span>
                    {typeof row.euros === "number" ? <span className="text-[13px] tabular-nums text-white/60">{eurShort(row.euros)}</span> : null}
                  </li>
                );
              })}
            </ul>
          </Disclosure>
          <Disclosure title="En el radar · no pujar hoy" count={radar.length}>
            <ul className="ini-divide border-t border-[var(--ini-line)]">
              {radar.map((row, i) => {
                const name = row.nombre || "Jugador";
                return (
                  <li key={`${row.player_id || name}-${i}`} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                    <Avatar name={name} imageUrl={photoFor(photos, row.player_id, name)} size={32} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] text-white/80">{name}</span>
                      <span className="block text-[12px] text-white/40">
                        {typeof row.mejora_neta === "number" ? `Mejora ${signedPoints(row.mejora_neta)} pts · no compensa el peaje` : "No compensa el peaje"}
                      </span>
                    </span>
                    {typeof row.euros === "number" ? <span className="text-[13px] tabular-nums text-white/60">{eurShort(row.euros)}</span> : null}
                  </li>
                );
              })}
            </ul>
          </Disclosure>
        </div>
      ) : null}

      <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex justify-center lg:bottom-8">
        <span className="ini-toast rounded-full border border-white/10 bg-[#0b0f14]/95 px-4 py-2 text-[13px] font-medium tabular-nums text-white shadow-2xl backdrop-blur" data-on={toast !== null}>
          {toast ?? " "}
        </span>
      </div>
    </section>
  );
}

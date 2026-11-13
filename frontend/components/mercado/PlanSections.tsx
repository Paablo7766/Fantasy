"use client";

// Plan de fichajes, Modo parón y Jugadores que sobran: tres bloques con el
// mismo lenguaje — foto, acción en una pastilla, una frase con el porqué en
// cifras y el importe a la derecha. Sin jerga del motor.

import { useId, useState, type ReactNode } from "react";
import { Chevron, Face, TONE, cleanText, compact, money } from "@/components/ui/kit";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { planBid } from "@/lib/mercado/marketAction";
import type { PlanFichajeAccion, PlanFichajes } from "@/lib/types";

const MINT = "#7FE0A8";

function num(value: number, digits = 1): string {
  return value.toLocaleString("es-ES", { maximumFractionDigits: digits });
}

function pts(value: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${num(Math.abs(value))} pts`;
}

function pct(value: number): string {
  return `${num(Math.abs(value), 0)} %`;
}

/** «2026-11-20T20:59…» → «vie 20 nov». */
function shortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric", month: "short" })
    .format(date)
    .replace(/\./g, "")
    .replace(",", "");
}

/** «miércoles 18-nov» → «mié 18 nov». */
function shortDay(text: string | null | undefined): string {
  if (!text) return "";
  const [day, rest] = text.split(" ");
  return `${day.slice(0, 3)} ${(rest || "").replace("-", " ")}`.trim();
}

function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const time = new Date(iso).getTime();
  return Number.isNaN(time) ? null : Math.max(0, (time - Date.now()) / 86_400_000);
}

// ── Piezas comunes ──────────────────────────────────────────────────────────

const ICONS: Record<"plan" | "paron" | "sobran", ReactNode> = {
  plan: (
    <svg viewBox="0 0 20 20" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M3 14.5 7.5 10l3 3L17 6.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12.5 6.5H17V11" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  paron: (
    <svg viewBox="0 0 20 20" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M6 3h8M6 17h8M7 3c0 3.5 6 4 6 7s-6 3.5-6 7M13 3c0 3.5-6 4-6 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  sobran: (
    <svg viewBox="0 0 20 20" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="8" cy="7" r="3" />
      <path d="M2.5 16.5c.6-2.8 2.8-4.5 5.5-4.5s4.9 1.7 5.5 4.5M13.5 9h4" strokeLinecap="round" />
    </svg>
  ),
};

/**
 * Tarjeta plegable con cabecera que ya informa cerrada: icono con el color de
 * la sección, título, una línea de resumen y la cifra clave a la derecha.
 */
function SectionCard({
  icon,
  tone,
  title,
  summary,
  figure,
  figureTone,
  figureLabel,
  progress,
  defaultOpen = false,
  children,
}: {
  icon: keyof typeof ICONS;
  tone: string;
  title: string;
  summary: ReactNode;
  figure?: string | null;
  figureTone?: string;
  figureLabel?: string;
  /** 0–1: barra fina bajo la cabecera (fase, cobertura…). */
  progress?: number | null;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <section
      className="home-glass relative overflow-hidden"
      style={{ background: `radial-gradient(70% 140% at 0% 0%, ${tone}1f 0%, transparent 60%), linear-gradient(180deg, rgba(255,255,255,0.065) 0%, rgba(255,255,255,0.03) 100%)` }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3.5 px-4 py-4 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl" style={{ color: tone, background: `${tone}1f`, boxShadow: `inset 0 0 0 1px ${tone}33` }}>
          {ICONS[icon]}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[16px] font-semibold tracking-[-0.01em] text-white">{title}</span>
          <span className="mt-0.5 line-clamp-2 block text-[12.5px] leading-snug text-white/50">{summary}</span>
        </span>
        {figure ? (
          <span className="shrink-0 text-right">
            <span className="block text-[17px] font-semibold leading-tight tabular-nums" style={{ color: figureTone || "#fff" }}>
              {figure}
            </span>
            {figureLabel ? <span className="block text-[11px] text-white/40">{figureLabel}</span> : null}
          </span>
        ) : null}
        <Chevron open={open} />
      </button>
      {typeof progress === "number" ? (
        <span className="mx-4 mb-3 block h-[3px] overflow-hidden rounded-full bg-white/[0.06]" aria-hidden="true">
          <span className="block h-full rounded-full transition-[width] duration-700" style={{ width: `${Math.max(4, Math.min(1, progress) * 100)}%`, background: tone }} />
        </span>
      ) : null}
      {open ? (
        <div id={id} className="row-in border-t border-white/[0.06] px-4 pb-4 pt-3">
          {children}
        </div>
      ) : null}
    </section>
  );
}

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4" style={{ color, background: `${color}1f` }}>
      {label}
    </span>
  );
}

function Eyebrow({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <p className="text-[11.5px] font-semibold uppercase tracking-[0.08em] text-white/40">{children}</p>
      {right ? <p className="shrink-0 text-[12px] tabular-nums text-white/45">{right}</p> : null}
    </div>
  );
}

/** Fila de jugador: foto con anillo de la acción, nombre, pastilla y porqué; importe a la derecha. */
function PlayerRow({
  name,
  photo,
  color,
  pill,
  why,
  amount,
  amountTone,
  hint,
}: {
  name: string;
  photo: string | null;
  color: string;
  pill: string;
  why: ReactNode;
  amount?: string | null;
  amountTone?: string;
  hint?: ReactNode;
}) {
  return (
    <li className="flex items-center gap-3 py-3">
      <Face name={name} src={photo} size={42} ring={color} />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[14.5px] font-medium text-white">{name}</span>
          <Pill label={pill} color={color} />
        </span>
        <span className="mt-0.5 block text-[12.5px] leading-snug text-white/50">{why}</span>
      </span>
      {amount ? (
        <span className="shrink-0 text-right">
          <span className="block text-[15px] font-semibold tabular-nums" style={{ color: amountTone || "#fff" }}>
            {amount}
          </span>
          {hint ? <span className="block text-[11px] tabular-nums text-white/40">{hint}</span> : null}
        </span>
      ) : null}
    </li>
  );
}

/** Pasos de una secuencia con el actual encendido. */
function Stepper({ steps, current, color }: { steps: string[]; current: number; color: string }) {
  return (
    <ol className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
      {steps.map((label, index) => {
        const state = index < current ? "past" : index === current ? "now" : "next";
        return (
          <li key={label} className="min-w-0">
            <span
              className="block h-1 rounded-full"
              style={{ background: state === "next" ? "rgba(255,255,255,0.08)" : color, opacity: state === "past" ? 0.4 : 1 }}
            />
            <span className={`mt-1.5 block truncate text-[11.5px] ${state === "now" ? "font-semibold" : "text-white/35"}`} style={state === "now" ? { color } : undefined}>
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Dos cifras frente a frente: barra de antes y de después. */
function BeforeAfter({ before, after }: { before: number; after: number }) {
  const top = Math.max(before, after, 1);
  return (
    <div className="mt-3 grid gap-1.5">
      {[
        { label: "Ahora", value: before, color: "rgba(255,255,255,0.28)" },
        { label: "Con el plan", value: after, color: TONE.green },
      ].map((row) => (
        <div key={row.label} className="flex items-center gap-3">
          <span className="w-[5.5rem] shrink-0 text-[12px] text-white/45">{row.label}</span>
          <span className="relative h-2 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
            <span className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700" style={{ width: `${(row.value / top) * 100}%`, background: row.color }} />
          </span>
          <span className="w-[4.5rem] shrink-0 text-right text-[12.5px] font-medium tabular-nums text-white/80">{num(row.value)} pts</span>
        </div>
      ))}
    </div>
  );
}

function Callout({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <p className="mt-3 flex gap-2.5 rounded-2xl px-3.5 py-2.5 text-[12.5px] leading-snug text-white/70" style={{ background: `${tone}12`, boxShadow: `inset 0 0 0 1px ${tone}26` }}>
      <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: tone }} aria-hidden="true" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}

// ── Plan de fichajes ─────────────────────────────────────────────────────────

type Kind = "puja" | "clausula" | "vende" | "escaparate" | "busca";

const KIND: Record<Kind, { label: string; color: string }> = {
  puja: { label: "Pujar", color: TONE.green },
  clausula: { label: "Clausular", color: TONE.copper },
  vende: { label: "Vender", color: TONE.red },
  escaparate: { label: "A la venta", color: TONE.amber },
  busca: { label: "Buscar", color: TONE.gray },
};

function kindOf(accion: PlanFichajeAccion): Kind {
  if (accion.etiqueta === "CLAUSULAR" || accion.tipo === "CLAUSULAZO") return "clausula";
  if (accion.tipo === "VENDE" || accion.tipo === "VENDER HOY") return "vende";
  if (accion.tipo === "ESCAPARATE") return "escaparate";
  if (accion.tipo === "BUSCA") return "busca";
  return "puja";
}

/** El porqué de cada acción en una frase con cifras: puntos, subida y euros. */
function planWhy(accion: PlanFichajeAccion, kind: Kind): string {
  const parts: string[] = [];
  const trend = typeof accion.prevision_7d_pct === "number" ? accion.prevision_7d_pct : null;
  const euros = typeof accion.euros === "number" ? accion.euros : null;
  if (kind === "puja" || kind === "clausula") {
    if (typeof accion.mejora_neta === "number" && accion.mejora_neta !== 0) parts.push(`${pts(accion.mejora_neta)} a tu once`);
    else if (typeof accion.jornada === "number") parts.push(`${num(accion.jornada)} pts esperados`);
    if (trend !== null && trend > 1) parts.push(`sube ~${pct(trend)}${euros ? ` (${compact((euros * trend) / 100, true)})` : ""} en 7 días`);
  } else if (kind === "vende" || kind === "escaparate") {
    if (trend !== null && trend < -1) parts.push(`baja ~${pct(trend)} en 7 días`);
    if (typeof accion.ganancia_esperada_eur === "number" && accion.ganancia_esperada_eur > 0) parts.push(`evitas perder ${compact(accion.ganancia_esperada_eur)}`);
    if (kind === "escaparate") parts.push("tendrás oferta mañana");
    if (accion.momento === "condicional") parts.push("solo si ganas la puja");
  } else {
    parts.push(accion.posicion ? `Falta un ${accion.posicion}` : "Falta cubrir un hueco");
  }
  return parts.join(" · ");
}

function PlanActionRow({ accion, photos }: { accion: PlanFichajeAccion; photos: PhotoIndex }) {
  const kind = kindOf(accion);
  const meta = KIND[kind];
  const name = kind === "busca" ? `Buscar ${accion.posicion || "jugador"}` : accion.nombre || "Jugador";
  // En una puja, la cifra a escribir es la misma que enseña Inicio.
  const cifra = kind === "puja" ? (planBid(accion) ?? accion.euros) : accion.euros;
  const competitiva = typeof accion.puja_competitiva_liga === "number" && typeof cifra === "number" && accion.puja_competitiva_liga > cifra;
  const later = accion.momento && accion.momento !== "hoy";
  return (
    <PlayerRow
      name={name}
      photo={kind === "busca" ? null : photoFor(photos, accion.player_id ?? undefined, accion.nombre ?? undefined)}
      color={meta.color}
      pill={later ? `${meta.label} · después` : meta.label}
      why={
        <>
          {[accion.posicion, planWhy(accion, kind)].filter(Boolean).join(" · ").replace(/^./, (c) => c.toUpperCase())}
          {competitiva && accion.alta_demanda ? (
            <span className="mt-0.5 block text-[#FFC08A]">
              Muy pujado: para asegurarlo, {money(accion.puja_competitiva_liga)}
            </span>
          ) : null}
        </>
      }
      amount={typeof cifra === "number" && cifra > 0 ? money(cifra) : null}
      amountTone={kind === "vende" || kind === "escaparate" ? MINT : undefined}
      hint={kind === "escaparate" ? "valor" : kind === "vende" ? "ingresas" : undefined}
    />
  );
}

const PLAN_TONE: Record<string, string> = { "Hazlo ya": TONE.green, Recomendable: TONE.blue, Opcional: TONE.gray };

export function PlanBlock({ plan, photos }: { plan: PlanFichajes | null | undefined; photos: PhotoIndex }) {
  const acciones = Array.isArray(plan?.acciones) ? plan.acciones : [];
  const radar = Array.isArray(plan?.en_radar) ? plan.en_radar : [];
  const veredicto = plan?.veredicto || "Opcional";
  const gain = typeof plan?.mejora_puntos_jornada === "number" ? plan.mejora_puntos_jornada : 0;
  const before = plan?.puntos_once_actual;
  const after = plan?.puntos_once;
  const p = plan?.presupuesto;
  const spend = p ? p.gasto_pujas + p.gasto_clausulas : 0;
  const credit = Math.max(p?.credito_paron ?? 0, typeof plan?.saldo_al_final === "number" && plan.saldo_al_final < 0 ? -plan.saldo_al_final : 0);
  const fromCash = Math.max(0, spend - credit - (p?.ventas_hoy ?? 0) - (p?.ventas_si_ganas ?? 0));
  const saleDay = plan?.paron?.ruta_salida?.dia_venta;
  const tone = PLAN_TONE[veredicto] || TONE.gray;
  const hoy = acciones.filter((a) => !a.momento || a.momento === "hoy");
  const despues = acciones.filter((a) => a.momento && a.momento !== "hoy");

  const counts = new Map<string, number>();
  for (const a of hoy) {
    const label = KIND[kindOf(a)].label;
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  const resumen = hoy.length
    ? [...counts].map(([label, n]) => `${label} ${n}`).join(" · ")
    : "Nada que hacer hoy";

  return (
    <SectionCard
      icon="plan"
      tone={TONE.green}
      title="Tu plan de fichajes"
      defaultOpen
      summary={
        <>
          <span className="font-semibold" style={{ color: tone }}>{veredicto}</span>
          <span className="text-white/30"> · </span>
          {resumen}
        </>
      }
      figure={gain > 0.05 ? pts(gain) : null}
      figureTone={MINT}
      figureLabel="a tu once"
    >
      {typeof before === "number" && typeof after === "number" && after > before ? (
        <>
          <p className="text-[14px] leading-snug text-white/75">
            Tu once pasa de <span className="font-semibold tabular-nums text-white">{num(before)}</span> a{" "}
            <span className="font-semibold tabular-nums text-[#7FE0A8]">{num(after)} pts</span> en la próxima jornada.
          </p>
          <BeforeAfter before={before} after={after} />
        </>
      ) : (
        <p className="text-[14px] leading-snug text-white/65">Hoy nada del mercado mejora tu once lo bastante para gastar caja.</p>
      )}

      {spend > 0 ? (
        <div className="mt-4 grid grid-cols-3 gap-2 rounded-2xl bg-white/[0.04] p-3">
          <div className="min-w-0">
            <p className="text-[11px] text-white/40">Inviertes</p>
            <p className="truncate text-[15px] font-semibold tabular-nums text-white">{compact(spend)}</p>
          </div>
          <div className="min-w-0">
            <p className="text-[11px] text-white/40">De tu caja</p>
            <p className="truncate text-[15px] font-semibold tabular-nums text-white/80">{compact(fromCash + (p?.ventas_hoy ?? 0))}</p>
          </div>
          <div className="min-w-0">
            <p className="text-[11px] text-white/40">Con crédito</p>
            <p className="truncate text-[15px] font-semibold tabular-nums" style={{ color: credit > 0 ? TONE.amber : "rgba(255,255,255,0.5)" }}>
              {credit > 0 ? compact(credit) : "—"}
            </p>
          </div>
          {credit > 0 ? (
            <p className="col-span-3 text-[11.5px] leading-snug text-white/45">
              Sin sanción mientras no empiece la jornada: devuélvelo vendiendo{saleDay ? ` el ${shortDay(saleDay)}` : " antes del cierre"}.
              {plan?.deuda_paron?.cubierta_con_banquillo ? " Se cubre con tu banquillo, sin tocar el once." : ""}
            </p>
          ) : null}
        </div>
      ) : null}

      {hoy.length ? (
        <div className="mt-4">
          <Eyebrow right={`${hoy.length}`}>Hoy</Eyebrow>
          <ul className="divide-y divide-white/[0.05]">
            {hoy.map((accion, index) => (
              <PlanActionRow key={`${accion.tipo}-${accion.player_id || accion.nombre}-${index}`} accion={accion} photos={photos} />
            ))}
          </ul>
        </div>
      ) : null}

      {despues.length ? (
        <div className="mt-3">
          <Eyebrow right={`${despues.length}`}>Después</Eyebrow>
          <ul className="divide-y divide-white/[0.05]">
            {despues.map((accion, index) => (
              <PlanActionRow key={`luego-${accion.player_id || accion.nombre}-${index}`} accion={accion} photos={photos} />
            ))}
          </ul>
        </div>
      ) : null}

      {radar.length ? (
        <div className="mt-3">
          <Eyebrow>Vigilar, sin pujar hoy</Eyebrow>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {radar.map((accion, index) => (
              <span key={`radar-${accion.player_id || accion.nombre}-${index}`} className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.05] py-1 pl-1 pr-2.5 text-[12px] text-white/70">
                <Face name={accion.nombre || "Jugador"} src={photoFor(photos, accion.player_id ?? undefined, accion.nombre ?? undefined)} size={20} />
                {accion.nombre}
                {typeof accion.euros === "number" ? <span className="tabular-nums text-white/40">{compact(accion.euros)}</span> : null}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

// ── Modo parón ───────────────────────────────────────────────────────────────

const FASES_PARON = ["Fichar y limpiar", "Cobrar", "Cerrar el once"];

export function ParonBlock({ plan, photos }: { plan: PlanFichajes | null | undefined; photos: PhotoIndex }) {
  const paron = plan?.paron;
  if (!paron?.activo) return null;
  const ruta = paron.ruta_salida;
  const proy = paron.proyeccion;
  const cierre = shortDate(paron.cierre);
  const venta = shortDay(ruta.dia_venta);
  const diasVenta = daysUntil(ruta.dia_venta_at);
  const deuda = Math.max(0, ruta.deuda_a_saldar);
  const cobertura = deuda > 0 ? Math.min(1, ruta.ingreso / deuda) : 1;
  const enPlan = new Set((plan?.acciones || []).map((a) => String(a.player_id)));
  // Lo que el plan ya enseña no se repite: aquí solo las piezas propias del parón.
  const extras = [
    { label: "Vender ya", color: TONE.red, items: paron.corta_hemorragias },
    { label: "Especular", color: TONE.blue, items: paron.especular },
    { label: "Recoger beneficios", color: TONE.green, items: paron.recoger_beneficios },
  ]
    .map((g) => ({ ...g, items: (g.items || []).filter((a) => !enPlan.has(String(a.player_id))) }))
    .filter((g) => g.items.length);

  return (
    <SectionCard
      icon="paron"
      tone={TONE.copper}
      title="Modo parón"
      summary={
        <>
          <span className="font-semibold text-[#FFC08A]">{`Fase ${paron.fase} de 3`}</span>
          <span className="text-white/30"> · </span>
          {venta ? `vende el ${venta}` : `cierra en ${num(paron.dias_al_cierre, 0)} días`}
          {deuda > 0 ? (
            <>
              <span className="text-white/30"> · </span>
              <span style={{ color: ruta.cubre ? MINT : TONE.red }}>{ruta.cubre ? "deuda cubierta" : `faltan ${compact(ruta.falta_eur)}`}</span>
            </>
          ) : null}
        </>
      }
      figure={proy.beneficio_total_eur ? compact(proy.beneficio_total_eur, true) : null}
      figureTone={MINT}
      figureLabel="en valor"
      progress={paron.fase / 3}
    >
      <Stepper steps={FASES_PARON} current={Math.min(2, Math.max(0, paron.fase - 1))} color={TONE.copper} />
      <p className="mt-3 text-[13px] leading-snug text-white/60">
        Sin partidos, el saldo puede quedar en negativo sin perder puntos. Ficha ahora lo que va a subir y véndelo{venta ? ` el ${venta}` : ""} para llegar
        {cierre ? ` al ${cierre}` : " al cierre"} con saldo positivo.
      </p>

      {plan?.brecha_posicional?.texto ? (
        <p className="mt-3 rounded-xl bg-white/[0.04] px-3 py-2 text-[12.5px] leading-snug text-white/65">{plan.brecha_posicional.texto}</p>
      ) : null}

      <div className="mt-4 grid grid-cols-3 gap-2">
        <div className="min-w-0 rounded-2xl bg-white/[0.04] p-3">
          <p className="text-[11px] text-white/40">Ganas en valor</p>
          <p className="truncate text-[17px] font-semibold tabular-nums text-[#7FE0A8]">{compact(proy.beneficio_total_eur, true)}</p>
        </div>
        <div className="min-w-0 rounded-2xl bg-white/[0.04] p-3">
          <p className="text-[11px] text-white/40">Puntos extra</p>
          <p className="truncate text-[17px] font-semibold tabular-nums text-[#FFC08A]">{pts(proy.mejora_xp_j13).replace(" pts", "")}</p>
        </div>
        <div className="min-w-0 rounded-2xl bg-white/[0.04] p-3">
          <p className="text-[11px] text-white/40">Deuda a saldar</p>
          <p className="truncate text-[17px] font-semibold tabular-nums" style={{ color: deuda > 0 ? TONE.amber : "#fff" }}>
            {deuda > 0 ? compact(deuda) : "0"}
          </p>
        </div>
      </div>

      {paron.hold_j13.length ? (
        <div className="mt-4">
          <Eyebrow right="subida prevista">Se revalorizan</Eyebrow>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {paron.hold_j13.map((item) => (
              <span key={`hold-${item.player_id}`} className="inline-flex items-center gap-1.5 rounded-full bg-[#10B981]/10 py-1 pl-1 pr-2.5 text-[12.5px] text-white/80">
                <Face name={item.nombre} src={photoFor(photos, item.player_id, item.nombre)} size={22} />
                {item.nombre}
                <span className="font-semibold tabular-nums text-[#7FE0A8]">{compact(item.subida_esperada_eur, true)}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {extras.map((grupo) => (
        <div key={grupo.label} className="mt-4">
          <Eyebrow>{grupo.label}</Eyebrow>
          <ul className="divide-y divide-white/[0.05]">
            {grupo.items.map((accion, index) => (
              <PlanActionRow key={`paron-${grupo.label}-${accion.player_id || accion.nombre}-${index}`} accion={accion} photos={photos} />
            ))}
          </ul>
        </div>
      ))}

      <div className="mt-4 rounded-2xl bg-white/[0.04] p-3.5">
        <Eyebrow right={diasVenta !== null ? `en ${num(diasVenta, 0)} días` : undefined}>{`Ruta de salida${venta ? ` · ${venta}` : ""}`}</Eyebrow>
        {deuda > 0 ? (
          <>
            <div className="mt-2 flex items-baseline justify-between gap-3 text-[12.5px] tabular-nums">
              <span className="text-white/60">
                Entran <span className="font-semibold text-white">{compact(ruta.ingreso)}</span> para cubrir {compact(deuda)}
              </span>
              <span className="font-semibold" style={{ color: ruta.cubre ? TONE.green : TONE.red }}>
                {ruta.cubre ? "Cubierto" : `Faltan ${compact(ruta.falta_eur)}`}
              </span>
            </div>
            <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-white/[0.08]">
              <span className="block h-full rounded-full transition-[width] duration-700" style={{ width: `${cobertura * 100}%`, background: ruta.cubre ? TONE.green : TONE.red }} />
            </span>
            {ruta.escenarios ? (
              <div className="mt-3 grid grid-cols-2 gap-2 text-[12px] tabular-nums">
                {[ruta.escenarios.esperado, ruta.escenarios.estres].map((esc) => (
                  <div key={esc.etiqueta} className="rounded-xl bg-white/[0.04] p-2.5">
                    <p className="text-white/45">{esc.etiqueta}</p>
                    <p className="mt-0.5 font-semibold" style={{ color: esc.cubre ? TONE.green : TONE.red }}>
                      {compact(esc.ingreso)} · {esc.cubre ? "cubre" : "no cubre"}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
            {ruta.ventana_escaparate ? (
              <p className="mt-2 text-[12px] leading-snug text-white/50">
                Escaparate: {ruta.ventana_escaparate}. Entre lunes y miércoles la máquina pagó una mediana de +3,4 %; el viernes, −2,6 %.
              </p>
            ) : null}
          </>
        ) : (
          <p className="mt-2 text-[12.5px] text-white/60">No hay deuda que saldar: no hace falta vender.</p>
        )}
        {ruta.ventas.length ? (
          <ul className="mt-1 divide-y divide-white/[0.05]">
            {ruta.ventas.map((v) => {
              const sube = v.valor_proyectado - v.valor_hoy;
              return (
                <PlayerRow
                  key={`ruta-${v.player_id}`}
                  name={v.nombre}
                  photo={photoFor(photos, v.player_id, v.nombre)}
                  color={v.titular ? TONE.amber : TONE.gray}
                  pill={v.titular ? "Titular" : "Banquillo"}
                  why={`Vale ${compact(v.valor_hoy)} hoy${Math.abs(sube) > 50_000 ? ` · ${compact(sube, true)} hasta la venta` : ""}${v.xp_perdido > 0 ? ` · tu once pierde ${num(v.xp_perdido)} pts` : ""}`}
                  amount={compact(v.ingreso)}
                  amountTone={MINT}
                  hint="peor caso"
                />
              );
            })}
          </ul>
        ) : null}
        {ruta.ventas.length && typeof ruta.margen_oferta === "number" ? (
          <p className="mt-1 text-[11.5px] leading-snug text-white/40">
            Cuenta la peor oferta de LaLiga ({num(ruta.margen_oferta * 100, 0)} % del valor)
            {ruta.titulares_vendidos === 0 ? " y no toca a ningún titular." : `; vende ${ruta.titulares_vendidos} ${ruta.titulares_vendidos === 1 ? "titular" : "titulares"}.`}
          </p>
        ) : null}
      </div>
    </SectionCard>
  );
}

// ── Jugadores que sobran ─────────────────────────────────────────────────────

const FASES_SEMANA = ["APALANCAMIENTO", "ESCAPARATE", "LIQUIDACION"] as const;
const FASE_LABEL = ["Esperar", "Poner en venta", "Vender ya"];
const FASE_TEXTO: Record<string, string> = {
  APALANCAMIENTO: "Quedan 3 días o más: se guardan mientras suban. Solo se venden si la oferta ya paga su valor.",
  ESCAPARATE: "Ponlos en venta hoy: la oferta de LaLiga cambia cada día y se acepta la que pague su valor.",
  LIQUIDACION: "Último día: acepta la oferta que haya para dejar 11 jugadores y el saldo en positivo.",
};

function sobranteAction(accion: string | null | undefined): { label: string; color: string } {
  const text = (accion || "").toUpperCase();
  if (text.startsWith("VENDER")) return { label: "Vender hoy", color: TONE.red };
  if (text.startsWith("SIN OFERTA")) return { label: "Vender a un rival", color: TONE.amber };
  if (text.includes("ESCAPARATE")) return { label: "A la venta", color: TONE.amber };
  return { label: "Guardar", color: TONE.gray };
}

export function LiquidacionBlock({ plan, photos }: { plan: PlanFichajes | null | undefined; photos: PhotoIndex }) {
  const liq = plan?.liquidacion;
  const sobrantes = Array.isArray(liq?.sobrantes) ? liq.sobrantes : [];
  if (!liq?.activo || !sobrantes.length || !liq.fase) return null;
  const faseIndex = Math.max(0, FASES_SEMANA.indexOf(liq.fase as (typeof FASES_SEMANA)[number]));
  // Si el plan de hoy ya manda vender o poner a la venta a alguien, esa orden gana a la de la semana.
  const planHoy = new Map(
    (plan?.acciones || [])
      .filter((a) => (a.momento || "hoy") === "hoy" && ["VENDE", "VENDER HOY", "ESCAPARATE"].includes(a.tipo || ""))
      .map((a) => [String(a.player_id), a]),
  );
  const totalValor = sobrantes.reduce((t, s) => t + (typeof s.valor === "number" ? s.valor : 0), 0);
  const peor = typeof liq.saldo_peor_caso === "number" ? liq.saldo_peor_caso : null;
  const tras = typeof liq.saldo_tras_liquidar === "number" ? liq.saldo_tras_liquidar : null;
  const faseTone = [TONE.gray, TONE.amber, TONE.red][faseIndex];
  const urgentes = sobrantes.filter((s) => planHoy.has(String(s.player_id)) || sobranteAction(s.accion).label !== "Guardar").length;

  return (
    <SectionCard
      icon="sobran"
      tone={faseTone}
      title="Jugadores que sobran"
      summary={
        <>
          <span className="font-semibold" style={{ color: faseIndex === 0 ? "rgba(255,255,255,0.75)" : faseTone }}>{FASE_LABEL[faseIndex]}</span>
          <span className="text-white/30"> · </span>
          {`${sobrantes.length} ${sobrantes.length === 1 ? "jugador" : "jugadores"} fuera del once`}
          {urgentes ? (
            <>
              <span className="text-white/30"> · </span>
              <span style={{ color: TONE.amber }}>{`${urgentes} hoy`}</span>
            </>
          ) : null}
        </>
      }
      figure={compact(totalValor)}
      figureLabel="en valor"
      progress={(faseIndex + 1) / 3}
    >
      <Stepper steps={FASE_LABEL} current={faseIndex} color={faseTone} />
      <p className="mt-3 text-[13px] leading-snug text-white/60">
        Fuera de tu once {sobrantes.length === 1 ? "queda 1 jugador" : `quedan ${sobrantes.length} jugadores`}. {FASE_TEXTO[liq.fase] || ""}
      </p>

      <ul className="mt-1 divide-y divide-white/[0.05]">
        {sobrantes.map((item, index) => {
          const name = item.nombre || "Jugador";
          const orden = planHoy.get(String(item.player_id));
          const action = orden ? (orden.tipo === "ESCAPARATE" ? { label: "A la venta hoy", color: TONE.amber } : { label: "Vender hoy", color: TONE.red }) : sobranteAction(item.accion);
          const trend = typeof item.pct === "number" ? item.pct : null;
          const valor = typeof item.valor === "number" ? item.valor : null;
          const why = [
            item.position,
            trend !== null && Math.abs(trend) >= 1 ? `${trend > 0 ? "sube" : "baja"} ~${pct(trend)} en 7 días${valor ? ` (${compact((valor * trend) / 100, true)})` : ""}` : "",
            orden ? "el plan de hoy lo adelanta" : cleanText(item.motivo).replace(/\.$/, ""),
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <PlayerRow
              key={`liq-${item.player_id || name}-${index}`}
              name={name}
              photo={photoFor(photos, item.player_id ?? undefined, name)}
              color={action.color}
              pill={action.label}
              why={why}
              amount={typeof item.oferta_eur === "number" ? money(item.oferta_eur) : valor !== null ? money(valor) : null}
              hint={typeof item.oferta_eur === "number" ? "oferta" : "valor"}
            />
          );
        })}
      </ul>

      {tras !== null ? (
        <div className="mt-2 flex items-baseline justify-between gap-3 rounded-2xl bg-white/[0.04] px-3.5 py-3">
          <span className="text-[12.5px] text-white/55">Saldo si los vendes</span>
          <span className="text-right tabular-nums">
            <span className="text-[15px] font-semibold" style={{ color: tras >= 0 ? TONE.green : TONE.red }}>
              {money(tras)}
            </span>
            {peor !== null && money(peor) !== money(tras) ? <span className="block text-[11px] text-white/40">{`${money(peor)} en el peor caso`}</span> : null}
          </span>
        </div>
      ) : null}
      {typeof liq.deficit_eur === "number" && liq.deficit_eur > 0 ? (
        <Callout tone={TONE.red}>Aun vendiéndolos faltan {compact(liq.deficit_eur)}: habrá que vender a alguien del once.</Callout>
      ) : null}
    </SectionCard>
  );
}

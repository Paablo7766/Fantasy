"use client";

import { useId, useState, type ReactNode } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";

export const TONE = {
  copper: "#FF9A5A",
  blue: "#0297DE",
  green: "#10B981",
  amber: "#F59E0B",
  red: "#FC734D",
  gray: "#8B9EB0",
} as const;

/** Importe corto con decimales justos: 12,4 M€ · 940k €. */
export function money(value: number | null | undefined, digits?: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000) {
    const places = digits ?? (abs >= 10_000_000 ? 1 : 2);
    return `${sign}${(abs / 1_000_000).toLocaleString("es-ES", { minimumFractionDigits: places, maximumFractionDigits: places })} M€`;
  }
  if (abs >= 1_000) return `${sign}${Math.round(abs / 1_000).toLocaleString("es-ES")}k €`;
  return `${sign}${Math.round(abs).toLocaleString("es-ES")} €`;
}

/** Cifra corta para casillas estrechas, como el saldo de Inicio: 6,4M · −940k. */
export function compact(value: number | null | undefined, signed = false): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : signed && value > 0 ? "+" : "";
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toLocaleString("es-ES", { maximumFractionDigits: 1 })}M`;
  if (abs >= 1_000) return `${sign}${Math.round(abs / 1_000)}k`;
  return `${sign}${Math.round(abs)}`;
}

export function signedMoney(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${money(value)}`;
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const text = Math.abs(value).toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${text}%`;
}

/** ``"+10.9%"`` → 10.9. Las previsiones a 7 días llegan como texto. */
export function parsePct(value: string | number | null | undefined): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (!value) return null;
  const parsed = Number.parseFloat(value.replace(",", ".").replace(/[^\d.+-]/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

export function toneOf(value: number | null | undefined): string {
  if (typeof value !== "number" || Math.abs(value) < 1e-9) return "rgba(255,255,255,0.55)";
  return value > 0 ? TONE.green : TONE.red;
}

/** Verde ≥ 80 %, ámbar 50–80 %, rojo < 50 %, gris sin dato. */
export function ringColor(share: number | null | undefined): string {
  if (typeof share !== "number") return "rgba(255,255,255,0.22)";
  if (share >= 0.8) return TONE.green;
  if (share >= 0.5) return TONE.amber;
  return TONE.red;
}

export function lastName(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 && parts.at(-1)!.length > 2 ? parts.at(-1)! : name;
}

export function Face({
  name,
  src,
  size = 40,
  ring,
}: {
  name: string;
  src?: string | null;
  size?: number;
  ring?: string;
}) {
  // ``size = 0`` llena el contenedor (fichas del campo, que escalan con él).
  const box = size ? { width: size, height: size } : { width: "100%", height: "100%" };
  const avatar = (
    <PlayerAvatar
      player={{ name, image_url: src || null }}
      size="sm"
      className={`!h-full !w-full !text-[11px] !ring-0 ${ring ? "border-2 border-[#120C09]" : "border border-white/[0.12]"}`}
    />
  );
  return (
    <span className="relative inline-flex shrink-0 rounded-full" style={{ ...box, padding: ring ? 2 : 0, background: ring }}>
      {avatar}
    </span>
  );
}

export function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`h-4 w-4 shrink-0 text-white/40 transition-transform duration-200 ease-out ${open ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <path d="M4 6.2 8 10l4-3.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Bloque plegable de cristal: un título, un dato a la derecha y el detalle dentro. */
export function Disclosure({
  title,
  meta,
  icon,
  children,
  defaultOpen = false,
}: {
  title: string;
  meta?: ReactNode;
  icon?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <section className="home-glass overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[3.5rem] w-full items-center gap-3 px-4 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        {icon ? <span className="shrink-0 text-[#FF9A5A]">{icon}</span> : null}
        <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-white">{title}</span>
        {meta ? <span className="shrink-0 text-[13px] tabular-nums text-white/50">{meta}</span> : null}
        <Chevron open={open} />
      </button>
      {open ? (
        <div id={id} className="row-in border-t border-white/[0.06] px-4 pb-4 pt-3">
          {children}
        </div>
      ) : null}
    </section>
  );
}

export function SectionHead({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-1">
      <h3 className="text-[1.1rem] font-semibold tracking-tight text-white">{title}</h3>
      {meta ? <p className="shrink-0 text-[13px] tabular-nums text-white/50">{meta}</p> : null}
    </div>
  );
}

/** Una sola banda de estado para avisos que bloquean: punto de color y frase corta. */
export function StatusBand({ tone, items }: { tone: "fail" | "warn"; items: string[] }) {
  if (!items.length) return null;
  const color = tone === "fail" ? TONE.red : TONE.amber;
  return (
    <p
      role="status"
      className="flex min-h-[2.75rem] items-center gap-2.5 rounded-2xl px-4 py-2 text-[13.5px] font-medium"
      style={{ color, background: `${color}1f`, border: `1px solid ${color}33` }}
    >
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
      <span className="min-w-0">{items.join(" · ")}</span>
    </p>
  );
}

export function HeroStat({ value, label, tone }: { value: string; label: string; tone?: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-white/[0.07] bg-white/[0.05] px-3 py-3 backdrop-blur-md">
      <p className="truncate text-[1.15rem] font-semibold leading-none tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      <p className="mt-1.5 truncate text-[12px] text-white/50">{label}</p>
    </div>
  );
}

/** Mini dato de detalle: etiqueta gris encima, cifra debajo. */
export function Fact({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[11.5px] text-white/45">{label}</p>
      <p className="mt-0.5 truncate text-[15px] font-semibold tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {hint ? <p className="truncate text-[11.5px] tabular-nums text-white/45">{hint}</p> : null}
    </div>
  );
}

export function Empty({ title, detail, action }: { title: string; detail?: string; action?: ReactNode }) {
  return (
    <div className="home-glass flex flex-col items-center px-6 py-10 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-full bg-[#FF7A3D]/15 text-[#FF9A5A]" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M10 6v4.5M10 13.5h.01" strokeLinecap="round" />
          <circle cx="10" cy="10" r="7" />
        </svg>
      </span>
      <p className="mt-4 text-[16px] font-medium text-white">{title}</p>
      {detail ? <p className="mt-1 max-w-xs text-[13.5px] leading-snug text-white/50">{detail}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Skeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Cargando">
      <div className="eq-skel h-56" />
      <div className="eq-skel h-24" />
      <div className="eq-skel h-40" />
    </div>
  );
}

/** Serie corta como área suave en cobre; el último punto se marca. */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const width = 320;
  const height = 72;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(1, Math.abs(max) * 0.01);
  const points = values.map((value, index) => {
    const x = 4 + (index / (values.length - 1)) * (width - 8);
    const y = 6 + (1 - (value - min) / span) * (height - 14);
    return [x, y] as const;
  });
  const line = points.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width} ${height} L0 ${height} Z`;
  const [lx, ly] = points.at(-1)!;
  return (
    <div className="relative">
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block h-[72px] w-full" role="img" aria-label={label}>
      <defs>
        <linearGradient id="eq-spark-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#FF7A3D" stopOpacity="0.35" />
          <stop offset="1" stopColor="#FF7A3D" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="eq-spark-line" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#FF6A2B" />
          <stop offset="1" stopColor="#FFC08A" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#eq-spark-fill)" />
      <path d={line} fill="none" stroke="url(#eq-spark-line)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
      <span
        className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-[0_0_10px_rgba(255,170,110,0.9)]"
        style={{ left: `${(lx / width) * 100}%`, top: `${(ly / height) * 100}%` }}
        aria-hidden="true"
      />
    </div>
  );
}

/** Etiqueta de veredicto sin caja: punto de color y texto corto. */
export function Verdict({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-[12.5px] font-semibold" style={{ color }}>
      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
      <span className="truncate">{label}</span>
    </span>
  );
}

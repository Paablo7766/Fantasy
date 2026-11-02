"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";

/** Anima un número hasta ``target`` (ease-out). Respeta ``prefers-reduced-motion``. */
export function useCountUp(target: number | null, duration = 900): number | null {
  const [value, setValue] = useState<number | null>(target);
  const from = useRef<number>(0);

  useEffect(() => {
    if (target === null) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const start = from.current;
    if (reduced || start === target) {
      from.current = target;
      const id = requestAnimationFrame(() => setValue(target));
      return () => cancelAnimationFrame(id);
    }
    const t0 = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 4);
      setValue(start + (target - start) * eased);
      if (p < 1) frame = requestAnimationFrame(tick);
      else from.current = target;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return target === null ? null : value;
}

/** Bloque plegable con animación de altura (grid 0fr → 1fr). */
export function Collapse({ open, children }: { open: boolean; children: ReactNode }) {
  return (
    <div className="ini-collapse" data-open={open} aria-hidden={!open}>
      <div>{children}</div>
    </div>
  );
}

export function Chevron({ open, className = "" }: { open: boolean; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`h-4 w-4 shrink-0 text-white/35 transition-transform duration-300 ${open ? "rotate-180" : ""} ${className}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <path d="M4 6.2 8 10l4-3.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Tag({ label, color }: { label: string; color: string }) {
  return (
    <span className="ini-tag" style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}>
      {label}
    </span>
  );
}

/** Foto del jugador con un anillo del color de la acción o del riesgo. */
export function Avatar({ name, imageUrl, color, size = 40 }: { name: string; imageUrl?: string | null; color?: string; size?: number }) {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full"
      style={{ width: size + 6, height: size + 6, boxShadow: color ? `0 0 0 1.5px ${color}` : "0 0 0 1px rgba(255,255,255,0.12)" }}
    >
      <span className="block overflow-hidden rounded-full" style={{ width: size, height: size }}>
        <PlayerAvatar player={{ name, image_url: imageUrl ?? null }} size="md" className="rounded-full" />
      </span>
    </span>
  );
}

/**
 * Barra fina que compara una cifra con su referencia (justo, mercado, perfecta).
 * ``mark`` pinta una muesca extra, por ejemplo la caja del rival más rico.
 */
export function Meter({ value, reference, good, mark }: { value: number; reference: number; good: boolean; mark?: number | null }) {
  const top = Math.max(value, reference, mark ?? 0, 1);
  const width = (value / top) * 100;
  const ref = (reference / top) * 100;
  const markAt = typeof mark === "number" ? (mark / top) * 100 : null;
  return (
    <span className="relative mt-2 block h-[3px] w-full rounded-full bg-white/[0.08]">
      <span
        className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700"
        style={{ width: `${width}%`, background: good ? "var(--ini-mint)" : "var(--ini-red)" }}
      />
      <span className="absolute -top-[3px] h-[9px] w-px bg-white/60" style={{ left: `${ref}%` }} />
      {markAt !== null ? <span className="absolute -top-[3px] h-[9px] w-[2px] rounded-full bg-[var(--ini-amber)]" style={{ left: `${markAt}%` }} /> : null}
    </span>
  );
}

export type Fact = { label: string; value: string; tone?: string };

export function FactGrid({ facts }: { facts: Fact[] }) {
  if (!facts.length) return null;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 min-[560px]:grid-cols-3">
      {facts.map((fact) => (
        <div key={fact.label} className="min-w-0">
          <dt className="truncate text-[12px] text-white/45">{fact.label}</dt>
          <dd className="mt-0.5 truncate text-[14px] font-medium tabular-nums" style={{ color: fact.tone || "#fff" }}>
            {fact.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Fila de asesor (cláusulas o ventas): resumen en una línea y el porqué plegado. */
export function AdvisorRow({
  name,
  sub,
  imageUrl,
  ring,
  verdict,
  value,
  meter,
  facts,
  reason,
  extra,
  index,
}: {
  name: string;
  sub: string;
  imageUrl: string | null;
  ring: string;
  verdict: { label: string; color: string };
  value: ReactNode;
  meter?: ReactNode;
  facts: Fact[];
  reason?: string | null;
  extra?: ReactNode;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li className="ini-row ini-in" style={{ "--i": index } as CSSProperties}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-3 px-4 py-3.5 text-left sm:px-5">
        <Avatar name={name} imageUrl={imageUrl} color={ring} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-medium leading-tight text-white">{name}</span>
          <span className="mt-1 flex min-w-0 items-center gap-2">
            <Tag label={verdict.label} color={verdict.color} />
            <span className="truncate text-[12px] text-white/45">{sub}</span>
          </span>
        </span>
        <span className="w-[5.75rem] shrink-0 text-right sm:w-[6.5rem]">
          <span className="block text-[15px] font-semibold tabular-nums text-white">{value}</span>
          {meter}
        </span>
        <Chevron open={open} className="max-sm:hidden" />
      </button>
      <Collapse open={open}>
        <div className="px-4 pb-4 pl-[4.25rem] sm:px-5 sm:pl-[4.5rem]">
          <FactGrid facts={facts} />
          {reason ? <p className="mt-3 text-[13px] leading-5 text-white/55">{reason}</p> : null}
          {extra}
        </div>
      </Collapse>
    </li>
  );
}

/** Pestañas segmentadas con indicador que se desliza. */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
}: {
  items: { id: T; label: string; count?: number | null }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  const index = Math.max(0, items.findIndex((item) => item.id === value));
  return (
    <div className="ini-tabs" role="tablist" aria-label={label}>
      <span
        className="ini-tabs__ind"
        aria-hidden="true"
        style={{ width: `calc((100% - 8px) / ${items.length})`, transform: `translateX(${index * 100}%)` }}
      />
      {items.map((item) => (
        <button key={item.id} type="button" role="tab" aria-selected={item.id === value} className="ini-tab" onClick={() => onChange(item.id)}>
          {item.label}
          {item.count ? <span className="text-[11.5px] tabular-nums text-white/40">{item.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

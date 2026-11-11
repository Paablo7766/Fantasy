import type { ReactNode } from "react";

/** Celda numérica: cifra arriba y un apoyo gris debajo. Solo lleva color lo que significa un cambio. */
export function Cell({ value, sub, tone, subTone, strong = false, className = "" }: { value: string; sub?: string | null; tone?: string; subTone?: string; strong?: boolean; className?: string }) {
  return (
    <span className={`min-w-0 text-right ${className}`}>
      <span className={`block truncate tabular-nums ${strong ? "text-[15px] font-semibold" : "text-[14px] font-medium"}`} style={{ color: tone || "#fff" }}>
        {value}
      </span>
      {sub ? (
        <span className="mt-0.5 block truncate text-[11.5px] tabular-nums" style={{ color: subTone || "rgba(255,255,255,0.4)" }}>
          {sub}
        </span>
      ) : null}
    </span>
  );
}

/** Cabecera de una superficie: título, cuenta y una línea de apoyo. */
export function CardHead({ title, count, caption, children }: { title: string; count?: number; caption?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 pb-3 pt-4 min-[900px]:px-5">
      <div className="min-w-0">
        <h3 className="text-[15px] font-semibold text-white">
          {title}
          {typeof count === "number" ? <span className="ml-1.5 font-normal tabular-nums text-white/40">{count}</span> : null}
        </h3>
        {caption ? <p className="mt-0.5 text-[12.5px] leading-snug text-white/45">{caption}</p> : null}
      </div>
      {children}
    </div>
  );
}

/** Casilla del resumen: etiqueta, cifra y, si hace falta, a quién se refiere. */
export function Tile({ label, value, hint, tone }: { label: string; value: string; hint?: string | null; tone?: string }) {
  return (
    <div className="min-w-0 rounded-[1.1rem] bg-black/40 px-3.5 py-3 backdrop-blur-md">
      <p className="truncate text-[11.5px] text-white/50">{label}</p>
      <p className="mt-1.5 truncate text-[1.1rem] font-semibold leading-none tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {hint ? <p className="mt-1.5 truncate text-[11.5px] text-white/40">{hint}</p> : null}
    </div>
  );
}

/** Cabecera de columnas de una tabla; solo en escritorio. */
export function ColumnHead({ grid, labels }: { grid: string; labels: { label: string; left?: boolean }[] }) {
  return (
    <div className={`${grid} hidden border-y border-white/[0.06] px-5 py-2 min-[900px]:grid`} aria-hidden="true">
      {labels.map((item) => (
        <span key={item.label} className={`truncate text-[11.5px] text-white/40 ${item.left ? "" : "text-right"}`}>
          {item.label}
        </span>
      ))}
    </div>
  );
}

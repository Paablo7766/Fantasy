"use client";

import { useId, useState, type KeyboardEvent, type PointerEvent } from "react";
import { TONE, money, signedMoney, signedPct } from "@/components/ui/kit";

/* Gráficos de la Cartera. Todo SVG/HTML propio: sin librerías, como el resto de la app. */

const INK = "rgba(255,255,255,0.92)";
const MUTED = "rgba(255,255,255,0.45)";
const GRID = "rgba(255,255,255,0.07)";

/**
 * Color por posición. Orden fijo y validado sobre #141414 (banda de luminosidad,
 * separación para daltonismo y contraste): no reordenar ni reciclar.
 */
export const POSITION_COLOR: Record<string, string> = {
  POR: "#E06A24",
  DEF: "#3A8DDE",
  MC: "#B58C1C",
  DEL: "#9B72E3",
};
const OTHER_COLOR = "#6B7280";

/* ── Evolución del valor ────────────────────────────────────────────────── */

export type ValuePoint = {
  /** Día en días desde época: la escala horizontal es temporal, no por índice. */
  t: number;
  value: number;
  label: string;
  forecast?: boolean;
};

function niceStep(range: number, count: number): number {
  const raw = range / Math.max(1, count);
  const pow = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / pow;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10) * pow;
}

/** Curva cúbica monótona (Fritsch–Carlson): suaviza sin inventar picos entre dos días. */
function monotonePath(points: (readonly [number, number])[]): string {
  if (points.length < 2) return "";
  if (points.length === 2) return `M${points[0][0]} ${points[0][1]} L${points[1][0]} ${points[1][1]}`;
  const n = points.length;
  const dx: number[] = [];
  const slope: number[] = [];
  for (let i = 0; i < n - 1; i += 1) {
    dx.push(points[i + 1][0] - points[i][0]);
    slope.push((points[i + 1][1] - points[i][1]) / (dx[i] || 1));
  }
  const tangent: number[] = [slope[0]];
  for (let i = 1; i < n - 1; i += 1) {
    tangent.push(slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2);
  }
  tangent.push(slope[n - 2]);
  for (let i = 0; i < n - 1; i += 1) {
    if (slope[i] === 0) {
      tangent[i] = 0;
      tangent[i + 1] = 0;
      continue;
    }
    const a = tangent[i] / slope[i];
    const b = tangent[i + 1] / slope[i];
    const norm = a * a + b * b;
    if (norm > 9) {
      const scale = 3 / Math.sqrt(norm);
      tangent[i] = scale * a * slope[i];
      tangent[i + 1] = scale * b * slope[i];
    }
  }
  let path = `M${points[0][0].toFixed(2)} ${points[0][1].toFixed(2)}`;
  for (let i = 0; i < n - 1; i += 1) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const third = dx[i] / 3;
    path += ` C${(x0 + third).toFixed(2)} ${(y0 + tangent[i] * third).toFixed(2)} ${(x1 - third).toFixed(2)} ${(y1 - tangent[i + 1] * third).toFixed(2)} ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }
  return path;
}

/**
 * Valor de la plantilla día a día, con la previsión a 7 días como tramo
 * discontinuo. Pasar el dedo o el ratón enseña la cifra de cada día.
 */
export function ValueChart({ points, summary }: { points: ValuePoint[]; summary: string }) {
  const [active, setActive] = useState<number | null>(null);
  const gradient = useId();
  if (points.length < 2) return null;

  const history = points.filter((point) => !point.forecast);
  const forecast = points.find((point) => point.forecast) || null;
  const today = history.at(-1)!;

  const values = points.map((point) => point.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const pad = (rawMax - rawMin || Math.abs(rawMax) * 0.02 || 1) * 0.18;
  const lo = rawMin - pad;
  const hi = rawMax + pad;
  const t0 = points[0].t;
  const t1 = points.at(-1)!.t;
  const xOf = (t: number) => ((t - t0) / (t1 - t0 || 1)) * 100;
  const yOf = (value: number) => (1 - (value - lo) / (hi - lo)) * 100;

  const step = niceStep(hi - lo, 4);
  const ticks: number[] = [];
  for (let tick = Math.ceil(lo / step) * step; tick < hi; tick += step) ticks.push(tick);
  const tickDigits = step >= 1_000_000 ? 0 : 1;

  const coords = history.map((point) => [xOf(point.t), yOf(point.value)] as const);
  const line = monotonePath(coords);
  const area = `${line} L${coords.at(-1)![0].toFixed(2)} 100 L${coords[0][0].toFixed(2)} 100 Z`;
  const todayX = xOf(today.t);
  const todayY = yOf(today.value);

  const pick = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - box.left) / box.width) * 100;
    let best = 0;
    points.forEach((point, index) => {
      if (Math.abs(xOf(point.t) - x) < Math.abs(xOf(points[best].t) - x)) best = index;
    });
    setActive(best);
  };
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const from = active ?? points.indexOf(today);
    setActive(Math.max(0, Math.min(points.length - 1, from + (event.key === "ArrowRight" ? 1 : -1))));
  };

  const shown = active !== null ? points[active] : null;
  const shownX = shown ? xOf(shown.t) : 0;
  const base = shown?.forecast ? today.value : history[0].value;
  const delta = shown ? shown.value - base : 0;

  return (
    <div>
      <div className="relative h-[168px] min-[1100px]:h-[200px]">
      <div
        className="absolute inset-y-0 left-0 right-12 cursor-crosshair touch-pan-y select-none outline-none focus-visible:ring-1 focus-visible:ring-white/30"
        role="img"
        tabIndex={0}
        aria-label={summary}
        onPointerMove={pick}
        onPointerDown={pick}
        onPointerLeave={() => setActive(null)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
      >
        {ticks.map((tick) => (
          <span key={tick} className="pointer-events-none absolute inset-x-0" style={{ top: `${yOf(tick)}%` }} aria-hidden="true">
            <span className="block h-px w-full" style={{ background: GRID }} />
            <span className="absolute left-full top-0 ml-2 -translate-y-1/2 whitespace-nowrap text-[10.5px] tabular-nums" style={{ color: "rgba(255,255,255,0.42)" }}>
              {money(tick, tickDigits)}
            </span>
          </span>
        ))}

        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
          <defs>
            <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#FF8A3D" stopOpacity="0.42" />
              <stop offset="0.7" stopColor="#FF8A3D" stopOpacity="0.06" />
              <stop offset="1" stopColor="#FF8A3D" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${gradient})`} />
          <path d={line} fill="none" stroke="#FFB27A" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          {forecast ? (
            <path
              d={`M${todayX.toFixed(2)} ${todayY.toFixed(2)} L${xOf(forecast.t).toFixed(2)} ${yOf(forecast.value).toFixed(2)}`}
              fill="none"
              stroke="rgba(255,255,255,0.6)"
              strokeWidth="1.6"
              strokeDasharray="1 5"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
        </svg>

        {/* Hoy: punto lleno. Previsión: punto hueco. */}
        <span
          className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-[0_0_0_4px_rgba(255,154,90,0.22),0_0_14px_rgba(255,170,110,0.9)]"
          style={{ left: `${todayX}%`, top: `${todayY}%` }}
          aria-hidden="true"
        />
        {forecast ? (
          <span
            className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white/80 bg-[#0b0b0b]"
            style={{ left: `${xOf(forecast.t)}%`, top: `${yOf(forecast.value)}%` }}
            aria-hidden="true"
          />
        ) : null}

        {shown ? (
          <>
            <span className="pointer-events-none absolute inset-y-0 w-px bg-white/25" style={{ left: `${shownX}%` }} aria-hidden="true" />
            <span
              className="pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#0b0b0b] bg-white"
              style={{ left: `${shownX}%`, top: `${yOf(shown.value)}%` }}
              aria-hidden="true"
            />
            <div
              className="pointer-events-none absolute top-0 z-10 whitespace-nowrap rounded-xl border border-white/10 bg-[#161616]/95 px-3 py-2 shadow-[0_12px_30px_rgba(0,0,0,0.6)] backdrop-blur"
              style={{
                left: `${shownX}%`,
                transform: `translateX(${shownX > 68 ? "calc(-100% - 10px)" : shownX < 32 ? "10px" : "-50%"})`,
              }}
              role="status"
            >
              <p className="text-[11px]" style={{ color: MUTED }}>
                {shown.forecast ? "Previsión a 7 días" : shown.label}
              </p>
              <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-white">{money(shown.value, 1)}</p>
              {shown !== history[0] ? (
                <p className="mt-0.5 text-[11.5px] tabular-nums" style={{ color: delta > 0 ? TONE.green : delta < 0 ? TONE.red : MUTED }}>
                  {signedMoney(delta)} {shown.forecast ? "sobre hoy" : `desde el ${history[0].label}`}
                </p>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
      </div>

      <div className="relative mr-12 mt-2 h-4 text-[11px] tabular-nums" style={{ color: MUTED }} aria-hidden="true">
        <span className="absolute left-0">{history[0].label}</span>
        {todayX > 22 && todayX < 80 ? (
          <span className="absolute -translate-x-1/2 font-medium text-white/75" style={{ left: `${todayX}%` }}>
            Hoy
          </span>
        ) : null}
        <span className="absolute right-0">{forecast ? "en 7 días" : "Hoy"}</span>
      </div>
    </div>
  );
}

/* ── Composición por posición ───────────────────────────────────────────── */

export type Slice = { id: string; label: string; value: number; count: number };

export function AllocationDonut({ slices, total }: { slices: Slice[]; total: number }) {
  const [active, setActive] = useState<string | null>(null);
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const gap = slices.length > 1 ? 2.4 : 0;
  const arcs = slices.map((slice, index) => {
    const before = slices.slice(0, index).reduce((sum, item) => sum + item.value, 0);
    const length = total > 0 ? (slice.value / total) * circumference : 0;
    const offset = total > 0 ? (before / total) * circumference : 0;
    return { slice, length, offset, color: POSITION_COLOR[slice.id] || OTHER_COLOR };
  });
  const focus = arcs.find((arc) => arc.slice.id === active) || null;

  return (
    <div className="flex items-center gap-5">
      <div className="relative h-[132px] w-[132px] shrink-0">
        <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90" role="img" aria-label="Reparto del valor de tu plantilla por posición">
          <circle cx="60" cy="60" r={radius} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="13" />
          {arcs.map((arc) => (
            <circle
              key={arc.slice.id}
              cx="60"
              cy="60"
              r={radius}
              fill="none"
              stroke={arc.color}
              strokeWidth={active === arc.slice.id ? 16 : 13}
              strokeDasharray={`${Math.max(0.5, arc.length - gap)} ${circumference}`}
              strokeDashoffset={-arc.offset}
              opacity={active && active !== arc.slice.id ? 0.3 : 1}
              className="cursor-pointer transition-[opacity,stroke-width] duration-200 ease-out"
              onPointerEnter={() => setActive(arc.slice.id)}
              onPointerLeave={() => setActive(null)}
            />
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="text-[1.35rem] font-semibold leading-none tabular-nums text-white">
            {focus ? `${Math.round((focus.slice.value / total) * 100)}%` : slices.reduce((sum, slice) => sum + slice.count, 0)}
          </span>
          <span className="mt-1 text-[11px]" style={{ color: MUTED }}>
            {focus ? focus.slice.label : "jugadores"}
          </span>
        </div>
      </div>

      <ul className="flex min-w-0 flex-1 flex-col gap-1">
        {arcs.map((arc) => {
          const share = total > 0 ? (arc.slice.value / total) * 100 : 0;
          return (
            <li
              key={arc.slice.id}
              className="flex items-center gap-2.5 rounded-lg px-1.5 py-1 transition-colors duration-200"
              style={{ background: active === arc.slice.id ? "rgba(255,255,255,0.05)" : undefined, opacity: active && active !== arc.slice.id ? 0.5 : 1 }}
              onPointerEnter={() => setActive(arc.slice.id)}
              onPointerLeave={() => setActive(null)}
            >
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: arc.color }} aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] text-white">{arc.slice.label}</span>
                <span className="block text-[11px] tabular-nums" style={{ color: MUTED }}>
                  {arc.slice.count} · {money(arc.slice.value, 1)}
                </span>
              </span>
              <span className="shrink-0 text-[13.5px] font-semibold tabular-nums" style={{ color: INK }}>
                {Math.round(share)}%
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ── Previsión por jugador ──────────────────────────────────────────────── */

export type ForecastRow = { id: string; name: string; delta: number; pct: number | null; today: number; next: number };

/** Barras divergentes: a la derecha del eje los que suben de valor, a la izquierda los que bajan. */
export function ForecastBars({ rows }: { rows: ForecastRow[] }) {
  const up = Math.max(0, ...rows.map((row) => row.delta));
  const down = Math.max(0, ...rows.map((row) => -row.delta));
  const span = up + down || 1;
  const zero = (down / span) * 100;
  return (
    <ul className="flex flex-col gap-[7px]">
      {rows.map((row) => {
        const width = Math.max(0.8, (Math.abs(row.delta) / span) * 100);
        const positive = row.delta >= 0;
        const flat = Math.abs(row.delta) < 1;
        return (
          <li
            key={row.id}
            className="grid grid-cols-[minmax(0,5.75rem)_minmax(0,1fr)_4.6rem] items-center gap-2.5"
            title={`${row.name}: ${money(row.today)} hoy → ${money(row.next)} en 7 días`}
          >
            <span className="truncate text-[12.5px] text-white/80">{row.name}</span>
            <span className="relative block h-3.5">
              <span className="absolute inset-y-[-3px] w-px bg-white/15" style={{ left: `${zero}%` }} aria-hidden="true" />
              {flat ? null : (
                <span
                  className="absolute inset-y-[3px] transition-[width] duration-700 ease-out"
                  style={{
                    left: positive ? `calc(${zero}% + 1px)` : `calc(${zero - width}% - 1px)`,
                    width: `${width}%`,
                    background: positive ? TONE.green : TONE.red,
                    borderRadius: positive ? "0 4px 4px 0" : "4px 0 0 4px",
                  }}
                />
              )}
            </span>
            <span className="text-right text-[12px] font-medium tabular-nums" style={{ color: flat ? MUTED : INK }}>
              {flat ? "=" : `${positive ? "▲" : "▼"} ${money(Math.abs(row.delta))}`}
              {row.pct !== null && !flat ? <span className="sr-only"> ({signedPct(row.pct)})</span> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/* ── Balance de la temporada ────────────────────────────────────────────── */

export type WaterfallStep = { label: string; value: number; hint?: string };

/** Cascada: cada barra arranca donde acabó la anterior; la última es el total. */
export function SeasonWaterfall({ steps }: { steps: WaterfallStep[] }) {
  const bars = steps.map((step, index) => {
    const start = steps.slice(0, index).reduce((sum, item) => sum + item.value, 0);
    return { ...step, start, end: start + step.value };
  });
  const total = steps.reduce((sum, step) => sum + step.value, 0);
  const lo = Math.min(0, ...bars.map((bar) => Math.min(bar.start, bar.end)));
  const hi = Math.max(0, ...bars.map((bar) => Math.max(bar.start, bar.end)));
  const span = hi - lo || 1;
  const at = (value: number) => ((value - lo) / span) * 100;
  const rows = [
    ...bars.map((bar) => ({ ...bar, isTotal: false })),
    { label: "Total", value: total, hint: undefined as string | undefined, start: 0, end: total, isTotal: true },
  ];
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row) => {
        const left = at(Math.min(row.start, row.end));
        const width = Math.max(0.8, (Math.abs(row.value) / span) * 100);
        const color = row.isTotal ? "rgba(255,255,255,0.85)" : row.value >= 0 ? TONE.green : TONE.red;
        return (
          <li key={row.label} className={row.isTotal ? "border-t border-white/[0.07] pt-3" : undefined}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0">
                <span className={`block truncate text-[13px] ${row.isTotal ? "font-semibold text-white" : "text-white/85"}`}>{row.label}</span>
                {row.hint ? (
                  <span className="block truncate text-[11px]" style={{ color: MUTED }}>
                    {row.hint}
                  </span>
                ) : null}
              </span>
              <span className={`shrink-0 tabular-nums text-white ${row.isTotal ? "text-[15px] font-semibold" : "text-[13.5px] font-medium"}`}>
                {signedMoney(row.value)}
              </span>
            </div>
            <div className="relative mt-1.5 h-2">
              <span className="absolute inset-y-[-2px] w-px bg-white/15" style={{ left: `${at(0)}%` }} aria-hidden="true" />
              <span
                className="absolute inset-y-0 rounded-[4px] transition-[width,left] duration-700 ease-out"
                style={{ left: `${left}%`, width: `${width}%`, background: color }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

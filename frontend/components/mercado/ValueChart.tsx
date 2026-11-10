"use client";

import { useId, useMemo, useRef, useState } from "react";
import { TONE, money, signedPct } from "@/components/ui/kit";
import { MONTHS } from "@/lib/core/format";

const DAY_MS = 86_400_000;
const HORIZON = 7;
const W = 600;
const H = 200;
const PAD_X = 6;
const PAD_TOP = 22;
const PAD_BOTTOM = 18;
/** Separación mínima, en px, entre dos etiquetas del eje de precios. */
const TAG_GAP = 18;

type Point = { t: number; value: number; future?: boolean };

function dayStart(ms: number): number {
  const date = new Date(ms);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

function parseDay(day: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(day);
  if (!match) return null;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function dateLabel(t: number): string {
  const date = new Date(t);
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}

/** Curva suave que pasa por todos los puntos (Catmull-Rom a Bézier, sin sobrepasar). */
function smooth(points: Array<[number, number]>): string {
  if (!points.length) return "";
  if (points.length < 3) return points.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  let path = `M${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const p0 = points[index - 1] ?? points[index];
    const p1 = points[index];
    const p2 = points[index + 1];
    const p3 = points[index + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    // Los controles no salen del rango vertical del tramo: sin picos inventados.
    const lo = Math.min(p1[1], p2[1]);
    const hi = Math.max(p1[1], p2[1]);
    path += ` C${c1x.toFixed(1)} ${Math.max(lo, Math.min(hi, c1y)).toFixed(1)} ${c2x.toFixed(1)} ${Math.max(lo, Math.min(hi, c2y)).toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return path;
}

/**
 * Valor guardado día a día y la previsión a 7 días en su sitio del calendario:
 * la zona de futuro mide 7 días igual que el pasado, así la pendiente es real.
 * A la derecha, un eje de precios con el valor de hoy y el previsto marcados.
 */
export function ValueChart({
  history,
  today,
  forecast,
  trendPct,
}: {
  history: { day: string; value: number }[];
  today: number | null;
  forecast: number | null;
  trendPct: number | null;
}) {
  const id = useId().replace(/:/g, "");
  const box = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [mountedAt] = useState(() => Date.now());

  const model = useMemo(() => {
    const now = dayStart(mountedAt);
    const past: Point[] = [];
    for (const row of history) {
      const t = parseDay(row.day);
      if (t === null || typeof row.value !== "number" || t > now) continue;
      if (past.length && past.at(-1)!.t === t) past[past.length - 1] = { t, value: row.value };
      else past.push({ t, value: row.value });
    }
    past.sort((a, b) => a.t - b.t);
    if (today !== null) {
      if (past.length && past.at(-1)!.t === now) past[past.length - 1] = { t: now, value: today };
      else past.push({ t: now, value: today });
    }
    if (!past.length) return null;
    const last = past.at(-1)!;
    const future: Point | null = forecast !== null ? { t: last.t + HORIZON * DAY_MS, value: forecast, future: true } : null;
    const start = past.length > 1 ? past[0].t : last.t - HORIZON * DAY_MS;
    const end = future ? future.t : last.t;
    const values = [...past.map((point) => point.value), ...(future ? [future.value] : [])];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || Math.max(1, max * 0.02);
    const lo = min - span * 0.12;
    const hi = max + span * 0.12;
    const x = (t: number) => PAD_X + ((t - start) / Math.max(1, end - start)) * (W - PAD_X * 2);
    const y = (value: number) => PAD_TOP + (1 - (value - lo) / (hi - lo)) * (H - PAD_TOP - PAD_BOTTOM);
    return { past, future, last, min, max, x, y };
  }, [history, today, forecast, mountedAt]);

  if (!model) return <p className="py-6 text-center text-[13px] text-white/45">Sin histórico de valor guardado.</p>;

  const { past, future, last, min, max, x, y } = model;
  const pts = past.map((point) => [x(point.t), y(point.value)] as [number, number]);
  const line = smooth(pts);
  const area = pts.length > 1 ? `${line} L${pts.at(-1)![0].toFixed(1)} ${H} L${pts[0][0].toFixed(1)} ${H} Z` : "";
  const flat = trendPct === null || Math.abs(trendPct) < 0.05;
  const futureColor = flat ? "rgba(255,255,255,0.6)" : future && future.value < last.value ? TONE.red : TONE.green;
  const fx = future ? x(future.t) : null;
  const fy = future ? y(future.value) : null;
  const tx = x(last.t);
  const ty = y(last.value);
  const all: Point[] = [...past, ...(future ? [future] : [])];
  const active = hover !== null ? all[hover] : null;
  const pctX = (px: number) => `${(px / W) * 100}%`;

  // Eje de precios: hoy y previsto mandan; las guías se callan si chocan con ellos.
  const todayTagY = fy !== null && Math.abs(ty - fy) < TAG_GAP ? (fy > ty ? fy - TAG_GAP : fy + TAG_GAP) : ty;
  const guides = (max > min ? [max, (max + min) / 2, min] : [max]).map((value) => ({ value, py: y(value) }));
  const shownGuides = guides.filter((guide) => Math.abs(guide.py - todayTagY) >= TAG_GAP && (fy === null || Math.abs(guide.py - fy) >= TAG_GAP));

  const onMove = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return;
    const px = ((clientX - rect.left) / rect.width) * W;
    let best = 0;
    for (let index = 1; index < all.length; index += 1) {
      if (Math.abs(x(all[index].t) - px) < Math.abs(x(all[best].t) - px)) best = index;
    }
    setHover(best);
  };

  const activeDelta = active && active.t !== last.t && last.value ? ((active.value - last.value) / last.value) * 100 : null;

  return (
    <div>
      <div className="flex">
        <div
          ref={box}
          className="relative min-w-0 flex-1 touch-pan-y select-none"
          style={{ height: H }}
          onPointerMove={(event) => onMove(event.clientX)}
          onPointerDown={(event) => onMove(event.clientX)}
          onPointerLeave={() => setHover(null)}
        >
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-full w-full" role="img" aria-label="Evolución del valor y previsión a 7 días">
            <defs>
              <linearGradient id={`${id}-area`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor="#fff" stopOpacity="0.13" />
                <stop offset="1" stopColor="#fff" stopOpacity="0" />
              </linearGradient>
              <linearGradient id={`${id}-line`} x1="0" x2="1" y1="0" y2="0">
                <stop offset="0" stopColor="#fff" stopOpacity="0.45" />
                <stop offset="1" stopColor="#fff" />
              </linearGradient>
              <linearGradient id={`${id}-future`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor={futureColor} stopOpacity="0.16" />
                <stop offset="1" stopColor={futureColor} stopOpacity="0" />
              </linearGradient>
            </defs>
            {guides.map((guide) => (
              <line key={guide.value} x1="0" x2={W} y1={guide.py} y2={guide.py} stroke="rgba(255,255,255,0.06)" vectorEffect="non-scaling-stroke" />
            ))}
            {future && fx !== null && fy !== null ? (
              <>
                <path d={`M${tx} ${ty} L${fx} ${fy} L${fx} ${H} L${tx} ${H} Z`} fill={`url(#${id}-future)`} />
                <line x1={tx} x2={tx} y1={PAD_TOP - 8} y2={H} stroke="rgba(255,255,255,0.16)" strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
                <path
                  d={`M${tx} ${ty} L${fx} ${fy}`}
                  fill="none"
                  stroke={futureColor}
                  strokeWidth="2"
                  strokeDasharray="1 6"
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                />
              </>
            ) : null}
            {area ? <path d={area} fill={`url(#${id}-area)`} /> : null}
            {pts.length > 1 ? (
              <path d={line} fill="none" stroke={`url(#${id}-line)`} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            ) : null}
            {active ? (
              <line x1={x(active.t)} x2={x(active.t)} y1="0" y2={H} stroke="rgba(255,255,255,0.2)" vectorEffect="non-scaling-stroke" />
            ) : null}
          </svg>

          <span
            className="pointer-events-none absolute h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-white"
            style={{ left: pctX(tx), top: ty, boxShadow: "0 0 0 4px rgba(255,255,255,0.14)" }}
            aria-hidden="true"
          />
          {future && fx !== null && fy !== null ? (
            <span
              className="pointer-events-none absolute h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-black"
              style={{ left: pctX(fx), top: fy, borderColor: futureColor }}
              aria-hidden="true"
            />
          ) : null}
          {active && active.t !== last.t && !active.future ? (
            <span
              className="pointer-events-none absolute h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-black"
              style={{ left: pctX(x(active.t)), top: y(active.value) }}
              aria-hidden="true"
            />
          ) : null}
          {active ? (
            <span
              className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 whitespace-nowrap rounded-lg bg-[#1a1a1a] px-2.5 py-1.5 text-center shadow-[0_10px_24px_-8px_rgba(0,0,0,0.9),inset_0_0_0_1px_rgba(255,255,255,0.08)]"
              style={{ left: `clamp(3.75rem, ${pctX(x(active.t))}, calc(100% - 3.75rem))` }}
            >
              <span className="block text-[10.5px] text-white/45">
                {active.future ? `Previsto ${dateLabel(active.t)}` : active.t === last.t ? "Hoy" : dateLabel(active.t)}
              </span>
              <span className="block text-[13px] font-semibold tabular-nums text-white">{money(active.value)}</span>
              {activeDelta !== null ? (
                <span
                  className="block text-[10.5px] tabular-nums"
                  style={{ color: Math.abs(activeDelta) < 0.05 ? "rgba(255,255,255,0.45)" : activeDelta > 0 ? TONE.green : TONE.red }}
                >
                  {signedPct(activeDelta)} frente a hoy
                </span>
              ) : null}
            </span>
          ) : null}
        </div>

        <div className="relative w-[3.75rem] shrink-0 text-[10.5px] tabular-nums" style={{ height: H }} aria-hidden="true">
          {shownGuides.map((guide) => (
            <span key={guide.value} className="absolute right-0 -translate-y-1/2 whitespace-nowrap text-white/30" style={{ top: guide.py }}>
              {money(guide.value)}
            </span>
          ))}
          <span className="absolute right-0 -translate-y-1/2 whitespace-nowrap font-semibold text-white" style={{ top: todayTagY }}>
            {money(last.value)}
          </span>
          {future && fy !== null ? (
            <span className="absolute right-0 -translate-y-1/2 whitespace-nowrap font-semibold" style={{ top: fy, color: futureColor }}>
              {money(future.value)}
            </span>
          ) : null}
        </div>
      </div>

      <div className="relative mr-[3.75rem] mt-2 h-4 text-[10.5px] tabular-nums text-white/35">
        {past.length > 1 && tx / W > 0.22 ? <span className="absolute left-0">{dateLabel(past[0].t)}</span> : null}
        <span className="absolute -translate-x-1/2 font-medium text-white/70" style={{ left: pctX(tx) }}>
          Hoy
        </span>
        {future ? <span className="absolute right-0">{dateLabel(future.t)}</span> : null}
      </div>
    </div>
  );
}

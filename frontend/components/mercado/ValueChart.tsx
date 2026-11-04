"use client";

import { useId, useMemo, useRef, useState } from "react";
import { TONE, money, signedPct } from "@/components/ui/kit";
import { MONTHS } from "@/lib/core/format";

const DAY_MS = 86_400_000;
const HORIZON = 7;
const W = 600;
const H = 190;
const PAD_X = 10;
const PAD_TOP = 18;
const PAD_BOTTOM = 14;

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
    const lo = min - span * 0.18;
    const hi = max + span * 0.18;
    const x = (t: number) => PAD_X + ((t - start) / Math.max(1, end - start)) * (W - PAD_X * 2);
    const y = (value: number) => PAD_TOP + (1 - (value - lo) / (hi - lo)) * (H - PAD_TOP - PAD_BOTTOM);
    return { past, future, last, start, end, x, y, now: last.t };
  }, [history, today, forecast, mountedAt]);

  if (!model) return <p className="py-6 text-center text-[13px] text-white/45">Sin histórico de valor guardado.</p>;

  const { past, future, last, x, y } = model;
  const pts = past.map((point) => [x(point.t), y(point.value)] as [number, number]);
  const line = smooth(pts);
  const area = pts.length > 1 ? `${line} L${pts.at(-1)![0].toFixed(1)} ${H} L${pts[0][0].toFixed(1)} ${H} Z` : "";
  const up = future ? future.value >= last.value : true;
  const futureColor = trendPct === null || Math.abs(trendPct) < 0.05 ? "rgba(255,255,255,0.6)" : up ? TONE.green : TONE.red;
  const fx = future ? x(future.t) : null;
  const fy = future ? y(future.value) : null;
  const tx = x(last.t);
  const ty = y(last.value);
  const all: Point[] = [...past, ...(future ? [future] : [])];
  const active = hover !== null ? all[hover] : null;
  const pctX = (px: number) => `${(px / W) * 100}%`;
  const pctY = (px: number) => `${(px / H) * 100}%`;

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

  return (
    <div>
      <div
        ref={box}
        className="relative touch-pan-y select-none"
        onPointerMove={(event) => onMove(event.clientX)}
        onPointerDown={(event) => onMove(event.clientX)}
        onPointerLeave={() => setHover(null)}
      >
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-[190px] w-full" role="img" aria-label="Evolución del valor y previsión a 7 días">
          <defs>
            <linearGradient id={`${id}-area`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#FF7A3D" stopOpacity="0.32" />
              <stop offset="1" stopColor="#FF7A3D" stopOpacity="0" />
            </linearGradient>
            <linearGradient id={`${id}-line`} x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="#FF6A2B" stopOpacity="0.55" />
              <stop offset="1" stopColor="#FFC08A" />
            </linearGradient>
            <linearGradient id={`${id}-future`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor={futureColor} stopOpacity="0.22" />
              <stop offset="1" stopColor={futureColor} stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0.33, 0.66].map((share) => (
            <line key={share} x1="0" x2={W} y1={H * share} y2={H * share} stroke="rgba(255,255,255,0.045)" vectorEffect="non-scaling-stroke" />
          ))}
          {future && fx !== null && fy !== null ? (
            <>
              <rect x={tx} y="0" width={W - tx} height={H} fill="rgba(255,255,255,0.025)" />
              <path d={`M${tx} ${ty} L${fx} ${fy} L${fx} ${H} L${tx} ${H} Z`} fill={`url(#${id}-future)`} />
              <line x1={tx} x2={tx} y1="0" y2={H} stroke="rgba(255,255,255,0.14)" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
              <path
                d={`M${tx} ${ty} L${fx} ${fy}`}
                fill="none"
                stroke={futureColor}
                strokeWidth="2.4"
                strokeDasharray="2 6"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            </>
          ) : null}
          {area ? <path d={area} fill={`url(#${id}-area)`} /> : null}
          {pts.length > 1 ? (
            <path d={line} fill="none" stroke={`url(#${id}-line)`} strokeWidth="2.6" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          ) : null}
          {active ? (
            <line x1={x(active.t)} x2={x(active.t)} y1="0" y2={H} stroke="rgba(255,255,255,0.22)" vectorEffect="non-scaling-stroke" />
          ) : null}
        </svg>

        <span
          className="pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#0b0b0b] bg-white"
          style={{ left: pctX(tx), top: pctY(ty), boxShadow: "0 0 14px rgba(255,170,110,0.9)" }}
          aria-hidden="true"
        />
        {future && fx !== null && fy !== null ? (
          <>
            <span
              className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{ left: pctX(fx - 1), top: pctY(fy), background: futureColor, boxShadow: `0 0 0 4px ${futureColor}33` }}
              aria-hidden="true"
            />
            {!active ? (
              <span
                className="pointer-events-none absolute -translate-x-full whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-semibold tabular-nums backdrop-blur-md"
                style={{
                  left: pctX(fx - 8),
                  top: pctY(fy < 40 ? fy + 12 : fy - 34),
                  color: futureColor,
                  background: "rgba(11,11,11,0.7)",
                  boxShadow: `inset 0 0 0 1px ${futureColor}44`,
                }}
              >
                {money(future.value)}
              </span>
            ) : null}
          </>
        ) : null}
        {active ? (
          <span
            className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 whitespace-nowrap rounded-xl bg-[#1c1c1e] px-2.5 py-1.5 text-center shadow-[0_10px_24px_-8px_rgba(0,0,0,0.9)]"
            style={{ left: `clamp(3.5rem, ${pctX(x(active.t))}, calc(100% - 3.5rem))` }}
          >
            <span className="block text-[10.5px] text-white/45">
              {active.future ? `Previsto ${dateLabel(active.t)}` : active.t === last.t ? "Hoy" : dateLabel(active.t)}
            </span>
            <span className="block text-[13px] font-semibold tabular-nums" style={{ color: active.future ? futureColor : "#fff" }}>
              {money(active.value)}
            </span>
          </span>
        ) : null}
      </div>
      <div className="relative mt-2 h-4 text-[10.5px] tabular-nums text-white/35">
        {past.length > 1 ? <span className="absolute left-0">{dateLabel(past[0].t)}</span> : null}
        <span className="absolute -translate-x-1/2 font-medium text-white/60" style={{ left: pctX(tx) }}>
          Hoy
        </span>
        {future ? (
          <span className="absolute right-0" style={{ color: futureColor }}>
            +7 días{trendPct !== null ? ` · ${signedPct(trendPct)}` : ""}
          </span>
        ) : null}
      </div>
    </div>
  );
}

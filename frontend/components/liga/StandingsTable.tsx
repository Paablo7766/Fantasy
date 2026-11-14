"use client";

import { useMemo, useState } from "react";
import { points } from "@/lib/core/format";
import type { LeagueFormRow } from "@/lib/types";
import { TONE, money, signedMoney, signedPct, toneOf } from "@/components/ui/kit";
import { CardHead } from "./parts";

export type StandingRow = {
  id: string;
  self: boolean;
  name: string;
  team: string | null;
  rank: number | null;
  points: number | null;
  /** Puntos de este mánager menos los tuyos. */
  gap: number | null;
  form: LeagueFormRow | null;
  /** Puntos esperados de su mejor once en la próxima jornada. */
  projection: number | null;
  ceiling: number | null;
  cash: number | null;
  bidLimit: number | null;
  /** Valor de mercado de la plantilla, sin la caja. */
  teamValue: number | null;
  /** Lo que ha cambiado hoy el valor de la plantilla. */
  delta: number | null;
};

type Metric = "points" | "form" | "projection" | "cash" | "value" | "patrimonio" | "delta";

const METRICS: { id: Metric; label: string }[] = [
  { id: "points", label: "Puntos" },
  { id: "delta", label: "Subida de hoy" },
  { id: "patrimonio", label: "Patrimonio" },
  { id: "value", label: "Valor del equipo" },
  { id: "cash", label: "Caja" },
  { id: "form", label: "Forma" },
  { id: "projection", label: "Próxima jornada" },
];

/** Caja + valor de la plantilla. Sin valor de plantilla no hay patrimonio que comparar. */
function patrimonioOf(row: StandingRow): number | null {
  return row.teamValue === null ? null : row.teamValue + (row.cash ?? 0);
}

function metricValue(row: StandingRow, metric: Metric): number | null {
  if (metric === "patrimonio") return patrimonioOf(row);
  if (metric === "form") return row.form?.recent_avg ?? null;
  if (metric === "projection") return row.projection;
  if (metric === "cash") return row.cash;
  if (metric === "value") return row.teamValue;
  if (metric === "delta") return row.delta;
  return row.points;
}

/** Qué mide cada vista, en una frase: se enseña bajo el selector. */
function helpText(metric: Metric, window: number): string {
  if (metric === "delta") return "Cuánto ha subido o bajado hoy el valor de mercado de cada plantilla.";
  if (metric === "patrimonio") return "Todo lo que tiene cada mánager: caja más valor de mercado de la plantilla. La caja de los rivales es una estimación.";
  if (metric === "value") return "Lo que vale en el mercado la plantilla de cada mánager, sin contar su caja.";
  if (metric === "cash") return "Dinero que tiene cada uno para fichar. La de los rivales es una estimación a partir de sus movimientos.";
  if (metric === "form") return `Quién viene en racha: media de puntos por jornada en las últimas ${window}, no en toda la temporada.`;
  if (metric === "projection") return "Puntos que se esperan del mejor once de cada mánager en la próxima jornada. El techo es lo que haría si todo le sale bien.";
  return "La clasificación de la liga: puntos acumulados y a cuánto está cada uno de ti.";
}

function mainText(row: StandingRow, metric: Metric): string {
  const value = metricValue(row, metric);
  if (value === null) return "—";
  if (metric === "points") return String(value);
  if (metric === "form" || metric === "projection") return points(value);
  if (metric === "delta") return signedMoney(value);
  return money(value);
}

function subText(row: StandingRow, metric: Metric, leaderGap: number | null, window: number): string | null {
  if (metric === "points") {
    if (row.self) return leaderGap === null ? null : leaderGap === 0 ? "líder" : `a ${leaderGap} del líder`;
    if (row.gap === null) return null;
    return row.gap === 0 ? "empatado contigo" : `${Math.abs(row.gap)} ${row.gap > 0 ? "más" : "menos"} que tú`;
  }
  if (metric === "form") {
    const last = (row.form?.rounds || []).slice(-window);
    return last.length ? `últimas: ${last.map((item) => item.points).join(" · ")}` : "sin jornadas";
  }
  if (metric === "projection") return row.projection === null ? "sin once" : row.ceiling !== null ? `techo ${points(row.ceiling)}` : "pts esperados";
  if (metric === "cash") return row.bidLimit !== null ? `puja hasta ${money(row.bidLimit)}` : null;
  if (metric === "patrimonio") return row.teamValue === null ? null : `plantilla ${money(row.teamValue)} · caja ${row.cash === null ? "—" : money(row.cash)}`;
  if (metric === "value") return typeof row.delta === "number" && Math.abs(row.delta) >= 1 ? `${signedMoney(row.delta)} hoy` : "sin cambio hoy";
  if (row.delta !== null && row.teamValue) return `${signedPct((row.delta / (row.teamValue - row.delta)) * 100, 2)} de su valor`;
  return null;
}

/** Barra de la fila: de 0 al máximo de la liga; la subida de hoy crece desde el centro, verde o roja. */
function Bar({ value, top, metric, self, className = "" }: { value: number | null; top: number; metric: Metric; self: boolean; className?: string }) {
  const share = value === null || top <= 0 ? 0 : Math.min(1, Math.abs(value) / top);
  if (metric === "delta") {
    const up = (value ?? 0) >= 0;
    return (
      <span className={`relative block h-1.5 overflow-hidden rounded-full bg-white/[0.06] ${className}`} aria-hidden="true">
        <span className="absolute inset-y-0 left-1/2 w-px bg-white/25" />
        <span
          className="absolute inset-y-0 rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${share * 50}%`, background: up ? TONE.green : TONE.red, ...(up ? { left: "50%" } : { right: "50%" }) }}
        />
      </span>
    );
  }
  return (
    <span className={`block h-1.5 overflow-hidden rounded-full bg-white/[0.06] ${className}`} aria-hidden="true">
      <span
        className="block h-full rounded-full transition-[width] duration-500 ease-out"
        style={{ width: `${value !== null && value > 0 ? Math.max(2, share * 100) : 0}%`, background: self ? "#FFC08A" : "rgba(255,255,255,0.5)" }}
      />
    </span>
  );
}

const GRID =
  "grid grid-cols-[1.5rem_minmax(0,1fr)_auto_1rem] items-center gap-x-3 min-[900px]:grid-cols-[1.5rem_minmax(0,14rem)_minmax(0,1fr)_minmax(7.5rem,auto)_1rem] min-[900px]:gap-x-6";

/**
 * La liga ordenada por lo que elijas: puntos, subida de hoy, valor, caja, forma
 * o lo que se espera la próxima jornada. La cifra elegida es la grande de cada
 * fila y la barra la compara con el resto de un vistazo.
 */
export function StandingsTable({
  rows,
  window,
  leaderGap,
  onOpen,
}: {
  rows: StandingRow[];
  window: number;
  /** Puntos que te saca el líder (0 si lo eres tú). */
  leaderGap: number | null;
  onOpen: (id: string) => void;
}) {
  const [metric, setMetric] = useState<Metric>("points");

  const sorted = useMemo(() => {
    return rows.slice().sort((a, b) => {
      const left = metricValue(a, metric);
      const right = metricValue(b, metric);
      if (left === null && right === null) return (a.rank ?? 999) - (b.rank ?? 999);
      if (left === null) return 1;
      if (right === null) return -1;
      return right - left || (a.rank ?? 999) - (b.rank ?? 999);
    });
  }, [rows, metric]);

  const top = Math.max(0, ...rows.map((row) => Math.abs(metricValue(row, metric) ?? 0)));

  return (
    <section className="home-glass overflow-hidden" aria-label="Clasificación">
      <CardHead title="Clasificación" count={rows.length} caption="Elige qué comparar. Toca un mánager para ver su plantilla." />

      <div className="flex gap-5 overflow-x-auto border-b border-white/[0.06] px-4 [scrollbar-width:none] min-[900px]:px-5" role="tablist" aria-label="Qué comparar">
        {METRICS.map((item) => {
          const on = metric === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => setMetric(item.id)}
              className={`relative shrink-0 whitespace-nowrap pb-3 pt-2 text-[13.5px] transition-colors duration-200 ${on ? "font-semibold text-white" : "text-white/50 hover:text-white/80"}`}
            >
              {item.label}
              {on ? <span className="absolute inset-x-0 bottom-0 h-[2px] rounded-full bg-peach" aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      <p className="px-4 py-3 text-[12.5px] leading-snug text-white/45 min-[900px]:px-5">{helpText(metric, window)}</p>

      <ul key={metric} className="divide-y divide-white/[0.05] border-t border-white/[0.06]">
        {sorted.map((row, index) => {
          const value = metricValue(row, metric);
          const tone = metric === "delta" ? toneOf(value) : metric === "cash" && value !== null && value < 0 ? TONE.red : "#fff";
          const sub = subText(row, metric, leaderGap, window);
          return (
            <li key={row.id} className="row-in" style={{ animationDelay: `${Math.min(index, 14) * 20}ms` }}>
              <button
                type="button"
                onClick={() => onOpen(row.id)}
                className={`${GRID} w-full px-4 py-3 text-left transition-colors duration-200 hover:bg-white/[0.035] min-[900px]:px-5 ${row.self ? "bg-white/[0.045]" : ""}`}
              >
                <span className="text-[14px] font-medium tabular-nums" style={{ color: row.self ? "#FFC08A" : "rgba(255,255,255,0.5)" }}>
                  {value === null ? "—" : index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[14.5px] font-medium text-white">
                    {row.name}
                    {row.self ? <span className="ml-1.5 text-[12px] font-normal text-peach">Tú</span> : null}
                  </span>
                  {metric !== "points" && row.rank !== null ? (
                    <span className="mt-0.5 hidden truncate text-[11.5px] tabular-nums text-white/40 min-[900px]:block">
                      {row.rank}º en la liga{row.points !== null ? ` · ${row.points} pts` : ""}
                    </span>
                  ) : null}
                  <Bar value={value} top={top} metric={metric} self={row.self} className="mt-2 min-[900px]:hidden" />
                </span>
                <Bar value={value} top={top} metric={metric} self={row.self} className="hidden min-[900px]:block" />
                <span className="min-w-0 text-right">
                  <span className="block truncate text-[16px] font-semibold tabular-nums" style={{ color: tone }}>
                    {mainText(row, metric)}
                  </span>
                  {sub ? <span className="mt-0.5 block truncate text-[11.5px] tabular-nums text-white/40">{sub}</span> : null}
                </span>
                <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-white/25" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                  <path d="m6 4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

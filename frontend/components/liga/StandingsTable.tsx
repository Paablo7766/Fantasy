"use client";

import { useMemo, useState } from "react";
import { points } from "@/lib/core/format";
import type { LeagueFormRow } from "@/lib/types";
import { TONE, money, signedMoney, toneOf } from "@/components/ui/kit";
import { CardHead, Cell } from "./parts";

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
  value: number | null;
  delta: number | null;
};

type Sort = "points" | "form" | "projection" | "cash" | "value";

const SORTS: { id: Sort; label: string }[] = [
  { id: "points", label: "Puntos" },
  { id: "form", label: "Forma" },
  { id: "projection", label: "Próx. jornada" },
  { id: "cash", label: "Caja" },
  { id: "value", label: "Patrimonio" },
];

/** En móvil, puesto, mánager y puntos; en escritorio, todas las columnas. */
const GRID =
  "grid grid-cols-[1.5rem_minmax(0,1fr)_auto_1rem] items-center gap-x-3 min-[900px]:grid-cols-[1.5rem_minmax(0,2fr)_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.1fr)_1rem] min-[900px]:gap-x-5";

function sortValue(row: StandingRow, sort: Sort): number | null {
  if (sort === "form") return row.form?.recent_avg ?? null;
  if (sort === "projection") return row.projection;
  if (sort === "cash") return row.cash;
  if (sort === "value") return row.value;
  return row.points;
}

/** Puntos de las últimas jornadas, a la misma escala para toda la liga; la última, a pleno color. */
function FormBars({ row, top, window, self }: { row: LeagueFormRow; top: number; window: number; self: boolean }) {
  const shown = row.rounds.slice(-window);
  return (
    <span className="flex h-6 shrink-0 items-end gap-[3px]" aria-hidden="true">
      {shown.map((item, index) => (
        <span
          key={item.round}
          title={`J${item.round}: ${item.points} pts`}
          className="w-[5px] rounded-[2px]"
          style={{
            height: `${Math.max(12, (item.points / top) * 100)}%`,
            background: self ? "#FFC08A" : "#fff",
            opacity: index === shown.length - 1 ? (self ? 1 : 0.75) : self ? 0.45 : 0.25,
          }}
        />
      ))}
    </span>
  );
}

function gapText(row: StandingRow, leaderGap: number | null): string | null {
  if (row.self) return leaderGap === null ? null : leaderGap === 0 ? "líder" : `a ${Math.abs(leaderGap)} del líder`;
  if (row.gap === null) return null;
  if (row.gap === 0) return "empatado contigo";
  return `${Math.abs(row.gap)} ${row.gap > 0 ? "más" : "menos"} que tú`;
}

/**
 * La clasificación como una sola tabla: puntos, forma reciente, lo que se
 * espera de cada once y el dinero de cada mánager. Cada columna ordena.
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
  const [sort, setSort] = useState<Sort>("points");
  const [ascending, setAscending] = useState(false);

  const sorted = useMemo(() => {
    return rows.slice().sort((a, b) => {
      const left = sortValue(a, sort);
      const right = sortValue(b, sort);
      if (left === null && right === null) return (a.rank ?? 999) - (b.rank ?? 999);
      if (left === null) return 1;
      if (right === null) return -1;
      const diff = ascending ? left - right : right - left;
      return diff || (a.rank ?? 999) - (b.rank ?? 999);
    });
  }, [rows, sort, ascending]);

  const top = Math.max(1, ...rows.flatMap((row) => (row.form?.rounds || []).slice(-window).map((item) => item.points)));
  const hasForm = rows.some((row) => row.form);
  const hasProjection = rows.some((row) => row.projection !== null);

  return (
    <section className="home-glass overflow-hidden" aria-label="Clasificación">
      <CardHead title="Clasificación" count={rows.length} caption="Toca un mánager para ver su plantilla y sus movimientos.">
        <label className="shrink-0 min-[900px]:hidden">
          <span className="sr-only">Ordenar por</span>
          <select
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as Sort);
              setAscending(false);
            }}
            className="h-8 rounded-full bg-white/[0.06] px-2.5 text-[12.5px] text-white outline-none"
          >
            {SORTS.map((item) => (
              <option key={item.id} value={item.id} className="bg-[#141414]">
                {item.label}
              </option>
            ))}
          </select>
        </label>
      </CardHead>

      {/* Cada columna ordena, y repetir el clic invierte el sentido. */}
      <div className={`${GRID} hidden border-y border-white/[0.06] px-5 py-2 min-[900px]:grid`}>
        <span className="text-[11.5px] text-white/40">#</span>
        <span className="text-[11.5px] text-white/40">Mánager</span>
        {SORTS.map((item) => {
          const on = sort === item.id;
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={on}
              aria-label={`Ordenar por ${item.label}${on ? (ascending ? ", de menor a mayor" : ", de mayor a menor") : ""}`}
              onClick={() => {
                if (on) setAscending((state) => !state);
                else {
                  setSort(item.id);
                  setAscending(false);
                }
              }}
              className={`inline-flex items-center justify-end gap-1 text-right text-[11.5px] transition-colors duration-200 ${on ? "font-semibold text-white" : "text-white/40 hover:text-white/75"}`}
            >
              {item.label}
              <svg viewBox="0 0 8 8" className={`h-2 w-2 transition-transform duration-300 ${on ? "opacity-100" : "opacity-0"} ${ascending ? "rotate-180" : ""}`} aria-hidden="true">
                <path d="M1 2.5 4 6l3-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          );
        })}
        <span aria-hidden="true" />
      </div>

      <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06] min-[900px]:border-t-0">
        {sorted.map((row, index) => {
          const trend = row.form?.trend;
          const up = typeof trend === "number" && trend > 0.5;
          const down = typeof trend === "number" && trend < -0.5;
          const slim =
            sort === "form" && row.form
              ? `${points(row.form.recent_avg)} pts de media`
              : sort === "projection" && row.projection !== null
                ? `${points(row.projection)} pts previstos`
                : sort === "value"
                  ? `Patrimonio ${money(row.value)}`
                  : `Caja ${money(row.cash)}`;
          return (
            <li key={row.id} className="row-in" style={{ animationDelay: `${Math.min(index, 14) * 25}ms` }}>
              <button
                type="button"
                onClick={() => onOpen(row.id)}
                className={`${GRID} w-full px-4 py-3 text-left transition-colors duration-200 hover:bg-white/[0.035] min-[900px]:px-5 ${row.self ? "bg-white/[0.045]" : ""}`}
              >
                <span className="text-[14px] font-medium tabular-nums" style={{ color: row.self ? "#FFC08A" : "rgba(255,255,255,0.5)" }}>
                  {row.rank ?? "—"}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[14.5px] font-medium text-white">
                    {row.name}
                    {row.self ? <span className="ml-1.5 text-[12px] font-normal text-[#FFC08A]">Tú</span> : null}
                  </span>
                  <span className="mt-0.5 block truncate text-[11.5px] tabular-nums text-white/40 min-[900px]:hidden">{slim}</span>
                  {row.team ? <span className="mt-0.5 hidden truncate text-[11.5px] text-white/40 min-[900px]:block">{row.team}</span> : null}
                </span>
                <Cell value={row.points !== null ? String(row.points) : "—"} sub={gapText(row, leaderGap)} strong />
                <span className="hidden min-w-0 items-center justify-end gap-2.5 min-[900px]:flex">
                  {row.form ? (
                    <>
                      <FormBars row={row.form} top={top} window={window} self={row.self} />
                      <span className="w-[3.4rem] shrink-0 text-right">
                        <span className="block text-[14px] font-medium tabular-nums text-white">{points(row.form.recent_avg)}</span>
                        <span className="mt-0.5 block text-[11.5px] tabular-nums" style={{ color: up ? TONE.green : down ? TONE.red : "rgba(255,255,255,0.4)" }}>
                          {typeof trend === "number" ? (up ? `▲ ${points(trend)}` : down ? `▼ ${points(-trend)}` : "estable") : "—"}
                        </span>
                      </span>
                    </>
                  ) : (
                    <span className="text-[14px] text-white/40">—</span>
                  )}
                </span>
                <Cell
                  className="hidden min-[900px]:block"
                  value={row.projection !== null ? points(row.projection) : "—"}
                  sub={row.ceiling !== null ? `techo ${points(row.ceiling)}` : null}
                />
                <Cell className="hidden min-[900px]:block" value={money(row.cash)} tone={row.cash !== null && row.cash < 0 ? TONE.red : undefined} />
                <Cell
                  className="hidden min-[900px]:block"
                  value={money(row.value)}
                  sub={typeof row.delta === "number" && Math.abs(row.delta) >= 1 ? `${signedMoney(row.delta)} hoy` : null}
                  subTone={toneOf(row.delta)}
                />
                <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-white/25" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                  <path d="m6 4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </li>
          );
        })}
      </ul>

      <p className="border-t border-white/[0.06] px-4 py-3 text-[12px] leading-relaxed text-white/35 min-[900px]:px-5">
        {[
          hasForm ? `Forma: media de puntos de las últimas ${window} jornadas y si la última fue mejor o peor que las anteriores.` : null,
          hasProjection ? "Próx. jornada: puntos esperados de su mejor once." : null,
          "La caja de los rivales es una estimación a partir de sus movimientos.",
        ]
          .filter(Boolean)
          .join(" ")}
      </p>
    </section>
  );
}

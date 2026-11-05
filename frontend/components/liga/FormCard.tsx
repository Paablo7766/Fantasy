"use client";

import { points } from "@/lib/core/format";
import type { LeagueFormPayload, LeagueFormRow } from "@/lib/types";
import { Disclosure, TONE } from "@/components/ui/kit";

const nameOf = (row: LeagueFormRow) => row.manager_name || row.fantasy_team_name || "Rival";

/** Barras de las últimas jornadas, a la misma escala para toda la liga. */
function Bars({ row, top, window }: { row: LeagueFormRow; top: number; window: number }) {
  const shown = row.rounds.slice(-window);
  return (
    <span className="flex h-7 shrink-0 items-end gap-1" aria-hidden>
      {shown.map((item, index) => (
        <span
          key={item.round}
          title={`J${item.round}: ${item.points} pts`}
          className="w-2 rounded-sm"
          style={{
            height: `${Math.max(12, (item.points / top) * 100)}%`,
            background: row.is_self ? "#FFC08A" : "rgba(255,255,255,0.32)",
            opacity: index === shown.length - 1 ? 1 : 0.55,
          }}
        />
      ))}
    </span>
  );
}

/**
 * Puntos por jornada de cada mánager, ordenados por media reciente: enseña
 * quién viene fuerte, que el acumulado no dice.
 */
export function FormCard({ form }: { form: LeagueFormPayload | null }) {
  const rows = form && form.ok !== false ? form.rows || [] : [];
  if (rows.length < 2) return null;
  const window = form?.recent_window ?? 3;
  const top = Math.max(1, ...rows.flatMap((row) => row.rounds.slice(-window).map((item) => item.points)));
  const mine = rows.find((row) => row.is_self);
  const last = form?.rounds?.at(-1);

  return (
    <Disclosure title="Forma reciente" meta={mine ? `Tú: ${mine.form_rank}º` : `J${last ?? ""}`}>
      <p className="text-[12.5px] text-white/45">Media de las últimas {window} jornadas. Quien viene fuerte no siempre va arriba en el acumulado.</p>
      <ul className="mt-2 divide-y divide-white/[0.05]">
        {rows.map((row) => {
          const up = typeof row.trend === "number" && row.trend > 0.5;
          const down = typeof row.trend === "number" && row.trend < -0.5;
          return (
            <li key={String(row.team_id)} className="flex items-center gap-3 py-2.5">
              <span className="w-4 shrink-0 text-[12px] tabular-nums text-white/40">{row.form_rank}</span>
              <span className="min-w-0 flex-1 truncate text-[14px]" style={{ color: row.is_self ? "#FFC08A" : "#fff" }}>
                {row.is_self ? "Tú" : nameOf(row)}
              </span>
              <Bars row={row} top={top} window={window} />
              <span className="w-[4.5rem] shrink-0 text-right">
                <span className="block text-[14px] font-semibold tabular-nums text-white">{points(row.recent_avg)}</span>
                <span className="block text-[11px] tabular-nums" style={{ color: up ? TONE.green : down ? TONE.red : "rgba(255,255,255,0.35)" }}>
                  {typeof row.trend === "number" ? `${up ? "▲" : down ? "▼" : "="} ${points(Math.abs(row.trend))}` : "—"}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[12px] leading-relaxed text-white/35">La flecha compara la última jornada con la media de las anteriores.</p>
    </Disclosure>
  );
}

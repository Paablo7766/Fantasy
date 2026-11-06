"use client";

import { points } from "@/lib/core/format";
import type { LeagueEdge, LeagueFormPayload, LeagueFormRow } from "@/lib/types";
import { Disclosure, TONE } from "@/components/ui/kit";

/** Jornadas de una temporada de LaLiga. */
const SEASON_ROUNDS = 38;

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
 * Cuándo alcanzas al de arriba, o te alcanza el de abajo, si cada uno sigue con
 * su media reciente. Solo se dice algo cuando el cruce ocurre antes de que acabe
 * la liga; con pocas jornadas es una orientación, no una predicción.
 */
function paceLines(rows: LeagueFormRow[], above: LeagueEdge | null | undefined, below: LeagueEdge | null | undefined, left: number): string[] {
  const mine = rows.find((row) => row.is_self);
  if (!mine || left <= 0) return [];
  const find = (edge: LeagueEdge | null | undefined) => rows.find((row) => edge?.team_id != null && String(row.team_id) === String(edge.team_id));
  const lines: string[] = [];
  const up = find(above);
  if (up && typeof above?.edge_points === "number" && above.edge_points < 0) {
    const gap = -above.edge_points;
    const diff = mine.recent_avg - up.recent_avg;
    if (diff > 0 && Math.ceil(gap / diff) <= left) lines.push(`A este ritmo alcanzas a ${nameOf(up)} en unas ${Math.ceil(gap / diff)} jornadas.`);
    else lines.push(`A este ritmo no alcanzas a ${nameOf(up)}: te saca ${points(gap)} pts y rinde ${points(Math.max(0, -diff))} más por jornada.`);
  }
  const down = find(below);
  if (down && typeof below?.edge_points === "number" && below.edge_points > 0) {
    const lead = below.edge_points;
    const diff = down.recent_avg - mine.recent_avg;
    if (diff > 0 && Math.ceil(lead / diff) <= left) lines.push(`${nameOf(down)} te alcanza en unas ${Math.ceil(lead / diff)} jornadas si no cambias.`);
  }
  return lines;
}

/**
 * Puntos por jornada de cada mánager, ordenados por media reciente: enseña
 * quién viene fuerte, que el acumulado no dice.
 */
export function FormCard({ form, above, below }: { form: LeagueFormPayload | null; above?: LeagueEdge | null; below?: LeagueEdge | null }) {
  if (!form) return null;
  const rows = form.ok !== false ? form.rows || [] : [];
  if (rows.length < 2) {
    // Se dice por qué falta en vez de esconderse: ayuda a ver si el servidor
    // tiene ya esta versión o si los nombres no casan.
    const unmatched = form.unmatched?.length ? ` No casan con ningún equipo: ${form.unmatched.slice(0, 4).join(", ")}.` : "";
    return (
      <p className="px-1 text-[12px] leading-relaxed text-white/35">
        {form.ok === false ? "Forma reciente: el servidor no responde a esta función (¿versión antigua?)." : `Forma reciente: faltan datos.${unmatched}`}
      </p>
    );
  }
  const window = form?.recent_window ?? 3;
  const top = Math.max(1, ...rows.flatMap((row) => row.rounds.slice(-window).map((item) => item.points)));
  const mine = rows.find((row) => row.is_self);
  const last = form?.rounds?.at(-1);
  const pace = paceLines(rows, above, below, SEASON_ROUNDS - (last ?? SEASON_ROUNDS));

  return (
    <Disclosure title="Quién viene en racha" meta={mine ? `Tú: ${mine.form_rank}º en forma` : `J${last ?? ""}`} defaultOpen>
      <p className="text-[13px] leading-snug text-white/60">
        Ordenados por los <span className="font-semibold text-white">puntos que han hecho de media en las últimas {window} jornadas</span>, no por el total de la temporada.
      </p>
      {mine ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-2xl bg-white/[0.05] px-3 py-2.5">
            <p className="text-[1.15rem] font-semibold leading-none tabular-nums" style={{ color: "#FFC08A" }}>{points(mine.recent_avg)} pts</p>
            <p className="mt-1.5 text-[12px] text-white/50">Tu media por jornada</p>
          </div>
          <div className="rounded-2xl bg-white/[0.05] px-3 py-2.5">
            <p className="text-[1.15rem] font-semibold leading-none tabular-nums text-white">{mine.form_rank}º de {rows.length}</p>
            <p className="mt-1.5 text-[12px] text-white/50">Tu puesto en forma</p>
          </div>
        </div>
      ) : null}
      <div className="mt-4 flex items-center gap-3 border-b border-white/[0.06] pb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-white/35">
        <span className="w-4 shrink-0">#</span>
        <span className="min-w-0 flex-1">Mánager</span>
        <span className="shrink-0">Últ. {window}</span>
        <span className="w-[5.5rem] shrink-0 text-right">Media / jorn.</span>
      </div>
      <ul className="divide-y divide-white/[0.05]">
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
              <span className="w-[5.5rem] shrink-0 text-right">
                <span className="block text-[14px] font-semibold tabular-nums text-white">
                  {points(row.recent_avg)} <span className="text-[11px] font-normal text-white/40">pts</span>
                </span>
                <span
                  className="block text-[11px] tabular-nums"
                  title="Última jornada comparada con su media anterior"
                  style={{ color: up ? TONE.green : down ? TONE.red : "rgba(255,255,255,0.35)" }}
                >
                  {typeof row.trend === "number" ? (up ? `▲ ${points(row.trend)} al alza` : down ? `▼ ${points(-row.trend)} a la baja` : "= estable") : "—"}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      {pace.length ? (
        <div className="mt-3 border-t border-white/[0.06] pt-3">
          {pace.map((line) => (
            <p key={line} className="text-[13px] leading-snug text-white/70">
              {line}
            </p>
          ))}
        </div>
      ) : null}
      <p className="mt-2 text-[12px] leading-relaxed text-white/35">Las barras son los puntos de cada una de las últimas {window} jornadas (la más clara, la última). «Al alza» o «a la baja» compara la última jornada con su media anterior. Con pocas jornadas jugadas, es orientativo.</p>
    </Disclosure>
  );
}

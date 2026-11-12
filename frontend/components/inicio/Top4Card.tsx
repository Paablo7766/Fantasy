"use client";

import { useSearchParams } from "next/navigation";
import { useJson } from "@/lib/core/useJson";
import { points } from "@/lib/core/format";
import { TONE } from "@/components/ui/kit";
import type { Top4Payload } from "@/lib/types";

const pct = (value: number) => `${Math.round(value * 100)}`;

/**
 * La cifra que decide la liga: probabilidad de quedar entre los 4 primeros de
 * la próxima jornada (los demás pagan multa). Sale de simular la jornada con el
 * xP del once esperado de cada mánager y la dispersión real de la liga.
 */
export function Top4Card() {
  const league = useSearchParams().get("league");
  const data = useJson<Top4Payload>("/api/top4", league);
  if (data === null) {
    return <section className="home-glass px-4 py-5 text-[13px] text-white/45 min-[900px]:px-5">Simulando la jornada…</section>;
  }
  if (data.ok === false || typeof data.p_top4 !== "number") {
    return (
      <section className="home-glass px-4 py-5 text-[13px] text-white/45 min-[900px]:px-5">
        Sin simulación de la jornada: {data.error?.message || data.message || "faltan plantillas"}.
      </section>
    );
  }

  const void_ = data.void === true;
  const scenario = void_ ? data.if_completed ?? null : null;
  const prob = scenario ? scenario.p_top4 : data.p_top4;
  const gap = scenario ? scenario.xp_gap_to_cutoff : (data.xp_gap_to_cutoff ?? 0);
  const mine = scenario ? scenario.expected_points : data.expected_points;
  const managers = data.managers ?? [];
  const calibration = data.calibration;

  return (
    <section className="home-glass overflow-hidden" aria-label="Probabilidad de top 4">
      <div className="grid gap-5 px-4 py-5 min-[900px]:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] min-[900px]:items-end min-[900px]:px-5">
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-white/65">Top 4 de la próxima jornada</p>
          <p className="mt-2 flex items-baseline gap-1 font-mono leading-none tracking-[-0.04em] text-white">
            <span className="text-[3.4rem] font-semibold">{pct(prob)}</span>
            <span className="text-xl font-medium text-white/60">%</span>
          </p>
          <p className="mt-3 max-w-[46ch] text-[13.5px] leading-snug text-white/65">
            <span className="font-mono font-semibold" style={{ color: gap > 0 ? TONE.red : TONE.green }}>
              {gap > 0 ? `Te faltan ${points(gap)} xP` : `Vas ${points(Math.abs(gap))} xP por encima`}
            </span>{" "}
            {gap > 0 ? "para el corte" : "del corte"} (<span className="font-mono">{points(data.cutoff_median)}</span> pts, el 4.º; tu once suma <span className="font-mono">{points(mine)}</span>).
          </p>
          {void_ ? (
            <p className="mt-2 max-w-[46ch] text-[12.5px] leading-snug text-white/60">
              <span className="font-semibold text-white">Hoy solo tienes {data.player_count} jugadores</span>: con menos de 11 la jornada entera puntúa 0 (regla oficial), y tu probabilidad real ahora es{" "}
              <span className="font-mono">{pct(data.p_top4 ?? 0)} %</span>. La cifra grande es con el once completado
              {scenario ? ` (hueco cubierto con un recambio de ${points(scenario.fill_xp)} xP)` : ""}.
            </p>
          ) : null}
        </div>

        <table className="w-full text-right" aria-label="Probabilidad de cada mánager">
          <thead>
            <tr className="text-[11.5px] text-white/40">
              <th className="py-1.5 text-left font-normal">Mánager</th>
              <th className="py-1.5 font-normal">xP</th>
              <th className="py-1.5 font-normal">Top 4</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05]">
            {managers.map((row) => (
              <tr key={String(row.team_id ?? row.manager_name)} className={`text-[13px] ${row.is_self ? "text-[#FFC08A]" : "text-white/80"}`}>
                <td className="truncate py-1.5 text-left">
                  {row.manager_name}
                  {row.is_self ? <span className="ml-1.5 text-[11.5px] opacity-70">Tú</span> : null}
                </td>
                <td className="py-1.5 font-mono">{row.has_xp ? points(row.expected_points) : "—"}</td>
                <td className="py-1.5 font-mono font-semibold">
                  {row.is_self && void_ && scenario ? (
                    <>
                      {pct(scenario.p_top4)} %<span className="ml-1 text-[10.5px] font-normal opacity-60">con 11</span>
                    </>
                  ) : (
                    `${pct(row.p_top4)} %`
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-white/[0.06] px-4 py-3 text-[12px] leading-snug text-white/40 min-[900px]:px-5">
        20.000 jornadas simuladas con el xP del once esperado de cada mánager
        {calibration ? `; dispersión de ±${points(calibration.sigma)} pts por jornada medida en ${calibration.rounds_used} jornadas reales` : ""}. Dentro del top 4 es igualar o superar al 4.º.
        {data.is_stale ? " La foto de las plantillas no está al día." : ""}
      </p>
    </section>
  );
}

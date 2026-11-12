"use client";

import type { LeagueMyRound } from "@/lib/types";
import { TONE } from "@/components/ui/kit";
import { CardHead } from "./parts";

const signed = (value: number) => (value > 0 ? `+${value}` : value < 0 ? `−${Math.abs(value)}` : "0");

/**
 * Tu puesto en cada jornada contra la línea del 4.º. Es la tabla que importa:
 * quien queda fuera del top 4 de la jornada paga multa. Solo lleva color la
 * diferencia con el corte (verde dentro, rojo fuera).
 */
export function RoundsTable({ rounds, sources }: { rounds: LeagueMyRound[]; sources?: Record<string, "actividad" | "manual"> }) {
  if (!rounds.length) {
    return (
      <section className="home-glass px-4 py-5 text-[13px] text-white/50 min-[900px]:px-5" aria-label="Tus jornadas">
        Aún no hay puntos por jornada: salen solos de los premios de la actividad en cuanto se publica el primero.
      </section>
    );
  }
  const inside = rounds.filter((item) => item.in_top4).length;
  const last = [...rounds].reverse();
  const mean = rounds.reduce((sum, item) => sum + item.gap, 0) / rounds.length;
  return (
    <section className="home-glass overflow-hidden" aria-label="Tus jornadas">
      <CardHead
        title="Tus jornadas"
        count={rounds.length}
        caption={`Top 4 en ${inside} de ${rounds.length}. De media te falta ${Math.abs(Math.round(mean * 10) / 10).toLocaleString("es-ES")} pts ${mean >= 0 ? "(vas por encima del corte)" : "para el corte"}.`}
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[24rem] border-t border-white/[0.06] text-right">
          <thead>
            <tr className="text-[11.5px] font-normal text-white/40">
              <th className="px-4 py-2.5 text-left font-normal min-[900px]:px-5">Jornada</th>
              <th className="px-2 py-2.5 font-normal">Puntos</th>
              <th className="px-2 py-2.5 font-normal">Puesto</th>
              <th className="px-2 py-2.5 font-normal">4.º</th>
              <th className="px-4 py-2.5 font-normal min-[900px]:px-5">Diferencia</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05]">
            {last.map((item) => (
              <tr key={item.round} className="font-mono text-[14px] text-white">
                <td className="px-4 py-3 text-left font-sans text-white/75 min-[900px]:px-5">
                  J{item.round}
                  {sources?.[String(item.round)] === "manual" ? <span className="ml-1.5 text-[11px] text-white/30">manual</span> : null}
                </td>
                <td className="px-2 py-3 font-semibold">{item.points}</td>
                <td className="px-2 py-3 text-white/75">
                  {item.rank}º<span className="text-white/30"> /{item.field}</span>
                </td>
                <td className="px-2 py-3 text-white/55">{item.cutoff}</td>
                <td className="px-4 py-3 font-semibold min-[900px]:px-5" style={{ color: item.in_top4 ? TONE.green : TONE.red }}>
                  {signed(item.gap)}
                  {item.tied_at_cutoff ? <span className="ml-1 text-[11px] font-normal text-white/40">empate</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-white/[0.06] px-4 py-3 text-[12px] leading-snug text-white/40 min-[900px]:px-5">
        «4.º» es la línea de la jornada: los puntos del cuarto mánager. La diferencia son tus puntos menos esa línea; empatar con ella cuenta como dentro.
      </p>
    </section>
  );
}

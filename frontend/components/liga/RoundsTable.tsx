"use client";

import type { LeagueMyRound } from "@/lib/types";
import { TONE } from "@/components/ui/kit";
import { CardHead } from "./parts";

const signed = (value: number) => (value > 0 ? `+${value}` : value < 0 ? `−${Math.abs(value)}` : "0");

/**
 * Tu puesto en cada jornada contra la línea del 4.º. Es la tabla que importa:
 * quien queda fuera del top 4 de la jornada paga multa. Cada fila es una barra
 * con tus puntos y una raya en el corte; verde si entraste.
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
  const top = Math.max(1, ...rounds.map((item) => Math.max(item.points, item.cutoff)));
  const meanText = Math.abs(Math.round(mean * 10) / 10).toLocaleString("es-ES");
  return (
    <section className="home-glass overflow-hidden" aria-label="Tus jornadas">
      <CardHead
        title="Tus jornadas"
        caption={`Top 4 en ${inside} de ${rounds.length}. De media ${mean >= 0 ? `superas el corte por ${meanText} pts` : `te quedas a ${meanText} pts del corte`}.`}
      />
      <ul className="border-t border-white/[0.06]">
        {last.map((item) => (
          <li key={item.round} className="grid grid-cols-[2.75rem_minmax(0,1fr)_3.25rem_3rem] items-center gap-3 border-b border-white/[0.05] px-4 py-3 last:border-b-0 min-[900px]:px-5">
            <span className="text-[13.5px] text-white/60">
              J{item.round}
              {sources?.[String(item.round)] === "manual" ? <span className="block text-[10.5px] text-white/30">a mano</span> : null}
            </span>
            {/* Tus puntos como barra; la raya es la línea del 4.º. */}
            <span className="relative block h-2 rounded-full bg-white/[0.06]" role="img" aria-label={`${item.points} puntos; el 4.º hizo ${item.cutoff}`}>
              <span className="block h-full rounded-full" style={{ width: `${Math.max(3, (item.points / top) * 100)}%`, background: item.in_top4 ? TONE.green : "rgba(255,255,255,0.3)" }} />
              <span className="absolute -top-1 h-4 w-px bg-white/70" style={{ left: `${(item.cutoff / top) * 100}%` }} title={`Corte: ${item.cutoff}`} />
            </span>
            <span className="text-right">
              <span className="block text-[14.5px] font-semibold tabular-nums text-white">{item.points}</span>
              <span className="block text-[11.5px] tabular-nums" style={{ color: item.in_top4 ? TONE.green : TONE.red }}>
                {item.tied_at_cutoff ? "empate" : signed(item.gap)}
              </span>
            </span>
            <span className="text-right text-[14.5px] font-semibold tabular-nums" style={{ color: item.in_top4 ? "#fff" : "rgba(255,255,255,0.5)" }}>
              {item.rank}º
            </span>
          </li>
        ))}
      </ul>
      <p className="border-t border-white/[0.06] px-4 py-3 text-[12px] leading-snug text-white/40 min-[900px]:px-5">
        La raya marca los puntos del 4.º en esa jornada: llegar a ella te libra de la multa. Debajo de tus puntos, la diferencia con esa raya.
      </p>
    </section>
  );
}

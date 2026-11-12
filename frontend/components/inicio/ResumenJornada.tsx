"use client";

import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { points } from "@/lib/core/format";
import { useJson } from "@/lib/core/useJson";
import type { LeagueFormPayload, PostMortemPayload } from "@/lib/types";

const MINT = "var(--ini-mint)";
const RED = "var(--ini-red)";
const MONO = { fontFamily: "var(--font-mono), ui-monospace, monospace" } as const;

/**
 * Resumen de la última jornada jugada: mi puesto, lo que me faltó (o sobró) para
 * el 4.º y los puntos que dejé fuera del once. Los puntos por mánager salen del
 * premio de jornada de la actividad (100.000 € por punto); si una jornada solo
 * viene del respaldo manual se dice. Dos lecturas de disco, ninguna llamada a LaLiga.
 */
export function ResumenJornada() {
  const search = useSearchParams();
  const { trends } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const form = useJson<LeagueFormPayload>("/api/league-form", league);
  const mortem = useJson<PostMortemPayload>("/api/laboratorio/post-mortem", league);

  const rounds = form && form.ok !== false ? (form.my_rounds ?? []) : [];
  const last = rounds[rounds.length - 1];
  if (!last) return null;

  const missing = last.in_top4 ? 0 : Math.max(0, last.cutoff - last.points);
  const margin = last.points - last.cutoff;
  const source = form?.sources?.[String(last.round)];
  const fuga = mortem?.jornada === String(last.round) ? mortem.fuga : undefined;
  const leaked = fuga?.disponible ? (fuga.fuga ?? null) : null;
  const left = fuga?.disponible ? (fuga.dejados_fuera ?? []) : [];

  return (
    <section className="ini-card ini-in" aria-label={`Resumen de la jornada ${last.round}`} data-ui="resumen-jornada">
      <header className="px-5 pb-3 pt-5">
        <p className="ini-eyebrow">Resumen de la J{last.round}</p>
        <h2 className="mt-2 text-[28px] font-semibold leading-tight tracking-[-0.03em] text-white">
          <span style={MONO}>{last.rank}º</span> <span className="text-[16px] font-normal text-white/50">de {last.field}</span>
        </h2>
        <p className="mt-1.5 text-[13px] text-white/60">
          <span style={MONO}>{last.points} pts</span>
          {" · "}
          {last.in_top4 ? (
            <span style={{ color: MINT }}>
              Top 4 con <span style={MONO}>{margin >= 0 ? `+${margin}` : margin}</span> sobre el corte
            </span>
          ) : (
            <span style={{ color: RED }}>
              Te faltaron <span style={MONO}>{missing}</span> para el 4.º
            </span>
          )}
        </p>
      </header>
      <dl className="ini-divide text-[13px]">
        <div className="flex flex-col gap-1 px-5 py-3 min-[420px]:flex-row min-[420px]:items-baseline min-[420px]:justify-between">
          <dt className="text-white/55">Puntos fuera del once</dt>
          <dd className="text-white/85 min-[420px]:text-right">
            {leaked !== null ? (
              <>
                <span style={{ ...MONO, color: leaked > 0.05 ? RED : undefined }}>{points(leaked)} pts</span>
                {left.length ? <span className="block text-[12px] text-white/45">{left.slice(0, 3).map((p) => p.nombre).filter(Boolean).join(", ")}</span> : null}
              </>
            ) : (
              <span className="text-white/45">{fuga?.motivo === "sin_once" ? "No medible: el once guardado tiene menos de 11" : fuga?.detalle || "No medible con el once de ahora"}</span>
            )}
          </dd>
        </div>
      </dl>
      <table className="w-full text-[12px]" style={MONO}>
        <thead>
          <tr className="text-white/40">
            <th className="px-5 py-2 text-left font-normal">Jornada</th>
            <th className="py-2 text-right font-normal">Puntos</th>
            <th className="py-2 text-right font-normal">Puesto</th>
            <th className="px-5 py-2 text-right font-normal">Corte 4.º</th>
          </tr>
        </thead>
        <tbody>
          {[...rounds].reverse().map((r) => (
            <tr key={r.round} className="border-t border-white/5 text-white/80">
              <td className="px-5 py-2">J{r.round}</td>
              <td className="py-2 text-right">{r.points}</td>
              <td className="py-2 text-right">{r.rank}º</td>
              <td className="px-5 py-2 text-right" style={{ color: r.in_top4 ? MINT : RED }}>
                {r.cutoff}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {source === "manual" ? (
        <p className="px-5 pb-4 pt-2 text-[11px] text-white/40">Puntos de la J{last.round} anotados a mano: no vienen del premio de la actividad.</p>
      ) : null}
    </section>
  );
}

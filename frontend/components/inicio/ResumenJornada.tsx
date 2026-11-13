"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { points } from "@/lib/core/format";
import { useJson } from "@/lib/core/useJson";
import type { LeagueFormPayload, PostMortemPayload } from "@/lib/types";

const MINT = "var(--ini-mint)";
const RED = "var(--ini-red)";

function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string | null; color?: string }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[12px] text-white/45">{label}</p>
      <p className="mt-1 truncate text-[20px] font-semibold leading-none tracking-[-0.02em] tabular-nums" style={{ color: color ?? "#fff" }}>
        {value}
      </p>
      <p className="mt-1 truncate text-[12px] text-white/40">{sub || " "}</p>
    </div>
  );
}

/**
 * La última jornada en tres cifras: puesto, puntos contra la línea del 4.º y
 * los puntos que se quedaron en el banquillo. El historial completo vive en
 * Liga → Jornadas; aquí solo se enlaza.
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

  const margin = last.points - last.cutoff;
  const fuga = mortem?.jornada === String(last.round) ? mortem.fuga : undefined;
  const leaked = fuga?.disponible && typeof fuga.fuga === "number" ? fuga.fuga : null;
  const left = fuga?.disponible ? (fuga.dejados_fuera ?? []).map((p) => p.nombre).filter(Boolean).slice(0, 2).join(", ") : "";
  const recent = rounds.slice(-8);
  const query = new URLSearchParams(search.toString());
  query.set("tab", "jornadas");

  return (
    <section className="ini-card ini-in" aria-label={`Resumen de la jornada ${last.round}`} data-ui="resumen-jornada">
      <div className="px-5 pb-4 pt-5">
        <div className="flex items-center justify-between gap-3">
          <p className="ini-eyebrow">Última jornada · J{last.round}</p>
          <span className="flex items-center gap-1" role="img" aria-label={`Top 4 en ${recent.filter((r) => r.in_top4).length} de las últimas ${recent.length} jornadas`}>
            {recent.map((r) => (
              <span key={r.round} title={`J${r.round}: ${r.rank}º`} className="h-1.5 w-1.5 rounded-full" style={{ background: r.in_top4 ? MINT : "rgba(255,255,255,0.18)" }} />
            ))}
          </span>
        </div>
        <div className="mt-3.5 grid grid-cols-3 gap-3">
          <Stat label="Puesto" value={`${last.rank}º`} sub={`de ${last.field}`} />
          <Stat
            label="Puntos"
            value={String(last.points)}
            sub={last.in_top4 ? `${margin > 0 ? `+${margin}` : "igualas"} el corte` : `${margin} del corte`}
            color={last.in_top4 ? MINT : RED}
          />
          <Stat label="En el banquillo" value={leaked !== null ? `${points(leaked)} pts` : "—"} sub={leaked !== null ? left || "nada que rascar" : "no medible"} />
        </div>
      </div>
      <Link href={`/liga?${query.toString()}`} className="ini-foot">
        <span>Todas las jornadas</span>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" style={{ transform: "rotate(-90deg)" }}>
          <path d="m4 6 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Link>
    </section>
  );
}

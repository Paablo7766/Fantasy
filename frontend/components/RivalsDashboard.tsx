"use client";

import { ErrorCard, Skeleton } from "@/components/Feedback";
import { cashClass, clockLabel, eur, glass, multiple, playerName, points } from "@/lib/format";
import type { ClauseRow, NeedRival, NeedsPayload, SquadsPayload } from "@/lib/types";

function needsByTeam(needs: NeedsPayload | null): Map<string, NeedRival> {
  const map = new Map<string, NeedRival>();
  const rivals = needs?.ok ? needs.rivals || [] : [];
  for (const rival of rivals) map.set(String(rival.team_id), rival);
  return map;
}

function StatusChips({ rival }: { rival: NeedRival | undefined }) {
  if (!rival) return null;
  const chips: string[] = [];
  if (rival.direct === true) chips.push("Directo");
  if (rival.lacks_liquidity === true) chips.push("Sin liquidez");
  if (rival.lacks_replacements === true) chips.push("Sin recambio");
  for (const position of rival.thin_positions || []) chips.push(`Hueco ${position}`);
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {chips.map((label) => (
        <span key={label} className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-white/70">
          {label}
        </span>
      ))}
    </div>
  );
}

function ruleLabel(row: ClauseRow): string {
  if (row.clause_rule === "A") return "Regla A";
  if (row.clause_rule === "B") return "Regla B";
  return "Fuera";
}

export function RivalsDashboard({
  squads,
  needs,
  loading = false,
}: {
  squads: SquadsPayload | null;
  needs: NeedsPayload | null;
  loading?: boolean;
}) {
  if (loading && !squads) return <Skeleton title="Rivales" rows={6} />;
  if (!squads || squads.ok === false) {
    return <ErrorCard title="Rivales" payload={squads || { error: { message: "Sin plantillas." } }} brief />;
  }
  const risk = needsByTeam(needs);
  const zone = squads.clause_lock_timezone || "Europe/Madrid";
  const rivals = squads.rivals || [];
  const clauses = squads.clauses || [];

  return (
    <article className={glass("p-4")}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-white/40">Rivales</p>
          <h2 className="text-xl font-medium">{squads.rival_count || 0} plantillas</h2>
        </div>
        <p className="max-w-md text-xs leading-5 text-white/40">
          Solo cláusulas que pasan la regla de oro: media ≥ 3 y cláusula ≤ 1,6×, o media ≥ 6 y cláusula ≤ 2,2×.
        </p>
      </div>
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-[0.14em] text-white/40">
            <tr>
              <th className="p-4 font-medium">Rival</th>
              <th className="p-4 font-medium">Puesto</th>
              <th className="p-4 font-medium">Caja</th>
              <th className="p-4 font-medium">Plantilla</th>
              <th className="p-4 font-medium">Bloqueadas</th>
            </tr>
          </thead>
          <tbody>
            {rivals.length ? (
              rivals.map((rival) => (
                <tr key={String(rival.team_id)} className="border-t border-white/5 align-top transition-colors hover:bg-white/10">
                  <td className="p-4">
                    <div className="font-medium">{rival.manager_name || rival.fantasy_team_name || rival.team_id || "Rival"}</div>
                    <div className="text-xs text-white/40">{rival.fantasy_team_name || ""}</div>
                    <StatusChips rival={risk.get(String(rival.team_id))} />
                  </td>
                  <td className="p-4 font-mono">{rival.rank ?? "s/d"}</td>
                  <td className={`p-4 font-mono ${cashClass(rival.cash_eur)}`}>{eur(rival.cash_eur)}</td>
                  <td className="p-4 text-white/70">{rival.player_count} jug.</td>
                  <td className="p-4 font-mono">{rival.locked_clauses}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="p-4 text-white/50" colSpan={5}>
                  La liga no devolvió rivales.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <h3 className="mb-2 mt-6 px-4 text-[11px] uppercase tracking-[0.16em] text-emerald-300/80">
        Cláusulas que merecen la pena · {zone}
      </h3>
      <div className="scroll-thin max-h-[460px] overflow-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="sticky top-0 bg-slate-950/95 text-[11px] uppercase tracking-[0.14em] text-white/40 backdrop-blur-md">
            <tr>
              <th className="p-4 font-medium">Jugador</th>
              <th className="p-4 font-medium">Rival</th>
              <th className="p-4 font-medium">Media</th>
              <th className="p-4 font-medium">Cláusula</th>
              <th className="p-4 font-medium">Múltiplo</th>
              <th className="p-4 font-medium">Regla</th>
              <th className="p-4 font-medium">Hora</th>
            </tr>
          </thead>
          <tbody>
            {clauses.length ? (
              clauses.map((row) => (
                <tr key={`${row.team_id}-${row.player_id}`} className="border-t border-white/5 transition-colors hover:bg-white/10">
                  <td className="p-4 font-medium">{playerName(row)}</td>
                  <td className="p-4 text-white/70">{row.manager_name || row.fantasy_team_name || ""}</td>
                  <td className="p-4 font-mono">{points(row.average_points)}</td>
                  <td className="p-4 font-mono">{eur(row.buyout_clause_eur)}</td>
                  <td className="p-4 font-mono text-emerald-300">{multiple(row.clause_multiple)}</td>
                  <td className="p-4">
                    <span className="rounded-full bg-emerald-400/15 px-2 py-1 text-[11px] uppercase tracking-wide text-emerald-300">
                      {ruleLabel(row)}
                    </span>
                  </td>
                  <td className="p-4 font-mono text-xs">{clockLabel(row.clause_lock)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="p-4 text-white/50" colSpan={7}>
                  Ninguna cláusula rival cumple la regla de oro.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {squads.clause_lock_note ? <p className="mt-3 px-4 text-xs text-white/35">{squads.clause_lock_note}</p> : null}
    </article>
  );
}

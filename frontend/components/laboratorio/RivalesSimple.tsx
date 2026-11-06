"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { endpoint } from "@/lib/core/api";
import { useCachedJson } from "@/lib/core/useCachedJson";
import { playerName, points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { ClauseBoardPayload, ClauseBoardRow, RivalFinancialTeam, RivalIntelPayload, SquadsPayload } from "@/lib/types";
import { Empty, HeroStat, Skeleton, TONE, money } from "@/components/ui/kit";
import { List, Row } from "./RadarSimple";
import { bidBudget } from "@/lib/mercado/budget";

type View = "pujas" | "clausulas" | "como";

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "pujas", label: "Cuánto pueden pujar", hint: "Lo máximo que cada rival puede gastar hoy en una puja: su caja más lo que puede endeudarse." },
  { id: "clausulas", label: "Cláusulas a tiro", hint: "Jugadores rivales que ya puedes clausular con tu caja, y los que se abren pronto." },
  { id: "como", label: "Cómo se calcula", hint: "De dónde sale la caja de cada rival." },
];

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function opensLabel(row: ClauseBoardRow): string {
  const lock = row.clause_lock;
  if (!lock || !lock.local_date) return "Bloqueada";
  const [, month, day] = String(lock.local_date).split("-");
  return `Abre el ${Number(day)} ${MONTHS[Number(month) - 1] || month}${lock.local_time ? ` · ${lock.local_time}` : ""}`;
}

/**
 * Puja máxima: caja + 20 % del valor de su plantilla (regla de endeudamiento).
 * El backend aún no da ese margen (``debt_limit_eur`` llega a 0), así que se
 * suma aquí con el valor de la plantilla de la foto.
 */
function bidOf(team: RivalFinancialTeam, values: Map<string, number>): number | null {
  const cash = cashOf(team);
  if (cash === null) return null;
  const squadValue = values.get(String(team.team_id)) ?? null;
  const debt = typeof team.debt_limit_eur === "number" && team.debt_limit_eur > 0 ? team.debt_limit_eur : null;
  const budget = debt !== null ? cash + debt : bidBudget(cash, squadValue);
  return budget === null ? null : Math.max(0, budget);
}

function cashOf(team: RivalFinancialTeam): number | null {
  const value = team.cash_expected_eur ?? team.calculated_cash;
  return typeof value === "number" ? value : null;
}

const CONFIDENCE: Record<string, { label: string; color: string }> = {
  high: { label: "Dato fiable", color: TONE.green },
  medium: { label: "Aproximado", color: TONE.amber },
  low: { label: "Poco fiable", color: TONE.red },
};

export function RivalesSimple({ photos }: { photos: PhotoIndex }) {
  const search = useSearchParams();
  const league = search.get("league");
  const { squads } = useDashboard();
  const intel = useCachedJson<RivalIntelPayload>(endpoint("/api/rival-intel", league));
  const board = useCachedJson<ClauseBoardPayload>(endpoint("/api/clause-board", league));
  const [view, setView] = useState<View>("pujas");
  const cash = (squads as SquadsPayload | null)?.self?.cash_eur ?? null;
  const values = useMemo(() => {
    const map = new Map<string, number>();
    for (const rival of (squads as SquadsPayload | null)?.rivals ?? []) {
      if (rival.team_id && typeof rival.market_value_total === "number") map.set(String(rival.team_id), rival.market_value_total);
    }
    return map;
  }, [squads]);

  const rivals = useMemo(
    () =>
      Object.values(intel?.teams ?? {})
        .filter((team) => !team.is_self)
        .sort((a, b) => (bidOf(b, values) ?? -1) - (bidOf(a, values) ?? -1)),
    [intel, values],
  );
  const topBid = Math.max(1, ...rivals.map((team) => bidOf(team, values) ?? 0));

  const clauses = useMemo(() => {
    const rows = (board?.rows ?? []).filter((row) => typeof row.buyout_clause_eur === "number");
    const open = rows
      .filter((row) => !row.is_locked && cash !== null && (row.buyout_clause_eur ?? Infinity) <= cash)
      .sort((a, b) => (b.average_points ?? 0) - (a.average_points ?? 0));
    const soon = rows
      .filter((row) => row.is_locked && row.clause_lock?.expires_at)
      .sort((a, b) => String(a.clause_lock?.expires_at).localeCompare(String(b.clause_lock?.expires_at)));
    return { open, soon };
  }, [board, cash]);

  if (intel === null) return <Skeleton />;
  if (intel.ok === false) {
    return <Empty title="No se pudo leer a los rivales" detail={`${intel.error?.message || "Sin datos."} Prueba a actualizar la foto desde Inicio.`} />;
  }

  const richest = rivals[0];
  const current = VIEWS.find((v) => v.id === view)!;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid grid-cols-3 gap-2.5">
        <HeroStat value={richest ? money(bidOf(richest, values)) : "—"} label={richest ? `máx. puja · ${richest.manager_name}` : "máx. puja rival"} tone={TONE.copper} />
        <HeroStat value={board && board.ok !== false ? String(clauses.open.length) : "—"} label="cláusulas a tiro" tone={TONE.green} />
        <HeroStat value={cash !== null ? money(cash) : "—"} label="tu caja" />
      </div>

      <div className="eq-scroll -mx-1 flex gap-1.5 px-1" role="tablist" aria-label="Vistas de rivales">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} className={view === v.id ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setView(v.id)}>
            {v.label}
          </button>
        ))}
      </div>
      <p className="-mt-1 px-1 text-[13px] text-white/50">{current.hint}</p>

      <div key={view} className="row-in">
        {view === "pujas" ? (
          <ul className="home-glass flex flex-col gap-4 p-5">
            {rivals.map((team, index) => {
              const bid = bidOf(team, values);
              const conf = CONFIDENCE[String(team.confidence)] ?? CONFIDENCE.medium;
              const teamCash = cashOf(team);
              return (
                <li key={team.team_id ?? index} className="row-in !bg-transparent" style={{ animationDelay: `${index * 25}ms` }}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0 truncate text-[15px] font-medium text-white">
                      <span className="mr-2 text-white/35 tabular-nums">{team.rank ?? index + 1}º</span>
                      {team.manager_name || team.fantasy_team_name || "Rival"}
                    </span>
                    <span className="shrink-0 text-[15px] font-semibold tabular-nums text-white">{money(bid)}</span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.07]">
                    <span className="block h-full rounded-full transition-[width] duration-700 ease-out" style={{ width: `${bid ? (bid / topBid) * 100 : 0}%`, background: TONE.copper }} />
                  </div>
                  <p className="mt-1.5 flex justify-between gap-3 text-[12px] text-white/45">
                    <span>Caja {teamCash !== null ? money(teamCash) : "—"}{teamCash !== null && teamCash < 0 ? " · en negativo" : ""}</span>
                    <span style={{ color: conf.color }}>{conf.label}</span>
                  </p>
                </li>
              );
            })}
          </ul>
        ) : view === "clausulas" ? (
          board === null ? (
            <Skeleton />
          ) : board.ok === false ? (
            <Empty title="Sin tablero de cláusulas" detail={board.error?.message || "Sin datos."} />
          ) : (
            <div className="flex flex-col gap-5">
              <section className="flex flex-col gap-2">
                <p className="px-1 text-[13px] font-medium text-white/70">Puedes pagarlas ya ({clauses.open.length})</p>
                <List
                  rows={clauses.open}
                  empty={cash === null ? "Sin tu caja no se puede saber qué te cabe." : "Ninguna cláusula abierta cabe hoy en tu caja."}
                  render={(row, i) => {
                    const name = playerName(row);
                    return (
                      <Row
                        key={`${row.team_id}-${row.player_id}`}
                        index={i}
                        name={name}
                        photo={photoFor(photos, String(row.player_id), name)}
                        meta={[row.position, row.club, `de ${row.manager_name}`].filter(Boolean).join(" · ")}
                        value={money(row.buyout_clause_eur)}
                        note={`${points(row.average_points)} pts de media`}
                      />
                    );
                  }}
                />
              </section>
              <section className="flex flex-col gap-2">
                <p className="px-1 text-[13px] font-medium text-white/70">Se abren pronto</p>
                <List
                  rows={clauses.soon}
                  empty="No hay cláusulas bloqueadas con fecha."
                  render={(row, i) => {
                    const name = playerName(row);
                    const fits = cash !== null && (row.buyout_clause_eur ?? Infinity) <= cash;
                    return (
                      <Row
                        key={`${row.team_id}-${row.player_id}`}
                        index={i}
                        name={name}
                        photo={photoFor(photos, String(row.player_id), name)}
                        meta={[`de ${row.manager_name}`, opensLabel(row)].filter(Boolean).join(" · ")}
                        value={money(row.buyout_clause_eur)}
                        valueTone={fits ? TONE.green : undefined}
                        note={fits ? "Te cabe" : "No te llega"}
                      />
                    );
                  }}
                />
              </section>
            </div>
          )
        ) : (
          <div className="flex flex-col gap-3">
            <ol className="home-glass flex flex-col gap-4 p-5">
              {[
                ["Libro de cuentas", `Se parte del presupuesto inicial y se suman ventas y primas, y se restan compras y cláusulas pagadas. Se han leído ${intel.activity?.event_count ?? 0} movimientos de la liga.`],
                ["Vídeo diario", `LaLiga no publica quién ve el anuncio diario (${money(intel.config?.daily_ad_revenue_eur ?? 100_000)}). Se asume que cada rival lo ve como tú.`],
                ["Puja máxima", "Caja más el 20 % del valor de su equipo, que es lo que el juego deja endeudarse para pujar."],
                ["Fiabilidad", "«Dato fiable» si la cuenta cuadra con lo visible; «Aproximado» si faltan movimientos."],
              ].map(([title, text], i) => (
                <li key={title} className="flex gap-3">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#FF7A3D]/15 text-[12.5px] font-semibold text-[#FF9A5A]">{i + 1}</span>
                  <span>
                    <span className="block text-[14.5px] font-medium text-white">{title}</span>
                    <span className="block text-[13px] leading-snug text-white/55">{text}</span>
                  </span>
                </li>
              ))}
            </ol>
            {intel.warnings?.length ? (
              <details className="home-glass p-5">
                <summary className="cursor-pointer text-[13px] font-medium text-white/60">Avisos técnicos ({intel.warnings.length})</summary>
                <ul className="mt-3 flex list-disc flex-col gap-1.5 pl-5 text-[12.5px] leading-snug text-white/50">
                  {intel.warnings.map((w) => (
                    <li key={w} className="!bg-transparent">{w}</li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

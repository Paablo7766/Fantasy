"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { PlayerQuantCard } from "@/components/liga/PlayerQuantCard";
import { endpoint, getJson } from "@/lib/core/api";
import { eur, eurShort, glass, multiple, playerName, points } from "@/lib/core/format";
import type { ClauseBoardPayload, ClauseBoardRow, Player, SquadsPayload } from "@/lib/types";

type Filter = "todos" | "oro" | "pagadas" | "subidas" | "asequibles";
type Group = "desbloqueo" | "equipo";

const FILTERS: readonly [Filter, string][] = [
  ["todos", "Todas"],
  ["oro", "Regla de oro"],
  ["pagadas", "Subida pagada"],
  ["subidas", "Con subida"],
  ["asequibles", "Con mi caja"],
];

function ruleBadge(row: ClauseBoardRow): { label: string; tone: string } | null {
  if (row.clause_rule === "A") return { label: "A", tone: "badge badge--good" };
  if (row.clause_rule === "B") return { label: "B", tone: "badge badge--warn" };
  return null;
}

/** «27 oct · 14:08» a partir del candado, sin depender del reloj del sistema. */
function unlockLabel(row: ClauseBoardRow): string {
  const lock = row.clause_lock;
  if (!lock || lock.present !== true || !lock.local_date || !lock.local_time) return "sin hora";
  const [, month, day] = String(lock.local_date).split("-");
  const shortMonths = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${Number(day)} ${shortMonths[Number(month) - 1] || month} · ${lock.local_time}`;
}

function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "s/f";
  const [year, month, day] = iso.split("-");
  return `${Number(day)}/${month}/${String(year).slice(2)}`;
}

function RaiseBadge({ row }: { row: ClauseBoardRow }) {
  if (row.clause_paid_by_rival) {
    return (
      <span
        className="badge badge--bad"
        title={`El rival pagó ${eur(row.clause_paid_raise_eur)} de su caja para subirla${
          row.clause_auto_raise_eur ? `. ${eur(row.clause_auto_raise_eur)} subió gratis con el valor` : ""
        }`}
      >
        pagó {eurShort(row.clause_paid_raise_eur)}
      </span>
    );
  }
  if (row.clause_auto_raise_eur) {
    return (
      <span
        className="badge badge--warn"
        title={`Subió ${eur(row.clause_auto_raise_eur)} porque subió su valor de mercado. El rival no pagó nada.`}
      >
        gratis {eurShort(row.clause_auto_raise_eur)}
      </span>
    );
  }
  if (row.raised_today) {
    return (
      <span className="badge badge--bad" title={`Subió ${eur(row.clause_delta_eur)} en la última foto`}>
        +{eurShort(row.clause_delta_eur)} hoy
      </span>
    );
  }
  if (row.raised_since_photo) {
    return (
      <span className="badge badge--warn" title={`Subió ${eur(row.clause_delta_eur)} desde la foto de referencia`}>
        +{eurShort(row.clause_delta_eur)}
      </span>
    );
  }
  if (row.raise_count) {
    return (
      <span className="badge badge--warn" title={`Última subida el ${dayLabel(row.raise_latest_day)}`}>
        subió {dayLabel(row.raise_latest_day)}
      </span>
    );
  }
  return null;
}

function clauseMove(row: ClauseBoardRow): string | null {
  if (typeof row.clause_delta_pct !== "number") return null;
  const pctValue = row.clause_delta_pct * 100;
  const text = Math.abs(pctValue).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${pctValue > 0 ? "+" : pctValue < 0 ? "-" : ""}${text}%`;
}

function ClauseCards({
  rows,
  cash,
  onOpenTeam,
}: {
  rows: ClauseBoardRow[];
  cash: number | null;
  onOpenTeam: (teamId: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2.5 lg:hidden">
      {rows.map((row) => {
        const affordable = typeof cash === "number" && typeof row.buyout_clause_eur === "number" && row.buyout_clause_eur <= cash;
        return (
          <PlayerQuantCard
            key={`${row.team_id}-${row.player_id}`}
            player={row as Player}
            price={row.market_value}
            variation={clauseMove(row)}
            xp={row.average_points}
            ifStarts={row.average_points}
            ceiling={null}
            rightTitle="Cláusula"
            rightValue={eurShort(row.buyout_clause_eur)}
            rightHint={affordable ? "te cabe" : unlockLabel(row)}
            onClick={() => row.team_id && onOpenTeam(String(row.team_id))}
          />
        );
      })}
    </div>
  );
}

function ClauseTable({
  rows,
  cash,
  onOpenTeam,
}: {
  rows: ClauseBoardRow[];
  cash: number | null;
  onOpenTeam: (teamId: string) => void;
}) {
  return (
    <div className="hidden lg:block">
      <table className="table-dense hidden w-full text-left text-sm lg:table">
        <thead>
          <tr>
            <th>Jugador</th>
            <th>Rival</th>
            <th className="text-right">Cláusula</th>
            <th className="text-right">Abre</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const affordable = typeof cash === "number" && typeof row.buyout_clause_eur === "number" && row.buyout_clause_eur <= cash;
            const rule = ruleBadge(row);
            return (
              <tr key={`${row.team_id}-${row.player_id}`}>
                <td>
                  <div className="flex items-center gap-2.5">
                    <PlayerAvatar player={row} size="sm" />
                    <div className="min-w-0">
                      <p className="flex items-center gap-1.5">
                        <span className="truncate font-medium">{playerName(row)}</span>
                        {rule ? <span className={`${rule.tone} !px-1.5 !py-0 text-[10px]`}>{rule.label}</span> : null}
                        <RaiseBadge row={row} />
                      </p>
                      <p className="text-[11px] text-white/50">
                        {row.position || ""}
                        {row.club ? ` · ${row.club}` : ""}
                        {typeof row.average_points === "number" ? ` · ${points(row.average_points)} pts` : ""}
                      </p>
                    </div>
                  </div>
                </td>
                <td>
                  <button
                    type="button"
                    className="text-sm text-white/70 underline decoration-dotted underline-offset-2"
                    onClick={() => row.team_id && onOpenTeam(String(row.team_id))}
                  >
                    {row.manager_name || "Rival"}
                  </button>
                </td>
                <td className={`metric-value text-right ${affordable ? "text-[#0297DE]" : ""}`}>{eur(row.buyout_clause_eur)}</td>
                <td className="text-right font-mono text-[11px] text-white/50">{unlockLabel(row)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Tablero de **todas** las cláusulas rivales.
 *
 * El plan de cláusulas solo publica los chollos que cumplen la regla de oro
 * (A/B). Antes de un desbloqueo eso deja fuera a la mayoría de la liga y no se
 * ve si el rival movió la cláusula. Esta vista no filtra: lee
 * ``/api/clause-board``, que cruza la foto con el histórico de cláusulas ya
 * guardado en disco, y marca las subidas con su fecha.
 */
export function ClauseBoardPanel({ onOpenTeam }: { onOpenTeam?: (teamId: string) => void }) {
  const search = useSearchParams();
  const league = search.get("league");
  const { squads } = useDashboard();
  const [loaded, setLoaded] = useState<{ league: string | null; payload: ClauseBoardPayload } | null>(null);
  const [filter, setFilter] = useState<Filter>("todos");
  const [group, setGroup] = useState<Group>("desbloqueo");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    getJson<ClauseBoardPayload>(endpoint("/api/clause-board", league))
      .then((payload) => {
        if (!cancelled) setLoaded({ league, payload });
      })
      .catch(() => {
        if (!cancelled) {
          setLoaded({ league, payload: { ok: false, error: { message: "Sin /api/clause-board." } } });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const payload = loaded && loaded.league === league ? loaded.payload : null;
  const cash = (squads as SquadsPayload | null)?.self?.cash_eur ?? null;

  const rows = useMemo(() => {
    const all = payload?.rows || [];
    const needle = query.trim().toLowerCase();
    return all.filter((row) => {
      if (filter === "oro" && !row.clause_rule) return false;
      if (filter === "pagadas" && !row.clause_paid_by_rival) return false;
      if (filter === "subidas" && !row.raise_count && !row.raised_since_photo) return false;
      if (filter === "asequibles" && !(typeof cash === "number" && typeof row.buyout_clause_eur === "number" && row.buyout_clause_eur <= cash)) {
        return false;
      }
      if (!needle) return true;
      const haystack = `${row.nickname || ""} ${row.name || ""} ${row.manager_name || ""} ${row.club || ""}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [payload, filter, query, cash]);
  const grouped = useMemo(() => {
    if (group === "desbloqueo") return null;
    const map = new Map<string, ClauseBoardRow[]>();
    for (const row of rows) {
      const key = row.manager_name || String(row.team_id || "Rival");
      const list = map.get(key) || [];
      list.push(row);
      map.set(key, list);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b, "es"));
  }, [rows, group]);

  if (!payload) return <Skeleton title="Cláusulas" rows={8} />;
  if (payload.ok === false) return <ErrorCard title="Cláusulas" payload={payload} brief />;

  const counts = payload.counts;

  return (
    <article className={glass("p-4 md:p-5")}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="lab-eyebrow">Cláusulas rivales</p>
          <h2 className="lab-title mt-1">
            {counts ? `${counts.total} jugadores a la vista` : "Todas las cláusulas"}
          </h2>
          <p className="lab-support mt-1">
            Sin filtro de regla de oro: lo que pide cada rival, cuándo abre y si movió la cláusula desde la foto
            anterior.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-right sm:grid-cols-4">
          <div>
            <p className="metric-label">Bloqueadas</p>
            <p className="metric-value text-sm">{counts?.locked ?? "s/d"}</p>
          </div>
          <div>
            <p className="metric-label">Abiertas</p>
            <p className="metric-value text-sm text-mint">{counts?.open ?? "s/d"}</p>
          </div>
          <div>
            <p className="metric-label">Regla oro</p>
            <p className="metric-value text-sm text-gold">{counts?.golden ?? "s/d"}</p>
          </div>
          <div>
            <p className="metric-label">Subidas hoy</p>
            <p className={`metric-value text-sm ${counts?.raised_today ? "text-coral" : "text-white/50"}`}>
              {counts?.raised_today ?? 0}
            </p>
          </div>
          <div>
            <p className="metric-label">Pagadas</p>
            <p className={`metric-value text-sm ${counts?.paid_raise ? "text-coral" : "text-white/50"}`}>
              {counts?.paid_raise ?? 0}
            </p>
          </div>        </div>
      </header>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="seg">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={filter === key ? "seg__btn seg__btn--active" : "seg__btn"}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="seg">
          {(
            [
              ["desbloqueo", "Por desbloqueo"],
              ["equipo", "Por equipo"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setGroup(key)}
              className={group === key ? "seg__btn seg__btn--active" : "seg__btn"}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar jugador o rival"
          className="h-8 w-44 rounded-lg border border-[color:var(--line-strong)] bg-white/[0.04] px-2.5 text-xs text-white outline-none placeholder:text-faint"
        />
      </div>

      <p className="mt-3 text-[11px] leading-4 text-faint">
        Diff contra la foto del <span className="font-mono">{dayLabel(payload.from_day)}</span> · lectura del{" "}
        <span className="font-mono">{dayLabel(payload.photo_day)}</span>
        {typeof payload.diff_gap_days === "number" && payload.diff_gap_days > 1
          ? ` (${payload.diff_gap_days} días de diferencia: una subida marcada puede ser de cualquiera de esos días)`
          : ""}
        . El histórico se guarda una vez al día, así que una subida aparece al refrescar. Coste de subirla: la mitad
        del incremento (redondeo al alza).
      </p>

      <p className="mt-2 rounded-xl border border-white/[0.07] bg-white/[0.04] px-2.5 py-2 text-[11px] leading-4 text-white/50">
        <span className="font-semibold text-white">Ojo con las subidas.</span> En un jugador <span className="font-medium">fichado</span> la
        cláusula se queda en el mayor de 1 M€, el precio pagado o su valor de mercado: si el valor sube, la cláusula sube{" "}
        <span className="font-medium text-warn">gratis</span> y el rival no paga nada. Solo hay{" "}
        <span className="font-medium text-coral">subida pagada</span> cuando la cláusula supera ese techo. En un jugador de
        reparto la cláusula no flota: cualquier salto lo puso el rival con su caja.
      </p>

      {!rows.length ? (
        <p className="mt-5 text-sm text-white/50">
          {query || filter !== "todos"
            ? "Ningún jugador cumple este filtro."
            : "La foto no trae cláusulas rivales."}
        </p>
      ) : grouped ? (
        <div className="mt-4 space-y-5">
          {grouped.map(([team, list]) => (
            <section key={team}>
              <p className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
                <span className="text-white">{team}</span>
                <span className="font-mono font-normal">{list.length}</span>
                <span className="font-normal normal-case text-faint">· abre {unlockLabel(list[0])}</span>
              </p>
              <ClauseCards rows={list} cash={cash} onOpenTeam={(teamId) => onOpenTeam?.(teamId)} />
              <ClauseTable rows={list} cash={cash} onOpenTeam={(teamId) => onOpenTeam?.(teamId)} />
            </section>
          ))}
        </div>
      ) : (
        <div className="mt-4">
          <ClauseCards rows={rows} cash={cash} onOpenTeam={(teamId) => onOpenTeam?.(teamId)} />
          <ClauseTable rows={rows} cash={cash} onOpenTeam={(teamId) => onOpenTeam?.(teamId)} />
        </div>
      )}

      <p className="mt-4 text-[11px] leading-4 text-faint">
        Una cláusula sin marca de subida no significa que el rival no la haya movido nunca: el histórico empieza el día
        en que se guardó la primera foto. La columna «antes» solo aparece cuando hay dos lecturas comparables.
      </p>
    </article>
  );
}

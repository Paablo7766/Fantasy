"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { eur, glass, playerName, points } from "@/lib/core/format";
import { applyLiquidity, financialIndex, liquidityRead } from "@/lib/liga/liquidity";
import { enrichSquadsPayload } from "@/lib/liga/squadEnrich";
import type { ClauseIntelPayload, NeedsPayload, RivalIntelPayload, RivalSquad, SquadsPayload, TrendsPayload } from "@/lib/types";
import { ThermometerIcon } from "./dashboard/Liquidity";
import { RivalListCard } from "./dashboard/RivalListCard";
import { RivalSheet } from "./dashboard/RivalSheet";
import type { RivalSort } from "./dashboard/shared";
import { sortSquads, windowLabel } from "./dashboard/shared";

function ExtraBlock({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-[color:var(--line)]">
      <button type="button" className="flex w-full items-center justify-between gap-3 py-3.5 text-left" onClick={onToggle}>
        <span className="text-sm font-semibold text-ink">{title}</span>
        <span className="text-[12px] text-muted">
          {count} · {open ? "Ocultar" : "Ver"}
        </span>
      </button>
      {open ? <div className="pb-4">{children}</div> : null}
    </div>
  );
}

export function RivalsDashboard({
  squads,
  needs,
  trends = null,
  clauseIntel = null,
  rivalIntel = null,
  clauseIntelLoading = false,
  loading = false,
}: {
  squads: SquadsPayload | null;
  needs: NeedsPayload | null;
  trends?: TrendsPayload | null;
  clauseIntel?: ClauseIntelPayload | null;
  /** Auditoría de caja (``/api/rival-intel``): trae la cota calibrada. */
  rivalIntel?: RivalIntelPayload | null;
  clauseIntelLoading?: boolean;
  loading?: boolean;
}) {
  const [selectedTeam, setSelectedTeam] = useState<string | null>(null);
  const [rivalSort, setRivalSort] = useState<RivalSort>("rank");
  const [showOffers, setShowOffers] = useState(false);
  const [showClauses, setShowClauses] = useState(false);
  const view = useMemo(() => enrichSquadsPayload(squads, trends), [squads, trends]);
  const financials = useMemo(
    () => financialIndex(rivalIntel?.ok === false ? null : rivalIntel?.teams),
    [rivalIntel],
  );
  // Sin la cota calibrada la tarjeta mentiría: se fusiona la auditoría de caja
  // sobre el perfil de plantillas antes de ordenar o de abrir la ficha.
  const rivals = useMemo(
    () =>
      (view?.rivals || [])
        .map((row) => applyLiquidity(row, financials.get(String(row.team_id))))
        .filter((row): row is RivalSquad => row !== null),
    [view, financials],
  );
  const own = useMemo(
    () => applyLiquidity(view?.self, view?.self ? financials.get(String(view.self.team_id)) : null),
    [view, financials],
  );
  const ownTeamId = own?.team_id != null ? String(own.team_id) : null;
  const leagueSquads = useMemo(() => {
    const all = [...rivals];
    if (own) all.push(own);
    return all;
  }, [rivals, own]);
  const sortedSquads = useMemo(() => sortSquads(leagueSquads, rivalSort), [leagueSquads, rivalSort]);
  const calibratedCount = useMemo(() => leagueSquads.filter((row) => liquidityRead(row).tightened).length, [leagueSquads]);
  const selectedSquad = useMemo(
    () => (selectedTeam ? leagueSquads.find((row) => String(row.team_id) === selectedTeam) || null : null),
    [selectedTeam, leagueSquads],
  );

  if (loading && !squads) return <Skeleton title="Rivales" rows={6} />;
  if (!view || view.ok === false) {
    return <ErrorCard title="Rivales" payload={view || squads || { error: { message: "Sin plantillas." } }} brief />;
  }

  const clauses = view.clauses || [];
  const offers = clauseIntel?.ok !== false ? clauseIntel?.offers || [] : [];
  const selectedOffers = selectedTeam ? offers.filter((row) => String(row.team_id) === selectedTeam) : [];

  return (
    <article className={glass("p-4 md:p-6")}>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Liga</p>
          <h2 className="section-title mt-1">{leagueSquads.length} managers</h2>
          <p className="section-support">Lista corta. Entra en un rival para ver plantilla y su mercado.</p>
          {calibratedCount ? (
            <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-faint">
              <ThermometerIcon className="h-3.5 w-3.5 text-mint" />
              <span className="font-medium text-mint">{calibratedCount}</span>
              caja(s) calibrada(s) por el grupo de control: la puja máxima ya descuenta el riesgo contable.
            </p>
          ) : null}
        </div>
        <div className="seg flex-wrap justify-end">
          {(
            [
              ["rank", "Puesto"],
              ["patrimonio", "Patrimonio"],
              ["cash", "Caja"],
              ["delta", "Δ hoy"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setRivalSort(key)}
              className={rivalSort === key ? "seg__btn seg__btn--active" : "seg__btn"}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <div className="divide-y divide-[color:var(--line)] rounded-2xl border border-[color:var(--line)] bg-[color:var(--surface)]">
        {sortedSquads.length ? (
          sortedSquads.map((squad) => {
            const teamId = String(squad.team_id);
            return (
              <RivalListCard
                key={teamId}
                squad={squad}
                sort={rivalSort}
                isSelf={ownTeamId !== null && teamId === ownTeamId}
                onOpen={() => setSelectedTeam(teamId)}
              />
            );
          })
        ) : (
          <p className="px-4 py-6 text-sm text-muted">La liga no devolvió plantillas.</p>
        )}
      </div>

      <div className="mt-8">
        <ExtraBlock title="Clausulazos" count={offers.length} open={showOffers} onToggle={() => setShowOffers((value) => !value)}>
          <p className="mb-2 text-[11px] text-faint">{windowLabel(clauseIntel)}</p>
          {clauseIntelLoading && !clauseIntel ? (
            <p className="text-sm text-muted">Calculando…</p>
          ) : offers.length ? (
            <ul className="space-y-2">
              {offers.map((row) => (
                <li key={String(row.player_id)}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-3 text-left"
                    onClick={() => row.team_id != null && setSelectedTeam(String(row.team_id))}
                  >
                    <span className="min-w-0 truncate text-sm text-ink">
                      {playerName(row)}
                      <span className="text-muted"> · {row.manager_name || ""}</span>
                    </span>
                    <span className="metric-value text-xs text-mint">
                      {typeof row.points_delta === "number" ? `+${points(row.points_delta)}` : eur(row.buyout_clause_eur)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Ningún clausulazo mejora el XI ahora.</p>
          )}
        </ExtraBlock>
        <ExtraBlock title="Cláusulas interesantes" count={clauses.length} open={showClauses} onToggle={() => setShowClauses((value) => !value)}>
          {clauses.length ? (
            <ul className="space-y-2">
              {clauses.map((row) => (
                <li key={`${row.team_id}-${row.player_id}`}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-3 text-left"
                    onClick={() => row.team_id != null && setSelectedTeam(String(row.team_id))}
                  >
                    <span className="min-w-0 truncate text-sm text-ink">
                      {playerName(row)}
                      <span className="text-muted"> · {row.manager_name || ""}</span>
                    </span>
                    <span className="metric-value text-xs">{eur(row.buyout_clause_eur)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Ninguna cláusula cumple la regla de oro.</p>
          )}
          <p className="mt-2 text-[11px] leading-4 text-faint">
            Solo aparecen los chollos de la regla de oro. Para ver <strong className="font-semibold">todas</strong> las
            cláusulas de la liga, con la subida de cada jugador: pestaña «Todas las cláusulas».
          </p>
        </ExtraBlock>
      </div>

      <RivalSheet
        squad={selectedSquad}
        isSelf={selectedTeam !== null && selectedTeam === ownTeamId}
        needs={needs}
        clauses={clauses}
        clauseOffers={selectedOffers}
        onClose={() => setSelectedTeam(null)}
      />
    </article>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { clockLabel, deltaEur, deltaTone, eur, initials, multiple, playerName, points } from "@/lib/core/format";
import { liquidityRead } from "@/lib/liga/liquidity";
import { squadHoldings } from "@/lib/liga/squadTotals";
import type { ClauseIntelOffer, ClauseRow, NeedsPayload, RivalSquad } from "@/lib/types";
import { CalibratedBadge, CalibratedCash, LiquidityBand, ThermometerBar } from "./Liquidity";
import { MarketTab, PlayerDeal } from "./MarketTab";
import { Metric } from "./Metric";
import type { SheetTab } from "./shared";
import { ledgerFromNeeds, positionGroups, rankTone, rivalLabel } from "./shared";

export function RivalSheet({
  squad,
  isSelf,
  needs,
  clauses,
  clauseOffers,
  onClose,
}: {
  squad: RivalSquad | null;
  isSelf: boolean;
  needs: NeedsPayload | null;
  clauses: ClauseRow[];
  clauseOffers: ClauseIntelOffer[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<SheetTab>("plantilla");
  const [openPlayer, setOpenPlayer] = useState<string | null>(null);
  const teamId = squad?.team_id != null ? String(squad.team_id) : null;

  // Al cambiar de rival, la ficha vuelve a la pestaña de plantilla. Se ajusta
  // durante el render (patrón de React) en vez de sembrarlo desde un efecto.
  const [shownTeamId, setShownTeamId] = useState(teamId);
  if (shownTeamId !== teamId) {
    setShownTeamId(teamId);
    setTab("plantilla");
    setOpenPlayer(null);
  }

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (squad && !dialog.open) dialog.showModal();
    if (!squad && dialog.open) dialog.close();
  }, [squad]);

  if (!squad || !teamId) {
    return (
      <dialog ref={ref} className="bid-dialog rival-dialog" onClose={onClose}>
        <div className="bid-dialog__body" />
      </dialog>
    );
  }

  const holdings = squadHoldings(squad);
  const read = liquidityRead(squad);
  const players = squad.players || [];
  const groups = positionGroups(players);
  const events = squad.activity_profile?.recent_events || [];
  const teamClauses = clauses.filter((row) => String(row.team_id) === teamId);
  // La ficha muestra la plantilla **entera** con cláusula: ``squads.clauses``
  // solo publica las que cumplen la regla de oro y dejaría fuera a la mayoría.
  const teamSheetClauses: ClauseRow[] = players
    .filter((player) => typeof player.buyout_clause === "number" && player.buyout_clause > 0)
    .map((player) => ({
      team_id: teamId,
      manager_name: squad.manager_name,
      fantasy_team_name: squad.fantasy_team_name,
      player_id: player.player_id,
      name: player.name,
      nickname: player.nickname,
      position: player.position,
      club: player.club,
      image_url: player.image_url,
      buyout_clause_eur: player.buyout_clause,
      market_value: player.market_value,
      average_points: player.own_expected_points ?? null,
      clause_multiple: player.clause_multiple ?? null,
      is_shielded: player.is_shielded === true,
      is_locked: player.clause_lock?.is_locked ?? undefined,
      clause_lock: player.clause_lock ?? null,
      clause_rule: teamClauses.find((row) => String(row.player_id) === String(player.player_id))?.clause_rule ?? null,
    }))
    .sort((a, b) => {
      const da = `${a.clause_lock?.local_date || "9999-99-99"}T${a.clause_lock?.local_time || "99:99"}`;
      const db = `${b.clause_lock?.local_date || "9999-99-99"}T${b.clause_lock?.local_time || "99:99"}`;
      if (da !== db) return da.localeCompare(db);
      return (b.buyout_clause_eur || 0) - (a.buyout_clause_eur || 0);
    });
  const tabs: { id: SheetTab; label: string }[] = [
    { id: "plantilla", label: "Plantilla" },
    { id: "mercado", label: "Mercado" },
    { id: "clausulas", label: "Cláusulas" },
  ];

  return (
    <dialog
      ref={ref}
      className="bid-dialog rival-dialog"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="bid-dialog__body scroll-thin">
        <div className="rival-sheet-head">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className={`${rankTone(squad.rank, isSelf)} !h-12 !w-12 !text-base`}>
                {typeof squad.rank === "number" ? squad.rank : initials(rivalLabel(squad))}
              </div>
              <div className="min-w-0">
                <p className="eyebrow">{isSelf ? "Tu equipo" : "Rival"}</p>
                <h3 className="truncate text-xl font-semibold tracking-tight text-ink">{rivalLabel(squad)}</h3>
              </div>
            </div>
            <button type="button" className="btn btn-secondary shrink-0" onClick={onClose}>
              Cerrar
            </button>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[color:var(--line)] pt-4">
            <div>
              <div className="flex flex-wrap items-center gap-1.5">
                <p className="metric-label">Caja</p>
                <CalibratedBadge read={read} compact />
              </div>
              <p className="mt-1">
                <CalibratedCash read={read} size="lg" />
              </p>
              {read.tightened && read.temperaturePct !== null ? (
                <p className="mt-1 flex items-center gap-1.5 text-[10.5px] text-faint">
                  <ThermometerBar read={read} className="w-10" />
                  {read.temperaturePct} % de confianza
                </p>
              ) : null}
            </div>
            <Metric label="Cobrado" value={eur(squad.activity_profile?.sales_eur)} tone="text-mint" />
            <Metric label="Plusvalía" value={deltaEur(holdings.gain_eur)} tone={deltaTone(holdings.gain_eur)} />
          </div>

          <div className="seg mt-4 w-full">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? "seg__btn seg__btn--active" : "seg__btn"}
                onClick={() => setTab(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4">
          <LiquidityBand read={read} label="Banda de liquidez · puja máxima" />
        </div>

        {tab === "plantilla" ? (
          <section className="mt-5 space-y-5">
            <p className="text-[12px] text-muted">Pulsa un jugador para ver qué pagó, cuánto vale y su ROI.</p>
            {groups.length ? (
              groups.map((group) => (
                <div key={group.position}>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
                    {group.label}
                    <span className="ml-2 font-mono font-normal">{group.rows.length}</span>
                  </p>
                  <div className="space-y-2">
                    {group.rows.map((player) => {
                      const id = String(player.player_id);
                      return (
                        <PlayerDeal
                          key={id}
                          player={player}
                          events={events}
                          open={openPlayer === id}
                          onToggle={() => setOpenPlayer(openPlayer === id ? null : id)}
                        />
                      );
                    })}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted">Esta plantilla no trae jugadores.</p>
            )}
          </section>
        ) : null}

        {tab === "mercado" ? (
          <section className="mt-5">
            <MarketTab squad={squad} ledger={ledgerFromNeeds(needs, teamId)} />
          </section>
        ) : null}

        {tab === "clausulas" ? (
          <section className="mt-5 space-y-4">
            {clauseOffers.map((row) => (
              <div key={String(row.player_id)} className="flex items-center gap-3">
                <PlayerAvatar player={row} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-ink">{playerName(row)}</p>
                  <p className="text-[11px] text-muted">
                    {eur(row.buyout_clause_eur)}
                    {typeof row.points_delta === "number" ? ` · +${points(row.points_delta)} pts` : ""}
                  </p>
                </div>
                <span className={row.decision === "PAGAR" ? "badge badge--good" : "badge badge--warn"}>
                  {row.decision === "PAGAR" ? "Pagar" : "Alternativa"}
                </span>
              </div>
            ))}
            <div className="space-y-2 border-t border-[color:var(--line)] pt-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-faint">
                Plantilla completa con cláusula
                <span className="ml-2 font-mono font-normal">{teamSheetClauses.length}</span>
              </p>
              {teamSheetClauses.map((row) => (
                <div key={`${row.team_id}-${row.player_id}`} className="flex items-baseline justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">
                      {playerName(row)}
                      {typeof row.average_points === "number" ? (
                        <span className="text-faint"> · {points(row.average_points)} pts</span>
                      ) : null}
                    </p>
                    <p className="text-[11px] text-muted">
                      {eur(row.buyout_clause_eur)} · {multiple(row.clause_multiple)} · {clockLabel(row.clause_lock)}
                      {row.is_shielded ? " · blindado" : ""}
                    </p>
                  </div>
                  {row.clause_rule ? (
                    <span className={`shrink-0 text-[11px] font-medium ${row.clause_rule === "A" ? "text-mint" : "text-gold"}`}>
                      Regla {row.clause_rule}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[11px] text-faint">fuera de regla</span>
                  )}
                </div>
              ))}
              {!teamSheetClauses.length ? (
                <p className="text-sm text-muted">Este rival no tiene cláusulas en esta lectura.</p>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </dialog>
  );
}

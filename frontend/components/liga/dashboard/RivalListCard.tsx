"use client";

import { DebtBanner } from "@/components/liga/StrategyBits";
import { eur, eurShort, initials } from "@/lib/core/format";
import { liquidityRead } from "@/lib/liga/liquidity";
import type { RivalSquad } from "@/lib/types";
import { CalibratedBadge, CalibratedCash, ThermometerBar } from "./Liquidity";
import type { RivalSort } from "./shared";
import { listMetric, rankTone, rivalInDebt, rivalLabel } from "./shared";

export function RivalListCard({
  squad,
  isSelf,
  sort,
  onOpen,
}: {
  squad: RivalSquad;
  isSelf: boolean;
  sort: RivalSort;
  onOpen: () => void;
}) {
  const name = rivalLabel(squad);
  const teamName = squad.fantasy_team_name && squad.fantasy_team_name !== name ? squad.fantasy_team_name : null;
  const metric = listMetric(squad, sort);
  const read = liquidityRead(squad);
  const inDebt = !isSelf && rivalInDebt(squad, read);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`rival-card group w-full px-4 py-3.5 text-left ${isSelf ? "rival-card--self" : ""} ${inDebt ? "rival-card--debt" : ""}`}
    >
      <div className="flex items-center gap-3">
        <div className={rankTone(squad.rank, isSelf)}>
          {typeof squad.rank === "number" ? squad.rank : initials(name).slice(0, 2)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[15px] font-semibold tracking-tight text-ink">{name}</span>
            {isSelf ? <span className="badge badge--good text-[10px]">Tú</span> : null}
            {inDebt ? <span className="badge badge--bad text-[10px]">Saldo negativo</span> : null}
            <CalibratedBadge read={read} compact />
          </div>
          <p className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-[12px] text-muted">
            {teamName ? <span className="truncate">{teamName} ·</span> : null}
            <span>caja</span>
            <CalibratedCash read={read} />
            {read.temperaturePct !== null && (read.tightened || read.level !== "alta") ? (
              <span className="inline-flex items-center gap-1 text-[10.5px] text-faint">
                <ThermometerBar read={read} className="w-8" />
                {read.temperaturePct} %
              </span>
            ) : null}
          </p>
          {inDebt ? <DebtBanner /> : null}
        </div>
        <div className="shrink-0 text-right">
          <p className={`metric-value text-sm ${metric.tone || "text-ink"}`}>{metric.value}</p>
          <p className="text-[10px] text-faint">{metric.label}</p>
          {sort === "cash" && read.bidTightened && typeof read.rawBidLimit === "number" ? (
            <p className="text-[10px] text-faint" title={`Tope sin calibrar: ${eur(read.rawBidLimit)}`}>
              antes {eurShort(read.rawBidLimit)}
            </p>
          ) : null}
        </div>
      </div>
    </button>
  );
}

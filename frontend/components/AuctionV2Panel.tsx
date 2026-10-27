"use client";

import { eur, pct } from "@/lib/format";
import type { MarketDecision } from "@/lib/types";

const INTENT_LABEL: Record<string, string> = {
  FLIP: "Especulación",
  STRUCTURAL: "Estructural",
  NONE: "Sin lectura",
};

function winPct(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  if (value > 1) return pct(value / 100);
  return pct(value);
}

function winFraction(value: number): number {
  const raw = value > 1 ? value / 100 : value;
  return Math.max(0, Math.min(1, raw));
}

function winBarTone(fraction: number): string {
  if (fraction >= 0.7) return "bg-mint";
  if (fraction >= 0.4) return "bg-gold";
  return "bg-coral";
}

function WinProbabilityMeter({
  value,
  compact = false,
}: {
  value: number;
  compact?: boolean;
}) {
  const fraction = winFraction(value);
  const widthPct = Math.round(fraction * 100);
  if (compact) {
    return (
      <span className="inline-flex min-w-[4.5rem] items-center gap-1.5">
        <span className="h-1 w-10 overflow-hidden rounded-full bg-[color:var(--line)]">
          <span className={`block h-full rounded-full ${winBarTone(fraction)}`} style={{ width: `${widthPct}%` }} />
        </span>
        <span className="text-muted">{winPct(value)}</span>
      </span>
    );
  }
  return (
    <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-faint">Prob. victoria</span>
        <span className="metric-value text-sm">{winPct(value)}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-[color:var(--line)]">
        <div className={`h-full rounded-full ${winBarTone(fraction)}`} style={{ width: `${widthPct}%` }} />
      </div>
    </div>
  );
}

function intentTone(intent: string | null | undefined): string {
  if (intent === "STRUCTURAL") return "badge badge--good";
  if (intent === "FLIP") return "badge badge--warn";
  return "badge";
}

type Variant = "compact" | "full";

export function AuctionV2Panel({
  player,
  variant = "full",
}: {
  player: MarketDecision;
  variant?: Variant;
}) {
  const optimal = player.optimal_bid_eur;
  const hasAuction =
    typeof optimal === "number" ||
    typeof player.win_probability === "number" ||
    typeof player.intrinsic_valuation_eur === "number" ||
    typeof player.expected_surplus_eur === "number" ||
    (player.rival_knockout_targets?.length ?? 0) > 0 ||
    Boolean(player.bid_intent);

  if (!hasAuction) return null;

  const intent = player.bid_intent;
  const knockouts = player.rival_knockout_targets?.filter(Boolean) ?? [];

  if (variant === "compact") {
    return (
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
        {typeof optimal === "number" ? (
          <span className="rounded-md bg-[color:var(--gold-soft)] px-1.5 py-0.5 font-medium text-gold">
            Óptima v2 {eur(optimal)}
          </span>
        ) : null}
        {typeof player.win_probability === "number" ? (
          <WinProbabilityMeter value={player.win_probability} compact />
        ) : null}
        {intent ? <span className={intentTone(intent)}>{INTENT_LABEL[intent] || intent}</span> : null}
        {knockouts.length ? (
          <span className="rounded-md border border-coral/40 bg-coral/10 px-1.5 py-0.5 text-coral">
            KO {knockouts.slice(0, 2).join(", ")}
            {knockouts.length > 2 ? ` +${knockouts.length - 2}` : ""}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <section className="mt-4 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3.5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">Subasta v2.0</p>
        {intent ? <span className={intentTone(intent)}>{INTENT_LABEL[intent] || intent}</span> : null}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {typeof optimal === "number" ? (
          <div className="rounded-lg bg-[color:var(--gold-soft)] px-3 py-2">
            <dt className="text-[11px] text-faint">Puja óptima</dt>
            <dd className="metric-value mt-0.5 text-sm text-gold">{eur(optimal)}</dd>
          </div>
        ) : null}
        {typeof player.win_probability === "number" ? (
          <WinProbabilityMeter value={player.win_probability} />
        ) : null}
        {typeof player.intrinsic_valuation_eur === "number" ? (
          <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
            <dt className="text-[11px] text-faint">Valor intrínseco</dt>
            <dd className="metric-value mt-0.5 text-sm">{eur(player.intrinsic_valuation_eur)}</dd>
          </div>
        ) : null}
        {typeof player.expected_surplus_eur === "number" ? (
          <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
            <dt className="text-[11px] text-faint">Superávit esperado</dt>
            <dd className="metric-value mt-0.5 text-sm text-mint">{eur(player.expected_surplus_eur)}</dd>
          </div>
        ) : null}
      </dl>
      {knockouts.length ? (
        <div className="mt-3 rounded-lg border border-coral/35 bg-coral/10 px-3 py-2.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-coral">Knock-out de caja rival</p>
          <p className="mt-1 text-sm leading-5 text-ink">
            Puja justo por encima del techo de{" "}
            <span className="font-medium">{knockouts.join(", ")}</span> para eliminarlos sin pagar de más.
          </p>
        </div>
      ) : null}
    </section>
  );
}

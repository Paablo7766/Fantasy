import type { CatalogPlayer, MarketDecision, Player, TrendsPayload } from "@/lib/types";

export type SignalDiscrepancyKind = "signal_cross" | "ceiling_gap" | "delta_cross" | "bid_cap_conflict";

export type SignalDiscrepancyRow = {
  player: MarketDecision | CatalogPlayer;
  kinds: SignalDiscrepancyKind[];
  headline: string;
  severity: number;
  inMarket: boolean;
};

const KIND_LABEL: Record<SignalDiscrepancyKind, string> = {
  signal_cross: "Señal opuesta",
  ceiling_gap: "Techo AF > own",
  delta_cross: "Previsión cruzada",
  bid_cap_conflict: "Topes no cuadran",
};

export function discrepancyKindLabel(kind: SignalDiscrepancyKind): string {
  return KIND_LABEL[kind];
}

function normSignal(value: string | null | undefined): "up" | "down" | null {
  if (value === "up" || value === "down") return value;
  return null;
}

function analyzePlayer(player: Player, inMarket: boolean): SignalDiscrepancyRow | null {
  const kinds: SignalDiscrepancyKind[] = [];
  let severity = 0;

  const afSig = normSignal(player.af_market_signal);
  const ownSig = normSignal(player.own_market_signal);
  if (afSig && ownSig && afSig !== ownSig) {
    kinds.push("signal_cross");
    severity += 40;
  }

  const afMax = player.af_max_bid;
  const ownMax = player.own_max_bid;
  if (typeof afMax === "number" && typeof ownMax === "number" && afMax > ownMax + 25_000) {
    kinds.push("ceiling_gap");
    severity += 30 + Math.min(25, Math.round((afMax - ownMax) / 200_000));
  }

  const afDelta = player.af_predicted_delta;
  const ownDelta = player.own_predicted_delta;
  if (
    typeof afDelta === "number" &&
    typeof ownDelta === "number" &&
    afDelta * ownDelta < 0 &&
    Math.abs(afDelta) >= 20_000 &&
    Math.abs(ownDelta) >= 20_000
  ) {
    kinds.push("delta_cross");
    severity += 25;
  }

  const bidLimit = (player as MarketDecision).bid_limit;
  if (bidLimit === "fuentes_no_coinciden") {
    kinds.push("bid_cap_conflict");
    severity += 35;
  }

  if (!kinds.length) return null;

  const parts: string[] = [];
  if (kinds.includes("signal_cross")) {
    parts.push(`AF ${afSig === "up" ? "sube" : "baja"} · own ${ownSig === "up" ? "sube" : "baja"}`);
  }
  if (kinds.includes("ceiling_gap") && typeof afMax === "number" && typeof ownMax === "number") {
    parts.push(`techo AF ${Math.round(afMax / 1_000_000)}M vs own ${Math.round(ownMax / 1_000_000)}M`);
  }
  if (kinds.includes("delta_cross")) {
    parts.push("Δ mañana con signo contrario");
  }
  if (kinds.includes("bid_cap_conflict")) {
    parts.push("puja limitada por fuentes");
  }

  if (inMarket) severity += 15;

  return {
    player: player as MarketDecision | CatalogPlayer,
    kinds,
    headline: parts.join(" · "),
    severity,
    inMarket,
  };
}

export function buildSignalDiscrepancies(trends: TrendsPayload | null, limit = 24): SignalDiscrepancyRow[] {
  if (!trends || trends.ok === false) return [];

  const seen = new Set<string>();
  const rows: SignalDiscrepancyRow[] = [];

  const decisions = Array.isArray(trends.market_decisions) ? trends.market_decisions : [];
  for (const row of decisions) {
    const id = String(row.player_id || "");
    if (!id || seen.has(id)) continue;
    const hit = analyzePlayer(row, true);
    if (hit) {
      seen.add(id);
      rows.push(hit);
    }
  }

  const catalog = Array.isArray(trends.catalog) ? trends.catalog : [];
  for (const row of catalog) {
    const id = String(row.player_id || "");
    if (!id || seen.has(id)) continue;
    const hit = analyzePlayer(row, false);
    if (hit) {
      seen.add(id);
      rows.push(hit);
    }
  }

  rows.sort((a, b) => b.severity - a.severity);
  return rows.slice(0, limit);
}

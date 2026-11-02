import { TONE } from "@/components/equipo/ui";
import { eur, pct } from "@/lib/format";
import type { MarketAction } from "@/lib/marketAction";
import type { MarketDecision, MarketDecisionSummary } from "@/lib/types";

export const ACTION_VERDICT: Record<MarketAction, { label: string; color: string }> = {
  PUJAR: { label: "Pujar", color: TONE.green },
  ESPERAR: { label: "Esperar", color: TONE.amber },
  NO: { label: "No", color: TONE.gray },
};

const DIFFICULTY: Record<string, string> = {
  muy_facil: "muy fácil",
  facil: "fácil",
  media: "media",
  dificil: "difícil",
  muy_dificil: "muy difícil",
};

export function difficultyLabel(key: string | null | undefined): string {
  if (!key) return "";
  return DIFFICULTY[key] || key.replace(/_/g, " ");
}

export function sourceLabel(player: MarketDecision): string {
  if (player.offer_source === "rival") return `venta de ${player.seller_manager || "un rival"}`;
  if (player.offer_source === "propio") return "tu venta";
  return "liga";
}

/** P(ganar) llega como fracción o como porcentaje según la fuente. */
export function winShare(value: number | null | undefined): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return Math.max(0, Math.min(1, value > 1 ? value / 100 : value));
}

/** Reparto de la caja entre los mercados que quedan hasta la jornada. */
export function budgetLine(summary: MarketDecisionSummary): string | null {
  const markets = summary.markets_left;
  const day = summary.day_budget_eur;
  if (typeof markets === "number" && markets > 1 && typeof day === "number") {
    return `Quedan ${markets} mercados hasta la jornada: hoy como mucho ${eur(day)}; el resto se guarda.`;
  }
  return null;
}

/** Lo que la liga suele pagar de más cuando hay guerra de pujas. */
export function historyLine(summary: MarketDecisionSummary): string {
  const wars = summary.league_war_count ?? 0;
  const median = summary.league_median_premium;
  const priced = summary.league_priced_count ?? 0;
  const buys = summary.league_buy_count ?? 0;
  if (wars >= 3 && typeof median === "number") {
    return `Cuando hay guerra, la compra ganadora queda un ${pct(median)} por encima del valor de ese día (${priced || wars} compras con valor guardado).`;
  }
  if (priced > 0) {
    return `Historial: ${priced} compras con valor de ese día. Hacen falta 3 guerras de rivales que puedan pagar para fijar la sobrepuja.`;
  }
  if (buys > 0) {
    return `Historial: ${buys} compras leídas, sin el valor de esos días no se mide la sobrepuja.`;
  }
  return "Sin historial de sobrepujas de la liga: la cifra es el precio justo, no lo que suele hacer falta para ganar.";
}

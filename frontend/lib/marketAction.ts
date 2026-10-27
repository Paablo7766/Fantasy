import type { MarketDecision } from "@/lib/types";

/**
 * Comando único de mercado. El backend ya manda `action` (PUJAR / ESPERAR / NO)
 * y `action_reason`; `decision` se conserva solo como respaldo de lecturas
 * antiguas. Aquí no se recalcula el veredicto: se elige qué campo mostrar.
 */
export type MarketAction = "PUJAR" | "ESPERAR" | "NO";

const ACTIONS = new Set<string>(["PUJAR", "ESPERAR", "NO"]);

export function marketAction(player: Partial<MarketDecision> | null | undefined): MarketAction {
  const raw = player?.action || player?.decision;
  if (typeof raw === "string" && ACTIONS.has(raw)) return raw as MarketAction;
  return "NO";
}

/** Un veto anula la cifra: nunca se pinta «PUJAR» junto a un importe vetado. */
export function isVetoed(player: Partial<MarketDecision> | null | undefined): boolean {
  if (player?.is_vetoed === true) return true;
  return marketAction(player) === "NO" && typeof player?.suggested_bid !== "number";
}

export function actionTone(action: MarketAction | null | undefined): string {
  if (action === "PUJAR") return "badge badge--good";
  if (action === "ESPERAR") return "badge badge--warn";
  return "badge badge--bad";
}

/** Frase del motor; si falta, se cae al motivo y por último a un texto neutro. */
export function actionReason(
  player: Partial<MarketDecision> | null | undefined,
  fallback?: string | null,
): string | null {
  const reason = typeof player?.action_reason === "string" ? player.action_reason.trim() : "";
  if (reason) return reason;
  if (fallback) return fallback;
  return null;
}

/** Cifra ejecutable: con veto no hay puja que ofrecer. */
export function executableBid(player: Partial<MarketDecision> | null | undefined): number | null {
  if (isVetoed(player)) return null;
  if (typeof player?.optimal_bid_eur === "number") return player.optimal_bid_eur;
  if (typeof player?.suggested_bid === "number") return player.suggested_bid;
  return null;
}

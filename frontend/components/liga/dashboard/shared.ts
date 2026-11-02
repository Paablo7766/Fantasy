import { deltaEur, deltaTone, eur, eurShort } from "@/lib/core/format";
import { liquidityRead, temperatureClasses, type LiquidityRead } from "@/lib/liga/liquidity";
import { squadHoldings, squadPatrimonio, squadTotals } from "@/lib/liga/squadTotals";
import type { ActivityEvent, ClauseIntelPayload, NeedRival, NeedsPayload, RivalPlayer, RivalSquad } from "@/lib/types";

export type RivalSort = "rank" | "patrimonio" | "cash" | "value" | "delta";

export type SheetTab = "plantilla" | "mercado" | "clausulas";

export function rivalLabel(squad: RivalSquad): string {
  return squad.manager_name || squad.fantasy_team_name || String(squad.team_id || "Rival");
}

export function ledgerFromNeeds(needs: NeedsPayload | null, teamId: string): NeedRival["ledger"] | null {
  return (needs?.ok ? needs.rivals || [] : []).find((row) => String(row.team_id) === teamId)?.ledger ?? null;
}

export function sortKey(squad: RivalSquad, mode: RivalSort): number {
  if (mode === "cash") {
    // Ordena por la caja calibrada: es la que de verdad puede gastar.
    const cash = liquidityRead(squad).calibratedCash;
    return typeof cash === "number" ? cash : Number.NEGATIVE_INFINITY;
  }
  if (mode === "value") {
    const value = squadTotals(squad).market_value_total;
    return typeof value === "number" ? value : Number.NEGATIVE_INFINITY;
  }
  if (mode === "delta") {
    const delta = squadTotals(squad).price_delta_day;
    return typeof delta === "number" ? delta : Number.NEGATIVE_INFINITY;
  }
  if (mode === "patrimonio") {
    const patrimonio = squadPatrimonio(squad);
    return typeof patrimonio === "number" ? patrimonio : Number.NEGATIVE_INFINITY;
  }
  return Number.NEGATIVE_INFINITY;
}

export function sortSquads(list: RivalSquad[], mode: RivalSort): RivalSquad[] {
  return list.slice().sort((a, b) => {
    if (mode === "rank") {
      const left = typeof a.rank === "number" ? a.rank : 9999;
      const right = typeof b.rank === "number" ? b.rank : 9999;
      if (left !== right) return left - right;
      return rivalLabel(a).localeCompare(rivalLabel(b), "es");
    }
    const delta = sortKey(b, mode) - sortKey(a, mode);
    if (delta) return delta;
    return rivalLabel(a).localeCompare(rivalLabel(b), "es");
  });
}

export function windowLabel(intel: ClauseIntelPayload | null): string {
  if (!intel || intel.ok === false) return "Sin lectura";
  if (intel.clause_window_open === true) {
    const close = intel.clause_market_close;
    if (close?.local_date && close?.local_time) return `Abierta · cierra ${close.local_date} ${close.local_time}`;
    return "Abierta";
  }
  if (intel.clause_window_open === false) return "Cerrada";
  return "Ventana s/d";
}

export const POS_ORDER = ["POR", "DEF", "MC", "MED", "DEL"];

export const POS_LABEL: Record<string, string> = {
  POR: "Portería",
  DEF: "Defensa",
  MC: "Mediocampo",
  MED: "Mediocampo",
  DEL: "Delantera",
};

export function positionGroups(players: RivalPlayer[]) {
  const buckets = new Map<string, RivalPlayer[]>();
  for (const player of players) {
    const pos = String(player.position || "?").toUpperCase();
    buckets.set(pos, [...(buckets.get(pos) || []), player]);
  }
  const ordered = POS_ORDER.filter((pos) => buckets.has(pos)).map((pos) => ({
    position: pos,
    label: POS_LABEL[pos] || pos,
    rows: buckets.get(pos) || [],
  }));
  for (const [pos, rows] of buckets) {
    if (!POS_ORDER.includes(pos)) ordered.push({ position: pos, label: POS_LABEL[pos] || pos, rows });
  }
  return ordered;
}

export function acquisitionLabel(kind: string | null | undefined): string {
  if (kind === "clausula") return "Cláusula";
  if (kind === "mercado") return "Mercado";
  return "Sin origen";
}

export function rankTone(rank: number | null | undefined, isSelf: boolean): string {
  if (isSelf) return "rival-rank rival-rank--self";
  if (rank === 1) return "rival-rank rival-rank--gold";
  if (rank === 2) return "rival-rank rival-rank--silver";
  if (rank === 3) return "rival-rank rival-rank--bronze";
  return "rival-rank";
}

export function eventTone(event: ActivityEvent): string {
  if (event.kind === "sell" || (typeof event.signed_eur === "number" && event.signed_eur > 0)) return "text-mint";
  if (event.kind === "buy" || event.kind === "clause") return "text-coral";
  return "text-muted-strong";
}

export function listMetric(squad: RivalSquad, sort: RivalSort): { label: string; value: string; tone?: string } {
  const totals = squadTotals(squad);
  if (sort === "delta") {
    return { label: "Δ hoy", value: deltaEur(totals.price_delta_day), tone: deltaTone(totals.price_delta_day) };
  }
  if (sort === "cash") {
    // La caja calibrada ya va en la línea del nombre; aquí manda la puja máxima,
    // que es la cifra accionable cuando el techo se aprieta.
    const read = liquidityRead(squad);
    return {
      label: read.bidTightened ? "Puja calibrada" : "Puja máx.",
      value: eurShort(read.bidLimit),
      tone: temperatureClasses(read.level).text,
    };
  }
  if (sort === "patrimonio") {
    return { label: "Patrimonio", value: eur(squadPatrimonio(squad)), tone: "text-gold" };
  }
  if (sort === "value") {
    return { label: "Valor", value: eur(totals.market_value_total), tone: "text-ink" };
  }
  const holdings = squadHoldings(squad);
  if (typeof holdings.gain_eur === "number") {
    return { label: "Plusvalía", value: deltaEur(holdings.gain_eur), tone: deltaTone(holdings.gain_eur) };
  }
  return { label: "Δ hoy", value: deltaEur(totals.price_delta_day), tone: deltaTone(totals.price_delta_day) };
}

export function rivalInDebt(squad: RivalSquad, read: LiquidityRead): boolean {
  const shown = read.calibratedCash ?? read.cash ?? squad.cash_eur;
  return typeof shown === "number" && shown < 0;
}

// Plan de hoy (`/api/plan`): acciones, reloj, línea roja y estrategias.
import type { AsesorClausulas, RadarAntiRobo } from "./clausulas";
import type { ApiError, PhotoMeta } from "./common";
import type { AuditoriaVenta, PlanFichajes, ResumenVentas, VentaForzada } from "./fichajes";
import type { LeagueEdge, LeagueRacePayload, SquadsPayload } from "./liga";
import type { MarketDecision, TrendsPayload } from "./mercado";
import type { CapitanPick, OptimizePayload } from "./once";
import type { NeedsPayload } from "./rivales";

export type PlanPlayer = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  expected_points?: number | null;
};

export type PlanAction = {
  kind?: string;
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  club?: string | null;
  image_url?: string | null;
  amount_eur?: number | null;
  cash_after_eur?: number | null;
  when?: string | null;
  when_local_time?: string | null;
  detail?: string | null;
  requires_confirmation?: boolean;
  /** ``eligible: false`` = la acción no se puede ejecutar (p. ej. caja insuficiente). */
  eligible?: boolean;
  reason?: string | null;
  overbid_status?: string | null;
  bid_how?: string | null;
  points_delta?: number | null;
  objective?: number | null;
  target_clause_eur?: number | null;
  manager_name?: string | null;
  window_open?: boolean | null;
  /** Dónde viene una acción de once: `saved` = once guardado con menos de 11. */
  gap_reason?: "saved_invalid" | "market_gap" | null;
  signed_gaps?: string | null;
};

export type PlanProtectOption = {
  kind?: string;
  amount_eur?: number | null;
  cash_after_eur?: number | null;
  eligible?: boolean;
  reason?: string | null;
  requires_confirmation?: boolean;
  target_clause_eur?: number | null;
};

export type PlanProtectRow = PlanPlayer & {
  club?: string | null;
  image_url?: string | null;
  buyout_clause_eur?: number | null;
  threat_count?: number | null;
  richest_cash_eur?: number | null;
  top_rival?: { team_id?: string | null; manager_name?: string | null; cash_eur?: number | null } | null;
  cash_unknown?: boolean;
  options?: PlanProtectOption[];
};

export type PlanClockEvent = {
  kind?: string;
  label?: string;
  at?: string;
  local_date?: string;
  local_time?: string;
  local_clock?: string;
  timezone?: string;
  manager_name?: string | null;
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  is_self?: boolean;
  amount_eur?: number | null;
};

export type PlanMarketSummary = {
  pujar?: number;
  esperar?: number;
  no?: number;
  count?: number;
  cash_eur?: number | null;
  markets_left?: number | null;
  day_budget_eur?: number | null;
  plan_spend_eur?: number | null;
  plan_cash_after_eur?: number | null;
  league_war_count?: number;
  league_median_premium?: number | null;
};

/** Postura del motor según la brecha con el líder (``league_race.POSURES``). */
export type LeagueMode = {
  name: "ventaja" | "remontada" | "neutro" | "sin_tabla" | string;
  label?: string | null;
  headline?: string | null;
  detail?: string | null;
  gap_to_leader?: number | null;
  own_points?: number | null;
  own_rank?: number | null;
  leader?: {
    team_id?: string | null;
    manager_name?: string | null;
    points?: number | null;
    rank?: number | null;
  } | null;
  above?: LeagueEdge | null;
  below?: LeagueEdge | null;
};

export type PlanRedLineCheck = {
  key?: string;
  label?: string;
  status?: "ok" | "warn" | "fail" | "unknown" | string;
  detail?: string;
  value?: number | null;
};

export type PlanRedLine = {
  status?: "ok" | "warn" | "fail" | string;
  headline?: string;
  checks?: PlanRedLineCheck[];
  failing?: string[];
  warnings?: string[];
  pending_actions?: number | null;
};

/** Tarjeta de la home: qué / cuánto / cuándo / qué pasa si no lo haces. */
export type PlanPriorityAction = PlanAction & {
  rank?: number;
  verdict?: "HAZLO" | "NO" | string;
  what?: string | null;
  cost_eur?: number | null;
  cost_label?: string | null;
  when_label?: string | null;
  ignore?: string | null;
  blocked_reason?: string | null;
  is_lineup?: boolean;
};

export type PlanStrategyMove = PlanPlayer & {
  kind?: "vender" | "pujar" | "clausular" | string;
  amount_eur?: number | null;
  jornada_ev?: number | null;
  points_in_xi?: number | null;
  points_delta?: number | null;
  manager_name?: string | null;
  image_url?: string | null;
  replaces_name?: string | null;
  replaced_by_name?: string | null;
};

export type PlanStrategy = {
  id?: string;
  rank?: number;
  expected_points?: number | null;
  points_delta?: number | null;
  cash_after_eur?: number | null;
  spend_eur?: number | null;
  sale_income_eur?: number | null;
  net_eur?: number | null;
  points_per_million?: number | null;
  needs_sale?: boolean;
  cash_only?: boolean;
  value_delta_eur?: number | null;
  formation?: string | null;
  moves?: PlanStrategyMove[];
};

export type PlanPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  league_id?: string | null;
  league_name?: string | null;
  dashboard_at?: string | null;
  fetched_at?: string | null;
  stale?: boolean;
  cash_eur?: number | null;
  kickoff?: string | null;
  /** Postura del motor: ventaja / remontada / neutro / sin_tabla. */
  mode?: LeagueMode | null;
  league_race?: LeagueRacePayload | null;
  /** Línea roja: caja ≥ 0, XI de 11 y once guardado. */
  red_line?: PlanRedLine | null;
  /** Las 4 tarjetas: what / cost / when / ignore. */
  priority_actions?: PlanPriorityAction[];
  clock?: PlanClockEvent[];
  lineup?: {
    formation?: string | null;
    saved_formation?: string | null;
    expected_points?: number | null;
    saved_points?: number | null;
    points_delta?: number | null;
    enters?: PlanPlayer[];
    leaves?: PlanPlayer[];
    /** Once recomendado (no siempre viene; sirve para contar el XI). */
    xi?: PlanPlayer[];
    differs?: boolean;
    missing_inputs?: string[];
    /** false = el once guardado no junta 11 jugadores (hueco real, no mejora). */
    saved_valid?: boolean;
    recommended_valid?: boolean;
    missing_slots?: number;
    recommended_partial?: boolean;
    xi_changed?: boolean;
  };
  actions?: PlanAction[];
  decisions?: MarketDecision[];
  protect?: PlanProtectRow[];
  market_summary?: PlanMarketSummary | null;
  expert_mentions?: Array<
    PlanPlayer & {
      kind?: string | null;
      source?: string | null;
      mention?: string | null;
    }
  >;
  lineup_notes?: Array<
    PlanPlayer & {
      agreement?: string | null;
      club?: string | null;
    }
  >;
  expert_note?: string | null;
  clause_market_close?: { at?: string | null; local_date?: string; local_time?: string } | null;
  clause_offers?: Array<Record<string, unknown>>;
  /** Planes conjuntos: mercado + cláusulas + ventas que maximizan el once. */
  strategies?: PlanStrategy[];
  ratio_mercado?: number | null;
  capitan_seguro?: CapitanPick | null;
  capitan_remontada?: CapitanPick | null;
  plan_fichajes?: PlanFichajes | null;
  ventas_forzadas?: VentaForzada[];
  /** Una auditoría por jugador susceptible de venta (ofertas de LaLiga y rivales). */
  auditoria_ventas?: AuditoriaVenta[];
  resumen_ventas?: ResumenVentas | null;
  /** Jugadores tuyos en peligro con su cláusula perfecta y los mejores clausulazos. */
  asesor_clausulas?: AsesorClausulas | null;
  /** Radar anti-robo: cláusulas abiertas o a punto, cruzadas con la caja rival. */
  radar_anti_robo?: RadarAntiRobo[];
  strategy_baseline_points?: number | null;
  audit?: {
    complete?: boolean;
    played?: boolean | null;
    predicted_points?: number | null;
    actual_points?: number | null;
    error?: number | null;
    written?: boolean;
    missing?: string[];
  };
};

export type DashboardState = {
  optimize: OptimizePayload | null;
  trends: TrendsPayload | null;
  squads: SquadsPayload | null;
  needs: NeedsPayload | null;
  plan: PlanPayload | null;
};

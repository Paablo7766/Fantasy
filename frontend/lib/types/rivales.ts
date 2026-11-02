// Caja y necesidades de los rivales (`/api/needs`, `/api/clause-intel`, `/api/rival-intel`).
import type { ApiError, PhotoMeta } from "./common";
import type { CashReconciliation } from "./liga";
import type { ClauseLock } from "./once";

export type NeedRival = {
  team_id?: string | null;
  direct?: boolean;
  lacks_liquidity?: boolean;
  lacks_replacements?: boolean;
  thin_positions?: string[];
  ledger?: {
    observed_cash_eur?: number | null;
    reconstructed_cash_eur?: number | null;
    balanced?: boolean | null;
    gap_eur?: number | null;
    initial_budget_eur?: number | null;
    cash_is_ceiling?: boolean | null;
    premiums_eur?: number | null;
    purchases_eur?: number | null;
    clauses_eur?: number | null;
    sales_eur?: number | null;
  } | null;
};

export type ClauseAlert = {
  team_id?: string | null;
  manager_name?: string | null;
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  buyout_clause_eur?: number | null;
  alert_local_date?: string | null;
  alert_local_time?: string | null;
  already_open?: boolean | null;
  scheduled?: boolean | null;
  we_can_pay?: boolean | null;
  eligible?: boolean | null;
  lacks_replacements?: boolean | null;
  lacks_liquidity?: boolean | null;
  clause_lock?: ClauseLock | null;
};

export type ClauseIntelOffer = {
  decision?: string | null;
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  club?: string | null;
  image_url?: string | null;
  team_id?: string | null;
  manager_name?: string | null;
  buyout_clause_eur?: number | null;
  cash_after_eur?: number | null;
  objective?: number | null;
  points_delta?: number | null;
  enters_xi?: boolean | null;
  window_open?: boolean | null;
  requires_confirmation?: boolean | null;
  clause_lock?: ClauseLock | null;
};

export type ClauseIntelPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  stale?: boolean;
  dashboard_at?: string | null;
  cash_eur?: number | null;
  baseline_points?: number | null;
  clause_window_open?: boolean | null;
  clause_market_close?: {
    local_date?: string | null;
    local_time?: string | null;
    local_clock?: string | null;
  } | null;
  offers?: ClauseIntelOffer[];
  protect?: Array<{
    player_id?: string | null;
    name?: string | null;
    nickname?: string | null;
    position?: string | null;
    buyout_clause_eur?: number | null;
    threat_count?: number | null;
    top_rival?: { team_id?: string | null; manager_name?: string | null; cash_eur?: number | null } | null;
  }>;
};

export type NeedsPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  alert_count?: number | null;
  clause_alerts?: ClauseAlert[];
  dashboard_at?: string | null;
  stale?: boolean;
  history?: {
    buy_count?: number | null;
    priced_count?: number | null;
    war_count?: number | null;
    bomb_count?: number | null;
    median_premium?: number | null;
    initial_source?: string | null;
    initial_budget_eur?: number | null;
  } | null;
  rivals?: NeedRival[];
  liquidity?: {
    status?: string;
    headline?: string;
    detail?: string;
    cash_eur?: number | null;
    formation?: string | null;
    expected_points?: number | null;
  } | null;
};

export type HiddenExpense = {
  team_id?: string | null;
  player_id?: string | null;
  name?: string | null;
  position?: string | null;
  clause_base_eur?: number | null;
  clause_current_eur?: number | null;
  increase_eur?: number | null;
  cost_eur?: number | null;
  source?: "retroactivo" | "diario" | string | null;
  basis?: "fichado" | "campo_oculto" | "valor_mercado" | "snapshot" | string | null;
  day?: string | null;
  from_day?: string | null;
};

export type RivalFinancialTeam = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  is_self?: boolean | null;
  rank?: number | null;
  calculated_cash?: number | null;
  /** Caja mínima demostrable: sin anuncios, o solo con los que el libro obliga. */
  cash_floor_eur?: number | null;
  /** Caja esperada usando la tasa de vídeo calibrada con la caja propia. */
  cash_expected_eur?: number | null;
  /** Anchura de la banda: todo el dinero que el vídeo diario puede explicar. */
  cash_band_eur?: number | null;
  max_bid_limit?: number | null;
  floor_bid_limit?: number | null;
  expected_bid_limit?: number | null;
  /** Banda del vídeo diario: días, mínimo obligado, esperado y máximo posible. */
  ad_bounds?: {
    days?: number | null;
    max_ad_eur?: number | null;
    min_ad_eur?: number | null;
    expected_ad_eur?: number | null;
    own_rate_pct?: number | null;
    forced_by_balance?: boolean | null;
    lowest_book_balance_eur?: number | null;
    no_score_reasons?: string[] | null;
    team_start_day?: string | null;
  } | null;
  /** Cota calibrada contra el saldo observado (nunca por debajo de él). */
  risk_adjusted_cash?: number | null;
  risk_adjusted_bid_limit?: number | null;
  debt_limit_eur?: number | null;
  cash_is_upper_bound?: boolean | null;
  hidden_expenses_eur?: number | null;
  detected_hidden_expenses?: HiddenExpense[];
  confidence?: "high" | "medium" | "low" | string | null;
  players?: number | null;
  breakdown?: {
    initial_budget_eur?: number | null;
    premiums_eur?: number | null;
    sales_eur?: number | null;
    purchases_eur?: number | null;
    clauses_eur?: number | null;
    ad_revenue_eur?: number | null;
    ad_days?: number | null;
    clause_raises_eur?: number | null;
    period?: string | null;
    anchor_day?: string | null;
    anchor_reason?: string | null;
  } | null;
  reconciliation?: CashReconciliation | null;
};

export type RivalIntelPayload = ApiError &
  PhotoMeta & {
    ok?: boolean;
    league_id?: string | null;
    generated_at?: string | null;
    days_elapsed?: number | null;
    ad_revenue_per_team_eur?: number | null;
    config?: RivalIntelConfig | null;
    activity?: RivalIntelActivity | null;
    teams?: Record<string, RivalFinancialTeam>;
    /** Gasto detectado fuera de los libros, con su bitácora en disco. */
    hidden_log?: { path?: string | null; entries?: number | null; total_eur?: number | null; error?: string | null } | null;
    daily_diff?: {
      day?: string | null;
      from_day?: string | null;
      change_count?: number | null;
      total_cost_eur?: number | null;
      persisted?: boolean | null;
    } | null;
    adjustments?: { path?: string | null; teams_with_anchor?: string[] } | null;
    warnings?: string[];
  };

export type RivalIntelActivity = {
  ok?: boolean;
  event_count?: number | null;
  income_eur?: number | null;
  expense_eur?: number | null;
  ignored_events?: number | null;
  kinds?: Record<string, number> | null;
  source?: string | null;
  from_ledgers?: boolean | null;
};

export type RivalIntelConfig = {
  initial_budget_eur?: number | null;
  initial_budget_source?: string | null;
  starting_clause_multiplier?: number | null;
  clause_increase_multiplier?: number | null;
  daily_ad_revenue_eur?: number | null;
  league_start_date?: string | null;
  /** De dónde sale el arranque: ``alta``, ``actividad`` o ``configuracion``. */
  league_start_source?: string | null;
  /** Inicio real del devengo de anuncios (alta o primer movimiento). */
  season_start_date?: string | null;
  /** Fracción de días en que el mánager propio vio el vídeo, calibrada con su caja. */
  own_ad_rate_pct?: number | null;
  debt_limit_eur?: number | null;
  /** Escala del termómetro de control (hueco relativo = tau · caja). */
  thermometer_tau?: number | null;
  /** Hueco relativo que se considera ruido de medición. */
  arbitrage_band?: number | null;
  /** Suelo de la incertidumbre de caja que alimenta la barrera bayesiana. */
  uncertainty_floor_eur?: number | null;
};

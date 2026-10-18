export type ApiError = {
  ok?: boolean;
  error?: {
    code?: string;
    message?: string;
    status?: number | null;
  };
  message?: string;
};

export type Player = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  club?: string | null;
  expected_points?: number | null;
  p_titular?: number | null;
  p_titular_source?: string | null;
  player_status?: string | null;
  market_value?: number | null;
  buyout_clause?: number | null;
  average_points?: number | null;
  clause_multiple?: number | null;
  is_at_risk?: boolean;
  sell_signal?: boolean;
  price_delta?: number | null;
  excluded_reason?: string | null;
  sale_price?: number | null;
  acceleration?: number | null;
  value_ratio?: number | string | null;
  gap_eur?: number | null;
  fitness?: string | null;
  sanction?: { suspended?: boolean; on_verge?: boolean } | null;
  bid_eur?: number | null;
  snipe?: {
    fire_local_clock?: string | null;
    fire_local_time?: string | null;
  } | null;
};

export type Gap = {
  position?: string;
  missing?: number;
  label?: string;
  options?: Player[];
};

export type ClauseLock = {
  present?: boolean;
  is_locked?: boolean | null;
  local_date?: string | null;
  local_time?: string | null;
  local_clock?: string | null;
  expires_at?: string | null;
  timezone?: string | null;
};

export type OptimizePayload = ApiError & {
  ok?: boolean;
  formation?: string | null;
  manager_name?: string | null;
  expected_points?: number | null;
  xi?: Player[];
  gaps?: Gap[];
  benched?: Player[];
  excluded?: Player[];
  market_fills?: Gap[];
  counts?: Record<string, number>;
  eligible_counts?: Record<string, number>;
  partial?: boolean;
  matchday_void?: boolean;
  void_reasons?: string[];
  calibration_note?: string | null;
  dashboard_at?: string | null;
  saved_lineup?: {
    ok?: boolean;
    formation?: string | null;
    xi?: Player[];
  } | null;
};

export type TrendsPayload = ApiError & {
  ok?: boolean;
  league_name?: string | null;
  dashboard_at?: string | null;
  fetched_at?: string | null;
  partial?: boolean;
  catalog_count?: number | null;
  flip_count?: number | null;
  flips?: Player[];
  rising?: Player[];
  undervalued?: Player[];
  availability?: Player[];
  market?: {
    count?: number | null;
    listings?: Player[];
  } | null;
};

export type RivalSquad = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  rank?: number | null;
  cash_eur?: number | null;
  player_count?: number | null;
  locked_clauses?: number | null;
};

export type ClauseRow = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  buyout_clause_eur?: number | null;
  market_value?: number | null;
  average_points?: number | null;
  clause_multiple?: number | null;
  clause_rule?: "A" | "B" | string | null;
  is_shielded?: boolean;
  is_locked?: boolean;
  at_risk?: boolean;
  clause_lock?: ClauseLock | null;
};

export type SquadsPayload = ApiError & {
  ok?: boolean;
  league_name?: string | null;
  dashboard_at?: string | null;
  rival_count?: number | null;
  rivals?: RivalSquad[];
  clauses?: ClauseRow[];
  shield?: Player[];
  sell?: Player[];
  clause_lock_timezone?: string | null;
  clause_lock_note?: string | null;
};

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
  } | null;
};

export type NeedsPayload = ApiError & {
  ok?: boolean;
  alert_count?: number | null;
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

export type DashboardState = {
  optimize: OptimizePayload | null;
  trends: TrendsPayload | null;
  squads: SquadsPayload | null;
  needs: NeedsPayload | null;
};

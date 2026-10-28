export type ApiError = {
  ok?: boolean;
  error?: {
    code?: string;
    message?: string;
    status?: number | null;
  };
  message?: string;
};

/**
 * Sello de la foto guardada. Lo pone el backend en cada GET: dice de cuándo es
 * el dato y cuánto hace, sin tocar la red. La interfaz decide si avisar.
 */
export type PhotoMeta = {
  last_updated?: string | null;
  photo_age_seconds?: number | null;
  is_stale?: boolean;
  stale?: boolean;
  /**
   * Cuánto hace que se **descargó** el dato (``fetched_at`` de LALIGA). Puede
   * ser bastante mayor que ``photo_age_seconds``, que mide cuándo se guardó la
   * foto: un refresco rápido sella la foto al escribir aunque el mercado se
   * leyera minutos antes.
   */
  data_age_seconds?: number | null;
};

/**
 * ``GET /api/refresh-status``: el latido de la descarga en curso.
 *
 * Una pasada completa dura media hora con la cadencia humana. Este documento
 * es RAM pura (no gasta una sola petición a las fuentes) y dice en qué fase
 * va, cuánto lleva y cuántas llamadas ha hecho: es lo que distingue «avanza»
 * de «colgado».
 */
export type RefreshStatusPayload = ApiError & {
  ok?: boolean;
  command?: string;
  running?: boolean;
  tier?: "core" | "full" | string | null;
  league?: string | null;
  phase?: string | null;
  phase_label?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  elapsed_seconds?: number | null;
  calls?: number;
  /** Documentos resueltos desde caché: el trabajo que no gasta petición. */
  cache_hits?: number;
  /** ``false`` en air-gap: la pasada avanza leyendo disco, sin abrir sockets. */
  network?: boolean;
  by_source?: Array<{ id: string; label: string; calls: number; cache_hits?: number }>;
  current_source?: string | null;
  current_label?: string | null;
  in_flight?: number;
  /** Segundos desde el último documento resuelto: distingue pausa de cuelgue. */
  last_activity_seconds?: number | null;
  /** Resultado de la pasada. ``null`` mientras corre o si nunca corrió. */
  result_ok?: boolean | null;
  error?: ApiError["error"];
};

export type Player = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  club?: string | null;
  image_url?: string | null;
  expected_points?: number | null;
  jornada_ev?: number | null;
  points_if_starts?: number | null;
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
  /** ``diferencia1`` de FútbolFantasy (prioridad en UI frente a marketValueChange). */
  ff_price_delta?: number | null;
  /**
   * Δ medido entre dos capturas propias consecutivas. Es el único delta que
   * este proyecto calcula con datos de LaLiga; si falta, no hay dos capturas
   * que restar y la UI no debe inventarlo.
   */
  measured_price_delta?: number | null;
  measured_price_delta_source?: string | null;
  /** El mismo número que ``price_delta``, declarado como estimación de terceros. */
  price_delta_estimated?: number | null;
  price_delta_is_estimate?: boolean;
  /** ``diferencia2``: acumulado de 2 días de la misma fuente. */
  ff_price_delta_2?: number | null;
  /** ``diferencia3``: acumulado de 3 días de la misma fuente. */
  ff_price_delta_3?: number | null;
  excluded_reason?: string | null;
  sale_price?: number | null;
  acceleration?: number | null;
  value_ratio?: number | string | null;
  gap_eur?: number | null;
  fitness?: string | null;
  fitness_detail?: string | null;
  sanction?: { suspended?: boolean; on_verge?: boolean } | null;
  bid_eur?: number | null;
  af_ideal_bid?: number | null;
  af_max_bid?: number | null;
  af_price_delta?: number | null;
  af_market_value?: number | null;
  af_market_signal?: "up" | "down" | string | null;
  af_signal_strength?: number | null;
  af_predicted_delta?: number | null;
  af_expected_points?: number | null;
  af_ceiling_points?: number | null;
  af_goal_probability?: number | null;
  af_assist_probability?: number | null;
  af_points_per_million?: number | null;
  af_recommendation_pct?: number | null;
  af_titular_delta?: number | null;
  own_ideal_bid?: number | null;
  own_max_bid?: number | null;
  own_market_signal?: "up" | "down" | string | null;
  own_signal_strength?: number | null;
  own_predicted_delta?: number | null;
  own_expected_points?: number | null;
  own_ceiling_points?: number | null;
  own_goal_probability?: number | null;
  own_assist_probability?: number | null;
  own_points_per_million?: number | null;
  own_recommendation_pct?: number | null;
  ideal_bid?: number | null;
  max_bid?: number | null;
  own_calendar?: Array<{
    matchday?: number;
    opponent?: string;
    is_home?: boolean;
    predicted_score?: string;
    recommendation_pct?: number;
    difficulty?: string;
  }> | null;
  af_form?: {
    recent_average?: number | null;
    signal_count?: number | null;
    signals?: string[];
  } | null;
  af_injury?: {
    status?: string | null;
    info?: string | null;
    report?: string | null;
    start?: string | null;
    expected_return?: string | null;
  } | null;
  af_suspension?: {
    status?: string | null;
    info?: string | null;
    report?: string | null;
  } | null;
  af_set_pieces?: Array<{ role?: string | null; shirt?: number | null }> | null;
  af_calendar?: Array<{
    matchday?: number;
    opponent?: string;
    is_home?: boolean;
    predicted_score?: string;
    recommendation_pct?: number;
    difficulty?: string;
  }> | null;
  snipe?: {
    fire_local_clock?: string | null;
    fire_local_time?: string | null;
    fire_at?: string | null;
    status?: string | null;
    eligible?: boolean | null;
    expires_local_clock?: string | null;
  } | null;
  bid_plan?: {
    how?: string | null;
    recommended_bid_eur?: number | null;
    floor_eur?: number | null;
    reason?: string | null;
    overbid?: {
      status?: string | null;
      count?: number | null;
      reason?: string | null;
    } | null;
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

export type OptimizePayload = ApiError & PhotoMeta & {
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
  stale?: boolean;
  saved_lineup?: {
    ok?: boolean;
    formation?: string | null;
    xi?: Player[];
  } | null;
};

export type RivalBid = {
  amount?: number | null;
  manager_name?: string | null;
  team_id?: string | null;
  own?: boolean;
};

export type FixtureView = {
  opponent?: string | null;
  is_home?: boolean | null;
  predicted_score?: string | null;
  recommendation_pct?: number | null;
  difficulty?: string | null;
  source?: string | null;
  af_recommendation_pct?: number | null;
  af_difficulty?: string | null;
  af_opponent?: string | null;
  af_predicted_score?: string | null;
};

export type XiReplace = {
  player_id?: string | null;
  name?: string | null;
  position?: string | null;
  club?: string | null;
  points?: number | null;
  points_source?: string | null;
};

export type JornadaClub = {
  club?: string | null;
  opponent?: string | null;
  is_home?: boolean | null;
  predicted_score?: string | null;
  recommendation_pct?: number | null;
  difficulty?: string | null;
  source?: string | null;
  market_count?: number | null;
  af_recommendation_pct?: number | null;
  af_difficulty?: string | null;
  af_opponent?: string | null;
  af_predicted_score?: string | null;
};

export type MarketDecision = Player & {
  decision?: "PUJAR" | "ESPERAR" | "NO" | string | null;
  primary_motive?: string | null;
  motives?: string[];
  /** Comando de una palabra del motor; es lo que ve la interfaz. */
  action?: "PUJAR" | "ESPERAR" | "NO" | string | null;
  is_vetoed?: boolean | null;
  /** Frase corta que explica el veredicto. */
  action_reason?: string | null;
  price_band?: "bargain" | "fair" | "overpay" | "unknown" | string | null;
  jornada_ev?: number | null;
  expected_points_source?: "own" | "af" | "opta" | string | null;
  points_roi?: number | null;
  score?: number | null;
  reasons?: string[];
  missing_inputs?: string[];
  cash_after_eur?: number | null;
  calendar_recommendation_pct?: number | null;
  calendar_difficulty?: string | null;
  suggested_bid?: number | null;
  raise_to?: number | null;
  bid_limit?: string | null;
  league_bid?: number | null;
  stretch_bid?: number | null;
  league_bid_blocked?: boolean | null;
  league_war_count?: number | null;
  league_priced_count?: number | null;
  league_buy_count?: number | null;
  league_median_premium?: number | null;
  value_ceiling?: number | null;
  value_ceiling_source?: string | null;
  aggressive_ceiling?: number | null;
  aggressive_ceiling_source?: string | null;
  leading_bid?: number | null;
  rival_bids?: RivalBid[];
  replaces?: XiReplace | null;
  points_delta?: number | null;
  points_delta_source?: string | null;
  fixture?: FixtureView | null;
  offer_source?: "liga" | "rival" | "propio" | string | null;
  seller_team_id?: string | null;
  seller_manager?: string | null;
  optimal_bid_eur?: number | null;
  win_probability?: number | null;
  intrinsic_valuation_eur?: number | null;
  expected_surplus_eur?: number | null;
  rival_knockout_targets?: string[];
  bid_intent?: "FLIP" | "STRUCTURAL" | "NONE" | string | null;
  auction_decision?: "PUJAR" | "ESPERAR" | "NO" | string | null;
};

export type MarketDecisionSummary = {
  pujar?: number | null;
  esperar?: number | null;
  no?: number | null;
  cash_eur?: number | null;
  count?: number | null;
  liga?: number | null;
  rival?: number | null;
  propio?: number | null;
  league_war_count?: number | null;
  league_priced_count?: number | null;
  league_buy_count?: number | null;
  league_median_premium?: number | null;
  league_bomb_count?: number | null;
  markets_left?: number | null;
  day_budget_eur?: number | null;
  plan_spend_eur?: number | null;
  plan_cash_after_eur?: number | null;
};

export type SourceStatus = {
  ok?: boolean;
  count?: number | null;
  error?: string | null;
  from_cache?: boolean;
};

export type TrendsPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  league_id?: string | null;
  league_name?: string | null;
  dashboard_at?: string | null;
  fetched_at?: string | null;
  stale?: boolean;
  partial?: boolean;
  optional_sources_degraded?: boolean;
  form_note?: string | null;
  sources?: Record<string, SourceStatus>;
  catalog_count?: number | null;
  flip_count?: number | null;
  cash_eur?: number | null;
  flips?: Player[];
  rising?: Player[];
  falling?: Player[];
  undervalued?: Player[];
  availability?: Player[];
  af_prediction_rising?: Player[];
  af_prediction_falling?: Player[];
  af_oracle_points?: Player[];
  af_oracle_chollos?: Player[];
  af_in_form?: Player[];
  own_prediction_rising?: Player[];
  own_prediction_falling?: Player[];
  market_decisions?: MarketDecision[];
  jornada_board?: JornadaClub[];
  market_decision_summary?: MarketDecisionSummary | null;
  engine_confidence?: EngineConfidence | null;
  calibration?: CalibrationPayload | null;
  market?: {
    count?: number | null;
    fetched_at?: string | null;
    listings?: Player[];
  } | null;
  catalog?: CatalogPlayer[];
};

export type CatalogPlayer = Player & {
  owner?: "libre" | "rival" | "propio" | string | null;
  price_points?: Array<{ day?: string; market_value?: number | null }>;
};

export type ActivityEvent = {
  kind?: string | null;
  label?: string | null;
  amount_eur?: number | null;
  signed_eur?: number | null;
  player_id?: string | null;
  player_name?: string | null;
  at?: string | null;
  team_id?: string | null;
  manager_name?: string | null;
};

export type ActivityProfile = {
  initial_budget_eur?: number | null;
  premiums_eur?: number | null;
  purchases_eur?: number | null;
  clauses_eur?: number | null;
  sales_eur?: number | null;
  net_outflow_eur?: number | null;
  realized_gain_eur?: number | null;
  priced_sales?: number | null;
  sale_count?: number | null;
  event_count?: number | null;
  recent_events?: ActivityEvent[];
};

export type PortfolioSummary = {
  player_count?: number | null;
  priced_count?: number | null;
  cost_eur?: number | null;
  market_value_eur?: number | null;
  gain_eur?: number | null;
  roi?: number | null;
};

export type RivalPlayer = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  club?: string | null;
  image_url?: string | null;
  market_value?: number | null;
  average_points?: number | null;
  buyout_clause?: number | null;
  clause_multiple?: number | null;
  price_delta?: number | null;
  own_predicted_delta?: number | null;
  own_expected_points?: number | null;
  af_price_delta?: number | null;
  p_titular?: number | null;
  clause_lock?: ClauseLock | null;
  is_shielded?: boolean | null;
  cost_eur?: number | null;
  gain_eur?: number | null;
  roi?: number | null;
  acquired_at?: string | null;
  acquisition_kind?: "mercado" | "clausula" | string | null;
};

/**
 * Conciliación entre la cota reconstruida y el saldo que publica la API.
 *
 * ``temperature`` mide cuánto cuadra la cota con la caja observada (1 = cuadra
 * del todo) y ``arbitrage_eur`` es el dinero observado que los libros no
 * explican y que no cabe en la banda de ruido. La cota calibrada
 * (``risk_adjusted_cash``) sale de aquí: si sobra caja se aprieta; si falta, no
 * se inventa y el hueco se publica como arbitraje.
 */
export type CashReconciliation = {
  observed_cash_eur?: number | null;
  gap_eur?: number | null;
  relative_gap?: number | null;
  /** 0–1: cuánto explica la cota la caja publicada por la API. */
  temperature?: number | null;
  /** Φ(hueco/σ): probabilidad de que la cota siga cubriendo la caja real. */
  cover_probability?: number | null;
  noise_band_eur?: number | null;
  /** Caja observada que los libros no explican, fuera de la banda de ruido. */
  arbitrage_eur?: number | null;
  posterior_sigma_eur?: number | null;
  status?: "exact" | "within_band" | "underestimated" | "overestimated" | string | null;
  underestimated?: boolean | null;
  covers_observed?: boolean | null;
};

export type RivalSquad = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  rank?: number | null;
  cash_eur?: number | null;
  cash_is_ceiling?: boolean | null;
  player_count?: number | null;
  locked_clauses?: number | null;
  market_value_total?: number | null;
  price_delta_day?: number | null;
  price_delta_players?: number | null;
  players?: RivalPlayer[];
  activity_profile?: ActivityProfile | null;
  portfolio?: PortfolioSummary | null;
  /** Cota calibrada contra el saldo observado. Nunca por debajo de él. */
  risk_adjusted_cash?: number | null;
  /**
   * Cota reconstruida desde los libros, antes de calibrar. Es la referencia que
   * se tacha cuando el grupo de control aprieta el techo.
   */
  calculated_cash?: number | null;
  max_bid_limit?: number | null;
  risk_adjusted_bid_limit?: number | null;
  debt_limit_eur?: number | null;
  cash_is_upper_bound?: boolean | null;
  /** Atajo plano de ``reconciliation.arbitrage_eur`` para consumidores simples. */
  arbitrage_eur?: number | null;
  /** Atajo plano de ``reconciliation.temperature``. */
  temperature?: number | null;
  reconciliation?: CashReconciliation | null;
};

export type ClauseRow = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  club?: string | null;
  image_url?: string | null;
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

/** Subida de cláusula fechada: qué día, de cuánto a cuánto y qué costó subirla. */
export type ClauseRaise = {
  day: string;
  before_eur: number;
  after_eur: number;
  increase_eur: number;
  cost_eur?: number | null;
};

/** Fila del tablero completo: cualquier jugador con cláusula, no solo los de la regla A/B. */
export type ClauseBoardRow = ClauseRow & {
  prev_clause_eur?: number | null;
  clause_delta_eur?: number | null;
  clause_delta_pct?: number | null;
  /** Subió respecto a la foto de referencia (puede no ser de hoy). */
  raised_since_photo?: boolean;
  /** Subió en la última lectura: solo si la referencia es de ayer o de hoy. */
  raised_today?: boolean;
  raise_latest_day?: string | null;
  raise_latest_eur?: number | null;
  raise_count?: number | null;
  raises?: ClauseRaise[];
  /** Precio pagado por el rival, si el jugador se fichó o se clausuló. */
  clause_paid_eur?: number | null;
  /** Suelo de la cláusula: 1 M€ o el precio pagado, el mayor. */
  clause_floor_eur?: number | null;
  /** Tramo que subió gratis porque subió el valor de mercado (solo fichajes). */
  clause_auto_raise_eur?: number | null;
  /** Tramo que el rival pagó de su caja para engordar la cláusula. */
  clause_paid_raise_eur?: number | null;
  clause_paid_by_rival?: boolean;
};

export type ClauseBoardPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  league_id?: string | null;
  league_name?: string | null;
  photo_day?: string | null;
  /** Último día con cláusulas guardadas contra el que se hizo el diff. */
  from_day?: string | null;
  /** Días entre ``from_day`` y la foto: si es > 1, el salto no es de hoy. */
  diff_gap_days?: number | null;
  counts?: {
    total: number;
    golden: number;
    raised_today: number;
    raised_since_photo?: number;
    raised_ever: number;
    locked: number;
    open: number;
    /** Jugadores cuya cláusula el rival empujó pagando, no por el mercado. */
    paid_raise?: number;
    /** Fichajes cuya cláusula subió gratis al subir su valor de mercado. */
    auto_raise?: number;
  } | null;
  rows?: ClauseBoardRow[];
};

export type SquadsPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  league_id?: string | null;
  league_name?: string | null;
  dashboard_at?: string | null;
  stale?: boolean;
  partial?: boolean;
  rival_count?: number | null;
  self?: RivalSquad | null;
  rivals?: RivalSquad[];
  clauses?: ClauseRow[];
  shield?: Player[];
  sell?: Player[];
  portfolio?: {
    summary?: PortfolioSummary | null;
    recent_events?: ActivityEvent[];
  } | null;
  portfolio_meta?: {
    activity_ok?: boolean;
    activity_event_count?: number | null;
    ledger_event_count?: number | null;
    history_ready?: boolean;
  } | null;
  activity_feed?: ActivityEvent[];
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

export type EngineConfidence = {
  score?: number | null;
  band?: "alta" | "media" | "baja" | "unknown" | string | null;
  label?: string | null;
  notes?: string[];
};

export type CalibrationJornadaRow = {
  jornada_id?: string;
  mae?: number | null;
  scored?: number | null;
  ceiling_break_rate?: number | null;
};

export type CalibrationPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  engine_confidence?: EngineConfidence | null;
  points?: {
    jornadas?: CalibrationJornadaRow[];
    overall_mae?: number | null;
    trend?: string | null;
    delta_mae_recent?: number | null;
    sample_jornadas?: number | null;
  } | null;
  sell_at_crest?: {
    signals?: number;
    accuracy_pct?: number | null;
    hit_48h_rate?: number | null;
  } | null;
  pujar?: {
    resolved?: number;
    hits?: number;
    lost?: number;
    overbid?: number;
    hit_rate?: number | null;
    hit_rate_pct?: number | null;
    pending?: number;
  } | null;
  win_probability?: {
    samples?: number;
    brier?: number | null;
    bins?: Array<{
      lo?: number;
      hi?: number;
      count?: number;
      mean_predicted?: number | null;
      observed_rate?: number | null;
    }>;
  } | null;
  coverage?: {
    price_snapshots?: number;
    activity_buys?: number;
    matchday_jornadas?: number;
    cache_root?: string;
    hydrated_from_store?: { snapshots_imported?: number; buys_imported?: number };
  } | null;
  database?: string | null;
};

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

export type LeagueEdge = {
  team_id?: string | null;
  manager_name?: string | null;
  rank?: number | null;
  points?: number | null;
  /** Positivo = colchón; negativo = déficit. */
  edge_points?: number | null;
  ahead?: boolean | null;
};

export type LeagueProjection = {
  expected_points?: number | null;
  ceiling_points?: number | null;
  formation?: string | null;
  players_available?: number | null;
  gaps?: string[];
  source?: string | null;
};

export type LeagueRaceRow = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  is_self?: boolean;
  rank?: number | null;
  points?: number | null;
  cash_eur?: number | null;
  player_count?: number | null;
  thin_positions?: string[];
  projection?: LeagueProjection | null;
};

export type LeagueDenialRow = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  sale_price?: number | null;
  managers?: string[];
  count?: number | null;
  label?: string | null;
};

export type LeagueRacePayload = ApiError & PhotoMeta & {
  ok?: boolean;
  command?: string;
  league_id?: string | null;
  team_id?: string | null;
  fetched_at?: string | null;
  stale?: boolean;
  mode?: LeagueMode | null;
  headline?: string | null;
  my_projection?: LeagueProjection | null;
  league_projection?: number | null;
  table?: LeagueRaceRow[];
  rivals?: LeagueRaceRow[];
  denial?: LeagueDenialRow[];
  sends?: boolean;
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

export type DataHealthStatus = "ok" | "caducada" | "error" | "no_leida";

export type DataHealthField = {
  id: string;
  label: string;
  field: string;
  impact: string;
  critical: boolean;
  status: DataHealthStatus | string;
  ok?: boolean | null;
  count?: number | null;
  error?: string | null;
  from_cache?: boolean | null;
  ttl_seconds?: number | null;
  ttl_label?: string | null;
  expires_in_seconds?: number | null;
  expires_label?: string | null;
};

export type DataHealthPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  command?: string;
  generated_at?: string | null;
  fetched_at?: string | null;
  stale?: boolean;
  partial?: boolean;
  status?: "ok" | "warn" | "fail" | string;
  headline?: string | null;
  fields?: DataHealthField[];
  broken?: string[];
  missing?: string[];
  critical_broken?: string[];
  stale_critical?: string[];
  notes?: string[];
};

export type ApiRateWindow = {
  seconds: number;
  label: string;
  calls: number;
  ok?: number;
  errors: number;
  not_found: number;
  auth: number;
  rate_limited: number;
  retries: number;
  cache_hits: number;
  rate_per_minute: number;
};

export type ApiSourceUsage = {
  id: string;
  label: string;
  host?: string | null;
  calls: number;
  calls_1m: number;
  calls_10m: number;
  cache_hits: number;
  errors: number;
  errors_pending?: number;
  recovered?: number;
  not_found: number;
  auth: number;
  rate_limited: number;
  retries: number;
  avg_ms?: number | null;
  last_at?: string | null;
  rate_per_minute?: number | null;
  share_pct?: number | null;
  budget_per_minute?: number | null;
  utilization_pct?: number | null;
};

export type ApiTimelinePoint = {
  minutes_ago: number;
  label: string;
  calls: number;
};

export type ApiRisk = {
  level: "bajo" | "medio" | "alto" | string;
  score: number;
  headline: string;
  advice: string;
  reasons: string[];
  rules: string[];
};

export type ApiStability = {
  level: "ok" | "warn" | string;
  headline: string;
  errors_10m: number;
  recovered_10m?: number;
  not_found_10m: number;
  status_mix: Record<string, number>;
  note: string;
};

export type ApiUsagePayload = ApiError & {
  ok?: boolean;
  command?: string;
  generated_at?: string | null;
  process_started_at?: string | null;
  uptime_seconds?: number | null;
  scope?: string;
  rate?: {
    calls_1m: number;
    per_minute: number;
    band: string;
    calls_10m: number;
    per_minute_10m: number;
  };
  windows?: ApiRateWindow[];
  sources?: ApiSourceUsage[];
  status_mix?: Record<string, number>;
  timeline?: ApiTimelinePoint[];
  in_flight?: { now: number; by_source: Record<string, number>; peak_1m: number };
  totals?: {
    calls: number;
    cache_hits: number;
    errors: number;
    not_found: number;
    rate_limited: number;
    retries: number;
    seconds: number;
  };
  risk?: ApiRisk;
  stability?: ApiStability;
  notes?: string[];
};

/** Una línea de `.cache/network_logs.jsonl`: una llamada HTTP que salió a la red. */
export type NetworkLogEntry = {
  timestamp?: string | null;
  fuente?: string;
  metodo?: string;
  status?: number | null;
  duracion_ms?: number | null;
  resultado?: "ok" | "error" | "red" | string;
  url?: string | null;
};

export type NetworkErrorBucket = {
  fuente: string;
  total: number;
  por_status: Record<string, number>;
  ultimo?: string | null;
};

export type NetworkDiagnosticsPayload = ApiError & {
  ok?: boolean;
  command?: string;
  file?: string;
  file_exists?: boolean;
  limit?: number;
  scanned?: number;
  total_count?: number;
  count?: number;
  calls?: NetworkLogEntry[];
  errors?: NetworkErrorBucket[];
  notes?: string[];
};

/**
 * Value Investing puro: ``/api/market/quant-radar``. Todo sale de la foto
 * cacheada; ``sources.network`` siempre dice ``none``.
 */
export type QuantPlayer = Player & {
  player_id: string;
  effective_price?: number | null;
  affordable?: boolean | null;
  owner?: "libre" | "rival" | "propio" | "mercado" | string | null;
  manager_name?: string | null;
  on_market?: boolean;
  games?: number | null;
  median_points?: number | null;
  mean_points?: number | null;
  stdev_points?: number | null;
  blank_rate?: number | null;
  floor_rate?: number | null;
  boom_rate?: number | null;
  points_source?: "weekPoints" | "averagePoints" | string | null;
  cost_per_point_eur?: number | null;
  points_per_million?: number | null;
  risk_adjusted_points_per_million?: number | null;
  position_baseline_cost_per_point_eur?: number | null;
  discount_vs_position?: number | null;
  undervalued?: boolean;
  relative_acceleration?: number | null;
  smart_money?: boolean | null;
  momentum_signal?: string | null;
  in_catalog?: boolean;
  score?: number | null;
  verdict?: "COMPRAR" | "VIGILAR" | "TOXICO" | "MERCADO" | "NO_FICHABLE" | "SIN_MUESTRA" | string;
  reasons?: string[];
};

export type QuantBaseline = {
  count?: number;
  median_cost_per_point_eur?: number | null;
  p25_cost_per_point_eur?: number | null;
  median_points?: number | null;
  median_points_per_million?: number | null;
};

export type QuantRadarPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  command?: string;
  generated_at?: string;
  league_id?: string | null;
  league_name?: string | null;
  photo_saved_at?: string | null;
  cash_eur?: number | null;
  sources?: {
    catalog_origin?: string;
    catalog_rows?: number;
    players_scored?: number;
    real_series?: number;
    market_listings?: number;
    trend_players?: number;
    momentum_source?: string | null;
    network?: string;
  };
  assumptions?: {
    blank_threshold_points?: number;
    min_games?: number;
    undervalued_discount?: number;
    max_blank_rate?: number;
    weights?: { value?: number; discount?: number; momentum?: number };
    notes?: string[];
  };
  baselines?: Record<string, QuantBaseline>;
  summary?: {
    buys?: number;
    watchlist?: number;
    toxic?: number;
    undervalued?: number;
    signable?: number;
    smart_money?: number;
    scanned?: number;
    momentum_up?: number;
    momentum_down?: number;
  };
  buys?: QuantPlayer[];
  watchlist?: QuantPlayer[];
  toxic?: QuantPlayer[];
  candidates?: QuantPlayer[];
  momentum?: {
    counts?: Record<string, number>;
    source?: string | null;
    smart_money?: QuantPlayer[];
    top?: QuantPlayer[];
  };
};

/**
 * Perfil de un jugador del catálogo con serie de jornadas. Lo comparten
 * ``/api/catalog/free-agents`` y ``/api/catalog/arbitrage``: es el mismo
 * ``_row`` de ``catalog_intel`` con distinto filtro.
 */
export type CatalogProfilePlayer = Player & {
  player_id: string;
  club_short?: string | null;
  is_free_agent?: boolean | null;
  owner_team_id?: string | null;
  sample?: number | null;
  median?: number | null;
  mean?: number | null;
  stdev?: number | null;
  ceiling?: number | null;
  floor?: number | null;
  blank_rate?: number | null;
  consistency?: number | null;
  asset_class?: "refugio" | "riesgo" | "equilibrado" | string | null;
  /** ``null`` sin histórico de precios: no se presume tendencia. */
  price_trend?: {
    falling?: boolean;
    decelerating?: boolean;
    recovery?: boolean;
    first_delta?: number | null;
    last_delta?: number | null;
    days?: string[];
  } | null;
  distress_kind?: string | null;
  floor_signal?: string | null;
};

export type CatalogCounts = {
  catalog?: number | null;
  profiled?: number | null;
  refuge?: number | null;
  risk?: number | null;
  distressed?: number | null;
  free_agents?: number | null;
  owned?: number | null;
};

/** Escasez e inflación esperada del talento libre (``inflation_radar``). */
export type CatalogInflation = {
  top_free_count?: number | null;
  top_free_liquidity_eur?: number | null;
  thresholds?: {
    max_top_free?: number | null;
    max_liquidity_eur?: number | null;
    min_median?: number | null;
  } | null;
  scarce?: boolean | null;
  level?: "normal" | "alta" | "extrema" | "desconocida" | string | null;
  known?: boolean | null;
  flag?: string | null;
  recommendation?: string | null;
};

export type FreeAgentsPayload = ApiError &
  PhotoMeta & {
    ok?: boolean;
    count?: number | null;
    league_name?: string | null;
    counts?: CatalogCounts | null;
    inflation?: CatalogInflation | null;
    free_agents?: CatalogProfilePlayer[];
    top_free?: CatalogProfilePlayer[];
  };

export type ArbitragePayload = ApiError &
  PhotoMeta & {
    ok?: boolean;
    count?: number | null;
    league_name?: string | null;
    counts?: CatalogCounts | null;
    /** Suelo de precio tras una caída ya desacelerada (lesión o sanción). */
    distressed?: CatalogProfilePlayer[];
    /** Suelo alto y varianza baja: el que no se cae del once. */
    refuge?: CatalogProfilePlayer[];
    /** Techo alto con muchos ceros: lotería, no inversión. */
    risk?: CatalogProfilePlayer[];
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

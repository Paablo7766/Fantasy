// Mercado de la liga (`/api/trends`): decisiones, pujas y catálogo.
import type { ApiError, PhotoMeta } from "./common";
import type { PlanFichajes, VentaForzada } from "./fichajes";
import type { CalibrationPayload, EngineConfidence } from "./laboratorio";
import type { CapitanPick, Player } from "./once";

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
  /** Formación del mejor once con el fichaje; solo si el motor la recalcula. */
  formation?: string | null;
  formation_from?: string | null;
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
  /** Recuento de pujas de la liga. LaLiga no manda el importe. */
  bid_count?: number | null;
  /** Recuento de ofertas en una venta de rival. El importe no es público. */
  offer_count?: number | null;
  rival_bids?: RivalBid[];
  replaces?: XiReplace | null;
  points_delta?: number | null;
  points_delta_source?: string | null;
  fixture?: FixtureView | null;
  offer_source?: "liga" | "rival" | "propio" | string | null;
  seller_team_id?: string | null;
  seller_manager?: string | null;
  optimal_bid_eur?: number | null;
  /** Puja genérica al estilo de La Pizarra: valor × 1,047. */
  app_bid_eur?: number | null;
  /** Nota de fichaje 0-10 y veredicto del evaluador de mercado. */
  nota_mercado?: number | null;
  veredicto_mercado?: string | null;
  etiqueta_mercado?: string | null;
  frase_mercado?: string | null;
  /** Techo dinámico: +15 % más previsión a 7 días y dificultad, cap +30 %. */
  financial_max_bid_eur?: number | null;
  /** Puja que supera la caja del rival interesado sin pasar el tope. */
  smart_bid_eur?: number | null;
  smart_bid_success_pct?: number | null;
  smart_bid_analysis?: string | null;
  smart_bid_rivals?: string[];
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
  ratio_mercado?: number | null;
  capitan_seguro?: CapitanPick | null;
  capitan_remontada?: CapitanPick | null;
  plan_fichajes?: PlanFichajes | null;
  ventas_forzadas?: VentaForzada[];
};

export type CatalogPlayer = Player & {
  owner?: "libre" | "rival" | "propio" | string | null;
  price_points?: Array<{ day?: string; market_value?: number | null }>;
};

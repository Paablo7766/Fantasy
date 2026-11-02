// Radar cuantitativo y catálogo fuera del mercado.
import type { ApiError, PhotoMeta } from "./common";
import type { Player } from "./once";

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

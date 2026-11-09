// Once, capitanía y jugador base (`/api/optimize`).
import type { ApiError, PhotoMeta } from "./common";
import type { PlanFichajes, VentaForzada } from "./fichajes";

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
  /** Puntos en un buen día (techo del modelo). */
  ceiling_points?: number | null;
  p_titular?: number | null;
  p_titular_source?: string | null;
  player_status?: string | null;
  /** Estado de la foto más nueva entre mercado, plantilla y catálogo. */
  official_status?: string | null;
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
  /** (valoración + acciones) por 90 minutos, de sus actas. */
  own_produccion_pura_90?: number | null;
  /** Mínimo de puntos en partidos de más de 70'. `activo` = muro (mínimo >= 6). */
  own_suelo_muro?: { activo: boolean; minimo: number; n_partidos: number } | null;
  /** Titular al que cambian entre el 45' y el 59' de forma repetida. */
  own_cambio_cronico?: {
    activo: boolean;
    n_titularidades: number;
    n_cambios_antes_60: number;
    minutos_techo: number;
    llega_60: number;
    factor_minutos: number;
  } | null;
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
  /** Variación de valor a 7 días, con signo: ``+10.9%`` o ``-2.1%``. */
  prevision_7d_pct?: string | null;
  valor_en_7d?: number | null;
  valor_justo?: number | null;
  xp_4_jornadas?: number | null;
  /** Puntos oficiales de las últimas jornadas, de la más antigua a la última. */
  week_points?: number[] | null;
  /** Valor diario guardado en local, del día más antiguo al más reciente. */
  value_history?: Array<{ day: string; value: number }> | null;
  lineup_status?: string | null;
  listing_expires_at?: string | null;
  /** Puntos que pierde el once óptimo si este titular sale hoy. */
  tu_once_pierde_sin_el?: number | null;
  consejo_oferta?: {
    acepta?: boolean;
    explicacion?: string | null;
  } | null;
  puja_recomendada?: number | null;
  puja_maxima?: number | null;
  puja_smart?: number | null;
  venta_forzada_rival?: boolean | null;
  venta_forzada_detalle?: string | null;
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
      status?: "guerra" | "high" | "low" | "unknown" | string | null;
      count?: number | null;
      reason?: string | null;
      etiqueta?: string | null;
      rivales_hueco?: string[];
      rivales_justo?: string[];
      rivales_sin_caja?: string[];
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
  ratio_mercado?: number | null;
  capitan_seguro?: CapitanPick | null;
  capitan_remontada?: CapitanPick | null;
  plan_fichajes?: PlanFichajes | null;
  ventas_forzadas?: VentaForzada[];
};

export type CapitanPick = {
  player_id?: string | null;
  nombre?: string | null;
  posicion?: string | null;
  jornada?: number | null;
  si_titular?: number | null;
  techo?: number | null;
  p_titular?: number | null;
  criterio?: "jornada" | "techo" | string | null;
};

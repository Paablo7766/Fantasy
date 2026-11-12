// Liga: plantillas, rivales, cláusulas ajenas y carrera de liga.
import type { ApiError, DineroCaliente, PhotoMeta } from "./common";
import type { PlanFichajes, VentaForzada } from "./fichajes";
import type { CapitanPick, ClauseLock, Player } from "./once";
import type { LeagueMode } from "./plan";

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
  prevision_7d_pct?: string | null;
  valor_en_7d?: number | null;
  tu_once_pierde_sin_el?: number | null;
  venta_forzada_rival?: boolean | null;
  venta_forzada_detalle?: string | null;
  clause_lock?: ClauseLock | null;
  player_status?: string | null;
  official_status?: string | null;
  is_shielded?: boolean | null;
  cost_eur?: number | null;
  gain_eur?: number | null;
  roi?: number | null;
  acquired_at?: string | null;
  acquisition_kind?: "mercado" | "clausula" | string | null;
  /** Puntos de la temporada (todas las jornadas conocidas). */
  points_total?: number | null;
  /** Puntos desde que es tuyo; con compra conocida se estima por fecha de jornada. */
  points_owned?: number | null;
  rounds_owned?: number | null;
  points_owned_estimated?: boolean | null;
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

/** Cómo puja de verdad un rival, ajustado con sus compras pasadas. */
export type BidProfile = {
  style: "conservador" | "moderado" | "agresivo" | "sin_datos";
  n_buys: number;
  /** Probabilidad de que puje a valor de mercado (prima <= 1 %). */
  p_exact: number;
  /** Mediana de la sobrepuja cuando sobrepuja. */
  median_overbid_pct?: number | null;
  /** Prima típica de sus compras, en %. */
  typical_premium_pct?: number | null;
};

/** Huella de puja: cómo termina su importe, a qué hora clausula y qué anuncios suyos ya tienen a una persona pujando. */
export type RivalHuella = {
  cola?: {
    estilo: "pica" | "redondea_100k" | "redondea_10k" | "mixto";
    etiqueta: string;
    n_compras: number;
  } | null;
  ventanas_clausulazo?: string[];
  ofertas_humanas?: Array<{
    market_id?: string | null;
    player_id?: string | null;
    nombre?: string | null;
    offer_count: number;
    sale_price?: number | null;
    etiqueta: string;
  }>;
};

export type RivalSquad = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  rank?: number | null;
  cash_eur?: number | null;
  /** Puntos acumulados en la liga. */
  points?: number | null;
  cash_is_ceiling?: boolean | null;
  player_count?: number | null;
  locked_clauses?: number | null;
  market_value_total?: number | null;
  price_delta_day?: number | null;
  price_delta_players?: number | null;
  players?: RivalPlayer[];
  activity_profile?: ActivityProfile | null;
  bid_profile?: BidProfile | null;
  huella?: RivalHuella | null;
  dinero_caliente?: DineroCaliente | null;
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
  dinero_caliente?: DineroCaliente | null;
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
  /** La actividad oficial dice que otro equipo lo fichó después: no se puede pagar. */
  taken_by_other?: boolean;
  taken_by_manager?: string | null;
  taken_at?: string | null;
  taken_kind?: string | null;
  taken_eur?: number | null;
  /** Está anunciado en el mercado: se compra por oferta o puja, sin esperar al candado. */
  on_market?: boolean;
  market_listing_expires_local_time?: string | null;
  market_sale_price_eur?: number | null;
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
  /** Cláusulas que la plantilla oficial aún muestra pero que la actividad ya da por fichadas. */
  taken?: ClauseBoardRow[];
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
  /** Valor diario de tu plantilla actual (fotos de precio, últimos 14 días). */
  value_history?: Array<{ day: string; value_eur: number; coverage?: number | null }>;
  clause_lock_timezone?: string | null;
  clause_lock_note?: string | null;
  ratio_mercado?: number | null;
  capitan_seguro?: CapitanPick | null;
  capitan_remontada?: CapitanPick | null;
  plan_fichajes?: PlanFichajes | null;
  ventas_forzadas?: VentaForzada[];
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

/** Un titular del once proyectado, con lo justo para cruzar onces. */
export type LeagueXiPlayer = {
  player_id?: string | null;
  name?: string | null;
  position?: string | null;
  club?: string | null;
  image_url?: string | null;
  expected_points?: number | null;
};

export type LeagueProjection = {
  xi?: LeagueXiPlayer[];
  expected_points?: number | null;
  ceiling_points?: number | null;
  formation?: string | null;
  players_available?: number | null;
  gaps?: string[];
  /** El once no llega a 11: la plantilla es corta y los huecos puntúan 0. */
  partial?: boolean;
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

export type LeagueFormRound = { round: number; points: number; rank: number };

export type LeagueFormRow = {
  team_id?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  is_self?: boolean;
  rounds: LeagueFormRound[];
  /** Media de las últimas jornadas. */
  recent_avg: number;
  total: number;
  best: number;
  /** Última jornada menos la media de las anteriores. `null` con una sola. */
  trend: number | null;
  form_rank: number;
};

/** Mi puesto en una jornada contra la línea del 4.º (el corte de la multa). */
export type LeagueMyRound = {
  round: number;
  points: number;
  rank: number;
  /** Puntos del 4.º: la línea que hay que igualar o superar. */
  cutoff: number;
  /** Mis puntos menos los del corte. */
  gap: number;
  in_top4: boolean;
  tied_at_cutoff: boolean;
  leader: number;
  field: number;
};

export type LeagueFormPayload = ApiError & {
  ok?: boolean;
  my_rounds?: LeagueMyRound[];
  /** De dónde sale cada jornada: premios de la actividad o el respaldo manual. */
  sources?: Record<string, "actividad" | "manual">;
  top_n?: number;
  rounds?: number[];
  recent_window?: number;
  rows?: LeagueFormRow[];
  unmatched?: string[];
};

export type Top4Manager = {
  team_id?: string | null;
  manager_name?: string | null;
  is_self?: boolean;
  expected_points: number;
  has_xp: boolean;
  player_count: number;
  void: boolean;
  p_top4: number;
};

export type Top4Scenario = {
  missing_players: number;
  fill_xp: number;
  expected_points: number;
  p_top4: number;
  cutoff_median: number;
  /** Positivo = faltan xP para el corte; negativo = vas por encima. */
  xp_gap_to_cutoff: number;
  expected_rank: number;
};

export type Top4Payload = ApiError & {
  ok?: boolean;
  top_n?: number;
  p_top4?: number;
  /** Con menos de 11 jugadores la jornada entera puntúa 0. */
  void?: boolean;
  player_count?: number;
  expected_points?: number;
  cutoff_median?: number;
  cutoff_range?: [number, number];
  xp_gap_to_cutoff?: number;
  expected_rank?: number;
  p_win?: number;
  if_completed?: Top4Scenario | null;
  managers?: Top4Manager[];
  calibration?: { sigma: number; rounds_used: number; calibrated: boolean };
  is_stale?: boolean;
  photo_age_seconds?: number | null;
};

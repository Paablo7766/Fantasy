// Auditoría: calibración del motor, salud de datos y uso de API.
import type { ApiError, PhotoMeta } from "./common";

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
    suficiente?: boolean;
    solo_pujas_propias?: boolean;
    bins?: Array<{
      lo?: number;
      hi?: number;
      count?: number;
      mean_predicted?: number | null;
      observed_rate?: number | null;
    }>;
  } | null;
  plan_stability?: {
    dias_con_plan?: number;
    pares_comparados?: number;
    cambio_medio?: number | null;
    planes_nuevos_enteros?: number;
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

export type PostMortemJugador = {
  player_id?: string;
  nombre?: string;
  position?: string | null;
  puntos?: number | null;
};

export type PostMortemFuga = {
  disponible?: boolean;
  motivo?: string | null;
  detalle?: string | null;
  puntos_once?: number | null;
  puntos_maximos?: number | null;
  fuga?: number | null;
  formacion_optima?: string | null;
  dejados_fuera?: PostMortemJugador[];
  sobraban?: PostMortemJugador[];
};

export type PostMortemBloque = {
  valor?: number | null;
  caja?: number | null;
  puntos?: number | null;
};

export type PostMortemTrading = {
  disponible?: boolean;
  motivo?: string | null;
  detalle?: string | null;
  snapshot_day?: string | null;
  snapshot_es_lunes?: boolean;
  operaciones?: number;
  compras_eur?: number;
  ventas_eur?: number;
  valores_congelados?: number;
  hoy?: PostMortemBloque;
  sin_operar?: PostMortemBloque;
  delta_valor?: number | null;
  delta_caja?: number | null;
  delta_puntos?: number | null;
};

export type PostMortemPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  command?: string;
  es_lunes?: boolean;
  hoy?: string;
  jornada?: string | null;
  once_fuente?: "guardado" | "recomendado" | "ninguno" | string;
  fuga?: PostMortemFuga;
  trading?: PostMortemTrading;
  snapshot_guardado?: { day?: string; nuevo?: boolean } | null;
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

// Informe del modelo (/api/laboratorio/modelo): fuentes, mercado frente a
// modelo, goleadores, histórico guardado y modo sombra. ``text`` es el mismo
// informe en texto plano para pegarlo en una conversación.
export type ModelSourceRow = {
  id: string;
  label: string;
  state: "ok" | "respaldo" | "fallo" | string;
  count?: number | null;
  source?: string | null;
  detail?: string | null;
};

export type ModelMatchSide = {
  club: string;
  lambda_for?: number | null;
  p_cs?: number | null;
  predicted_score?: string | null;
};

export type ModelMatchRow = {
  match_key: string;
  kickoff?: string | null;
  home?: ModelMatchSide | null;
  away?: ModelMatchSide | null;
  market_weight?: number | null;
  market?: {
    odds_1x2: [number, number, number];
    p_home: number;
    p_draw: number;
    p_away: number;
    lambda_home?: number | null;
    lambda_away?: number | null;
    captured_day?: string | null;
    days_stored?: number | null;
  } | null;
};

export type ModelScorerRow = {
  player_id: string;
  name: string;
  club?: string | null;
  position?: string | null;
  mine: boolean;
  price?: number | null;
  market_p?: number | null;
  own_p?: number | null;
  gap?: number | null;
  match_key: string;
};

export type ModelHistoryRow = {
  jornada: string;
  players: number;
  evaluated: number;
  mae?: number | null;
  xi: number;
  days_logged: number;
};

export type ModelScoreRow = {
  id: string;
  label: string;
  measure: string;
  value: string;
  baseline?: string | null;
  n: number;
  verdict: "mejor" | "peor" | "pocos_datos" | "sin_medir";
  note?: string | null;
};

export type ModelShadowItem = {
  id: string;
  label: string;
  state: string;
  progress: number;
  progress_text: string;
  rule: string;
};

export type ModelReportPayload = ApiError & PhotoMeta & {
  ok?: boolean;
  generated_at?: string;
  dashboard_at?: string | null;
  league_id?: string | null;
  jornada?: string | null;
  sources?: ModelSourceRow[];
  matches?: ModelMatchRow[];
  scorers?: { rows: ModelScorerRow[]; linked: number; listed: number };
  history?: { jornadas: ModelHistoryRow[]; odds_days: number; odds_matches: number; scorer_rows: number };
  scoreboard?: ModelScoreRow[];
  shadow?: ModelShadowItem[];
  text?: string;
};

// Previa de la jornada (/api/laboratorio/previa): TOP, Apuesta y No recomendable
// por partido, ediciones congeladas y evaluación contra los puntos reales.
export type PreviaPick = {
  player_id?: string | null;
  name?: string | null;
  club?: string | null;
  position?: string | null;
  score: number;
  mean: number;
  availability: number;
  availability_source?: string | null;
  owner?: string | null;
  mine?: boolean;
  on_market?: boolean;
  price?: number | null;
};

export type PreviaMatch = {
  match_key: string;
  home: string;
  away: string;
  kickoff?: string | null;
  lambda_home?: number | null;
  lambda_away?: number | null;
  source?: string | null;
  top: PreviaPick[];
  apuesta: PreviaPick[];
  no_recomendable: PreviaPick[];
  bajas: PreviaPick[];
  naive_top: PreviaPick[];
  mine: PreviaPick[];
  market_buys: PreviaPick[];
  players_scored: number;
};

export type PreviaEdition = {
  jornada: string | null;
  edition: "martes" | "jueves" | string;
  generated_at?: string;
  rule?: string;
  matches: PreviaMatch[];
  universe?: number;
  frozen_eligible?: boolean;
};

export type PreviaEvalCategory = { n: number; missing: number; mean: number | null };

export type PreviaEvalRow = {
  jornada: string;
  edition?: string | null;
  top: PreviaEvalCategory;
  apuesta: PreviaEvalCategory;
  no_recomendable: PreviaEvalCategory;
  naive_top: PreviaEvalCategory;
};

export type PreviaPayload = {
  ok?: boolean;
  error?: { message?: string };
  dashboard_at?: string | null;
  live?: PreviaEdition;
  frozen_now?: boolean;
  editions?: PreviaEdition[];
  evaluation?: PreviaEvalRow[];
};

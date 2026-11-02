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

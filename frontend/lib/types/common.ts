// Tipos comunes de todas las respuestas de la API.

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
  /** Cuándo quedó guardada la foto rápida. Permite pintarla antes de que acabe la completa. */
  core_saved_at?: string | null;
  error?: ApiError["error"];
};
